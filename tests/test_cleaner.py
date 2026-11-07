"""Synthetic acceptance checks for the derived subtitle cleaner."""
from datetime import timedelta
import contextlib
import io
from pathlib import Path
import tempfile
import unittest

from common import sha256
from simplesrt import SimpleSrt, Subtitle, clean_text, dedupe_yt_srt, process_srt, subs_to_text
from srt_fixer_cli import main


def cue(number, start, end, text):
    return f"{number}\n{start} --> {end}\n{text}\n\n"


SINGLE = cue(1, "00:00:01,000", "00:00:02,000", "A synthetic line.")


class ParserTests(unittest.TestCase):
    def test_bom_crlf_multiline_and_numeric_dialogue(self):
        source = "\ufeff" + cue(9, "00:00:01,000", "00:00:02,000", "First line\n42\nSecond line").replace("\n", "\r\n")
        parsed = SimpleSrt(source).subs
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0].text, "First line\n42\nSecond line")
        self.assertEqual(clean_text(source, manual=True), cue(1, "00:00:01,000", "00:00:02,000", "First line\n42\nSecond line"))

    def test_empty_and_unparseable_input_rejected(self):
        for source in ("", " \n\t", "1 None", "plain transcript", "\ufeff"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                clean_text(source)
        self.assertEqual(list(dedupe_yt_srt([])), [])
        self.assertEqual(subs_to_text([]), "")

    def test_malformed_block_is_not_silently_skipped(self):
        for source in (SINGLE + "garbage", SINGLE + "2\ninvalid\nText\n", SINGLE + "2\n00:00:03,000 --> 00:00:04,000\n",
                       "0\n00:00:00,000 --> 00:00:01,000\nText", "00:00:00,000 --> 00:00:01,000\nText"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                clean_text(source)

    def test_strict_timestamp_ranges_and_order(self):
        invalid = ("00:60:00,000", "00:00:60,000", "00:00:00,1000", "-01:00:00,000", "0:00:00,000", "00:00:00.000")
        for start in invalid:
            with self.subTest(start=start), self.assertRaises(ValueError):
                clean_text(cue(1, start, "02:00:00,000", "Text"))
        for start, end in (("00:00:02,000", "00:00:01,000"), ("00:00:01,000", "00:00:01,000")):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                clean_text(cue(1, start, end, "Text"))
        with self.assertRaises(ValueError):
            SimpleSrt.get_duration((0, 60, 0, 0))
        with self.assertRaises(ValueError):
            Subtitle(timedelta(seconds=-1), timedelta(seconds=1), "Text")

    def test_trailing_timecode_junk_and_missing_separator_rejected(self):
        for source in (SINGLE.replace("00:00:02,000", "00:00:02,000 junk"), SINGLE.rstrip() + "\n2\n00:00:03,000 --> 00:00:04,000\nText"):
            with self.subTest(source=source), self.assertRaises(ValueError):
                clean_text(source)

    def test_durations_over_24_hours_do_not_wrap(self):
        source = cue(1, "49:01:02,345", "49:01:03,456", "A long recording.")
        self.assertEqual(clean_text(source), source)
        self.assertEqual(Subtitle._print_duration(timedelta(days=2, hours=1, minutes=1, seconds=2, milliseconds=345)), "49:01:02,345")
        with self.assertRaises(ValueError):
            Subtitle._print_duration(timedelta(milliseconds=-1))


class DedupeTests(unittest.TestCase):
    def test_overlapping_advancing_windows_remove_only_shared_lines(self):
        source = (cue(1, "00:00:00,000", "00:00:03,000", "First shared line")
                  + cue(2, "00:00:01,000", "00:00:04,000", "First shared line\nSecond shared line")
                  + cue(3, "00:00:02,000", "00:00:05,000", "First shared line\nSecond shared line\nThird line"))
        result = SimpleSrt(clean_text(source)).subs
        self.assertEqual([item.text for item in result], ["First shared line", "Second shared line", "Third line"])
        self.assertEqual([(item.start, item.end) for item in result], [(item.start, item.end) for item in SimpleSrt(source).subs])

    def test_genuine_repeated_phrase_preserved(self):
        source = cue(1, "00:00:00,000", "00:00:02,000", "Say it again.") + cue(2, "00:00:01,000", "00:00:03,000", "Say it again.")
        self.assertEqual(clean_text(source), source)

    def test_long_gap_and_touching_cues_preserved(self):
        for start, end in (("00:00:02,000", "00:00:03,000"), ("00:01:00,000", "00:01:02,000")):
            source = cue(1, "00:00:00,000", "00:00:02,000", "A repeated line") + cue(2, start, end, "A repeated line\nA new line")
            self.assertEqual(clean_text(source), source)

    def test_short_manual_cues_and_one_word_overlap_preserved(self):
        source = (cue(1, "00:00:00,000", "00:00:00,100", "Yes.")
                  + cue(2, "00:00:00,050", "00:00:00,120", "Yes.\nGo.")
                  + cue(3, "00:00:00,120", "00:00:00,200", "No."))
        self.assertEqual(clean_text(source), source)

    def test_manual_mode_retains_rolling_content(self):
        source = cue(1, "00:00:00,000", "00:00:02,000", "Shared line") + cue(2, "00:00:01,000", "00:00:03,000", "Shared line\nNew line")
        self.assertEqual(clean_text(source, manual=True), source)
        self.assertNotEqual(clean_text(source), source)

    def test_cleaning_does_not_mutate_supplied_subtitles(self):
        source = SimpleSrt(cue(1, "00:00:00,000", "00:00:02,000", "Shared line") + cue(2, "00:00:01,000", "00:00:03,000", "Shared line\nNew line")).subs
        list(dedupe_yt_srt(source))
        self.assertEqual(source[1].text, "Shared line\nNew line")


class OutputAndCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source.srt"
        self.source.write_text(SINGLE, encoding="utf-8")

    def invoke(self, arguments):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(arguments)

    def test_process_srt_is_atomic_and_preserves_source(self):
        target = self.root / "nested" / "output.srt"
        before = sha256(self.source)
        process_srt(self.source, target)
        self.assertEqual(target.read_text(encoding="utf-8"), SINGLE)
        self.assertEqual(sha256(self.source), before)
        self.assertEqual(list(target.parent.glob(".write-*.tmp")), [])

    def test_same_source_and_existing_output_require_safety(self):
        with self.assertRaises(ValueError):
            process_srt(self.source, self.source, overwrite=True)
        target = self.root / "target.srt"
        target.write_text("existing output", encoding="utf-8")
        with self.assertRaises(FileExistsError):
            process_srt(self.source, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "existing output")
        process_srt(self.source, target, overwrite=True)
        self.assertEqual(target.read_text(encoding="utf-8"), SINGLE)

    def test_invalid_input_does_not_replace_existing_output(self):
        target = self.root / "target.srt"
        target.write_text("existing output", encoding="utf-8")
        self.source.write_text("1 None", encoding="utf-8")
        with self.assertRaises(ValueError):
            process_srt(self.source, target, overwrite=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "existing output")

    def test_no_output_argument_and_output_directory(self):
        self.assertEqual(self.invoke([str(self.source)]), 0)
        self.assertTrue((self.root / "source.fixed.srt").is_file())
        target_dir = self.root / "out"
        self.assertEqual(self.invoke([str(self.source), "-odir", str(target_dir)]), 0)
        self.assertTrue((target_dir / "source.fixed.srt").is_file())
        target_dir_2 = self.root / "existing"
        target_dir_2.mkdir()
        self.assertEqual(self.invoke([str(self.source), "-o", str(target_dir_2)]), 0)
        self.assertTrue((target_dir_2 / "source.fixed.srt").is_file())

    def test_invalid_cli_input_has_nonzero_status(self):
        for source in ("", "garbage"):
            self.source.write_text(source, encoding="utf-8")
            self.assertEqual(self.invoke([str(self.source)]), 1)
        self.assertFalse((self.root / "source.fixed.srt").exists())
        self.assertEqual(self.invoke([str(self.root / "missing.srt")]), 1)
        with self.assertRaises(SystemExit) as result:
            self.invoke([])
        self.assertNotEqual(result.exception.code, 0)

    def test_batch_filters_files_and_excludes_generated_outputs(self):
        (self.root / "extra.SRT").write_text(SINGLE, encoding="utf-8")
        (self.root / "already.fixed.srt").write_text(SINGLE, encoding="utf-8")
        (self.root / "unrelated.txt").write_text("ignore", encoding="utf-8")
        output = self.root / "out"
        self.assertEqual(self.invoke(["-idir", str(self.root), "-odir", str(output), "-manual"]), 0)
        self.assertEqual(sorted(path.name for path in output.iterdir()), ["extra.fixed.srt", "source.fixed.srt"])
        self.assertEqual(self.invoke(["-idir", str(self.root), "-odir", str(output)]), 1)
        self.assertEqual(self.invoke(["-idir", str(self.root), "-odir", str(output), "--overwrite"]), 0)

    def test_cli_manual_option_and_source_refusal(self):
        source = cue(1, "00:00:00,000", "00:00:02,000", "Shared line") + cue(2, "00:00:01,000", "00:00:03,000", "Shared line\nNew line")
        self.source.write_text(source, encoding="utf-8")
        target = self.root / "manual.srt"
        self.assertEqual(self.invoke([str(self.source), "-o", str(target), "--manual"]), 0)
        self.assertEqual(target.read_text(encoding="utf-8"), source)
        self.assertEqual(self.invoke([str(self.source), "-o", str(self.source), "--overwrite"]), 1)


if __name__ == "__main__":
    unittest.main()
