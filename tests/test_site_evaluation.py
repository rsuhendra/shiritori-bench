import json
import math
import unittest

from shiritori_bench.bots import GameState, VocabularyGraph, Word
from shiritori_bench.public_site import build_public_payload
from shiritori_bench.site_evaluation import WordStrength, annotate, percentile, wilson


class StrengthTests(unittest.TestCase):
    def test_two_ply_matches_explicit_candidate_and_reply_removal(self):
        readings=('かか','かさ','かた','さか','ささ','さた','たか','たさ','たた')
        graph=VocabularyGraph(Word(w,w[0],w[-1],True) for w in readings)
        frequencies={w:i+1 for i,w in enumerate(readings)}
        scorer=WordStrength(graph,frequencies)
        for used in (set(),{'さた','たか'}):
            for kana in ('か','さ','た'):
                before=GameState(kana,frozenset(used))
                for w in graph.safe_moves(before):
                    after=before.after(w)
                    replies=graph.safe_moves(after)
                    mass=sum(frequencies[r.reading] for r in replies)
                    pressure=-math.log1p(mass)
                    balance=pressure+.85*sum(frequencies[r.reading]*math.log1p(sum(
                        frequencies[v.reading] for v in graph.safe_moves(after.after(r)))) for r in replies)/mass
                    score=scorer.scores(kana,w.reading,used)
                    self.assertAlmostEqual(score['reply_pressure'],pressure,places=11)
                    self.assertAlmostEqual(score['two_ply'],balance,places=11)

    def test_missing_destination_is_unavailable_not_best_trap(self):
        graph=VocabularyGraph(Word(w,w[0],w[-1],True) for w in ('かさ','さか'))
        s=WordStrength(graph,{'かさ':3}).scores('か','かさ',set())
        self.assertIsNone(s['two_ply'])
        self.assertIsNone(s['reply_pressure_percentile'])
        self.assertEqual(s['reply_pressure_alternatives'],0)

    def test_supported_pressure_can_have_unsupported_continuation(self):
        graph=VocabularyGraph(Word(w,w[0],w[-1],True) for w in ('かさ','さた','たか'))
        s=WordStrength(graph,{'かさ':3,'さた':2}).scores('か','かさ',set())
        self.assertIsNotNone(s['reply_pressure'])
        self.assertIsNone(s['two_ply'])

    def test_unmeasured_chosen_word_can_be_scored(self):
        graph=VocabularyGraph(Word(w,w[0],w[-1],True) for w in ('かさ','さた'))
        s=WordStrength(graph,{'さた':2}).scores('か','かさ',set())
        self.assertIsNotNone(s['two_ply'])

    def test_midrank_ties_and_no_choices(self):
        self.assertEqual(percentile([3,3,3],3),50)
        self.assertEqual(percentile([1,2,3],3),100*2.5/3)
        self.assertIsNone(percentile([],1))
        self.assertIsNone(wilson(0,0))
        self.assertGreater(wilson(2,2)[0],0)
        self.assertLess(wilson(0,2)[1],1)


def record(identifier='a',version='v2',bot=False,outcome='PLAYER_ONE_WIN'):
    return dict(match_id=identifier, started_at='2026-10-29', opening_kana='か',
        vocabulary_version=version, players=[dict(name='model',kind='llm'),dict(name='MemoryBot' if bot else 'model',kind='algorithmic' if bot else 'llm')],
        winner_index=None if outcome=='TURN_LIMIT_DRAW' else 0,loser_index=None if outcome=='TURN_LIMIT_DRAW' else 1,
        outcome=outcome,ending='TURN_LIMIT_DRAW' if outcome=='TURN_LIMIT_DRAW' else 'INVALID_WORD',
        turns=[dict(turn=1,player_index=0,player_name='model',submitted='かさ',normalized='かさ',outcome='VALID',required_kana='か',next_required_kana='さ',
            metadata=dict(model='test',request=dict(thinking=False,max_completion_tokens=20),reasoning_content='DO NOT EXPORT')),
            dict(turn=2,player_index=1,player_name='MemoryBot' if bot else 'model',submitted='さた',normalized='さた',outcome='INVALID_WORD',required_kana='さ',next_required_kana=None,
            metadata=dict() if bot else dict(model='test',request=dict(thinking=False,max_completion_tokens=20)))])


class EvaluationTests(unittest.TestCase):
    def payload(self,records):
        graph=VocabularyGraph(Word(w,w[0],w[-1],True) for w in ('かさ','さた'))
        payload=build_public_payload(records,{}, {}, {},glossary=lambda w:'gloss')
        return annotate(payload,records,WordStrength(graph,{'かさ':2,'さた':1}))

    def test_competitions_and_versions_are_separate(self):
        p=self.payload([record('a',bot=True),record('b',version='v3',bot=True),record('c')])
        self.assertEqual(len(p['evaluations']),3)
        self.assertEqual({(e['competition'],e['vocabulary_version']) for e in p['evaluations']},
            {('model-bot','v2'),('model-bot','v3'),('model-model','v2')})

    def test_selfplay_excluded_from_win_rate_but_moves_retained(self):
        p=self.payload([record()]); e=p['evaluations'][0]['entries'][0]
        self.assertEqual(e['selfplay_appearances'],2)
        self.assertIsNone(e['win_rate'])
        self.assertEqual(e['valid_moves'],1)

    def test_caps_and_errors_excluded_from_comparative_outcomes(self):
        p=self.payload([record(bot=True,outcome='TURN_LIMIT_DRAW'),record('error',bot=True,outcome='PLAYER_ERROR')])
        self.assertEqual(len(p['games']),1)
        self.assertEqual(p['summary']['completed_games'],0)
        self.assertEqual(len(p['excluded']),1)
        self.assertEqual(p['evaluations'][0]['entries'][0]['comparison_games'],0)
        self.assertIsNone(p['games'][0]['turns'][1]['strength'])

    def test_token_budget_creates_distinct_configuration(self):
        a=record('a'); b=record('b')
        b['turns'][0]['metadata']['request']['max_completion_tokens']=100
        p=self.payload([a,b])
        self.assertEqual(len(p['models']),2)

    def test_historical_warning_does_not_relabel_result(self):
        r=record(bot=True,version='jmdict-noun-v2')
        r['turns'][-1].update(submitted='まくら',normalized='まくら',required_kana='ま')
        p=self.payload([r])
        self.assertIn('referee artifact',p['games'][0]['policy_warning'])
        self.assertEqual(p['games'][0]['ending'],'INVALID_WORD')
        self.assertNotIn('DO NOT EXPORT',json.dumps(p))

    def test_private_exception_messages_are_not_published(self):
        r=record(outcome='PLAYER_ERROR')
        r['ending']='PLAYER_ERROR:ValueError:DO NOT EXPORT'
        self.assertNotIn('DO NOT EXPORT',json.dumps(self.payload([r])))
