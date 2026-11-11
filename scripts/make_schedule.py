#!/usr/bin/env python3
"""Create a deterministic balanced match manifest without making API calls."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.schedule import round_robin_schedule  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", type=Path, default=PROJECT_ROOT / "config/models.json")
    parser.add_argument("--experiment", type=Path, default=PROJECT_ROOT / "config/experiment.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "results/schedule.json")
    arguments = parser.parse_args()
    model_config = json.loads(arguments.models.read_text(encoding="utf-8"))
    experiment = json.loads(arguments.experiment.read_text(encoding="utf-8"))
    players = [
        f"model:{model['id']}"
        for model in model_config["models"]
        if model.get("enabled", False)
    ]
    players.extend(experiment.get("include_algorithmic_players", []))
    schedule = round_robin_schedule(
        players, experiment["opening_kana"], repetitions=experiment["repetitions"]
    )
    payload = {
        "schema_version": 1,
        "vocabulary_version": experiment["vocabulary_version"],
        "turn_limit": experiment["turn_limit"],
        "search_nodes": experiment["search_nodes"],
        "matches": [asdict(match) | {"match_id": match.match_id} for match in schedule],
    }
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote {len(schedule)} matches to {arguments.output}")


if __name__ == "__main__":
    main()
