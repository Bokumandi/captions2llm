#!/usr/bin/env python3
"""Subtitle-only batch orchestration behind the Windows subsdown launchers."""
from __future__ import annotations
import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import json
from itertools import islice
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
        path = parsed.path.rstrip('/')
        channel = re.fullmatch(r'(/@[^/\s?#]+|/(?:user|c)/[^/\s?#]+|/channel/UC[A-Za-z0-9_-]{22})(/(?:videos|shorts|streams))?', path)
        if host != 'youtu.be' and channel:
            return 'https://www.youtube.com' + channel.group(1) + (channel.group(2) or '')
        raise ValueError('Expected a video, playlist or public channel URL')
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

def metadata(executable, url, *, flat=False, playlist_end=None):
    arguments = ['--ignore-config', '--no-cache-dir', '--skip-download', '--no-warnings',
                 '--encoding', 'utf-8', '--dump-single-json']
    arguments += ['--flat-playlist'] if flat else ['--no-playlist']
    if flat and playlist_end is not None:
        arguments += ['--playlist-end', str(playlist_end)]
    data = json.loads(invoke(executable, [*arguments, url]))
    if not isinstance(data, dict):
        raise ValueError('yt-dlp returned invalid video metadata')
    return data

def channel_base(url):
    """Return the public channel identity without an explicit upload tab."""
    path = urlsplit(url).path.rstrip('/')
    return re.sub(r'/(?:videos|shorts|streams)$', '', path)


def collection_entries(executable, data, source_url, *, playlist_end=None):
    """Flatten public upload tabs while retaining the root collection identity.

    Follow only upload-tab links belonging to the requested channel or an alias
    reported by its metadata. Never follow arbitrary collection or account URLs.
    """
    channel_source = not parse_qs(urlsplit(source_url).query).get('list')
    aliases = {channel_base(source_url)}
    for key in ('channel_url', 'uploader_url'):
        if data.get(key):
            try:
                aliases.add(channel_base(youtube_url(data[key])))
            except ValueError:
                pass
    for key in ('channel_id', 'id'):
        identity = str(data.get(key, ''))
        if re.fullmatch(r'UC[A-Za-z0-9_-]{22}', identity):
            aliases.add('/channel/' + identity)
    visited = {source_url}

    def walk(entries, depth):
        if depth > 8:
            raise ValueError('Nested upload collection exceeds the supported depth')
        for entry in entries:
            if entry is None:
                yield None
                continue
            if not isinstance(entry, dict):
                raise ValueError('Invalid nested upload entry')
            if isinstance(entry.get('entries'), list):
                yield from walk(entry['entries'], depth + 1)
            elif re.fullmatch(r'[A-Za-z0-9_-]{11}', str(entry.get('id', ''))):
                yield entry
            elif entry.get('url'):
                linked = youtube_url(entry['url'])
                video_id = parse_qs(urlsplit(linked).query).get('v', [''])[0]
                if video_id:
                    yield {**entry, 'id': video_id}
                    continue
                path = urlsplit(linked).path.rstrip('/')
                if (not channel_source or channel_base(linked) not in aliases or
                    not path.endswith(('/videos', '/shorts', '/streams'))):
                    raise ValueError('Unsupported nested collection URL in upload enumeration')
                if linked in visited:
                    raise ValueError('Cyclic upload-tab enumeration')
                visited.add(linked)
                nested = metadata(executable, linked, flat=True, playlist_end=playlist_end)
                if not isinstance(nested.get('entries'), list):
                    raise ValueError('Upload tab did not return a collection')
                yield from walk(nested['entries'], depth + 1)
            elif entry.get('_type') in ('playlist', 'multi_video', 'url', 'url_transparent'):
                raise ValueError('Nested collection is missing a supported upload-tab URL')
            else:
                yield None

    yield from walk(data['entries'], 0)


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

def result_record():
    return {'schema_version': 'subsdown.result.v1', 'product_version': VERSION,
            'exit_code': 1, 'manifest_path': None, 'output_root': None,
            'summary': {'success': 0, 'unavailable': 0, 'failed': 0},
            'merged_json': None, 'merged_markdown': None,
            'index_json': None, 'index_markdown': None}


