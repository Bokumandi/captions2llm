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
    if ('list' in query or not query.get('v')) and '--no-playlist' not in args:
        if os.environ.get('SD_FAKE_REQUIRE_END') and '--playlist-end' not in args:
            raise SystemExit(12)
        cap = int(args[args.index('--playlist-end')+1]) if '--playlist-end' in args else None
        path = urlsplit(url).path.rstrip('/')
        channel_id = 'UC' + 'A' * 22
        base = 'https://www.youtube.com/@Synthetic'
        if 'list' in query:
            entries = [{'id':'aaaaaaaaaaa'}, {'id':'bbbbbbbbbbb'}, None]
            if os.environ.get('SD_FAKE_NULL_SECOND'):
                entries = [{'id':'aaaaaaaaaaa'}, None, {'id':'ccccccccccc'}]
            if os.environ.get('SD_FAKE_PLAYLIST_RECOVER'):
                entries = [{'id':'aaaaaaaaaaa'}, {'id':'ccccccccccc'}, {'id':'ddddddddddd'}]
            data = {'_type':'playlist','id':'PL_SYNTHETIC',
                    'title':os.environ.get('SD_FAKE_PLAYLIST_NAME', 'Synthetic playlist')}
        else:
            data = {'_type':'playlist','id':channel_id, 'channel_id':channel_id,
                    'channel_url':'https://www.youtube.com/channel/' + channel_id,
                    'uploader_url':base, 'title':'Synthetic uploads'}
            if path.endswith('/videos'):
                entries = [{'id':'aaaaaaaaaaa'}]
            elif path.endswith('/shorts'):
                entries = [{'id':'ccccccccccc'}]
            elif path.endswith('/streams'):
                entries = [{'id':'ddddddddddd'}]
            else:
                entries = [{'_type':'playlist', 'entries':[{'id':'aaaaaaaaaaa'}]},
                           {'_type':'playlist', 'entries':[{'id':'ccccccccccc'}, {'id':'aaaaaaaaaaa'}]},
                           {'_type':'url', 'url':base + '/streams', 'ie_key':'YoutubeTab'}]
        data['entries'] = entries[:cap] if 'list' in query else entries
        print(json.dumps(data))
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
