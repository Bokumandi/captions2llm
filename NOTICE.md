# Code provenance, licenses and AI assistance

## Modified upstream cleaner

Subsdown includes a modified copy of [bindestriche/srt_fix](https://github.com/bindestriche/srt_fix).
The derived files are `simplesrt.py` and `srt_fixer_cli.py`. The original local
copies matched upstream revision `5b4442a8cdcae06c53545f4d0c99c3e624416919` exactly:

| Original file | Git blob at the matching revision |
| --- | --- |
| simplesrt.py | 282c90a13ae371ca9b5ebc7f9c015b35c4655787 |
| srt_fixer_cli.py | 0a72e277b7b1bbefc9c2e67aa3e866cac66f1c89 |

The upstream code was released under the **Unlicense**. Its original notice is
preserved in [LICENSES/srt_fix-Unlicense.txt](LICENSES/srt_fix-Unlicense.txt),
Git blob `68a49daad8ff7e35068f2b7a97d643aab440eaec`.
Subsdown's original contributions and local modifications are **MIT licensed**,
copyright 2026 Bokumandi; see [LICENSE](LICENSE).

The locally maintained derivative adds strict SRT parsing, conservative rolling
caption deduplication, manual-caption preservation, validated timestamps, atomic
outputs and revised CLI behavior. The original upstream notice applies to its
code; the MIT notice applies to local contributions. Attribution does not imply
upstream review, endorsement or responsibility for Subsdown.

## Repository relationship

This is an independent application incorporating a modified upstream component,
not a GitHub-network fork of the complete srt_fix repository. The copied source
origin is declared above regardless of GitHub's repository badge. We did not import
the complete upstream Git history. This avoids claiming either that the cleaner
was created from scratch or that this repository has a network connection it lacks.
See [GitHub's fork definition](https://docs.github.com/en/pull-requests/reference/forks)
and [maintenance evidence](docs/MAINTENANCE.md).

The owner's historical download/merge wrappers were the initial local application
sources; their imported hashes are recorded in [source-imports.json](source-imports.json).
A byte match identifies matching source, not the historical acquisition method.

## AI-assisted development

Subsdown's application code, modifications, tests and documentation were generated
and reworked with **OpenAI Codex, using GPT-family models**, under the repository
owner's direction. Parallel Codex agents were used for implementation and review.
The upstream srt_fix component is credited separately: its authorship is not
attributed to Codex. The origin of any AI assistance to the historical upstream
project is unknown and is not asserted here.

The owner commissioned and directed this work; no claim is made that the owner
manually reviewed every generated line. Verification evidence consists of the
recorded automated tests, independent agent reviews and specifically identified
real runs, with their limits. See [docs/MAINTENANCE.md](docs/MAINTENANCE.md).

## Other components and content

yt-dlp, FFmpeg, Python and Deno are external runtime tools, not bundled in this
repository or the source release. Their respective licenses and installation
receipts remain with those installations. Downloaded captions retain their own
provenance; the software license does not grant rights to third-party video text.