def run(args):
    args.result = result_record()
    max_videos = getattr(args, 'max_videos', None)
    text_only = getattr(args, 'text_only', False)
    if text_only and not args.merge:
        raise ValueError('--text-only requires --merge')
    if max_videos is not None and (isinstance(max_videos, bool) or not isinstance(max_videos, int) or max_videos < 1):
        raise ValueError('--max-videos must be a positive integer')
    if args.resume:
        previous = json.loads(Path(args.resume).read_text(encoding='utf-8-sig'))
        if previous.get('schema_version') != 'subsdown.run.v1':
            raise ValueError('Unsupported resume manifest')
        if args.url or args.input_file or args.language or args.manual or args.subtitle_args or args.current_video_only or args.process_all or max_videos is not None:
            raise ValueError('Resume uses the saved input/selection; do not supply input or selection overrides')
        root = Path(previous['output_root']).resolve()
        if args.out_root and Path(args.out_root).resolve() != root:
            raise ValueError('Resume must use the original OutRoot')
        selection = previous['selection']
        max_videos = selection.get('max_videos')
        if max_videos is not None and (isinstance(max_videos, bool) or not isinstance(max_videos, int) or max_videos < 1):
            raise ValueError('Invalid saved max-videos scope')
        targets = previous['targets']
        for target in targets:
            target['url'] = youtube_url(target['url'])
        old_items = {item['key']: item for item in previous.get('recovery_items', previous['items'])}
        saved_queue = previous.get('expanded_targets', [])
        enumeration_targets = previous.get('enumeration_targets', targets if not saved_queue else [])
        for target in saved_queue + enumeration_targets:
            target['url'] = youtube_url(target['url'])
            if 'entry_end' in target:
                entry_end = target['entry_end']
                if (max_videos is None or isinstance(entry_end, bool) or not isinstance(entry_end, int)
                    or entry_end < 1 or entry_end > max_videos):
                    raise ValueError('Invalid saved upload enumeration scope')
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
                     'keep_work': args.keep_work, 'process_all': args.process_all, 'max_videos': max_videos, 'format': custom.get('format', 'srt/vtt/best')}
        if not selection['manual'] and not selection['auto']:
            raise ValueError('At least one subtitle source must be enabled')
        targets = [{'url': url, 'playlist': {}} for url in urls]
        old_items = {}
        saved_queue = []
        enumeration_targets = targets
    if selection['current_video_only'] and any(not parse_qs(urlsplit(target['url']).query) for target in targets):
        raise ValueError('--current-video-only cannot select a public channel')
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
    args.result.update(manifest_path=str(manifest_path), output_root=str(root))
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
    # A capped run keeps the first occurrence of each video across its inputs.
    # Missing source positions consume scope too; resume retries those positions
    # without widening the original selection.
    queue_keys = {target['url'] if max_videos else target['url'] + '|' + str(target['playlist'].get('id') or '')
                  for target in queue}
    selected_positions = len(queue_keys)
    remaining_enumeration = []
    for target in enumeration_targets:
        scoped_retry = max_videos is not None and 'entry_end' in target
        if max_videos is not None and selected_positions >= max_videos and not scoped_retry:
            break
        entry_end = target.get('entry_end') if scoped_retry else (max_videos - selected_positions if max_videos else None)
        inspected = 0
        unavailable = False
        try:
            data = metadata(executable, target['url'], flat=not selection['current_video_only'], playlist_end=entry_end)
            entries = data.get('entries')
            if isinstance(entries, list):
                playlist = {'title': data.get('title'), 'id': data.get('id'), 'source_url': target['url']}
                flattened = collection_entries(executable, data, target['url'], playlist_end=entry_end)
                if entry_end is not None:
                    flattened = islice(flattened, entry_end)
                for number, entry in enumerate(flattened, 1):
                    if max_videos is not None and selected_positions >= max_videos and not scoped_retry:
                        break
                    inspected = number
                    if isinstance(entry, dict) and re.fullmatch(r'[A-Za-z0-9_-]{11}', str(entry.get('id', ''))):
                        candidate = {'url': 'https://www.youtube.com/watch?v=' + entry['id'],
                                     'playlist': {**playlist, 'index': number if not parse_qs(urlsplit(target['url']).query).get('list') else entry.get('playlist_index') or number}}
                        key = candidate['url'] if max_videos else candidate['url'] + '|' + str(playlist.get('id') or '')
                        if key not in queue_keys:
                            queue.append(candidate)
                            queue_keys.add(key)
                        selected_positions += 1
                    else:
                        unavailable = True
                        selected_positions += 1
                        manifest['items'].append({'key': target['url'] + '#' + str(number), 'status': 'unavailable',
                                                  'message': 'Playlist entry unavailable', 'exports': []})
                if unavailable:
                    retry = target.copy()
                    if max_videos is not None:
                        retry['entry_end'] = inspected
                    remaining_enumeration.append(retry)
            else:
                video_id = str(data.get('id', ''))
                if not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id):
                    raise ValueError('Invalid video identity returned by yt-dlp')
                candidate = {'url': 'https://www.youtube.com/watch?v=' + video_id, 'playlist': target.get('playlist') or {}}
                key = candidate['url'] if max_videos else candidate['url'] + '|' + str(candidate['playlist'].get('id') or '')
                if key not in queue_keys:
                    queue.append(candidate)
                    queue_keys.add(key)
                    selected_positions += 1
        except (RuntimeError, ValueError) as exc:
            retry = target.copy()
            if max_videos is not None:
                retry['entry_end'] = entry_end
                selected_positions += entry_end
            remaining_enumeration.append(retry)
            manifest['items'].append({'key': target['url'], 'status': 'failed', 'message': str(exc), 'exports': []})
    if max_videos is not None:
        queue = queue[:max_videos]
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
        markdown_path = merged_path.with_suffix('.md')
        if not paths or merge_files(paths, root, merged_path, include_original=False,
                                    markdown_output=markdown_path, text_only=text_only):
            manifest['merge_error'] = 'Current-run fusion failed or no successful transcript was available'
            exit_code = 2
        else:
            manifest['merged_output'] = str(merged_path.relative_to(root))
            manifest['merged_markdown'] = str(markdown_path.relative_to(root))
    # Index only this run, including its gaps; never silently index older exports.
    try:
        from subsbatch import write_index
        indexed = write_index(root, root / ('subsindex-' + run_id + '.json'),
                              root / ('subsindex-' + run_id + '.md'), manifest=manifest)
        manifest['index_json'] = str(Path(indexed['index_json']).relative_to(root))
        manifest['index_markdown'] = str(Path(indexed['index_markdown']).relative_to(root))
        args.result.update(index_json=indexed['index_json'], index_markdown=indexed['index_markdown'])
        if any(indexed.get(key, 0) for key in ('gap_count', 'error_count', 'enumeration_pending')):
            exit_code = 2
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as exc:
        manifest['index_error'] = str(exc)
        args.result['index_error'] = str(exc)
        exit_code = 2
    manifest['exit_code'] = exit_code
    checkpoint()
    args.result.update(exit_code=exit_code, summary=counts,
                       merged_json=str(root / manifest['merged_output']) if 'merged_output' in manifest else None,
                       merged_markdown=str(root / manifest['merged_markdown']) if 'merged_markdown' in manifest else None)
    print('Summary: ' + json.dumps(counts))
    print('Manifest: ' + str(manifest_path))
    return exit_code

