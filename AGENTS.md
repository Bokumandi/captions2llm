# Captions2LLM agent router

For installation or operation, read [docs/AGENT_GUIDE.md](docs/AGENT_GUIDE.md) first.
For code changes, read README.md and docs/MAINTENANCE.md before changing behavior.
This repository prepares caption-derived video corpora for LLM ingestion, using
Windows launchers and standard-library Python helpers. Read NOTICE.md for upstream
cleaner provenance, licensing scope and Codex/GPT-assisted development disclosure.
Keep legacy command entry points and the documented JSON export fields compatible.
VERSION is the single source of the product version. Keep active documentation,
comments, docstrings and tests in English. Preserve LICENSES/srt_fix-Unlicense.txt
and upstream attribution when modifying the derived cleaner.
Never include downloaded transcripts, media, credentials, raw provider metadata,
local absolute paths or logs in Git. Use synthetic fixtures in tests.
Do not install or update machine tools implicitly. Respect explicit publication
authorization and never force-push. Run python verify.py before publishing.
Use one writer per file when delegating work. Keep documentation proportional:
README.md owns the first-use path and command overview; docs/AGENT_GUIDE.md owns
agent workflows and machine contracts; docs/MAINTENANCE.md separates current
maintenance contracts and verification from dated historical records.
