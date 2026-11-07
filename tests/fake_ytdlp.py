"""Offline yt-dlp/FFmpeg double; synthetic data only."""
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, urlsplit
args = sys.argv[1:]
if '--version' in args or '-version' in args:
    print('synthetic-1.0')
    raise SystemExit(0)
url = args[-1]
query = parse_qs(urlsplit(url).query)
video = query.get('v', ['aaaaaaaaaaa'])[0]
if '--dump-single-json' in args:
    if os.environ.get('SD_FAKE_FAIL_METADATA'):
        raise SystemExit(7)
    if 'list' in query and '--no-playlist' not in args:
        print(json.dumps({'_type':'playlist','id':'PL_SYNTHETIC','title':os.environ.get('SD_FAKE_PLAYLIST_NAME', 'Synthetic playlist'),
                          'entries':[{'id':'aaaaaaaaaaa'}, {'id':'bbbbbbbbbbb'}, None]}))
    else:
        print(json.dumps({'id': video, 'title': 'Demonstration é [test]', 'channel': 'Synthetic channel',
                          'language': 'fr-FR', 'duration': 5, 'subtitles': {'fr':[{'ext':'srt'}]},
                          'automatic_captions': {} if video == 'bbbbbbbbbbb' else {
                              'fr-orig':[{'ext':'srt'}], 'en-orig':[{'ext':'srt'}],
                              'en':[{'url':'https://example.invalid/?tlang=en','ext':'srt'}]}}))
    raise SystemExit(0)
if '--skip-download' not in args or '--no-playlist' not in args or '--ignore-config' not in args:
    raise SystemExit(9)
if '--exec' in args:
    raise SystemExit(10)
lang = args[args.index('--sub-langs')+1]
lang = re.sub(r'\\(.)',r'\1',lang)
if lang == os.environ.get('SD_FAKE_FAIL_LANGUAGE'):
    raise SystemExit(7)
output = args[args.index('--output')+1]
output = output.replace('%(id)s',video).replace('%(ext)s', lang + '.srt')
Path(output).parent.mkdir(parents=True,exist_ok=True)
Path(output).write_text('1\n00:00:00,000 --> 00:00:02,000\nBonjour tout le monde\n\n2\n00:00:01,000 --> 00:00:03,000\nBonjour tout le monde\nUne nouvelle ligne\n',encoding='utf-8')
