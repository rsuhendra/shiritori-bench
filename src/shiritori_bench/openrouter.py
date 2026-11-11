"""Minimal standard-library OpenRouter client for text-only model turns."""

from __future__ import annotations

import json
import urllib.request
from typing import Any
from .http_retry import post_json


class OpenRouterClient:
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(self, api_key: str, *, timeout_seconds: float = 120, max_retries: int = 2) -> None:
        if not api_key:
            raise ValueError("OpenRouter API key is required")
        self.api_key = api_key
        self.timeout_seconds, self.max_retries = timeout_seconds, max_retries

    def complete(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        temperature: float = 0,
        max_completion_tokens: int = 16,
        reasoning_effort: str | None = "low",
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_completion_tokens": max_completion_tokens,
            "usage": {"include": True},
            "provider": {"allow_fallbacks": False},
        }
        if reasoning_effort is not None:
            payload["reasoning_effort"] = reasoning_effort

        request = urllib.request.Request(
            self.endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/",
                "X-Title": "ShiritoriBench",
            },
            method="POST",
        )
        raw = post_json(request, timeout=self.timeout_seconds, max_retries=self.max_retries)
        raw['provider'] = 'openrouter'
        raw['latency_seconds'] = raw['transport']['latency_seconds']
        return raw

