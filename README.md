# Subsdown + Subsmerge

Download YouTube captions, conservatively clean automatic rolling subtitles, and
export timestamped SRT, Markdown and JSON transcripts. Merge a batch into one JSON
file for reading or LLM processing. Video and audio are never requested.

Windows PowerShell 5.1 and PowerShell 7 launchers are supported. The Python helpers
use only the standard library; no Python package installation is needed.

For agent-driven installation, dependency discovery and operation, start with the
[agent operations guide](docs/AGENT_GUIDE.md).

## Requirements

- Windows with Python **3.11 or 3.13**, `yt-dlp`, and FFmpeg available on `PATH`.
- A working yt-dlp JavaScript runtime when YouTube requires it; follow the
  [official yt-dlp instructions](https://github.com/yt-dlp/yt-dlp#dependencies).
- Publicly accessible YouTube captions. Missing tracks, authentication requirements,
  rate limits and site changes are reported; the tool does not transcribe audio.

Reuse existing installations. There is no implicit download, installation or tool
update. Supply explicit paths with `-Python`, `-YtDlp` and `-FFmpeg` when necessary.
Run commands from this checkout, or invoke the launchers by their full paths.

## Download and clean

```powershell
# Original-language automatic captions, plus a merged JSON for this run.
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Merge

# Choose French manual captions instead.
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Manual -Language fr

# Download a playlist. Quote URLs containing &.
.\subsdown.ps1 "https://www.youtube.com/playlist?list=PLAYLIST_ID" -Merge

# A video link containing a playlist: process only this video.
.\subsdown.ps1 "https://www.youtube.com/watch?v=VIDEO_ID&list=PLAYLIST_ID" -CurrentVideoOnly

# Batch links.txt contains one video or playlist URL per line; # starts a comment.
.\subsdown.ps1 -InputFile .\links.txt -OutRoot .\subsdown_output -Merge

# Explicit selection can include multiple language patterns.
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" -Language "en.*,fr.*" -Merge
```

Replace placeholder IDs with real YouTube IDs. `subsdown.cmd` exposes the same
parameters through Windows PowerShell 5.1. Use `pwsh -File .\subsdown.ps1 ...`
for PowerShell 7. The current working directory owns the default
`subsdown_output` directory; it is not fixed to the script installation.

The default is **automatic captions in the original language**. Original-track
markers take priority over metadata for dubbed audio. If several original tracks
exist, the declared video language selects one; ambiguous original language is an
explicit unavailable result. A missing language does not trigger fallback.
`-Manual` selects uploaded/manual captions. Translated tracks explicitly requested
by language are marked when YouTube metadata identifies them as translations;
manual translations may not be distinguishable from author-provided captions.

Legacy subtitle arguments remain supported, for example:

```powershell
.\subsdown.ps1 "https://youtu.be/VIDEO_ID" --write-subs --sub-langs fr
```

Allowed legacy arguments are `--write-subs`, `--no-write-subs`,
`--write-auto-subs`, `--no-write-auto-subs`, `--sub-langs`, `--sub-format` and
`--convert-subs srt`. Output/execution/download options are rejected. SRT output
is required. `-ProcessAllDownloadedSubtitles` remains accepted for compatibility;
all explicitly selected tracks are already exported. `-KeepWork` retains raw
caption intermediates. Failed work is retained for diagnosis by default.

## Outputs, partial runs and resume

```text
subsdown_output/
  Channel/
    Playlist-or-video [ID]/
      VIDEO_ID-language-kind/
        transcript.srt
        transcript.md
        transcript.json
  .runs/RUN_ID.json
  subsmerge-RUN_ID.json       # when -Merge was requested
```

Each three-file bundle is staged privately and published with one directory
rename. A new execution creates a unique bundle rather than overwriting an old
one. The extra item directory keeps the three formats consistent on interruption.
Source media and the historical script directory are never modified.

The run manifest records selected inputs, tool versions, per-video status,
relative output paths and SHA-256 hashes. Partial batches retain their successful
tracks, including when another track of the same video fails. `-Merge` includes
only verified bundles from this run, not unrelated older downloads.

```powershell
# Use the manifest path printed at the end of the original run.
.\subsdown.ps1 -Resume .\subsdown_output\.runs\RUN_ID.json -Merge
```

Resume retains the original output root and caption selection. Do not combine it
with new input or selection options. Complete verified items are reused without
fetching their metadata again. Failed items and unresolved playlist entries are
retried; modified or missing exports are not trusted. Reuse validates all three
files. A checkpoint preserves unvisited prior results across repeated interruptions.
Use a reasonably short `-OutRoot` (at most 105 characters) for Windows path limits.

Downloader exit codes: **0** complete, **2** partial/unavailable, **1** fatal setup
or input error. A usable merged subset can accompany exit 2; consult the manifest.

## Merge existing transcripts

```powershell
.\subsmerge.ps1 .\subsdown_output -Output .\combined.json -Pretty
.\subsmerge.ps1 .\subsdown_output -Output .\combined.json -Overwrite
.\subsmerge.ps1 .\subsdown_output -Output .\compact.json -NoOriginal -FailOnError
```

`subsmerge.cmd` and `python subsmerge.py` are also available. The merger accepts
historical subsdown exports, skips staging and already-merged datasets, and sorts
by playlist index then title. `-NoOriginal` omits embedded original JSON;
`-IncludeAllJson` explicitly permits unrelated JSON. No source file may be replaced.
Existing outputs require `-Overwrite`; writes are atomic. Invalid inputs produce
an `.errors.json` report. `-FailOnError` prevents the merged dataset when any input
cannot be read. Merger exit codes: **0** output written (inspect `error_count` for
non-strict partial reads), **2** input/output error, **3** strict read failure,
**4** no usable transcript.

## Clean local SRT files

```powershell
python srt_fixer_cli.py source.srt
python srt_fixer_cli.py source.srt -o cleaned.srt
python srt_fixer_cli.py -idir .\raw -odir .\clean
python srt_fixer_cli.py source.srt -o cleaned.srt --manual
```

The cleaner rejects empty/malformed files and invalid timestamps. Automatic mode
removes shared multiword lines only from overlapping advancing caption windows.
It preserves exact repeated phrases, short cues and separated speech. Manual mode
preserves every cue/text line and normalizes the SRT representation. Valid overlaps
are retained rather than inventing new timings. Existing outputs need `--overwrite`;
the source file can never be overwritten.

## Development and provenance

```powershell
python verify.py
```

The verification command uses synthetic fixtures and fake subprocesses, never
YouTube. CI runs it on Windows with Python 3.11 and 3.13 and exercises both
PowerShell versions. Real captions, logs and local evidence remain private and
are excluded from Git. Review local exports before sharing them: metadata and
merged files can include local paths and third-party transcript text.

See [maintenance decisions and verification](docs/MAINTENANCE.md) and
[contributor instructions](AGENTS.md). Project contributions are MIT licensed;
the derived `srt_fix` cleaner retains its [upstream Unlicense](LICENSES/srt_fix-Unlicense.txt).
