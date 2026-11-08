"""Synthetic public-contract checks for indexed, bounded reading plans."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import subsbatch
import subsmerge


ROOT = Path(__file__).resolve().parents[1]


class BatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="batch-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "sources café 雪"
        self.source.mkdir()

    def write_json(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def read_json(self, path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def digest(self, path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def transcript(self, directory="one-fr-auto", video_id="aaaaaaaaaaa", language="fr",
                   kind="auto", texts=None, position=1):
        if texts is None:
            texts = ["First synthetic sentence café 雪.", "Second sentence. 🤖"]
        segments = [{"index": 20 + i, "start": f"00:00:0{i},000",
                     "end": f"00:00:0{i + 1},000", "text": text}
                    for i, text in enumerate(texts)]
        obj = {"schema_version": "subsdown.v4", "type": "YouTubeSubtitleTranscript",
               "created_at": "2026-01-02T03:04:05Z",
               "video": {"id": video_id, "title": "Synthetic café 雪 " + video_id,
                         "channel": "Synthetic channel", "upload_date": "20260102",
                         "duration_seconds": 123.5,
                         "url_clean": "https://www.youtube.com/watch?v=" + video_id},
               "playlist": {"id": "synthetic-playlist", "index": position},
               "subtitle": {"language": language, "kind": kind, "translated": False},
               "transcript": {"plain_text": "\n".join(texts), "segments": segments}}
        path = self.write_json(self.source / directory / "transcript.json", obj)
        path.with_suffix(".md").write_text("Synthetic original Markdown", encoding="utf-8")
        path.with_suffix(".srt").write_text("Synthetic original SRT", encoding="utf-8")
        return path

    def cli(self, *args):
        completed = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "subsbatch.py"),
                                    *map(str, args), "--json"], cwd=self.root,
                                   capture_output=True, encoding="utf-8")
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1,
                         completed.stdout + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["exit_code"], completed.returncode)
        return completed, result

    def assert_sources_unchanged(self, snapshots):
        for path, content in snapshots.items():
            self.assertEqual(path.read_bytes(), content, str(path))

    def prepare(self, max_chars=1400, name="reading café 雪"):
        output = self.root / name
        completed, result = self.cli("prepare", self.source, "--output", output,
                                     "--max-chars", max_chars)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        plan_path = output / "plan.json"
        self.assertTrue(plan_path.is_file(), result)
        return plan_path, self.read_json(plan_path)

    def report(self, plan_path, plan, complete=True):
        batch = plan["batches"][0]
        report = self.read_json(plan_path.parent / batch["template_file"])
        report.update(agent="Synthetic test agent", model="synthetic-model",
                      instructions="Read each assigned source range and cite it.",
                      synthesis="Synthetic synthesis café 雪.", uncertainties=["Synthetic uncertainty"],
                      remaining_work=[] if complete else ["Read remaining material"])
        parts = {part["part_id"]: part for part in plan["parts"]}
        for row in report["parts"]:
            row.update(status="complete" if complete else "partial", summary="Synthetic summary",
                       topics=["Synthetic topic"], observations=["Synthetic observation"])
            fragment = parts[row["part_id"]]["fragments"][0]
            row["evidence"] = [{key: fragment[key] for key in (
                "segment_index", "segment_ordinal", "start", "end", "offset_start", "offset_end")}]
        return report

    def test_reports_declare_partial_complete_and_require_explicit_replacement(self):
        self.transcript()
        plan_path, plan = self.prepare()
        completed, state = self.cli("status", plan_path)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(state["counts"]["pending"], 1)
        report_path = self.write_json(self.root / "report.json", self.report(plan_path, plan, complete=False))
        completed, accepted = self.cli("accept-report", plan_path, report_path)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(accepted["state"], "partial")
        self.assertIs(accepted["semantic_verification"], False)
        saved_json, saved_md = Path(accepted["report_json"]), Path(accepted["report_markdown"])
        before = {path: path.read_bytes() for path in saved_json.parent.iterdir()}
        self.write_json(report_path, self.report(plan_path, plan))
        rejected, result = self.cli("accept-report", plan_path, report_path)
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("error", result)
        self.assert_sources_unchanged(before)
        completed, accepted = self.cli("accept-report", plan_path, report_path, "--overwrite")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(accepted["state"], "declared_complete")
        self.assertEqual(self.read_json(saved_json)["parts"][0]["status"], "complete")
        markdown = saved_md.read_text(encoding="utf-8")
        for expected in ("Synthetic summary", "Synthetic topic", "Synthetic observation",
                         "Synthetic synthesis café 雪.", "Synthetic uncertainty", "segment_index"):
            self.assertIn(expected, markdown)
        completed, state = self.cli("status", plan_path)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(state["counts"]["declared_complete"], 1)
        self.assertEqual(state["counts"]["partial"], 0)

    def test_accepted_not_read_template_remains_pending(self):
        self.transcript()
        plan_path, plan = self.prepare()
        template = self.read_json(plan_path.parent / plan["batches"][0]["template_file"])
        self.assertTrue(all(row["status"] == "not_read" for row in template["parts"]))
        report_path = self.write_json(self.root / "not-read.json", template)
        completed, accepted = self.cli("accept-report", plan_path, report_path)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(accepted["state"], "pending")
        completed, result = self.cli("status", plan_path)
        self.assertEqual(completed.returncode, 0)
        self.assertEqual(result["counts"], {"pending": 1, "partial": 0,
                                           "declared_complete": 0, "invalidated": 0})

    def test_report_overwrite_preserves_unrecognized_directory_and_unexpected_files(self):
        self.transcript()
        for existing in ("unrecognized", "accepted-with-user-file"):
            with self.subTest(existing=existing):
                plan_path, plan = self.prepare(name=existing)
                report_path = self.write_json(self.root / (existing + ".json"), self.report(plan_path, plan))
                target = plan_path.parent / "reports" / plan["batches"][0]["batch_id"]
                if existing == "accepted-with-user-file":
                    completed, result = self.cli("accept-report", plan_path, report_path)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertEqual(Path(result["report_json"]).parent, target)
                else:
                    target.mkdir(parents=True)
                sentinel = target / "user-original.txt"
                sentinel.write_bytes(b"User material must survive explicit derived-report overwrite.\x00\xff")
                snapshots = {path: path.read_bytes() for path in target.iterdir()}
                completed, result = self.cli("accept-report", plan_path, report_path, "--overwrite")
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("error", result)
                self.assertEqual(set(target.iterdir()), set(snapshots))
                self.assert_sources_unchanged(snapshots)
                self.assertEqual(list(target.parent.glob(".staging-*")), [])

    def test_report_missing_unknown_duplicate_and_out_of_range_references_are_rejected(self):
        self.transcript()
        plan_path, plan = self.prepare()
        valid = self.report(plan_path, plan)
        invalid = []
        report = deepcopy(valid)
        report["parts"] = []
        invalid.append(report)
        report = deepcopy(valid)
        report["parts"][0]["part_id"] = "unknown-part"
        invalid.append(report)
        report = deepcopy(valid)
        report["parts"].append(deepcopy(report["parts"][0]))
        invalid.append(report)
        report = deepcopy(valid)
        report["batch_id"] = "unknown-batch"
        invalid.append(report)
        report = deepcopy(valid)
        report["parts"][0]["evidence"][0]["segment_index"] = 999999
        invalid.append(report)
        report = deepcopy(valid)
        report["parts"][0]["evidence"][0]["offset_end"] = 999999
        invalid.append(report)
        for i, report in enumerate(invalid):
            with self.subTest(case=i):
                report_path = self.write_json(self.root / (str(i) + ".json"), report)
                completed, result = self.cli("accept-report", plan_path, report_path)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("error", result)
                self.assertFalse((plan_path.parent / "reports").exists())

    def test_changed_or_missing_source_invalidates_accepted_report(self):
        source = self.transcript()
        original = source.read_bytes()
        for mutation in ("change", "delete"):
            with self.subTest(mutation=mutation):
                source.write_bytes(original)
                plan_path, plan = self.prepare(name=mutation)
                report_path = self.write_json(self.root / (mutation + ".json"), self.report(plan_path, plan))
                completed, accepted = self.cli("accept-report", plan_path, report_path)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                snapshots = {path: path.read_bytes() for path in Path(accepted["report_json"]).parent.iterdir()}
                if mutation == "change":
                    source.write_bytes(original + b"\n ")
                else:
                    source.unlink()
                completed, state = self.cli("status", plan_path)
                self.assertEqual(state["counts"]["invalidated"], 1)
                rejected, result = self.cli("accept-report", plan_path, report_path, "--overwrite")
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("error", result)
                self.assert_sources_unchanged(snapshots)

    def test_changed_reading_or_accepted_report_is_invalidated(self):
        self.transcript()
        for artifact in ("reading", "report"):
            with self.subTest(artifact=artifact):
                plan_path, plan = self.prepare(name=artifact)
                report_path = self.write_json(self.root / (artifact + ".json"), self.report(plan_path, plan))
                completed, accepted = self.cli("accept-report", plan_path, report_path)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                target = (plan_path.parent / plan["batches"][0]["reading_file"]
                          if artifact == "reading" else Path(accepted["report_json"]))
                target.write_bytes(target.read_bytes() + b"\n ")
                completed, state = self.cli("status", plan_path)
                self.assertEqual(state["counts"]["invalidated"], 1)
                self.assertTrue(state["batches"][0]["errors"])

    def test_source_change_between_parse_and_hash_cannot_publish_stale_reading(self):
        source = self.transcript()
        original = source.read_bytes()
        changed = original.replace(b"First synthetic sentence", b"Later synthetic sentence")
        self.assertEqual(len(original), len(changed))
        self.assertNotEqual(original, changed)
        output = self.root / "racing-source"
        digest = subsmerge.sha256
        mutated = []

        def mutate_before_normalization_hash(path):
            if Path(path) == source and not mutated:
                source.write_bytes(changed)
                mutated.append(True)
            return digest(path)

        with patch("subsmerge.sha256", side_effect=mutate_before_normalization_hash):
            with self.assertRaises(ValueError):
                subsbatch.prepare(self.source, output=output)
        self.assertTrue(mutated, "The test must exercise the read/hash boundary")
        self.assertFalse((output / "plan.json").exists())
        self.assertFalse(output.exists())

    def test_plan_cannot_silently_omit_all_parts_and_batches(self):
        self.transcript()
        plan_path, plan = self.prepare()
        self.assertTrue(plan["items"])
        plan["parts"] = []
        plan["batches"] = []
        self.write_json(plan_path, plan)
        completed, result = self.cli("status", plan_path)
        self.assertNotEqual(completed.returncode, 0)
        self.assertIn("error", result)

    def test_interrupted_report_replacement_restores_previous_bundle(self):
        self.transcript()
        plan_path, plan = self.prepare()
        report_path = self.write_json(self.root / "report.json", self.report(plan_path, plan, complete=False))
        accepted = subsbatch.accept_report(plan_path, report_path)
        target = Path(accepted["report_json"]).parent
        before = {path: path.read_bytes() for path in target.iterdir()}
        self.write_json(report_path, self.report(plan_path, plan))
        rename = subsbatch.os.rename
        interrupted = []

        def interrupt_publication(source, destination):
            if Path(destination) == target and not interrupted:
                interrupted.append(True)
                raise KeyboardInterrupt("synthetic publication interruption")
            return rename(source, destination)

        with patch("subsbatch.os.rename", side_effect=interrupt_publication):
            with self.assertRaises(KeyboardInterrupt):
                subsbatch.accept_report(plan_path, report_path, overwrite=True)
        self.assertTrue(interrupted)
        self.assert_sources_unchanged(before)
        self.assertEqual(list(target.parent.glob(".staging-*")), [])
        self.assertEqual(subsbatch.status(plan_path)["counts"]["partial"], 1)

    def assert_lossless_parts(self, plan_path, plan, sources):
        """Reconstruct each original cue using coverage intervals, independently."""
        fragments = {}
        reading_parts = {}
        for batch in plan["batches"]:
            body = (plan_path.parent / batch["reading_file"]).read_text(encoding="utf-8")
            starts = [body.index("Part: " + part_id + "\n") for part_id in batch["part_ids"]]
            self.assertEqual(starts, sorted(starts))
            for i, part_id in enumerate(batch["part_ids"]):
                reading_parts[part_id] = body[starts[i]:starts[i + 1] if i + 1 < len(starts) else len(body)]
        for part in plan["parts"]:
            relative = part["source_relative_path"]
            self.assertEqual(part["source_sha256"], self.digest(self.source / relative))
            body = reading_parts[part["part_id"]]
            citations = list(re.finditer(
                r"^\[segment (\d+); ordinal (\d+); (.*?) --> (.*?); chars (\d+):(\d+)\]\n",
                body, re.MULTILINE))
            self.assertEqual(len(citations), len(part["fragments"]))
            for fragment, citation in zip(part["fragments"], citations):
                self.assertEqual(tuple(map(int, (citation[1], citation[2], citation[5], citation[6]))),
                                 (fragment["segment_index"], fragment["segment_ordinal"],
                                  fragment["offset_start"], fragment["offset_end"]))
                self.assertEqual((citation[3], citation[4]), (fragment["start"], fragment["end"]))
                fragment = dict(fragment)
                length = fragment["offset_end"] - fragment["offset_start"]
                fragment["text"] = body[citation.end():citation.end() + length]
                key = (relative, fragment["segment_ordinal"])
                fragments.setdefault(key, []).append(fragment)
        for source in sources:
            relative = source.relative_to(self.source).as_posix()
            original = self.read_json(source)["transcript"]["segments"]
            for ordinal, segment in enumerate(original, 1):
                pieces = fragments.pop((relative, ordinal))
                pieces.sort(key=lambda piece: piece["offset_start"])
                cursor = 0
                reconstructed = []
                for piece in pieces:
                    self.assertEqual(piece["offset_start"], cursor)
                    self.assertEqual(piece["start"], segment["start"])
                    self.assertEqual(piece["end"], segment["end"])
                    self.assertEqual(piece["segment_index"], segment["index"])
                    self.assertEqual(piece["text"], segment["text"][cursor:piece["offset_end"]])
                    reconstructed.append(piece["text"])
                    cursor = piece["offset_end"]
                self.assertEqual(cursor, len(segment["text"]))
                self.assertEqual("".join(reconstructed), segment["text"])
        self.assertEqual(fragments, {})

    def test_bounded_reading_files_split_large_unicode_cues_losslessly(self):
        oversized = "é雪🤖é <&>\n" * 700
        long_source = self.transcript("long", texts=["Leading cue.", oversized,
                                                       "Repeated words. Repeated words."])
        short_source = self.transcript("small", "bbbbbbbbbbb", position=2)
        sources = [long_source, short_source]
        snapshots = {path: path.read_bytes() for path in self.source.rglob("transcript.*")}
        plan_path, plan = self.prepare()
        self.assert_lossless_parts(plan_path, plan, sources)
        self.assertGreater(len([part for part in plan["parts"]
                                if part["source_relative_path"] == long_source.relative_to(self.source).as_posix()]), 1)
        self.assertEqual(len([part for part in plan["parts"]
                              if part["source_relative_path"] == short_source.relative_to(self.source).as_posix()]), 1)
        covered = []
        for batch in plan["batches"]:
            reading = plan_path.parent / batch["reading_file"]
            body = reading.read_text(encoding="utf-8")
            self.assertLessEqual(len(body), 1400)
            self.assertEqual(batch["reading_sha256"], self.digest(reading))
            self.assertTrue(body.strip())
            covered.extend(batch["part_ids"])
        self.assertCountEqual(covered, [part["part_id"] for part in plan["parts"]])
        self.assertEqual(len(covered), len(set(covered)))
        self.assert_sources_unchanged(snapshots)

    def test_derived_artifacts_are_not_merged_even_with_generic_json_enabled(self):
        self.transcript()
        for schema in ("index", "plan", "report", "status"):
            self.write_json(self.source / ("renamed-" + schema + ".json"),
                            {"schema_version": "subsbatch." + schema + ".v1",
                             "text": "Derived text must not become a transcript"})
        self.transcript(".batches/private")
        self.transcript(".indexes/private")
        output = self.root / "merged.json"
        self.assertEqual(subsmerge.merge_files(subsmerge.find_json_files(self.source, output),
                                              self.source, output, include_all_json=True,
                                              include_original=False), 0)
        corpus = self.read_json(output)
        self.assertEqual(corpus["item_count"], 1)
        self.assertEqual(corpus["items"][0]["video_id"], "aaaaaaaaaaa")
        self.assertNotIn("Derived text", output.read_text(encoding="utf-8"))

    def test_copied_run_metadata_is_not_indexed_as_a_transcript(self):
        self.transcript()
        self.write_json(self.source / 'renamed-run.json',
                        {'schema_version': 'subsdown.run.v1', 'items': []})
        self.write_json(self.source / 'renamed-result.json',
                        {'schema_version': 'subsdown.result.v1', 'exit_code': 0})
        index = subsbatch.build_index(self.source)
        self.assertEqual(index['item_count'], 1)
        self.assertEqual(index['errors'], [])

    def test_index_is_deterministic_metadata_for_every_track_without_text(self):
        self.transcript("z-later", "bbbbbbbbbbb", position=2)
        self.transcript("b-first-manual", language="en", kind="manual")
        self.transcript("a-first-auto")
        snapshots = {path: path.read_bytes() for path in self.source.rglob("transcript.*")}
        first = subsbatch.build_index(self.source)
        second = subsbatch.build_index(self.source)
        self.assertEqual(first["items"], second["items"])
        items = first["items"]
        self.assertEqual(len(items), 3)
        self.assertEqual(len({item["item_id"] for item in items}), 3)
        self.assertEqual([item["video_id"] for item in items],
                         ["aaaaaaaaaaa", "aaaaaaaaaaa", "bbbbbbbbbbb"])
        for item in items:
            relative = Path(item["source_relative_path"])
            self.assertFalse(relative.is_absolute())
            self.assertNotIn("..", relative.parts)
            self.assertEqual(item["source_sha256"], self.digest(self.source / relative))
            self.assertNotIn("segments", item)
            self.assertNotIn("text", item)
            self.assertNotIn("plain_text", item)
        encoded = json.dumps(first, ensure_ascii=False)
        self.assertNotIn("First synthetic sentence", encoded)
        self.assertIn("20260102", encoded)
        self.assertIn("123.5", encoded)
        self.assert_sources_unchanged(snapshots)

    def test_manifest_selects_current_exports_and_exposes_unavailable_gaps(self):
        current = self.transcript()
        self.transcript("old", "zzzzzzzzzzz", position=9)
        manifest = {"schema_version": "subsdown.run.v1", "summary": {
            "success": 1, "unavailable": 1, "failed": 0}, "items": [
                {"key": "current", "status": "success", "url": "https://youtu.be/aaaaaaaaaaa",
                 "exports": [{"path": str(current.relative_to(self.source)),
                              "sha256": self.digest(current)}]},
                {"key": "missing", "status": "unavailable", "exports": [],
                 "url": "https://youtu.be/bbbbbbbbbbb", "message": "No public captions"}]}
        indexed = subsbatch.build_index(self.source, manifest=manifest)
        self.assertEqual([item["video_id"] for item in indexed["items"]], ["aaaaaaaaaaa"])
        coverage = json.dumps(indexed["coverage"])
        self.assertIn("unavailable", coverage)
        self.assertIn("bbbbbbbbbbb", coverage)
        self.assertNotIn("zzzzzzzzzzz", json.dumps(indexed))
        altered = deepcopy(manifest)
        altered["items"][0]["exports"][0]["path"] = "../outside.json"
        outside = self.write_json(self.root / "outside.json", self.read_json(current))
        before = outside.read_bytes()
        indexed = subsbatch.build_index(self.source, manifest=altered)
        self.assertEqual(indexed["items"], [])
        self.assertTrue(indexed["errors"])
        self.assertEqual(outside.read_bytes(), before)

    def test_manifest_hash_mismatch_does_not_silently_index_changed_source(self):
        source = self.transcript()
        original_hash = self.digest(source)
        manifest = {"schema_version": "subsdown.run.v1", "items": [{"key": "selected", "status": "success", "exports": [
            {"path": str(source.relative_to(self.source)), "sha256": original_hash}]}]}
        changed = self.read_json(source)
        changed["transcript"]["segments"][0]["text"] = "Source edited after download"
        self.write_json(source, changed)
        indexed = subsbatch.build_index(self.source, manifest=manifest)
        self.assertEqual(indexed["items"], [])
        self.assertTrue(indexed["errors"])

    def test_failed_manifest_item_retains_verified_track_and_failure_gap(self):
        source = self.transcript()
        manifest = {"schema_version": "subsdown.run.v1", "items": [
            {"key": "failed-current", "url": "https://youtu.be/aaaaaaaaaaa", "status": "failed",
             "message": "A later selected track failed after this track was published",
             "exports": [{"path": str(path.relative_to(self.source)), "sha256": self.digest(path)}
                         for path in source.parent.iterdir()]}]}
        indexed = subsbatch.build_index(self.source, manifest=manifest)
        self.assertEqual(len(indexed["items"]), 1)
        self.assertEqual(indexed["items"][0]["source_sha256"], self.digest(source))
        self.assertEqual(indexed["coverage"]["indexed_count"], 1)
        self.assertEqual(indexed["coverage"]["gap_count"], 1)
        self.assertEqual(indexed["coverage"]["gaps"][0]["status"], "failed")
        self.assertEqual(indexed["coverage"]["gaps"][0]["key"], "failed-current")
        self.assertEqual(indexed["errors"], [])

    def test_partial_manifest_cli_returns_useful_plan_and_pending_coverage(self):
        source = self.transcript()
        manifest = {"schema_version": "subsdown.run.v1", "items": [
            {"key": "https://youtu.be/aaaaaaaaaaa|", "url": "https://youtu.be/aaaaaaaaaaa",
             "status": "success", "exports": [{"path": str(source.relative_to(self.source)),
                                                  "sha256": self.digest(source)}]},
            {"key": "missing", "url": "https://youtu.be/bbbbbbbbbbb", "status": "unavailable",
             "message": "No captions", "exports": []}],
            "expanded_targets": [{"url": "https://youtu.be/aaaaaaaaaaa", "playlist": {}},
                                 {"url": "https://youtu.be/ccccccccccc", "playlist": {}}]}
        manifest_path = self.write_json(self.source / ".runs" / "manifest.json", manifest)
        output = self.root / "partial"
        completed, result = self.cli("prepare", self.source, "--manifest", manifest_path,
                                     "--output", output)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        plan = self.read_json(result["plan_path"])
        self.assertEqual(len(plan["items"]), 1)
        self.assertEqual(plan["coverage"]["selected_count"], 3)
        self.assertEqual({gap["status"] for gap in plan["coverage"]["gaps"]},
                         {"unavailable", "pending"})
        self.assertEqual(len(plan["parts"]), 1)
        self.assertTrue((output / plan["batches"][0]["reading_file"]).is_file())

    def test_windows_shell_wrappers_preserve_json_and_unicode_paths(self):
        self.transcript()
        available = [name for name in ("powershell.exe", "pwsh.exe") if shutil.which(name)]
        if not available:
            self.skipTest("PowerShell unavailable")
        for shell in available:
            with self.subTest(shell=shell):
                output = self.root / (shell + " café 雪")
                command = [shutil.which(shell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(ROOT / "subsbatch.ps1"), "prepare", str(self.source),
                           "-Output", str(output), "-MaxChars", "1400", "-Json"]
                completed = subprocess.run(command + ["-Python", sys.executable], cwd=ROOT,
                                           capture_output=True, encoding="utf-8")
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
                result = json.loads(completed.stdout)
                self.assertEqual(result["item_count"], 1)
                self.assertEqual(Path(result["plan_path"]), output / "plan.json")
                missing = subprocess.run(command + ["-Python", "missing-synthetic-executable-19483"],
                                         cwd=ROOT, capture_output=True, encoding="utf-8")
                self.assertEqual(missing.returncode, 2)
                self.assertEqual(json.loads(missing.stdout)["exit_code"], 2)
        if sys.platform == "win32":
            output = self.root / "CMD café 雪"
            command = ["cmd.exe", "/d", "/c", "subsbatch.cmd", "index", str(self.source),
                       "-Output", str(output), "-Python", sys.executable, "-Json"]
            completed = subprocess.run(command, cwd=ROOT, capture_output=True, encoding="utf-8")
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            self.assertEqual(json.loads(completed.stdout)["item_count"], 1)

    def test_index_cli_outputs_and_invalid_arguments_are_machine_readable(self):
        self.transcript()
        output = self.root / "index café 雪"
        completed, result = self.cli("index", self.source, "--output", output)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        index = self.read_json(result["index_json"])
        self.assertEqual(len(index["items"]), 1)
        markdown = Path(result["index_markdown"]).read_text(encoding="utf-8")
        self.assertIn("aaaaaaaaaaa", markdown)
        self.assertNotIn("First synthetic sentence", markdown)
        invalid, result = self.cli("prepare", self.source, "--max-chars", 0)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("error", result)
        missing, result = self.cli("index", self.root / "does-not-exist")
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("error", result)
        unknown, result = self.cli("--unknown-option")
        self.assertNotEqual(unknown.returncode, 0)
        self.assertIn("error", result)

    def test_existing_output_directory_is_not_replaced(self):
        transcript = self.transcript()
        snapshots = {path: path.read_bytes() for path in transcript.parent.iterdir()}
        for command in ("index", "prepare"):
            with self.subTest(command=command):
                completed, result = self.cli(command, self.source, "--output", transcript.parent)
                self.assertNotEqual(completed.returncode, 0)
                self.assertIn("error", result)
                self.assert_sources_unchanged(snapshots)

    def test_external_transcript_symlink_is_not_indexed(self):
        outside = self.transcript()
        target = self.root / "external.json"
        outside.replace(target)
        link = outside
        try:
            link.symlink_to(target)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        indexed = subsbatch.build_index(self.source)
        self.assertEqual(indexed["items"], [])


if __name__ == "__main__":
    unittest.main()
