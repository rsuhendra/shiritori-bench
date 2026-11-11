#!/usr/bin/env python3
"""Analyze vocabulary, frequency coverage, thresholds and CDFs for every kana."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.frequency import INDEX_PATH
from shiritori_bench.kana_analysis import analyze, text_report


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocabulary", type=Path, default=PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite")
    parser.add_argument("--frequency", type=Path, default=INDEX_PATH)
    parser.add_argument("--thresholds", type=float, nargs="+", default=[0, 0.1, 1, 10])
    parser.add_argument("--alpha", type=float, default=1, help="Sampling weight = frequency ** alpha")
    parser.add_argument("--frequency-policy", choices=["unambiguous", "lower"], default="unambiguous",
                        help="Exclude ambiguous readings, or use their uniquely assigned lower counts")
    parser.add_argument("--top", type=int, default=10, help="Example words per kana")
    parser.add_argument("--output-dir", type=Path, help="New directory; existing directories are not overwritten")
    args = parser.parse_args()
    if not args.frequency.exists():
        parser.error("Install TUBELEX frequencies with scripts/build_tubelex_frequency.py first")
    index = json.loads(args.frequency.read_text(encoding="utf-8"))
    vocabulary_hash = digest(args.vocabulary)
    if index.get("vocabulary_sha256") != vocabulary_hash:
        parser.error("Frequency index was built for a different vocabulary; rebuild it first")
    with sqlite3.connect(f"{args.vocabulary.resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT reading, start_kana, end_kana, common FROM words")]
    try:
        analysis, word_rows = analyze(rows, index, thresholds=args.thresholds,
                                     alpha=args.alpha, policy=args.frequency_policy, top=args.top)
    except ValueError as error:
        parser.error(str(error))
    analysis["provenance"] = {"created_at": datetime.now(timezone.utc).isoformat(),
        "vocabulary_sha256": vocabulary_hash, "frequency_sha256": digest(args.frequency),
        "frequency_source": index.get("source"), "source_revision": index.get("revision"),
        "scope": "Initial safe vocabulary; no model calls, used words, or strategy simulation."}
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = args.output_dir or PROJECT_ROOT / "results/analysis" / identifier
    destination.mkdir(parents=True, exist_ok=False)
    report = text_report(analysis)
    (destination / "summary.txt").write_text(report, encoding="utf-8")
    (destination / "analysis.json").write_text(json.dumps(analysis, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (destination / "word-distributions.jsonl").open("w", encoding="utf-8") as output:
        for word in word_rows:
            output.write(json.dumps(word, ensure_ascii=False, allow_nan=False) + "\n")
    # Compact console view; full per-kana explanations and examples are in summary.txt.
    print(report.split("PER-KANA DETAILS")[0])
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()
