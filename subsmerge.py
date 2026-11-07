#!/usr/bin/env python3
# subsmerge.py
# Recursively merge subsdown JSON subtitle files into one LLM-friendly JSON file.

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import VERSION, atomic_write_json


def safe_filename(text: str, max_len: int = 140) -> str:
    text = str(text or "folder").strip()
    text = re.sub(r'[<>:"/\\|?*\x00-\x1F]', " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        text = "folder"
    if len(text) > max_len:
        text = text[:max_len].rstrip(" .")
    return text or "folder"


def read_json(path: Path) -> Any:
    # utf-8-sig handles UTF-8 with or without BOM.
    text = path.read_text(encoding="utf-8-sig")

    # Be forgiving if a file has accidental leading characters before JSON.
    stripped = text.lstrip()
    if stripped and stripped[0] not in "[{":
        first_obj = min([i for i in [stripped.find("{"), stripped.find("[")] if i >= 0], default=-1)
        if first_obj >= 0:
            stripped = stripped[first_obj:]

    return json.loads(stripped)


def get_nested(obj: Any, path: str, default: Any = None) -> Any:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part, default)
        else:
            return default
        if cur is None:
            return default
    return cur


def first_value(obj: Any, paths: List[str], default: Any = None) -> Any:
    for path in paths:
        val = get_nested(obj, path, None)
        if val is not None and val != "":
            return val
    return default


def looks_like_subsdown(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False

    schema = str(obj.get("schema_version", ""))
    typ = str(obj.get("type", ""))

    if schema.startswith("subsdown"):
        return True
    if typ == "YouTubeSubtitleTranscript":
        return True
    if isinstance(obj.get("video"), dict) and isinstance(obj.get("transcript"), dict):
        return True
    if isinstance(obj.get("subtitle"), dict) and isinstance(obj.get("transcript"), dict):
        return True

    return False


def normalize_segments(segments: Any) -> List[Dict[str, Any]]:
    if not isinstance(segments, list):
        return []

    out: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments, start=1):
        if isinstance(seg, dict):
            out.append({
                "index": seg.get("index", idx),
                "start": seg.get("start", ""),
                "end": seg.get("end", ""),
                "text": seg.get("text", ""),
            })
        else:
            out.append({
                "index": idx,
                "start": "",
                "end": "",
                "text": str(seg),
            })
    return out


def normalize_item(obj: Any, source_file: Path, source_root: Path, include_original: bool, include_all_json: bool) -> Optional[Dict[str, Any]]:
    source_file = source_file.resolve()
    source_root = source_root.resolve()
    if not isinstance(obj, dict):
        if include_all_json:
            item = {
                "source_file": str(source_file),
                "source_relative_path": str(source_file.relative_to(source_root)),
                "file_name": source_file.name,
                "recognized_as": "generic_json_non_object",
            }
            if include_original:
                item["original"] = obj
            return item
        return None

    recognized = looks_like_subsdown(obj)
    if not recognized and not include_all_json:
        return None

    segments = normalize_segments(first_value(obj, ["transcript.segments", "subtitle.segments"], []))
    plain_text = first_value(obj, ["transcript.plain_text", "subtitle.plain_text", "text", "plain_text"], "")
    if not plain_text and segments:
        plain_text = "\n".join(str(seg.get("text", "")) for seg in segments).strip()

    title = first_value(obj, ["video.title", "title", "metadata.title"], source_file.stem)
    channel = first_value(obj, ["video.channel", "channel", "uploader", "metadata.channel"], "")
    url = first_value(obj, ["video.url_clean", "video.url", "url", "webpage_url", "metadata.url"], "")
    video_id = first_value(obj, ["video.id", "youtube_id", "video_id", "id"], "")
    playlist_title = first_value(obj, ["playlist.title", "playlist_title"], "")
    playlist_id = first_value(obj, ["playlist.id", "playlist_id"], "")
    playlist_index = first_value(obj, ["playlist.index", "playlist_index"], None)
    subtitle_language = first_value(obj, ["subtitle.language", "language", "subtitle_language"], "")

    item: Dict[str, Any] = {
        "source_file": str(source_file),
        "source_relative_path": str(source_file.relative_to(source_root)),
        "file_name": source_file.name,
        "recognized_as": "subsdown" if recognized else "generic_json",
        "title": title,
        "channel": channel,
        "url": url,
        "video_id": video_id,
        "playlist": {
            "title": playlist_title,
            "id": playlist_id,
            "index": playlist_index,
        },
        "subtitle": {
            "language": subtitle_language,
            "segment_count": len(segments) if segments else first_value(obj, ["transcript.segment_count", "subtitle.segment_count"], 0),
        },
        "text": plain_text,
        "segments": segments,
    }

    if include_original:
        item["original"] = obj

    return item


