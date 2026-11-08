# Maintenance, provenance and verification

## Product contract

Subsdown prepares caption-derived text corpora for LLMs and agents through a
Windows CLI. Whole playlists and public channel collections are primary inputs;
combined JSON/Markdown are the primary exchange artifacts. It retrieves existing
captions, not media, and is not an audio transcription or LLM inference service. Keep the PowerShell/CMD commands, standard-library Python helpers and
historical `subsdown.v4` transcript fields compatible. `VERSION` owns the product
version. `subsmerge_version: 2.0.0` is the retained merged-format marker;
`product_version` identifies this product's implementation.

README.md owns the command reference, docs/AGENT_GUIDE.md owns agent setup and
operation, AGENTS.md routes agents, and this file owns
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

## Windows CI follow-up — 2026-11-08

The first hosted Windows runs exposed a genuine short-path alias defect:
`Path.resolve()` expanded the source root while candidate paths retained 8.3
aliases such as RUNNER~1. Lexical containment checks consequently rejected valid
inputs and could bypass CLI source-output protection. Canonicalize both sides
before comparison and normalization, while checking staging parents before alias
resolution. A GetShortPathNameW regression exercises real 8.3 paths, merge output,
CLI source protection and staging exclusion. No requirement or expected result
was weakened to pass CI. The real-video bundle was also resumed successfully
through the discovered PowerShell 7 executable, with hash-verified reuse.

The corrected local integrated gate completed with 58 tests: 56 passed, two
skipped because this local volume creates no 8.3 aliases and symlink privilege
is unavailable. Hosted CI is responsible for exercising the real short-path
branch on its alias-bearing Windows environment.

The narrow follow-up review also checked a staging junction resolving back to the
source root. Lexical staging names are rejected before accepting an alias of the
root; a deterministic mocked-junction regression covers this without requiring
symlink privileges.

## Agent setup documentation — 2026-11-08

The owner requested an agent-readable installation, dependency and operation guide.
Added docs/AGENT_GUIDE.md and linked it from AGENTS.md and README.md. It separates
source checkout, existing shared-tool discovery, explicit dependency provisioning,
offline verification and authorized network retrieval. It covers batches, original
language, manual tracks, merge/resume, exit codes, result interpretation and error
recovery. Upstream Python, yt-dlp/EJS, FFmpeg and Deno documentation was read for
dependency instructions. No runtime behavior, installer or dependency changed.
The existing README remains the full command reference; the new guide owns setup
and agent workflow, avoiding a second competing option specification. This narrow
documentation task is sequential because its edits share the same routing surface.

Guide verification: local Markdown targets resolve, all five PowerShell example
blocks parse, and the existing integrated gate passes 58 tests (two local
platform-capability skips). No dependency was provisioned and no additional video
was downloaded for this documentation change.

## LLM-corpus Goal — 2026-11-08

The owner clarified the purpose: collect available transcripts from entire
playlists/channels and create a large JSON/Markdown corpus for LLM analysis, with
manual command-line use and especially agent-system integration. Whole collections
must have no arbitrary default cap. Large aggregate files are useful storage and
exchange, but the consuming LLM/agent must still respect its context window.

Read-only audits found the former presentation understated that purpose, channel
URLs were rejected, only JSON could be merged, normalized compact merges lost
caption-source provenance, transcript bodies were repeated, no structured CLI
stdout existed and no release had been published. GitHub REST reported fork=false
and no parent/source network metadata. Existing upstream attribution was real but
buried; NOTICE.md now names the modified files/revision and distinguishes their
Unlicense upstream code from MIT local modifications. Root LICENSE is standard
MIT text; detection is checked separately rather than assumed.

The owner's additional instruction requires visible AI-development disclosure.
README/NOTICE identify Codex with GPT-family models, under owner direction; no
upstream code is attributed to AI without evidence. This is provenance disclosure,
not an assertion that GitHub requires every incorporated component to be a network
fork. No history/repository recreation is needed to declare a vendored derivative.

