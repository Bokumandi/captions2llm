"""Captions2LLM command entry point; the compatible helpers own all processing."""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
VERSION = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
COMMANDS = {"download": "subsdown.py", "merge": "subsmerge.py",
            **{name: "subsbatch.py" for name in ("index", "prepare", "status", "accept-report")}}


def launch_failure(command, message, machine):
    """Keep operation schemas stable even when a helper cannot be launched."""
    code = 1 if command == "download" else 2
    if command == "download":
        result = {"schema_version": "subsdown.result.v1", "product_version": VERSION,
                  "exit_code": code, "manifest_path": None, "output_root": None,
                  "summary": {"success": 0, "unavailable": 0, "failed": 0},
                  "merged_json": None, "merged_markdown": None,
                  "index_json": None, "index_markdown": None}
    elif command == "merge":
        result = {"schema": "subsmerge.result.v1", "version": VERSION, "exit_code": code,
                  "output_json": None, "output_markdown": None, "error_log": None,
                  "item_count": 0, "ignored_count": 0, "error_count": 0}
    else:
        result = {"schema": "subsbatch.result.v1" if command in COMMANDS else "captions2llm.result.v1",
                  "version": VERSION, "command": command, "exit_code": code}
    print("ERROR: " + message, file=sys.stderr)
    if machine:
        print(json.dumps({**result, "error": message}, ensure_ascii=False))
    return code


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv in (["--help"], ["-h"]):
        print(f"Captions2LLM {VERSION}\n"
              "Usage: captions2llm.py COMMAND [arguments]\n\n"
              "Commands:\n"
              "  download       Retrieve existing YouTube captions\n"
              "  merge          Merge existing transcript exports\n"
              "  index          Inventory existing exports offline\n"
              "  prepare        Prepare bounded offline reading batches\n"
              "  status         Check a reading plan and source hashes\n"
              "  accept-report  Validate an operator report\n\n"
              "Use COMMAND --help for operation arguments.\n"
              "--version prints the product version. Legacy output names and schemas are retained.")
        return 0
    if argv == ["--version"]:
        print(f"Captions2LLM {VERSION}")
        return 0
    command, *arguments = argv
    if command not in COMMANDS:
        return launch_failure(command, f"unknown command: {command}", "--json" in argv)
    helper = ROOT / COMMANDS[command]
    if not helper.is_file():
        return launch_failure(command, f"Python helper not found: {helper}", "--json" in arguments)
    forwarded = [command, *arguments] if COMMANDS[command] == "subsbatch.py" else arguments
    try:
        return subprocess.call([sys.executable, "-X", "utf8", str(helper), *forwarded])
    except OSError as exc:
        return launch_failure(command, str(exc), "--json" in arguments)


if __name__ == "__main__":
    raise SystemExit(main())
