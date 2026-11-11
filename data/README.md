# Vocabulary data

The source snapshot is the English JMdict XML distribution downloaded from
EDRDG. `SOURCE.json` pins its URL, download date, checksum, and filter version.

Generated files:

- `raw/JMdict_e.gz` — pinned compressed source snapshot.
- `processed/bot-vocabulary.sqlite` — priority-marked vocabulary available to bots.
- `processed/referee-vocabulary.sqlite` — full eligible-noun validation vocabulary.

The generated databases are ignored by Git because they can be reproduced:

```text
python3 scripts/build_vocabulary.py \
  data/raw/JMdict_e.gz \
  data/processed/bot-vocabulary.sqlite \
  --common-only
```

Build the referee database without `--common-only`.

The referee vocabulary accepts readings with an applicable common,
adverbial, temporal, or independent `する`-noun sense. It excludes proper
nouns, names, places, organizations, abbreviations, obsolete or archaic
entries, prefixes, suffix-only senses, and counters. A sense tagged both as
an allowed standalone noun and as usable as a suffix remains eligible under
the current noun-v3 policy. Sense restrictions (`stagr` and
`stagk`) are respected. Readings are normalized to hiragana and deduplicated.

The bot edition additionally requires a primary JMdict priority marker on the
reading or one of its applicable written forms. Bots search only that smaller
edition; model responses are validated against the full referee edition. Both
lists can be rebuilt from the pinned source, but are not supplied to models
during games. GreedyBot and SearchBot use the priority-marked bot edition;
FrequencyBot and MemoryBot instead use a frequency-filtered pool derived from
the referee edition and TUBELEX. Run `scripts/build_glosses.py` and
`scripts/build_tubelex_frequency.py --download` after rebuilding the dictionaries
to generate the local English glossary and frequency index. These generated
files and raw corpora are not included in the public repository.
