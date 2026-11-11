"""Exploratory retrieval/recognition ablations, not calibrated human models."""

from dataclasses import dataclass
import hashlib
import math
import random

from .bots import GameState
from .frequency_bot import FrequencyBot


def recognition_probability(age, *, recent=12, half_life=40.0, floor=0.2):
    """Age counts global played moves; recent observations are recognized exactly."""
    if age <= recent:
        return 1.0
    return floor + (1 - floor) * 2 ** (-(age - recent) / half_life)


@dataclass(frozen=True)
class CognitiveDecision:
    word: str | None
    attempts: tuple[dict, ...]
    stop_reason: str


class CognitiveBot:
    """Frequency retrieval WITHOUT a global used-word prefilter.

    Candidates are sampled without replacement within a turn. Across turns all
    known words return to the retrieval pool, including previously played words.
    Perfect-memory mode rejects every used candidate. Noisy mode queries latent
    last-seen traces with age-dependent recognition; forgotten repeats can escape.
    This is intentional limited recognition despite a visible full history, not
    a hidden-transcript experiment. Word legality and the n-rule remain perfect.
    """

    def __init__(self, vocabulary, frequencies, *, profile="combined", seed=0,
                 alpha=1.0, attempts=10, recent=12, half_life=40.0, floor=0.2):
        if profile not in {"recall", "memory", "combined"}:
            raise ValueError("Unknown cognitive profile")
        if not isinstance(attempts, int) or attempts < 1:
            raise ValueError("attempts must be a positive integer")
        if not isinstance(recent, int) or recent < 0:
            raise ValueError("recent must be a nonnegative integer")
        if not math.isfinite(half_life) or half_life <= 0:
            raise ValueError("half_life must be finite and positive")
        if not math.isfinite(floor) or not 0 <= floor <= 1:
            raise ValueError("floor must be in [0,1]")
        base = FrequencyBot(vocabulary, frequencies, seed=seed, alpha=alpha)
        self.vocabulary, self.frequencies = base.vocabulary, base.frequencies
        self.rng = base.rng
        memory_seed = int.from_bytes(hashlib.sha256(f"recognition:{seed}".encode()).digest()[:8], "big")
        self.memory_rng = random.Random(memory_seed)
        self.seed, self.alpha, self.profile = seed, alpha, profile
        self.attempt_limit = None if profile == "memory" else attempts
        self.imperfect_memory = profile != "recall"
        self.recent, self.half_life, self.floor = recent, half_life, floor
        self.name = {"recall": "RecallBot", "memory": "MemoryBot", "combined": "RecallMemoryBot"}[profile]

    def analyze(self, required_kana, history=()):
        # Deliberately empty used_words: retrieval is not an oracle unused list.
        remaining = list(self.vocabulary.safe_moves(GameState(required_kana)))
        limit = len(remaining) if self.attempt_limit is None else self.attempt_limit
        last_seen = {word: i for i, word in enumerate(history)}
        attempts = []
        while remaining and len(attempts) < limit:
            maximum = max(self.frequencies[w.reading] for w in remaining)
            weights = [(self.frequencies[w.reading] / maximum) ** self.alpha for w in remaining]
            draw, cumulative = self.rng.random() * math.fsum(weights), 0.0
            selected = len(remaining) - 1
            for i, weight in enumerate(weights):
                cumulative += weight
                if draw < cumulative:
                    selected = i
                    break
            word = remaining.pop(selected).reading
            age = len(history) - last_seen[word] if word in last_seen else None
            probability = (recognition_probability(age, recent=self.recent, half_life=self.half_life,
                            floor=self.floor) if self.imperfect_memory else 1.0) if age is not None else None
            recognized = age is not None and (probability == 1 or self.memory_rng.random() < probability)
            attempts.append({"word": word, "actual_age_moves": age,
                "recognition_probability": probability, "recognized_as_used": recognized})
            if not recognized:
                return CognitiveDecision(word, tuple(attempts), "submitted")
        reason = "known_pool_exhausted" if not remaining else "retrieval_budget_exhausted"
        return CognitiveDecision(None, tuple(attempts), reason)
