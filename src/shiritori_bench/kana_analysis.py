"""Explore initial-kana vocabularies and frequency-weighted move distributions."""

from __future__ import annotations

from collections import defaultdict
import math
from typing import Any

STANDARD_KANA = list("あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽゔ")


def distribution(words: list[dict[str, Any]], threshold: float, alpha: float) -> dict[str, Any]:
    """Conditional distribution after filtering; words must already be safe."""
    candidates = [w for w in words if w["selected_frequency"] is not None
                  and w["selected_frequency"] > 0 and w["selected_frequency"] >= threshold]
    candidates.sort(key=lambda w: (-w["selected_frequency"], w["reading"]))
    frequencies = [w["selected_frequency"] for w in candidates]
    mass = math.fsum(frequencies)
    # Rescale by maximum to avoid overflow for large exponents.
    weights = [(f / frequencies[0]) ** alpha for f in frequencies] if frequencies else []
    weight_sum = math.fsum(weights)
    probabilities = [w / weight_sum for w in weights]
    cumulative, running = [], 0.0
    for probability in probabilities:
        running += probability
        cumulative.append(min(1.0, running))
    if cumulative:
        cumulative[-1] = 1.0
    entropy = -math.fsum(p * math.log2(p) for p in probabilities if p)
    n_for_mass = {str(q): next((i + 1 for i, p in enumerate(cumulative) if p + 1e-12 >= q), None)
                  for q in (0.5, 0.9, 0.95, 0.99)}
    top_mass = {str(n): math.fsum(probabilities[:n]) if candidates else None for n in (1, 5, 10, 20, 50, 100)}
    # ECDF answers "what fraction of words have frequency <= x?";
    # mass CDF answers "what fraction of draws go to those words?".
    frequency_cdf = [
        {"frequency_per_million_at_most": cutoff,
         "word_fraction": sum(f <= cutoff for f in frequencies) / len(frequencies) if frequencies else None,
         "sampling_mass": math.fsum(p for f, p in zip(frequencies, probabilities) if f <= cutoff) if frequencies else None}
        for cutoff in (0.01, 0.1, 1, 10, 100, 1000)
    ]
    endings: dict[str, float] = defaultdict(float)
    for word, probability in zip(candidates, probabilities):
        endings[word["end_kana"]] += probability
    return {
        "threshold": threshold, "eligible_words": len(candidates),
        "frequency_mass_per_million": mass, "corpus_token_mass": mass / 1_000_000,
        "entropy_bits": entropy if candidates else None,
        "effective_words_entropy": 2 ** entropy if candidates else 0,
        "effective_words_simpson": 1 / math.fsum(p * p for p in probabilities) if candidates else 0,
        "top_probability_mass": top_mass, "words_for_probability_mass": n_for_mass,
        "frequency_cdf": frequency_cdf, "ending_probabilities": dict(sorted(endings.items())),
        "ranked": [(word, probability, cumulative[i]) for i, (word, probability) in enumerate(zip(candidates, probabilities))],
    }


