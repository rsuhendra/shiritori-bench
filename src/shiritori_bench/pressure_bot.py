"""Perfect-recall strategic probes, not models of human play."""
from collections import defaultdict
import math

from .bots import GameState
from .players import PlayerResponse


class PressureBot:
    kind = "algorithmic"

    def __init__(self, graph, frequencies, *, policy="two_ply", gamma=0.85):
        if policy not in {"immediate", "two_ply"}:
            raise ValueError("Unknown pressure policy")
        if not 0 <= gamma <= 1:
            raise ValueError("gamma must be in [0,1]")
        self.graph, self.frequencies = graph, frequencies
        self.starts = sorted({graph.word(w).start_kana for w in frequencies})
        self.policy, self.gamma = policy, gamma
        self.name = f"PressureBot({policy})"

    def scores(self, state):
        rows = {k: self.graph.safe_moves(GameState(k, state.used_words))
                for k in self.starts}
        mass = {k: math.fsum(self.frequencies[w.reading] for w in row)
                for k, row in rows.items()}
        edges = defaultdict(float)
        expected = {}
        for k, row in rows.items():
            total = 0.0
            for reply in row:
                f = self.frequencies[reply.reading]
                edges[k, reply.end_kana] += f
                own_mass = mass.get(reply.end_kana, 0) - (f if reply.end_kana == k else 0)
                total += f * math.log1p(max(0, own_mass))
            expected[k] = total / mass[k] if mass[k] else 0.0
        a = state.required_kana
        values = {}
        for word in rows.get(a, ()):
            b, f = word.end_kana, self.frequencies[word.reading]
            opponent_mass = max(0, mass.get(b, 0) - (f if a == b else 0))
            # Exhausting the opponent's entire baseline pool outranks any heuristic.
            if not opponent_mass:
                values[word.reading] = float("inf")
                continue
            reward = -math.log1p(opponent_mass)
            if self.policy == "two_ply":
                if a != b:
                    continuation = expected[b] + edges[b, a] / opponent_mass * (
                        math.log1p(max(0, mass[a] - f)) - math.log1p(mass[a]))
                else:
                    continuation = math.fsum(
                        self.frequencies[r.reading] * math.log1p(max(0,
                            mass.get(r.end_kana, 0) - (f if r.end_kana == a else 0)
                            - (self.frequencies[r.reading] if r.end_kana == b else 0)))
                        for r in rows[b] if r.reading != word.reading) / opponent_mass
                reward += self.gamma * continuation
            values[word.reading] = reward
        return values

    def play(self, context):
        scores = self.scores(GameState(context.required_kana, context.used_words))
        word = min(scores, key=lambda w: (-scores[w], -self.frequencies[w], w)) if scores else "PASS"
        score = scores.get(word)
        return PlayerResponse(word, {"policy": self.policy, "gamma": self.gamma,
            "score": score if score is not None and math.isfinite(score) else None,
            "pool_exhausting_move": score == float("inf")})
