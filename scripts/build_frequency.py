#!/usr/bin/env python3
"""Download/import BCCWJ v1.0 lists; keep their tokenizations separate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import urllib.request
import urllib.error

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.frequency import INDEX_PATH, read_archive

SOURCES = {
    "suw": "https://repository.ninjal.ac.jp/records/3234/files/BCCWJ_frequencylist_suw_ver1_0.zip?download=1",
    "luw": "https://repository.ninjal.ac.jp/records/3228/files/BCCWJ_frequencylist_luw_ver1_0.zip?download=1",
}


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download missing archives from NINJAL")
    parser.add_argument("--units", nargs="+", choices=SOURCES, default=["suw", "luw"])
    args = parser.parse_args()
    vocabulary = PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite"
    with sqlite3.connect(f"{vocabulary.as_uri()}?mode=ro", uri=True) as connection:
        readings = {row[0] for row in connection.execute("SELECT reading FROM words")}
    result = {"schema_version": 1, "source": "NINJAL BCCWJ1 frequency lists v1.0",
              "built_at": datetime.now(timezone.utc).isoformat(),
              "reference": "https://clrd.ninjal.ac.jp/bccwj/en/freq-list.html",
              "manual": "https://clrd.ninjal.ac.jp/bccwj/data-files/frequency-list/BCCWJ_frequencylist_manual_ver1_0.pdf",
              "usage": "Research/educational use; consult the source manual before redistribution.",
              "matching": "Exact normalized lemma reading; noun homophones summed; proper nouns and numerals excluded. Not a JMdict sense-level alignment.",
              "rank_policy": "Competition rank among all eligible noun readings in each source, before vocabulary filtering.",
              "vocabulary_sha256": digest(vocabulary), "vocabulary_readings": len(readings),
              "sources": {}, "coverage": {}, "readings": {}}
    for unit in args.units:
        archive = PROJECT_ROOT / f"data/raw/BCCWJ_frequencylist_{unit}_ver1_0.zip"
        if not archive.exists() and args.download:
            archive.parent.mkdir(parents=True, exist_ok=True)
            temporary = archive.with_suffix(".zip.part")
            print(f"Downloading {unit.upper()} from NINJAL...", flush=True)
            try:
                with urllib.request.urlopen(SOURCES[unit], timeout=180) as response, temporary.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
            except (urllib.error.URLError, TimeoutError) as error:
                parser.exit(1, f"NINJAL download failed: {error}\nNo new frequency index was installed. Retry later or place the official archive at {archive}.\n")
            temporary.replace(archive)
        if not archive.exists():
            parser.error(f"Missing {archive}. Use --download or place the official archive there.")
        print(f"Importing {unit.upper()}...", flush=True)
        totals = read_archive(archive, unit)
        matched = readings & totals.keys()
        for reading in matched:
            result["readings"].setdefault(reading, {})[unit] = totals[reading]
        result["sources"][unit] = {"url": SOURCES[unit], "archive": archive.name, "sha256": digest(archive)}
        result["coverage"][unit] = {"matched_readings": len(matched), "fraction": len(matched) / len(readings)}
    result["coverage"]["either"] = {"matched_readings": len(result["readings"]),
                                      "fraction": len(result["readings"]) / len(readings)}
    INDEX_PATH.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["coverage"], indent=2))
    print(f"Saved: {INDEX_PATH}")


if __name__ == "__main__":
    main()