The 0.2.0 change adds whole public channel roots and explicit upload tabs, combined
JSON/Markdown, text-only ingestion, additive normalized caption/processing
provenance, structured process reports and deterministic interpreter discovery.
The existing per-video schema and standalone merge defaults remain compatible.
Default subsdown -Merge now omits the redundant original payload; standalone merge
retains it unless NoOriginal/TextOnly is selected. Text-only changes combined
outputs only, preserving individual timed sources. MaxVideos is opt-in and its
selection scope is persisted; it is not a default bound or a paging API.

A source ZIP release with VERSION, code, docs, tests and licenses is appropriate
for Python; external runtimes remain separate. The archive/manifest/checksum
builder fixes a Git commit/tree and excludes untracked private outputs. See
RELEASING.md. No PyPI package, self-contained exe, MCP server or new framework is
introduced just to expose the already useful CLI integration seam.

Remaining scale limits are explicit: enumeration/merge materialize data in memory,
checkpoint inventories are rewritten repeatedly, networking is sequential and
YouTube can omit inaccessible content. Synthetic complete-collection tests and a
small real retrieval validate behavior, not a million-video throughput claim.
An index/sharded or streaming representation can be revisited after measured
memory/latency limits are reached; ordinary per-video artifacts already permit
selective consumption without sending the whole corpus to an LLM.

Mission routing: provenance audit Sol/high; runtime capability audit/implementation
Sol/high; merger implementation Sol/high; source packaging Terra/medium. Coordinator
owns product contracts, version, docs, attribution, integration and publication.
Requested models/efforts are recorded; confirmed runtime model, tokens and cost
are not separately exposed. Disjoint writes are used; final acceptance is freshly
verified by the coordinator rather than inferred from agent reports.

Knowledge delta: README.md, NOTICE.md, AGENTS.md, docs/AGENT_GUIDE.md,
docs/MAINTENANCE.md, docs/RELEASING.md and CHANGELOG.md. No new machine installation,
model service, repository skill, global configuration or private-media migration
is introduced. Canonical source import hashes remain unchanged.

Independent integration/release review returned CLEAR. Fresh in-memory probes
covered nested upload tabs, compact provenance/body uniqueness, Markdown metadata,
structured fatal reports and unsafe archive paths. Local documentation links and
all 11 PowerShell blocks parse successfully.

A real bounded channel-root retrieval used the public channel associated with the
owner's original video and explicitly selected two source positions. Both returned
automatic captions and exit 0. The coordinator parsed the JSON process result,
validated two compact corpus items (no embedded original or segment bodies),
retained caption provenance/source hashes, and confirmed each full text appears
once in the combined Markdown. Caption/corpus files remain ignored local evidence.
This validates actual channel entry and corpus integration, not a whole-channel
network census or a high-volume throughput benchmark. The 120-item uncapped
synthetic test verifies complete selected enumeration and actual corpus writing.

Combined corpus files are atomic individually, not as an overwrite transaction
for the whole JSON/Markdown pair. New files owned by a failed paired write are
rolled back; previously existing derived outputs are not deleted. A failed
Markdown overwrite may leave the earlier JSON replacement in place. Inspect the
nonzero status/report before treating a pair as complete. New per-run paired
outputs avoid this overwrite case; original per-video bundle publication remains
atomic as a directory.

The final coordinator gate for 0.2.0 completed with 82 tests: 80 passed and two
local platform-capability skips (symlink privilege and new 8.3 aliases). The 120
synthetic-video case writes and checks real aggregate files, using mocked network
metadata and publication inputs. The independent review returned CLEAR. Final
archive extraction and hosted CI are release acceptance steps, recorded with the
published release rather than inferred from these local results.

The first extracted-archive gate found a CMD test-harness quoting error for an
absolute batch path containing spaces. The runtime launchers were unchanged;
the test now invokes `cmd /d /c subsdown.cmd` with the extracted source directory
as its working directory, matching the documented manual workflow and avoiding
CMD's special first-quoted-argument parsing. No assertion or required behavior
was relaxed. The replacement archive must pass the full gate in that spaced path
before release publication.