def main():
    class ResultParser(argparse.ArgumentParser):
        def error(self, message):
            raise ValueError(message)

    parser = ResultParser(description=__doc__)
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
    parser.add_argument('--text-only', action='store_true', help='With --merge, omit repeated segment text from combined outputs')
    parser.add_argument('--max-videos', type=int, help='Select at most N source video positions (unavailable positions count)')
    parser.add_argument('--json', action='store_true', help='Print one JSON result; send progress to stderr')
    parser.add_argument('--yt-dlp', default='yt-dlp')
    parser.add_argument('--ffmpeg', default='ffmpeg')
    parser.add_argument('--version', action='version', version=VERSION)
    parser.add_argument('--subtitle-args', nargs=argparse.REMAINDER, default=[])
    json_output = '--json' in sys.argv[1:]
    args = None
    result = result_record()
    try:
        args = parser.parse_args()
        json_output = args.json
        if json_output:
            with redirect_stdout(sys.stderr):
                exit_code = run(args)
        else:
            exit_code = run(args)
        result = args.result
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        exit_code = 1
        result = getattr(args, 'result', result)
        result.update(exit_code=exit_code, error=str(exc))
        print('ERROR: ' + str(exc), file=sys.stderr)
    if json_output:
        print(json.dumps(result, ensure_ascii=False))
    return exit_code

if __name__ == '__main__':
    raise SystemExit(main())
