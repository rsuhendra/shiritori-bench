"""Configuration-driven players sharing the same match interface."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .bots import GreedyBot, SearchBot, VocabularyGraph
from .deepseek import DeepSeekClient
from .openrouter import OpenRouterClient
from .players import BotPlayer, LLMPlayer, Player
from .frequency_bot import load_frequency_vocabulary, FrequencyBot
from .cognitive_bot import CognitiveBot


def configured_player(config: dict[str, Any], *, prompt_path: Path,
                      bot_vocabulary: Path) -> Player:
    provider = config["provider"]
    if provider == "bot":
        if config["model"] in {"frequency", "memory"}:
            root = bot_vocabulary.resolve().parents[2]
            graph, frequencies, _ = load_frequency_vocabulary(
                root / "data/processed/referee-vocabulary.sqlite",
                root / "data/processed/word-frequency.json",
                threshold=config.get("threshold", 1), policy=config.get("frequency_policy", "unambiguous"))
            options = {"seed": config.get("seed", 17), "alpha": config.get("alpha", 1)}
            bot = (FrequencyBot(graph, frequencies, **options) if config["model"] == "frequency" else
                   CognitiveBot(graph, frequencies, profile="memory", **options,
                       recent=config.get("recent", 12), half_life=config.get("half_life", 40),
                       floor=config.get("floor", .2)))
            player = BotPlayer(bot)
            player.name = config.get("label", player.name)
            return player
        graph = VocabularyGraph.from_sqlite(str(bot_vocabulary))
        if config["model"] == "greedy":
            return BotPlayer(GreedyBot(graph))
        if config["model"] == "search":
            return BotPlayer(SearchBot(graph, node_budget=config.get("node_budget", 10000)))
        raise ValueError("Unknown bot model")
    if provider == "deepseek":
        client = DeepSeekClient(os.environ.get("DEEPSEEK_API_KEY", ""),
                                thinking=config.get("thinking", False),
                                max_retries=config.get("max_retries", 2))
    elif provider == "openrouter":
        client = OpenRouterClient(os.environ.get("OPENROUTER_API_KEY", ""),
                                  max_retries=config.get("max_retries", 2))
    else:
        raise ValueError(f"Unsupported provider: {provider}")
    return LLMPlayer.from_prompt_file(
        name=config.get("label", config["id"]), model=config["model"],
        client=client, prompt_path=prompt_path,
        temperature=config.get("temperature", 0),
        max_completion_tokens=config.get("max_completion_tokens", 4096),
        reasoning_effort=config.get("reasoning_effort"),
    )
