"""Direct DeepSeek transport with bounded transient-error retries; no SDK or tools."""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from .http_retry import post_json


class DeepSeekClient:
    endpoint = "https://api.deepseek.com/chat/completions"

    def __init__(self, api_key: str, *, thinking: bool = False,
                 timeout_seconds: float = 120, max_retries: int = 2) -> None:
        if not api_key:
            raise ValueError("DEEPSEEK_API_KEY is required")
        self.api_key = api_key
        self.thinking = thinking
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries

    def complete(self, *, model: str, messages: list[dict[str, str]],
                 temperature: float = 0, max_completion_tokens: int = 4096,
                 reasoning_effort: str | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model, "messages": messages,
            "max_tokens": max_completion_tokens,
            "thinking": {"type": "enabled" if self.thinking else "disabled"},
        }
        if self.thinking:
            if reasoning_effort is not None:
                if reasoning_effort not in {"low", "high", "max"}:
                    raise ValueError("Thinking effort must be low, high, or max")
                payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = temperature
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"}, method="POST",
        )
        raw = post_json(request, timeout=self.timeout_seconds, max_retries=self.max_retries)
        raw["provider"] = "deepseek"
        raw["latency_seconds"] = raw["transport"]["latency_seconds"]
        return raw
