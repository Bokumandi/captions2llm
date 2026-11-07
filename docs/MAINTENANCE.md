# Maintenance, provenance and verification

## Product contract

Subsdown is a small Windows subtitle tool, not a transcription service or a media
downloader. Keep the PowerShell/CMD commands, standard-library Python helpers and
historical `subsdown.v4` transcript fields compatible. `VERSION` owns the product
version. `subsmerge_version: 2.0.0` is the retained merged-format marker;
`product_version` identifies this product's implementation.

README.md owns user procedures, AGENTS.md routes contributors, and this file owns
decisions, verification evidence and maintenance history. This is the knowledge
delta for the initial import and corrections; no empty wiki, separate rules tree
or duplicated per-library documentation is needed. The README captures the
repeatable download/resume/merge procedure without installing an additional skill.

## Source inventory and reuse decision — 2026-11-08

The owner requested an independent copy of the existing local subsdown v4 and
subsmerge v2 scripts, debugging, incremental improvements and public publication
as Bokumandi/subsdown. Only seven source scripts were copied. No historical
transcripts, media, caches or prior output trees were imported.

The local `simplesrt.py` and `srt_fixer_cli.py` matched Git blobs at upstream
[bindestriche/srt_fix revision 5b4442a8cdcae06c53545f4d0c99c3e624416919](https://github.com/bindestriche/srt_fix/tree/5b4442a8cdcae06c53545f4d0c99c3e624416919):

| File | Original Git blob |
| --- | --- |
| simplesrt.py | 282c90a13ae371ca9b5ebc7f9c015b35c4655787 |
| srt_fixer_cli.py | 0a72e277b7b1bbefc9c2e67aa3e866cac66f1c89 |

This identifies matching source, not the original acquisition method. Preserve
LICENSES/srt_fix-Unlicense.txt (upstream license blob
68a49daad8ff7e35068f2b7a97d643aab440eaec). The owner selected MIT for local wrappers
and new product contributions; upstream attribution/licensing remains explicit.
Original SHA-256 receipts for all imported scripts are in source-imports.json.

Options considered: keep yt-dlp and the local scripts; adopt the newer upstream
cleaner wholesale; replace the tool with a packaged Python CLI/framework.
The selected approach reuses yt-dlp and the local entry points, incorporates
upstream fixes and adds bounded validation. Wholesale upstream replacement did
not address the local launcher, batches or merger; a framework/package migration
would add maintenance without improving this Windows workflow.

The upstream [duration correction](https://github.com/bindestriche/srt_fix/commit/8ccbeb8e908866ef1f11a4d2448a31a4d8395104)
and [optional output fix](https://github.com/bindestriche/srt_fix/commit/2622ad661a299e6e0057eada25a9178a91e46bfd)
were read before implementation. Local code additionally needs conservative
speech preservation, strict timestamps and atomic writes, so upstream patches
alone are insufficient.

## Decisions and failure mechanisms

- The original `$Args` parameters collided with PowerShell's automatic variable;
  argument loss was directly reproduced under PS5.1. Python subprocess argv now
  owns native calls; the small PS launchers preserve the existing command surface.
  This also avoids PS5.1 UTF-16 redirection versus UTF-8 metadata decoding.
- Default language changes from English to original automatic captions by owner
  decision. Original-track evidence is shared with manual selection; ambiguous
  metadata and absent tracks never authorize a different language silently.
- A per-video/track subdirectory is an intentional layout addition: one rename
  publishes the SRT/Markdown/JSON bundle. Historical JSON fields are retained.
- Resume uses explicit run manifests and complete SHA-256-verified bundles. Saved
  expanded identities decouple success reuse from live metadata and playlist names.
  Pending enumeration and unvisited prior items remain recoverable at checkpoints.
- Cleanup only deletes the current invocation's resolved temporary directory after
  checking its exact parent, prefix and non-symlink identity. Failed work is kept.
- The cleaner no longer joins arbitrary one/two-word cues or subtracts 1ms from
  prior timings. It removes only demonstrated overlapping rolling-line repeats.
  Exact repeated cues may remain; preserving speech is preferable to deleting it.
- Normal Git, existing GitHub authentication and a dedicated public repository are
  used. No shared installation, global configuration or source project is changed.

## Verification and limits

The local baseline tested Python 3.13.2, Windows PowerShell 5.1.26100.9711 and
PowerShell 7.6.5. Synthetic regression suites cover cleaner/parser behavior,
launchers, paths, atomic writes, batch accounting, language selection, resumes,
interruption recovery and merger compatibility. `python verify.py` is the single
integrated gate; focused regressions are used while fixing observed failures.
CI adds Python 3.11 and repeats Python 3.13 on Windows.

A real PS5.1 → Python → yt-dlp → clean → merge run on owner-supplied video
UUnD024yY5A retrieved `fr-orig`, automatic and untranslated, with 592 valid segments.
Tools used: yt-dlp 2026.10.26, FFmpeg 9.0.2 Full, Python 3.13.2. Media/text files
and manifests are private local evidence; the public repository records only
this result. A real playlist was not downloaded; playlist/error cases are
qualified with deterministic synthetic subprocesses. Network tests are not CI.

A crash between bundle rename and its next manifest checkpoint can leave an
intact untracked bundle. Resume safely writes a unique new copy; it never trusts
a filename alone. There is no automatic orphan deletion. Do not run two resumes
against the same output tree concurrently; each execution has its own manifest
and unique outputs, but filesystem races may make an item fail explicitly.
Tool/site evolution can invalidate network behavior; versions are recorded on each
run. YouTube may expose several dubbed original tracks; metadata selects among
them when possible. Human-translated manual tracks are not always identifiable.

## Agent work and review

Requested routing for this batch: coordinator on its attached session; cleaner
implementation GPT-6.1 Sol/high; merger implementation GPT-6.1 Sol/medium;
independent integration/data-preservation review GPT-6 Astra/high. Requested
models/efforts are recorded; the interface does not separately expose confirmed
model identifiers, token consumption or cost. No numerical savings are claimed.
The coordinator owns common helpers, orchestration, documentation and integration;
subagents own disjoint cleaner and merger surfaces. Integration evidence is run
by the coordinator rather than inferred from agent summaries.

The independent review found original-language selection and interrupted-resume
inventory defects; each was corrected with a corresponding regression. Review
this document when the CLI, schema markers, staging or resume contracts change.

## Initial acceptance result — 2026-11-08

The coordinator's integrated `python -X utf8 verify.py` completed successfully:
56 tests, 55 passed and one Windows symlink-privilege skip. The independent
integration and documentation review returned CLEAR after the resume regressions
were addressed. The upstream license file was verified against its original Git
blob. Source-publication inspection confirmed private local evidence and caches
are ignored; the imported receipt JSON parses successfully.
