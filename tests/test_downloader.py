"""Public downloader behavior through synthetic subprocesses and Windows launchers."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import common
import subsdown

ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / 'tests' / 'fake_ytdlp.py'
VIDEO = 'https://youtu.be/aaaaaaaaaaa'

class DownloaderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='sd-')
        self.root = Path(self.temp.name)
        self.output = self.root / 'out [test]'
    def tearDown(self):
        self.temp.cleanup()
    def cli(self, extra=(), expected=0, shell=None):
        if shell == 'cmd':
            command = ['cmd.exe', '/c', str(ROOT/'subsdown.cmd')]
        elif shell:
            command = [shell,'-NoProfile','-NonInteractive','-File',str(ROOT/'subsdown.ps1')]
        else:
            command = [sys.executable,'-X','utf8',str(ROOT/'subsdown.py')]
        if shell:
            command += ['-Python',sys.executable,'-YtDlp',str(FAKE),'-FFmpeg',str(FAKE),'-OutRoot',str(self.output)]
        else:
            command += ['--yt-dlp',str(FAKE),'--ffmpeg',str(FAKE),'--out-root',str(self.output)]
        result = subprocess.run(command+list(extra),capture_output=True,text=True,encoding='utf-8',errors='replace')
        self.assertEqual(result.returncode,expected,result.stdout+'\n'+result.stderr)
        return result
    def manifest(self):
        paths = list((self.output/'.runs').glob('*.json'))
        return json.loads(max(paths,key=lambda p:p.stat().st_mtime_ns).read_text(encoding='utf-8'))
    def test_original_auto_and_merge(self):
        self.cli([VIDEO,'--merge'])
        state=self.manifest()
        self.assertEqual(state['summary'],{'success':1,'failed':0,'unavailable':0})
        exported=next(self.output/p['path'] for p in state['items'][0]['exports'] if p['path'].endswith('.json'))
        data=json.loads(exported.read_text(encoding='utf-8'))
        self.assertEqual(data['subtitle']['language'],'fr-orig')
        self.assertEqual(data['subtitle']['kind'],'auto')
        self.assertFalse(data['subtitle']['translated'])
        self.assertIn('\n',data['transcript']['plain_text'])
        self.assertTrue(exported.with_suffix('.md').read_text(encoding='utf-8').startswith('# Demonstration é'))
        merged=json.loads((self.output/state['merged_output']).read_text(encoding='utf-8'))
        self.assertEqual(merged['item_count'],1)
        self.assertFalse(any((self.output/'_tmp').iterdir()))
    def test_repeat_preserves_first(self):
        self.cli([VIDEO])
        old={str(p):common.sha256(p) for p in self.output.rglob('transcript.*')}
        self.cli([VIDEO])
        for path, digest in old.items(): self.assertEqual(common.sha256(Path(path)),digest)
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),2)
    def test_resume_reuses_verified_exports(self):
        self.cli([VIDEO])
        manifest=next((self.output/'.runs').glob('*.json'))
        self.cli(['--resume',str(manifest),'--merge'])
        self.assertTrue(self.manifest()['items'][0]['reused'])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),1)
    def test_resume_retries_modified_export(self):
        self.cli([VIDEO])
        manifest=next((self.output/'.runs').glob('*.json'))
        next(self.output.rglob('transcript.md')).write_text('changed',encoding='utf-8')
        self.cli(['--resume',str(manifest)])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),2)
    def test_playlist_partial_retains_successes_and_retries(self):
        self.cli(['https://www.youtube.com/playlist?list=PL_SYNTHETIC','--merge'],expected=2)
        state=self.manifest()
        self.assertEqual(state['summary'],{'success':1,'unavailable':2,'failed':0})
        manifest=max((self.output/'.runs').glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
        self.cli(['--resume',str(manifest)],expected=2)
        self.assertEqual(self.manifest()['summary']['unavailable'],2)
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),1)
    def test_current_video_only_drops_playlist_from_reuse_identity(self):
        self.cli([VIDEO+'?list=PL_SYNTHETIC','--current-video-only'])
        manifest=next((self.output/'.runs').glob('*.json'))
        self.cli(['--resume',str(manifest)])
        self.assertTrue(self.manifest()['items'][0]['reused'])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),1)

    def test_list_and_manual(self):
        file=self.root/'links.txt'
        file.write_text('# comment\n'+VIDEO+'\n'+VIDEO+'\nhttps://youtu.be/ccccccccccc\n',encoding='utf-8')
        self.cli(['--input-file',str(file),'--manual','--language','fr','--merge'])
        self.assertEqual(self.manifest()['summary']['success'],2)
        for path in self.output.rglob('transcript.json'):
            data=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(data['subtitle']['kind'],'manual')
            self.assertEqual(len(data['transcript']['segments']),2)
            self.assertIn('Bonjour tout le monde',data['transcript']['segments'][1]['text'])
    def test_language_absent_no_fallback(self):
        self.cli([VIDEO,'--language','ja'],expected=2)
        self.assertEqual(self.manifest()['summary']['unavailable'],1)
        self.assertFalse(list(self.output.rglob('transcript.json')))
    def test_translated_track_labeled(self):
        self.cli([VIDEO,'--language','en'])
        data=json.loads(next(self.output.rglob('transcript.json')).read_text(encoding='utf-8'))
        self.assertTrue(data['subtitle']['translated'])
    def test_unsafe_options_fail_before_output(self):
        self.cli([VIDEO,'--subtitle-args','--exec','echo unsafe'],expected=1)
        self.assertFalse(self.output.exists())
    def test_missing_tool_fatal(self):
        result=subprocess.run([sys.executable,str(ROOT/'subsdown.py'),VIDEO,'--yt-dlp','missing-sd-tool'],capture_output=True)
        self.assertEqual(result.returncode,1)
    def test_original_ambiguity_is_explicit(self):
        info={'automatic_captions':{'fr-orig':[],'en-orig':[]}}
        with self.assertRaises(subsdown.ItemUnavailable):
            subsdown.choose_tracks(info,{'auto':True,'manual':False,'language':'original'})
    def test_original_evidence_beats_dubbed_metadata(self):
        info={'language':'en','automatic_captions':{'en':[{'url':'https://example.invalid/?tlang=en'}],
                                                  'fr-orig':[{'ext':'srt'}]},
              'subtitles':{'fr':[{'ext':'srt'}],'en':[{'ext':'srt'}]}}
        for manual in (False,True):
            tracks=subsdown.choose_tracks(info,{'auto':not manual,'manual':manual,'language':'original'})
            self.assertEqual(tracks[0][1], 'fr' if manual else 'fr-orig')
            self.assertFalse(tracks[0][2])
    def test_bad_language_expression_is_preflight_error(self):
        result=self.cli([VIDEO,'--language','['],expected=1)
        self.assertNotIn('Traceback',result.stderr)
        self.assertFalse(self.output.exists())
    def test_resume_works_without_metadata_for_verified_success(self):
        self.cli([VIDEO])
        manifest=next((self.output/'.runs').glob('*.json'))
        with patch.dict(os.environ,{'SD_FAKE_FAIL_METADATA':'1'}):
            self.cli(['--resume',str(manifest),'--merge'])
        self.assertTrue(self.manifest()['items'][0]['reused'])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),1)
    def test_playlist_rename_keeps_video_identity_for_resume(self):
        self.cli(['https://www.youtube.com/playlist?list=PL_SYNTHETIC'],expected=2)
        manifest=next((self.output/'.runs').glob('*.json'))
        with patch.dict(os.environ,{'SD_FAKE_PLAYLIST_NAME':'Renamed playlist'}):
            self.cli(['--resume',str(manifest)],expected=2)
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),1)
        self.assertTrue(any(item.get('reused') for item in self.manifest()['items']))
    def test_partial_track_fusion_and_resume(self):
        with patch.dict(os.environ,{'SD_FAKE_FAIL_LANGUAGE':'en-orig'}):
            self.cli([VIDEO,'--language','fr-orig,en-orig','--merge'],expected=2)
        state=self.manifest()
        merged=json.loads((self.output/state['merged_output']).read_text(encoding='utf-8'))
        self.assertEqual(merged['item_count'],1)
        manifest=next((self.output/'.runs').glob('*.json'))
        first=next(self.output.rglob('transcript.json'))
        digest=common.sha256(first)
        self.cli(['--resume',str(manifest),'--merge'])
        self.assertEqual(common.sha256(first),digest)
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),2)
    def test_public_channel_forms_and_upload_tabs(self):
        roots = ['/@Synthetic', '/channel/UC' + 'A' * 22, '/user/Creator', '/c/Creator']
        for root in roots:
            for tab in ('', '/videos', '/shorts', '/streams'):
                url = 'https://www.youtube.com' + root + tab
                self.assertEqual(subsdown.youtube_url(url + '/?tracking=ignored'), url)
        for path in ('/feed/subscriptions', '/feed/history', '/account', '/@Synthetic/playlists'):
            with self.assertRaises(ValueError):
                subsdown.youtube_url('https://www.youtube.com' + path)

    def test_channel_root_merges_all_upload_tabs_once(self):
        result = self.cli(['https://www.youtube.com/@Synthetic', '--merge', '--json'])
        report = json.loads(result.stdout)
        self.assertEqual(report['schema_version'], 'subsdown.result.v1')
        self.assertEqual(report['exit_code'], 0)
        self.assertEqual(report['summary'], {'success': 3, 'unavailable': 0, 'failed': 0})
        self.assertIn('Exported:', result.stderr)
        state = self.manifest()
        self.assertIsNone(state['selection']['max_videos'])
        self.assertEqual(state['targets'][0]['url'], 'https://www.youtube.com/@Synthetic')
        merged = json.loads(Path(report['merged_json']).read_text(encoding='utf-8'))
        self.assertEqual({item['video_id'] for item in merged['items']},
                         {'aaaaaaaaaaa', 'ccccccccccc', 'ddddddddddd'})
        self.assertEqual(merged['item_count'], 3)
        self.assertTrue(all('original' not in item for item in merged['items']))
        for export in self.output.rglob('transcript.json'):
            item = json.loads(export.read_text(encoding='utf-8'))
            self.assertEqual(item['playlist']['source_url'], 'https://www.youtube.com/@Synthetic')
        self.assertTrue(Path(report['merged_markdown']).is_file())
        self.assertEqual(Path(report['manifest_path']).resolve().parent, (self.output / '.runs').resolve())

    def test_channel_explicit_video_tab_has_only_video(self):
        self.cli(['https://www.youtube.com/@Synthetic/videos', '--merge'])
        state = self.manifest()
        self.assertEqual(state['summary']['success'], 1)
        merged = json.loads((self.output / state['merged_output']).read_text(encoding='utf-8'))
        self.assertEqual([item['video_id'] for item in merged['items']], ['aaaaaaaaaaa'])

    def test_cap_bounds_enumeration_without_out_of_scope_errors(self):
        with patch.dict(os.environ, {'SD_FAKE_REQUIRE_END': '1'}):
            result = self.cli(['https://www.youtube.com/playlist?list=PL_SYNTHETIC',
                               '--max-videos', '1', '--merge', '--json'])
        self.assertEqual(json.loads(result.stdout)['summary'], {'success': 1, 'unavailable': 0, 'failed': 0})
        state = self.manifest()
        self.assertEqual(state['selection']['max_videos'], 1)
        self.assertEqual(len(state['expanded_targets']), 1)
        self.assertFalse(state['enumeration_targets'])
        self.cli(['--resume', json.loads(result.stdout)['manifest_path'], '--json'])
        self.assertEqual(self.manifest()['summary']['success'], 1)

    def test_cap_missing_position_is_immutable_on_resume(self):
        playlist = 'https://www.youtube.com/playlist?list=PL_SYNTHETIC'
        with patch.dict(os.environ, {'SD_FAKE_NULL_SECOND': '1'}):
            result = self.cli([playlist, '--max-videos', '2', '--json'], expected=2)
        report = json.loads(result.stdout)
        self.assertEqual(report['summary'], {'success': 1, 'unavailable': 1, 'failed': 0})
        self.assertEqual(self.manifest()['enumeration_targets'][0]['entry_end'], 2)
        with patch.dict(os.environ, {'SD_FAKE_PLAYLIST_RECOVER': '1'}):
            self.cli(['--resume', report['manifest_path'], '--json'])
        state = self.manifest()
        self.assertEqual(state['summary'], {'success': 2, 'unavailable': 0, 'failed': 0})
        self.assertEqual({target['url'][-11:] for target in state['expanded_targets']},
                         {'aaaaaaaaaaa', 'ccccccccccc'})
        self.cli(['--resume', report['manifest_path'], '--max-videos', '3', '--json'], expected=1)

    def test_legacy_manifest_without_cap_remains_resumable(self):
        self.cli([VIDEO])
        manifest = next((self.output / '.runs').glob('*.json'))
        saved = json.loads(manifest.read_text(encoding='utf-8'))
        del saved['selection']['max_videos']
        manifest.write_text(json.dumps(saved), encoding='utf-8')
        result = self.cli(['--resume', str(manifest), '--merge', '--json'])
        self.assertEqual(json.loads(result.stdout)['summary']['success'], 1)
        self.assertTrue(self.manifest()['items'][0]['reused'])

    def test_cap_does_not_follow_out_of_scope_nested_tab(self):
        data = {'id': 'UC' + 'A' * 22, 'title': 'Bounded root',
                'entries': [{'_type': 'playlist', 'entries': [{'id': 'aaaaaaaaaaa'}]},
                            {'_type': 'url', 'url': 'https://www.youtube.com/@Synthetic/streams'}]}
        real_metadata = subsdown.metadata
        calls = []
        def bounded(executable, url, *, flat=False, playlist_end=None):
            calls.append(url)
            if flat:
                self.assertEqual(playlist_end, 1)
                return data
            return real_metadata(executable, url, flat=flat, playlist_end=playlist_end)
        with patch.object(subsdown, 'metadata', side_effect=bounded):
            self.assertEqual(subsdown.run(self.direct_args(url='https://www.youtube.com/@Synthetic', max_videos=1)), 0)
        self.assertFalse(any(url.endswith('/streams') for url in calls))
        self.assertEqual(self.manifest()['summary'], {'success': 1, 'unavailable': 0, 'failed': 0})

    def test_global_cap_skips_later_sources(self):
        inputs = self.root / 'links.txt'
        inputs.write_text(VIDEO + '\nhttps://www.youtube.com/@Synthetic\n', encoding='utf-8')
        self.cli(['--input-file', str(inputs), '--max-videos', '1', '--json'])
        self.assertEqual(len(self.manifest()['expanded_targets']), 1)
        self.assertEqual(self.manifest()['summary']['success'], 1)

    def test_json_fatal_and_invalid_arguments_are_one_object(self):
        for options in ([VIDEO, '--max-videos', '0'], [VIDEO, '--max-videos', '-1'],
                        [VIDEO, '--max-videos', 'bad'], [VIDEO, '--text-only'],
                        ['https://www.youtube.com/feed/subscriptions'], [VIDEO, '--unknown']):
            with self.subTest(options=options):
                result = self.cli([*options, '--json'], expected=1)
                report = json.loads(result.stdout)
                self.assertEqual(report['schema_version'], 'subsdown.result.v1')
                self.assertEqual(report['exit_code'], 1)
                self.assertIn('error', report)
                self.assertFalse(self.output.exists())

    def test_json_partial_and_text_only_resume(self):
        result = self.cli(['https://www.youtube.com/playlist?list=PL_SYNTHETIC',
                           '--merge', '--json'], expected=2)
        report = json.loads(result.stdout)
        self.assertEqual(report['exit_code'], 2)
        self.assertIsNotNone(report['merged_json'])
        before = {str(p): common.sha256(p) for p in self.output.rglob('transcript.*')}
        resumed = self.cli(['--resume', report['manifest_path'], '--merge', '--text-only', '--json'], expected=2)
        combined = json.loads(Path(json.loads(resumed.stdout)['merged_json']).read_text(encoding='utf-8'))
        self.assertTrue(all('original' not in item and 'segments' not in item for item in combined['items']))
        for path, digest in before.items():
            self.assertEqual(common.sha256(Path(path)), digest)

    def test_channel_nested_tab_cycle_and_external_link_are_errors(self):
        root = 'https://www.youtube.com/@Synthetic'
        for link in (root + '/streams', 'https://example.invalid/private',
                     'https://www.youtube.com/@SomeoneElse/streams'):
            data = {'entries': [{'_type': 'url', 'url': link}]}
            with patch.object(subsdown, 'metadata', return_value=data):
                with self.assertRaises(ValueError):
                    list(subsdown.collection_entries([], data, root))

    def test_uncapped_channel_120_videos_are_all_processed_and_merged(self):
        ids = [f'{index:011d}' for index in range(120)]
        root_url = 'https://www.youtube.com/@Synthetic'
        exports = []
        def metadata(executable, url, *, flat=False, playlist_end=None):
            self.assertIsNone(playlist_end)
            if flat:
                return {'id': 'UC' + 'A' * 22, 'title': 'All uploads',
                        'entries': [{'_type': 'playlist', 'entries': [{'id': video} for video in ids[:60]]},
                                    {'_type': 'playlist', 'entries': [{'id': video} for video in ids[60:]]}]}
            video = url[-11:]
            return {'id': video, 'title': video, 'channel': 'Synthetic',
                    'automatic_captions': {'en-orig': [{'ext': 'srt'}]}}
        def publish(info, track, stage, output_root, selection, versions, playlist):
            video = info['id']
            bundle = output_root / video
            bundle.mkdir()
            (bundle / 'transcript.srt').write_text('1\n00:00:00,000 --> 00:00:01,000\nText ' + video + '\n', encoding='utf-8')
            (bundle / 'transcript.md').write_text('Text ' + video, encoding='utf-8')
            record = {'schema_version': 'subsdown.v4', 'type': 'YouTubeSubtitleTranscript',
                      'video': {'id': video, 'title': video, 'url_clean': 'https://www.youtube.com/watch?v=' + video},
                      'playlist': playlist, 'subtitle': {'language': 'en-orig', 'kind': 'auto', 'translated': False},
                      'transcript': {'segment_count': 1, 'plain_text': 'Text ' + video,
                                     'segments': [{'index': 1, 'start': '00:00:00,000', 'end': '00:00:01,000', 'text': 'Text ' + video}]}}
            common.atomic_write_json(bundle / 'transcript.json', record)
            exports.append(video)
            return [{'path': str(file.relative_to(output_root)), 'sha256': common.sha256(file)} for file in bundle.iterdir()]
        args = self.direct_args(url=root_url, merge=True)
        with redirect_stdout(io.StringIO()), patch.object(subsdown, 'metadata', side_effect=metadata), patch.object(subsdown, 'publish_track', side_effect=publish):
            self.assertEqual(subsdown.run(args), 0)
        self.assertEqual(exports, ids)
        state = self.manifest()
        self.assertEqual(state['summary']['success'], 120)
        merged = json.loads((self.output / state['merged_output']).read_text(encoding='utf-8'))
        self.assertEqual([item['video_id'] for item in merged['items']], ids)
        markdown = (self.output / state['merged_markdown']).read_text(encoding='utf-8')
        self.assertTrue(all('Text ' + video in markdown for video in ids))

    @unittest.skipUnless(sys.platform == 'win32', 'Windows launcher discovery')
    def test_launcher_selects_first_python_application(self):
        def quoted(value):
            return "'" + str(value).replace("'", "''") + "'"
        script = self.root / 'mock-discovery.ps1'
        script.write_text("function Get-Command { param($Name, $CommandType, $ErrorAction) "
                          "[pscustomobject]@{Source=" + quoted(sys.executable) + "}; "
                          "[pscustomobject]@{Source='missing-second-python.exe'} }\n"
                          "& " + quoted(ROOT / 'subsdown.ps1') + " " + quoted(VIDEO) +
                          " -OutRoot " + quoted(self.output) + " -Python python -YtDlp " + quoted(FAKE) +
                          " -FFmpeg " + quoted(FAKE) + " -MaxVideos 1 -Merge -Json\n", encoding='utf-8-sig')
        for shell in ('powershell.exe', 'pwsh.exe'):
            if not shutil.which(shell):
                continue
            result = subprocess.run([shell, '-NoProfile', '-NonInteractive', '-File', str(script)],
                                    capture_output=True, text=True, encoding='utf-8', errors='replace')
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['summary']['success'], 1)

    def direct_args(self, **overrides):
        values=dict(url=None,input_file=None,out_root=str(self.output),language=None,manual=False,
                    current_video_only=False,keep_work=False,process_all=False,resume=None,
                    merge=False,yt_dlp=str(FAKE),ffmpeg=str(FAKE),subtitle_args=[])
        values.update(overrides)
        return SimpleNamespace(**values)
    def test_interrupted_enumeration_is_resumable(self):
        with patch.object(subsdown,'metadata',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt): subsdown.run(self.direct_args(url=VIDEO))
        manifest=next((self.output/'.runs').glob('*.json'))
        self.assertEqual(len(self.manifest()['enumeration_targets']),1)
        self.cli(['--resume',str(manifest)])
        self.assertEqual(self.manifest()['summary']['success'],1)
    def test_partial_exports_survive_metadata_failure_on_resume(self):
        with patch.dict(os.environ,{'SD_FAKE_FAIL_LANGUAGE':'en-orig'}):
            self.cli([VIDEO,'--language','fr-orig,en-orig','--merge'],expected=2)
        manifest=max((self.output/'.runs').glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
        with patch.dict(os.environ,{'SD_FAKE_FAIL_METADATA':'1'}):
            self.cli(['--resume',str(manifest),'--merge'],expected=2)
        state=self.manifest()
        self.assertEqual(len(state['items'][0]['exports']),3)
        merged=json.loads((self.output/state['merged_output']).read_text(encoding='utf-8'))
        self.assertEqual(merged['item_count'],1)
        manifest=max((self.output/'.runs').glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
        self.cli(['--resume',str(manifest)])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),2)
    def test_interrupted_resume_retains_unvisited_inventory(self):
        inputs=self.root/'links.txt'
        inputs.write_text(VIDEO+'\nhttps://youtu.be/ccccccccccc\n',encoding='utf-8')
        self.cli(['--input-file',str(inputs)])
        manifest=max((self.output/'.runs').glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
        verify=subsdown.verified_exports
        count=0
        def interrupted(item,root):
            nonlocal count
            count+=1
            if count==2: raise KeyboardInterrupt
            return verify(item,root)
        with patch.object(subsdown,'verified_exports',side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt): subsdown.run(self.direct_args(resume=str(manifest)))
        manifest=max((self.output/'.runs').glob('*.json'),key=lambda p:p.stat().st_mtime_ns)
        self.assertEqual(len(self.manifest()['recovery_items']),2)
        self.cli(['--resume',str(manifest)])
        self.assertEqual(len(list(self.output.rglob('transcript.json'))),2)

    def test_tampered_resume_url_is_rejected(self):
        self.cli([VIDEO])
        manifest=next((self.output/'.runs').glob('*.json'))
        state=json.loads(manifest.read_text(encoding='utf-8'))
        state['expanded_targets'][0]['url']='https://example.invalid/private'
        manifest.write_text(json.dumps(state),encoding='utf-8')
        self.cli(['--resume',str(manifest)],expected=1)

    def test_atomic_failure_does_not_replace_destination(self):
        target=self.root/'existing.json'
        common.atomic_write_json(target,{'old':1})
        with patch('common.os.replace',side_effect=OSError('synthetic interruption')):
            with self.assertRaises(OSError): common.atomic_write_json(target,{'new':2},overwrite=True)
        self.assertEqual(json.loads(target.read_text()),{'old':1})
        self.assertFalse(list(self.root.glob('.write-*')))
    def test_safe_names_and_urls(self):
        self.assertEqual(common.safe_filename('CON'),'_CON')
        self.assertNotIn('/',common.safe_filename('bad/name'))
        self.assertEqual(subsdown.youtube_url(VIDEO+'?si=tracking'),'https://www.youtube.com/watch?v=aaaaaaaaaaa')
        for url in ('https://example.org/aaaaaaaaaaa','https://user:secret@youtube.com/watch?v=aaaaaaaaaaa'):
            with self.assertRaises(ValueError): subsdown.youtube_url(url)
    @unittest.skipUnless(sys.platform=='win32','Windows launchers')
    def test_windows_launchers_unicode_and_custom_selection(self):
        for shell in ('powershell.exe','pwsh.exe','cmd'):
            if shell!='cmd' and not shutil.which(shell): continue
            with self.subTest(shell=shell):
                self.cli([VIDEO,'-Language','fr','-Manual','-Merge'],shell=shell)
                data=json.loads(next(self.output.rglob('transcript.json')).read_text(encoding='utf-8'))
                self.assertEqual(data['subtitle']['language'],'fr')
                self.assertEqual(data['subtitle']['kind'],'manual')
    @unittest.skipUnless(sys.platform=='win32','Windows launchers')
    def test_legacy_subtitle_arguments(self):
        self.cli([VIDEO,'--write-subs','--sub-langs','fr'],shell='powershell.exe')
        self.assertEqual(self.manifest()['summary']['success'],1)

if __name__=='__main__': unittest.main()
