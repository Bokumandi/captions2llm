# Captions2LLM

Collect existing captions from YouTube videos, playlists and public channels.
Export Markdown and JSON with source URLs for LLM analysis, or split a large
collection into reading batches. Captions2LLM runs locally on Windows; you or your
own LLM/agent perform the analysis.

The cleaner derives from [srt_fix](https://github.com/bindestriche/srt_fix)
(Unlicense); Captions2LLM's own contributions are MIT licensed. Development used
**OpenAI Codex with GPT-family models**. See [NOTICE](NOTICE.md) for attribution,
source revisions and AI-development details.

## Quick start

### 1. Check the requirements

| Task | Requirements |
| --- | --- |
| Every command | Windows and Python 3.11 or 3.13 |
| PowerShell/CMD launchers | PowerShell 5.1 or 7; CMD uses Windows PowerShell 5.1 |
| Download captions | yt-dlp, FFmpeg and Deno for YouTube challenge support |
| Clone this repository | Git |

Reuse existing tools. The examples below assume `python`, `yt-dlp`, `ffmpeg` and
`deno` are available on PATH. For discovery and explicit executable paths, see
[the setup guide](docs/AGENT_GUIDE.md#find-the-required-tools). Local indexing,
merging and batch preparation use Python's standard library and need no network.

### 2. Get the release or source

These instructions cover **Captions2LLM 0.4.0**. Download the source ZIP, manifest
and checksums from the [v0.4.0 release](https://github.com/Bokumandi/captions2llm/releases/tag/v0.4.0),
then [verify and extract them](docs/RELEASING.md#install-a-packaged-release).
Keep VERSION, modules and license notices together. For another version, follow
the README bundled with that version.

Alternatively, clone the current source. In PowerShell, from a short directory:

```powershell
git clone https://github.com/Bokumandi/captions2llm.git
Set-Location captions2llm
.\captions2llm.ps1 --version
```

If you already extracted the release or have a suitable checkout, enter that
directory and run the version command instead of cloning again. There is no
`pip install`, build step or API key to configure.

### 3. Download a playlist

Replace `PLAYLIST_ID` with your playlist's ID. This stores the captions outside
the source checkout and creates a compact combined corpus:

```powershell
$Run = & .\captions2llm.ps1 download "https://www.youtube.com/playlist?list=PLAYLIST_ID" -OutRoot ..\captions-output -Merge -TextOnly -Json | ConvertFrom-Json
$DownloadExit = $LASTEXITCODE
if ($DownloadExit -eq 1) { throw "Download failed: $($Run.error)" }
$Run.summary
$Run.merged_markdown
```

Open the file named by `merged_markdown` to read the combined text. Each caption
track also has its own `transcript.md`, `transcript.json` and `transcript.srt`;
these individual files retain timestamps. `-TextOnly` reduces repetition in the
combined files and leaves the individual exports intact.

Exit **0** means the selected scope completed. Exit **2** means some captions or
outputs are missing: keep the successful files and inspect `$Run.manifest_path`.
A merged output can be absent, so check its returned path before opening it.
The default is **automatic captions in the original language**, with no silent
fallback to another language.

## Choose what to read

| Need | Use |
| --- | --- |
| Read or analyze one video | Its individual `transcript.md` |
| Work with timestamps or structured metadata | Its individual `transcript.json` |
| Edit subtitles | Its individual `transcript.srt` |
| Read a small collection together | Combined Markdown from `download -Merge -TextOnly` |
| Inventory sources and missing captions | The compact index at `$Run.index_json` or `$Run.index_markdown` |
| Analyze a collection in separate LLM contexts | A reading plan from `prepare` |

The index contains metadata and file references, not transcript bodies. A combined
corpus is useful for storage and exchange; choose batches when it is too large
to read in one context.

## Prepare reading batches

### Prepare this download run

Pass the run's manifest to select its exports and retain its missing-caption
records. Continue from `$Run` above:

```powershell
$Prepared = & .\captions2llm.ps1 prepare $Run.output_root -Manifest $Run.manifest_path -MaxChars 30000 -Json | ConvertFrom-Json
if (-not $Prepared.plan_path) { throw "Preparation failed: $($Prepared.error)" }
$PlanPath = $Prepared.plan_path
Get-Content -LiteralPath $Prepared.instructions -Raw -Encoding UTF8
.\captions2llm.ps1 status $PlanPath -Json
```

Each batch has a Markdown reading file and a JSON report template. Read one batch,
copy its template to a separate working file, fill in what you actually read and
found, then submit it with `accept-report`. See the [complete report
workflow](docs/AGENT_GUIDE.md#complete-a-batch-report) for file selection, a filled
example and acceptance commands.

Save the report before starting another batch in a fresh context. Build the final
synthesis from those reports and reopen source passages as needed.

The default limit is **30,000 characters per reading file**, including headings
and timestamps. It measures characters rather than model tokens; leave room for
your prompt and response. A caption track stays together when it fits. Longer
tracks are split into consecutive passages without deleting text. Different
language tracks remain separate; overlapping videos are not semantically deduplicated.

### Prepare every export in a folder

Without a manifest, `prepare` scans all transcript exports in the folder,
including earlier runs. It cannot establish which requested videos are missing.
Use this mode when the whole folder is intentionally your corpus:

```powershell
.\captions2llm.ps1 prepare ..\captions-output -MaxChars 30000 -Json
```

## Download options and recovery

Use a video URL, playlist URL or public channel URL as the `download` input.
Channel paths ending in `/videos`, `/shorts` or `/streams` restrict the selected
upload tab. A watch URL containing `list=` selects the playlist unless you pass
`-CurrentVideoOnly`. Quote URLs containing `&`.

| Option | Purpose |
| --- | --- |
| `-Merge` | Create combined JSON and Markdown for the current run |
| `-TextOnly` | With `-Merge`, keep transcript text once and omit segment bodies in combined outputs |
| `-Language fr` | Request French captions explicitly |
| `-Manual` | Select uploaded captions instead of automatic captions |
| `-InputFile .\links.txt` | Read one URL per line; ignore blank lines and `#` comments |
| `-MaxVideos 10` | Select at most ten source positions, including unavailable entries |
| `-OutRoot PATH` | Choose the output folder; keep its absolute path at most 105 characters |
| `-KeepWork` | Retain raw working files for diagnosis |
| `-Json` | Emit one JSON result on stdout; progress goes to stderr |

Collections have no default size cap. They cover the public entries returned by
YouTube/yt-dlp, subject to access and caption availability. Downloads run sequentially.
Automatic captions can contain errors; identified translations are labeled.

To retry missing or failed work, use the saved manifest. Completed, hash-verified
exports are reused:

```powershell
.\captions2llm.ps1 download -Resume $Run.manifest_path -Merge -TextOnly -Json
```

Resume keeps the saved input, language and scope; do not add selection flags.
Run one resume per output tree and one report writer per plan at a time.

## Where the files go

```text
captions-output/
  Channel/Collection [ID]/VIDEO_ID-language-kind/
    transcript.md, transcript.json, transcript.srt
  .runs/RUN_ID.json                  # download scope, results and recovery
  subsindex-RUN_ID.json, .md          # automatic download index
  subsmerge-RUN_ID.json, .md          # download -Merge
  .indexes/INDEX_ID/index.json, .md   # separate index command
  .batches/PLAN_ID/                  # prepare command
    plan.json, index.json, index.md, instructions.md
    batch-ID.md, batch-ID.report.json
    reports/batch-ID/                # accepted reports
```

Names shown together denote separate files. Commands return their exact paths.
New runs and plans use unique destinations; original exports are preserved.

## Command reference

| Command | Operation |
| --- | --- |
| `download URL` | Collect captions, individual exports and an index; optionally merge |
| `merge FOLDER` | Merge existing exports in a folder, including earlier runs |
| `index FOLDER` | Create a compact inventory of existing exports |
| `prepare FOLDER` | Create bounded reading files and report templates |
| `status PLAN` | Check batch progress and source integrity |
| `accept-report PLAN REPORT` | Validate report structure and references, then render Markdown |

Use `python captions2llm.py COMMAND --help` for each command's arguments. Python
uses `--kebab-case`; Windows launchers accept the PowerShell spellings shown above.
For example:

```powershell
.\captions2llm.ps1 merge ..\captions-output -Output ..\corpus.json -MarkdownOutput ..\corpus.md -TextOnly -Json
python captions2llm.py prepare ..\captions-output --max-chars 30000 --json
```

Standalone `merge` includes the original JSON payload by default. Use `-NoOriginal`
to retain timed segments without it, or `-TextOnly` to keep only one transcript
body. `-FailOnError` rejects a partial merge; `-Overwrite` explicitly replaces
existing derived outputs. Source transcripts are protected. The separate cleaner
accepts `python srt_fixer_cli.py source.srt -o cleaned.srt`.

Exit codes differ by operation; see the [agent result contract](docs/AGENT_GUIDE.md#result-contracts-and-exit-codes).
An accepted report records the author's declared coverage; it does not independently
verify the analysis. `status` detects missing or modified source/reading files.

## Compatibility and further help

All `subsdown`, `subsmerge` and `subsbatch` entry points remain available in Python,
PowerShell and CMD. Their schemas, import APIs and output names are unchanged.
The default output folder is still `subsdown_output` when `-OutRoot` is omitted.
Existing manifests and reading plans remain usable.

- [Agent guide](docs/AGENT_GUIDE.md): tool discovery, complete report workflow and troubleshooting.
- [Maintenance](docs/MAINTENANCE.md): current contracts, verification and historical decisions.
- [Release procedure](docs/RELEASING.md): build, verify and publish source assets.
- [Changelog](CHANGELOG.md) and [provenance/licensing](NOTICE.md).

Captions2LLM retrieves available captions, not audio or video. It does not transcribe
missing captions or call an LLM. `python verify.py` runs the offline test suite;
results and limits are recorded in maintenance. Software licenses are
[MIT](LICENSE) for local contributions and [Unlicense](LICENSES/srt_fix-Unlicense.txt)
for the upstream cleaner; third-party caption rights are separate.
