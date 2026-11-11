#!/usr/bin/env python3
"""Build a reading-frequency proxy from a pinned TUBELEX Japanese lemma list."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import lzma
import sqlite3
import unicodedata
import shutil
import urllib.request
import xml.etree.ElementTree as ET

from build_vocabulary import PROJECT_ROOT, eligible_senses, open_source, text_values
from shiritori_bench.frequency import INDEX_PATH, aggregate_tubelex
from shiritori_bench.normalize import normalize_reading

REVISION = "7cb5fb36add76b83a266d1967536e1a1d3faa513"
BASE_URL = f"https://raw.githubusercontent.com/naist-nlp/tubelex/{REVISION}"


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--download", action="store_true", help="Download missing pinned TUBELEX files")
    args = parser.parse_args()
    vocabulary = PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite"
    archive = PROJECT_ROOT / "data/raw/tubelex-ja-lemma-pos.tsv.xz"
    jmdict = PROJECT_ROOT / "data/raw/JMdict_e.gz"
    license_path = PROJECT_ROOT / "data/raw/TUBELEX-LICENSE.txt"
    for destination, url in ((archive, f"{BASE_URL}/frequencies/tubelex-ja-lemma-pos.tsv.xz"),
                             (license_path, f"{BASE_URL}/LICENSE")):
        if destination.exists():
            continue
        if not args.download:
            parser.error(f"Missing {destination}; use --download")
        temporary = destination.with_suffix(destination.suffix + ".part")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as source, temporary.open("wb") as output:
            shutil.copyfileobj(source, output)
        temporary.replace(destination)
    with sqlite3.connect(f"{vocabulary.as_uri()}?mode=ro", uri=True) as connection:
        readings = {row[0] for row in connection.execute("SELECT reading FROM words")}
    forms = {}
    with open_source(jmdict) as source:
        for _, entry in ET.iterparse(source, events=("end",)):
            if entry.tag != "entry":
                continue
            entry_forms = set(text_values(entry, "k_ele/keb"))
            for node in entry.findall("r_ele"):
                original = node.findtext("reb", "")
                restrictions = set(text_values(node, "re_restr"))
                permitted = set() if node.find("re_nokanji") is not None else restrictions or entry_forms
                senses = eligible_senses(entry, original, permitted)
                if not senses:
                    continue
                reading = normalize_reading(original)
                # Match each form only to senses actually applicable to it.
                for form in permitted | {original}:
                    if form != original and not eligible_senses(entry, original, {form}):
                        continue
                    key = unicodedata.normalize("NFKC", form).lower()
                    forms.setdefault(key, set()).add(reading)
            entry.clear()
    with lzma.open(archive, "rt", encoding="utf-8-sig", newline="") as source:
        totals, stats = aggregate_tubelex(source, forms)
    matched = readings & totals.keys()
    records = {reading: totals[reading] for reading in matched}
    previous, rank = None, 0
    ranked = sorted((item for item in records.values() if item["count"] > 0), key=lambda item: -item["count"])
    for position, item in enumerate(ranked, 1):
        if item["count"] != previous:
            previous, rank = item["count"], position
        item["matched_reading_rank"] = rank
    unambiguous = sum(item["count"] == item["count_upper"] for item in records.values())
    result = {
        "schema_version": 2, "source_id": "tubelex", "source": "TUBELEX Japanese lemma-majority-POS",
        "built_at": datetime.now(timezone.utc).isoformat(), "revision": REVISION,
        "reference": "https://github.com/naist-nlp/tubelex",
        "paper": "https://aclanthology.org/2025.coling-main.641/",
        "source_url": f"{BASE_URL}/frequencies/tubelex-ja-lemma-pos.tsv.xz",
        "license": "BSD-3-Clause; see data/raw/TUBELEX-LICENSE.txt",
        "archive_sha256": digest(archive), "jmdict_sha256": digest(jmdict),
        "vocabulary_sha256": digest(vocabulary), "statistics": stats,
        "coverage": {"vocabulary_readings": len(readings), "any_form_match": len(records),
                     "fraction": len(records) / len(readings), "unambiguous_only": unambiguous,
                     "ambiguous_only": sum(item["count"] == 0 for item in records.values())},
        "policy": "Majority ordinary-noun POS only. NFKC/lower written-form join through eligible JMdict noun senses; UniDic suffix metadata (e.g. マップ-map) stripped only when Japanese prefix matches. Homophones summed; homograph counts bounded, not allocated. No inferred vowel equivalences or compound reconstruction. Counts may include other POS uses because source POS is majority only.",
        "rank_policy": "Competition ranks of uniquely assigned counts among matched benchmark readings with positive lower counts; not corpus-wide noun ranks. Ambiguous estimates are not displayed with a rank.",
        "readings": {reading: {"tubelex": item} for reading, item in records.items()},
    }
    INDEX_PATH.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"coverage": result["coverage"], "statistics": stats}, indent=2))
    print(f"Saved: {INDEX_PATH}")


if __name__ == "__main__":
    main()
