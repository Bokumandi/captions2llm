"""Validated SRT parsing and conservative cleanup of rolling subtitle windows.

Derived from https://github.com/bindestriche/srt_fix, revision
5b4442a8cdcae06c53545f4d0c99c3e624416919. Upstream code: Unlicense;
local modifications: MIT. See NOTICE.md and LICENSES/srt_fix-Unlicense.txt.
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
import os
import re
from typing import Iterable, Iterator

from common import atomic_write_text


class Subtitle:
    """One nonempty subtitle with a positive interval and nonnegative times."""

    def __init__(self, start_duration: timedelta, end_duration: timedelta, text: str):
        if not isinstance(start_duration, timedelta) or not isinstance(end_duration, timedelta):
            raise ValueError("Subtitle times must be timedelta values")
        if start_duration < timedelta(0) or end_duration <= start_duration:
            raise ValueError("Subtitle end must be after its nonnegative start")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Subtitle text must not be empty")
        self.start = start_duration
        self.end = end_duration
        self.text = text.strip()

    @staticmethod
    def _print_duration(duration: timedelta) -> str:
        if not isinstance(duration, timedelta) or duration < timedelta(0):
            raise ValueError("Timestamp must be a nonnegative timedelta")
        milliseconds = (duration.days * 86400 + duration.seconds) * 1000 + duration.microseconds // 1000
        hours, remainder = divmod(milliseconds, 3600000)
        minutes, remainder = divmod(remainder, 60000)
        seconds, milliseconds = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def __str__(self) -> str:
        return f"{self._print_duration(self.start)} --> {self._print_duration(self.end)}\n{self.text}\n\n"

    def __repr__(self) -> str:
        return f"Subtitle Object start:{self.start}, end:{self.end}, text:{self.text!r}"


class SimpleSrt:
    """Parse every SRT block, rejecting malformed or empty input as a whole."""

    _TIMECODE = re.compile(
        r"(\d{2,}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*"
        r"(\d{2,}):(\d{2}):(\d{2}),(\d{3})"
    )

    def __init__(self, srt_string: str):
        self.subs = list(self.parse_srt(srt_string))

    @staticmethod
    def get_duration(parts) -> timedelta:
        try:
            hour, minute, second, millisecond = parts
        except (TypeError, ValueError) as error:
            raise ValueError("Timestamp requires hours, minutes, seconds and milliseconds") from error
        if any(type(value) is not int for value in (hour, minute, second, millisecond)):
            raise ValueError("Timestamp components must be integers")
        if hour < 0 or not 0 <= minute < 60 or not 0 <= second < 60 or not 0 <= millisecond < 1000:
            raise ValueError("Timestamp component out of range")
        try:
            return timedelta(hours=hour, minutes=minute, seconds=second, milliseconds=millisecond)
        except OverflowError as error:
            raise ValueError("Timestamp is too large") from error

    def parse_timecode_string(self, line):
        """Return a valid interval, or False for a non-timecode line."""
        match = self._TIMECODE.fullmatch(line.strip())
        if match is None:
            return False
        try:
            start = self.get_duration(tuple(map(int, match.groups()[:4])))
            end = self.get_duration(tuple(map(int, match.groups()[4:])))
        except ValueError:
            return False
        return (start, end) if end > start else False

    def parse_srt(self, subtitle_text: str) -> Iterator[Subtitle]:
        if not isinstance(subtitle_text, str):
            raise ValueError("SRT input must be text")
        normalized = subtitle_text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ValueError("SRT input is empty")
        for block_number, block in enumerate(re.split(r"\n[ \t]*\n+", normalized), 1):
            lines = block.split("\n")
            if len(lines) < 3 or not re.fullmatch(r"[0-9]+", lines[0].strip()) or int(lines[0]) < 1:
                raise ValueError(f"SRT block {block_number} requires a positive cue index, timecode and text")
            interval = self.parse_timecode_string(lines[1])
            if not interval:
                raise ValueError(f"SRT block {block_number} has an invalid timecode")
            text = "\n".join(line.strip() for line in lines[2:]).strip()
            if not text:
                raise ValueError(f"SRT block {block_number} has no subtitle text")
            # An unseparated second cue is malformed; never consume it as dialogue.
            if any(self._TIMECODE.fullmatch(line.strip()) or "-->" in line for line in lines[2:]):
                raise ValueError(f"SRT block {block_number} contains an unexpected timecode")
            yield Subtitle(*interval, text)


def dedupe_yt_srt(subs_iter: Iterable[Subtitle]) -> Iterator[Subtitle]:
    """Remove shared complete lines only from overlapping, advancing windows.

    Exact repeats, isolated short cues and cues separated by a gap are retained.
    At least two words must overlap and the current cue must add new text. No
    timing is shortened, swapped or extended. Use manual mode to bypass this
    heuristic entirely when the source contains authored overlapping dialogue.
    """
    previous = None
    for original in subs_iter:
        subtitle = Subtitle(original.start, original.end, original.text)
        if previous is not None and subtitle.start < previous.end and previous.start <= subtitle.start:
            previous_lines = previous.text.splitlines()
            current_lines = subtitle.text.splitlines()
            # Longest complete-line suffix/prefix match, with a novel remainder.
            for count in range(min(len(previous_lines), len(current_lines) - 1), 0, -1):
                overlap = current_lines[:count]
                if previous_lines[-count:] == overlap and len(" ".join(overlap).split()) >= 2:
                    subtitle.text = "\n".join(current_lines[count:])
                    break
        yield subtitle
        previous = original


def subs_to_text(subs_iter: Iterable[Subtitle]) -> str:
    """Serialize nonempty cues with consecutive indices and standard spacing."""
    return "".join(f"{index}\n{subtitle}" for index, subtitle in enumerate(subs_iter, 1))


def clean_text(text: str, *, manual: bool = False) -> str:
    """Validate SRT and return normalized UTF-8-ready text, optionally deduped."""
    subtitles = SimpleSrt(text).subs
    return subs_to_text(subtitles if manual else dedupe_yt_srt(subtitles))


def process_srt(file_path, new_file_path, *, manual: bool = False, overwrite: bool = False):
    """Validate then atomically write a distinct output; existing files need opt-in."""
    source, target = Path(file_path), Path(new_file_path)
    if source.resolve() == target.resolve() or (target.exists() and os.path.samefile(source, target)):
        raise ValueError("Input and output must be different files")
    if target.exists() and not overwrite:
        raise FileExistsError(f"Output already exists: {target.name}; use --overwrite explicitly")
    text = source.read_text(encoding="utf-8-sig")
    cleaned = clean_text(text, manual=manual)
    atomic_write_text(target, cleaned, overwrite=overwrite)
