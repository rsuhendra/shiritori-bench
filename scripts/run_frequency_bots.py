#!/usr/bin/env python3
"""Run reproducible pure-frequency self-play; no LLM client or API calls."""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import statistics
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.frequency_bot import FrequencyBot, load_frequency_vocabulary
from shiritori_bench.bots import GameState
from shiritori_bench.match import MatchRunner
from shiritori_bench.players import BotPlayer
from shiritori_bench.referee import Referee
from shiritori_bench.results import append_jsonl
from shiritori_bench.transcript import render_games


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--opening", default="か")
    parser.add_argument("--trials", type=int, default=3, help="Seed pairs, each played in both orders")
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--threshold", type=float, default=1)
    parser.add_argument("--alpha", type=float, default=1)
    parser.add_argument("--frequency-policy", choices=["unambiguous", "lower"], default="unambiguous")
    parser.add_argument("--turn-limit", type=int, default=2000)
    parser.add_argument("--vocabulary", type=Path, default=PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite")
    parser.add_argument("--frequency", type=Path, default=PROJECT_ROOT / "data/processed/word-frequency.json")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.trials < 1 or args.turn_limit < 1:
        parser.error("trials and turn-limit must be positive")
    graph, frequencies, provenance = load_frequency_vocabulary(args.vocabulary, args.frequency,
        threshold=args.threshold, policy=args.frequency_policy)
    # Validate all bot parameters before creating output files.
    FrequencyBot(graph, frequencies, seed=args.seed, alpha=args.alpha)
    if not graph.safe_moves(GameState(args.opening)):
        parser.error("Opening has no safe words in the selected bot vocabulary")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    destination = args.output_dir or PROJECT_ROOT / "results/bot-selfplay" / run_id
    destination.mkdir(parents=True, exist_ok=False)
    schedule = [{"trial": trial + 1, "order": order + 1,
        "seeds": list(pair if order == 0 else pair[::-1]),
        "match_id": f"{run_id}-{trial + 1:02d}-{order + 1}"}
        for trial in range(args.trials)
        for pair in [(args.seed + 2 * trial, args.seed + 2 * trial + 1)]
        for order in range(2)]
    pool = json.dumps(dict(sorted(frequencies.items())), ensure_ascii=False, indent=2) + "\n"
    (destination / "vocabulary.json").write_text(pool, encoding="utf-8")
    manifest = {"created_at": datetime.now(timezone.utc).isoformat(), "python": platform.python_version(),
        "bot": "FrequencyBot", "strategy": "none; beta=0; p(word|state) proportional to frequency**alpha",
        "alpha": args.alpha, "opening": args.opening, "turn_limit": args.turn_limit,
        "sampling": "local random.Random(seed); inverse CDF over sorted readings; fresh RNG per game",
        "exhaustion": "PASS when no unused safe word remains in this bot's fixed vocabulary; no full-dictionary rescue. This loses even if the referee has other words.",
        "vocabulary": provenance, "pool_sha256": hashlib.sha256(pool.encode()).hexdigest(),
        "schedule": schedule, "code_sha256": {str(p.relative_to(PROJECT_ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [Path(__file__).resolve(), *[PROJECT_ROOT / "src/shiritori_bench" / name
                for name in ("frequency_bot.py", "bots.py", "players.py", "match.py", "referee.py", "normalize.py")]]}}
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    version = "jmdict-" + provenance["dictionary_metadata"]["filter_version"] + "-" + provenance["vocabulary_sha256"][:12]
    referee, records = Referee(str(args.vocabulary)), []
    try:
        runner = MatchRunner(referee, vocabulary_version=version, turn_limit=args.turn_limit)
        for item in schedule:
            players = [BotPlayer(FrequencyBot(graph, frequencies, seed=s, alpha=args.alpha)) for s in item["seeds"]]
            record = runner.run(*players, opening_kana=args.opening, match_id=item["match_id"])
            append_jsonl(destination / "matches.jsonl", record)
            data = record.to_dict()
            records.append(data)
            valid = sum(t["outcome"] == "VALID" for t in data["turns"])
            print(f"Trial {item['trial']}, order {item['order']}: seeds {item['seeds']}; {valid} words; {record.ending}", flush=True)
    finally:
        referee.close()
    game_text = ("FrequencyBot self-play — exploratory baseline smoke test\n"
        f"Fixed vocabulary: {len(frequencies)} safe readings; threshold {args.threshold:g}/million; "
        f"policy {args.frequency_policy}; alpha {args.alpha:g}; no search.\n"
        "PASS means the bot's own vocabulary is exhausted, not necessarily the full dictionary.\n"
        "Human familiarity is not calibrated; absent and ambiguous frequency data can exclude common words.\n\n")
    (destination / "games.txt").write_text(game_text + render_games(records), encoding="utf-8")
    lengths = [sum(t["outcome"] == "VALID" for t in r["turns"]) for r in records]
    summary = {"games": len(records), "valid_words_per_game": lengths,
        "mean_valid_words": statistics.mean(lengths), "median_valid_words": statistics.median(lengths),
        "minimum": min(lengths), "maximum": max(lengths),
        "endings": dict(Counter(r["ending"] for r in records)),
        "p1_wins": sum(r["winner_index"] == 0 for r in records),
        "p2_wins": sum(r["winner_index"] == 1 for r in records),
        "turn_limit_unfinished": sum(r["outcome"] == "TURN_LIMIT_DRAW" for r in records),
        "infrastructure_errors": sum(r["outcome"] == "PLAYER_ERROR" for r in records)}
    rows = ["FrequencyBot self-play summary", "", game_text.strip(), "",
        "Trial / order / P1 seed / P2 seed / valid words / losing required kana / P1 or P2 winner / ending"]
    for item, record, length in zip(schedule, records, lengths):
        tail = record["turns"][-1] if record["turns"] else {}
        winner = record["winner_index"]
        rows.append(f"{item['trial']} / {item['order']} / {item['seeds'][0]} / {item['seeds'][1]} / {length} / "
            f"{tail.get('required_kana', '—')} / {('P' + str(winner + 1)) if winner is not None else 'none'} / {record['ending']}")
    rows += ["", json.dumps(summary, ensure_ascii=False, indent=2), "",
        "Same-policy self-play only: seed or seat win counts are not rankings of distinct bot strengths.",
        "A turn-limit result is unfinished, not demonstrated equal strength. No paid calls were made."]
    (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (destination / "summary.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")
    print("\n".join(rows))
    print(f"Saved: {destination}")
    if summary["infrastructure_errors"]:
        raise SystemExit("One or more games had a player/infrastructure error; inspect matches.jsonl")


if __name__ == "__main__":
    main()
