"""Offline transport contract tests; never contact the provider."""

import json
import unittest
from unittest.mock import MagicMock, patch

from shiritori_bench.deepseek import DeepSeekClient
from shiritori_bench.players import LLMPlayer, TurnContext


class DeepSeekTests(unittest.TestCase):
    def request_payload(self, thinking):
        response = MagicMock()
        response.read.return_value = b'{"choices": [{"message": {"content": "word"}}]}'
        with patch("urllib.request.urlopen") as transport:
            transport.return_value.__enter__.return_value = response
            raw = DeepSeekClient("test-key", thinking=thinking).complete(
                model="deepseek-flash", messages=[{"role": "user", "content": "test"}],
                temperature=0, max_completion_tokens=4096, reasoning_effort="low")
            request = transport.call_args.args[0]
        self.assertEqual(raw["provider"], "deepseek")
        self.assertIn("latency_seconds", raw)
        return json.loads(request.data)

    def test_thinking_request_has_budget_and_no_sampling_or_tools(self):
        payload = self.request_payload(True)
        self.assertEqual(payload["thinking"], {"type": "enabled"})
        self.assertEqual(payload["reasoning_effort"], "low")
        self.assertEqual(payload["max_tokens"], 4096)
        self.assertNotIn("temperature", payload)
        self.assertNotIn("tools", payload)
        self.assertNotIn("max_completion_tokens", payload)

    def test_non_thinking_request_disables_default_thinking(self):
        payload = self.request_payload(False)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertEqual(payload["temperature"], 0)
        self.assertNotIn("reasoning_effort", payload)

    def test_reasoning_never_becomes_submitted_word(self):
        client = MagicMock()
        client.complete.return_value = {"model": "returned-model", "choices": [{
            "finish_reason": "stop", "message": {
                "content": "かさ", "reasoning_content": "private reasoning"}}]}
        player = LLMPlayer(name="test", model="requested-model", client=client,
                           prompt_template="{required_kana}: {used_words}")
        response = player.play(TurnContext("か", frozenset(), "test", 1))
        self.assertEqual(response.text, "かさ")
        self.assertEqual(response.metadata["returned_model"], "returned-model")
        self.assertEqual(response.metadata["reasoning_content"], "private reasoning")


if __name__ == "__main__":
    unittest.main()
