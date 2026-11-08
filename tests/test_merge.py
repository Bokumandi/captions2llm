"""Synthetic checks for standalone and subset subtitle merges."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import subsmerge
from common import VERSION, sha256


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "sources"
        self.source.mkdir()
        self.output = self.root / "result.json"

    def write(self, name, obj):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
        return path

    def transcript(self, name="one.json", title="Café 雪"):
        return self.write(name, {"type": "YouTubeSubtitleTranscript", "video": {"title": title},
                                "transcript": {"segments": [{"text": "bonjour"}]}})

    def cli(self, *args):
        return subprocess.run([sys.executable, "-X", "utf8", str(Path(subsmerge.__file__)),
                               str(self.source), *map(str, args)], capture_output=True,
                              encoding="utf-8", cwd=self.root)

    def test_subset_shape_unicode_and_overwrite(self):
        current = self.transcript()
        self.transcript("stale.json", "Stale")
        self.assertEqual(subsmerge.merge_files([current], self.source, self.output), 0)
        obj = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(obj["item_count"], 1)
        self.assertEqual(obj["subsmerge_version"], "2.0.0")
        self.assertEqual(obj["product_version"], VERSION)
        self.assertEqual(obj["items"][0]["title"], "Café 雪")
        self.assertEqual(obj["items"][0]["text"], "bonjour")
        self.assertIn("original", obj["items"][0])
        before = self.output.read_bytes()
        self.assertEqual(subsmerge.merge_files([current], self.source, self.output), 2)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(subsmerge.merge_files([current], self.source, self.output, overwrite=True), 0)

    def test_generic_arrays_no_original(self):
        array = self.write("array.json", ["synthetic"])
        mapping = self.write("mapping.json", {"text": "synthetic"})
        self.assertEqual(subsmerge.merge_files([array, mapping], self.source, self.output,
                                              include_all_json=True, include_original=False), 0)
        items = json.loads(self.output.read_text(encoding="utf-8"))["items"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all("original" not in item for item in items))

    def test_strict_error_sidecar_parent_and_missing_input(self):
        missing = self.source / "missing.json"
        target = self.root / "new" / "nested" / "result.json"
        self.assertEqual(subsmerge.merge_files([missing], self.source, target, fail_on_error=True), 3)
        self.assertFalse(target.exists())
        errors = json.loads(target.with_suffix(".errors.json").read_text(encoding="utf-8"))
        self.assertEqual(errors["error_count"], 1)
        self.assertEqual(subsmerge.merge_files([missing], self.source, target, fail_on_error=True), 2)

    def test_non_strict_read_error_and_no_items(self):
        good = self.transcript()
        bad = self.source / "broken.json"
        bad.write_text("{invalid", encoding="utf-8")
        self.assertEqual(subsmerge.merge_files([bad, good], self.source, self.output), 0)
        self.assertEqual(json.loads(self.output.read_text())["error_count"], 1)
        self.assertEqual(subsmerge.merge_files([], self.source, self.root / "empty.json"), 4)

    def test_invalid_source_and_source_identity(self):
        good = self.transcript()
        before = good.read_bytes()
        self.assertEqual(subsmerge.merge_files([good], self.source, good, overwrite=True), 2)
        self.assertEqual(self.cli("-o", good, "--overwrite").returncode, 2)
        self.assertEqual(good.read_bytes(), before)
        self.assertEqual(subsmerge.merge_files([], self.root / "absent", self.output), 2)
        outside = self.root / "outside.json"
        outside.write_text("{}")
        self.assertEqual(subsmerge.merge_files([outside], self.source, self.output), 2)

    def test_discovery_ignores_staging_output_and_merged_content(self):
        self.transcript()
        for directory in (".runs", "_tmp", ".staging"):
            self.transcript(directory + "/staged.json")
        self.write("renamed.json", {"subsmerge_version": "2.0.0", "items": []})
        result = self.cli("-o", self.output, "--include-all-json", "--pretty", "--no-original")
        self.assertEqual(result.returncode, 0, result.stderr)
        obj = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(obj["item_count"], 1)
        self.assertEqual(obj["ignored_count"], 1)
        self.assertNotIn("original", obj["items"][0])
        self.assertIn('\n  "subsmerge_version"', self.output.read_text())
        internal = self.source / "custom.json"
        self.assertEqual(self.cli("-o", internal).returncode, 0)
        self.assertEqual(self.cli("-o", internal, "--overwrite").returncode, 0)
        self.assertEqual(json.loads(internal.read_text(encoding="utf-8"))["item_count"], 1)

    def test_external_symlink_rejected(self):
        outside = self.root / "external.json"
        outside.write_text("{}")
        link = self.source / "linked.json"
        try:
            link.symlink_to(outside)
        except OSError:
            self.skipTest("symlink privilege unavailable")
        self.assertNotIn(link, subsmerge.find_json_files(self.source, self.output))
        self.assertEqual(subsmerge.merge_files([link], self.source, self.output), 2)

    def test_atomic_failure_does_not_change_existing_output(self):
        good = self.transcript()
        self.output.write_text("previous")
        with patch("common.os.replace", side_effect=OSError("synthetic failure")):
            self.assertEqual(subsmerge.merge_files([good], self.source, self.output, overwrite=True), 2)
        self.assertEqual(self.output.read_text(), "previous")
        self.assertEqual(list(self.root.glob(".write-*")), [])

    def test_hardlink_source_identity(self):
        good = self.transcript()
        try:
            self.output.hardlink_to(good)
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.assertEqual(subsmerge.merge_files([good], self.source, self.output, overwrite=True), 2)

    def test_error_sidecar_cannot_replace_source(self):
        self.transcript()
        sidecar = self.transcript("dataset.errors.json")
        before = sidecar.read_bytes()
        result = self.cli("-o", self.source / "dataset.json", "--overwrite")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(sidecar.read_bytes(), before)

    def test_powershell_launchers(self):
        self.transcript()
        for name in ("powershell", "pwsh"):
            executable = shutil.which(name)
            if not executable:
                continue
            with self.subTest(shell=name):
                output = self.root / (name + " café 雪.json")
                command = [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(Path(subsmerge.__file__).with_suffix(".ps1")), str(self.source),
                           "-Output", str(output)]
                result = subprocess.run(command + ["-Python", sys.executable], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["item_count"], 1)
                result = subprocess.run(command + ["-Python", sys.executable], capture_output=True)
                self.assertEqual(result.returncode, 2)
                result = subprocess.run(command + ["-Python", sys.executable, "-Overwrite"], capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run(command + ["-Python", "missing-synthetic-executable-19483"],
                                        capture_output=True)
                self.assertEqual(result.returncode, 2)

    def test_staging_alias_back_to_root_is_excluded(self):
        canonical_root = self.source.resolve()
        good = self.transcript().resolve()
        alias = canonical_root / "_tmp"
        candidate = alias / good.name
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == candidate:
                return good
            if path == alias:
                return canonical_root
            return original_resolve(path, *args, **kwargs)

        with patch.object(Path, "resolve", resolve):
            self.assertFalse(subsmerge.eligible_path(candidate, canonical_root))

    @unittest.skipUnless(sys.platform == "win32", "Windows 8.3 path API required")
    def test_windows_short_path_aliases(self):
        import ctypes
        from ctypes import wintypes

        self.source = (self.root / "long folder name for subsmerge").resolve()
        self.source.mkdir()
        good = self.transcript("long transcript filename.json")
        get_short_path = ctypes.WinDLL("kernel32", use_last_error=True).GetShortPathNameW
        get_short_path.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        get_short_path.restype = wintypes.DWORD

        def short_path(path):
            required = get_short_path(str(path), None, 0)
            if not required:
                raise ctypes.WinError(ctypes.get_last_error())
            buffer = ctypes.create_unicode_buffer(required)
            written = get_short_path(str(path), buffer, required)
            if not written or written >= required:
                raise ctypes.WinError(ctypes.get_last_error())
            return Path(buffer.value)

        short_source = short_path(self.source)
        short_good = short_path(good)
        if short_source == self.source and short_good == good:
            self.skipTest("volume does not provide 8.3 aliases for new files")
        self.assertNotEqual((short_source, short_good), (self.source, good))
        self.assertEqual(short_source.resolve(), self.source.resolve())
        self.assertTrue(subsmerge.eligible_path(short_good, self.source))
        self.assertTrue(subsmerge.eligible_path(good, short_source))
        self.assertEqual(subsmerge.merge_files([short_good], self.source, self.output), 0)
        payload = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(payload["items"][0]["source_relative_path"], good.name)
        other = self.root / "other.json"
        self.assertEqual(subsmerge.merge_files([good], short_source, other), 0)
        normalized = subsmerge.normalize_item(json.loads(good.read_text(encoding="utf-8")),
                                              short_good, self.source, False, False)
        self.assertEqual(normalized["source_relative_path"], good.name)
        result = self.cli("-o", short_good, "--overwrite")
        self.assertEqual(result.returncode, 2, result.stderr)
        staged = self.transcript(".staging/staged.json")
        self.assertFalse(subsmerge.eligible_path(short_path(staged), short_source))
        self.source = short_source
        result = self.cli("-o", self.root / "cli.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((self.root / "cli.json").read_text(encoding="utf-8"))["item_count"], 1)

    def test_text_only_keeps_text_once_and_preserves_provenance(self):
        sentence = "A unique synthetic sentence for corpus checking."
        processing = {"tool_versions": {"yt-dlp": "test-version"}, "raw_sha256": "a" * 64,
                      "product_version": "synthetic-1"}
        source = self.write("track.json", {
            "schema_version": "subsdown.v4", "type": "YouTubeSubtitleTranscript",
            "video": {"title": "Synthetic track", "channel": "Test channel", "id": "abc",
                      "url_clean": "https://www.youtube.com/watch?v=abc"},
            "subtitle": {"language": "fr", "kind": "auto", "origin": "youtube auto-generated captions",
                         "translated": False}, "processing": processing,
            "transcript": {"plain_text": sentence, "segments": [
                {"index": 1, "start": "00:00:01,000", "end": "00:00:03,000", "text": sentence}]}})
        markdown = self.output.with_suffix(".md")
        self.assertEqual(subsmerge.merge_files([source], self.source, self.output,
                                              text_only=True, markdown_output=markdown), 0)
        encoded = self.output.read_text(encoding="utf-8")
        item = json.loads(encoded)["items"][0]
        self.assertEqual(encoded.count(sentence), 1)
        self.assertEqual(markdown.read_text(encoding="utf-8").count(sentence), 1)
        self.assertNotIn("segments", item)
        self.assertNotIn("original", item)
        self.assertEqual(item["subtitle"]["segment_count"], 1)
        self.assertEqual(item["subtitle"]["kind"], "auto")
        self.assertEqual(item["subtitle"]["origin"], "youtube auto-generated captions")
        self.assertIs(item["subtitle"]["translated"], False)
        self.assertEqual(item["processing"], processing)
        self.assertEqual(item["source_schema_version"], "subsdown.v4")
        self.assertEqual(item["source_sha256"], sha256(source))
        self.assertNotIn("00:00:01,000", markdown.read_text(encoding="utf-8"))

    def test_paired_corpus_same_subset_order_timestamps_and_unknown_provenance(self):
        selected = []
        for index in (13, 2, 25, 1):
            selected.append(self.write(f"track-{index}.json", {
                "video": {"title": f"Video {index}", "id": f"id-{index}", "channel": "Synthetic", "url": f"https://example.com/{index}"},
                "playlist": {"index": index}, "subtitle": {"language": "en", "kind": "manual"},
                "transcript": {"segments": [{"start": "00:00:00,500", "end": "00:00:01,500", "text": f"Sentence {index}."}]}}))
        self.transcript("older.json", "An unrelated older transcript")
        markdown = self.output.with_suffix(".md")
        self.assertEqual(subsmerge.merge_files(selected, self.source, self.output,
                                              include_original=False, markdown_output=markdown), 0)
        items = json.loads(self.output.read_text(encoding="utf-8"))["items"]
        self.assertEqual([item["video_id"] for item in items], ["id-1", "id-2", "id-13", "id-25"])
        text = markdown.read_text(encoding="utf-8")
        positions = [text.index("## " + str(n) + ". " + item["title"]) for n, item in enumerate(items, 1)]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(text.count("[00:00:00,500 --> 00:00:01,500]"), 4)
        self.assertNotIn("An unrelated older transcript", text)
        self.assertIn("- Translated: unknown", text)
        self.assertIn("- Caption origin: unknown", text)
        for item in items:
            self.assertNotIn("original", item)
            self.assertIn("segments", item)
            self.assertNotIn("translated", item["subtitle"])
            self.assertIn(item["url"], text)

    def test_all_destinations_preflight_before_writing(self):
        good = self.transcript()
        source_markdown = self.source / "transcript.md"
        source_markdown.write_text("Source Markdown must survive", encoding="utf-8")
        staging_markdown = self.source / ".staging" / "transcript.md"
        staging_markdown.parent.mkdir()
        staging_markdown.write_text("Staged source Markdown", encoding="utf-8")
        for markdown in (good, source_markdown, staging_markdown, self.output, self.output.with_suffix(".errors.json")):
            with self.subTest(markdown=markdown):
                self.assertEqual(subsmerge.merge_files([good], self.source, self.output,
                                                      markdown_output=markdown, overwrite=True), 2)
                self.assertFalse(self.output.exists())
                self.assertEqual(source_markdown.read_text(encoding="utf-8"), "Source Markdown must survive")
        blocker = self.root / "parent-is-a-file"
        blocker.write_text("previous")
        self.assertEqual(subsmerge.merge_files([good], self.source, self.output,
                                              markdown_output=blocker / "result.md"), 2)
        self.assertFalse(self.output.exists())

    def test_markdown_and_error_hardlinks_to_unselected_source_are_protected(self):
        good = self.transcript()
        other = self.transcript("unselected.json", "Unselected source")
        before = other.read_bytes()
        for target in (self.root / "corpus.md", self.output.with_suffix(".errors.json")):
            with self.subTest(target=target):
                try:
                    target.hardlink_to(other)
                except OSError:
                    self.skipTest("hardlinks unavailable")
                try:
                    self.assertEqual(subsmerge.merge_files([good], self.source, self.output,
                                                          markdown_output=self.root / "corpus.md", overwrite=True), 2)
                    self.assertEqual(other.read_bytes(), before)
                    self.assertFalse(self.output.exists())
                finally:
                    target.unlink()

    def test_paired_io_failure_removes_only_new_json(self):
        source = self.transcript()
        before = source.read_bytes()
        markdown = self.root / "corpus.md"
        markdown.write_text("previous Markdown", encoding="utf-8")
        with patch("subsmerge.atomic_write_text", side_effect=OSError("synthetic Markdown failure")):
            self.assertEqual(subsmerge.merge_files([source], self.source, self.output,
                                                  markdown_output=markdown, overwrite=True), 2)
        self.assertFalse(self.output.exists())
        self.assertEqual(markdown.read_text(encoding="utf-8"), "previous Markdown")
        self.output.write_text("previous derived output", encoding="utf-8")
        with patch("subsmerge.atomic_write_text", side_effect=OSError("synthetic Markdown failure")):
            self.assertEqual(subsmerge.merge_files([source], self.source, self.output,
                                                  markdown_output=markdown, overwrite=True), 2)
        self.assertTrue(self.output.exists())
        self.assertEqual(json.loads(self.output.read_text(encoding="utf-8"))["item_count"], 1)
        self.assertEqual(source.read_bytes(), before)
        self.assertEqual(markdown.read_text(encoding="utf-8"), "previous Markdown")

    def test_cli_machine_report_success_strict_and_fatal(self):
        self.transcript()
        markdown = self.root / "corpus.md"
        completed = self.cli("--json", "-o", self.output, "--markdown-output", markdown, "--text-only")
        self.assertEqual(completed.returncode, 0, completed.stderr)
        result = json.loads(completed.stdout)
        self.assertEqual(result["schema"], "subsmerge.result.v1")
        self.assertEqual(result["version"], VERSION)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["item_count"], 1)
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["output_json"], str(self.output))
        self.assertEqual(result["output_markdown"], str(markdown))
        self.assertIn("JSON integrated:", completed.stderr)
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
        bad = self.source / "broken.json"
        bad.write_text("{invalid", encoding="utf-8")
        strict = self.cli("--json", "-o", self.root / "strict.json", "--fail-on-error")
        self.assertEqual(strict.returncode, 3, strict.stderr)
        result = json.loads(strict.stdout)
        self.assertEqual(result["exit_code"], 3)
        self.assertEqual(result["error_count"], 1)
        self.assertIsNone(result["output_json"])
        self.assertTrue(Path(result["error_log"]).is_file())
        invalid = self.cli("--json", "--unknown-option")
        self.assertEqual(invalid.returncode, 2)
        self.assertEqual(json.loads(invalid.stdout)["exit_code"], 2)
        missing = subprocess.run([sys.executable, str(Path(subsmerge.__file__)),
                                  str(self.root / "missing"), "--json"], capture_output=True, encoding="utf-8")
        self.assertEqual(missing.returncode, 2)
        self.assertIn("error", json.loads(missing.stdout))

    def test_powershell_paired_text_only_machine_report_and_setup_failure(self):
        self.transcript()
        for shell in ("powershell", "pwsh"):
            executable = shutil.which(shell)
            if not executable:
                continue
            with self.subTest(shell=shell):
                output = self.root / (shell + "-corpus.json")
                markdown = output.with_suffix(".md")
                command = [executable, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(Path(subsmerge.__file__).with_suffix(".ps1")), str(self.source),
                           "-Output", str(output), "-MarkdownOutput", str(markdown), "-TextOnly", "-Json"]
                completed = subprocess.run(command + ["-Python", sys.executable], capture_output=True, encoding="utf-8")
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertEqual(json.loads(completed.stdout)["output_markdown"], str(markdown))
                item = json.loads(output.read_text(encoding="utf-8"))["items"][0]
                self.assertNotIn("original", item)
                self.assertNotIn("segments", item)
                missing = subprocess.run(command + ["-Python", "missing-synthetic-executable-19483"], capture_output=True, encoding="utf-8")
                self.assertEqual(missing.returncode, 2)
                self.assertEqual(json.loads(missing.stdout)["schema"], "subsmerge.result.v1")

    def test_default_cli_name(self):
        self.transcript()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "subsmerge-sources.json").is_file())


if __name__ == "__main__":
    unittest.main()
