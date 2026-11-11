#!/usr/bin/env python3
"""Offline round robin: frequency, recall, memory and combined ablations."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
from itertools import combinations_with_replacement
import json
from pathlib import Path
import platform
import statistics
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.bots import GameState
from shiritori_bench.cognitive_bot import CognitiveBot
from shiritori_bench.frequency_bot import FrequencyBot, load_frequency_vocabulary
from shiritori_bench.match import MatchRunner
from shiritori_bench.players import BotPlayer
from shiritori_bench.referee import Referee
from shiritori_bench.results import append_jsonl
from shiritori_bench.transcript import render_games, romanize

PROFILES = ("frequency", "recall", "memory", "combined")
LABELS = {"frequency":"FrequencyBot", "recall":"RecallBot", "memory":"MemoryBot", "combined":"RecallMemoryBot"}


def make_schedule(openings, trials, seed):
    schedule = []
    for o, opening in enumerate(openings):
        for trial in range(trials):
            for i, j in combinations_with_replacement(range(len(PROFILES)), 2):
                base = seed + 1000 * o + 20 * trial
                seats = [(PROFILES[i], base + 2 * i), (PROFILES[j], base + 2 * j + int(i == j))]
                for order in range(2):
                    schedule.append({"opening": opening, "opening_index":o,
                        "trial":trial + 1, "order":order + 1,
                        "seats":[{"profile":p, "seed":s} for p,s in (seats if order == 0 else seats[::-1])]})
    return schedule


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openings", nargs="+", default=["か", "さ", "ず"])
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--attempts", type=int, default=10)
    parser.add_argument("--recent", type=int, default=12)
    parser.add_argument("--half-life", type=float, default=40)
    parser.add_argument("--memory-floor", type=float, default=0.2)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--alpha", type=float, default=1)
    parser.add_argument("--frequency-policy", choices=["unambiguous", "lower"], default="unambiguous")
    parser.add_argument("--turn-limit", type=int, default=2000)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.trials < 1 or args.turn_limit < 1 or len(set(args.openings)) != len(args.openings):
        parser.error("Use positive trials/turn-limit and distinct openings")
    graph, frequencies, provenance = load_frequency_vocabulary(
        PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite", PROJECT_ROOT / "data/processed/word-frequency.json",
        threshold=args.threshold, policy=args.frequency_policy)
    settings = {"alpha":args.alpha, "attempts":args.attempts, "recent":args.recent,
        "half_life":args.half_life, "floor":args.memory_floor}

    def player(profile, seed):
        bot = FrequencyBot(graph, frequencies, seed=seed, alpha=args.alpha) if profile == "frequency" else (
            CognitiveBot(graph, frequencies, profile=profile, seed=seed, **settings))
        return BotPlayer(bot)

    for profile in PROFILES:
        player(profile, args.seed)
    for opening in args.openings:
        if not graph.safe_moves(GameState(opening)):
            parser.error(f"Opening {opening} has no selected safe vocabulary")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = args.output_dir or PROJECT_ROOT / "results/cognitive-bots" / run_id
    destination.mkdir(parents=True, exist_ok=False)
    schedule = make_schedule(args.openings, args.trials, args.seed)
    for index, item in enumerate(schedule):
        item["match_id"] = f"{run_id}-{index + 1:04d}"
    pool = json.dumps(dict(sorted(frequencies.items())), ensure_ascii=False, indent=2) + "\n"
    (destination / "vocabulary.json").write_text(pool, encoding="utf-8")
    notes = [
        "Exploratory parameters selected before the run; not fitted to human games or to a target length.",
        "All profiles share the same vocabulary, alpha, openings, referee and turn cap. Fresh seeded bots each game.",
        "Recall samples without replacement per turn BEFORE rejecting recognized played words. Limited variants get 10 attempts by default.",
        "Memory profiles remember the last 12 GLOBAL played moves exactly by default. Older recognition probability = floor + (1-floor)*2^(-(age-recent)/half_life).",
        "A latent last-seen trace drives noisy recognition. The history is visible; the impairment is intentional limited recognition, not a hidden-history condition.",
        "Retrieval and recognition have separate seeded RNG streams. Unlimited means at most one retrieval of every known starting-kana candidate per turn.",
        "All models still know dictionary legality and avoid n perfectly. No spelling errors or attention lapses are modeled.",
        "FrequencyBot is an oracle unused-word sampler; RecallBot has perfect history recognition but bounded retrieval; MemoryBot has unlimited retrieval and noisy recognition; RecallMemoryBot has both limitations.",
        "No strategy/search is added. This compares retrieval/recognition mechanisms, not human realism.",
        "Counterbalancing gives equal first/second seats; self-play games are excluded from cross-profile win rates. No LLM calls."]
    code_files = [Path(__file__).resolve(), *[PROJECT_ROOT / "src/shiritori_bench" / name
        for name in ("cognitive_bot.py", "frequency_bot.py", "bots.py", "players.py", "match.py", "referee.py", "normalize.py")]]
    manifest = {"created_at":datetime.now(timezone.utc).isoformat(), "python":platform.python_version(),
        "settings":settings, "vocabulary":provenance, "openings":args.openings, "turn_limit":args.turn_limit,
        "profiles":LABELS, "schedule":schedule, "notes":notes,
        "pool_sha256":hashlib.sha256(pool.encode()).hexdigest(),
        "code_sha256":{str(p.relative_to(PROJECT_ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_files}}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records, observations = [], []
    referee = Referee(str(PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite"))
    version = f"jmdict-{provenance['dictionary_metadata']['filter_version']}-{provenance['vocabulary_sha256'][:12]}"
    try:
        runner = MatchRunner(referee, vocabulary_version=version, turn_limit=args.turn_limit)
        for index, item in enumerate(schedule):
            record = runner.run(*[player(s["profile"],s["seed"]) for s in item["seats"]],
                opening_kana=item["opening"], match_id=item["match_id"])
            append_jsonl(destination / "matches.jsonl", record)
            data = record.to_dict()
            records.append(data)
            valid = [t for t in data["turns"] if t["outcome"] == "VALID"]
            used = frozenset(t["normalized"] for t in valid)
            tail = data["turns"][-1] if data["turns"] else None
            diagnostic = {"match_id":record.match_id, "opening":item["opening"], "seats":item["seats"],
                "valid_words":len(valid), "winner_index":record.winner_index, "ending":record.ending,
                "infrastructure_error":record.outcome == "PLAYER_ERROR", "unfinished":record.outcome == "TURN_LIMIT_DRAW"}
            if tail:
                remaining = len(graph.safe_moves(GameState(tail["required_kana"], used)))
                reason = tail["metadata"].get("stop_reason", "known_pool_exhausted" if tail["submitted"] == "PASS" else "submitted")
                diagnostic.update({"failure_required_kana":tail["required_kana"], "final_submission":tail["submitted"],
                    "remaining_baseline_safe_moves":remaining, "internal_stop_reason":reason,
                    "repeat_age":(tail["metadata"].get("retrieval_attempts") or [{}])[-1].get("actual_age_moves"),
                    "failure_profile":item["seats"][record.loser_index]["profile"] if record.loser_index is not None else None})
            observations.append(diagnostic)
            if (index + 1) % 10 == 0:
                print(f"Completed {index + 1}/{len(schedule)} games", flush=True)
    finally:
        referee.close()
    (destination / "games.txt").write_text("Exploratory cognitive-bot tournament\n\n" + "\n".join(notes) + "\n\n" + render_games(records), encoding="utf-8")
    (destination / "game-diagnostics.jsonl").write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in observations), encoding="utf-8")
    pair_groups = defaultdict(list)
    for observation in observations:
        pair_groups[tuple(sorted(s["profile"] for s in observation["seats"]))].append(observation)
    pairs = []
    for profiles, games in sorted(pair_groups.items()):
        lengths = [g["valid_words"] for g in games if not g["infrastructure_error"]]
        wins = Counter()
        if profiles[0] != profiles[1]:
            for g in games:
                if g["winner_index"] is not None:
                    wins[g["seats"][g["winner_index"]]["profile"]] += 1
        pairs.append({"profiles":profiles, "games":len(games), "mean_words":statistics.mean(lengths),
            "median_words":statistics.median(lengths), "min_words":min(lengths), "max_words":max(lengths),
            "wins":dict(wins), "endings":dict(Counter(g["ending"] for g in games)),
            "unfinished":sum(g["unfinished"] for g in games)})
    profile_stats = {}
    for profile in PROFILES:
        cross = [g for g in observations if len({s["profile"] for s in g["seats"]}) == 2
                 and any(s["profile"] == profile for s in g["seats"]) and not g["infrastructure_error"]]
        wins = sum(g["winner_index"] is not None and g["seats"][g["winner_index"]]["profile"] == profile for g in cross)
        losses = [g for g in observations if g.get("failure_profile") == profile and not g["infrastructure_error"] and not g["unfinished"]]
        profile_stats[profile] = {"cross_games":len(cross), "cross_wins":wins,
            "cross_win_fraction":wins / len(cross) if cross else None,
            "failure_endings_including_selfplay":dict(Counter(g["ending"] for g in losses)),
            "internal_failure_reasons":dict(Counter(g.get("internal_stop_reason") for g in losses)),
            "passes_with_unused_baseline_words":sum(g.get("final_submission") == "PASS" and g.get("remaining_baseline_safe_moves",0) > 0 for g in losses)}
    summary = {"games":len(records), "pairs":pairs, "profiles":profile_stats,
        "endings":dict(Counter(g["ending"] for g in observations)),
        "unfinished":sum(g["unfinished"] for g in observations),
        "infrastructure_errors":sum(g["infrastructure_error"] for g in observations)}
    lines = ["Cognitive bot tournament: exploratory, not human-calibrated", "", *notes, "",
        f"Games: {len(records)}; vocabulary: {len(frequencies)}; openings: {' '.join(args.openings)}", "",
        "Pair / games / mean accepted words / median / range / cross-profile wins"]
    for p in pairs:
        lines.append(f"{' vs '.join(LABELS[n] for n in p['profiles'])} / {p['games']} / {p['mean_words']:.1f} / {p['median_words']:g} / {p['min_words']}-{p['max_words']} / {p['wins']}")
    lines += ["", "Profile outcomes (cross-profile games only for wins; all losses for failure breakdown)", json.dumps(profile_stats, ensure_ascii=False, indent=2),
        "", f"Unfinished: {summary['unfinished']}; infrastructure errors: {summary['infrastructure_errors']}"]
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "summary.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    examples = ["Short excerpts: first four and last six submissions of one self-play game per profile", ""]
    for profile in PROFILES:
        index = next(i for i,g in enumerate(observations) if all(s["profile"] == profile for s in g["seats"]))
        record, diagnostic = records[index], observations[index]
        examples += [f"{LABELS[profile]}: {diagnostic['valid_words']} accepted words; {diagnostic['ending']}"]
        for t in record["turns"][:4]:
            examples.append(f"  {t['turn']:>4} P{t['player_index'] + 1}: {t['submitted']} / {romanize(t['submitted'])} / {t['outcome']}")
        if len(record["turns"]) > 10:
            examples.append("  ...")
        for t in record["turns"][max(4,len(record["turns"]) - 6):]:
            examples.append(f"  {t['turn']:>4} P{t['player_index'] + 1}: {t['submitted']} / {romanize(t['submitted'])} / {t['outcome']}")
        examples.append("")
    (destination / "examples.txt").write_text("\n".join(examples), encoding="utf-8")
    print("\n".join(lines[:26]))
    print(f"Saved: {destination}")
    if summary["infrastructure_errors"]:
        raise SystemExit("Player/infrastructure errors found; inspect matches.jsonl")


if __name__ == "__main__":
    main()
