# Adversarial Shiritori Benchmark

## Purpose

This benchmark evaluates language models through competitive Japanese Shiritori. It is a closed-book, text-only evaluation: models do not receive the vocabulary, cannot call tools, and must select words from their internal Japanese-language knowledge.

The benchmark measures:

- Japanese lexical knowledge
- Rule following
- Strategic planning
- Recall of previously played words
- Persistence across a multi-turn game
- Efficiency in tokens, latency, and cost

## Core Game

Two players alternate Japanese words. Each word must begin with the final kana of the previous word. A word may not be repeated. Playing a word ending in `ん`, making an invalid move, or failing to produce a legal move results in a loss.

The objective is to win, not to maximize the length of the game.

## Canonical Model Prompt

```text
You are playing competitive Japanese Shiritori.

Reply with exactly one Japanese noun written in hiragana and nothing else.

Rules:

1. Your word must begin with the required kana.
2. Your word must be present in the benchmark's fixed JMdict-derived vocabulary.
3. Your word must not have appeared previously in the match.
4. A word ending in ん loses immediately.
5. Proper nouns, personal names, place names, organization names,
   abbreviations, prefixes, suffixes, counters, particles, archaic words,
   obsolete words, and inflected forms are prohibited.
6. Katakana loanwords are allowed, but they must be written in hiragana.
7. Words containing spaces, punctuation, symbols, or numbers are prohibited.
8. Small final kana are normalized as follows:
   ゃ→や, ゅ→ゆ, ょ→よ,
   ぁ→あ, ぃ→い, ぅ→う, ぇ→え, ぉ→お, っ→つ.
9. Voiced, unvoiced, and semi-voiced kana remain distinct.
   For example, は, ば, and ぱ do not match one another.
10. Words ending in the long-vowel mark ー are prohibited.
11. Different words with the same normalized reading are treated as the same word.
12. If you cannot produce a legal word, output PASS.
13. Do not include explanations, punctuation, numbering, translations, or
    multiple candidates.

Your objective is to win strategically, not merely to prolong the game.

Vocabulary authority: {VOCABULARY_VERSION}
Required kana: {REQUIRED_KANA}
Previously used words: {USED_WORDS}
```

Example valid response:

```text
らくだ
```

## Vocabulary Policy

The authoritative vocabulary is a pinned, versioned snapshot derived from JMdict. JMdict is disclosed to models as the source of the referee vocabulary, but the complete accepted-word list is not included in prompts.

An entry is eligible when it:

- Has a kana reading
- Has at least one eligible noun-like sense
- Is not a proper noun, person, place, or organization name
- Is not solely a prefix, suffix, counter, particle, or abbreviation
- Is not marked archaic or obsolete
- Contains only Japanese kana after normalization
- Does not contain spaces, punctuation, symbols, or numbers

Loanwords are eligible when they otherwise satisfy the policy. Words ending in `ん` remain in the vocabulary because they are legal losing moves.

The normalized hiragana reading is the identity of a word. Homophones therefore share one game identity. Once `はし` is used, it cannot be played again under a different written meaning.

"Closed book" means that the vocabulary is absent from the model prompt and external retrieval is forbidden. The vocabulary itself should be public and reproducible.

## Vocabulary Versioning

Every evaluation must record:

```text
vocabulary_version: jmdict-YYYY-MM-DD
source_sha256: <checksum>
normalization_version: 1
filter_version: 1
override_version: 1
```

Do not silently update the vocabulary during a leaderboard period. A new JMdict snapshot or rule change creates a new benchmark vocabulary version.

Publish:

- The source snapshot date and checksum
- The import and filtering scripts
- The final accepted-word list
- Excluded entries and exclusion reasons
- Manual overrides and their justifications

## Manual Overrides

Maintain small, reviewed override files:

```text
overrides/allow.txt
overrides/deny.txt
```

Overrides should be exceptional and documented. They must not become an undocumented second dictionary.

## Suggested SQLite Schema

```sql
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

CREATE INDEX words_by_start
ON words(start_kana);

CREATE INDEX words_by_transition
ON words(start_kana, end_kana);
```

The referee should validate model output against the normalized `reading` field.

## Match Protocol

- Run each model pairing in both player orders.
- Use multiple starting words or starting kana.
- Repeat each condition to measure variance.
- Give every model the same system prompt and state format.
- Use identical decoding settings where the APIs permit it.
- Set a maximum turn count for operational safety.
- Treat malformed output as an invalid move.
- Preserve the complete transcript and referee decision log.

If a maximum-turn game remains unresolved, mark it as a draw rather than using chain length as the winner.

## Referee Outcomes

Each turn should receive exactly one outcome code:

```text
VALID
INVALID_WORD
WRONG_START
REPEATED_WORD
ENDS_IN_N
MALFORMED_OUTPUT
PASS_WITH_LEGAL_MOVE
PASS_NO_LEGAL_MOVE
```

The log should include the submitted text, normalized reading, required kana, matching JMdict entry when present, and vocabulary version.

## Scoring

Primary score:

- Win: 1 point
- Draw: 0.5 points
- Loss: 0 points

Diagnostic metrics:

- Win rate
- First-player and second-player win rates
- Legal-move rate
- Invalid-word rate
- Wrong-start rate
- Repetition rate
- `ん`-loss rate
- Unsupported `PASS` rate
- Mean match length
- Tokens per move
- Cost per match
- Latency per move

Match length should not be the primary score: a strategically strong player may force a quick victory.

## Evaluation Tracks

### Closed-Book Arena

Models play complete matches without vocabulary access. This is the primary public game and measures vocabulary together with strategy.

### Solved Positions

Models answer independent positions whose winning status has been computed in advance. This reduces error propagation and context-window effects, and provides a cleaner strategic score.

### Endurance Track

Long matches intentionally test recall and context management. Results should be separated by context limit so context size does not silently dominate the main leaderboard.

## Open Questions

- Exact JMdict part-of-speech whitelist
- Treatment of rare but untagged entries
- Whether `PASS` with no legal dictionary move is a draw or a loss
- Match turn limit
- Starting-position selection
- Whether the opponent is another model or a deterministic search engine
- How to handle provider-specific token and sampling controls
