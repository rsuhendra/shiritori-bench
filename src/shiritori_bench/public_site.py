"""Allowlisted, dependency-free exports for the public static site.

Never publish raw match metadata: it includes requests and private reasoning.
Player aliases are merged by recorded model and thinking configuration, so
thinking A/B are not presented as separate model capabilities.
"""

from collections import Counter
from datetime import datetime, timezone
import statistics

from .transcript import ending_description, english_meaning, romanize


def configuration(turn):
    metadata = turn.get("metadata", {})
    request = metadata.get("request", {})
    return (metadata.get("model", turn["player_name"]),
            request.get("thinking"), request.get("reasoning_effort"))


def build_public_payload(records, frequency_index, analysis, diagnostics, *, glossary=english_meaning):
    configurations, models, games = {}, {}, []
    failures = Counter()
    accepted = submissions = completion_tokens = 0
    competitive = [m for m in records if m["outcome"] != "PLAYER_ERROR"]
    excluded = [m for m in records if m["outcome"] == "PLAYER_ERROR"]
    for match in competitive:
        player_ids = []
        for player_index, player in enumerate(match["players"]):
            observed = next((t for t in match["turns"] if t["player_index"] == player_index), None)
            key = configuration(observed) if observed else (player["name"], None, None)
            if key not in configurations:
                identifier = f"configuration-{len(configurations) + 1}"
                configurations[key] = identifier
                models[identifier] = {"id": identifier, "model": key[0], "name": "DeepSeek Flash"
                    if "deepseek" in str(key[0]).lower() else key[0],
                    "thinking": key[1], "reasoning_effort": key[2],
                    "mode": f"Thinking · {key[2] or 'default'}" if key[1] else "Non-thinking" if key[1] is False else "Unspecified",
                    "appearances": 0, "wins": 0, "losses": 0,
                    "submissions": 0, "valid_moves": 0, "completion_tokens": 0,
                    "failure_counts": {}, "latencies": []}
            identifier = configurations[key]
            player_ids.append(identifier)
            model = models[identifier]
            model["appearances"] += 1
            model["wins"] += int(match.get("winner_index") == player_index)
            model["losses"] += int(match.get("loser_index") == player_index)
        turns = []
        for turn in match["turns"]:
            metadata = turn.get("metadata", {})
            usage = metadata.get("usage", {})
            count = usage.get("completion_tokens", 0) or 0
            word = turn.get("normalized") or turn.get("submitted", "")
            estimate = frequency_index.get("readings", {}).get(word, {}).get("tubelex")
            model = models[player_ids[turn["player_index"]]]
            model["submissions"] += 1
            model["valid_moves"] += int(turn["outcome"] == "VALID")
            model["completion_tokens"] += count
            if isinstance(metadata.get("latency_seconds"), (int, float)):
                model["latencies"].append(metadata["latency_seconds"])
            if turn["outcome"] != "VALID":
                failures[turn["outcome"]] += 1
                model["failure_counts"][turn["outcome"]] = model["failure_counts"].get(turn["outcome"], 0) + 1
            turns.append({"turn": turn["turn"], "player_index": turn["player_index"],
                "word": turn["submitted"], "romanization": romanize(turn["submitted"]),
                "meaning": glossary(word), "required_kana": turn["required_kana"],
                "next_kana": turn.get("next_required_kana"), "outcome": turn["outcome"],
                "frequency": {"lower": estimate["per_million"], "upper": estimate["per_million_upper"]}
                    if estimate else None,
                "completion_tokens": count, "latency_seconds": metadata.get("latency_seconds")})
            accepted += int(turn["outcome"] == "VALID")
            submissions += 1
            completion_tokens += count
        games.append({"id": match["match_id"], "date": match["started_at"],
            "opening": match["opening_kana"], "players": player_ids,
            "player_labels": [p["name"] for p in match["players"]],
            "same_configuration": player_ids[0] == player_ids[1],
            "winner_index": match.get("winner_index"), "ending": match["ending"],
            "ending_description": ending_description(match), "turns": turns})
    for model in models.values():
        model["validity"] = model["valid_moves"] / model["submissions"] if model["submissions"] else None
        latencies = model.pop("latencies")
        model["median_latency_seconds"] = statistics.median(latencies) if latencies else None
    reference = next((p for p in analysis.get("profiles", [])
        if p["threshold"] == analysis["settings"]["threshold"] and p["transform"] == "log"), None)
    return {"schema_version": 2, "generated_at": datetime.now(timezone.utc).isoformat(),
        "is_sample_data": False,
        "summary": {"configurations": len(models), "completed_games": len(games),
            "excluded_games": len(excluded), "valid_moves": accepted, "submissions": submissions,
            "validity": accepted / submissions if submissions else None,
            "completion_tokens": completion_tokens,
            "openings": sorted({m["opening_kana"] for m in competitive}),
            "vocabulary_version": competitive[0]["vocabulary_version"] if competitive else None,
            "last_match_at": max((m["started_at"] for m in competitive), default=None)},
        "models": list(models.values()), "games": games,
        "failures": dict(failures),
        "excluded": [{"id": m["match_id"], "reason": ending_description(m)} for m in excluded],
        "atlas": {"threshold": analysis.get("settings", {}).get("threshold"),
            "alpha": analysis.get("settings", {}).get("alpha"),
            "gammas": analysis.get("settings", {}).get("gammas", []),
            "kana": reference["kana"] if reference else []},
        "diagnostics": {key: diagnostics[key] for key in
            ("mixing", "log_depth_decomposition", "linear_depth_decomposition", "saved_game_audit")
            if key in diagnostics},
        "licenses": {"dictionary": "JMdict / EDRDG · CC BY-SA 4.0",
            "frequency": "TUBELEX · BSD-3-Clause"}}
