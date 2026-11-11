"""Append-only result storage and website aggregation."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from .match import MatchRecord


def append_jsonl(path: str | Path, record: MatchRecord) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("a", encoding="utf-8") as output:
        output.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as source:
        return [json.loads(line) for line in source if line.strip()]


def aggregate_for_web(
    matches: Iterable[dict[str, Any]],
    *,
    vocabulary_version: str,
) -> dict[str, Any]:
    records = [match for match in matches if match.get("outcome") != "PLAYER_ERROR"]
    stats: dict[str, dict[str, float]] = defaultdict(
        lambda: {"matches": 0, "wins": 0, "draws": 0, "moves": 0, "valid": 0, "cost": 0}
    )
    player_kinds: dict[str, str] = {}
    ratings: dict[str, float] = defaultdict(lambda: 1500.0)

    for match in records:
        for index, player in enumerate(match["players"]):
            name = player["name"]
            player_kinds[name] = player["kind"]
            stats[name]["matches"] += 1
            if match.get("winner_index") == index:
                stats[name]["wins"] += 1
            if match.get("winner_index") is None:
                stats[name]["draws"] += 1

        for turn in match.get("turns", []):
            name = turn["player_name"]
            stats[name]["moves"] += 1
            if turn["outcome"] in {"VALID", "ENDS_IN_N"}:
                stats[name]["valid"] += 1
            usage = turn.get("metadata", {}).get("usage", {})
            stats[name]["cost"] += float(usage.get("cost") or 0)

        left = match["players"][0]["name"]
        right = match["players"][1]["name"]
        expected_left = 1 / (1 + 10 ** ((ratings[right] - ratings[left]) / 400))
        winner = match.get("winner_index")
        actual_left = 0.5 if winner is None else float(winner == 0)
        change = 20 * (actual_left - expected_left)
        ratings[left] += change
        ratings[right] -= change

    models = []
    for name, values in sorted(stats.items()):
        matches_played = int(values["matches"])
        moves = int(values["moves"])
        score = values["wins"] + 0.5 * values["draws"]
        kind = player_kinds[name]
        models.append(
            {
                "name": name,
                "lab": "Algorithmic" if kind == "algorithmic" else "Model",
                "track": "algorithmic" if kind == "algorithmic" else "standard",
                "rating": round(ratings[name], 1),
                "win_rate": score / matches_played if matches_played else 0,
                "valid_move_rate": values["valid"] / moves if moves else 0,
                "cost_per_match_usd": values["cost"] / matches_played if matches_played else 0,
            }
        )

    total_moves = sum(len(match.get("turns", [])) for match in records)
    valid_moves = sum(
        turn["outcome"] in {"VALID", "ENDS_IN_N"}
        for match in records
        for turn in match.get("turns", [])
    )
    recent = records[-12:]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_sample_data": False,
        "summary": {
            "models": len(stats),
            "matches": len(records),
            "valid_move_rate": valid_moves / total_moves if total_moves else 0,
            "vocabulary": vocabulary_version,
        },
        "models": models,
        "matches": [
            {
                "opening": match["opening_kana"],
                "status": "draw" if match.get("winner_index") is None else "complete",
                "player_one": match["players"][0]["name"],
                "player_one_result": _player_result(match, 0),
                "player_two": match["players"][1]["name"],
                "player_two_result": _player_result(match, 1),
                "turns": len(match.get("turns", [])),
                "ending": match["ending"],
            }
            for match in reversed(recent)
        ],
    }


def _player_result(match: dict[str, Any], index: int) -> str:
    winner = match.get("winner_index")
    if winner is None:
        return "draw"
    return "winner" if winner == index else "loss"


def write_web_results(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
