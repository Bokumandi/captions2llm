#!/usr/bin/env python3
"""Subtitle-only batch orchestration behind the Windows subsdown launchers."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from urllib.parse import parse_qs, urlencode, urlsplit

from common import VERSION, atomic_write_json, safe_filename, sha256
from simplesrt import SimpleSrt, process_srt

class ItemUnavailable(Exception):
    """The selected video or subtitle track is unavailable."""

def now():
    return datetime.now(timezone.utc).isoformat()

def youtube_url(value):
    parsed = urlsplit(value.strip())
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('Expected a public YouTube URL without credentials')
    if host not in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtu.be'):
        raise ValueError('Only YouTube URLs are supported')
    query = parse_qs(parsed.query)
    video = parsed.path.strip('/').split('/')[0] if host == 'youtu.be' else query.get('v', [''])[0]
    if parsed.path.startswith(('/shorts/', '/live/', '/embed/')):
        video = parsed.path.split('/')[2]
    playlist = query.get('list', [''])[0]
    if video and not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('Invalid YouTube video ID')
    if playlist and not re.fullmatch(r'[A-Za-z0-9_-]+', playlist):
        raise ValueError('Invalid playlist ID')
    if not video and not playlist:
        raise ValueError('Expected a video or playlist URL')
    return 'https://www.youtube.com/' + ('watch?' if video else 'playlist?') + urlencode(
        {**({'v': video} if video else {}), **({'list': playlist} if playlist else {})})

def command(executable):
    resolved = shutil.which(executable)
    if not resolved:
        candidate = Path(executable).expanduser()
        if candidate.is_file():
            resolved = str(candidate.resolve())
    if not resolved:
        raise ValueError(f'Executable not found: {executable}. Install it explicitly or pass its path.')
    return [sys.executable, '-X', 'utf8', resolved] if str(resolved).endswith('.py') else [resolved]

def invoke(executable, arguments, *, timeout=180):
    try:
        result = subprocess.run([*executable, *arguments], capture_output=True, text=True,
                                encoding='utf-8', errors='replace', timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Cannot execute {Path(executable[-1]).name}: {type(exc).__name__}') from exc
    if result.returncode:
        # Raw stderr can contain signed URLs and local credentials: keep it out of exports.
        raise RuntimeError(f'{Path(executable[-1]).name} failed (exit {result.returncode}); '
                           'check video availability, network access and installed tool versions')
    return result.stdout

def metadata(executable, url, *, flat=False):
    arguments = ['--ignore-config', '--no-cache-dir', '--skip-download', '--no-warnings',
                 '--encoding', 'utf-8', '--dump-single-json']
    arguments += ['--flat-playlist'] if flat else ['--no-playlist']
    data = json.loads(invoke(executable, [*arguments, url]))
    if not isinstance(data, dict):
        raise ValueError('yt-dlp returned invalid video metadata')
    return data

def legacy_selection(arguments):
    """Allow subtitle selection only; never forward execution or output options."""
    result = {}
    switches = {'--write-subs': ('manual', True), '--no-write-subs': ('manual', False),
                '--write-auto-subs': ('auto', True), '--no-write-auto-subs': ('auto', False)}
    values = {'--sub-langs', '--sub-format', '--convert-subs'}
    index = 0
    while index < len(arguments):
        option, separator, attached = arguments[index].partition('=')
        if option in switches and not separator:
            key, value = switches[option]
            result[key] = value
        elif option in values:
            index += not bool(separator)
            if not separator and index >= len(arguments):
                raise ValueError(f'Missing value for {option}')
            value = attached if separator else arguments[index]
            if option == '--sub-langs':
                result['language'] = value
            elif option == '--convert-subs' and value != 'srt':
                raise ValueError('Exports require --convert-subs srt')
            elif option == '--sub-format':
                if not value:
                    raise ValueError('Empty subtitle format')
                result['format'] = value
        else:
            raise ValueError(f'Unsupported yt-dlp option: {option}; only subtitle selection is accepted')
        index += 1
    return result

def choose_tracks(info, selection):
    groups = []
    if selection['manual']:
        groups.append(('manual', info.get('subtitles') or {}))
    if selection['auto']:
        groups.append(('auto', info.get('automatic_captions') or {}))
    selected = []
    requested = selection['language']
    original_keys = [key for key in (info.get('automatic_captions') or {}) if key.endswith('-orig')]
    native_language = original_keys[0][:-5] if len(original_keys) == 1 else str(info.get('language') or '').replace('_', '-')
    for kind, available in groups:
        if requested == 'original':
            language = native_language
            base = language.split('-')[0]
            originals = [key for key in available if key.endswith('-orig')]
            candidates = [language + '-orig', base + '-orig'] if originals else [language, base]
            key = originals[0] if len(originals) == 1 else next((candidate for candidate in candidates if candidate and candidate in available), None)
            matches = [key] if key else []
        else:
            patterns = requested.split(',')
            positive = [p for p in patterns if not p.startswith('-')]
            negative = [p[1:] for p in patterns if p.startswith('-')]
            for pattern in positive + negative:
                if pattern != 'all':
                    re.compile(pattern)
            matches = [key for key in available
                       if any(p == 'all' or re.fullmatch(p, key) for p in positive)
                       and not any(p == 'all' or re.fullmatch(p, key) for p in negative)]
        for key in matches:
            tracks = available[key]
            translated = any('tlang=' in str(track.get('url', '')) for track in tracks)
            if requested == 'original' and translated:
                continue
            selected.append((kind, key, translated))
    if not selected:
        raise ItemUnavailable('Requested subtitle language/source is unavailable; no language fallback used')
    return selected

def export_record(info, source, cleaned, language, kind, translated, selection, versions, playlist):
    segments = []
    for index, cue in enumerate(SimpleSrt(cleaned.read_text(encoding='utf-8-sig')).subs, 1):
        # Format with the cleaner to keep hours and millisecond handling consistent.
        from simplesrt import Subtitle
        segments.append({'index': index, 'start': Subtitle._print_duration(cue.start),
                         'end': Subtitle._print_duration(cue.end),
                         'text': ' '.join(cue.text.split())})
    if not segments:
        raise ValueError('Cleaner produced an empty transcript')
    video_id = info['id']
    canonical = 'https://www.youtube.com/watch?v=' + video_id
    return {
        'type': 'YouTubeSubtitleTranscript', 'schema_version': 'subsdown.v4', 'created_at': now(),
        'video': {'title': info.get('title') or video_id, 'channel': info.get('channel') or info.get('uploader') or 'unknown_channel',
                  'id': video_id, 'url_clean': canonical, 'webpage_url_original': canonical,
                  'duration_seconds': info.get('duration'), 'upload_date': info.get('upload_date')},
        'playlist': playlist,
        'subtitle': {'language': language, 'origin': 'youtube auto-generated captions' if kind == 'auto' else 'youtube manual captions',
                     'kind': kind, 'translated': translated, 'raw_file_name': source.name,
                     'clean_srt_file': 'transcript.srt', 'requested_yt_dlp_args': selection['legacy'],
                     'default_used': not selection['legacy']},
        'output_container': {},
        'processing': {'downloader': 'yt-dlp', 'cleaner': 'srt_fixer_cli.py', 'srt_parser': 'simplesrt.py',
                       'temporary_paths_shortened': True, 'temp_files_removed_on_success': not selection['keep_work'],
                       'product_version': VERSION, 'tool_versions': versions, 'raw_sha256': sha256(source)},
        'transcript': {'segment_count': len(segments), 'plain_text': '\n'.join(s['text'] for s in segments), 'segments': segments},
        'output_files': {'json': 'transcript.json', 'markdown': 'transcript.md', 'srt': 'transcript.srt'}}

def within(path, root):
    path = Path(path).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError('Output escapes the selected output root')
    return path

def verified_exports(item, root):
    entries = item.get('exports')
    if not isinstance(entries, list) or not entries or len(entries) % 3:
        return False
    try:
        groups = {}
        paths = set()
        for entry in entries:
            relative = Path(entry['path'])
            path = within(root / relative, root)
            if relative.is_absolute() or path in paths or not path.is_file() or path.is_symlink():
                return False
            if sha256(path) != entry['sha256']:
                return False
            paths.add(path)
            groups.setdefault(path.parent, []).append(path)
        for parent, files in groups.items():
            if {path.name for path in files} != {'transcript.json', 'transcript.md', 'transcript.srt'}:
                return False
            data = json.loads((parent / 'transcript.json').read_text(encoding='utf-8'))
            if (data.get('type') != 'YouTubeSubtitleTranscript' or
                data.get('schema_version') != 'subsdown.v4' or
                not data.get('transcript', {}).get('segments') or
                data.get('transcript', {}).get('segment_count') != len(data['transcript']['segments'])):
                return False
            canonical = youtube_url(data['video']['url_clean'])
            if parse_qs(urlsplit(canonical).query).get('v', [''])[0] != data['video']['id']:
                return False
            if item.get('url') and canonical != youtube_url(item['url']):
                return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False

def publish_track(info, track, stage, output_root, selection, versions, playlist):
    kind, language, translated = track
    downloaded = stage / 'raw'
    downloaded.mkdir()
    executable = selection['_command']
    arguments = ['--ignore-config', '--no-cache-dir', '--skip-download', '--no-playlist', '--no-warnings',
                 '--encoding', 'utf-8', '--no-mtime', '--no-overwrites', '--sub-format', selection.get('format', 'srt/vtt/best'),
                 '--convert-subs', 'srt', '--ffmpeg-location', selection['_ffmpeg'], '--sub-langs', re.escape(language),
                 '--write-auto-subs' if kind == 'auto' else '--write-subs',
                 '--no-write-subs' if kind == 'auto' else '--no-write-auto-subs',
                 '--output', str(downloaded / '%(id)s.%(ext)s'),
                 'https://www.youtube.com/watch?v=' + info['id']]
    invoke(executable, arguments)
    sources = list(downloaded.glob('*.srt'))
    if len(sources) != 1:
        raise ItemUnavailable('Expected one selected SRT subtitle track')
    # A complete export directory becomes visible with one rename.
    bundle = stage / 'bundle'
    bundle.mkdir()
    cleaned = bundle / 'transcript.srt'
    process_srt(str(sources[0]), str(cleaned), manual=kind == 'manual')
    record = export_record(info, sources[0], cleaned, language, kind, translated, selection, versions, playlist)
    channel_dir = output_root / safe_filename(record['video']['channel'], 32)
    group = playlist.get('title') or record['video']['title']
    identity = playlist.get('id') or info['id']
    group_dir = channel_dir / (safe_filename(group, 40) + ' [' + safe_filename(identity, 36) + ']')
    group_dir = within(group_dir, output_root)
    leaf = info['id'] + '-' + safe_filename(language, 24) + '-' + kind
    group_dir.mkdir(parents=True, exist_ok=True)
    destination = group_dir / leaf
    serial = 2
    while destination.exists():
        destination = group_dir / f'{leaf} ({serial})'
        serial += 1
    if len(str(destination / 'transcript.json')) > 240:
        raise ValueError('Output path is too long; choose a shorter OutRoot')
    record['output_container'] = {'channel_folder': channel_dir.name, 'content_folder': group_dir.name,
                                  'item_folder': destination.name, 'folder_pattern': '[channel]/[playlist-or-video]/[item]'}
    atomic_write_json(bundle / 'transcript.json', record)
    markdown = '# ' + record['video']['title'] + '\n\n' + '\n'.join([
        '- Channel: ' + record['video']['channel'], '- URL: ' + record['video']['url_clean'],
        '- Language: ' + language, '- Source: ' + kind, '- Automatic translation: ' + str(translated),
        '', '## Transcript', '', *[f"[{s['start']} --> {s['end']}] {s['text']}" for s in record['transcript']['segments']]])
    from common import atomic_write_text
    atomic_write_text(bundle / 'transcript.md', markdown + '\n')
    os.rename(bundle, destination)
    return [{'path': str(file.relative_to(output_root)), 'sha256': sha256(file)}
            for file in sorted(destination.iterdir())]

def run(args):
    if args.resume:
        previous = json.loads(Path(args.resume).read_text(encoding='utf-8-sig'))
        if previous.get('schema_version') != 'subsdown.run.v1':
            raise ValueError('Unsupported resume manifest')
        if args.url or args.input_file or args.language or args.manual or args.subtitle_args or args.current_video_only or args.process_all:
            raise ValueError('Resume uses the saved input/selection; do not supply input or selection overrides')
        root = Path(previous['output_root']).resolve()
        if args.out_root and Path(args.out_root).resolve() != root:
            raise ValueError('Resume must use the original OutRoot')
        selection = previous['selection']
        targets = previous['targets']
        for target in targets:
            target['url'] = youtube_url(target['url'])
        old_items = {item['key']: item for item in previous.get('recovery_items', previous['items'])}
        saved_queue = previous.get('expanded_targets', [])
        enumeration_targets = previous.get('enumeration_targets', targets if not saved_queue else [])
        for target in saved_queue + enumeration_targets:
            target['url'] = youtube_url(target['url'])
    else:
        if bool(args.url) == bool(args.input_file):
            raise ValueError('Specify exactly one URL or -InputFile')
        urls = [args.url] if args.url else [line.strip() for line in Path(args.input_file).read_text(encoding='utf-8-sig').splitlines()
                                         if line.strip() and not line.lstrip().startswith('#')]
        urls = list(dict.fromkeys(youtube_url(url) for url in urls))
        if not urls:
            raise ValueError('Input list is empty')
        root = Path(args.out_root or 'subsdown_output').expanduser().resolve()
        custom = legacy_selection(args.subtitle_args)
        selection = {'language': custom.get('language', args.language or 'original'),
                     'manual': custom.get('manual', args.manual), 'auto': custom.get('auto', not (custom.get('manual') or args.manual)),
                     'legacy': args.subtitle_args, 'current_video_only': args.current_video_only,
                     'keep_work': args.keep_work, 'process_all': args.process_all, 'format': custom.get('format', 'srt/vtt/best')}
        if not selection['manual'] and not selection['auto']:
            raise ValueError('At least one subtitle source must be enabled')
        targets = [{'url': url, 'playlist': {}} for url in urls]
        old_items = {}
        saved_queue = []
        enumeration_targets = targets
    if selection['language'] != 'original':
        try:
            for pattern in selection['language'].split(','):
                if not pattern or pattern == '-':
                    raise ValueError('Empty subtitle language pattern')
                if pattern.lstrip('-') != 'all':
                    re.compile(pattern[1:] if pattern.startswith('-') else pattern)
        except re.error as exc:
            raise ValueError('Invalid subtitle language expression') from exc
    if len(str(root)) > 105:
        raise ValueError('Choose an OutRoot of at most 105 characters for Windows path compatibility')
    executable = command(args.yt_dlp)
    ffmpeg = command(args.ffmpeg)
    versions = {'subsdown': VERSION, 'python': sys.version.split()[0],
                'yt_dlp': invoke(executable, ['--version'], timeout=30).strip().splitlines()[0],
                'ffmpeg': invoke(ffmpeg, ['-version'], timeout=30).strip().splitlines()[0]}
    root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid.uuid4().hex[:8]
    manifest_path = root / '.runs' / (run_id + '.json')
    manifest = {'schema_version': 'subsdown.run.v1', 'product_version': VERSION, 'created_at': now(),
                'output_root': str(root), 'selection': selection.copy(), 'tool_versions': versions,
                'targets': targets.copy(), 'expanded_targets': saved_queue.copy(), 'enumeration_targets': enumeration_targets.copy(), 'items': []}
    def checkpoint():
        inventory = old_items.copy()
        inventory.update({item['key']: item for item in manifest['items']})
        manifest['recovery_items'] = list(inventory.values())
        manifest['updated_at'] = now()
        atomic_write_json(manifest_path, manifest, overwrite=True)
    checkpoint()
    # Keep the executable out of persisted settings.
    selection = selection.copy()
    selection['_command'] = executable
    selection['_ffmpeg'] = ffmpeg[-1]
    selection['keep_work'] = args.keep_work or selection['keep_work']
    queue = saved_queue.copy()
    remaining_enumeration = []
    for target in enumeration_targets:
        try:
            data = metadata(executable, target['url'], flat=not selection['current_video_only'])
            entries = data.get('entries')
            if isinstance(entries, list):
                playlist = {'title': data.get('title'), 'id': data.get('id'), 'source_url': target['url']}
                for number, entry in enumerate(entries, 1):
                    if entry and re.fullmatch(r'[A-Za-z0-9_-]{11}', str(entry.get('id', ''))):
                        queue.append({'url': 'https://www.youtube.com/watch?v=' + entry['id'],
                                      'playlist': {**playlist, 'index': entry.get('playlist_index') or number}})
                    else:
                        if target not in remaining_enumeration:
                            remaining_enumeration.append(target)
                        manifest['items'].append({'key': target['url'] + '#' + str(number), 'status': 'unavailable',
                                                  'message': 'Playlist entry unavailable', 'exports': []})
            else:
                video_id = str(data.get('id', ''))
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    raise ValueError('Invalid video identity returned by yt-dlp')
                queue.append({'url': 'https://www.youtube.com/watch?v=' + video_id, 'playlist': target.get('playlist') or {}})
        except (RuntimeError, ValueError) as exc:
            remaining_enumeration.append(target)
            manifest['items'].append({'key': target['url'], 'status': 'failed', 'message': str(exc), 'exports': []})
    queue = list({target['url'] + '|' + str(target['playlist'].get('id') or ''): target for target in queue}.values())
    manifest['enumeration_targets'] = remaining_enumeration
    manifest['expanded_targets'] = queue
    checkpoint()
    for target in queue:
        item_key = target['url'] + '|' + str(target['playlist'].get('id') or '')
        old = old_items.get(item_key)
        if old and old.get('status') == 'success' and verified_exports(old, root):
            manifest['items'].append({**old, 'reused': True})
            checkpoint()
            print('Reused: ' + target['url'])
            continue
        item = {'key': item_key, 'url': target['url'], 'status': 'failed', 'exports': []}
        if old:
            old_groups = {}
            for entry in old.get('exports', []):
                old_groups.setdefault(str(Path(entry['path']).parent), []).append(entry)
            for group in old_groups.values():
                if verified_exports({'exports': group, 'url': target['url']}, root):
                    item['exports'].extend(group)
        manifest['items'].append(item)
        work = None
        try:
            info = metadata(executable, target['url'])
            if not re.fullmatch(r'[A-Za-z0-9_-]{11}', str(info.get('id', ''))):
                raise ValueError('Invalid video identity returned by yt-dlp')
            expected_id = parse_qs(urlsplit(target['url']).query).get('v', [''])[0]
            if expected_id and info['id'] != expected_id:
                raise ValueError('Video identity does not match the requested URL')
            tracks = choose_tracks(info, selection)
            parent = root / '_tmp'
            parent.mkdir(exist_ok=True)
            work = Path(tempfile.mkdtemp(prefix=run_id + '-', dir=parent)).resolve()
            for number, track in enumerate(tracks):
                track_work = work / str(number)
                track_work.mkdir()
                reused = []
                if old:
                    for entry in old.get('exports', []):
                        if not entry['path'].endswith('.json'):
                            continue
                        group = [part for part in old['exports'] if Path(part['path']).parent == Path(entry['path']).parent]
                        if len(group) != 3 or not verified_exports({'exports': group}, root):
                            continue
                        prior = json.loads((root / entry['path']).read_text(encoding='utf-8'))
                        if (prior.get('video', {}).get('id') == info['id'] and
                            prior.get('subtitle', {}).get('kind') == track[0] and
                            prior.get('subtitle', {}).get('language') == track[1]):
                            reused = group
                            break
                if not reused:
                    item['exports'].extend(publish_track(info, track, track_work, root, selection, versions, target['playlist']))
                checkpoint()
            item['status'] = 'success'
            print('Exported: ' + info['id'])
        except ItemUnavailable as exc:
            item.update(status='unavailable', message=str(exc))
        except (RuntimeError, ValueError, OSError) as exc:
            item.update(status='failed', message=str(exc))
        finally:
            if work and item['status'] == 'success' and not selection['keep_work']:
                resolved = work.resolve()
                expected_parent = (root / '_tmp').resolve()
                if resolved.parent != expected_parent or not resolved.name.startswith(run_id + '-') or work.is_symlink():
                    raise ValueError('Refusing unexpected temporary cleanup path')
                shutil.rmtree(resolved)
            checkpoint()
    counts = {status: sum(item['status'] == status for item in manifest['items'])
              for status in ('success', 'unavailable', 'failed')}
    manifest['summary'] = counts
    exit_code = 0 if counts['success'] and not (counts['unavailable'] or counts['failed']) else 2
    if args.merge:
        from subsmerge import merge_files
        paths = [root / entry['path'] for item in manifest['items'] if verified_exports(item, root)
                 for entry in item['exports'] if entry['path'].endswith('.json')]
        merged_path = root / ('subsmerge-' + run_id + '.json')
        if not paths or merge_files(paths, root, merged_path):
            manifest['merge_error'] = 'Current-run fusion failed or no successful transcript was available'
            exit_code = 2
        else:
            manifest['merged_output'] = str(merged_path.relative_to(root))
    manifest['exit_code'] = exit_code
    checkpoint()
    print('Summary: ' + json.dumps(counts))
    print('Manifest: ' + str(manifest_path))
    return exit_code

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url', nargs='?')
    parser.add_argument('--input-file')
    parser.add_argument('--out-root')
    parser.add_argument('--language')
    parser.add_argument('--manual', action='store_true')
    parser.add_argument('--current-video-only', action='store_true')
    parser.add_argument('--keep-work', action='store_true')
    parser.add_argument('--process-all', action='store_true')
    parser.add_argument('--resume')
    parser.add_argument('--merge', action='store_true')
    parser.add_argument('--yt-dlp', default='yt-dlp')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--subtitle-args', nargs=argparse.REMAINDER, default=[])
    args = parser.parse_args()
    try:
        return run(args)
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 1

if __name__ == '__main__':
    raise SystemExit(main())
