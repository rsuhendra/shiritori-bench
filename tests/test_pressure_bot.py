import math
import unittest
from shiritori_bench.bots import GameState, VocabularyGraph, Word
from shiritori_bench.pressure_bot import PressureBot


class PressureTests(unittest.TestCase):
    def test_matches_explicit_two_ply_depletion(self):
        readings = ('かか', 'かさ', 'かた', 'さか', 'ささ', 'さた', 'たか', 'たさ', 'たた')
        graph = VocabularyGraph(Word(w, w[0], w[-1], True) for w in readings)
        frequencies = {w: i + 1 for i, w in enumerate(readings)}
        for policy in ('immediate', 'two_ply'):
            bot = PressureBot(graph, frequencies, policy=policy)
            for used in (frozenset(), frozenset({'さた', 'たか'})):
                for start in ('か', 'さ', 'た'):
                    state = GameState(start, used)
                    for w, score in bot.scores(state).items():
                        after = state.after(graph.word(w))
                        replies = graph.safe_moves(after)
                        mass = sum(frequencies[r.reading] for r in replies)
                        expected = -math.log1p(mass)
                        if policy == 'two_ply':
                            expected += .85 * sum(frequencies[r.reading] * math.log1p(
                                sum(frequencies[v.reading] for v in graph.safe_moves(after.after(r))))
                                for r in replies) / mass
                        self.assertAlmostEqual(score, expected, places=11)

    def test_terminal_and_empty_pool(self):
        graph = VocabularyGraph([Word('かさ', 'か', 'さ', True)])
        bot = PressureBot(graph, {'かさ': 1})
        self.assertEqual(bot.scores(GameState('か')), {'かさ': float('inf')})
        self.assertEqual(bot.scores(GameState('さ')), {})
