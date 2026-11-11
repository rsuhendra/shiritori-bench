import json
import unittest

from shiritori_bench.public_site import build_public_payload


def turn(player, name, outcome="VALID"):
    return {"turn": player + 1, "player_index": player, "player_name": name,
        "submitted": "かさ", "normalized": "かさ", "outcome": outcome,
        "required_kana": "か", "next_required_kana": "さ",
        "metadata": {"model": "deepseek-test", "request": {"thinking": True,
            "reasoning_effort": "low", "messages": ["PRIVATE PROMPT"]},
            "reasoning_content": "SECRET REASONING", "response_id": "PRIVATE-ID",
            "latency_seconds": 1, "usage": {"completion_tokens": 10}}}


class PublicExportTests(unittest.TestCase):
    def record(self):
        return {"match_id": "test", "started_at": "2026-10-16", "opening_kana": "か",
            "players": [{"name": "thinking A"}, {"name": "thinking B"}],
            "winner_index": 0, "loser_index": 1, "outcome": "PLAYER_ONE_WIN",
            "ending": "INVALID_WORD", "vocabulary_version": "test",
            "turns": [turn(0, "thinking A"), turn(1, "thinking B", "INVALID_WORD")]}

    def payload(self, records):
        return build_public_payload(records, {}, {}, {}, glossary=lambda word: "test gloss")

    def test_aliases_merge_and_selfplay_is_disclosed(self):
        p = self.payload([self.record()])
        self.assertEqual(len(p["models"]), 1)
        self.assertTrue(p["games"][0]["same_configuration"])
        self.assertEqual(p["models"][0]["appearances"], 2)
        self.assertEqual(p["models"][0]["wins"], 1)
        self.assertEqual(p["models"][0]["losses"], 1)
        self.assertEqual(p["summary"]["validity"], 0.5)

    def test_export_does_not_contain_requests_or_reasoning(self):
        data = json.dumps(self.payload([self.record()]))
        for private in ("PRIVATE PROMPT", "SECRET REASONING", "PRIVATE-ID", "reasoning_content", "messages"):
            self.assertNotIn(private, data)

    def test_infrastructure_failure_never_counts_as_a_loss(self):
        record = self.record()
        record.update(outcome="PLAYER_ERROR", ending="GENERATION_ERROR:length")
        p = self.payload([record])
        self.assertEqual(p["summary"]["completed_games"], 0)
        self.assertEqual(p["summary"]["excluded_games"], 1)
        self.assertEqual(p["models"], [])


if __name__ == "__main__":
    unittest.main()
