#!/usr/bin/env python3
"""Decompose lookahead, test mixing, and audit frequency-coverage artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import statistics
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.move_quality import MoveAnalyzer, rank_correlation
from shiritori_bench.results import read_jsonl
from shiritori_bench.score_diagnostics import (
    coverage_rows, depth_decomposition, mixing_diagnostics, synthetic_index,
)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def fmt(value):
    return "n/a" if value is None else f"{value:.4g}"


def ranking(values, selected):
    if not values:
        return {"choices": 0, "chosen_in_pool": False, "percentile": None, "top": []}
    chosen = next((value for word, value in values if word == selected), None)
    percentile = None if chosen is None else 100 * (
        sum(value < chosen - 1e-9 for _, value in values) +
        0.5 * sum(abs(value - chosen) <= 1e-9 for _, value in values)) / len(values)
    return {"choices": len(values), "chosen_in_pool": chosen is not None, "percentile": percentile,
            "top": [{"word": word, "score": score}
                    for word, score in sorted(values, key=lambda item: (-item[1], item[0]))[:5]]}


def replay_coverage(analyzer, matches, gamma):
    """Score identical states; filter comparison pools without changing the graph."""
    output, provenance = [], []
    for path in matches:
        provenance.append({"path": str(path.resolve()), "sha256": digest(path)})
        for match in read_jsonl(path):
            used = set()
            for turn in match.get("turns", []):
                if turn["outcome"] != "VALID":
                    continue
                if match["outcome"] == "PLAYER_ERROR":
                    used.add(turn["normalized"])
                    continue
                print(f"Auditing {match['match_id']} turn {turn['turn']}", flush=True)
                position = analyzer.snapshot(used)
                required, chosen = turn["required_kana"], turn["normalized"]
                all_choices, supported, measured, unsupported = [], [], [], set()
                for word in position.safe[required]:
                    reading = word["reading"]
                    j = analyzer.positions[word["end_kana"]]
                    self_loop = int(word["start_kana"] == word["end_kana"])
                    has_frequency_reply = position.frequency_count[j] - (
                        self_loop * int(reading in analyzer.frequencies)) > 0
                    has_dictionary_reply = position.safe_count[j] - self_loop > 0
                    score = position.candidate_values(word)[str(gamma)]
                    all_choices.append((reading, score))
                    # Actual dictionary dead ends are valid terminal choices, not missing-data artifacts.
                    if has_frequency_reply or not has_dictionary_reply:
                        supported.append((reading, score))
                        if reading in analyzer.frequencies:
                            measured.append((reading, score))
                    else:
                        unsupported.add(reading)
                original = ranking(all_choices, chosen)
                for choice in original["top"]:
                    choice["unsupported_destination"] = choice["word"] in unsupported
                output.append({"match_id": match["match_id"], "turn": turn["turn"],
                    "word": chosen, "gamma": gamma, "required_kana": required,
                    "all_dictionary": original,
                    "supported_destination": ranking(supported, chosen),
                    "measured_word_and_supported_destination": ranking(measured, chosen),
                    "unsupported_destination_choices": len(unsupported)})
                used.add(chosen)
    return output, provenance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocabulary", type=Path, default=PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite")
    parser.add_argument("--frequency", type=Path, default=PROJECT_ROOT / "data/processed/word-frequency.json")
    parser.add_argument("--gammas", type=float, nargs="+", default=[0, 0.5, 0.85, 0.99])
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--alpha", type=float, default=1)
    parser.add_argument("--audit-gamma", type=float, default=0.85)
    parser.add_argument("--matches", type=Path, nargs="*")
    parser.add_argument("--skip-matches", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    index = json.loads(args.frequency.read_text(encoding="utf-8"))
    vocabulary_hash = digest(args.vocabulary)
    if vocabulary_hash != index.get("vocabulary_sha256"):
        parser.error("Frequency vocabulary hash mismatch")
    with sqlite3.connect(f"{args.vocabulary.resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        words = [dict(row) for row in connection.execute("SELECT reading, start_kana, end_kana, common FROM words")]
    gammas = tuple(sorted(set([*args.gammas, args.audit_gamma])))
    settings = {"threshold": args.threshold, "alpha": args.alpha, "gammas": gammas}
    try:
        baseline = MoveAnalyzer(words, index, **settings)
    except ValueError as error:
        parser.error(str(error))
    print("Decomposing baseline log-mass graph", flush=True)
    position = baseline.snapshot()
    starts = [i for i, count in enumerate(position.frequency_count) if count]
    reference_kana = [baseline.kana[i] for i in starts]
    depths = {str(g): depth_decomposition(position, g) for g in gammas}
    mixing = mixing_diagnostics(position.p, starts)
    linear = MoveAnalyzer(words, index, **settings, transform="linear").snapshot()
    linear_depths = {str(g): depth_decomposition(linear, g) for g in gammas}
    coverage = coverage_rows(position)

    scenarios = []

    def scenario(name, analyzer, *, synthetic=False):
        print(f"Coverage sensitivity: {name}", flush=True)
        state = analyzer.snapshot()
        values = {str(g): {kana: state.solutions[str(g)][0][analyzer.positions[kana]]
                           for kana in reference_kana} for g in gammas}
        ranked = {str(g): sorted(reference_kana, key=lambda k: (-values[str(g)][k], k)) for g in gammas}
        shifts = {}
        for g in gammas:
            old = sorted(reference_kana, key=lambda k: (-position.solutions[str(g)][0][baseline.positions[k]], k))
            old_ranks = {k: i + 1 for i, k in enumerate(old)}
            shifts[str(g)] = sorted([
                {"kana": k, "baseline_rank": old_ranks[k], "scenario_rank": i + 1}
                for i, k in enumerate(ranked[str(g)])],
                key=lambda row: -abs(row["baseline_rank"] - row["scenario_rank"]))[:10]
        scenarios.append({"name": name, "synthetic": synthetic,
            "settings": {"threshold": analyzer.threshold, "alpha": analyzer.alpha,
                         "policy": analyzer.policy, "transform": analyzer.transform},
            "selected_safe_words": sum(state.frequency_count),
            "safe_frequency_mass": math.fsum(state.frequency_mass),
            "unsupported_dictionary_kana": [r["kana"] for r in coverage_rows(state) if r["unsupported"]],
            "comparison_kana": reference_kana,
            "correlation_on_fixed_baseline_supported_kana": {str(g): rank_correlation(
                [position.solutions[str(g)][0][baseline.positions[k]] for k in reference_kana],
                [values[str(g)][k] for k in reference_kana]) for g in gammas},
            "rankings": ranked, "largest_rank_changes": shifts, "scores": values})

    scenario("baseline", baseline)
    for threshold in (0, 0.1, 10):
        scenario(f"measured_threshold_{threshold:g}", MoveAnalyzer(words, index, **(settings | {"threshold": threshold})))
    scenario("measured_lower_counts", MoveAnalyzer(words, index, **settings, policy="lower"))
    scenario("measured_alpha_0.5", MoveAnalyzer(words, index, **(settings | {"alpha": 0.5})))
    for floor in (0.001, 0.01, 0.1, 1):
        scenario(f"SYNTHETIC_excluded_word_floor_{floor:g}", MoveAnalyzer(words,
            synthetic_index(baseline, floor=floor), **(settings | {"threshold": 0})), synthetic=True)
    scenario("SYNTHETIC_uniform_full_dictionary", MoveAnalyzer(words,
        synthetic_index(baseline, uniform=True), **(settings | {"threshold": 0})), synthetic=True)

    matches = [] if args.skip_matches else (args.matches if args.matches is not None else
        sorted((PROJECT_ROOT / "results/pilots").glob("*/matches.jsonl")))
    # Replay only the audit discount: avoids solving unused systems in every state.
    audit_analyzer = MoveAnalyzer(words, index, **(settings | {"gammas": (args.audit_gamma,)}))
    moves, inputs = replay_coverage(audit_analyzer, matches, args.audit_gamma)
    deltas = [abs(m["all_dictionary"]["percentile"] - m["supported_destination"]["percentile"])
              for m in moves if m["supported_destination"]["percentile"] is not None]
    audit = {"valid_competitive_turns": len(moves),
        "turns_with_unsupported_top_choice": sum(bool(m["all_dictionary"]["top"]) and
            m["all_dictionary"]["top"][0]["unsupported_destination"] for m in moves),
        "turns_with_unsupported_in_top5": sum(any(w["unsupported_destination"] for w in
            m["all_dictionary"]["top"]) for m in moves),
        "chosen_destination_unsupported": sum(not m["supported_destination"]["chosen_in_pool"] for m in moves),
        "median_absolute_percentile_change": statistics.median(deltas) if deltas else None,
        "max_absolute_percentile_change": max(deltas, default=None)}
    notes = [
        "Frozen initial graph only; no future depletion, no minimax, no demonstrated playing-strength validity.",
        "Cross-kana statistics give each initially frequency-supported kana equal weight, not visitation weight.",
        "Centered SD removes common offsets; small centered error need not mean small absolute score error.",
        "Mixing TV includes an absorbing cemetery; survival distinguishes mixing from common termination.",
        "Coverage comparisons use the same baseline-supported kana, even if a scenario removes support.",
        "Synthetic floors assign every baseline-excluded reading the same artificial mass, including ambiguous and below-threshold readings. They are sensitivity scenarios, not measured frequencies or statistical bounds.",
        "Supported-destination filtering changes alternative pools, not the underlying graph. It does not repair incomplete coverage; measured-word restriction additionally changes lexical availability.",
        "Recorded illegal moves and all infrastructure-error matches are excluded from the coverage replay.",
    ]
    result = {"created_at": datetime.now(timezone.utc).isoformat(), "settings": settings,
        "audit_gamma": args.audit_gamma, "vocabulary_sha256": vocabulary_hash,
        "frequency_sha256": digest(args.frequency), "input_matches": inputs, "notes": notes,
        "log_depth_decomposition": depths, "linear_depth_decomposition": linear_depths,
        "mixing": mixing, "coverage": coverage, "sensitivity": scenarios, "saved_game_audit": audit}
    lines = ["Score diagnostics: depth, mixing and coverage", "", *notes,
             "", "MIXING: unconditional distributions from initially supported kana",
             "Depth   Max TV   Mean TV   Mean survival"]
    for row in mixing:
        lines.append(f"{row['depth']:>5}  {fmt(row['max_pairwise_tv']):>7}  {fmt(row['mean_pairwise_tv']):>8}  {fmt(row['mean_survival']):>13}")
    for label, decomposition in (("LOG", depths), ("LINEAR", linear_depths)):
        for gamma, records in decomposition.items():
            lines += ["", f"{label} MASS: gamma={gamma}",
                "Depth  Reward SD  Increment SD/immediate SD  Pair SD ratio  Pair mean ratio  Rank corr/infinite  Centered tail/infinite SD  Max absolute tail"]
            for row in records:
                lines.append(f"{row['depth']:>5}  {fmt(row['reward_sd']):>9}  {fmt(row['increment_sd_relative_to_immediate']):>25}  {fmt(row['adjacent_pair_sd_ratio']):>13}  {fmt(row['adjacent_pair_mean_ratio']):>15}  {fmt(row['cumulative_vs_infinite_spearman']):>18}  {fmt(row['centered_remainder_relative_to_infinite_sd']):>25}  {fmt(row['absolute_remainder_max']):>17}")
    lines += ["", "UNSUPPORTED KANA: not proven dictionary dead ends"]
    for row in coverage:
        if row["unsupported"]:
            lines.append(f"{row['kana']}: safe words={row['safe_dictionary_replies']}; missing={row['missing']}; ambiguous excluded={row['ambiguous_excluded']}; below threshold/zero={row['below_threshold_or_zero']}; reachable as safe ending={row['reachable_as_safe_ending']}")
    lines += ["", "SENSITIVITY: rank correlation on fixed baseline-supported kana", "Scenario / selected safe words / correlations by gamma"]
    for row in scenarios:
        lines.append(f"{row['name']} / {row['selected_safe_words']} / " +
            ", ".join(f"{g}: {fmt(c)}" for g, c in row["correlation_on_fixed_baseline_supported_kana"].items()))
        changes = row["largest_rank_changes"][str(args.audit_gamma)][:3]
        lines.append("  Largest changes at audit gamma: " + ", ".join(
            f"{r['kana']} {r['baseline_rank']}->{r['scenario_rank']}" for r in changes))
    lines += ["", "SAVED GAME COVERAGE AUDIT", json.dumps(audit, ensure_ascii=False, indent=2),
              "", "Word / all-dictionary percentile / supported-destination percentile / measured-word+supported percentile"]
    for m in moves:
        lines.append(f"{m['match_id']} turn {m['turn']}: {m['word']} / " + " / ".join(
            fmt(m[key]["percentile"]) for key in ("all_dictionary", "supported_destination", "measured_word_and_supported_destination")))
    destination = args.output_dir or PROJECT_ROOT / "results/score-diagnostics" / (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    destination.mkdir(parents=True, exist_ok=False)
    (destination / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    (destination / "moves.jsonl").write_text("".join(json.dumps(m, ensure_ascii=False, allow_nan=False) + "\n" for m in moves), encoding="utf-8")
    (destination / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:16]))
    print(json.dumps(audit, indent=2))
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()
