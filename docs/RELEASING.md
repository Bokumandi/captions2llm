# Source releases

A Python tool can have a versioned release even when its interpreter and external
tools are installed separately. Captions2LLM distributes **source**, not a standalone
executable or bundled runtime. See [agent setup](AGENT_GUIDE.md) for dependencies.

## Release contents and trust boundary

`VERSION` is the product version. The release tag is `vMAJOR.MINOR.FIX` and points
to the exact tested commit on main. GitHub also offers automatic tag archives;
our explicit source ZIP adds a predictable prefix, file inventory, source hashes
and a separate release manifest/checksum file. New source archives are named
`captions2llm-vVERSION-source.zip` and use the `captions2llm-vVERSION` prefix.
Previously published assets retain their original names. The ZIP contains the
committed code, tests, documentation and license notices. No downloaded captions, local evidence,
credentials, external binaries, Python environment or model is included.

The release builder uses Git blobs, not an arbitrary working-directory scan, and
rejects tracked working changes or unsafe/sensitive tracked paths. The output
must be a new location; it will not overwrite earlier release artifacts. The
build output filesystem must support hard links (for example, NTFS). Installing
the finished source ZIP does not require hard-link support.

## Maintainer sequence

1. Read AGENTS.md and NOTICE.md. Confirm owner authorization to publish a release.
2. Update VERSION and CHANGELOG, documentation and regression tests with the change.
3. Run `python verify.py`; review exact tracked paths and the staged diff.
4. Commit the qualified tree. Confirm target account, repository, branch and SHA.
5. Push with normal Git; fetch and compare remote SHA; require CI success on it.
6. Build source assets from that exact commit:

```powershell
python release.py --ref HEAD --output-dir .\local-evidence\release-vVERSION
```

7. Inspect the manifest and SHA256SUMS. Extract the ZIP into a new path with spaces,
   verify inventory/content against Git and run `python verify.py` from the archive.
   Offline verification requires Windows and both PowerShell versions; running
   the product has the smaller dependency set described in the agent guide.
8. Create the GitHub release with tag `vVERSION` targeting the qualified commit,
   upload all three assets, and state external dependency and validation limits.
9. Download the public assets into a new directory, compare SHA-256 with the local
   qualified assets, fetch the tag and verify its commit. Do not force-move tags.

Keep generated files in ignored local evidence or an explicitly selected external
output directory. Never commit them just to create a release. Do not upload raw
network logs or captions as release proof. If a step fails, keep its evidence and
correct the cause before claiming publication complete.

## Installing an asset

Download the versioned source ZIP, release manifest and SHA256SUMS from the same
release. Verify the ZIP checksum, extract it and preserve its directory structure.
The adjacent VERSION/modules/license files are needed. Reuse installed Python,
yt-dlp, FFmpeg and Deno as applicable. No `pip install` or build step is required.
Run the offline gate when both verification shells are available; a task can then
invoke PowerShell launchers or Python CLI by full path without a system install.

## AI and source provenance

Release notes must link NOTICE.md and disclose the modified upstream cleaner and
Codex/GPT-assisted development. The archive manifest fixes source identity; it is
not a claim that generated code or captions are independently fact-checked.
