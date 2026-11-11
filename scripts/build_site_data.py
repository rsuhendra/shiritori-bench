#!/usr/bin/env python3
"""Publish-safe snapshot of existing pilots and analyses. No API calls."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
from shiritori_bench.public_site import build_public_payload
from shiritori_bench.results import read_jsonl


def newest(pattern):
    paths = sorted(PROJECT_ROOT.glob(pattern))
    if not paths:
        raise SystemExit(f"Missing {pattern}; generate the corresponding offline analysis first")
    return paths[-1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", type=Path)
    parser.add_argument("--diagnostics", type=Path)
    parser.add_argument("--destination", type=Path, default=PROJECT_ROOT / "web/data/results.json")
    args = parser.parse_args()
    analysis = args.analysis or newest("results/move-analysis/*/analysis.json")
    diagnostics = args.diagnostics or newest("results/score-diagnostics/*/analysis.json")
    frequency = PROJECT_ROOT / "data/processed/word-frequency.json"
    sources = sorted((PROJECT_ROOT / "results/pilots").glob("*/matches.jsonl"))
    records = [record for path in sources for record in read_jsonl(path)]
    if len({m["match_id"] for m in records}) != len(records):
        raise SystemExit("Duplicate match IDs: refusing to double-count games")
    frequency_data = json.loads(frequency.read_text())
    analysis_data = json.loads(analysis.read_text())
    diagnostic_data = json.loads(diagnostics.read_text())
    expected_hash = frequency_data.get("vocabulary_sha256")
    if not expected_hash or any(source.get("vocabulary_sha256") != expected_hash
            for source in (analysis_data, diagnostic_data)):
        raise SystemExit("Refusing to combine analyses from different vocabulary snapshots")
    payload = build_public_payload(records, frequency_data, analysis_data, diagnostic_data)
    payload["provenance"] = [{"file": str(path.relative_to(PROJECT_ROOT)),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        for path in [*sources, analysis, diagnostics, frequency]]
    args.destination.parent.mkdir(parents=True, exist_ok=True)
    args.destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Exported {len(payload['games'])} competitive games; {payload['summary']['excluded_games']} infrastructure error(s) excluded.")
    print(f"Saved public allowlisted data: {args.destination}")


if __name__ == "__main__":
    main()
