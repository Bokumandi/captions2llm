"""Public downloader behavior through synthetic subprocesses and Windows launchers."""
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
