#!/usr/bin/env python3
"""Print clean transcripts and save games.txt; defaults to the latest pilot."""

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.results import read_jsonl
from shiritori_bench.transcript import render_games


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", nargs="?", type=Path, help="Run directory or matches.jsonl")
    args = parser.parse_args()
    source = args.run
    if source is None:
        candidates = sorted((PROJECT_ROOT / "results/pilots").glob("*/matches.jsonl"))
        if not candidates:
            parser.error("No completed pilot records found")
        source = candidates[-1]
    if source.is_dir():
        source = source / "matches.jsonl"
    transcript = render_games(read_jsonl(source))
    destination = source.parent / "games.txt"
    destination.write_text(transcript, encoding="utf-8")
    print(transcript)
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()
