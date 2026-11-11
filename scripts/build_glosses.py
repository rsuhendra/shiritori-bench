#!/usr/bin/env python3
"""Extract English noun glosses without changing the pinned referee database."""

import json
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

from build_vocabulary import PROJECT_ROOT, COMMON_PRIORITIES, eligible_senses, open_source, text_values
from shiritori_bench.normalize import normalize_reading


def main():
    database = PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite"
    with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
        rows = connection.execute("SELECT jmdict_id, reading, display_forms FROM words").fetchall()
    wanted = {reading for _, reading, _ in rows}
    glossary = {}
    with open_source(PROJECT_ROOT / "data/raw/JMdict_e.gz") as source:
        for _, entry in ET.iterparse(source, events=("end",)):
            if entry.tag != "entry":
                continue
            entry_forms = set(text_values(entry, "k_ele/keb"))
            for reading_node in entry.findall("r_ele"):
                original = reading_node.findtext("reb", "")
                reading = normalize_reading(original)
                if reading not in wanted:
                    continue
                restrictions = set(text_values(reading_node, "re_restr"))
                forms = set() if reading_node.find("re_nokanji") is not None else restrictions or entry_forms
                glosses = []
                for sense in eligible_senses(entry, original, forms):
                    for gloss in sense.findall("gloss"):
                        if gloss.get("{http://www.w3.org/XML/1998/namespace}lang", "eng") == "eng" and gloss.text:
                            if gloss.text not in glosses:
                                glosses.append(gloss.text)
                if glosses:
                    common = bool(COMMON_PRIORITIES & set(text_values(reading_node, "re_pri"))) or any(
                        node.findtext("keb") in forms and COMMON_PRIORITIES & set(text_values(node, "ke_pri"))
                        for node in entry.findall("k_ele"))
                    label = "/".join(sorted(forms)[:2])
                    meaning = (label + ": " if label else "") + "; ".join(glosses[:3])
                    glossary.setdefault(reading, []).append((not common, meaning))
            entry.clear()
    glossary = {reading: list(dict.fromkeys(meaning for _, meaning in sorted(meanings)))
                for reading, meanings in glossary.items()}
    destination = PROJECT_ROOT / "data/processed/english-glosses.json"
    destination.write_text(json.dumps(glossary, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    print(f"Saved English glosses for {len(glossary):,} readings: {destination}")


if __name__ == "__main__":
    main()
