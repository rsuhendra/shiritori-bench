"""Behavioral tests for the deterministic algorithmic reference players."""

from __future__ import annotations

import unittest

from shiritori_bench.bots import GameState, GreedyBot, SearchBot, VocabularyGraph, Word


def word(reading: str, start: str, end: str, *, common: bool = False) -> Word:
    return Word(reading, start, end, common)


class GreedyBotTests(unittest.TestCase):
    def test_avoids_ending_in_n(self) -> None:
        graph = VocabularyGraph(
            [
                word("かん", "か", "ん", common=True),
                word("かめ", "か", "め"),
                word("めし", "め", "し"),
            ]
        )

        self.assertEqual(GreedyBot(graph).choose(GameState("か")), "かめ")

    def test_minimizes_opponents_safe_replies(self) -> None:
        graph = VocabularyGraph(
            [
                word("かさ", "か", "さ"),
                word("かめ", "か", "め"),
                word("さる", "さ", "る"),
                word("すな", "さ", "な"),
                word("めし", "め", "し"),
            ]
        )

        self.assertEqual(GreedyBot(graph).choose(GameState("か")), "かめ")

    def test_returns_none_when_no_move_exists(self) -> None:
        graph = VocabularyGraph([word("かめ", "か", "め")])

        self.assertIsNone(GreedyBot(graph).choose(GameState("さ")))


class SearchBotTests(unittest.TestCase):
    def test_finds_a_forced_win_beyond_the_greedy_choice(self) -> None:
        # Greedy prefers かめ because it exposes one reply instead of two.
        # That line lets the opponent play めし and strand the bot on し.
        # Search sees that either response to かさ gives it a winning reply.
        graph = VocabularyGraph(
            [
                word("かめ", "か", "め", common=True),
                word("かさ", "か", "さ"),
                word("めし", "め", "し"),
                word("さる", "さ", "る"),
                word("さと", "さ", "と"),
                word("るす", "る", "す"),
                word("とり", "と", "り"),
            ]
        )
        state = GameState("か")

        greedy = GreedyBot(graph).choose(state)
        searched = SearchBot(graph, node_budget=1_000).analyze(state)

        self.assertEqual(greedy, "かめ")
        self.assertIsNotNone(searched)
        self.assertEqual(searched.word, "かさ")

    def test_tiny_budget_uses_deterministic_greedy_fallback(self) -> None:
        graph = VocabularyGraph(
            [
                word("かさ", "か", "さ"),
                word("かめ", "か", "め"),
                word("さる", "さ", "る"),
            ]
        )
        state = GameState("か")

        result = SearchBot(graph, node_budget=1).analyze(state)

        self.assertIsNotNone(result)
        self.assertEqual(result.word, GreedyBot(graph).choose(state))
        self.assertEqual(result.completed_depth, 0)
        self.assertTrue(result.budget_exhausted)


if __name__ == "__main__":
    unittest.main()
