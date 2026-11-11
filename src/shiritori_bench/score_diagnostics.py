"""Offline checks of frozen-graph scores; not estimates of playing strength."""

from __future__ import annotations

import math

from .move_quality import multiply, rank_correlation


def sd(values):
    if not values:
        return 0.0
    mean = math.fsum(values) / len(values)
    return math.sqrt(math.fsum((x - mean) ** 2 for x in values) / len(values))


def depth_decomposition(position, gamma, *, horizons=(1, 2, 3, 4, 8, 16, 32, 64, 128)):
    """Compare finite sums to the exact infinite value, centering across starts."""
    indices = [i for i, count in enumerate(position.frequency_count) if count]
    exact = position.solutions[str(gamma)][0]
    term, cumulative = position.r[:], [0.0] * len(position.r)
    previous, rows = None, []
    immediate_sd = sd([position.r[i] for i in indices])
    for depth in range(1, max(horizons) + 1):
        increment = [-(-gamma) ** (depth - 1) * x for x in term]
        cumulative = [x + y for x, y in zip(cumulative, increment)]
        if depth in horizons:
            selected = [increment[i] for i in indices]
            remainder = [exact[i] - cumulative[i] for i in indices]
            denominator = sd(selected) + sd([previous[i] for i in indices]) if previous is not None else 0
            mean_increment = math.fsum(selected) / len(indices) if indices else 0
            mean_previous = math.fsum(previous[i] for i in indices) / len(indices) if previous is not None and indices else 0
            mean_denominator = abs(mean_increment) + abs(mean_previous)
            rows.append({
                "depth": depth,
                "reward_mean": math.fsum(term[i] for i in indices) / len(indices) if indices else None,
                "reward_sd": sd([term[i] for i in indices]),
                "increment_mean": mean_increment,
                "adjacent_pair_mean_ratio": abs(mean_increment + mean_previous) / mean_denominator
                    if previous is not None and mean_denominator else None,
                "increment_sd": sd(selected),
                "increment_sd_relative_to_immediate": sd(selected) / immediate_sd if immediate_sd else None,
                "adjacent_pair_sd_ratio": sd([increment[i] + previous[i] for i in indices]) / denominator
                    if denominator else None,
                "cumulative_vs_immediate_spearman": rank_correlation(
                    [cumulative[i] for i in indices], [-position.r[i] for i in indices]),
                "cumulative_vs_infinite_spearman": rank_correlation(
                    [cumulative[i] for i in indices], [exact[i] for i in indices]),
                "centered_remainder_sd": sd(remainder),
                "centered_remainder_relative_to_infinite_sd": sd(remainder) / sd([exact[i] for i in indices])
                    if sd([exact[i] for i in indices]) else None,
                "absolute_remainder_max": max((abs(x) for x in remainder), default=0),
            })
        previous = increment
        term = multiply(position.p, term)
    return rows


def mixing_diagnostics(probabilities, starts, *, depths=(0, 1, 2, 4, 8, 16, 32)):
    """Unconditional TV distances; an absorbing cemetery preserves missing mass.

    Never renormalize surviving walks: absorption is part of the process. Small
    distances can reflect common absorption, so survival is reported alongside.
    """
    size = len(probabilities)
    transitions = []
    for row in probabilities:
        total = math.fsum(row)
        if any(p < 0 for p in row) or total > 1 + 1e-10:
            raise ValueError("Expected substochastic transitions")
        transitions.append([(j, p) for j, p in enumerate(row) if p] +
                           ([(size, max(0.0, 1 - total))] if total < 1 else []))
    transitions.append([(size, 1.0)])
    walks = [[float(j == start) for j in range(size + 1)] for start in starts]
    result = []
    for depth in range(max(depths) + 1):
        if depth in depths:
            distances = [0.5 * math.fsum(abs(x - y) for x, y in zip(left, right))
                         for i, left in enumerate(walks) for right in walks[i + 1:]]
            survival = [math.fsum(row[:-1]) for row in walks]
            result.append({"depth": depth,
                           "max_pairwise_tv": max(distances, default=0),
                           "mean_pairwise_tv": math.fsum(distances) / len(distances) if distances else 0,
                           "mean_survival": math.fsum(survival) / len(survival) if survival else None,
                           "min_survival": min(survival, default=None)})
        if depth == max(depths):
            break
        updated = []
        for row in walks:
            next_row = [0.0] * (size + 1)
            for i, weight in enumerate(row):
                if weight:
                    for j, p in transitions[i]:
                        next_row[j] += weight * p
            updated.append(next_row)
        walks = updated
    return result


def coverage_rows(position):
    """Distinguish absent measurement, policy exclusion and threshold exclusion."""
    analyzer = position.analyzer
    result = []
    for i, kana in enumerate(analyzer.kana):
        if not position.safe_count[i]:
            continue
        counts = {"missing": 0, "ambiguous_excluded": 0, "below_threshold_or_zero": 0, "selected": 0}
        for word in position.safe[kana]:
            reading = word["reading"]
            if reading in analyzer.frequencies:
                key = "selected"
            elif analyzer.frequency_status[reading] == "missing":
                key = "missing"
            elif analyzer.frequency_status[reading] == "ambiguous" and analyzer.policy == "unambiguous":
                key = "ambiguous_excluded"
            else:
                key = "below_threshold_or_zero"
            counts[key] += 1
        incoming = sum(row[i] for row in position.count_edges)
        result.append({"kana": kana, "safe_dictionary_replies": position.safe_count[i],
                       "safe_incoming_words": incoming, "reachable_as_safe_ending": incoming > 0,
                       "frequency_mass": position.frequency_mass[i],
                       "unsupported": position.frequency_count[i] == 0, **counts})
    return result


def synthetic_index(analyzer, *, floor=None, uniform=False):
    """Deliberately artificial frequencies for sensitivity, NEVER empirical data.

    Retain selected measured values, replacing *every* excluded reading by the
    supplied per-reading floor. Uniform replaces every reading by 1 instead.
    """
    if not uniform and (floor is None or not math.isfinite(floor) or floor <= 0):
        raise ValueError("A finite positive synthetic floor is required")
    readings = {}
    for reading in analyzer.words:
        value = 1.0 if uniform else analyzer.frequencies.get(reading, floor)
        readings[reading] = {"tubelex": {"count": value, "count_upper": value,
            "per_million": value, "per_million_upper": value}}
    return {"source_id": "tubelex", "synthetic_sensitivity_only": True, "readings": readings}
