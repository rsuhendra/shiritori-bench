import unittest

from shiritori_bench.score_diagnostics import (
    coverage_rows, depth_decomposition, mixing_diagnostics, synthetic_index,
)
from test_move_quality import fixture


class DiagnosticTests(unittest.TestCase):
    def test_immediately_mixing_chain_has_no_later_centered_contributions(self):
        position = fixture([("かか", 1), ("かさ", 1), ("さか", 1), ("ささ", 1)], gammas=(0.99,)).snapshot()
        rows = depth_decomposition(position, 0.99, horizons=(1, 2, 8))
        self.assertEqual(rows[-1]["increment_sd"], 0)
        self.assertAlmostEqual(rows[-1]["adjacent_pair_mean_ratio"], (1 - 0.99) / (1 + 0.99))
        mixing = mixing_diagnostics([[0.5, 0.5], [0.5, 0.5]], [0, 1], depths=(0, 1))
        self.assertEqual(mixing[0]["max_pairwise_tv"], 1)
        self.assertEqual(mixing[1]["max_pairwise_tv"], 0)
        self.assertEqual(mixing[1]["mean_survival"], 1)

    def test_periodic_chain_does_not_mix(self):
        result = mixing_diagnostics([[0, 1], [1, 0]], [0, 1], depths=(0, 1, 2, 8))
        self.assertTrue(all(row["max_pairwise_tv"] == 1 for row in result))

    def test_absorbed_mass_is_not_renormalized(self):
        result = mixing_diagnostics([[0, 0], [0, 1]], [0, 1], depths=(1,))
        self.assertEqual(result[0]["max_pairwise_tv"], 1)
        self.assertEqual(result[0]["mean_survival"], 0.5)
        result = mixing_diagnostics([[0, 0], [0, 0]], [0, 1], depths=(1,))
        self.assertEqual(result[0]["mean_survival"], 0)
        self.assertEqual(result[0]["max_pairwise_tv"], 0)

    def test_decomposition_matches_exact_two_node_solution(self):
        position = fixture([("かさ", 1), ("さか", 3)], gammas=(0, 0.5), transform="linear").snapshot()
        rows = depth_decomposition(position, 0.5, horizons=(1, 2, 32))
        self.assertAlmostEqual(rows[0]["reward_sd"], 1)
        self.assertAlmostEqual(rows[1]["increment_sd"], 0.5)
        self.assertLess(rows[-1]["absolute_remainder_max"], 1e-8)
        self.assertEqual(depth_decomposition(position, 0, horizons=(1,))[0]["absolute_remainder_max"], 0)

    def test_coverage_categories_partition_safe_words(self):
        position = fixture([("かさ", 5), ("かき", 0.1), ("かく", None), ("かん", 9)]).snapshot()
        row = next(row for row in coverage_rows(position) if row["kana"] == "か")
        self.assertEqual(row["safe_dictionary_replies"], 3)
        self.assertEqual(row["selected"], 1)
        self.assertEqual(row["missing"], 1)
        self.assertEqual(row["below_threshold_or_zero"], 1)

    def test_synthetic_floor_does_not_replace_measured_values(self):
        analyzer = fixture([("かさ", 5), ("さか", None), ("さき", 0.1)])
        index = synthetic_index(analyzer, floor=0.01)
        self.assertEqual(index["readings"]["かさ"]["tubelex"]["per_million"], 5)
        self.assertEqual(index["readings"]["さか"]["tubelex"]["per_million"], 0.01)
        self.assertEqual(index["readings"]["さき"]["tubelex"]["per_million"], 0.01)
        self.assertEqual(analyzer.frequency_status["さか"], "missing")
        self.assertTrue(index["synthetic_sensitivity_only"])


if __name__ == "__main__":
    unittest.main()
