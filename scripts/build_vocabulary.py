#!/usr/bin/env python3
"""Build a preliminary SQLite vocabulary from a pinned JMdict XML file.

The noun/POS policy is intentionally centralized here so it can be reviewed and
versioned before official benchmark runs.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import xml.etree.ElementTree as ET


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.normalize import (  # noqa: E402
    initial_kana,
    is_hiragana_word,
    normalize_reading,
    terminal_kana,
)


FILTER_VERSION = "noun-v3"
COMMON_PRIORITIES = {"news1", "ichi1", "spec1", "spec2", "gai1"}
ALLOWED_POS_MARKERS = (
    "noun (common)",
    "adverbial noun",
    "noun (temporal)",
    "noun or participle which takes the aux. verb suru",
)
REJECTED_MARKERS = (
    "abbreviation",
    "archaic",
    "obsolete",
    "proper noun",
    "person name",
    "place name",
    "company name",
    "organization name",
    "prefix",
    "counter",
)


def text_values(parent: ET.Element, path: str) -> list[str]:
    return [node.text for node in parent.findall(path) if node.text]


def marker_matches(labels: set[str], markers: tuple[str, ...]) -> bool:
    return any(marker in label for label in labels for marker in markers)


def sense_applies_to_reading(
    sense: ET.Element,
    reading: str,
    permitted_forms: set[str],
) -> bool:
    restricted_readings = set(text_values(sense, "stagr"))
    if restricted_readings and reading not in restricted_readings:
        return False

    restricted_forms = set(text_values(sense, "stagk"))
    if restricted_forms and not (restricted_forms & permitted_forms):
        return False
    return True


def eligible_senses(
    entry: ET.Element,
    reading: str,
    permitted_forms: set[str],
) -> list[ET.Element]:
    """Return eligible noun senses applicable to a specific reading.

    JMdict permits later senses to omit POS tags and inherit them from the
    preceding sense, so the effective POS set is carried forward here.
    Suffix usage is not a veto when that same sense also has an allowed
    standalone noun POS. Suffix-only senses still fail ALLOWED_POS_MARKERS.
    """

    effective_pos: set[str] = set()
    eligible: list[ET.Element] = []
    for sense in entry.findall("sense"):
        explicit_pos = {
            value.casefold() for value in text_values(sense, "pos")
        }
        if explicit_pos:
            effective_pos = explicit_pos
        misc = {value.casefold() for value in text_values(sense, "misc")}
        labels = effective_pos | misc
        if not sense_applies_to_reading(sense, reading, permitted_forms):
            continue
        if not marker_matches(effective_pos, ALLOWED_POS_MARKERS):
            continue
        if marker_matches(labels, REJECTED_MARKERS):
            continue
        eligible.append(sense)
    return eligible


def source_digest(source: Path) -> str:
    with source.open("rb") as source_file:
        return hashlib.file_digest(source_file, "sha256").hexdigest()


def open_source(source: Path):
    if source.suffix == ".gz":
        return gzip.open(source, "rb")
    return source.open("rb")


def build(source: Path, destination: Path, *, common_only: bool = False) -> None:
    connection = sqlite3.connect(destination)
    connection.executescript(
        """
        DROP TABLE IF EXISTS metadata;
        DROP TABLE IF EXISTS words;
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE words (
            id INTEGER PRIMARY KEY,
            jmdict_id INTEGER NOT NULL,
            reading TEXT NOT NULL UNIQUE,
            display_forms TEXT NOT NULL,
            start_kana TEXT NOT NULL,
            end_kana TEXT NOT NULL,
            pos TEXT NOT NULL,
            common INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX words_by_start ON words(start_kana);
        CREATE INDEX words_by_transition ON words(start_kana, end_kana);
        """
    )

    connection.executemany(
        "INSERT INTO metadata (key, value) VALUES (?, ?)",
        (
            ("source_filename", source.name),
            ("source_sha256", source_digest(source)),
            ("filter_version", FILTER_VERSION),
            ("common_only", str(common_only).lower()),
        ),
    )

    with open_source(source) as source_file:
        entries = ET.iterparse(source_file, events=("end",))
        for _, entry in entries:
            if entry.tag != "entry":
                continue

            sequence_text = entry.findtext("ent_seq")
            if not sequence_text:
                entry.clear()
                continue

            forms = text_values(entry, "k_ele/keb")
            for reading_element in entry.findall("r_ele"):
                reading_text = reading_element.findtext("reb")
                if not reading_text:
                    continue
                reading = normalize_reading(reading_text)
                if not is_hiragana_word(reading) or reading.endswith("ー"):
                    continue

                reading_restrictions = set(text_values(reading_element, "re_restr"))
                no_kanji = reading_element.find("re_nokanji") is not None
                if no_kanji:
                    permitted_forms: set[str] = set()
                elif reading_restrictions:
                    permitted_forms = reading_restrictions
                else:
                    permitted_forms = set(forms)

                senses = eligible_senses(entry, reading_text, permitted_forms)
                if not senses:
                    continue

                applicable_forms = sorted(permitted_forms) or [reading]
                pos = sorted(
                    {
                        value
                        for sense in senses
                        for value in text_values(sense, "pos")
                    }
                )
                reading_common = bool(
                    COMMON_PRIORITIES & set(text_values(reading_element, "re_pri"))
                )
                form_common = any(
                    element.findtext("keb") in permitted_forms
                    and bool(COMMON_PRIORITIES & set(text_values(element, "ke_pri")))
                    for element in entry.findall("k_ele")
                )
                common = reading_common or form_common
                if common_only and not common:
                    continue
                connection.execute(
                    """
                    INSERT INTO words
                        (jmdict_id, reading, display_forms, start_kana, end_kana, pos, common)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(reading) DO UPDATE SET
                        jmdict_id = CASE
                            WHEN excluded.common > words.common
                            THEN excluded.jmdict_id ELSE words.jmdict_id END,
                        display_forms = CASE
                            WHEN excluded.common > words.common
                            THEN excluded.display_forms ELSE words.display_forms END,
                        pos = CASE
                            WHEN excluded.common > words.common
                            THEN excluded.pos ELSE words.pos END,
                        common = MAX(words.common, excluded.common)
                    """,
                    (
                        int(sequence_text),
                        reading,
                        json.dumps(applicable_forms, ensure_ascii=False),
                        initial_kana(reading),
                        terminal_kana(reading),
                        json.dumps(pos, ensure_ascii=False),
                        int(common),
                    ),
                )
            entry.clear()

    connection.commit()
    connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path, help="Pinned JMdict XML file")
    parser.add_argument("destination", type=Path, help="Output SQLite database")
    parser.add_argument(
        "--common-only",
        action="store_true",
        help="Keep only readings/forms carrying a JMdict priority marker",
    )
    arguments = parser.parse_args()
    build(arguments.source, arguments.destination, common_only=arguments.common_only)


if __name__ == "__main__":
    main()