def analyze(rows: list[dict[str, Any]], index: dict[str, Any], *,
            thresholds: list[float], alpha: float = 1,
            policy: str = "unambiguous", top: int = 10) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if index.get("source_id") != "tubelex":
        raise ValueError("This analysis currently requires the TUBELEX index")
    if not math.isfinite(alpha) or alpha <= 0:
        raise ValueError("alpha must be finite and positive")
    if policy not in {"unambiguous", "lower"}:
        raise ValueError("Unknown frequency policy")
    if not thresholds or any(not math.isfinite(t) or t < 0 for t in thresholds):
        raise ValueError("Thresholds must be finite and nonnegative")
    if top < 1:
        raise ValueError("top must be positive")
    thresholds = sorted(set([0.0, *thresholds]))
    grouped = defaultdict(list)
    for row in rows:
        word = dict(row)
        frequency = index.get("readings", {}).get(word["reading"], {}).get("tubelex")
        word["status"] = "missing"
        word["selected_frequency"] = None
        if frequency is not None:
            low, high = frequency["per_million"], frequency["per_million_upper"]
            if not all(math.isfinite(f) and f >= 0 for f in (low, high)) or high < low:
                raise ValueError(f"Invalid frequency for {word['reading']}")
            ambiguous = frequency["count"] != frequency["count_upper"]
            word["status"] = "ambiguous" if ambiguous else "unambiguous"
            if not ambiguous or policy == "lower":
                word["selected_frequency"] = low
        grouped[word["start_kana"]].append(word)
    kana_order = STANDARD_KANA + sorted(set(grouped) - set(STANDARD_KANA))
    results, word_rows = [], []
    all_safe = [word for words in grouped.values() for word in words if word["end_kana"] != "ん"]
    global_masses = {threshold: math.fsum(w["selected_frequency"] for w in all_safe
                     if w["selected_frequency"] is not None and w["selected_frequency"] > 0
                     and w["selected_frequency"] >= threshold) for threshold in thresholds}
    global_baseline_words = sum(w["selected_frequency"] is not None and w["selected_frequency"] > 0 for w in all_safe)
    for kana in kana_order:
        words = grouped[kana]
        safe = [word for word in words if word["end_kana"] != "ん"]
        summary = {
            "kana": kana, "dictionary_words": len(words), "safe_words": len(safe),
            "ends_in_n_words": len(words) - len(safe),
            "jmdict_common_safe_words": sum(bool(w["common"]) for w in safe),
            "frequency_matched_safe_words": sum(w["status"] != "missing" for w in safe),
            "unambiguous_safe_words": sum(w["status"] == "unambiguous" for w in safe),
            "ambiguous_safe_words": sum(w["status"] == "ambiguous" for w in safe),
            "missing_frequency_safe_words": sum(w["status"] == "missing" for w in safe),
            "matched_coverage": sum(w["status"] != "missing" for w in safe) / len(safe) if safe else None,
            "thresholds": [],
        }
        for threshold in thresholds:
            stats = distribution(safe, threshold, alpha)
            ranked = stats.pop("ranked")
            stats["baseline_vocabulary_frequency_share"] = stats["frequency_mass_per_million"] / global_masses[threshold] if global_masses[threshold] else None
            stats["fraction_of_safe_dictionary_retained"] = len(ranked) / len(safe) if safe else None
            stats["fraction_of_covered_frequency_mass_retained"] = stats["frequency_mass_per_million"] / summary["thresholds"][0]["frequency_mass_per_million"] if threshold and summary["thresholds"][0]["frequency_mass_per_million"] else (1.0 if ranked else None)
            stats["top_words"] = [{"reading": w["reading"], "per_million": w["selected_frequency"],
                                   "probability_given_kana": p, "cumulative_probability": c,
                                   "next_kana": w["end_kana"]} for w, p, c in ranked[:top]]
            summary["thresholds"].append(stats)
            if threshold == 0:
                for rank, (word, probability, cumulative) in enumerate(ranked, 1):
                    word_rows.append({"kana": kana, "rank_within_kana": rank,
                        "reading": word["reading"], "next_kana": word["end_kana"],
                        "frequency_per_million": word["selected_frequency"],
                        "probability_given_kana": probability, "cumulative_probability": cumulative,
                        "corpus_token_mass": word["selected_frequency"] / 1_000_000,
                        "frequency_share_among_baseline_words": word["selected_frequency"] / global_masses[0],
                        "frequency_status": word["status"]})
        results.append(summary)
    global_thresholds = []
    for i, threshold in enumerate(thresholds):
        counts = {r["kana"]: r["thresholds"][i]["eligible_words"] for r in results}
        for row in results:
            stats = row["thresholds"][i]
            ranked = distribution([word for word in grouped[row["kana"]] if word["end_kana"] != "ん"], threshold, alpha)["ranked"]
            # At this initial position the played word is now unavailable.
            # A self-loop can remove the destination's last candidate.
            replies = [(max(0, counts.get(word["end_kana"], 0) - int(word["end_kana"] == row["kana"])), probability)
                       for word, probability, _ in ranked]
            stats["expected_baseline_replies_after_move"] = math.fsum(count * probability for count, probability in replies) if ranked else None
            stats["probability_of_leaving_baseline_no_reply"] = math.fsum(probability for count, probability in replies if count == 0) if ranked else None
        playable = [r["kana"] for r in results if r["thresholds"][i]["eligible_words"]]
        unplayable = [r["kana"] for r in results if not r["thresholds"][i]["eligible_words"]]
        global_thresholds.append({"threshold": threshold,
            "eligible_words": sum(r["thresholds"][i]["eligible_words"] for r in results),
            "frequency_mass_per_million": global_masses[threshold],
            "corpus_token_mass": global_masses[threshold] / 1_000_000,
            "playable_starting_kana": playable, "no_candidates_kana": unplayable})
    return {"schema_version": 1, "alpha": alpha, "frequency_policy": policy,
            "dictionary_words": len(rows), "safe_words": len(all_safe),
            "baseline_words_before_threshold": global_baseline_words,
            "thresholds": global_thresholds, "kana": results}, word_rows


