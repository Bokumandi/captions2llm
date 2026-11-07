"""Small shared primitives for durable, UTF-8 subtitle outputs."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata

VERSION = Path(__file__).with_name("VERSION").read_text(encoding="utf-8").strip()

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def safe_filename(text: str, max_len: int = 80) -> str:
    value = unicodedata.normalize("NFC", str(text or "untitled"))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")[:max_len].rstrip(" .") or "untitled"
    if re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", value, re.I):
        value = "_" + value
    return value[:max_len]

def atomic_write_text(path: Path, text: str, *, overwrite: bool = False) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".write-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        elif os.name == "nt":
            os.rename(temporary, path)
        else:
            os.link(temporary, path)
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)

def atomic_write_json(path: Path, value, *, overwrite: bool = False, pretty: bool = True) -> None:
    text = json.dumps(value, ensure_ascii=False, indent=2 if pretty else None,
                      separators=None if pretty else (",", ":"), allow_nan=False)
    atomic_write_text(path, text + "\n", overwrite=overwrite)
