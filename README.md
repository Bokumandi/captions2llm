# Subsdown + Subsmerge — YouTube text corpora for LLMs

**Turn captioned YouTube videos, whole playlists and public channels into a corpus
that an LLM or an agent can analyze.** Collect available automatic or manual
captions, remove demonstrated rolling-caption redundancies, preserve sources and
timestamps, then assemble **one JSON and one Markdown file for the collection**.
Per-video files remain available for selective reading and subtitle editing.

The primary workflow is **video text → cleaned transcripts → LLM ingestion**.
SRT export is a useful companion. The tool retrieves existing captions; it does
not download video/audio, invent a missing transcript or run an LLM itself.

**Upstream credit:** the cleaner contains a modified copy of
[bindestriche/srt_fix](https://github.com/bindestriche/srt_fix), originally released
under the Unlicense. This independent application incorporates that derived
component; it is not a GitHub-network fork of the complete upstream repository.
The original notice is preserved. Local contributions and modifications are MIT
licensed. See [NOTICE.md](NOTICE.md) for exact files, revision and license scope.

**AI-assisted development:** application code, modifications, tests and docs were
generated and reworked with **OpenAI Codex using GPT-family models**, under the
repository owner's direction. Upstream authorship is credited separately.

## Start with a whole playlist or channel

```powershell
# Process the entire returned playlist; create combined JSON + Markdown.
.\subsdown.ps1 "https://www.youtube.com/playlist?list=PLAYLIST_ID" -Merge

# Process the public channel, including its returned video/short/live upload tabs.
# TextOnly keeps a single copy of each transcript's text in the combined JSON.
.\subsdown.ps1 "https://www.youtube.com/@Creator" -Merge -TextOnly

# Optional small trial. There is NO automatic collection-size limit by default.
.\subsdown.ps1 "https://www.youtube.com/@Creator" -MaxVideos 10 -Merge -TextOnly

# Agent workflow: exactly one final JSON object on stdout; progress on stderr.
.\subsdown.ps1 -InputFile .\links.txt -Merge -TextOnly -Json
```

Replace placeholders with real public YouTube URLs. A channel root selects the
channel's public uploads as enumerated by yt-dlp; an explicit `/videos`, `/shorts`
or `/streams` tab restricts scope to that tab. Public `@handle`, `/channel/ID`,
`/user/name` and `/c/name` forms are accepted. Authenticated account feeds,
subscriptions and private libraries are not supported.

There is **no arbitrary default cap**. The request covers every entry returned
for the selected collection, subject to public access and caption availability.
`-MaxVideos N` is an explicit scope limit, counting selected source positions
including unavailable entries; it is retained on resume. It is not pagination or
an assertion of the channel's absolute completeness. YouTube may hide content.
Large collections take time: the downloader is sequential, not a parallel crawler.

For installation, dependency discovery and agent operation, start with the
[agent guide](docs/AGENT_GUIDE.md). It is linked from [AGENTS.md](AGENTS.md).

## Requirements and release installation

- Windows, Python **3.11 or 3.13**, and PowerShell **5.1 or 7** for launchers.
- For downloading: `yt-dlp`, FFmpeg and the JavaScript runtime required by yt-dlp
  for YouTube challenges. See [official dependencies](https://github.com/yt-dlp/yt-dlp#dependencies).
- Local cleaning/merging only needs Python. Helpers use the standard library:
  no `pip install`, npm, API key, model weights or server is required.

Use a checkout or extract the source ZIP from [Releases](https://github.com/Bokumandi/subsdown/releases).
Keep its directory structure, including `VERSION`, modules, launchers and license
notices. A source release fixes a version/commit and supplies SHA-256 checksums;
it is not a standalone executable and does not bundle third-party dependencies.
Python software can have releases even when external tools are installed separately.

Reuse compatible shared installations. Supply explicit paths with `-Python`,
`-YtDlp` and `-FFmpeg` when needed. There is no automatic installation or update.
Use `subsdown.cmd` for the Windows PowerShell 5.1 wrapper, or
`pwsh -File .\subsdown.ps1 ...` for PowerShell 7. No global PATH change is required.

## Choose the right corpus representation

| Output | Best use | Text and provenance |
| --- | --- | --- |
| Per-video `transcript.json` | Agent reads selected videos or timestamps | Structured video/track metadata, plain text and timed segments |
| Per-video `transcript.md` | Read one video in an LLM/chat | Source URL, caption labels and timestamped text |
| Combined JSON from `-Merge` | Store, exchange and programmatically inspect a collection | `items` with source identity, caption provenance, text and segments; no embedded duplicate original payload |
| Combined JSON with `-TextOnly` | Compact LLM ingestion | Text once per item; preserves identity, language, source/translation metadata and original segment count; omits segment bodies |
| Combined Markdown | Read/share a collection as text | Explicit video boundaries, source URLs and caption provenance; timestamps in normal mode, plain text in TextOnly mode |
| Per-video `transcript.srt` | Subtitle editing or timed interchange | Clean validated subtitles |

A large single JSON/MD makes sense as a **storage and exchange artifact**. It does
not make an unlimited corpus fit into an LLM's context window. Use the combined
Markdown/text-only profile when it fits; otherwise select videos and passages from
the per-video files, or split at video boundaries in the consuming workflow.
There is no tokenizer, embedding index, semantic search engine or model-specific
context-budget guarantee built into Subsdown.

The normal combined JSON intentionally contains both `text` and timed `segments`:
agents should ingest one representation for a given task. `-TextOnly` removes that
remaining repeated transcript text. Original per-video timestamped files remain.
Overlapping input collections may contain the same video more than once; this is
not an incremental global library cache or semantic duplicate detector.

## Other download options

```powershell
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Merge -OutRoot .\subsdown_output
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Language fr -Merge
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Manual -Language fr -Merge
.\subsdown.ps1 "https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID" -CurrentVideoOnly
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Language "en.*,fr.*" -Merge
```

`links.txt` contains one video, playlist or channel URL per line; blank lines and
`#` comments are ignored. Quote URLs containing `&`. Default captions are automatic
in the original language. Original-track evidence takes priority over dubbed audio
metadata; missing or ambiguous originals are reported without a language fallback.
`-Manual` selects uploaded captions; `-Language` can explicitly request a different
language. Identifiable translations are labeled. Human translations may not be
identifiable from metadata. Live chat is not an ordinary speech transcript.

Legacy subtitle arguments are retained: `--write-subs`, `--no-write-subs`,
`--write-auto-subs`, `--no-write-auto-subs`, `--sub-langs`, `--sub-format` and
`--convert-subs srt`. Arbitrary yt-dlp execution/output/download flags are refused.
`-ProcessAllDownloadedSubtitles` remains accepted; explicitly selected tracks are
already exported. `-KeepWork` retains raw intermediates; failed work is retained.

## Outputs, partial results and resume

```text
subsdown_output/
  Channel/Collection [ID]/VIDEO_ID-language-kind/
    transcript.srt
    transcript.md
    transcript.json
  .runs/RUN_ID.json
  subsmerge-RUN_ID.json
  subsmerge-RUN_ID.md
```

Each per-track three-file bundle is published by one directory rename. A new run
creates unique outputs instead of silently overwriting earlier exports.
The manifest records requested scope, tool versions, success/unavailable/failure
counts, relative export paths and hashes. Ingestion means **available caption text**:
a missing or restricted caption track becomes a reported gap, not fabricated text.

```powershell
.\subsdown.ps1 -Resume .\subsdown_output\.runs\RUN_ID.json -Merge -TextOnly -Json
```

Use the exact printed/reported manifest path. Input, language and collection scope
are fixed on resume; the combined output profile can be selected anew. Complete
hash-verified items are reused without fetching their metadata again. Changed,
missing and failed items are retried. Prior successes survive repeated interruptions.
Run one resume per output tree at a time. Keep OutRoot at most 105 characters.

Downloader exit codes: **0** complete selected scope, **2** partial/unavailable,
**1** fatal input/setup failure. Exit 2 can accompany a useful JSON/MD subset;
read the report/manifest before claiming coverage. With `-Json`, stdout is one
structured result containing exit code, manifest and corpus locations; progress
is on stderr. Direct Python uses `--json` and `--kebab-case` options.

## Merge existing collections or clean local SRT

```powershell
# Full legacy JSON export (includes original payload by default for compatibility).
.\subsmerge.ps1 .\subsdown_output -Output .\combined.json -Pretty

# Compact corpus plus one combined Markdown; suitable for LLM ingestion.
.\subsmerge.ps1 .\subsdown_output -Output .\corpus.json -MarkdownOutput .\corpus.md -TextOnly -Json

# Retain timed segments but omit the embedded original object.
.\subsmerge.ps1 .\subsdown_output -Output .\timed.json -NoOriginal -FailOnError

python srt_fixer_cli.py source.srt -o cleaned.srt
python srt_fixer_cli.py -idir .\raw -odir .\clean
python srt_fixer_cli.py source.srt -o cleaned.srt --manual
```

Separate merge/cleanup needs no network. Standalone merger preserves the historical
JSON default; automatic `subsdown -Merge` omits embedded original payloads.
`-Overwrite` / `--overwrite` is required to replace an output; source files are
protected. Merger exit codes: **0** dataset written (inspect `error_count` for
non-strict partial reads), **2** input/output error, **3** strict read failure,
**4** no usable transcript. `-IncludeAllJson` explicitly allows generic JSON.
Staging and already-merged datasets are excluded.

The cleaner derives from srt_fix but uses more conservative rules: it removes
shared multiword lines only from overlapping advancing caption windows. Exact
repeated phrases, separated speech and short cues are retained. Manual mode
preserves every cue/text line and normalizes formatting. Empty/malformed inputs
and invalid timestamps are rejected. Valid overlaps are retained rather than
inventing timings.

## Verification, integration and releases

```powershell
python verify.py
```

The offline gate uses synthetic captions and fake download processes; CI runs
Windows/Python 3.11 and 3.13 with both PowerShell versions. Read
[maintenance evidence and limits](docs/MAINTENANCE.md) for actual network and
batch tests. Whole-channel behavior is based on public enumeration, not a promise
that every hidden/private/deleted item can be recovered. Collection manifests and
merges are held in memory; checkpoint rewriting and large corpus memory costs have
not been qualified as a production-scale crawler benchmark.

Agents can call the CLI, parse `-Json`/`--json`, inspect manifest/exit status and read
per-video or combined outputs. This is a CLI integration contract, not an MCP
server or a hosted service. No automatic LLM upload or inference takes place.
See the [agent guide](docs/AGENT_GUIDE.md) and [release procedure](docs/RELEASING.md).

[Changelog](CHANGELOG.md) · [Code/AI provenance](NOTICE.md) · [MIT](LICENSE) ·
[Upstream Unlicense](LICENSES/srt_fix-Unlicense.txt)