def is_merged_dataset(obj: Any) -> bool:
    """Recognize merger outputs independently of their filename."""
    return isinstance(obj, dict) and "subsmerge_version" in obj and isinstance(obj.get("items"), list)


def eligible_path(path: Path, source_root: Path) -> bool:
    """Keep inputs inside the source tree and out of private staging folders."""
    staging_names = {".runs", "_tmp", ".staging"}
    try:
        source_root = source_root.resolve()
        relative = path.resolve().relative_to(source_root)
        if any(part.lower() in staging_names for part in relative.parts[:-1]):
            return False
        # Inspect original parents too: resolving a symlink must not hide a
        # staging directory. Resolved comparisons also accept Windows 8.3 aliases.
        for parent in path.absolute().parents:
            if parent.name.lower() in staging_names:
                return False
            if parent.resolve() == source_root:
                return True
    except (ValueError, OSError, RuntimeError):
        return False
    return False


def find_json_files(folder: Path, output_path: Optional[Path]) -> List[Path]:
    folder = folder.resolve()
    output_resolved = output_path.resolve() if output_path else None
    files = []
    for path in folder.rglob("*"):
        if path.suffix.lower() != ".json" or not path.is_file() or not eligible_path(path, folder):
            continue
        name = path.name.lower()
        if name.startswith("subsmerge-") or name in {"subsmerge.json", "manifest.json"}:
            continue
        if output_resolved and path.resolve() in {output_resolved, output_resolved.with_suffix(".errors.json")}:
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


