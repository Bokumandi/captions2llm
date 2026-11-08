# Provenance, licenses and AI-assisted development

## Upstream cleaner

Captions2LLM includes a modified copy of
[bindestriche/srt_fix](https://github.com/bindestriche/srt_fix), released under
the **Unlicense**. The derived files are `simplesrt.py` and `srt_fixer_cli.py`.
Their original local copies matched upstream revision
`5b4442a8cdcae06c53545f4d0c99c3e624416919`:

| Original file | Git blob at that revision |
| --- | --- |
| `simplesrt.py` | `282c90a13ae371ca9b5ebc7f9c015b35c4655787` |
| `srt_fixer_cli.py` | `0a72e277b7b1bbefc9c2e67aa3e866cac66f1c89` |

The original notice is preserved in
[LICENSES/srt_fix-Unlicense.txt](LICENSES/srt_fix-Unlicense.txt), Git blob
`68a49daad8ff7e35068f2b7a97d643aab440eaec`.

Local changes add stricter SRT validation, conservative removal of rolling-caption
repeats, preservation of manual captions and atomic file writes. Captions2LLM is
an independent application incorporating this component; its repository was not
created as a GitHub-network fork of the full upstream repository. Attribution
does not imply upstream review or endorsement.

## Local contributions

Captions2LLM's own contributions and local modifications are **MIT licensed**,
copyright 2026 Bokumandi. See [LICENSE](LICENSE). The upstream notice remains
applicable to the incorporated upstream code.

The original local download and merge scripts are recorded with their import
hashes in [source-imports.json](source-imports.json). Those records describe the
imported files; a byte match establishes source identity, not how a historical
copy was acquired. [Maintenance](docs/MAINTENANCE.md) records subsequent decisions
and verification.

## AI-assisted development

Application code, modifications, tests and documentation were generated and
reworked with **OpenAI Codex, using GPT-family models**, under the repository
owner's direction. Parallel Codex agents contributed to implementation and review.
The upstream `srt_fix` authorship is credited separately and is not attributed
to Codex.

Verification evidence consists of the tests, agent reviews and identified real
runs recorded in maintenance, with their stated limits. AI assistance does not
establish correctness by itself.

## External tools and caption content

Python, yt-dlp, FFmpeg and Deno are external tools, not bundled dependencies.
Their licenses apply to their respective distributions. Downloaded captions
retain their own provenance; the software licenses do not grant rights to
third-party video text.
