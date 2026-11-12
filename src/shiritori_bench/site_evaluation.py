"""Versioned competition summaries and two transparent, post-hoc move heuristics."""
from collections import Counter, defaultdict
import math
import statistics

from .bots import GameState


def percentile(values, chosen):
    if chosen is None or not values:
        return None
    return 100 * (sum(v < chosen - 1e-9 for v in values)
        + .5 * sum(abs(v - chosen) <= 1e-9 for v in values)) / len(values)


class WordStrength:
    """All safe dictionary alternatives; frequency support is never inferred from zero.

    Scores use the same fixed graph for every opponent and both competitions.
    Each candidate and each sampled reply are removed before the next mass is
    evaluated. Unmeasured candidate words may be scored if their destinations
    are supported; comparison coverage is always reported.
    """
    def __init__(self, dictionary, frequencies, gamma=.85):
        self.dictionary, self.frequencies, self.gamma = dictionary, frequencies, gamma
        self.starts = sorted({dictionary.word(w).start_kana for w in frequencies})

    def scores(self, required, chosen, used):
        state = GameState(required, frozenset(used))
        candidates = self.dictionary.safe_moves(state)
        rows = {k: tuple(w for w in self.dictionary.safe_moves(GameState(k, state.used_words))
                         if w.reading in self.frequencies) for k in self.starts}
        counts = {}
        def count(k):
            if k not in counts:
                counts[k] = len(self.dictionary.safe_moves(GameState(k, state.used_words)))
            return counts[k]
        mass = {k: math.fsum(self.frequencies[w.reading] for w in row) for k,row in rows.items()}
        all_scores = {}
        for word in candidates:
            a, b = word.start_kana, word.end_kana
            f = self.frequencies.get(word.reading, 0)
            replies = tuple(r for r in rows.get(b, ()) if r.reading != word.reading)
            opponent_mass = math.fsum(self.frequencies[r.reading] for r in replies)
            safe_replies = count(b) - int(a == b)
            pressure = -math.log1p(opponent_mass) if opponent_mass or not safe_replies else None
            balance, reason = None, None
            if pressure is None:
                reason = 'Opponent kana has safe dictionary replies but no frequency support.'
            elif not replies:
                balance = pressure  # Genuine safe-dictionary exhaustion, not a coverage gap.
            else:
                terms = []
                for reply in replies:
                    c, rf = reply.end_kana, self.frequencies[reply.reading]
                    own_mass = max(0, mass.get(c, 0) - (f if c == a else 0) - (rf if c == b else 0))
                    own_count = count(c) - int(c == a) - int(c == b)
                    if not own_mass and own_count > 0:
                        reason = 'A possible next-turn kana lacks frequency support.'
                        break
                    terms.append(rf * math.log1p(own_mass))
                if reason is None:
                    balance = pressure + self.gamma * math.fsum(terms) / opponent_mass
            all_scores[word.reading] = dict(reply_pressure=pressure, two_ply=balance,
                opponent_mass=opponent_mass if pressure is not None else None,
                safe_replies=safe_replies, unavailable_reason=reason)
        result = all_scores.get(chosen)
        if result is None:
            return dict(reply_pressure=None, two_ply=None, unavailable_reason='Not a safe alternative in the scoring dictionary.')
        result = dict(result, legal_alternatives=len(candidates))
        for metric in ('reply_pressure','two_ply'):
            values = [s[metric] for s in all_scores.values() if s[metric] is not None]
            result[metric + '_percentile'] = percentile(values, result[metric])
            result[metric + '_alternatives'] = len(values)
        return result


def wilson(wins, trials):
    if not trials:
        return None
    z=1.959963984540054
    p=wins/trials
    center=(p+z*z/(2*trials))/(1+z*z/trials)
    half=z*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))/(1+z*z/trials)
    return [max(0,center-half),min(1,center+half)]


def competition_for(match):
    kinds=[p.get('kind','llm') for p in match['players']]
    return 'model-bot' if 'llm' in kinds and any(k != 'llm' for k in kinds) else 'model-model' if kinds == ['llm','llm'] else 'bot-bot'


def annotate(payload, records, scorer):
    originals={r['match_id']:r for r in records}
    models={m['id']:m for m in payload['models']}
    cohorts=defaultdict(list)
    for game in payload['games']:
        original=originals[game['id']]
        game['competition']=competition_for(original)
        game['valid_words']=sum(t['outcome']=='VALID' for t in game['turns'])
        game['policy_warning']=None
        if game['vocabulary_version'].endswith('noun-v2') and game['turns'] and game['turns'][-1]['word']=='まくら' and game['ending']=='INVALID_WORD':
            game['policy_warning']='Historical referee artifact: まくら (pillow) was excluded by noun-v2’s mixed noun/suffix filter. Accepted by noun-v3; this recorded result has not been rescored.'
        used=set()
        for turn in game['turns']:
            turn['strength']=scorer.scores(turn['required_kana'], turn['word'], used) if turn['outcome']=='VALID' else None
            if turn['outcome']=='VALID': used.add(turn['word'])
        cohorts[game['competition'], game['vocabulary_version']].append(game)
    output=[]
    for (competition, version), games in sorted(cohorts.items()):
        entries=[]
        for identifier in sorted({p for g in games for p in g['players']}):
            appearances=[(g,seat) for g in games for seat,p in enumerate(g['players']) if p==identifier]
            comparison=[(g,s) for g,s in appearances if not g['same_configuration'] and not g['unfinished'] and g['winner_index'] is not None]
            wins=sum(g['winner_index']==s for g,s in comparison)
            turns=[t for g,s in appearances for t in g['turns'] if t['player_index']==s]
            lengths={result:[g['valid_words'] for g,s in comparison if (g['winner_index']==s)==(result=='wins')]
                     for result in ('wins','losses')}
            scores={metric:[t['strength'][metric+'_percentile'] for t in turns if t['strength'] and t['strength'].get(metric+'_percentile') is not None]
                    for metric in ('two_ply','reply_pressure')}
            entries.append(dict(id=identifier, kind=models[identifier]['kind'], appearances=len(appearances),
                wins=wins, losses=len(comparison)-wins, comparison_games=len(comparison),
                win_rate=wins/len(comparison) if comparison else None, win_interval=wilson(wins,len(comparison)),
                selfplay_appearances=sum(g['same_configuration'] for g,s in appearances),
                unfinished=sum(g['unfinished'] for g,s in appearances),
                valid_moves=sum(t['outcome']=='VALID' for t in turns), submissions=len(turns),
                validity=sum(t['outcome']=='VALID' for t in turns)/len(turns) if turns else None,
                mean_length=statistics.mean(g['valid_words'] for g,s in appearances),
                length_by_result={k:statistics.mean(v) if v else None for k,v in lengths.items()},
                strength={k:dict(mean=statistics.mean(v) if v else None, scored_moves=len(v)) for k,v in scores.items()}))
        output.append(dict(competition=competition, vocabulary_version=version, games=len(games),
            finished=sum(not g['unfinished'] for g in games), selfplay=sum(g['same_configuration'] for g in games),
            policy_warnings=sum(bool(g['policy_warning']) for g in games), entries=entries))
    payload.update(schema_version=3, evaluations=output)
    for row, original in zip(payload['excluded'],[r for r in records if r['outcome']=='PLAYER_ERROR']):
        row.update(competition=competition_for(original), vocabulary_version=original['vocabulary_version'])
    return payload
