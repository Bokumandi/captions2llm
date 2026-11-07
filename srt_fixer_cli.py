"""Command-line entry point for the derived srt_fix cleaner (Unlicense)."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys

from common import VERSION
from simplesrt import process_srt


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate SRT and conservatively remove overlapping rolling lines.")
    parser.add_argument("input", nargs="?", help="Input subtitle file.")
    parser.add_argument("-o", "--output", help="Output subtitle file or existing directory.")
    parser.add_argument("-idir", "--input-directory", help="Input directory containing SRT files.")
    parser.add_argument("-odir", "--output-directory", help="Directory for processed subtitle files.")
    parser.add_argument("-manual", "--manual", action="store_true", help="Preserve every cue and text line; validate and normalize only.")
    parser.add_argument("--overwrite", action="store_true", help="Explicitly replace existing output files (never the input).")
    parser.add_argument("--version", action="version", version=VERSION)
    args = parser.parse_args(argv)
    if bool(args.input) == bool(args.input_directory):
        parser.error("provide one input file or --input-directory")
    if args.input_directory and args.output:
        parser.error("--output is for one input file; use --output-directory for a batch")
    if args.output and args.output_directory:
        parser.error("choose --output or --output-directory")

    try:
        if args.input_directory:
            directory = Path(args.input_directory)
            if not directory.is_dir():
                raise ValueError("Input directory does not exist or is inaccessible")
            sources = sorted((path for path in directory.iterdir() if path.is_file()
                              and path.suffix.lower() == ".srt" and not path.name.lower().endswith(".fixed.srt")),
                             key=lambda path: path.name.casefold())
            if not sources:
                raise ValueError("Input directory contains no source SRT files")
            output_directory = Path(args.output_directory) if args.output_directory else directory
            jobs = [(source, output_directory / (source.stem + ".fixed.srt")) for source in sources]
        else:
            source = Path(args.input)
            if not source.is_file():
                raise ValueError("Input file does not exist or is inaccessible")
            if args.output:
                output = Path(args.output)
                target = output / (source.stem + ".fixed.srt") if output.is_dir() else output
            elif args.output_directory:
                target = Path(args.output_directory) / (source.stem + ".fixed.srt")
            else:
                target = source.with_name(source.stem + ".fixed.srt")
            jobs = [(source, target)]
        failed = False
        for source, target in jobs:
            try:
                process_srt(source, target, manual=args.manual, overwrite=args.overwrite)
                print(f"Written: {target.name}")
            except (OSError, ValueError) as error:
                print(f"Error processing {source.name}: {error}", file=sys.stderr)
                failed = True
        return 1 if failed else 0
    except (OSError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
