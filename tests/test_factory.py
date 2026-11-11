from pathlib import Path
import unittest
from unittest.mock import patch
from shiritori_bench.bots import VocabularyGraph, Word
from shiritori_bench.factory import configured_player
from shiritori_bench.players import TurnContext


class FactoryTests(unittest.TestCase):
    @patch('shiritori_bench.factory.load_frequency_vocabulary')
    def test_configured_memory_is_fresh_and_uses_explicit_parameters(self, load):
        graph = VocabularyGraph([Word('かさ', 'か', 'さ', True)])
        load.return_value = graph, {'かさ': 2}, {}
        spec = dict(provider='bot', model='memory', seed=43, recent=7, half_life=19, floor=.3)
        def make():
            return configured_player(spec, prompt_path=Path('unused'),
                                     bot_vocabulary=Path('/project/data/processed/bot-vocabulary.sqlite'))
        a, b = make(), make()
        self.assertIsNot(a.bot, b.bot)
        self.assertEqual((a.bot.seed, a.bot.recent, a.bot.half_life, a.bot.floor), (43,7,19,.3))
        context = TurnContext('か', frozenset(), 'test', 1)
        self.assertEqual(a.play(context), b.play(context))
        self.assertEqual(load.call_args.args[0], Path('/project/data/processed/referee-vocabulary.sqlite'))