def merge_files(paths: List[Path], source_root: Path, output_path: Path, *,
                pretty: bool = False, include_original: bool = True,
                include_all_json: bool = False, fail_on_error: bool = False,
                overwrite: bool = False) -> int:
    """Merge only the supplied files; return the same status as the CLI."""
    try:
        folder = Path(source_root).expanduser().resolve()
        output_path = Path(output_path).expanduser().absolute()
        if not folder.is_dir():
            raise ValueError("source folder does not exist or is not a directory")
        candidates = []
        seen = set()
        for supplied in paths:
            path = Path(supplied).expanduser().absolute()
            if not eligible_path(path, folder):
                raise ValueError(f"input is outside the source tree or in staging: {path}")
            path = path.resolve()
            resolved = path
            targets = (output_path, output_path.with_suffix(".errors.json"))
            if any(resolved == target.resolve() or
                   (path.exists() and target.exists() and path.samefile(target))
                   for target in targets):
                raise ValueError("output or error log is also a source file")
            # Use canonical paths for deduplication and source-relative metadata.
            if resolved not in seen:
                candidates.append(path)
                seen.add(resolved)
        if output_path.exists() and not overwrite:
            raise FileExistsError(f"output exists (use --overwrite): {output_path}")
        if output_path.is_dir():
            raise ValueError("output is a directory")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    items: List[Dict[str, Any]] = []
    ignored: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    for path in candidates:
        try:
            data = read_json(path)
            if is_merged_dataset(data):
                ignored.append({"file": str(path), "reason": "already a merged dataset"})
                continue
            item = normalize_item(data, path, folder, include_original, include_all_json)
            if item is None:
                ignored.append({"file": str(path), "reason": "valid JSON but not recognized as a subsdown subtitle export"})
            else:
                items.append(item)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})

    print(f"JSON integrated: {len(items)}; ignored: {len(ignored)}; read errors: {len(errors)}")
    if errors:
        err_path = output_path.with_suffix(".errors.json")
        try:
            atomic_write_json(err_path, {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_folder": str(folder), "error_count": len(errors), "errors": errors,
            }, overwrite=overwrite)
        except (OSError, ValueError) as exc:
            print(f"ERROR: could not write error log: {exc}", file=sys.stderr)
            return 2
        print(f"Error log: {err_path}")
    if fail_on_error and errors:
        print("ERROR: some JSON files could not be read and --fail-on-error is active.", file=sys.stderr)
        return 3
    if not items:
        print("ERROR: no subtitle JSON could be integrated.", file=sys.stderr)
        return 4

    def sort_key(item: Dict[str, Any]) -> Tuple[int, str, str]:
        try:
            idx_int = int(item.get("playlist", {}).get("index"))
        except (ValueError, TypeError, OverflowError):
            idx_int = 10**9
        return (idx_int, str(item.get("title", "")).lower(), str(item.get("source_relative_path", "")).lower())

    payload: Dict[str, Any] = {
        "subsmerge_version": "2.0.0",
        "product_version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": str(folder), "source_folder_name": folder.name,
        "item_count": len(items), "ignored_count": len(ignored), "error_count": len(errors),
        "items": sorted(items, key=sort_key),
    }
    if ignored:
        payload["ignored"] = ignored
    if errors:
        payload["errors"] = errors
    try:
        atomic_write_json(output_path, payload, overwrite=overwrite, pretty=pretty)
    except (OSError, ValueError) as exc:
        print(f"ERROR: could not write merged JSON: {exc}", file=sys.stderr)
        return 2
    print(f"Merged JSON: {output_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Merge subsdown JSON subtitle files recursively into one JSON.")
    parser.add_argument("folder", help="Folder containing subsdown JSON files")
    parser.add_argument("-o", "--output", help="Output JSON path. Default: ./subsmerge-[folder].json")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--include-all-json", action="store_true", help="Include every valid JSON file, even if it does not look like subsdown")
    parser.add_argument("--no-original", action="store_true", help="Do not embed each source JSON inside item.original")
    parser.add_argument("--fail-on-error", action="store_true", help="Fail if any JSON file cannot be read")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output or error log")
    args = parser.parse_args()
    try:
        folder = Path(args.folder).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError(f"source folder does not exist or is not a directory: {folder}")
        output_path = Path(args.output).expanduser().absolute() if args.output else Path.cwd() / f"subsmerge-{safe_filename(folder.name)}.json"
        # An overwrite flag never authorizes replacing a source transcript.
        if output_path.exists() and eligible_path(output_path, folder):
            try:
                existing = read_json(output_path)
            except (OSError, ValueError):
                existing = None
            if not is_merged_dataset(existing):
                raise ValueError("output names an existing source file")
        err_path = output_path.with_suffix(".errors.json")
        if err_path.exists() and eligible_path(err_path, folder):
            try:
                previous_errors = read_json(err_path)
            except (OSError, ValueError):
                previous_errors = None
            if not (isinstance(previous_errors, dict) and
                    isinstance(previous_errors.get("errors"), list) and
                    "error_count" in previous_errors and "source_folder" in previous_errors):
                raise ValueError("error log names an existing source file")
        candidates = find_json_files(folder, output_path)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return merge_files(candidates, folder, output_path, pretty=args.pretty,
                       include_original=not args.no_original,
                       include_all_json=args.include_all_json,
                       fail_on_error=args.fail_on_error, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
