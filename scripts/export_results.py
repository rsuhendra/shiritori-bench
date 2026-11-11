#!/usr/bin/env python3
"""Aggregate append-only match records into the static website payload."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.results import (  # noqa: E402
    aggregate_for_web,
    read_jsonl,
    write_web_results,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "source",
        type=Path,
        nargs="?",
        default=PROJECT_ROOT / "results/raw/matches.jsonl",
    )
    parser.add_argument(
        "destination",
        type=Path,
        nargs="?",
        default=PROJECT_ROOT / "web/data/results.json",
    )
    parser.add_argument(
        "--vocabulary-version",
        default="jmdict-2026-10-13-noun-v2",
    )
    arguments = parser.parse_args()
    payload = aggregate_for_web(
        read_jsonl(arguments.source),
        vocabulary_version=arguments.vocabulary_version,
    )
    write_web_results(arguments.destination, payload)


if __name__ == "__main__":
    main()
