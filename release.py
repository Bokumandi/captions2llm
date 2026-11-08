"""Build a reproducible source release from a clean Git commit."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parent
VERSION_RE = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
RESERVED = re.compile(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$")
BLOCKED = {".git", "__pycache__", ".venv", "local-evidence", "subsdown_output",
           "_tmp", ".staging", ".runs", ".indexes", ".batches"}
BLOCKED_EXTENSIONS = {".exe", ".dll", ".pyc", ".log"}


def git(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def safe_path(path: str) -> bool:
    parts = path.split("/")
    return bool(parts) and all(
        part and part not in {".", ".."} and part.casefold() not in BLOCKED
        and not RESERVED.fullmatch(part) and not part.endswith((" ", "."))
        and not any(ord(c) < 32 or c in '<>:"\\|?*' for c in part)
        and not part.casefold().startswith((".env", "subsindex-", ".staging-"))
        for part in parts
    ) and Path(parts[-1]).suffix.casefold() not in BLOCKED_EXTENSIONS


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(output: Path, ref: str) -> list[Path]:
    # Refuse tracked changes even when building an older commit; untracked files
    # cannot enter a tree-based archive.
    if git("status", "--porcelain=v1", "--untracked-files=no"):
        raise ValueError("Tracked changes present; commit or preserve them before release.")
    commit = git("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()
    tree = git("rev-parse", "--verify", commit + "^{tree}").decode().strip()
    entries = []
    names = set()
    for record in git("ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", "strict")
        if kind != "blob" or mode not in {"100644", "100755"} or not safe_path(path):
            raise ValueError("Unsafe or unsupported tracked entry: " + path)
        if path.casefold() in names:
            raise ValueError("Case-insensitive path collision: " + path)
        names.add(path.casefold())
        entries.append((path, mode, oid))
    blobs = [(path, mode, git("cat-file", "blob", oid)) for path, mode, oid in entries]
    version_data = next((data for path, _, data in blobs if path == "VERSION"), None)
    if version_data is None:
        raise ValueError("Commit has no VERSION file.")
    version = version_data.decode("utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError("VERSION must be MAJOR.MINOR.FIX.")
    prefix = f"subsdown-v{version}/"
    archive_name = f"subsdown-v{version}-source.zip"
    output.mkdir(parents=True, exist_ok=True)
    targets = [output / archive_name, output / "release-manifest.json", output / "SHA256SUMS"]
    if any(p.exists() for p in targets):
        raise FileExistsError("Release output already exists; choose an empty directory.")
    with tempfile.TemporaryDirectory() as temp:
        archive = Path(temp) / archive_name
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED,
                             compresslevel=9) as zf:
            for path, mode, data in blobs:
                info = zipfile.ZipInfo(prefix + path, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100755 if mode == "100755" else 0o100644) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                zf.writestr(info, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        archive_data = archive.read_bytes()
    manifest = {
        "version": version, "commit": commit, "tree": tree, "archive": archive_name,
        "archive_sha256": digest(archive_data),
        "requirements": "Windows; Python 3.11 or 3.13. Downloading captions also requires yt-dlp, FFmpeg and, when required by YouTube, Deno. Dependencies are not bundled.",
        "files": [{"path": path, "sha256": digest(data)} for path, _, data in blobs],
    }
    manifest_data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    sums = (f"{digest(archive_data)}  {archive_name}\n"
            f"{digest(manifest_data)}  release-manifest.json\n").encode("utf-8")
    created = []
    # Stage on the destination volume, then publish each complete file without
    # replacing any existing name. Roll back names created by this attempt.
    with tempfile.TemporaryDirectory(prefix=".release-", dir=output) as temp:
        staged = []
        for index, data in enumerate((archive_data, manifest_data, sums)):
            path = Path(temp) / str(index)
            with path.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            staged.append(path)
        try:
            for source, target in zip(staged, targets):
                os.link(source, target)
                created.append(target)
        except BaseException:
            for path in created:
                path.unlink(missing_ok=True)
            raise
    return targets


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--ref", default="HEAD", help="Git commit or ref (default: HEAD)")
    args = parser.parse_args()
    try:
        for path in build(args.output_dir, args.ref):
            print(path)
    except (OSError, ValueError, UnicodeError, subprocess.CalledProcessError) as exc:
        print(f"Release failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
