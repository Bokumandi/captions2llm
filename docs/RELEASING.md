# Build and publish a source release

This guide is for maintainers. For everyday installation and commands, start with
the [README](../README.md) or [agent guide](AGENT_GUIDE.md).

A release contains source code, tests, documentation and license notices.
Install Python and any download tools separately. A release may be older than
`main`; users should follow the README included with their chosen version.

## Release files

| File | Purpose |
| --- | --- |
| `captions2llm-vVERSION-source.zip` | Source tree under `captions2llm-vVERSION/` |
| `release-manifest.json` | Commit, tree, archive hash and per-file hashes |
| `SHA256SUMS` | Checksums for the ZIP and manifest |

`VERSION` supplies the version number. The tag `vVERSION` must identify the tested
commit. Historical release assets keep their original names.

The builder reads committed Git blobs, excludes untracked files and rejects unsafe
tracked paths. It requires a clean tracked working tree, a new output location and
a build filesystem supporting hard links, such as NTFS. Installing the extracted
archive does not require hard links.

## Publish a release

1. Confirm the owner's authorization to publish a release. Read [AGENTS](../AGENTS.md)
   and [NOTICE](../NOTICE.md), then update the version and changelog as needed.
2. Run `python -X utf8 verify.py`. Review the exact staged changes and ensure no
   captions, credentials, local evidence or machine-specific paths are included.
3. Commit the tested sources. Check the GitHub account, repository, target branch
   and commit, then push with normal Git. Fetch and compare the remote commit;
   wait for its GitHub CI checks to succeed.
4. Build from that exact commit into a new local evidence directory:

```powershell
python release.py --ref HEAD --output-dir .\local-evidence\release-vVERSION
```

5. Inspect the manifest and checksums. Extract the ZIP into a fresh directory with
   spaces in its name, compare its inventory and contents with the manifest/Git,
   and run `python -X utf8 verify.py` there. The offline gate needs Windows and both
   PowerShell versions; it uses synthetic captions rather than live downloads.
6. Create the GitHub release tagged `vVERSION` at the qualified commit and upload
   all three files. Describe dependencies, tested environments and remaining
   limits. Link NOTICE and disclose the upstream cleaner and Codex/GPT assistance.
7. Download the public assets into another new directory and compare their hashes
   with the qualified files. Fetch the tag and verify its commit. Never force-move
   an existing tag.

If a step fails, preserve its evidence and fix the cause before reporting success.
Publishing repository sources and publishing a packaged release are separate
operations; a new commit on `main` does not create a release automatically.

## Install a packaged release

Download the ZIP, manifest and checksums from the same release. Check the ZIP and
manifest against `SHA256SUMS`, extract the archive and preserve its directory
structure, including VERSION and license notices. Reuse compatible installed
tools as described in the bundled README. No `pip install` or build is required.

Checksums establish file integrity; the release manifest identifies the source
commit. They do not independently validate the software or the caption content.
