#!/usr/bin/env python3
"""Run one model-or-bot match using the shared deterministic referee."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.bots import GreedyBot, SearchBot, VocabularyGraph  # noqa: E402
from shiritori_bench.match import MatchRunner  # noqa: E402
from shiritori_bench.openrouter import OpenRouterClient  # noqa: E402
from shiritori_bench.players import BotPlayer, LLMPlayer, Player  # noqa: E402
from shiritori_bench.referee import Referee  # noqa: E402
from shiritori_bench.results import append_jsonl  # noqa: E402


def load_model_config(path: Path) -> tuple[dict, dict[str, dict]]:
    config = json.loads(path.read_text(encoding="utf-8"))
    return config["defaults"], {model["id"]: model for model in config["models"]}


def create_player(
    specification: str,
    *,
    graph: VocabularyGraph,
    search_nodes: int,
    defaults: dict,
    models: dict[str, dict],
    client: OpenRouterClient | None,
    prompt_path: Path,
) -> Player:
    if specification == "greedy":
        return BotPlayer(GreedyBot(graph))
    if specification == "search":
        return BotPlayer(SearchBot(graph, node_budget=search_nodes))
    if not specification.startswith("model:"):
        raise ValueError("Player must be greedy, search, or model:<OpenRouter ID>")

    model_id = specification.removeprefix("model:")
    if model_id not in models:
        raise ValueError(f"Model is not configured: {model_id}")
    if client is None:
        raise ValueError("OPENROUTER_API_KEY is required for model players")
    model = models[model_id]
    return LLMPlayer.from_prompt_file(
        name=model["label"],
        model=model_id,
        client=client,
        prompt_path=prompt_path,
        temperature=defaults.get("temperature", 0),
        max_completion_tokens=defaults.get("max_completion_tokens", 16),
        reasoning_effort=model.get(
            "reasoning_effort", defaults.get("reasoning_effort")
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", required=True)
    parser.add_argument("--second", required=True)
    parser.add_argument("--opening", required=True)
    parser.add_argument("--turn-limit", type=int, default=100)
    parser.add_argument("--search-nodes", type=int, default=10_000)
    parser.add_argument(
        "--models", type=Path, default=PROJECT_ROOT / "config/models.json"
    )
    parser.add_argument(
        "--prompt", type=Path, default=PROJECT_ROOT / "prompts/player.txt"
    )
    parser.add_argument(
        "--bot-vocabulary",
        type=Path,
        default=PROJECT_ROOT / "data/processed/bot-vocabulary.sqlite",
    )
    parser.add_argument(
        "--referee-vocabulary",
        type=Path,
        default=PROJECT_ROOT / "data/processed/referee-vocabulary.sqlite",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=PROJECT_ROOT / "results/raw/matches.jsonl",
    )
    arguments = parser.parse_args()

    defaults, models = load_model_config(arguments.models)
    needs_api = arguments.first.startswith("model:") or arguments.second.startswith(
        "model:"
    )
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    client = OpenRouterClient(api_key) if needs_api else None
    graph = VocabularyGraph.from_sqlite(str(arguments.bot_vocabulary))
    common = {
        "graph": graph,
        "search_nodes": arguments.search_nodes,
        "defaults": defaults,
        "models": models,
        "client": client,
        "prompt_path": arguments.prompt,
    }
    first = create_player(arguments.first, **common)
    second = create_player(arguments.second, **common)

    referee = Referee(str(arguments.referee_vocabulary))
    try:
        record = MatchRunner(
            referee,
            vocabulary_version="jmdict-2026-10-13-noun-v2",
            turn_limit=arguments.turn_limit,
        ).run(first, second, opening_kana=arguments.opening)
    finally:
        referee.close()

    append_jsonl(arguments.output, record)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
