"""Source release tests use synthetic local Git repositories only."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / "release.py"


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.repo = self.base / "source with spaces"
        self.repo.mkdir()
        self.git("init", "-q")
        shutil.copyfile(SOURCE, self.repo / "release.py")
        (self.repo / "VERSION").write_text("0.1.0\n", encoding="utf-8")
        (self.repo / "README.md").write_text("Synthetic source\n", encoding="utf-8")
        (self.repo / ".github").mkdir()
        (self.repo / ".github" / "ci.yml").write_text("fixture\n", encoding="utf-8")
        self.git("add", ".")
        self.commit("initial")
        self.first = self.git("rev-parse", "HEAD").strip()

    def tearDown(self):
        self.temp.cleanup()

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True, encoding="utf-8",
            stderr=subprocess.PIPE)

    def commit(self, message):
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                 "commit", "-qm", message)

    def run_release(self, directory, ref="HEAD"):
        return subprocess.run(
            [sys.executable, str(self.repo / "release.py"), "--output-dir", str(directory),
             "--ref", ref], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def test_reproducible_exact_commit_and_untracked_exclusion(self):
        (self.repo / "VERSION").write_text("0.2.0\n", encoding="utf-8")
        self.git("add", "VERSION")
        self.commit("new version")
        (self.repo / "private.log").write_text("secret", encoding="utf-8")
        first, second = self.base / "one", self.base / "two"
        for out in (first, second):
            result = self.run_release(out, self.first)
            self.assertEqual(result.returncode, 0, result.stderr)
        for name in ("subsdown-v0.1.0-source.zip", "release-manifest.json", "SHA256SUMS"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        manifest = json.loads((first / "release-manifest.json").read_text(encoding="utf-8"))
        archive = first / manifest["archive"]
        self.assertEqual(manifest["commit"], self.first)
        self.assertEqual(manifest["version"], "0.1.0")
        self.assertEqual(manifest["tree"], self.git("rev-parse", self.first + "^{tree}").strip())
        self.assertEqual(manifest["archive_sha256"], hashlib.sha256(archive.read_bytes()).hexdigest())
        expected = self.git("ls-tree", "-r", "--name-only", self.first).splitlines()
        self.assertEqual([x["path"] for x in manifest["files"]], expected)
        with zipfile.ZipFile(archive) as zf:
            self.assertEqual(zf.namelist(), ["subsdown-v0.1.0/" + p for p in expected])
            for entry in manifest["files"]:
                path = entry["path"]
                content = zf.read("subsdown-v0.1.0/" + path)
                original = subprocess.check_output(["git", "-C", str(self.repo), "show", self.first + ":" + path])
                self.assertEqual(content, original)
                self.assertEqual(hashlib.sha256(content).hexdigest(), entry["sha256"])
            destination = self.base / "extract with spaces"
            zf.extractall(destination)
            self.assertEqual((destination / "subsdown-v0.1.0" / "VERSION").read_text(), "0.1.0\n")
        for line in (first / "SHA256SUMS").read_text().splitlines():
            value, name = line.split("  ", 1)
            self.assertEqual(value, hashlib.sha256((first / name).read_bytes()).hexdigest())
        self.assertNotEqual(self.run_release(first, self.first).returncode, 0)

    def test_dirty_tracked_file_is_refused(self):
        (self.repo / "README.md").write_text("dirty", encoding="utf-8")
        result = self.run_release(self.base / "out")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Tracked changes", result.stderr)
        self.assertFalse((self.base / "out").exists())

    def test_unsafe_tracked_entry_is_refused(self):
        (self.repo / ".env.secret").write_text("synthetic", encoding="utf-8")
        self.git("add", ".env.secret")
        self.commit("unsafe")
        result = self.run_release(self.base / "out")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unsafe", result.stderr)

    def test_invalid_ref_is_refused(self):
        result = self.run_release(self.base / "out", "not-a-ref")
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.base / "out").exists())

    def test_derived_analysis_artifacts_are_refused(self):
        (self.repo / '.batches').mkdir()
        (self.repo / '.batches' / 'report.json').write_text('{}', encoding='utf-8')
        self.git('add', '.batches')
        self.commit('accidentally tracked analysis')
        result = self.run_release(self.base / 'out')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Unsafe', result.stderr)
        self.assertFalse((self.base / 'out').exists())


if __name__ == "__main__":
    unittest.main()
