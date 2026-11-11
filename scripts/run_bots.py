#!/usr/bin/env python3
"""Run one deterministic reference-bot match and append its result."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from shiritori_bench.bots import GreedyBot, SearchBot, VocabularyGraph  # noqa: E402
from shiritori_bench.match import MatchRunner  # noqa: E402
from shiritori_bench.players import BotPlayer  # noqa: E402
from shiritori_bench.referee import Referee  # noqa: E402
from shiritori_bench.results import append_jsonl  # noqa: E402


def make_bot(name: str, graph: VocabularyGraph, search_nodes: int) -> BotPlayer:
    if name == "greedy":
        return BotPlayer(GreedyBot(graph))
    if name == "search":
        return BotPlayer(SearchBot(graph, node_budget=search_nodes))
    raise ValueError(f"Unknown bot: {name}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--first", choices=("greedy", "search"), required=True)
    parser.add_argument("--second", choices=("greedy", "search"), required=True)
    parser.add_argument("--opening", required=True)
    parser.add_argument("--turn-limit", type=int, default=100)
    parser.add_argument("--search-nodes", type=int, default=10_000)
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

    graph = VocabularyGraph.from_sqlite(str(arguments.bot_vocabulary))
    first = make_bot(arguments.first, graph, arguments.search_nodes)
    second = make_bot(arguments.second, graph, arguments.search_nodes)
    referee = Referee(str(arguments.referee_vocabulary))
    try:
        runner = MatchRunner(
            referee,
            vocabulary_version="jmdict-2026-10-13-noun-v2",
            turn_limit=arguments.turn_limit,
        )
        record = runner.run(first, second, opening_kana=arguments.opening)
    finally:
        referee.close()

    append_jsonl(arguments.output, record)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
