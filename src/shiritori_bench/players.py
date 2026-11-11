"""Player adapters for bots and closed-book language models."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .bots import GameState, GreedyBot, SearchBot
from .frequency_bot import FrequencyBot
from .cognitive_bot import CognitiveBot

class CompletionClient(Protocol):
    def complete(self, *, model: str, messages: list[dict[str, str]],
                 temperature: float, max_completion_tokens: int,
                 reasoning_effort: str | None) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class TurnContext:
    required_kana: str
    used_words: frozenset[str]
    vocabulary_version: str
    turn_number: int
    history: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerResponse:
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class Player(Protocol):
    name: str
    kind: str

    def play(self, context: TurnContext) -> PlayerResponse: ...


class BotPlayer:
    kind = "algorithmic"

    def __init__(self, bot: GreedyBot | SearchBot | FrequencyBot | CognitiveBot) -> None:
        self.bot = bot
        self.name = bot.name

    def play(self, context: TurnContext) -> PlayerResponse:
        state = GameState(context.required_kana, context.used_words)
        if isinstance(self.bot, CognitiveBot):
            if set(context.history) != set(context.used_words):
                raise ValueError("CognitiveBot requires the full ordered move history")
            result = self.bot.analyze(context.required_kana, context.history)
            return PlayerResponse(result.word or "PASS", {
                "bot": self.name, "profile": self.bot.profile, "seed": self.bot.seed,
                "alpha": self.bot.alpha, "attempt_limit": self.bot.attempt_limit,
                "recent_moves": self.bot.recent, "recognition_half_life": self.bot.half_life,
                "recognition_floor": self.bot.floor, "retrieval_attempts": list(result.attempts),
                "attempts_used": len(result.attempts), "stop_reason": result.stop_reason})
        if isinstance(self.bot, FrequencyBot):
            result = self.bot.analyze(state)
            return PlayerResponse(result.word or "PASS", {
                "bot": self.name, "seed": self.bot.seed, "alpha": self.bot.alpha,
                "candidate_count": result.candidate_count,
                "selected_probability": result.selected_probability,
                "candidate_mass_per_million": result.candidate_mass_per_million,
                "baseline_vocabulary_exhausted": result.word is None})
        if isinstance(self.bot, SearchBot):
            result = self.bot.analyze(state)
            if result is None:
                return PlayerResponse("PASS", {"bot": self.name})
            return PlayerResponse(
                result.word,
                {
                    "bot": self.name,
                    "score": result.score,
                    "completed_depth": result.completed_depth,
                    "nodes": result.nodes,
                    "budget_exhausted": result.budget_exhausted,
                },
            )

        move = self.bot.choose(state)
        return PlayerResponse(move or "PASS", {"bot": self.name})


class LLMPlayer:
    kind = "llm"

    def __init__(
        self,
        *,
        name: str,
        model: str,
        client: CompletionClient,
        prompt_template: str,
        temperature: float = 0,
        max_completion_tokens: int = 16,
        reasoning_effort: str | None = "low",
    ) -> None:
        self.name = name
        self.model = model
        self.client = client
        self.prompt_template = prompt_template
        self.temperature = temperature
        self.max_completion_tokens = max_completion_tokens
        self.reasoning_effort = reasoning_effort

    @classmethod
    def from_prompt_file(
        cls,
        *,
        prompt_path: str | Path,
        **arguments: Any,
    ) -> LLMPlayer:
        template = Path(prompt_path).read_text(encoding="utf-8")
        return cls(prompt_template=template, **arguments)

    def play(self, context: TurnContext) -> PlayerResponse:
        used = "、".join(sorted(context.used_words)) or "なし"
        prompt = self.prompt_template.format(
            vocabulary_version=context.vocabulary_version,
            required_kana=context.required_kana,
            used_words=used,
        )
        raw = self.client.complete(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=self.temperature,
            max_completion_tokens=self.max_completion_tokens,
            reasoning_effort=self.reasoning_effort,
        )
        choices = raw.get("choices") or []
        if not choices:
            raise ValueError(f"Model {self.model} returned no choices")
        message = choices[0].get("message", {})
        content = message.get("content") or ""
        if not isinstance(content, str):
            raise TypeError(f"Model {self.model} returned non-text content")
        return PlayerResponse(
            content,
            {
                "model": self.model,
                "returned_model": raw.get("model"),
                "system_fingerprint": raw.get("system_fingerprint"),
                "finish_reason": choices[0].get("finish_reason"),
                "reasoning_content": message.get("reasoning_content"),
                "latency_seconds": raw.get("latency_seconds"),
                "transport": raw.get("transport"),
                "request": {
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": self.temperature,
                    "max_completion_tokens": self.max_completion_tokens,
                    "reasoning_effort": self.reasoning_effort,
                    "thinking": getattr(self.client, "thinking", None),
                },
                "provider": raw.get("provider"),
                "response_id": raw.get("id"),
                "usage": raw.get("usage", {}),
            },
        )
