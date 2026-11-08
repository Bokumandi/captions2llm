"""Offline acceptance of the Captions2LLM facade and retained legacy contracts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
FAKE = ROOT / "tests" / "fake_ytdlp.py"
VIDEO = "https://youtu.be/aaaaaaaaaaa"
COMMANDS = ("download", "merge", "index", "prepare", "status", "accept-report")


class BrandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="c2l-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.cwd = self.root / "unrelated working directory"
        self.cwd.mkdir()
        # A copied/extracted source distribution must find its sibling engines,
        # VERSION and cleaner independently of the caller's current directory.
        self.source = self.root / "extracted sources café 雪"
        self.source.mkdir()
        for path in ROOT.iterdir():
            if path.is_file() and (path.suffix in {".py", ".ps1", ".cmd"} or path.name == "VERSION"):
                shutil.copy2(path, self.source / path.name)

    def invoke(self, command, *args, shell=None, legacy=False, python=None, json_mode=True):
        args = list(map(str, args))
        if shell:
            script = "captions2llm"
            if legacy:
                script = {"download": "subsdown", "merge": "subsmerge"}.get(command, "subsbatch")
                if command not in {"download", "merge"}:
                    args.insert(0, command)
            elif command is not None:
                args.insert(0, command)
            if python is not None:
                args += ["-Python", python]
            if json_mode:
                args.append("-Json")
            if shell == "cmd":
                # CMD /s /c strips the outer quote pair. Keep a second pair
                # around the batch path so a source path with spaces is usable
                # even when the caller is outside the source directory.
                native = subprocess.list2cmdline([str(self.source / (script + ".cmd")), *args])
                launch = subprocess.list2cmdline([shutil.which("cmd.exe"), "/d", "/s", "/c"]) + ' "' + native + '"'
            else:
                launch = [shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-File", str(self.source / (script + ".ps1")), *args]
        else:
            script = "captions2llm.py"
            if legacy:
                script = {"download": "subsdown.py", "merge": "subsmerge.py"}.get(command, "subsbatch.py")
                if command not in {"download", "merge"}:
                    args.insert(0, command)
            elif command is not None:
                args.insert(0, command)
            if json_mode:
                args.append("--json")
            launch = [sys.executable, "-X", "utf8", str(self.source / script), *args]
        completed = subprocess.run(launch, cwd=self.cwd, capture_output=True,
                                   encoding="utf-8", errors="strict", timeout=90)
        if not json_mode:
            return completed
        self.assertEqual(len(completed.stdout.strip().splitlines()), 1,
                         completed.stdout + "\n" + completed.stderr)
        result = json.loads(completed.stdout)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["exit_code"], completed.returncode,
                         completed.stdout + "\n" + completed.stderr)
        return completed, result

    def success(self, command, *args, **kwargs):
        completed, result = self.invoke(command, *args, **kwargs)
        self.assertEqual(completed.returncode, 0, completed.stdout + "\n" + completed.stderr)
        schema_key = "schema_version" if command == "download" else "schema"
        schema = {"download": "subsdown.result.v1", "merge": "subsmerge.result.v1"}.get(
            command, "subsbatch.result.v1")
        self.assertEqual(result[schema_key], schema)
        return result

    @staticmethod
    def read_json(path):
        return json.loads(Path(path).read_text(encoding="utf-8"))

    @staticmethod
    def digest(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def download_args(self, output, shell=False):
        if shell:
            return [VIDEO, "-OutRoot", output, "-YtDlp", FAKE, "-FFmpeg", FAKE, "-Merge", "-TextOnly"]
        return [VIDEO, "--out-root", output, "--yt-dlp", FAKE, "--ffmpeg", FAKE, "--merge", "--text-only"]

    def complete_report(self, plan_path):
        plan = self.read_json(plan_path)
        self.assertEqual(len(plan["batches"]), 1)
        batch = plan["batches"][0]
        report = self.read_json(plan_path.parent / batch["template_file"])
        report.update(agent="Synthetic acceptance agent", model="synthetic-model",
                      instructions="Read the assigned synthetic ranges.",
                      synthesis="Synthetic synthesis café 雪.")
        parts = {part["part_id"]: part for part in plan["parts"]}
        for row in report["parts"]:
            fragment = parts[row["part_id"]]["fragments"][0]
            row.update(status="complete", summary="Synthetic summary.",
                       topics=["Synthetic topic"], observations=["Synthetic observation"],
                       evidence=[{key: fragment[key] for key in (
                           "segment_index", "segment_ordinal", "start", "end", "offset_start", "offset_end")}])
        path = plan_path.parent / "supplied report café 雪.json"
        path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        return path

    def workflow(self, label, shell=None, legacy=False):
        shell_options = {"shell": shell, "legacy": legacy}
        if shell:
            shell_options["python"] = sys.executable
        output = self.root / (label + " captions café 雪")
        downloaded = self.success("download", *self.download_args(output, bool(shell)), **shell_options)
        self.assertEqual(downloaded["summary"], {"success": 1, "unavailable": 0, "failed": 0})
        self.assertEqual(Path(downloaded["output_root"]).resolve(), output.resolve())
        source = next(output.rglob("transcript.json"))
        transcript = self.read_json(source)
        self.assertEqual(transcript["schema_version"], "subsdown.v4")
        self.assertEqual(transcript["video"]["id"], "aaaaaaaaaaa")
        self.assertEqual(transcript["subtitle"]["language"], "fr-orig")
        self.assertEqual(transcript["subtitle"]["kind"], "auto")
        self.assertIs(transcript["subtitle"]["translated"], False)
        self.assertEqual(transcript["transcript"]["plain_text"], "Bonjour tout le monde\nUne nouvelle ligne")
        self.assertEqual(transcript["processing"]["downloader"], "yt-dlp")
        self.assertEqual(transcript["processing"]["tool_versions"]["yt_dlp"], "synthetic-1.0")
        snapshots = {path: path.read_bytes() for path in source.parent.iterdir()}
        auto_corpus = self.read_json(downloaded["merged_json"])
        self.assertEqual(auto_corpus["subsmerge_version"], "2.0.0")
        self.assertEqual(auto_corpus["items"][0]["source_sha256"], self.digest(source))
        self.assertNotIn("segments", auto_corpus["items"][0])
        self.assertNotIn("original", auto_corpus["items"][0])

        merged_path = self.root / (label + " merged café 雪.json")
        markdown = merged_path.with_suffix(".md")
        options = ["-Output", merged_path, "-MarkdownOutput", markdown, "-TextOnly"] if shell else [
            "--output", merged_path, "--markdown-output", markdown, "--text-only"]
        merged = self.success("merge", output, *options, **shell_options)
        self.assertEqual(merged["item_count"], 1)
        self.assertEqual(Path(merged["output_json"]).resolve(), merged_path.resolve())
        corpus = self.read_json(merged_path)
        self.assertEqual(corpus["items"], auto_corpus["items"])
        self.assertEqual(corpus["items"][0]["processing"], transcript["processing"])
        self.assertIn(transcript["transcript"]["plain_text"], markdown.read_text(encoding="utf-8"))

        indexed_output = self.root / (label + " index café 雪")
        output_flag = "-Output" if shell else "--output"
        indexed = self.success("index", output, output_flag, indexed_output, **shell_options)
        index = self.read_json(indexed["index_json"])
        self.assertEqual(index["schema"], "subsbatch.index.v1")
        self.assertEqual(index["items"][0]["source_sha256"], self.digest(source))
        self.assertEqual(index["items"][0]["subtitle"]["language"], "fr-orig")
        self.assertNotIn("Bonjour", json.dumps(index, ensure_ascii=False))

        plan_output = self.root / (label + " reading café 雪")
        prepared = self.success("prepare", output, output_flag, plan_output,
                                "-MaxChars" if shell else "--max-chars", 1400, **shell_options)
        plan_path = Path(prepared["plan_path"])
        self.assertEqual(plan_path.resolve(), (plan_output / "plan.json").resolve())
        plan = self.read_json(plan_path)
        self.assertEqual(plan["schema"], "subsbatch.plan.v1")
        self.assertEqual(len(plan["parts"]), 1)
        self.assertEqual(plan["parts"][0]["source_sha256"], self.digest(source))
        reading = (plan_output / plan["batches"][0]["reading_file"]).read_text(encoding="utf-8")
        self.assertLessEqual(len(reading), 1400)
        for cue in transcript["transcript"]["segments"]:
            self.assertIn(cue["text"], reading)
            self.assertIn(cue["start"], reading)
        pending = self.success("status", plan_path, **shell_options)
        self.assertEqual(pending["counts"]["pending"], 1)
        report = self.complete_report(plan_path)
        report_args = ["-Report", report, "-Folder", plan_path] if shell and not legacy else [plan_path, report]
        accepted = self.success("accept-report", *report_args, **shell_options)
        self.assertEqual(accepted["state"], "declared_complete")
        self.assertIs(accepted["semantic_verification"], False)
        self.assertIn("Synthetic synthesis café 雪.", Path(accepted["report_markdown"]).read_text(encoding="utf-8"))
        if shell and not legacy:
            mixed = self.success("accept-report", plan_path, "-Report", report, "-Overwrite", **shell_options)
            self.assertEqual(mixed["state"], "declared_complete")
        complete = self.success("status", plan_path, **shell_options)
        self.assertEqual(complete["counts"], {"pending": 0, "partial": 0,
                                            "declared_complete": 1, "invalidated": 0})
        for path, content in snapshots.items():
            self.assertEqual(path.read_bytes(), content)
        return transcript, {name: set(result) for name, result in (
            ("download", downloaded), ("merge", merged), ("index", indexed),
            ("prepare", prepared), ("status", complete), ("accept-report", accepted))}, plan_path

    def test_python_canonical_and_legacy_workflows_preserve_data_and_result_contracts(self):
        canonical, canonical_fields, plan = self.workflow("canonical")
        legacy, legacy_fields, _ = self.workflow("legacy", legacy=True)
        canonical, legacy = deepcopy(canonical), deepcopy(legacy)
        canonical.pop("created_at")
        legacy.pop("created_at")
        self.assertEqual(canonical, legacy)
        self.assertEqual(canonical_fields, legacy_fields)
        self.assertEqual(self.success("status", plan, legacy=True)["counts"]["declared_complete"], 1)

    def test_windows_facades_run_all_six_commands_from_unicode_source_and_external_cwd(self):
        shells = [shutil.which(name) for name in ("powershell.exe", "pwsh.exe") if shutil.which(name)]
        if sys.platform == "win32":
            shells.append("cmd")
        if not shells:
            self.skipTest("Windows launchers unavailable")
        for number, shell in enumerate(shells):
            with self.subTest(shell=shell):
                _, _, plan = self.workflow("shell" + str(number), shell=shell)
                # Historical shell entry points still read a plan produced by
                # the canonical facade without schema conversion.
                legacy = self.success("status", plan, shell=shell, legacy=True, python=sys.executable)
                self.assertEqual(legacy["counts"]["declared_complete"], 1)

    def test_python_help_version_invalid_command_and_engine_errors(self):
        help_result = self.invoke(None, "--help", json_mode=False)
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("Captions2LLM", help_result.stdout)
        for command in COMMANDS:
            self.assertIn(command, help_result.stdout)
        version = self.invoke(None, "--version", json_mode=False)
        self.assertEqual(version.returncode, 0)
        self.assertIn((ROOT / "VERSION").read_text(encoding="utf-8").strip(), version.stdout)
        unknown, result = self.invoke("unsupported-synthetic-command")
        self.assertEqual(unknown.returncode, 2)
        self.assertEqual(result["schema"], "captions2llm.result.v1")
        self.assertIn("error", result)
        for command in COMMANDS:
            with self.subTest(command=command):
                args = [VIDEO, "--yt-dlp", "missing-c2l-tool-417294"] if command == "download" else [self.root / "missing"]
                canonical, result = self.invoke(command, *args)
                legacy, old_result = self.invoke(command, *args, legacy=True)
                self.assertEqual(canonical.returncode, 1 if command == "download" else 2)
                self.assertEqual(canonical.returncode, legacy.returncode)
                self.assertEqual(set(result), set(old_result))
                self.assertEqual(result.get("schema", result.get("schema_version")),
                                 old_result.get("schema", old_result.get("schema_version")))
                self.assertIn("error", result)

    def test_partial_download_exit_and_legacy_default_output_names_are_retained(self):
        output = self.root / "partial"
        args = ["https://www.youtube.com/playlist?list=PL_SYNTHETIC", *self.download_args(output)[1:]]
        completed, result = self.invoke("download", *args)
        self.assertEqual(completed.returncode, 2, completed.stderr)
        self.assertEqual(result["schema_version"], "subsdown.result.v1")
        self.assertEqual(result["summary"], {"success": 1, "unavailable": 2, "failed": 0})
        self.assertTrue(Path(result["manifest_path"]).name.endswith(".json"))
        self.assertEqual(Path(result["manifest_path"]).parent.name, ".runs")
        self.assertTrue(Path(result["merged_json"]).name.startswith("subsmerge-"))
        self.assertTrue(Path(result["index_json"]).name.startswith("subsindex-"))
        self.assertEqual(len(list(output.rglob("transcript.json"))), 1)

    def test_windows_help_version_unknown_commands_and_interpreter_failures(self):
        shells = [shutil.which(name) for name in ("powershell.exe", "pwsh.exe") if shutil.which(name)]
        if sys.platform == "win32":
            shells.append("cmd")
        if not shells:
            self.skipTest("Windows launchers unavailable")
        for shell in shells:
            with self.subTest(shell=shell):
                help_result = self.invoke(None, "--help", shell=shell, json_mode=False, python=sys.executable)
                self.assertEqual(help_result.returncode, 0, help_result.stdout + help_result.stderr)
                self.assertIn("Captions2LLM", help_result.stdout)
                version = self.invoke(None, "--version", shell=shell, json_mode=False, python=sys.executable)
                self.assertEqual(version.returncode, 0, version.stdout + version.stderr)
                self.assertIn((ROOT / "VERSION").read_text(encoding="utf-8").strip(), version.stdout)
                unknown, result = self.invoke("unsupported-synthetic-command", shell=shell, python=sys.executable)
                self.assertEqual(unknown.returncode, 2)
                self.assertEqual(result["schema"], "captions2llm.result.v1")
                for command in COMMANDS:
                    with self.subTest(command=command):
                        completed, result = self.invoke(command, self.root / "unused", shell=shell,
                                                        python="missing-c2l-python-417294")
                        self.assertEqual(completed.returncode, 1 if command == "download" else 2)
                        schema = {"download": "subsdown.result.v1", "merge": "subsmerge.result.v1"}.get(
                            command, "subsbatch.result.v1")
                        self.assertEqual(result.get("schema", result.get("schema_version")), schema)
                        self.assertIn("error", result)

    def test_powershell_documented_tool_splat_preserves_values_and_boolean_switches(self):
        shells = [shutil.which(name) for name in ("powershell.exe", "pwsh.exe") if shutil.which(name)]
        if not shells:
            self.skipTest("PowerShell unavailable")
        def literal(value):
            return "'" + str(value).replace("'", "''") + "'"
        for number, shell in enumerate(shells):
            with self.subTest(shell=shell):
                output = self.root / ("splat" + str(number) + " café 雪")
                tools = {"Python": sys.executable, "YtDlp": FAKE, "FFmpeg": FAKE, "OutRoot": output}
                assignments = [key + "=" + literal(value) for key, value in tools.items()]
                assignments += ["Json=$true", "Merge=$true", "Manual=$false", "TextOnly=$false"]
                script = "$Tools=@{" + "; ".join(assignments) + "}; & " + literal(self.source / "captions2llm.ps1")
                script += " download " + literal(VIDEO) + " @Tools; exit $LASTEXITCODE"
                completed = subprocess.run([shell, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                                            "-Command", script], cwd=self.cwd, capture_output=True,
                                           encoding="utf-8", timeout=90)
                self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
                self.assertEqual(len(completed.stdout.strip().splitlines()), 1)
                result = json.loads(completed.stdout)
                self.assertEqual(result["schema_version"], "subsdown.result.v1")
                self.assertEqual(result["exit_code"], 0)
                self.assertEqual(Path(result["output_root"]).resolve(), output.resolve())
                item = self.read_json(result["merged_json"])["items"][0]
                self.assertEqual(item["subtitle"]["kind"], "auto")
                self.assertEqual(item["subtitle"]["language"], "fr-orig")
                self.assertEqual(len(item["segments"]), 2)


if __name__ == "__main__":
    unittest.main()
