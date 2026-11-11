"""State-aware structural and discounted move scores (not win probabilities).

Known words and the proposed move are removed exactly. The discounted
continuation freezes that resulting graph: future words can recur in this
approximation. Frequency-weighted transitions describe a fixed policy, not
minimax play. No model or referee policy is modified by these diagnostics.
"""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

from .normalize import normalize_reading


def inverse(matrix: list[list[float]]) -> list[list[float]]:
    """Small dense inverse with partial pivoting; no numerical dependencies."""
    size = len(matrix)
    augmented = [row[:] + [float(i == j) for j in range(size)] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-14:
            raise ValueError("Singular discounted system")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        row = augmented[column]
        divisor = row[column]
        augmented[column] = row = [value / divisor for value in row]
        for i in range(size):
            if i == column:
                continue
            factor = augmented[i][column]
            if factor:
                augmented[i] = [a - factor * b for a, b in zip(augmented[i], row)]
    return [row[size:] for row in augmented]


def multiply(matrix: list[list[float]], vector: list[float]) -> list[float]:
    return [math.fsum(a * b for a, b in zip(row, vector)) for row in matrix]


def discounted_values(probabilities: list[list[float]], reward: list[float], gamma: float):
    """Solve Q = -r - gamma P Q; empty rows terminate continuation."""
    if not math.isfinite(gamma) or not 0 <= gamma < 1:
        raise ValueError("Discount must satisfy 0 <= gamma < 1")
    system = [[float(i == j) + gamma * p for j, p in enumerate(row)]
              for i, row in enumerate(probabilities)]
    inv = inverse(system)
    values = [-value for value in multiply(inv, reward)]
    residual = max((abs(values[i] + reward[i] + gamma * math.fsum(p * q for p, q in zip(row, values)))
                    for i, row in enumerate(probabilities)), default=0)
    if residual > 1e-8:
        raise ArithmeticError(f"Discounted solver residual too large: {residual}")
    return values, inv, residual


class MoveAnalyzer:
    def __init__(self, rows: list[dict[str, Any]], index: dict[str, Any], *,
                 threshold: float = 1, alpha: float = 1,
                 policy: str = "unambiguous", gammas=(0.5, 0.85, 0.95),
                 transform: str = "log", mass_scale: float = 1):
        if index.get("source_id") != "tubelex":
            raise ValueError("A TUBELEX index is required")
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("Threshold must be finite and nonnegative")
        if not math.isfinite(alpha) or alpha <= 0:
            raise ValueError("alpha must be finite and positive")
        if policy not in {"unambiguous", "lower"} or transform not in {"log", "linear"}:
            raise ValueError("Invalid frequency policy or reward transform")
        if not math.isfinite(mass_scale) or mass_scale <= 0:
            raise ValueError("mass_scale must be finite and positive")
        self.gammas = tuple(sorted(set(gammas)))
        if not self.gammas or any(not math.isfinite(g) or not 0 <= g < 1 for g in self.gammas):
            raise ValueError("Discounts must satisfy 0 <= gamma < 1")
        self.threshold, self.alpha, self.policy = threshold, alpha, policy
        self.transform, self.mass_scale = transform, mass_scale
        self.words = {row["reading"]: dict(row) for row in rows}
        self.kana = sorted({k for row in rows for k in (row["start_kana"], row["end_kana"])})
        self.positions = {k: i for i, k in enumerate(self.kana)}
        self.frequencies = {}
        self.raw_frequencies = {}
        self.frequency_status = {}
        for reading in self.words:
            frequency = index.get("readings", {}).get(reading, {}).get("tubelex")
            if frequency is None:
                self.frequency_status[reading] = "missing"
                continue
            low, high = frequency["per_million"], frequency["per_million_upper"]
            self.raw_frequencies[reading] = {"lower": low, "upper": high}
            if not all(math.isfinite(f) and f >= 0 for f in (low, high)) or high < low:
                raise ValueError(f"Invalid frequency for {reading}")
            ambiguous = frequency["count"] != frequency["count_upper"]
            self.frequency_status[reading] = "ambiguous" if ambiguous else "unambiguous"
            if low > 0 and low >= threshold and (not ambiguous or policy == "lower"):
                self.frequencies[reading] = low
        maximum = max(self.frequencies.values(), default=1)
        self.weights = {word: (frequency / maximum) ** alpha for word, frequency in self.frequencies.items()}

    def reward(self, mass):
        mass = max(0.0, mass) / self.mass_scale
        return math.log1p(mass) if self.transform == "log" else mass

    def snapshot(self, used=()):
        return Position(self, frozenset(normalize_reading(w) for w in used))


class Position:
    def __init__(self, analyzer: MoveAnalyzer, used: frozenset[str]):
        self.analyzer, self.used = analyzer, used
        n = len(analyzer.kana)
        self.safe = defaultdict(list)
        self.all_count = [0] * n
        self.safe_count = [0] * n
        self.count_edges = [[0] * n for _ in range(n)]
        self.frequency_count = [0] * n
        self.frequency_mass = [0.0] * n
        self.fatal_frequency_count = [0] * n
        self.fatal_frequency_mass = [0.0] * n
        self.weight_edges = [[0.0] * n for _ in range(n)]
        self.mass_edges = [[0.0] * n for _ in range(n)]
        self.pool = defaultdict(list)
        self.uncovered_count = [0] * n
        self.ambiguous_count = [0] * n
        for reading, word in analyzer.words.items():
            if reading in used:
                continue
            i, j = analyzer.positions[word["start_kana"]], analyzer.positions[word["end_kana"]]
            self.all_count[i] += 1
            frequency = analyzer.frequencies.get(reading)
            if word["end_kana"] == "ん":
                if frequency is not None:
                    self.fatal_frequency_count[i] += 1
                    self.fatal_frequency_mass[i] += frequency
                continue
            self.safe[word["start_kana"]].append(word)
            self.safe_count[i] += 1
            self.count_edges[i][j] += 1
            status = analyzer.frequency_status[reading]
            self.uncovered_count[i] += int(status == "missing")
            self.ambiguous_count[i] += int(status == "ambiguous")
            if frequency is not None:
                self.pool[word["start_kana"]].append(word)
                self.frequency_count[i] += 1
                self.frequency_mass[i] += frequency
                self.mass_edges[i][j] += frequency
                self.weight_edges[i][j] += analyzer.weights[reading]
        self.weight_sums = [math.fsum(row) for row in self.weight_edges]
        self.p = [[weight / total if total else 0 for weight in row]
                  for row, total in zip(self.weight_edges, self.weight_sums)]
        self.r = [analyzer.reward(mass) for mass in self.frequency_mass]
        self.solutions = {str(g): discounted_values(self.p, self.r, g) for g in analyzer.gammas}

    def kana_measures(self, kana):
        a = self.analyzer
        if kana not in a.positions:
            return None
        i = a.positions[kana]
        weights = [a.weights[w["reading"]] for w in self.pool[kana]]
        total = math.fsum(weights)
        probabilities = sorted((w / total for w in weights), reverse=True) if total else []
        entropy = -math.fsum(p * math.log2(p) for p in probabilities if p)
        incoming = sum(row[i] for row in self.count_edges)
        incoming_mass = math.fsum(row[i] for row in self.mass_edges)
        baseline_incoming = sum(w["end_kana"] == kana for words in self.pool.values() for w in words)
        baseline_starts = {w["start_kana"] for words in self.pool.values() for w in words if w["end_kana"] == kana}
        fatal = self.all_count[i] - self.safe_count[i]
        total_frequency = self.frequency_mass[i] + self.fatal_frequency_mass[i]
        return {
            "kana": kana, "dictionary_words": self.all_count[i], "safe_replies": self.safe_count[i],
            "covered_safe_replies": self.frequency_count[i], "frequency_mass_per_million": self.frequency_mass[i],
            "missing_frequency_safe_words": self.uncovered_count[i], "ambiguous_frequency_safe_words": self.ambiguous_count[i],
            "baseline_coverage_of_safe_replies": self.frequency_count[i] / self.safe_count[i] if self.safe_count[i] else None,
            "unsupported_by_frequency_model": self.safe_count[i] > 0 and self.frequency_count[i] == 0,
            "entropy_bits": entropy if probabilities else None,
            "effective_replies_entropy": 2 ** entropy if probabilities else 0,
            "effective_replies_simpson": 1 / math.fsum(p * p for p in probabilities) if probabilities else 0,
            "top1_probability": probabilities[0] if probabilities else None,
            "top5_probability": math.fsum(probabilities[:5]) if probabilities else None,
            "incoming_safe_words": incoming,
            "incoming_frequency_mass": incoming_mass,
            "attack_sustainability_count_ratio": incoming / self.safe_count[i] if self.safe_count[i] else None,
            "incoming_exceeds_outgoing": incoming > self.safe_count[i],
            "attack_accessibility": sum(row[i] > 0 for row in self.count_edges),
            "two_kana_attack_accessibility": len({w["start_kana"] for w in a.words.values()
                if w["reading"] not in self.used and w["end_kana"] == kana and len(w["reading"]) == 2}),
            "covered_attack_accessibility": len(baseline_starts),
            "covered_attack_sustainability_count_ratio": baseline_incoming / self.frequency_count[i] if self.frequency_count[i] else None,
            "attack_sustainability_mass_ratio": incoming_mass / self.frequency_mass[i] if self.frequency_mass[i] else None,
            "self_return_count": self.count_edges[i][i],
            "self_return_count_share": self.count_edges[i][i] / self.safe_count[i] if self.safe_count[i] else None,
            "self_return_probability": self.p[i][i] if total else None,
            "n_trap_count": fatal,
            "n_trap_count_share": fatal / self.all_count[i] if self.all_count[i] else None,
            "n_trap_frequency_share": self.fatal_frequency_mass[i] / total_frequency if total_frequency else None,
            "ending_probabilities": {a.kana[j]: p for j, p in enumerate(self.p[i]) if p},
            "immediate_pressure": -self.r[i],
            "discounted_values": {g: solution[0][i] for g, solution in self.solutions.items()},
        }

    def candidate_values(self, word):
        """Exact rank-one update for removing this candidate from the frozen graph."""
        a = self.analyzer
        i, j = a.positions[word["start_kana"]], a.positions[word["end_kana"]]
        frequency = a.frequencies.get(word["reading"], 0)
        if not frequency:
            return {g: solution[0][j] for g, solution in self.solutions.items()}
        remaining_count = self.frequency_count[i] - 1
        new_sum = self.weight_sums[i] - a.weights[word["reading"]]
        new_row = [(weight - (a.weights[word["reading"]] if k == j else 0)) / new_sum
                   if remaining_count > 0 else 0 for k, weight in enumerate(self.weight_edges[i])]
        delta_p = [new - old for new, old in zip(new_row, self.p[i])]
        delta_reward = a.reward(self.frequency_mass[i] - frequency) - self.r[i]
        result = {}
        for gamma, (values, inv, _) in self.solutions.items():
            g = float(gamma)
            numerator = delta_reward + g * math.fsum(p * value for p, value in zip(delta_p, values))
            denominator = 1 + g * math.fsum(p * inv[k][i] for k, p in enumerate(delta_p))
            if abs(denominator) < 1e-12:
                raise ArithmeticError("Unstable candidate update")
            result[gamma] = values[j] - inv[j][i] * numerator / denominator
        return result

    def score_move(self, submitted, required, *, horizons=(1, 2, 4, 8)):
        a = self.analyzer
        reading = normalize_reading(submitted)
        result = {"submitted": submitted, "normalized": reading,
                  "required_kana": required, "used_word_count": len(self.used)}
        # Match referee precedence; PASS is reported separately.
        if submitted.strip() == "PASS":
            legality = "PASS_WITH_SAFE_MOVE" if self.safe[required] else "PASS_NO_SAFE_MOVE"
        else:
            from .normalize import is_hiragana_word
            if not is_hiragana_word(submitted.strip()):
                legality = "MALFORMED_OUTPUT"
            elif not reading.startswith(required):
                legality = "WRONG_START"
            elif reading in self.used:
                legality = "REPEATED_WORD"
            elif reading not in a.words:
                legality = "INVALID_WORD"
            elif a.words[reading]["end_kana"] == "ん":
                legality = "ENDS_IN_N"
            else:
                legality = "VALID"
        result["legality"] = legality
        result["safe_legal"] = legality == "VALID"
        result["word_frequency_status"] = a.frequency_status.get(reading, "missing")
        result["word_frequency_per_million"] = a.raw_frequencies.get(reading)
        result["word_in_frequency_pool"] = reading in a.frequencies
        if legality != "VALID":
            result["strategy"] = None
            return result
        chosen = a.words[reading]
        after = a.snapshot(self.used | {reading})
        destination = chosen["end_kana"]
        j = a.positions[destination]
        result["strategy"] = after.kana_measures(destination)
        # Literal two-ply reply analysis removes the opponent word as well.
        reply_weights = [(word, a.weights[word["reading"]]) for word in after.pool[destination]]
        total = math.fsum(weight for _, weight in reply_weights)
        own_count, own_mass, own_r, zero = [], [], [], []
        worst_full, worst_covered = [], []
        for reply, weight in reply_weights:
            k = a.positions[reply["end_kana"]]
            self_loop = int(reply["start_kana"] == reply["end_kana"])
            count = after.frequency_count[k] - self_loop
            mass = max(0, after.frequency_mass[k] - (a.frequencies[reply["reading"]] if self_loop else 0))
            p = weight / total
            own_count.append(p * count)
            own_mass.append(p * mass)
            own_r.append(p * a.reward(mass))
            zero.append(p * (count == 0))
            worst_covered.append(count)
        for reply in after.safe[destination]:
            k = a.positions[reply["end_kana"]]
            worst_full.append(after.safe_count[k] - int(reply["start_kana"] == reply["end_kana"]))
        result["two_ply"] = {
            "expected_own_covered_replies": math.fsum(own_count) if total else None,
            "expected_own_frequency_mass": math.fsum(own_mass) if total else None,
            "probability_own_covered_pool_empty": math.fsum(zero) if total else None,
            "worst_own_dictionary_replies": min(worst_full, default=None),
            "worst_own_covered_replies": min(worst_covered, default=None),
            "depletion_aware_two_ply_values": {str(g): -after.r[j] + g * math.fsum(own_r)
                                               if total else -after.r[j] for g in a.gammas},
        }
        result["lookahead"] = {}
        for gamma, (values, _, residual) in after.solutions.items():
            term = after.r[:]
            value = [0.0] * len(term)
            finite = {}
            for step in range(1, max(horizons) + 1):
                coefficient = -(-float(gamma)) ** (step - 1)
                value = [v + coefficient * r for v, r in zip(value, term)]
                if step in horizons:
                    finite[str(step)] = value[j]
                term = multiply(after.p, term)
            result["lookahead"][gamma] = {"infinite": values[j], "finite_horizons": finite,
                                           "bellman_residual": residual}
        # Compare against ALL safe dictionary choices, not only frequency-covered words.
        scores = [(word["reading"], self.candidate_values(word)) for word in self.safe[required]]
        result["alternatives"] = {}
        for gamma in after.solutions:
            selected = result["lookahead"][gamma]["infinite"]
            values = [value[gamma] for _, value in scores]
            better = sum(v > selected + 1e-9 for v in values)
            tied = sum(abs(v - selected) <= 1e-9 for v in values)
            # Midrank percentile including chosen move; all tied -> 50.
            percentile = 100 * (sum(v < selected - 1e-9 for v in values) + 0.5 * tied) / len(values)
            top = sorted(scores, key=lambda item: (-item[1][gamma], item[0]))[:5]
            result["alternatives"][gamma] = {"safe_choices": len(scores), "strictly_better": better,
                "tied_choices": tied, "midrank_percentile": percentile,
                "best_score": max(values), "regret_under_heuristic": max(0.0, max(values) - selected),
                "top_choices": [{"word": word, "score": value[gamma],
                                 "ending": a.words[word]["end_kana"],
                                 "destination_covered_replies": self.frequency_count[a.positions[a.words[word]["end_kana"]]]
                                     - int(a.words[word]["start_kana"] == a.words[word]["end_kana"] and word in a.frequencies)}
                                for word, value in top]}
        return result


def rank_correlation(left, right):
    """Spearman correlation with average ranks for ties; undefined -> None."""
    def ranks(values):
        ordered = sorted(range(len(values)), key=lambda i: values[i])
        result = [0.0] * len(values)
        start = 0
        while start < len(ordered):
            end = start + 1
            while end < len(ordered) and values[ordered[end]] == values[ordered[start]]:
                end += 1
            for i in ordered[start:end]:
                result[i] = (start + end - 1) / 2
            start = end
        return result
    if len(left) < 2 or len(left) != len(right):
        return None
    x, y = ranks(left), ranks(right)
    mx, my = math.fsum(x) / len(x), math.fsum(y) / len(y)
    denominator = math.sqrt(math.fsum((v - mx) ** 2 for v in x) * math.fsum((v - my) ** 2 for v in y))
    return math.fsum((a - mx) * (b - my) for a, b in zip(x, y)) / denominator if denominator else None
