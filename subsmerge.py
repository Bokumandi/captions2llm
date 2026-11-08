#!/usr/bin/env python3
# subsmerge.py
# Recursively merge subsdown JSON subtitle files into one LLM-friendly JSON file.

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from common import VERSION, atomic_write_json, atomic_write_text, sha256


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


def normalize_item(obj: Any, source_file: Path, source_root: Path, include_original: bool, include_all_json: bool, text_only: bool = False) -> Optional[Dict[str, Any]]:
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
            if include_original and not text_only:
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

    # Keep track provenance even when the large original record is omitted.
    subtitle_metadata = obj.get("subtitle")
    if isinstance(subtitle_metadata, dict):
        for key, value in subtitle_metadata.items():
            if key not in {"language", "segment_count", "segments", "plain_text", "text"}:
                item["subtitle"][key] = value
    for key in ("kind", "origin", "translated"):
        if key not in item["subtitle"]:
            value = first_value(obj, ["subtitle_" + key, key], None)
            if value is not None:
                item["subtitle"][key] = value
    for key in ("processing", "tool_versions", "product_version"):
        if key in obj:
            item[key] = obj[key]
    for key in ("schema_version", "type", "created_at"):
        if key in obj:
            item["source_" + key] = obj[key]
    item["source_sha256"] = sha256(source_file)
    if text_only:
        item.pop("segments", None)
    elif include_original:
        item["original"] = obj

    return item


def is_merged_dataset(obj: Any) -> bool:
    """Recognize merger outputs independently of their filename."""
    return isinstance(obj, dict) and "subsmerge_version" in obj and isinstance(obj.get("items"), list)


def is_batch_artifact(obj: Any) -> bool:
    """Exclude derived corpus indexes, plans and reports even at custom paths."""
    return isinstance(obj, dict) and str(obj.get("schema_version", obj.get("schema", ""))).startswith("subsbatch.")


def eligible_path(path: Path, source_root: Path) -> bool:
    """Keep inputs inside the source tree and out of private staging folders."""
    staging_names = {".runs", "_tmp", ".staging", ".indexes", ".batches"}
    try:
        source_root = source_root.resolve()
        relative = path.resolve().relative_to(source_root)
        if any(part.lower() in staging_names or part.lower().startswith('.staging-')
               for part in relative.parts[:-1]):
            return False
        # Inspect original parents too: resolving a symlink must not hide a
        # staging directory. Resolved comparisons also accept Windows 8.3 aliases.
        for parent in path.absolute().parents:
            if parent.name.lower() in staging_names or parent.name.lower().startswith('.staging-'):
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
        if name.startswith(("subsmerge-", "subsindex-")) or name in {"subsmerge.json", "manifest.json"}:
            continue
        if output_resolved and path.resolve() in {output_resolved, output_resolved.with_suffix(".errors.json")}:
            continue
        files.append(path)
    return sorted(files, key=lambda p: str(p).lower())


MARKDOWN_MARKER = "<!-- subsmerge.markdown.v1 -->"


def same_path(left: Path, right: Path) -> bool:
    return left.resolve() == right.resolve() or (
        left.exists() and right.exists() and left.samefile(right))


def known_output(path: Path, kind: str) -> bool:
    """Only recognized derived files may be replaced within the input tree."""
    try:
        if kind == "markdown":
            with path.open(encoding="utf-8-sig") as stream:
                return stream.readline().strip() == MARKDOWN_MARKER
        obj = read_json(path)
        if kind == "json":
            return is_merged_dataset(obj)
        return (isinstance(obj, dict) and isinstance(obj.get("errors"), list)
                and "error_count" in obj and "source_folder" in obj)
    except (OSError, ValueError, TypeError, RecursionError):
        return False


def preflight_destinations(folder: Path, candidates: List[Path],
                           targets: List[Tuple[Path, str]], overwrite: bool) -> None:
    """Check every destination before writing any part of a merged corpus."""
    for index, (target, kind) in enumerate(targets):
        if any(same_path(target, other) for other, _ in targets[:index]):
            raise ValueError("JSON, Markdown and error-log destinations must be distinct")
        if any(same_path(target, source) for source in candidates):
            raise ValueError("output or error log is also a source file")
        if target.is_dir():
            raise ValueError(f"output is a directory: {target}")
        if target.exists():
            # Discovery excludes merger destinations. Do not let that hide an
            # existing transcript or its sibling Markdown from source protection.
            in_source_tree = (target.resolve().is_relative_to(folder)
                              or target.absolute().is_relative_to(folder))
            if in_source_tree and not known_output(target, kind):
                raise ValueError(f"output names an existing source file: {target}")
            if not overwrite:
                raise FileExistsError(f"output exists (use --overwrite): {target}")
            # A destination outside the tree can still be a hardlink/symlink to
            # an input that was not included in this explicit subset.
            for source in folder.rglob("*"):
                if source.is_file() and same_path(source, target):
                    if not in_source_tree or source.resolve() != target.resolve():
                        raise ValueError("output aliases a file in the source tree")
        parent = target.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if not parent.is_dir():
            raise ValueError(f"output parent is not a directory: {parent}")