def text_report(analysis: dict[str, Any]) -> str:
    lines = ["Shiritori kana vocabulary analysis", "",
        f"Dictionary readings: {analysis['dictionary_words']:,}; safe readings: {analysis['safe_words']:,}",
        f"Frequency policy: {analysis['frequency_policy']}; sampling exponent alpha={analysis['alpha']:g}",
        "Safe = not ending in ん. These are initial positions; no words have been used.",
        "Frequency is a TUBELEX matched-written-form proxy, not measured human familiarity.",
        "Missing frequency is unavailable, not zero. Ambiguous upper counts are never summed.",
        "Corpus mass = sum(frequency per million)/1,000,000; it is NOT a probability of winning.",
        "Baseline share = this kana's share of covered safe-word frequency, NOT the probability",
        "that play reaches this kana. Conditional word probabilities sum to 1 within each kana.",
        "N50/N90 = number of most likely words accounting for 50%/90% of draws.", "",
        "INITIAL VOCABULARY (threshold 0)",
        "Kana   Dict    Safe  Matched  Ambig   Pool    Mass/1M  Share%   Top1%  Top5%  N50  N90  Eff.words"]
    for row in analysis["kana"]:
        base = row["thresholds"][0]
        percent = lambda value: f"{100 * value:.1f}" if value is not None else "—"
        mass = base["words_for_probability_mass"]
        lines.append(f"{row['kana']}  {row['dictionary_words']:>7} {row['safe_words']:>7} {row['frequency_matched_safe_words']:>7} {row['ambiguous_safe_words']:>6} {base['eligible_words']:>6} {base['frequency_mass_per_million']:>10.3f} {percent(base['baseline_vocabulary_frequency_share']):>7} {percent(base['top_probability_mass']['1']):>7} {percent(base['top_probability_mass']['5']):>6} {str(mass['0.5'] or '—'):>4} {str(mass['0.9'] or '—'):>4} {base['effective_words_entropy']:>9.1f}")
    lines += ["", "THRESHOLD COMPARISON (occurrences per million corpus tokens)"]
    for stats in analysis["thresholds"]:
        lines.append(f"At >= {stats['threshold']:g}/million: {stats['eligible_words']:,} words; {len(stats['playable_starting_kana'])} supported starts; mass {stats['frequency_mass_per_million']:.3f}/million")
        lines.append("  No candidates: " + " ".join(stats["no_candidates_kana"]))
    lines += ["", "PER-KANA DETAILS"]
    for row in analysis["kana"]:
        if not row["dictionary_words"]:
            continue
        lines += ["", f"{row['kana']}: {row['safe_words']:,} safe, {row['ends_in_n_words']:,} immediate-loss words; {row['missing_frequency_safe_words']:,} safe words missing frequency"]
        for stats in row["thresholds"]:
            lines.append(f"  >= {stats['threshold']:g}/million: {stats['eligible_words']} candidates; N95={stats['words_for_probability_mass']['0.95']}; entropy={stats['entropy_bits'] if stats['entropy_bits'] is not None else 'unavailable'} bits")
        lines.append("  Most likely words at threshold 0:")
        for word in row["thresholds"][0]["top_words"]:
            lines.append(f"    {word['reading']} -> {word['next_kana']}   {word['per_million']:.4g}/million   P={word['probability_given_kana']:.2%}   cumulative={word['cumulative_probability']:.2%}")
    return "\n".join(lines) + "\n"
