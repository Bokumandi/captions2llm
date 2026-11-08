#!/usr/bin/env python3
"""Captions2LLM offline corpus indexing, bounded reading batches and agent reports."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import shutil
import sys
import tempfile
import uuid

from common import VERSION, atomic_write_json, atomic_write_text, sha256
from subsmerge import find_json_files, normalize_item, read_json, is_merged_dataset

INDEX_SCHEMA = "subsbatch.index.v1"
PLAN_SCHEMA = "subsbatch.plan.v1"
REPORT_SCHEMA = "subsbatch.report.v1"
EXCLUDED = {".runs", "_tmp", ".staging", ".indexes", ".batches", "reports"}


def is_batch_artifact(obj):
    return isinstance(obj, dict) and any(str(obj.get(key, "")).startswith("subsbatch.")
                                         for key in ("schema", "schema_version"))


def _is_collection_metadata(obj):
    return isinstance(obj, dict) and str(obj.get('schema_version', '')).startswith(
        ('subsdown.run.', 'subsdown.result.'))


def _now():
    return datetime.now(timezone.utc).isoformat()


def _id(prefix, value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode("utf-8")
    return prefix + hashlib.sha256(encoded).hexdigest()[:24]


def _inside(root, relative):
    """Resolve an untrusted relative artifact reference without accepting escapes."""
    if not isinstance(relative, str) or not relative or "\\" in relative:
        raise ValueError("artifact path must be a nonempty relative POSIX path")
    path = Path(relative)
    if path.is_absolute() or PureWindowsPath(relative).drive or ".." in path.parts:
        raise ValueError("artifact path escapes its root")
    root = Path(root).resolve()
    result = (root / path).resolve()
    if not result.is_relative_to(root):
        raise ValueError("artifact path escapes its root")
    return result


def _export_path(root, value):
    # Historical manifests use Windows separators; normalize before validation.
    if not isinstance(value, str):
        raise ValueError("export path must be a string")
    normalized = value.replace("\\", "/")
    path = _inside(root, normalized)
    if any(part.lower() in EXCLUDED or part.lower().startswith(".staging-")
           for part in Path(normalized).parts[:-1]):
        raise ValueError("export is in a generated or staging directory")
    return path


def _load_item(path, root):
    before_hash = sha256(path)
    obj = read_json(path)
    if is_merged_dataset(obj) or is_batch_artifact(obj) or _is_collection_metadata(obj):
        raise ValueError("derived artifact is not a transcript export")
    item = normalize_item(obj, path, root, False, False)
    if item is None:
        raise ValueError("not a recognized subtitle export")
    if item["source_sha256"] != before_hash or sha256(path) != before_hash:
        raise ValueError("source changed while reading transcript")
    item.pop("source_file", None)
    item["source_relative_path"] = path.resolve().relative_to(root).as_posix()
    video = obj.get("video") if isinstance(obj.get("video"), dict) else {}
    item["upload_date"] = video.get("upload_date")
    item["duration_seconds"] = video.get("duration_seconds")
    item["source_paths"] = {"json": item["source_relative_path"]}
    for extension, key in ((".md", "markdown"), (".srt", "srt")):
        sibling = path.with_suffix(extension)
        item["source_paths"][key] = (sibling.resolve().relative_to(root).as_posix()
                                     if sibling.is_file() and sibling.resolve().is_relative_to(root) else None)
    item["item_id"] = _id("track-", [item.get("video_id"), item["subtitle"],
                                     item["source_relative_path"], item["source_sha256"]])
    return item


def _inventory(root, manifest=None):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("source root must be an existing directory")
    errors, gaps, candidates = [], [], []
    coverage = {"mode": "folder", "selected_count": None, "gaps": gaps}
    if manifest is not None:
        manifest = read_json(Path(manifest)) if not isinstance(manifest, dict) else manifest
        if not isinstance(manifest, dict) or manifest.get("schema_version") != "subsdown.run.v1":
            raise ValueError("unsupported run manifest")
        entries = manifest.get("items")
        if not isinstance(entries, list):
            raise ValueError("manifest items must be a list")
        coverage.update(mode="manifest", selected_count=len(entries),
                        selection=manifest.get("selection", {}),
                        enumeration_pending=len(manifest.get("enumeration_targets", [])))
        for ordinal, entry in enumerate(entries, 1):
            if not isinstance(entry, dict):
                raise ValueError("manifest item must be an object")
            gap = {"ordinal": ordinal, "key": entry.get("key"), "url": entry.get("url"),
                   "status": entry.get("status", "missing"), "message": entry.get("message", "")}
            if entry.get("status") != "success":
                gaps.append(gap)
                if not entry.get("exports"):
                    continue
            try:
                exports = entry.get("exports")
                if not isinstance(exports, list) or not exports:
                    raise ValueError("successful manifest item has no exports")
                verified = []
                for export in exports:
                    path = _export_path(root, export["path"])
                    if not path.is_file() or sha256(path) != export["sha256"]:
                        raise ValueError("export missing or hash mismatch: " + str(export["path"]))
                    if path.suffix.lower() == ".json":
                        verified.append(path)
                if not verified:
                    raise ValueError("successful manifest item has no JSON export")
                candidates.extend(verified)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                if entry.get("status") == "success":
                    gap.update(status="invalidated", message=str(exc))
                    gaps.append(gap)
                errors.append({"key": entry.get("key"), "error": str(exc)})
        completed_keys = {entry.get("key") for entry in entries}
        pending = []
        for target in manifest.get("expanded_targets", []):
            if not isinstance(target, dict) or not isinstance(target.get("url"), str):
                raise ValueError("invalid expanded manifest target")
            key = target["url"] + "|" + str((target.get("playlist") or {}).get("id") or "")
            if key not in completed_keys and target["url"] not in completed_keys:
                pending.append({"ordinal": len(entries) + len(pending) + 1, "key": key,
                                "url": target["url"], "status": "pending",
                                "message": "Selected target has no current-run result"})
        gaps.extend(pending)
        coverage["pending_count"] = len(pending)
        coverage["selected_count"] = len(entries) + len(pending)
    else:
        candidates = [path for path in find_json_files(root, None)
                      if not any(part.lower() in EXCLUDED or part.lower().startswith(".staging-")
                                 for part in path.relative_to(root).parts[:-1])]
    items, seen = [], set()
    for path in candidates:
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        try:
            obj = read_json(path)
            if is_batch_artifact(obj) or is_merged_dataset(obj) or _is_collection_metadata(obj):
                continue
            from subsmerge import looks_like_subsdown
            if not looks_like_subsdown(obj):
                continue
            item = _load_item(path, root)
            items.append(item)
        except (OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
            errors.append({"path": path.relative_to(root).as_posix(), "error": str(exc)})
    coverage["indexed_count"] = len(items)
    coverage["gap_count"] = len(gaps)
    return root, items, coverage, errors


def _index_from(items, coverage, errors):
    rows = []
    for item in items:
        row = {key: item.get(key) for key in (
            "item_id", "video_id", "title", "channel", "url", "upload_date", "duration_seconds",
            "playlist", "source_relative_path", "source_sha256", "source_paths")}
        row["subtitle"] = {key: item["subtitle"].get(key) for key in
                           ("language", "kind", "origin", "translated", "segment_count")}
        row["segment_count"] = len(item["segments"])
        row["character_count"] = len(str(item["text"]))
        row["segment_character_count"] = sum(len(str(seg["text"])) for seg in item["segments"])
        rows.append(row)
    return {"schema": INDEX_SCHEMA, "product_version": VERSION, "created_at": _now(),
            "item_count": len(rows), "items": rows, "coverage": coverage, "errors": errors}


def build_index(root, manifest=None):
    _, items, coverage, errors = _inventory(root, manifest)
    return _index_from(items, coverage, errors)


def _label(value):
    return str(value if value is not None else "unknown").replace("\r", " ").replace("\n", " ")


def _index_markdown(index):
    lines = ["<!-- subsbatch.index.v1 -->", "# Transcript index", "",
             f"Tracks: {index['item_count']}; coverage gaps: {index['coverage']['gap_count']}",
             "Coverage mode: " + index["coverage"]["mode"],
             "Pending enumeration targets: " + str(index["coverage"].get("enumeration_pending", "unknown")), ""]
    for item in index["items"]:
        lines.extend(["## " + _label(item["title"]), "", "- Track: " + item["item_id"],
                      "- Channel: " + _label(item["channel"]), "- URL: " + _label(item["url"]),
                      "- Upload date: " + _label(item["upload_date"]),
                      "- Duration (seconds): " + _label(item["duration_seconds"]),
                      "- Language: " + _label(item["subtitle"]["language"]),
                      "- Caption kind: " + _label(item["subtitle"]["kind"]),
                      "- Caption origin: " + _label(item["subtitle"]["origin"]),
                      "- Translated: " + _label(item["subtitle"]["translated"]),
                      "- Source: " + item["source_relative_path"],
                      "- SHA-256: " + item["source_sha256"],
                      f"- Segments: {item['segment_count']}; characters: {item['character_count']}", ""])
    for gap in index["coverage"]["gaps"]:
        lines.append("- Gap: " + _label(gap["key"]) + " — " + _label(gap["status"]) + ": " + _label(gap["message"]))
    for error in index["errors"]:
        lines.append("- Read error: " + _label(error.get("path", error.get("key"))) + ": " + _label(error["error"]))
    return "\n".join(lines) + "\n"


def write_index(root, json_path, markdown_path, manifest=None):
    index = build_index(root, manifest)
    targets = [Path(json_path).absolute(), Path(markdown_path).absolute()]
    if targets[0].resolve() == targets[1].resolve() or any(p.exists() for p in targets):
        raise FileExistsError("index destinations must be distinct new files")
    created = []
    try:
        atomic_write_json(targets[0], index)
        created.append(targets[0])
        atomic_write_text(targets[1], _index_markdown(index))
        created.append(targets[1])
        _verify_index_sources(Path(root).resolve(), index)
    except BaseException:
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return {"index_json": str(targets[0]), "index_markdown": str(targets[1]),
            "item_count": index["item_count"], "gap_count": index["coverage"]["gap_count"],
            "error_count": len(index["errors"]),
            "enumeration_pending": index["coverage"].get("enumeration_pending", 0)}


def _verify_index_sources(root, index):
    for item in index["items"]:
        path = _inside(root, item["source_relative_path"])
        if not path.is_file() or sha256(path) != item["source_sha256"]:
            raise ValueError("source changed while producing derived files: " + item["source_relative_path"])


def _new_target(root, output, kind):
    target = Path(output).expanduser().absolute() if output else root / kind / uuid.uuid4().hex[:16]
    if os.path.lexists(target):
        raise FileExistsError("output directory already exists; choose a new directory")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target.parent.resolve() / target.name


def _stage(target):
    return Path(tempfile.mkdtemp(prefix=".staging-", dir=target.parent))


def _remove_stage(path):
    if (path.name.startswith(".staging-") and path.is_dir() and not path.is_symlink()
            and path.resolve() == path and path.parent.resolve() == path.parent):
        shutil.rmtree(path)


def _publish(stage, target):
    if (stage.is_symlink() or stage.parent.resolve() != stage.parent
            or stage.parent != target.parent or target.parent.resolve() != target.parent):
        raise ValueError("staging or output parent changed during publication")
    if os.path.lexists(target):
        raise FileExistsError("output appeared during preparation; no files replaced")
    os.rename(stage, target)


def create_index(root, manifest=None, output=None):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("source root must be an existing directory")
    target = _new_target(root, output, ".indexes")
    stage = _stage(target)
    try:
        result = write_index(root, stage / "index.json", stage / "index.md", manifest)
        _publish(stage, target)
    finally:
        _remove_stage(stage)
    result.update(index_json=str(target / "index.json"), index_markdown=str(target / "index.md"))
    return result


def _cues(item):
    if item["segments"]:
        return item["segments"]
    return [{"index": 1, "start": "", "end": "", "text": str(item["text"]), "synthetic": True}]


def _fragment(cue, ordinal, begin, end):
    return {"segment_index": cue["index"], "segment_ordinal": ordinal,
            "start": cue["start"], "end": cue["end"],
            "offset_start": begin, "offset_end": end,
            "synthetic": bool(cue.get("synthetic", False))}


def _part(item, fragments):
    identity = [item["item_id"], fragments]
    return {"part_id": _id("part-", identity), "item_id": item["item_id"],
            "source_relative_path": item["source_relative_path"],
            "source_sha256": item["source_sha256"], "fragments": fragments}


def _render_part(part, item):
    lines = ["## " + _label(item["title"]), "", "Part: " + part["part_id"],
             "Track: " + item["item_id"], "URL: " + _label(item["url"]),
             "Source: " + part["source_relative_path"], "SHA-256: " + part["source_sha256"], ""]
    cues = _cues(item)
    for fragment in part["fragments"]:
        cue = cues[fragment["segment_ordinal"] - 1]
        lines.extend([f"[segment {fragment['segment_index']}; ordinal {fragment['segment_ordinal']}; "
                      f"{fragment['start']} --> {fragment['end']}; "
                      f"chars {fragment['offset_start']}:{fragment['offset_end']}]",
                      str(cue["text"])[fragment["offset_start"]:fragment["offset_end"]], ""])
    return "\n".join(lines) + "\n"


def _batch_header(batch_id):
    return "<!-- subsbatch.reading.v1 -->\n# Reading batch " + batch_id + "\n\n"


def _split_parts(item, max_chars):
    # IDs have fixed width. Include the complete batch prefix in every size check.
    prefix_size = len(_batch_header("batch-" + "0" * 24))
    pending, parts = [], []
    def fits(fragments):
        return prefix_size + len(_render_part(_part(item, fragments), item)) <= max_chars
    for ordinal, cue in enumerate(_cues(item), 1):
        text = str(cue["text"])
        offset = 0
        while offset < len(text) or (not text and offset == 0):
            whole = _fragment(cue, ordinal, offset, len(text))
            if fits(pending + [whole]):
                pending.append(whole)
                break
            if pending:
                parts.append(_part(item, pending))
                pending = []
                continue
            low, high = offset, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                if fits([_fragment(cue, ordinal, offset, middle)]):
                    low = middle
                else:
                    high = middle - 1
            if low == offset:
                raise ValueError("max-chars is too small for the complete Markdown header and one character")
            parts.append(_part(item, [_fragment(cue, ordinal, offset, low)]))
            offset = low
    if pending:
        parts.append(_part(item, pending))
    return parts


def _template(batch, parts):
    return {"schema": REPORT_SCHEMA, "batch_id": batch["batch_id"],
            "agent": "", "model": "", "instructions": "",
            "parts": [{"part_id": part["part_id"], "status": "not_read", "summary": "",
                       "topics": [], "observations": [], "evidence": []} for part in parts],
            "synthesis": "", "uncertainties": [], "remaining_work": [],
            "verification": "Agent declarations only; content and reasoning are not semantically verified."}


def prepare(root, manifest=None, output=None, max_chars=30000):
    if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
        raise ValueError("max-chars must be a positive integer")
    root, items, coverage, errors = _inventory(root, manifest)
    if not items:
        raise ValueError("no usable transcript exports")
    parts = [part for item in items for part in _split_parts(item, max_chars)]
    by_id = {item["item_id"]: item for item in items}
    groups, current, size = [], [], len(_batch_header("batch-" + "0" * 24))
    for part in parts:
        length = len(_render_part(part, by_id[part["item_id"]]))
        if current and size + length > max_chars:
            groups.append(current)
            current, size = [], len(_batch_header("batch-" + "0" * 24))
        current.append(part)
        size += length
    if current:
        groups.append(current)
    target = _new_target(root, output, ".batches")
    stage = _stage(target)
    try:
        index = _index_from(items, coverage, errors)
        atomic_write_json(stage / "index.json", index)
        atomic_write_text(stage / "index.md", _index_markdown(index))
        batches = []
        for group in groups:
            batch_id = _id("batch-", [part["part_id"] for part in group])
            reading_file = batch_id + ".md"
            template_file = batch_id + ".report.json"
            reading = _batch_header(batch_id) + "".join(_render_part(p, by_id[p["item_id"]]) for p in group)
            batch = {"batch_id": batch_id, "part_ids": [p["part_id"] for p in group],
                     "reading_file": reading_file, "template_file": template_file,
                     "character_count": len(reading)}
            atomic_write_text(stage / reading_file, reading)
            atomic_write_json(stage / template_file, _template(batch, group))
            batch.update(reading_sha256=sha256(stage / reading_file), template_sha256=sha256(stage / template_file))
            batches.append(batch)
        plan = {"schema": PLAN_SCHEMA, "product_version": VERSION, "created_at": _now(),
                "source_root": Path(os.path.relpath(root, target)).as_posix(),
                "max_chars": max_chars, "index": {"path": "index.json", "sha256": sha256(stage / "index.json")},
                "items": index["items"], "parts": parts, "batches": batches,
                "coverage": coverage, "source_errors": errors}
        instructions = ("# Agent reading procedure\n\n"
            "1. Inspect index.json coverage and source errors before choosing a batch.\n"
            "2. Select one pending batch from the status command. Read its complete Markdown file.\n"
            "3. Copy the hashed report template to a separate working JSON file before editing; "
            "never edit the template or reading file. Record agent, model and task instructions.\n"
            "4. Declare each part not_read, partial or complete. Cite segment_index, start/end "
            "and source character offsets for fragment-specific observations. Record uncertainties "
            "and remaining work; never describe unread content as read.\n"
            "5. Run accept-report PLAN WORKING_REPORT, then inspect status. Accepted JSON and "
            "Markdown reports preserve declarations; structural validation does not verify semantics.\n"
            "6. Save and accept the report before starting a fresh agent context. Resume with "
            "the unchanged plan and accepted reports, then select the next batch.\n")
        atomic_write_text(stage / "instructions.md", instructions)
        plan["instructions"] = {"path": "instructions.md", "sha256": sha256(stage / "instructions.md")}
        atomic_write_json(stage / "plan.json", plan)
        _verify_index_sources(root, index)
        _publish(stage, target)
    finally:
        _remove_stage(stage)
    return {"plan": str(target / "plan.json"), "plan_path": str(target / "plan.json"),
            "output_directory": str(target), "index_json": str(target / "index.json"),
            "index_markdown": str(target / "index.md"), "item_count": len(items),
            "part_count": len(parts), "batch_count": len(batches),
            "instructions": str(target / "instructions.md"),
            "gap_count": coverage["gap_count"], "error_count": len(errors),
            "enumeration_pending": coverage.get("enumeration_pending", 0)}


def _load_plan(path):
    path = Path(path).expanduser().resolve()
    plan = read_json(path)
    if not isinstance(plan, dict) or plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unsupported batch plan")
    if type(plan.get("max_chars")) is not int or plan["max_chars"] < 1:
        raise ValueError("invalid plan character budget")
    locator = plan.get("source_root")
    if (not isinstance(locator, str) or not locator or "\\" in locator
            or Path(locator).is_absolute() or PureWindowsPath(locator).anchor):
        raise ValueError("source_root must be a relative locator")
    root = (path.parent / locator).resolve()
    for key, identity in (("items", "item_id"), ("parts", "part_id"), ("batches", "batch_id")):
        rows = plan.get(key)
        if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get(identity), str) for row in rows):
            raise ValueError("invalid plan " + key)
        if len({row[identity] for row in rows}) != len(rows):
            raise ValueError("duplicate plan " + identity)
    item_ids = {item["item_id"] for item in plan["items"]}
    items = {item["item_id"]: item for item in plan["items"]}
    part_ids = {part["part_id"] for part in plan["parts"]}
    if (not item_ids or not part_ids or not plan["batches"] or
            {part.get("item_id") for part in plan["parts"]} != item_ids):
        raise ValueError("every indexed track must have reading parts and batches")
    referenced = [part_id for batch in plan["batches"] for part_id in batch["part_ids"]]
    if len(referenced) != len(set(referenced)) or set(referenced) != part_ids:
        raise ValueError("batch parts overlap or are missing")
    for part in plan["parts"]:
        if part.get("item_id") not in item_ids or not isinstance(part.get("fragments"), list):
            raise ValueError("invalid part source or fragments")
        _inside(root, part["source_relative_path"])
        item = items[part["item_id"]]
        if any(part.get(key) != item.get(key) for key in ("source_relative_path", "source_sha256")):
            raise ValueError("part does not reference its indexed source")
        if not part["fragments"] or part["part_id"] != _id("part-", [part["item_id"], part["fragments"]]):
            raise ValueError("part identity or fragments changed")
        for fragment in part["fragments"]:
            if (not isinstance(fragment, dict) or
                    any(type(fragment.get(key)) is not int for key in ("segment_ordinal", "offset_start", "offset_end")) or
                    fragment["segment_ordinal"] < 1 or fragment["offset_start"] < 0 or
                    fragment["offset_end"] < fragment["offset_start"] or
                    not all(key in fragment for key in ("segment_index", "start", "end", "synthetic"))):
                raise ValueError("invalid fragment source range")
    for batch in plan["batches"]:
        if batch["batch_id"] != _id("batch-", batch["part_ids"]):
            raise ValueError("batch identity or part references changed")
        if type(batch.get("character_count")) is not int or not 0 < batch["character_count"] <= plan["max_chars"]:
            raise ValueError("batch exceeds plan character budget")
        _inside(path.parent, batch["reading_file"])
        _inside(path.parent, batch["template_file"])
    return path, plan, root


def _batch_errors(path, plan, root, batch):
    errors = []
    checks = [(plan["index"]["path"], plan["index"]["sha256"]),
              (plan["instructions"]["path"], plan["instructions"]["sha256"]),
              (batch["reading_file"], batch["reading_sha256"]),
              (batch["template_file"], batch["template_sha256"])]
    for relative, digest in checks:
        try:
            file = _inside(path.parent, relative)
            if not file.is_file() or sha256(file) != digest:
                raise ValueError("missing or changed artifact")
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    try:
        index = read_json(_inside(path.parent, plan["index"]["path"]))
        if index.get("schema") != INDEX_SCHEMA or index.get("items") != plan["items"]:
            raise ValueError("plan items differ from the hashed index")
    except (OSError, ValueError, TypeError) as exc:
        errors.append({"path": plan["index"]["path"], "error": str(exc)})
    parts = {part["part_id"]: part for part in plan["parts"]}
    seen = set()
    for identity in batch["part_ids"]:
        part = parts[identity]
        relative = part["source_relative_path"]
        if relative in seen:
            continue
        seen.add(relative)
        try:
            source = _inside(root, relative)
            if not source.is_file() or sha256(source) != part["source_sha256"]:
                raise ValueError("missing or changed source transcript")
            original = _load_item(source, root)
            cues = _cues(original)
            fragments = [f for p in plan["parts"] if p["item_id"] == part["item_id"] for f in p["fragments"]]
            previous_ordinal, previous_end = 1, 0
            for fragment in fragments:
                ordinal = fragment["segment_ordinal"]
                if ordinal > len(cues):
                    raise ValueError("fragment segment ordinal exceeds source")
                cue = cues[ordinal - 1]
                if (any(fragment[key] != cue[key] for key in ("start", "end"))
                        or fragment["segment_index"] != cue["index"]
                        or fragment["offset_end"] > len(str(cue["text"]))):
                    raise ValueError("fragment is outside source segment")
                if ordinal != previous_ordinal:
                    if ordinal != previous_ordinal + 1 or previous_end != len(str(cues[previous_ordinal - 1]["text"])):
                        raise ValueError("source fragments have a gap or overlap")
                    previous_end = 0
                if fragment["offset_start"] != previous_end:
                    raise ValueError("source fragments have a gap or overlap")
                previous_ordinal, previous_end = ordinal, fragment["offset_end"]
            if previous_ordinal != len(cues) or previous_end != len(str(cues[-1]["text"])):
                raise ValueError("source fragments do not cover the full transcript")
        except (OSError, ValueError) as exc:
            errors.append({"path": relative, "error": str(exc)})
    return errors


def _validate_report(report, batch, plan):
    if not isinstance(report, dict) or report.get("schema") != REPORT_SCHEMA or report.get("batch_id") != batch["batch_id"]:
        raise ValueError("report schema or batch_id mismatch")
    for key in ("agent", "model", "instructions", "synthesis"):
        if not isinstance(report.get(key), str):
            raise ValueError("report " + key + " must be a string")
    for key in ("uncertainties", "remaining_work"):
        if not isinstance(report.get(key), list) or any(not isinstance(v, str) for v in report[key]):
            raise ValueError("report " + key + " must be a list of strings")
    rows = report.get("parts")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("report parts must be objects")
    identities = [row.get("part_id") for row in rows]
    if any(not isinstance(value, str) for value in identities) or len(set(identities)) != len(identities) or set(identities) != set(batch["part_ids"]):
        raise ValueError("report contains missing, duplicate or unknown parts")
    parts = {part["part_id"]: part for part in plan["parts"]}
    for row in rows:
        if row.get("status") not in {"not_read", "partial", "complete"} or not isinstance(row.get("summary"), str):
            raise ValueError("invalid part status or summary")
        for key in ("topics", "observations"):
            if not isinstance(row.get(key), list) or any(not isinstance(v, str) for v in row[key]):
                raise ValueError("part " + key + " must be a list of strings")
        if not isinstance(row.get("evidence"), list):
            raise ValueError("part evidence must be a list")
        for citation in row["evidence"]:
            if not isinstance(citation, dict) or not all(key in citation for key in ("segment_index", "start", "end")):
                raise ValueError("citation needs segment_index, start and end")
            matches = [fragment for fragment in parts[row["part_id"]]["fragments"]
                       if all(citation[key] == fragment[key] for key in ("segment_index", "start", "end"))
                       and ("segment_ordinal" not in citation or citation["segment_ordinal"] == fragment["segment_ordinal"])]
            if not matches:
                raise ValueError("citation is outside its part's source ranges")
            if "offset_start" in citation or "offset_end" in citation:
                begin, end = citation.get("offset_start"), citation.get("offset_end")
                if (type(begin) is not int or type(end) is not int or begin > end or
                        not any(f["offset_start"] <= begin <= end <= f["offset_end"] for f in matches)):
                    raise ValueError("citation character offsets are outside its part")
            if "quote" in citation and not isinstance(citation["quote"], str):
                raise ValueError("citation quote must be a string")
    return all(row["status"] == "complete" for row in rows)


def _report_markdown(report, complete):
    lines = ["<!-- subsbatch.accepted-report.v1 -->", "# Reading report", "",
             "Batch: " + report["batch_id"], "Declared complete: " + str(complete).lower(),
             "Agent: " + _label(report["agent"]), "Model: " + _label(report["model"]),
             "Instructions: " + _label(report["instructions"]), "",
             "This validates structure and source references only. Semantic accuracy is not verified.", ""]
    for part in report["parts"]:
        lines.extend(["## " + part["part_id"], "", "Status: " + part["status"], "", part["summary"], ""])
        for key in ("topics", "observations", "evidence"):
            lines.extend(["### " + key.title(), ""])
            for value in part[key]:
                lines.append("- " + (json.dumps(value, ensure_ascii=False) if isinstance(value, dict) else value))
            lines.append("")
    lines.extend(["## Synthesis", "", report["synthesis"], "", "## Uncertainties", ""])
    lines.extend("- " + value for value in report["uncertainties"])
    lines.extend(["", "## Remaining work", ""])
    lines.extend("- " + value for value in report["remaining_work"])
    return "\n".join(lines) + "\n"


def _report_target(path, batch_id):
    lexical = path.parent / "reports" / batch_id
    resolved = _inside(path.parent, "reports/" + batch_id)
    if lexical != resolved:
        raise ValueError("accepted report directories must not be filesystem aliases")
    return resolved


def _declared_state(report):
    states = [row["status"] for row in report["parts"]]
    if all(value == "complete" for value in states):
        return "declared_complete"
    return "pending" if all(value == "not_read" for value in states) else "partial"


def _owned_report_bundle(target, batch_id):
    if not target.is_dir() or target.is_symlink() or target.resolve() != target:
        raise ValueError("existing report target is not an owned report directory")
    expected = {"report.json", "report.md", "acceptance.json"}
    entries = list(target.iterdir())
    if {entry.name for entry in entries} != expected or any(not entry.is_file() or entry.is_symlink() for entry in entries):
        raise ValueError("existing report directory contains unrecognized files; nothing replaced")
    receipt = read_json(target / "acceptance.json")
    prior = read_json(target / "report.json")
    if (not isinstance(receipt, dict) or receipt.get("schema") != "subsbatch.acceptance.v1" or
            receipt.get("batch_id") != batch_id or not isinstance(prior, dict) or
            prior.get("schema") != REPORT_SCHEMA or prior.get("batch_id") != batch_id):
        raise ValueError("existing report bundle is not recognized; nothing replaced")


def accept_report(plan_path, report_path, overwrite=False):
    path, plan, root = _load_plan(plan_path)
    report = read_json(Path(report_path))
    batch = next((b for b in plan["batches"] if b["batch_id"] == report.get("batch_id")), None) if isinstance(report, dict) else None
    if batch is None:
        raise ValueError("unknown report batch_id")
    errors = _batch_errors(path, plan, root, batch)
    if errors:
        raise ValueError("batch invalidated: " + json.dumps(errors))
    complete = _validate_report(report, batch, plan)
    target = _report_target(path, batch["batch_id"])
    if target.exists() and not overwrite:
        raise FileExistsError("accepted report exists; use --overwrite")
    if target.exists():
        _owned_report_bundle(target, batch["batch_id"])
    target.parent.mkdir(parents=True, exist_ok=True)
    stage = _stage(target)
    backup = None
    try:
        atomic_write_json(stage / "report.json", report)
        atomic_write_text(stage / "report.md", _report_markdown(report, complete))
        receipt = {"schema": "subsbatch.acceptance.v1", "batch_id": batch["batch_id"],
                   "accepted_at": _now(), "declared_complete": complete,
                   "plan_sha256": sha256(path), "report_sha256": sha256(stage / "report.json"),
                   "markdown_sha256": sha256(stage / "report.md"),
                   "semantic_verification": False}
        atomic_write_json(stage / "acceptance.json", receipt)
        # Recheck after rendering and before publication to reject concurrent source edits.
        if _batch_errors(path, plan, root, batch):
            raise ValueError("batch changed during report acceptance")
        if target.exists():
            _owned_report_bundle(target, batch["batch_id"])
            backup = target.with_name(".staging-prior-" + batch["batch_id"] + "-" + uuid.uuid4().hex)
            os.rename(target, backup)
        try:
            os.rename(stage, target)
        except BaseException:
            if backup is not None:
                os.rename(backup, target)
                backup = None
            raise
        if backup is not None:
            try:
                _remove_stage(backup)
            except OSError:
                pass  # A retained prior bundle is safer than a failed accepted publication.
    finally:
        _remove_stage(stage)
    return {"batch_id": batch["batch_id"], "state": _declared_state(report),
            "report_json": str(target / "report.json"), "report_markdown": str(target / "report.md"),
            "semantic_verification": False}


def status(plan_path):
    path, plan, root = _load_plan(plan_path)
    rows = []
    for batch in plan["batches"]:
        errors = _batch_errors(path, plan, root, batch)
        state = "invalidated" if errors else "pending"
        accepted = _report_target(path, batch["batch_id"])
        if not accepted.exists() and list(accepted.parent.glob(".staging-prior-" + batch["batch_id"] + "-*")):
            errors.append({"path": "reports/" + batch["batch_id"],
                           "error": "Interrupted replacement: prior report bundle retained in .staging-prior directory"})
            state = "invalidated"
        if not errors and accepted.exists():
            try:
                receipt = read_json(_inside(accepted, "acceptance.json"))
                if receipt.get("schema") != "subsbatch.acceptance.v1" or receipt.get("plan_sha256") != sha256(path):
                    raise ValueError("accepted report references a changed plan")
                if receipt["report_sha256"] != sha256(_inside(accepted, "report.json")) or receipt["markdown_sha256"] != sha256(_inside(accepted, "report.md")):
                    raise ValueError("accepted report bundle changed")
                report = read_json(_inside(accepted, "report.json"))
                complete = _validate_report(report, batch, plan)
                state = _declared_state(report)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                errors.append({"path": "reports/" + batch["batch_id"], "error": str(exc)})
                state = "invalidated"
        rows.append({"batch_id": batch["batch_id"], "state": state, "errors": errors})
    return {"plan": str(path), "batches": rows,
            "counts": {state: sum(row["state"] == state for row in rows)
                       for state in ("pending", "partial", "declared_complete", "invalidated")},
            "coverage": plan.get("coverage", {}), "source_errors": plan.get("source_errors", []),
            "semantic_verification": False}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    machine = "--json" in argv
    argv = [arg for arg in argv if arg != "--json"]
    result = {"schema": "subsbatch.result.v1", "version": VERSION, "exit_code": 2}
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("index", "prepare"):
        command = commands.add_parser(name)
        command.add_argument("folder")
        command.add_argument("--manifest")
        command.add_argument("--output", help="New output directory")
        if name == "prepare":
            command.add_argument("--max-chars", type=int, default=30000)
    commands.add_parser("status").add_argument("plan")
    command = commands.add_parser("accept-report")
    command.add_argument("plan")
    command.add_argument("report")
    command.add_argument("--overwrite", action="store_true")
    def run():
        try:
            args = parser.parse_args(argv)
            result["command"] = args.command
            if args.command == "index":
                value = create_index(args.folder, args.manifest, args.output)
            elif args.command == "prepare":
                value = prepare(args.folder, args.manifest, args.output, args.max_chars)
            elif args.command == "status":
                value = status(args.plan)
            else:
                value = accept_report(args.plan, args.report, args.overwrite)
            partial = args.command in {"index", "prepare"} and any(
                value.get(key, 0) for key in ("gap_count", "error_count", "enumeration_pending"))
            result.update(value, exit_code=2 if partial else 0)
            if not machine:
                print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
            return result["exit_code"]
        except SystemExit as exc:
            result.update(exit_code=int(exc.code), error="invalid command arguments" if exc.code else None)
            return int(exc.code)
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, RecursionError) as exc:
            result.update(exit_code=2, error=str(exc))
            print("ERROR: " + str(exc), file=sys.stderr)
            return 2
    if machine:
        with redirect_stdout(sys.stderr):
            code = run()
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        return code
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
