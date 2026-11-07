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
from common import VERSION


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

    def test_default_cli_name(self):
        self.transcript()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "subsmerge-sources.json").is_file())


if __name__ == "__main__":
    unittest.main()
