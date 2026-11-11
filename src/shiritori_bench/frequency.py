"""BCCWJ noun-reading frequency annotations, separate from game legality."""

from __future__ import annotations

import csv
from functools import lru_cache
import io
import json
from pathlib import Path
from typing import Any, TextIO
import zipfile

from .normalize import normalize_reading

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INDEX_PATH = PROJECT_ROOT / "data/processed/word-frequency.json"


def aggregate_tubelex(source: TextIO, forms: dict[str, set[str]]) -> tuple[dict[str, Any], dict[str, int]]:
    """Bounds on matched written-form counts, without guessing pronunciations.

    The published POS is a majority label, not a POS-specific count.
    Lower counts include only forms with one eligible JMdict noun reading;
    upper counts also include forms ambiguous between multiple readings.
    Neither is a direct measurement of spoken reading frequency.
    """
    reader = csv.DictReader(source, delimiter="\t", quoting=csv.QUOTE_NONE)
    if not {"word", "count", "pos"}.issubset(reader.fieldnames or []):
        raise ValueError("TUBELEX file must have word, count, and pos columns")
    totals: dict[str, Any] = {}
    stats = {"corpus_tokens": 0, "noun_majority_forms": 0,
             "uniquely_matched_forms": 0, "ambiguous_forms": 0, "unmatched_forms": 0,
             "unidic_suffix_matches": 0}
    for row in reader:
        count = int(row["count"])
        if count < 0:
            raise ValueError("Negative TUBELEX count")
        if row["word"] == "[TOTAL]":
            stats["corpus_tokens"] = count
            continue
        if not row["pos"].startswith("名詞-普通名詞"):
            continue
        stats["noun_majority_forms"] += 1
        candidates = forms.get(row["word"], set())
        # UniDic loanword lemmas carry an origin label: e.g. マップ-map.
        # Strip metadata only as a fallback and only if the whole Japanese
        # prefix is a known dictionary form; never split arbitrary compounds.
        if not candidates and "-" in row["word"]:
            candidates = forms.get(row["word"].split("-", 1)[0], set())
            if candidates:
                stats["unidic_suffix_matches"] += 1
        if not candidates:
            stats["unmatched_forms"] += 1
            continue
        ambiguous = len(candidates) > 1
        stats["ambiguous_forms" if ambiguous else "uniquely_matched_forms"] += 1
        for reading in candidates:
            item = totals.setdefault(reading, {"count": 0, "count_upper": 0,
                                                "lemmas": [], "ambiguous_lemmas": []})
            item["count_upper"] += count
            if not ambiguous:
                item["count"] += count
            key = "ambiguous_lemmas" if ambiguous else "lemmas"
            if len(item[key]) < 12:
                item[key].append(row["word"])
    denominator = stats["corpus_tokens"]
    if denominator <= 0:
        raise ValueError("Missing or invalid TUBELEX [TOTAL] row")
    for item in totals.values():
        item["per_million"] = item["count"] * 1_000_000 / denominator
        item["per_million_upper"] = item["count_upper"] * 1_000_000 / denominator
    return totals, stats


def aggregate_rows(source: TextIO) -> dict[str, dict[str, Any]]:
    """Sum noun homophones; exclude proper nouns, numerals and affixes.

    lForm is a lemma reading, not necessarily a surface pronunciation.
    Exact NFKC/kana matching only: do not guess long-vowel equivalences.
    """
    reader = csv.DictReader(source, delimiter="\t", quoting=csv.QUOTE_NONE)
    required = {"lForm", "lemma", "pos", "frequency", "pmw"}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError(f"BCCWJ TSV missing columns: {required - set(reader.fieldnames or [])}")
    totals: dict[str, dict[str, Any]] = {}
    for row in reader:
        pos = row["pos"]
        if not pos.startswith("名詞") or any(tag in pos for tag in ("固有名詞", "数詞", "接頭辞", "接尾辞")):
            continue
        reading = normalize_reading(row["lForm"])
        if not reading or reading == "null":
            continue
        count = int(row["frequency"])
        pmw = float(row["pmw"])
        if count <= 0 or pmw < 0:
            raise ValueError("Invalid frequency in BCCWJ source")
        item = totals.setdefault(reading, {"count": 0, "per_million": 0.0,
                                            "entry_count": 0, "lemmas": []})
        item["count"] += count
        item["per_million"] += pmw
        item["entry_count"] += 1
        if row["lemma"] not in item["lemmas"] and len(item["lemmas"]) < 8:
            item["lemmas"].append(row["lemma"])
    # Competition ranks: tied aggregate counts share their rank.
    previous, rank = None, 0
    for position, item in enumerate(sorted(totals.values(), key=lambda item: -item["count"]), 1):
        if item["count"] != previous:
            previous, rank = item["count"], position
        item["noun_reading_rank"] = rank
        item["per_million"] = round(item["per_million"], 7)
    return totals


def read_archive(path: Path, unit: str) -> dict[str, dict[str, Any]]:
    expected = f"BCCWJ_frequencylist_{unit}_ver1_0.tsv"
    with zipfile.ZipFile(path) as archive:
        members = [name for name in archive.namelist() if Path(name).name == expected]
        if len(members) != 1:
            raise ValueError(f"Expected exactly one {expected} in {path}")
        with archive.open(members[0]) as binary:
            with io.TextIOWrapper(binary, encoding="utf-8-sig", newline="") as source:
                return aggregate_rows(source)


@lru_cache(maxsize=1)
def load_frequency() -> dict[str, Any]:
    path = INDEX_PATH if INDEX_PATH.exists() else INDEX_PATH.with_name("bccwj-frequency.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def lookup_frequency(word: str) -> dict[str, Any]:
    if not word or word == "PASS":
        return {}
    return load_frequency().get("readings", {}).get(normalize_reading(word), {})


def frequency_label(word: str) -> str:
    if not load_frequency():
        return "Frequency: dataset not installed"
    values = lookup_frequency(word)
    if load_frequency().get("source_id") == "tubelex":
        item = values.get("tubelex")
        if not item:
            return "TUBELEX: unavailable (no matched noun form)"
        low, high = item["per_million"], item["per_million_upper"]
        if item["count"] != item["count_upper"]:
            return f"TUBELEX: {low:.3g}–{high:.3g}/million (reading ambiguous; matched-form bounds)"
        return f"TUBELEX: {low:.3g}/million (matched-form estimate; rank {item['matched_reading_rank']:,})"
    if not values:
        return "BCCWJ: unavailable"
    parts = []
    for unit in ("suw", "luw"):
        entry = values.get(unit)
        parts.append(f"{unit.upper()} {entry['per_million']:.3g}/million (noun-reading rank {entry['noun_reading_rank']:,})"
                     if entry else f"{unit.upper()} unavailable")
    return "BCCWJ: " + "; ".join(parts)
