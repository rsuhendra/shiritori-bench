"""Mathematical checks for alternating values, word removal, and diagnostics."""

import unittest

from shiritori_bench.move_quality import MoveAnalyzer, discounted_values, rank_correlation


def fixture(words, **options):
    rows = [{"reading": word, "start_kana": word[0], "end_kana": word[-1], "common": 1}
            for word, _ in words]
    index = {"source_id": "tubelex", "readings": {word: {"tubelex": {
        "count": frequency, "count_upper": frequency,
        "per_million": frequency, "per_million_upper": frequency}}
        for word, frequency in words if frequency is not None}}
    return MoveAnalyzer(rows, index, **options)


class DiscountedValueTests(unittest.TestCase):
    def test_two_node_cycle_has_expected_alternating_signs(self):
        values, _, residual = discounted_values([[0, 1], [1, 0]], [1, 3], 0.5)
        self.assertAlmostEqual(values[0], (-1 + 0.5 * 3) / (1 - 0.5 ** 2))
        self.assertAlmostEqual(values[1], -3 - 0.5 * values[0])
        self.assertLess(residual, 1e-12)

    def test_three_step_chain_and_dead_end(self):
        values, _, _ = discounted_values([[0, 1, 0], [0, 0, 1], [0, 0, 0]], [1, 2, 4], 0.5)
        self.assertAlmostEqual(values[0], -1 + 0.5 * 2 - 0.25 * 4)
        self.assertAlmostEqual(values[2], -4)

    def test_no_discount_is_immediate_pressure(self):
        values, _, _ = discounted_values([[1]], [3], 0)
        self.assertEqual(values, [-3])

    def test_one_node_self_loop(self):
        values, _, _ = discounted_values([[1]], [3], 0.9)
        self.assertAlmostEqual(values[0], -3 / 1.9)

    def test_gamma_one_is_rejected(self):
        with self.assertRaises(ValueError):
            discounted_values([[1]], [1], 1)


class MoveQualityTests(unittest.TestCase):
    def test_rank_one_updates_match_full_recomputation(self):
        analyzer = fixture([("かさ", 20), ("かか", 5), ("さか", 10), ("ささ", 2),
                            ("さる", None), ("るか", 1)], gammas=(0, 0.5, 0.95))
        before = analyzer.snapshot()
        for word in analyzer.words.values():
            predicted = before.candidate_values(word)
            after = analyzer.snapshot([word["reading"]])
            j = analyzer.positions[word["end_kana"]]
            for gamma in predicted:
                self.assertAlmostEqual(predicted[gamma], after.solutions[gamma][0][j], places=9)

    def test_removing_only_candidate_creates_empty_row(self):
        analyzer = fixture([("かか", 10)], gammas=(0.85,))
        word = analyzer.words["かか"]
        self.assertAlmostEqual(analyzer.snapshot().candidate_values(word)["0.85"], 0)

    def test_used_words_and_fatal_words_are_excluded_from_safe_pool(self):
        analyzer = fixture([("かさ", 20), ("かん", 100), ("かき", 5)])
        position = analyzer.snapshot(["かさ"])
        stats = position.kana_measures("か")
        self.assertEqual(stats["safe_replies"], 1)
        self.assertEqual(stats["frequency_mass_per_million"], 5)
        self.assertAlmostEqual(stats["n_trap_frequency_share"], 100 / 105)

    def test_structural_measures_and_self_return(self):
        stats = fixture([("かか", 1), ("かさ", 1), ("さか", 1)]).snapshot().kana_measures("か")
        self.assertEqual(stats["attack_sustainability_count_ratio"], 1)
        self.assertEqual(stats["attack_accessibility"], 2)
        self.assertEqual(stats["self_return_count"], 1)
        self.assertAlmostEqual(stats["self_return_probability"], 0.5)

    def test_immediate_loss_has_no_strategy_score(self):
        result = fixture([("かん", 20)]).snapshot().score_move("かん", "か")
        self.assertEqual(result["legality"], "ENDS_IN_N")
        self.assertIsNone(result["strategy"])

    def test_two_ply_reply_is_removed_before_counting_own_options(self):
        result = fixture([("かさ", 5), ("ささ", 10)]).snapshot().score_move("かさ", "か")
        self.assertEqual(result["two_ply"]["probability_own_covered_pool_empty"], 1)
        self.assertEqual(result["two_ply"]["expected_own_covered_replies"], 0)
        for value in result["alternatives"].values():
            self.assertEqual(value["midrank_percentile"], 50)

    def test_missing_frequency_is_not_zero_dictionary_options(self):
        stats = fixture([("かさ", None)]).snapshot().kana_measures("か")
        self.assertEqual(stats["safe_replies"], 1)
        self.assertEqual(stats["covered_safe_replies"], 0)
        self.assertTrue(stats["unsupported_by_frequency_model"])

    def test_finite_horizon_matches_one_and_two_step_formula(self):
        analyzer = fixture([("かさ", 5), ("さか", 10), ("かか", 2)], gammas=(0.5,))
        result = analyzer.snapshot().score_move("かさ", "か")
        after = analyzer.snapshot(["かさ"])
        j = analyzer.positions["さ"]
        finite = result["lookahead"]["0.5"]["finite_horizons"]
        self.assertAlmostEqual(finite["1"], -after.r[j])
        self.assertAlmostEqual(finite["2"], -after.r[j] + 0.5 * sum(p * r for p, r in zip(after.p[j], after.r)))

    def test_rank_correlation_with_ties(self):
        self.assertAlmostEqual(rank_correlation([1, 1, 3], [2, 2, 4]), 1)
        self.assertAlmostEqual(rank_correlation([1, 2, 3], [3, 2, 1]), -1)
        self.assertIsNone(rank_correlation([1, 1], [1, 2]))


if __name__ == "__main__":
    unittest.main()
