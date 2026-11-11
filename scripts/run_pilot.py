#!/usr/bin/env python3
"""Small balanced pilot with per-turn journals and isolated run directories."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.factory import configured_player
from shiritori_bench.match import MatchRunner
from shiritori_bench.referee import Referee
from shiritori_bench.results import append_jsonl
from shiritori_bench.transcript import render_games
from shiritori_bench.frequency import INDEX_PATH


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=PROJECT_ROOT / "config/pilot-deepseek.json")
    parser.add_argument("--limit", type=int, default=2,
                        help="Number of games; defaults to a swapped-order smoke pair")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule without credentials or writes")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    specs = config["players"]
    if len(specs) < 2 or len({p["id"] for p in specs}) != len(specs):
        parser.error("At least two players with unique IDs are required")
    if not config["openings"] or config["turn_limit"] < 1 or args.limit < 1:
        parser.error("Openings, turn limit, and game limit must be positive")
    schedule = [
        {"first": first["id"], "second": second["id"], "opening": opening}
        for left, right in itertools.combinations(specs, 2)
        for opening in config["openings"]
        for first, second in ((left, right), (right, left))
    ][:args.limit]
    if len(schedule) % 2:
        parser.error("Use an even game limit to preserve swapped-order pairs")
    specs_by_id = {p["id"]: p for p in specs}
    retry_policy = {}
    for spec in specs:
        if spec['provider'] == 'bot':
            continue
        count = spec.get('max_retries', 2)
        if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 2:
            parser.error('max_retries must be an integer from 0 to 2')
        retry_policy[spec['id']] = {'max_retries': count, 'max_attempts_per_turn': 1 + count}
    maximum_model_attempts = sum(
        ((config['turn_limit'] + 1 - seat) // 2) * retry_policy[player_id]['max_attempts_per_turn']
        for game in schedule for seat, player_id in enumerate((game['first'], game['second']))
        if player_id in retry_policy)
    print(json.dumps({"games": len(schedule),
                      "maximum_turn_requests": len(schedule) * config["turn_limit"],
                      "maximum_model_http_attempts_including_retries": maximum_model_attempts,
                      "retry_policy": retry_policy,
                      "schedule": schedule}, ensure_ascii=False, indent=2))
    if args.dry_run:
        return
    prompt = PROJECT_ROOT / "prompts/player.txt"
    vocabulary = PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite"
    def fresh_player(player_id):
        return configured_player(specs_by_id[player_id], prompt_path=prompt,
               bot_vocabulary=PROJECT_ROOT / "data/processed/bot-vocabulary.sqlite")
    # Validate every spec before creating a run or making a paid request.
    for spec in specs:
        fresh_player(spec["id"])
    referee = Referee(str(vocabulary))
    try:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        destination = args.output_dir or PROJECT_ROOT / "results/pilots" / run_id
        destination.mkdir(parents=True, exist_ok=False)
        manifest = {"config": config, "schedule": schedule,
                    "retry_policy": retry_policy,
                    "prompt": prompt.read_text(encoding="utf-8"),
                    "prompt_sha256": digest(prompt), "vocabulary_sha256": digest(vocabulary),
                    "started_at": datetime.now(timezone.utc).isoformat()}
        manifest["frequency_index_sha256"] = digest(INDEX_PATH) if INDEX_PATH.exists() else None
        (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        runner = MatchRunner(referee, vocabulary_version=config["vocabulary_version"],
                             turn_limit=config["turn_limit"])
        records = []
        for index, game in enumerate(schedule):
            match_id = f"{run_id}-{index:03d}"
            def journal(turn):
                with (destination / "turns.jsonl").open("a", encoding="utf-8") as output:
                    output.write(json.dumps({"match_id": match_id, **asdict(turn)}, ensure_ascii=False) + "\n")
            # Reset seeded bot state for each match, including seat-swapped pairs.
            record = runner.run(fresh_player(game["first"]), fresh_player(game["second"]),
                                opening_kana=game["opening"], match_id=match_id, on_turn=journal)
            append_jsonl(destination / "matches.jsonl", record)
            records.append(record)
            (destination / "games.txt").write_text(
                render_games(r.to_dict() for r in records), encoding="utf-8")
            print(f"{index + 1}/{len(schedule)}: {record.ending}; {len(record.turns)} turns", flush=True)
            # Stop on infrastructure/truncation errors; don't spend the whole pilot
            # repeating a bad configuration or count these as competitive losses.
            if record.outcome == "PLAYER_ERROR":
                break
        summary = {
            "completed_games": len(records),
            "competitive_games": sum(r.outcome != "PLAYER_ERROR" for r in records),
            "endings": dict(Counter(r.ending for r in records)),
            "wins": dict(Counter(r.players[r.winner_index]["name"] for r in records if r.winner_index is not None)),
            "turns": sum(len(r.turns) for r in records),
            "prompt_tokens": sum(t.metadata.get("usage", {}).get("prompt_tokens", 0) for r in records for t in r.turns),
            "completion_tokens": sum(t.metadata.get("usage", {}).get("completion_tokens", 0) for r in records for t in r.turns),
            "transport_retries": sum((t.metadata.get('transport') or {}).get('retries', 0)
                for r in records for t in r.turns) + sum((r.error_metadata or {}).get('retries', 0) for r in records),
            "usage_note": "Token totals cover received responses only. Failed attempts may still be billed by the provider.",
        }
        (destination / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Results: {destination}")
        if any(r.outcome == "PLAYER_ERROR" for r in records):
            raise SystemExit("Pilot stopped after a player/infrastructure error; inspect matches.jsonl")
    finally:
        referee.close()


if __name__ == "__main__":
    main()
