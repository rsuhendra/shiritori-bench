"""Small, explicit answer-key cases for every referee outcome and key boundaries.

Uses a miniature in-memory vocabulary, not the changing production dictionary.
The actual mixed noun/suffix importer regression lives in test_vocabulary_policy.
"""
import unittest

from shiritori_bench.normalize import terminal_kana
from shiritori_bench.referee import MoveOutcome, Referee


class RefereeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.referee = Referee(':memory:')
        self.referee.connection.execute('CREATE TABLE words (reading TEXT PRIMARY KEY, '
            'start_kana TEXT, end_kana TEXT, jmdict_id INTEGER)')
        words = [('かさ', 'か', 'さ'), ('さくら', 'さ', 'ら'), ('らっか', 'ら', 'か'),
                 ('まくら', 'ま', 'ら'), ('ずぼん', 'ず', 'ん'), ('ぐんかん', 'ぐ', 'ん'),
                 ('おもちゃ', 'お', 'や'), ('がっき', 'が', 'き'),
                 ('どれっしんぐ', 'ど', 'ぐ'), ('こーひーまめ', 'こ', 'め')]
        self.referee.connection.executemany('INSERT INTO words VALUES (?, ?, ?, ?)',
            [(reading, start, end, i) for i, (reading, start, end) in enumerate(words, 1)])

    def tearDown(self):
        self.referee.close()

    def test_answer_key_covers_every_outcome(self):
        cases = [
            ('まくら', 'ま', set(), MoveOutcome.VALID),
            ('ずいひ', 'ず', set(), MoveOutcome.INVALID_WORD),
            ('さくら', 'ま', set(), MoveOutcome.WRONG_START),
            ('かさ', 'か', {'かさ'}, MoveOutcome.REPEATED_WORD),
            ('ずぼん', 'ず', set(), MoveOutcome.ENDS_IN_N),
            ('かさ。', 'か', set(), MoveOutcome.MALFORMED_OUTPUT),
            ('PASS', 'か', set(), MoveOutcome.PASS_WITH_LEGAL_MOVE),
            ('PASS', 'ぬ', set(), MoveOutcome.PASS_NO_LEGAL_MOVE),
        ]
        self.assertEqual({expected for _, _, _, expected in cases}, set(MoveOutcome))
        for word, kana, used, expected in cases:
            with self.subTest(word=word, kana=kana, used=used):
                self.assertEqual(self.referee.validate(word, kana, used).outcome, expected)

    def test_real_pilot_n_ending_failure_has_correct_start(self):
        result = self.referee.validate('ぐんかん', 'ぐ', set())
        self.assertEqual(result.outcome, MoveOutcome.ENDS_IN_N)
        self.assertEqual(result.normalized, 'ぐんかん')
        self.assertEqual(result.next_required_kana, 'ん')

    def test_valid_move_sets_next_kana_and_dictionary_id(self):
        result = self.referee.validate('どれっしんぐ', 'ど', set())
        self.assertEqual(result.outcome, MoveOutcome.VALID)
        self.assertEqual(result.next_required_kana, 'ぐ')
        self.assertIsNotNone(result.jmdict_id)

    def test_malformed_output_boundaries(self):
        for word in ('', 'かさ\nさくら', 'かさ さくら', 'かさ / umbrella', '1. かさ',
                     '傘', 'カサ', 'kasa', 'pass', 'かさ🙂'):
            with self.subTest(word=word):
                self.assertEqual(self.referee.validate(word, 'か', set()).outcome,
                                 MoveOutcome.MALFORMED_OUTPUT)

    def test_surrounding_whitespace_is_ignored_but_not_internal_whitespace(self):
        self.assertEqual(self.referee.validate('  かさ\n', 'か', set()).outcome, MoveOutcome.VALID)
        self.assertEqual(self.referee.validate('か さ', 'か', set()).outcome, MoveOutcome.MALFORMED_OUTPUT)

    def test_voiced_unvoiced_and_semivoiced_kana_are_distinct(self):
        self.assertEqual(self.referee.validate('がっき', 'が', set()).outcome, MoveOutcome.VALID)
        for kana in ('か', 'ぱ'):
            self.assertEqual(self.referee.validate('がっき', kana, set()).outcome, MoveOutcome.WRONG_START)

    def test_final_small_kana_changes_next_kana_not_word_identity(self):
        result = self.referee.validate('おもちゃ', 'お', set())
        self.assertEqual(result.next_required_kana, 'や')
        self.assertEqual(result.normalized, 'おもちゃ')
        self.assertEqual(self.referee.validate('おもちゃ', 'お', {'おもちゃ'}).outcome,
                         MoveOutcome.REPEATED_WORD)
        for small, full in zip('ゃゅょぁぃぅぇぉっ', 'やゆよあいうえおつ'):
            with self.subTest(small=small):
                self.assertEqual(terminal_kana('あ' + small), full)

    def test_internal_long_vowel_mark_is_allowed(self):
        self.assertEqual(self.referee.validate('こーひーまめ', 'こ', set()).outcome, MoveOutcome.VALID)

    def test_pass_checks_unused_words_not_just_starting_kana_exists(self):
        self.assertEqual(self.referee.validate('PASS', 'か', {'かさ'}).outcome,
                         MoveOutcome.PASS_NO_LEGAL_MOVE)
        self.assertEqual(self.referee.validate('PASS', 'か', {'さくら'}).outcome,
                         MoveOutcome.PASS_WITH_LEGAL_MOVE)

    def test_repeated_word_by_either_player_is_rejected(self):
        required, used = 'か', set()
        for word in ('かさ', 'さくら', 'らっか'):
            result = self.referee.validate(word, required, used)
            self.assertEqual(result.outcome, MoveOutcome.VALID)
            used.add(result.normalized)
            required = result.next_required_kana
        # Player 2 now tries a reading first used by Player 1.
        self.assertEqual(self.referee.validate('かさ', required, used).outcome,
                         MoveOutcome.REPEATED_WORD)

    def test_overlapping_errors_use_stable_first_failure_order(self):
        self.assertEqual(self.referee.validate('ぐんかん', 'か', {'ぐんかん'}).outcome,
                         MoveOutcome.WRONG_START)
        self.assertEqual(self.referee.validate('ぐんかん', 'ぐ', {'ぐんかん'}).outcome,
                         MoveOutcome.REPEATED_WORD)
