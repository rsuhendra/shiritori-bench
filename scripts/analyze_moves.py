#!/usr/bin/env python3
"""Compare structural/alternating scores and annotate saved matches offline."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.frequency import INDEX_PATH
from shiritori_bench.move_quality import MoveAnalyzer, rank_correlation
from shiritori_bench.results import read_jsonl
from shiritori_bench.transcript import english_meaning, romanize


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def display(value, digits=3):
    return "unavailable" if value is None else f"{value:.{digits}f}"


def profile(analyzer):
    position = analyzer.snapshot()
    metrics = [position.kana_measures(k) for k in analyzer.kana]
    # Report correlations only where the assumed reply policy has support.
    supported = [m for m in metrics if m["covered_safe_replies"] > 0]
    correlations = {}
    for g in analyzer.gammas:
        values = [m["discounted_values"][str(g)] for m in supported]
        correlations[str(g)] = {
            "vs_immediate_mass_pressure": rank_correlation(values, [m["immediate_pressure"] for m in supported]),
            "vs_negative_reply_count": rank_correlation(values, [-m["safe_replies"] for m in supported]),
            "vs_sustainability_ratio": rank_correlation(values, [m["attack_sustainability_count_ratio"] for m in supported]),
        }
    return {"threshold": analyzer.threshold, "transform": analyzer.transform,
            "mass_scale": analyzer.mass_scale, "supported_kana": len(supported),
            "correlations": correlations, "solver_residuals": {g: solution[2] for g, solution in position.solutions.items()},
            "kana": metrics}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vocabulary", type=Path, default=PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite")
    parser.add_argument("--frequency", type=Path, default=INDEX_PATH)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--sensitivity-thresholds", type=float, nargs="+", default=[0.1, 1, 10])
    parser.add_argument("--gammas", type=float, nargs="+", default=[0.5, 0.85, 0.95])
    parser.add_argument("--alpha", type=float, default=1)
    parser.add_argument("--frequency-policy", choices=["unambiguous", "lower"], default="unambiguous")
    parser.add_argument("--transform", choices=["log", "linear"], default="log")
    parser.add_argument("--mass-scale", type=float, default=1, help="Reward mass unit, in occurrences per million")
    parser.add_argument("--matches", nargs="*", type=Path, help="Matches JSONL files; default: all saved pilots")
    parser.add_argument("--skip-matches", action="store_true")
    parser.add_argument("--word", help="Also evaluate a custom submitted word")
    parser.add_argument("--required", help="Required starting kana for --word")
    parser.add_argument("--used", nargs="*", default=[], help="Previously used readings for --word")
    parser.add_argument("--output-dir", type=Path, help="New directory; never overwrite an existing run")
    args = parser.parse_args()
    if args.word and not args.required:
        parser.error("--word requires --required")
    if not args.frequency.is_file():
        parser.error("Build the TUBELEX frequency index first")
    index = json.loads(args.frequency.read_text(encoding="utf-8"))
    vocabulary_hash = digest(args.vocabulary)
    if index.get("vocabulary_sha256") != vocabulary_hash:
        parser.error("Frequency vocabulary hash mismatch; rebuild the index")
    with sqlite3.connect(f"{args.vocabulary.resolve().as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        rows = [dict(row) for row in connection.execute("SELECT reading, start_kana, end_kana, common FROM words")]
    settings = {"threshold": args.threshold, "alpha": args.alpha, "policy": args.frequency_policy,
                "gammas": args.gammas, "transform": args.transform, "mass_scale": args.mass_scale}
    try:
        analyzer = MoveAnalyzer(rows, index, **settings)
    except ValueError as error:
        parser.error(str(error))
    profiles = []
    for threshold in sorted(set([args.threshold, *args.sensitivity_thresholds])):
        for transform in ("log", "linear"):
            print(f"Analyzing kana: threshold={threshold:g}, reward={transform}", flush=True)
            try:
                profiles.append(profile(MoveAnalyzer(rows, index, **(settings | {"threshold": threshold, "transform": transform}))))
            except ValueError as error:
                parser.error(str(error))
    reference = next(p for p in profiles if p["threshold"] == args.threshold and p["transform"] == args.transform)
    reference_by_kana = {k["kana"]: k for k in reference["kana"]}
    for p in profiles:
        shared = [(k, reference_by_kana[k["kana"]]) for k in p["kana"]
                  if k["covered_safe_replies"] and reference_by_kana[k["kana"]]["covered_safe_replies"]]
        p["rank_stability_vs_reference"] = {str(g): rank_correlation(
            [k["discounted_values"][str(g)] for k, _ in shared],
            [k["discounted_values"][str(g)] for _, k in shared]) for g in analyzer.gammas}
    matches = [] if args.skip_matches else (args.matches if args.matches is not None else sorted((PROJECT_ROOT / "results/pilots").glob("*/matches.jsonl")))
    evaluated, input_files = [], []
    for path in matches:
        input_files.append({"path": str(path), "sha256": digest(path)})
        for match in read_jsonl(path):
            used = set()
            for turn in match.get("turns", []):
                print(f"Scoring {match['match_id']} turn {turn['turn']}: {turn['submitted'] or '(empty)'}", flush=True)
                result = analyzer.snapshot(used).score_move(turn["submitted"], turn["required_kana"])
                result.update({"match_id": match["match_id"], "turn": turn["turn"],
                               "player": turn["player_name"], "recorded_outcome": turn["outcome"],
                               "competitive_observation": match["outcome"] != "PLAYER_ERROR",
                               "finish_reason": turn.get("metadata", {}).get("finish_reason")})
                if result["legality"] != turn["outcome"]:
                    result["validation_disagreement"] = True
                evaluated.append(result)
                if turn["outcome"] == "VALID":
                    used.add(turn["normalized"])
    if args.word:
        result = analyzer.snapshot(args.used).score_move(args.word, args.required)
        result.update({"match_id": "custom", "turn": len(args.used) + 1, "player": "custom",
                       "competitive_observation": False})
        evaluated.append(result)
    identifier = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = args.output_dir or PROJECT_ROOT / "results/move-analysis" / identifier
    destination.mkdir(parents=True, exist_ok=False)
    metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "settings": settings,
                "vocabulary_sha256": vocabulary_hash, "frequency_sha256": digest(args.frequency),
                "input_matches": input_files,
                "score_definition": "Q = -r - gamma P Q; r=log1p(M/mass_scale) or M/mass_scale. Higher is better for the player who just moved, evaluated at the opponent's starting kana under the assumed policy.",
                "approximation": "Used words and candidate removed exactly; future graph frozen. Two-ply reply statistics additionally remove the opponent reply. Not minimax, win probability or human calibration.",
                "empty_pool_rule": "Empty transition rows are zero and terminate continuation; reward of zero mass is zero. No extra win/loss bonus. Unsupported dictionary destinations are separately flagged.",
                "n_trap_rule": "Count share includes dictionary ending-in-n words; frequency share uses covered words before excluding n. Safe-policy players never choose these fatal responses.",
                "historical_features": "2007 Murata et al. features adapted to current remaining vocabulary. BEGIN and END here count safe readings. Two-kana accessibility uses len(reading)==2, not a phonetic mora count.",
                "percentile_rule": "Midrank among all safe dictionary choices in that exact state; all tied = 50. Higher is better. Alternatives remove their own candidate, too.",
                "profiles": profiles}
    (destination / "analysis.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    with (destination / "moves.jsonl").open("w", encoding="utf-8") as output:
        for move in evaluated:
            output.write(json.dumps(move, ensure_ascii=False, allow_nan=False) + "\n")
    lines = ["Move-quality analysis", "", metadata["score_definition"], metadata["approximation"],
             "No score is a proven measure of skill. Frequency coverage is incomplete.",
             "No-candidate frequency destinations can reflect missing data rather than actual scarcity.",
             "N-trap shares describe possible erroneous replies; the safe transition policy excludes them.", "",
             "INITIAL KANA: DISCOUNTED SCORE VS IMMEDIATE PRESSURE", "",
             "Threshold  Reward   Gamma  Supported starts  Spearman vs mass  Spearman vs count"]
    for p in profiles:
        for g, correlation in p["correlations"].items():
            lines.append(f"{p['threshold']:>9g}  {p['transform']:<7}  {g:<5}  {p['supported_kana']:>16}  {display(correlation['vs_immediate_mass_pressure']):>16}  {display(correlation['vs_negative_reply_count']):>17}")
    lines += ["", "RANK STABILITY RELATIVE TO THE SELECTED THRESHOLD/REWARD (shared supported kana)"]
    for p in profiles:
        lines.append(f"  threshold={p['threshold']:g}, reward={p['transform']}: {p['rank_stability_vs_reference']}")
    for g in analyzer.gammas:
        supported = [k for k in reference["kana"] if k["covered_safe_replies"]]
        ordered = sorted(supported, key=lambda k: -k["discounted_values"][str(g)])
        lines += ["", f"MOST ATTRACTIVE SUPPORTED ENDINGS: threshold={args.threshold:g}, {args.transform}, gamma={g:g}",
                  "Kana  Dict replies  Covered replies    Mass/1M     Score  Sustainability  Self-return P"]
        for k in ordered[:15]:
            lines.append(f"{k['kana']}  {k['safe_replies']:>12}  {k['covered_safe_replies']:>15}  {k['frequency_mass_per_million']:>9.3f}  {k['discounted_values'][str(g)]:>8.3f}  {display(k['attack_sustainability_count_ratio']):>14}  {display(k['self_return_probability']):>13}")
    excluded = [k["kana"] for k in reference["kana"] if k["unsupported_by_frequency_model"]]
    lines += ["", "DICTIONARY HAS SAFE WORDS BUT FREQUENCY MODEL HAS NONE: " + " ".join(excluded), "",
              "SAVED GAMES: WORD-BY-WORD DIAGNOSTICS"]
    for move in evaluated:
        lines += ["", f"{move['match_id']} / turn {move['turn']} / {move['player']}",
                  f"  {move['submitted'] or '(no answer)'} ({romanize(move['submitted'])}) — {english_meaning(move['submitted'])}",
                  f"  Legality: {move['legality']}; recorded outcome: {move.get('recorded_outcome', 'custom')}"]
        if not move["competitive_observation"]:
            lines.append("  Not a competitive observation (infrastructure-error match or custom state).")
        strategy = move["strategy"]
        if strategy is None:
            continue
        lines += [f"  Opponent replies: {strategy['safe_replies']} dictionary / {strategy['covered_safe_replies']} frequency pool; mass={strategy['frequency_mass_per_million']:.3f}/million",
                  f"  Effective replies={strategy['effective_replies_entropy']:.2f}; sustainability={display(strategy['attack_sustainability_count_ratio'])}; self-return probability={display(strategy['self_return_probability'])}",
                  f"  Attack accessibility={strategy['attack_accessibility']}; N-trap dictionary share={display(strategy['n_trap_count_share'])}",
                  f"  Next own covered options: expected={display(move['two_ply']['expected_own_covered_replies'])}; worst={move['two_ply']['worst_own_covered_replies']}; probability empty={display(move['two_ply']['probability_own_covered_pool_empty'])}"]
        if strategy["unsupported_by_frequency_model"]:
            lines.append("  WARNING: this destination is unsupported by the frequency model, not a proven dead end.")
        for gamma, lookahead in move["lookahead"].items():
            alt = move["alternatives"][gamma]
            lines.append(f"  gamma={gamma}: score={lookahead['infinite']:.3f}; percentile={alt['midrank_percentile']:.1f}; heuristic regret={alt['regret_under_heuristic']:.3f}; horizons={lookahead['finite_horizons']}")
            lines.append("    Best alternatives: " + ", ".join(f"{w['word']}→{w['ending']} ({w['score']:.3f}; {w['destination_covered_replies']} covered replies)" for w in alt["top_choices"]))
    disagreements = [move for move in evaluated if move.get("validation_disagreement")]
    lines += ["", f"Validation disagreements: {len(disagreements)} (inspect moves.jsonl)."]
    report = "\n".join(lines) + "\n"
    (destination / "summary.txt").write_text(report, encoding="utf-8")
    print(report.split("SAVED GAMES: WORD-BY-WORD DIAGNOSTICS")[0])
    print(f"Analyzed {len(evaluated)} recorded/custom moves; validation disagreements: {len(disagreements)}")
    print(f"Saved: {destination}")


if __name__ == "__main__":
    main()
