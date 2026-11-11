"""Seeded, limited-vocabulary frequency sampling. No strategic lookahead."""

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3

from .bots import GameState, VocabularyGraph, Word


def build_frequency_vocabulary(words, index, *, threshold=1.0, policy="unambiguous"):
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be finite and nonnegative")
    if policy not in {"unambiguous", "lower"}:
        raise ValueError("Unknown ambiguity policy")
    if index.get("source_id") != "tubelex":
        raise ValueError("Expected a TUBELEX frequency index")
    selected, frequencies, excluded = [], {}, Counter()
    for word in words:
        if word.immediately_loses:
            excluded["ends_in_n"] += 1
            continue
        entry = index.get("readings", {}).get(word.reading, {}).get("tubelex")
        if entry is None:
            excluded["unmatched"] += 1
            continue
        low, high = entry["per_million"], entry["per_million_upper"]
        if not all(math.isfinite(v) and v >= 0 for v in (low, high)) or high < low:
            raise ValueError(f"Invalid frequency for {word.reading}")
        if policy == "unambiguous" and entry["count"] != entry["count_upper"]:
            excluded["ambiguous"] += 1
            continue
        if low <= 0 or low < threshold:
            excluded["below_threshold_or_zero"] += 1
            continue
        selected.append(word)
        frequencies[word.reading] = float(low)
    return VocabularyGraph(selected), frequencies, dict(excluded)


def load_frequency_vocabulary(database, index_path, *, threshold=1.0, policy="unambiguous"):
    database, index_path = Path(database), Path(index_path)
    with database.open("rb") as source:
        database_hash = hashlib.file_digest(source, "sha256").hexdigest()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("vocabulary_sha256") != database_hash:
        raise ValueError("Frequency index and referee vocabulary hashes differ")
    with sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True) as connection:
        words = [Word(r[0], r[1], r[2], bool(r[3])) for r in connection.execute(
            "SELECT reading, start_kana, end_kana, common FROM words ORDER BY reading")]
        metadata = dict(connection.execute("SELECT key, value FROM metadata"))
    graph, frequencies, excluded = build_frequency_vocabulary(words, index, threshold=threshold, policy=policy)
    return graph, frequencies, {"vocabulary_sha256": database_hash,
        "frequency_sha256": hashlib.sha256(index_path.read_bytes()).hexdigest(),
        "dictionary_metadata": metadata, "eligible_dictionary_readings": len(words),
        "selected_safe_readings": len(frequencies), "excluded": excluded,
        "threshold_per_million": threshold, "ambiguity_policy": policy}


@dataclass(frozen=True)
class FrequencyDecision:
    word: str | None
    candidate_count: int
    selected_probability: float | None
    candidate_mass_per_million: float


class FrequencyBot:
    """Choose safe unused words with p(w|state) proportional to frequency**alpha.

    Own local RNG, stable sorted candidates, fixed measured vocabulary. A pass
    means this bot's pool is exhausted, NOT that the full referee has no move.
    Reproduce by constructing a fresh bot with the same seed and replaying the
    same ordered states. No global random state is touched.
    """

    def __init__(self, vocabulary, frequencies, *, seed=0, alpha=1.0):
        if not isinstance(seed, int):
            raise ValueError("seed must be an integer")
        if not math.isfinite(alpha) or alpha < 0:
            raise ValueError("alpha must be finite and nonnegative")
        if any(not math.isfinite(v) or v <= 0 for v in frequencies.values()):
            raise ValueError("Selected frequencies must be finite and positive")
        selected = [vocabulary.word(reading) for reading in sorted(frequencies)
                    if not vocabulary.word(reading).immediately_loses]
        self.vocabulary = VocabularyGraph(selected)
        self.frequencies = {word.reading: float(frequencies[word.reading]) for word in selected}
        self.seed, self.alpha = seed, alpha
        self.rng = random.Random(seed)
        self.name = f"FrequencyBot(alpha={alpha:g}, seed={seed})"

    def analyze(self, state: GameState) -> FrequencyDecision:
        candidates = self.vocabulary.safe_moves(state)
        if not candidates:
            return FrequencyDecision(None, 0, None, 0.0)
        # Scaling by the largest *current* frequency avoids overflow, while
        # retaining exactly the same mathematical conditional distribution.
        maximum = max(self.frequencies[word.reading] for word in candidates)
        weights = [(self.frequencies[word.reading] / maximum) ** self.alpha for word in candidates]
        total = math.fsum(weights)
        draw, cumulative = self.rng.random() * total, 0.0
        selected = len(candidates) - 1
        for i, weight in enumerate(weights):
            cumulative += weight
            if draw < cumulative:
                selected = i
                break
        return FrequencyDecision(candidates[selected].reading, len(candidates), weights[selected] / total,
            math.fsum(self.frequencies[word.reading] for word in candidates))

    def choose(self, state: GameState) -> str | None:
        return self.analyze(state).word
