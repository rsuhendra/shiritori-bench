"""Initial-position analysis must distinguish availability from probability."""

import unittest

from shiritori_bench.kana_analysis import STANDARD_KANA, analyze, distribution


def word(reading, end, frequency):
    return {"reading": reading, "end_kana": end, "selected_frequency": frequency}


class KanaAnalysisTests(unittest.TestCase):
    def test_standard_kana_are_unique(self):
        self.assertEqual(len(STANDARD_KANA), 72)
        self.assertEqual(len(set(STANDARD_KANA)), 72)

    def test_probabilities_and_cumulative_mass(self):
        result = distribution([word("かさ", "さ", 20), word("かき", "き", 5)], 0, 1)
        self.assertAlmostEqual(result["ranked"][0][1], 0.8)
        self.assertEqual(result["ranked"][-1][2], 1)
        self.assertEqual(result["words_for_probability_mass"]["0.5"], 1)
        self.assertEqual(result["words_for_probability_mass"]["0.9"], 2)
        self.assertAlmostEqual(result["corpus_token_mass"], 25 / 1_000_000)

    def test_threshold_renormalizes_and_missing_is_not_zero(self):
        result = distribution([word("かさ", "さ", 20), word("かき", "き", 5), word("かく", "く", None)], 10, 1)
        self.assertEqual(result["eligible_words"], 1)
        self.assertEqual(result["ranked"][0][1], 1)

    def test_alpha_changes_concentration(self):
        words = [word("かさ", "さ", 20), word("かき", "き", 5)]
        self.assertAlmostEqual(distribution(words, 0, 0.5)["ranked"][0][1], 2 / 3)

    def test_empty_has_no_probability_distribution(self):
        result = distribution([], 0, 1)
        self.assertIsNone(result["entropy_bits"])
        self.assertIsNone(result["top_probability_mass"]["1"])
        self.assertIsNone(result["words_for_probability_mass"]["0.9"])

    def fixture(self):
        rows = [{"reading": reading, "start_kana": "か", "end_kana": end, "common": 1}
                for reading, end in [("かさ", "さ"), ("かき", "き"), ("かく", "く"), ("かん", "ん")]]
        index = {"source_id": "tubelex", "readings": {}}
        for reading, count, upper in [("かさ", 20, 20), ("かき", 5, 10), ("かん", 100, 100)]:
            index["readings"][reading] = {"tubelex": {"count": count, "count_upper": upper,
                "per_million": count, "per_million_upper": upper}}
        return rows, index

    def test_safe_filter_and_ambiguity_counts(self):
        result, words = analyze(*self.fixture(), thresholds=[0, 10])
        row = next(row for row in result["kana"] if row["kana"] == "か")
        self.assertEqual(row["dictionary_words"], 4)
        self.assertEqual(row["safe_words"], 3)
        self.assertEqual(row["ambiguous_safe_words"], 1)
        self.assertEqual(row["missing_frequency_safe_words"], 1)
        self.assertEqual(row["thresholds"][0]["eligible_words"], 1)
        self.assertEqual([w["reading"] for w in words], ["かさ"])
        self.assertEqual(words[0]["frequency_share_among_baseline_words"], 1)

    def test_lower_policy_never_adds_ambiguous_upper_counts(self):
        result, words = analyze(*self.fixture(), thresholds=[0], policy="lower")
        self.assertEqual(result["thresholds"][0]["frequency_mass_per_million"], 25)
        self.assertEqual(len(words), 2)

    def test_self_loop_consumes_only_reply(self):
        rows = [{"reading": "かか", "start_kana": "か", "end_kana": "か", "common": 1}]
        index = {"source_id": "tubelex", "readings": {"かか": {"tubelex": {
            "count": 1, "count_upper": 1, "per_million": 1, "per_million_upper": 1}}}}
        result, _ = analyze(rows, index, thresholds=[0])
        stats = next(row for row in result["kana"] if row["kana"] == "か")["thresholds"][0]
        self.assertEqual(stats["probability_of_leaving_baseline_no_reply"], 1)
        self.assertEqual(stats["expected_baseline_replies_after_move"], 0)

    def test_invalid_parameters_fail(self):
        for arguments in ({"alpha": 0}, {"alpha": float("nan")}, {"thresholds": [-1]}):
            with self.assertRaises(ValueError):
                analyze(*self.fixture(), **({"thresholds": [0]} | arguments))


if __name__ == "__main__":
    unittest.main()