## Offline index and bounded reading plans — 0.3.0

The 0.3.0 contract adds a compact per-run index and an offline CLI for existing
exports. The index includes track identity, available metadata, relative paths and
hashes, plus manifest coverage gaps; it does not embed transcript bodies. `prepare`
creates unique derived batches with a default 30,000-character Markdown budget,
including headings and citations. Whole caption tracks are preferred; consecutive segments
and oversized cue fragments preserve text without semantic deduplication. This is
a character limit, not a tokenizer or a guarantee about a model prompt or response.

Source bundles remain unchanged. Plans, report templates and accepted Markdown
are derived artifacts; status uses declared coverage and source hashes to distinguish
pending, partial, declared complete and invalidated states. A declaration is not
independent evidence that analysis occurred or that unavailable captions exist.
The Python standard library and small Windows launchers preserve the existing
local, offline workflow without a model service or new installation. `--output`
requires a new directory and report replacement requires explicit `--overwrite`.

Fresh coordinator verification: `python -X utf8 verify.py` passed 103 tests
(100 passed, three platform-capability skips) on Python 3.13.2. After final narrow
index/report regressions, `python -X utf8 -m unittest discover -s tests -p
test_batch.py -v` passed 21 tests (20 passed, one symlink-privilege skip). These
checks exercise actual PowerShell 5.1, PowerShell 7 and CMD launchers. The full
gate preceded the final copied-manifest exclusion and added regressions; the final
focused suite covers those changes. Python 3.11 and missing local 8.3/symlink
capabilities remain for hosted CI; no CI/publication result is claimed here.

A private real-corpus qualification used the 87 existing playlist tracks, retaining
two download gaps: 87 complete track parts in 50 reading batches, maximum 29,793
characters. Every segment reconstructed exactly and all source hashes remained
unchanged. A clearly labeled technical report tested partial acceptance/resume;
no new editorial analysis or complete reading was claimed. Timed cue labels add
reading overhead; the character cap bounds each file, not total inference cost.

Independent review reproduced and then verified fixes for valid tracks within a
failed item, unowned report-directory replacement, source mutation between parse
and hash, and plans omitting indexed sources. Additional seeded Unicode/CRLF/empty
cue probes reconstructed 78 fragments without loss. Review returned clear.
Report replacement expects one writer per plan. A process kill between directory
renames may leave a `.staging-prior-*` backup; status signals the interrupted
replacement and preserves that backup for recovery rather than deleting it.

Routing requested for this change: coordinator on its attached session; batch
implementation GPT-6.1 Sol/high; contract tests GPT-6.1 Sol/high; documentation
GPT-6.1 Terra/medium; independent review GPT-6 Astra/high. Requested configuration
is recorded; separate confirmed model identifiers and token/cost totals were not
exposed. Workers owned disjoint files and the coordinator ran integrated checks.

## Source publication qualification — 2026-11-08

Before the owner-authorized GitHub source update, the final installed 0.3.0
implementation passed `python -X utf8 verify.py`: 106 tests, 103 passed and three
local platform-capability skips. This full gate includes the final copied-manifest,
coverage, report-ownership and source-read-race regressions. Only this verification
record changed after the gate; no runtime or test source changed. GitHub CI remains
a separate result to check on the published commit.

## Batch test portability follow-up — 2026-11-08

The first hosted 0.3.0 source verification exposed three lexical path comparisons
in the new batch tests. Windows runners expose temporary directories through 8.3
aliases while the CLI correctly returns canonical paths. Normalize both sides in
report/output identity assertions and in the source-race injection condition. The
race test still requires the mutation to occur and preparation to reject it; user
file preservation and single-object Unicode launcher assertions remain unchanged.
This is a test-harness correction with no runtime or requirement change. Hosted
Python 3.11/3.13 verification is required to exercise the actual alias environment.
