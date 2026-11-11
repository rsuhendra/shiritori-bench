"""Frequency aggregation rules tested offline with a small synthetic corpus."""

import io
import unittest
from unittest.mock import patch

from shiritori_bench.frequency import aggregate_rows, aggregate_tubelex, frequency_label, lookup_frequency


class FrequencyTests(unittest.TestCase):
    def rows(self, *rows):
        return io.StringIO("lForm\tlemma\tpos\tfrequency\tpmw\n" + "\n".join(rows))

    def test_sum_homophones_but_exclude_proper_nouns_and_other_pos(self):
        data = aggregate_rows(self.rows(
            "スズ\t鈴\t名詞-普通名詞-一般\t20\t2",
            "スズ\t錫\t名詞-普通名詞-一般\t10\t1",
            "スズ\t珠洲\t名詞-固有名詞-地名\t100\t10",
            "スズ\t動詞\t動詞-一般\t100\t10",
            "イチ\t一\t名詞-数詞\t100\t10"))
        self.assertEqual(set(data), {"すず"})
        self.assertEqual(data["すず"]["count"], 30)
        self.assertEqual(data["すず"]["per_million"], 3)
        self.assertEqual(data["すず"]["entry_count"], 2)

    def test_tied_counts_share_rank(self):
        data = aggregate_rows(self.rows(
            "カサ\t傘\t名詞-普通名詞-一般\t20\t2",
            "サル\t猿\t名詞-普通名詞-一般\t20\t2",
            "スズ\t鈴\t名詞-普通名詞-一般\t5\t0.5"))
        self.assertEqual(data["かさ"]["noun_reading_rank"], 1)
        self.assertEqual(data["さる"]["noun_reading_rank"], 1)
        self.assertEqual(data["すず"]["noun_reading_rank"], 3)

    def test_long_vowel_spellings_are_not_silently_merged(self):
        data = aggregate_rows(self.rows("ルーペ\tルーペ\t名詞-普通名詞-一般\t2\t0.2"))
        self.assertIn("るーぺ", data)
        self.assertNotIn("るうぺ", data)

    def test_missing_is_unavailable_not_zero(self):
        with patch("shiritori_bench.frequency.load_frequency", return_value={"readings": {}}):
            self.assertEqual(lookup_frequency("ぱんぷ"), {})
            self.assertEqual(frequency_label("ぱんぷ"), "BCCWJ: unavailable")

    def test_missing_dataset_is_distinct_from_unmatched_reading(self):
        with patch("shiritori_bench.frequency.load_frequency", return_value={}):
            self.assertEqual(frequency_label("すず"), "Frequency: dataset not installed")

    def test_units_remain_separate(self):
        index = {"readings": {"すず": {"suw": {"per_million": 3, "noun_reading_rank": 20}}}}
        with patch("shiritori_bench.frequency.load_frequency", return_value=index):
            label = frequency_label("すず")
            self.assertIn("SUW 3/million", label)
            self.assertIn("LUW unavailable", label)

    def test_wrong_source_schema_fails_loudly(self):
        with self.assertRaises(ValueError):
            aggregate_rows(io.StringIO("reading\tcount\nすず\t3\n"))

    def test_tubelex_ambiguous_forms_are_not_counted_as_certain(self):
        source = io.StringIO("word\tcount\tpos\n鈴\t30\t名詞-普通名詞-一般\n錫\t10\t名詞-普通名詞-一般\n鈴木\t100\t名詞-固有名詞-人名\n[TOTAL]\t1000\t\n")
        totals, stats = aggregate_tubelex(source, {"鈴": {"すず", "りん"}, "錫": {"すず"}, "鈴木": {"すずき"}})
        self.assertEqual(totals["すず"]["count"], 10)
        self.assertEqual(totals["すず"]["count_upper"], 40)
        self.assertEqual(totals["りん"]["count"], 0)
        self.assertEqual(totals["すず"]["per_million"], 10000)
        self.assertNotIn("すずき", totals)
        self.assertEqual(stats["ambiguous_forms"], 1)

    def test_tubelex_sums_unambiguous_homophones(self):
        source = io.StringIO("word\tcount\tpos\n傘\t20\t名詞-普通名詞-一般\n笠\t5\t名詞-普通名詞-一般\n[TOTAL]\t1000\t\n")
        totals, _ = aggregate_tubelex(source, {"傘": {"かさ"}, "笠": {"かさ"}})
        self.assertEqual(totals["かさ"]["count"], 25)
        self.assertEqual(totals["かさ"]["count_upper"], 25)

    def test_tubelex_unidic_loanword_suffix(self):
        source = io.StringIO("word\tcount\tpos\nマップ-map\t20\t名詞-普通名詞-一般\n[TOTAL]\t1000\t\n")
        totals, stats = aggregate_tubelex(source, {"マップ": {"まっぷ"}})
        self.assertEqual(totals["まっぷ"]["count"], 20)
        self.assertEqual(stats["unidic_suffix_matches"], 1)

    def test_tubelex_requires_full_corpus_denominator(self):
        with self.assertRaises(ValueError):
            aggregate_tubelex(io.StringIO("word\tcount\tpos\n傘\t20\t名詞-普通名詞-一般\n"), {"傘": {"かさ"}})

    def test_tubelex_quote_tokens_do_not_consume_following_rows(self):
        source = io.StringIO('word\tcount\tpos\n"\t1\t記号\n傘\t20\t名詞-普通名詞-一般\n[TOTAL]\t1000\t\n')
        totals, _ = aggregate_tubelex(source, {"傘": {"かさ"}})
        self.assertEqual(totals["かさ"]["count"], 20)

    def test_tubelex_labels_ambiguity_without_point_rank(self):
        index = {"source_id": "tubelex", "readings": {"すず": {"tubelex": {
            "count": 10, "count_upper": 40, "per_million": 1, "per_million_upper": 4}}}}
        with patch("shiritori_bench.frequency.load_frequency", return_value=index):
            label = frequency_label("すず")
            self.assertIn("1–4/million", label)
            self.assertIn("ambiguous", label)
            self.assertNotIn("rank", label)


if __name__ == "__main__":
    unittest.main()