def markdown_dataset(items: List[Dict[str, Any]], text_only: bool) -> str:
    """Render the exact normalized JSON subset, without repeating its text."""
    def label(value: Any) -> str:
        if value is None or value == "":
            return "unknown"
        if isinstance(value, bool):
            return str(value).lower()
        return str(value).replace("\r", " ").replace("\n", " ")

    lines = [MARKDOWN_MARKER, "# Subtitle corpus", "", f"Videos/tracks: {len(items)}", ""]
    for number, item in enumerate(items, 1):
        subtitle = item.get("subtitle", {})
        lines.extend(["---", "", f"## {number}. {label(item.get('title'))}", "",
                      "- Channel: " + label(item.get("channel")),
                      "- URL: " + label(item.get("url")),
                      "- Video ID: " + label(item.get("video_id")),
                      "- Language: " + label(subtitle.get("language")),
                      "- Caption kind: " + label(subtitle.get("kind")),
                      "- Caption origin: " + label(subtitle.get("origin")),
                      "- Translated: " + label(subtitle.get("translated")),
                      "- Source file: " + label(item.get("source_relative_path")),
                      "- Source SHA-256: " + label(item.get("source_sha256")), ""])
        segments = item.get("segments", [])
        if segments and not text_only:
            for segment in segments:
                start, end = segment.get("start"), segment.get("end")
                timing = "[" + label(start) + " --> " + label(end) + "] " if start or end else ""
                lines.extend([timing + str(segment.get("text", "")), ""])
        else:
            lines.extend([str(item.get("text", "")), ""])
    return "\n".join(lines).rstrip() + "\n"


