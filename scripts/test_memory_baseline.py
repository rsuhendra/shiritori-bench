#!/usr/bin/env python3
"""Offline memory sensitivity and strategic-pressure experiment; no API calls."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from shiritori_bench.bots import GameState
from shiritori_bench.cognitive_bot import CognitiveBot
from shiritori_bench.frequency_bot import FrequencyBot, load_frequency_vocabulary
from shiritori_bench.match import MatchRunner
from shiritori_bench.players import BotPlayer
from shiritori_bench.pressure_bot import PressureBot
from shiritori_bench.referee import Referee
from shiritori_bench.results import append_jsonl

SETTINGS = {"weak": {"recent": 6, "half_life": 20, "floor": .1},
            "current": {"recent": 12, "half_life": 40, "floor": .2},
            "strong": {"recent": 24, "half_life": 80, "floor": .4}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=3)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.trials < 1:
        parser.error("trials must be positive")
    graph, frequencies, provenance = load_frequency_vocabulary(
        ROOT / "data/processed/referee-vocabulary.sqlite", ROOT / "data/processed/word-frequency.json")
    openings = ["か", "さ", "た", "は", "ま", "る", "ず", "ぬ"]
    assert all(graph.safe_moves(GameState(k)) for k in openings)
    schedule = []
    for setting in SETTINGS:
        for o, opening in enumerate(openings):
            for trial in range(args.trials):
                for policy in ("self", "frequency", "immediate", "two_ply"):
                    for seat in range(2):
                        schedule.append(dict(setting=setting, opening=opening, trial=trial,
                            policy=policy, challenger_seat=seat, seed=17001 + o * 1000 + trial * 2))
    output = args.output_dir or ROOT / "results/memory-validation" / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output.mkdir(parents=True, exist_ok=False)
    sources = [Path(__file__), *sorted((ROOT / "src/shiritori_bench").glob("*.py"))]
    manifest = dict(settings=SETTINGS, openings=openings, trials=args.trials, gamma=.85,
        turn_limit=2000, vocabulary=provenance, schedule=schedule,
        code_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        notes=["Parameters fixed before run; not human-calibrated.",
            "Perfect-memory challengers share the same frequency-filtered safe pool.",
            "Paired seeds and seats across policies/settings; trajectories still diverge.",
            "Two-ply assumes frequency-weighted legal opponent replies, not noisy-memory errors.",
            "Settings change three parameters together, not individual causal effects.",
            "Seeds are paired in seat-swaps; games are not independent replicates."])
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    observations = []
    referee = Referee(str(ROOT / "data/processed/referee-vocabulary.sqlite"))
    runner = MatchRunner(referee, vocabulary_version=provenance["vocabulary_sha256"], turn_limit=2000)
    def players(item):
        def memory(seed):
            return BotPlayer(CognitiveBot(graph, frequencies, profile="memory", seed=seed, **SETTINGS[item["setting"]]))
        seed = item["seed"]
        if item["policy"] == "self":
            pair = [memory(seed), memory(seed + 1)]
        else:
            challenger = (BotPlayer(FrequencyBot(graph, frequencies, seed=seed)) if item["policy"] == "frequency"
                          else PressureBot(graph, frequencies, policy=item["policy"]))
            pair = [challenger, memory(seed + 1)]
        return pair if item["challenger_seat"] == 0 else pair[::-1]
    try:
        for i, item in enumerate(schedule):
            record = runner.run(*players(item), opening_kana=item["opening"], match_id=f"memory-{i:04d}")
            append_jsonl(output / "matches.jsonl", record)
            data = record.to_dict()
            valid = sum(t["outcome"] == "VALID" for t in data["turns"])
            tail = data["turns"][-1]
            observations.append(dict(**item, valid_words=valid, ending=record.ending,
                outcome=record.outcome, winner_index=record.winner_index,
                challenger_win=record.winner_index == item["challenger_seat"] if item["policy"] != "self" else None,
                repeat_age=(tail["metadata"].get("retrieval_attempts") or [{}])[-1].get("actual_age_moves")))
            # Replay a stratified sample, including every setting/policy/opening/seat.
            if item["trial"] == 0:
                replay = runner.run(*players(item), opening_kana=item["opening"], match_id=record.match_id)
                assert replay.to_dict()["turns"] == data["turns"], "Non-deterministic replay"
            if (i + 1) % 24 == 0:
                print(f"Completed {i + 1}/{len(schedule)}", flush=True)
    finally:
        referee.close()
    (output / "observations.jsonl").write_text("".join(json.dumps(g, ensure_ascii=False) + "\n" for g in observations))
    groups = defaultdict(list)
    for game in observations:
        groups[game["setting"], game["policy"]].append(game)
    summary = []
    for (setting, policy), games in groups.items():
        lengths = sorted(g["valid_words"] for g in games)
        summary.append(dict(setting=setting, policy=policy, games=len(games),
            wins=sum(g["challenger_win"] is True for g in games),
            mean=statistics.mean(lengths), median=statistics.median(lengths),
            minimum=min(lengths), maximum=max(lengths),
            endings=dict(Counter(g["ending"] for g in games)),
            win_by={str(n): sum(g["challenger_win"] is True and g["valid_words"] <= n for g in games) for n in (25,50,100)},
            lengths=lengths))
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    lines = ["Memory baseline validation (offline; not human-calibrated)",
             "setting / policy / wins / games / mean / median / range / wins by 50 words"]
    for s in summary:
        lines.append(f"{s['setting']} / {s['policy']} / {s['wins']} / {s['games']} / {s['mean']:.1f} / {s['median']:g} / {s['minimum']}-{s['maximum']} / {s['win_by']['50']}")
    lines += [f"Replays checked: {sum(i['trial'] == 0 for i in schedule)}", f"Results: {output}"]
    (output / "summary.txt").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    assert not any(g["outcome"] in {"PLAYER_ERROR", "TURN_LIMIT_DRAW"} for g in observations)


if __name__ == "__main__":
    main()
