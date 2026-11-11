import unittest

from shiritori_bench.bots import VocabularyGraph, Word
from shiritori_bench.cognitive_bot import CognitiveBot, recognition_probability
from shiritori_bench.players import BotPlayer, TurnContext


def fixture(**options):
    words = [Word(w, w[0], w[-1], True) for w in ("かさ", "かき", "かん")]
    return CognitiveBot(VocabularyGraph(words), {"かさ": 1e10, "かき": 1, "かん": 1e12}, **options)


class CognitiveBotTests(unittest.TestCase):
    def test_recent_words_are_recognized_reliably(self):
        self.assertEqual(recognition_probability(12), 1)
        self.assertAlmostEqual(recognition_probability(52), 0.6)
        self.assertAlmostEqual(recognition_probability(10000), 0.2)

    def test_recall_does_not_prefilter_used_words(self):
        result = fixture(profile="recall", attempts=1).analyze("か", ("かさ",))
        self.assertIsNone(result.word)
        self.assertEqual(result.stop_reason, "retrieval_budget_exhausted")
        self.assertEqual(result.attempts[0]["word"], "かさ")

    def test_recall_can_search_past_remembered_words(self):
        result = fixture(profile="recall", attempts=2).analyze("か", ("かさ",))
        self.assertEqual(result.word, "かき")
        self.assertEqual(len(result.attempts), 2)

    def test_forgotten_repeat_is_submitted_not_oracle_filtered(self):
        bot = fixture(profile="memory", recent=0, half_life=0.0001, floor=0)
        result = bot.analyze("か", ("かさ",))
        self.assertEqual(result.word, "かさ")
        self.assertFalse(result.attempts[0]["recognized_as_used"])

    def test_perfect_recent_memory_prevents_repeat(self):
        result = fixture(profile="memory").analyze("か", ("かさ",))
        self.assertEqual(result.word, "かき")

    def test_memory_only_has_no_retrieval_cap(self):
        result = fixture(profile="memory", attempts=1).analyze("か", ("かさ",))
        self.assertEqual(result.word, "かき")
        self.assertEqual(len(result.attempts), 2)

    def test_recognition_checks_are_not_retried_within_turn(self):
        result = fixture(profile="recall", attempts=100).analyze("か", ("かさ", "かき"))
        self.assertEqual(len(result.attempts), 2)
        self.assertEqual(result.stop_reason, "known_pool_exhausted")

    def test_empty_start_passes(self):
        result = fixture().analyze("ず")
        self.assertIsNone(result.word)
        self.assertEqual(result.attempts, ())

    def test_same_seed_reproduces_full_decisions(self):
        a, b = fixture(seed=19), fixture(seed=19)
        for n in (0, 10, 20, 60, 100):
            history = ("かさ",) + ("さる",) * n
            self.assertEqual(a.analyze("か", history), b.analyze("か", history))

    def test_adapter_rejects_missing_ordered_history(self):
        with self.assertRaises(ValueError):
            BotPlayer(fixture()).play(TurnContext("か", frozenset({"かさ"}), "test", 2))

    def test_invalid_parameters_rejected(self):
        for options in ({"attempts":0}, {"recent":-1}, {"half_life":0}, {"floor":1.1}, {"profile":"unknown"}):
            with self.assertRaises(ValueError):
                fixture(**options)


if __name__ == "__main__":
    unittest.main()