def merge_files(paths: List[Path], source_root: Path, output_path: Path, *,
                pretty: bool = False, include_original: bool = True,
                include_all_json: bool = False, fail_on_error: bool = False,
                overwrite: bool = False, markdown_output: Optional[Path] = None,
                text_only: bool = False, report: Optional[Dict[str, Any]] = None) -> int:
    """Merge supplied files; preserve the legacy integer status and JSON defaults.

    Outputs are atomic per file. On a paired-write failure only newly created
    files from this call may be removed; existing derived files are never deleted.
    """
    result = report if report is not None else {}
    result.update({"schema": "subsmerge.result.v1", "version": VERSION,
                   "exit_code": 2, "output_json": None, "output_markdown": None,
                   "error_log": None, "item_count": 0, "ignored_count": 0,
                   "error_count": 0, "text_only": text_only})

    def finish(code: int, error: Optional[str] = None) -> int:
        result["exit_code"] = code
        if error:
            result["error"] = error
            print("ERROR: " + error, file=sys.stderr)
        return code

    try:
        folder = Path(source_root).expanduser().resolve()
        output_path = Path(output_path).expanduser().absolute()
        markdown_path = Path(markdown_output).expanduser().absolute() if markdown_output is not None else None
        error_path = output_path.with_suffix(".errors.json")
        if not folder.is_dir():
            raise ValueError("source folder does not exist or is not a directory")
        candidates: List[Path] = []
        seen = set()
        for supplied in paths:
            path = Path(supplied).expanduser().absolute()
            if not eligible_path(path, folder):
                raise ValueError(f"input is outside the source tree or in staging: {path}")
            path = path.resolve()
            if path not in seen:
                candidates.append(path)
                seen.add(path)
        targets = [(output_path, "json"), (error_path, "errors")]
        if markdown_path is not None:
            targets.append((markdown_path, "markdown"))
        preflight_destinations(folder, candidates, targets, overwrite)
    except (OSError, ValueError, RuntimeError) as exc:
        return finish(2, str(exc))

    items: List[Dict[str, Any]] = []
    ignored: List[Dict[str, str]] = []
    errors: List[Dict[str, str]] = []
    for path in candidates:
        try:
            data = read_json(path)
            if is_merged_dataset(data) or is_batch_artifact(data):
                ignored.append({"file": str(path), "reason": "derived corpus artifact"})
                continue
            item = normalize_item(data, path, folder, include_original, include_all_json, text_only)
            if item is None:
                ignored.append({"file": str(path), "reason": "valid JSON but not recognized as a subsdown subtitle export"})
            else:
                items.append(item)
        except (OSError, ValueError, TypeError, RecursionError) as exc:
            errors.append({"file": str(path), "error": f"{type(exc).__name__}: {exc}"})

    result.update(item_count=len(items), ignored_count=len(ignored), error_count=len(errors))
    print(f"JSON integrated: {len(items)}; ignored: {len(ignored)}; read errors: {len(errors)}")
    if errors:
        try:
            atomic_write_json(error_path, {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_folder": str(folder), "error_count": len(errors), "errors": errors,
            }, overwrite=overwrite)
        except (OSError, ValueError) as exc:
            return finish(2, f"could not write error log: {exc}")
        result["error_log"] = str(error_path)
        print(f"Error log: {error_path}")
    if fail_on_error and errors:
        return finish(3, "some JSON files could not be read and --fail-on-error is active.")
    if not items:
        return finish(4, "no subtitle JSON could be integrated.")

    def sort_key(item: Dict[str, Any]) -> Tuple[int, str, str]:
        try:
            idx_int = int(item.get("playlist", {}).get("index"))
        except (ValueError, TypeError, OverflowError):
            idx_int = 10**9
        return (idx_int, str(item.get("title", "")).lower(), str(item.get("source_relative_path", "")).lower())

    items.sort(key=sort_key)
    payload: Dict[str, Any] = {
        "subsmerge_version": "2.0.0", "product_version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_folder": str(folder), "source_folder_name": folder.name,
        "item_count": len(items), "ignored_count": len(ignored), "error_count": len(errors),
        "items": items,
    }
    if ignored:
        payload["ignored"] = ignored
    if errors:
        payload["errors"] = errors
    # Build both representations before touching destinations (e.g. reject
    # non-finite JSON values without creating a Markdown-only corpus).
    created: List[Tuple[Path, Any, str]] = []
    try:
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
        markdown = markdown_dataset(items, text_only) if markdown_path is not None else None
        destinations = [(output_path, "output_json")]
        if markdown_path is not None:
            destinations.append((markdown_path, "output_markdown"))
        for target, key in destinations:
            existed = target.exists()
            if key == "output_json":
                atomic_write_json(target, payload, overwrite=overwrite, pretty=pretty)
            else:
                atomic_write_text(target, markdown, overwrite=overwrite)
            result[key] = str(target)
            if not existed:
                created.append((target, target.stat(), key))
    except (OSError, ValueError, TypeError) as exc:
        # Never unlink a previous output or a path replaced by another writer.
        for target, identity, key in created:
            try:
                current = target.stat()
                if (current.st_dev, current.st_ino, current.st_mtime_ns, current.st_size) == (
                        identity.st_dev, identity.st_ino, identity.st_mtime_ns, identity.st_size):
                    target.unlink()
                    result[key] = None
            except OSError:
                pass
        return finish(2, f"could not write merged corpus: {exc}")
    print(f"Merged JSON: {output_path}")
    if markdown_path is not None:
        print(f"Merged Markdown: {markdown_path}")
    return finish(0)


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    machine = "--json" in argv
    report: Dict[str, Any] = {"schema": "subsmerge.result.v1", "version": VERSION,
                              "exit_code": 2, "output_json": None, "output_markdown": None,
                              "error_log": None, "item_count": 0, "ignored_count": 0,
                              "error_count": 0}
    parser = argparse.ArgumentParser(description="Captions2LLM: merge subtitle JSON files recursively into an LLM corpus (legacy subsmerge entry point).")
    parser.add_argument("folder", help="Folder containing subsdown JSON files")
    parser.add_argument("-o", "--output", help="Output JSON path. Default: ./subsmerge-[folder].json")
    parser.add_argument("--markdown-output", help="Also write the same corpus as Markdown")
    parser.add_argument("--text-only", action="store_true", help="Keep transcript text once; omit original JSON and segment text")
    parser.add_argument("--json", action="store_true", help="Write one machine-readable result object to stdout; progress goes to stderr")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON")
    parser.add_argument("--include-all-json", action="store_true", help="Include every valid JSON file, even if it does not look like subsdown")
    parser.add_argument("--no-original", action="store_true", help="Do not embed each source JSON inside item.original")
    parser.add_argument("--fail-on-error", action="store_true", help="Fail if any JSON file cannot be read")
    parser.add_argument("--overwrite", action="store_true", help="Replace an existing output or error log")

    def run() -> int:
        try:
            args = parser.parse_args(argv)
            folder = Path(args.folder).expanduser().resolve()
            if not folder.is_dir():
                raise ValueError(f"source folder does not exist or is not a directory: {folder}")
            output_path = Path(args.output).expanduser().absolute() if args.output else Path.cwd() / f"subsmerge-{safe_filename(folder.name)}.json"
            candidates = find_json_files(folder, output_path)
            return merge_files(candidates, folder, output_path, pretty=args.pretty,
                               include_original=not args.no_original, text_only=args.text_only,
                               markdown_output=args.markdown_output,
                               include_all_json=args.include_all_json,
                               fail_on_error=args.fail_on_error, overwrite=args.overwrite, report=report)
        except SystemExit as exc:
            report["exit_code"] = int(exc.code)
            if exc.code:
                report["error"] = "invalid command arguments"
            return int(exc.code)
        except (OSError, ValueError, TypeError, RuntimeError, RecursionError) as exc:
            report.update(exit_code=2, error=str(exc))
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

    if machine:
        with redirect_stdout(sys.stderr):
            code = run()
        print(json.dumps(report, ensure_ascii=False, allow_nan=False))
        return code
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
