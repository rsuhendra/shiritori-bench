import random
import unittest

from shiritori_bench.bots import GameState, VocabularyGraph, Word
from shiritori_bench.frequency_bot import FrequencyBot, build_frequency_vocabulary
from shiritori_bench.players import BotPlayer, TurnContext


def words():
    return [Word(w, w[0], w[-1], True) for w in ("かさ", "かき", "かん", "かく")]


class FrequencyBotTests(unittest.TestCase):
    def bot(self, seed=1, **options):
        return FrequencyBot(VocabularyGraph(words()), {"かさ": 9, "かき": 1, "かん": 1000}, seed=seed, **options)

    def test_same_seed_and_states_reproduce_moves(self):
        a, b = self.bot(), self.bot()
        self.assertEqual([a.choose(GameState("か")) for _ in range(100)],
                         [b.choose(GameState("か")) for _ in range(100)])

    def test_empirical_sampling_agrees_with_frequency_weights(self):
        bot = self.bot(seed=34)
        rate = sum(bot.choose(GameState("か")) == "かさ" for _ in range(5000)) / 5000
        self.assertAlmostEqual(rate, 0.9, delta=0.02)

    def test_fatal_and_unmeasured_words_are_never_selected(self):
        bot = self.bot()
        self.assertEqual(bot.vocabulary.remaining_word_count(frozenset()), 2)
        self.assertEqual(bot.choose(GameState("か", frozenset({"かさ"}))), "かき")
        self.assertIsNone(bot.choose(GameState("か", frozenset({"かさ", "かき"}))))

    def test_no_rescue_from_full_dictionary(self):
        response = BotPlayer(self.bot()).play(TurnContext("か", frozenset({"かさ", "かき"}), "test", 3))
        self.assertEqual(response.text, "PASS")
        self.assertTrue(response.metadata["baseline_vocabulary_exhausted"])

    def test_global_rng_unchanged(self):
        state = random.getstate()
        self.bot().choose(GameState("か"))
        self.assertEqual(random.getstate(), state)

    def test_row_order_does_not_affect_sampling(self):
        a = self.bot()
        b = FrequencyBot(VocabularyGraph(reversed(words())), {"かき": 1, "かさ": 9}, seed=1)
        self.assertEqual([a.choose(GameState("か")) for _ in range(50)],
                         [b.choose(GameState("か")) for _ in range(50)])

    def test_alpha_zero_means_uniform(self):
        bot = self.bot(alpha=0)
        self.assertEqual(bot.analyze(GameState("か")).selected_probability, 0.5)

    def test_invalid_alpha_rejected(self):
        for alpha in (-1, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                self.bot(alpha=alpha)

    def test_ambiguity_and_threshold_policies(self):
        def entry(f, upper):
            return {"tubelex": {"count": f, "count_upper": upper,
                "per_million": f, "per_million_upper": upper}}
        index = {"source_id": "tubelex", "readings": {"かさ": entry(5, 10), "かき": entry(0.5, 0.5)}}
        _, selected, excluded = build_frequency_vocabulary(words(), index)
        self.assertEqual(selected, {})
        self.assertEqual(excluded, {"ambiguous": 1, "below_threshold_or_zero": 1, "ends_in_n": 1, "unmatched": 1})
        _, selected, _ = build_frequency_vocabulary(words(), index, policy="lower")
        self.assertEqual(selected, {"かさ": 5})


if __name__ == "__main__":
    unittest.main()
