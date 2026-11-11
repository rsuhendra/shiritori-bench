"""Match execution tests using small in-memory player fixtures."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import tempfile
import unittest

from shiritori_bench.match import MatchRunner
from shiritori_bench.players import PlayerResponse, TurnContext
from shiritori_bench.referee import Referee


class SequencePlayer:
    kind = "fixture"

    def __init__(self, name: str, moves: list[str]) -> None:
        self.name = name
        self.moves = iter(moves)

    def play(self, context: TurnContext) -> PlayerResponse:
        return PlayerResponse(next(self.moves))


def create_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE words (
            id INTEGER PRIMARY KEY,
            jmdict_id INTEGER NOT NULL,
            reading TEXT NOT NULL UNIQUE,
            display_forms TEXT NOT NULL,
            start_kana TEXT NOT NULL,
            end_kana TEXT NOT NULL,
            pos TEXT NOT NULL,
            common INTEGER NOT NULL
        );
        INSERT INTO words
            (jmdict_id, reading, display_forms, start_kana, end_kana, pos, common)
        VALUES
            (1, 'かさ', '[]', 'か', 'さ', '[]', 1),
            (2, 'さる', '[]', 'さ', 'る', '[]', 1),
            (3, 'るすばん', '[]', 'る', 'ん', '[]', 1);
        """
    )
    connection.close()


class MatchRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        database = Path(self.temporary.name) / "words.sqlite"
        create_database(database)
        self.referee = Referee(str(database))

    def tearDown(self) -> None:
        self.referee.close()
        self.temporary.cleanup()

    def test_word_ending_in_n_loses_immediately(self) -> None:
        runner = MatchRunner(self.referee, vocabulary_version="test", turn_limit=10)
        record = runner.run(
            SequencePlayer("one", ["かさ", "るすばん"]),
            SequencePlayer("two", ["さる"]),
            opening_kana="か",
            match_id="fixed",
        )

        self.assertEqual(record.match_id, "fixed")
        self.assertEqual(record.winner_index, 1)
        self.assertEqual(record.ending, "ENDS_IN_N")
        self.assertEqual(len(record.turns), 3)

    def test_invalid_move_loses(self) -> None:
        runner = MatchRunner(self.referee, vocabulary_version="test")
        record = runner.run(
            SequencePlayer("one", ["さる"]),
            SequencePlayer("two", []),
            opening_kana="か",
        )

        self.assertEqual(record.winner_index, 1)
        self.assertEqual(record.ending, "WRONG_START")

    def test_turn_limit_draw(self) -> None:
        runner = MatchRunner(self.referee, vocabulary_version="test", turn_limit=2)
        record = runner.run(
            SequencePlayer("one", ["かさ"]),
            SequencePlayer("two", ["さる"]),
            opening_kana="か",
        )

        self.assertIsNone(record.winner_index)
        self.assertEqual(record.ending, "TURN_LIMIT_DRAW")

    def test_player_error_is_not_a_competitive_loss(self) -> None:
        record = MatchRunner(self.referee, vocabulary_version="test").run(
            SequencePlayer("one", []), SequencePlayer("two", []), opening_kana="か")
        self.assertEqual(record.outcome, "PLAYER_ERROR")
        self.assertIsNone(record.winner_index)

    def test_both_players_receive_ordered_valid_history(self) -> None:
        observed = []

        class RecordingPlayer(SequencePlayer):
            def play(self, context):
                observed.append((self.name, context.history, context.used_words))
                return super().play(context)

        MatchRunner(self.referee, vocabulary_version="test").run(
            RecordingPlayer("one", ["かさ", "るすばん"]),
            RecordingPlayer("two", ["さる"]), opening_kana="か")
        self.assertEqual([(name, history) for name, history, _ in observed],
                         [("one", ()), ("two", ("かさ",)), ("one", ("かさ", "さる"))])
        self.assertTrue(all(set(history) == set(used) for _, history, used in observed))

    def test_transport_retries_do_not_replay_completed_moves(self):
        from unittest.mock import MagicMock, patch
        from shiritori_bench.deepseek import DeepSeekClient
        from shiritori_bench.players import LLMPlayer
        import http.client
        first = MagicMock()
        first.__enter__.return_value.read.return_value = '{"choices":[{"message":{"content":"かさ"}}]}'.encode()
        last = MagicMock()
        last.__enter__.return_value.read.return_value = '{"choices":[{"message":{"content":"るすばん"}}]}'.encode()
        model = LLMPlayer(name='model', model='test', client=DeepSeekClient('test'),
                          prompt_template='{required_kana}: {used_words}')
        with patch('urllib.request.urlopen', side_effect=[first, http.client.RemoteDisconnected(), last]) as send, \
                patch('shiritori_bench.http_retry.time.sleep'), self.assertLogs('shiritori_bench.http_retry'):
            record = MatchRunner(self.referee, vocabulary_version='test').run(
                model, SequencePlayer('bot', ['さる']), opening_kana='か')
        self.assertEqual(len(record.turns), 3)
        self.assertEqual(send.call_count, 3)
        self.assertEqual(send.call_args_list[1].args[0].data, send.call_args_list[2].args[0].data)
        self.assertNotEqual(send.call_args_list[0].args[0].data, send.call_args_list[1].args[0].data)
        self.assertEqual(record.turns[-1].metadata['transport']['retries'], 1)

    def test_exhausted_retries_preserve_moves_and_no_winner(self):
        from shiritori_bench.http_retry import RetryExhausted
        class FailedPlayer(SequencePlayer):
            def play(self, context):
                if context.turn_number == 3:
                    raise RetryExhausted({'attempts': 3, 'retries': 2, 'failures': [
                        {'error_type':'TimeoutError', 'status':None}]})
                return super().play(context)
        record = MatchRunner(self.referee, vocabulary_version='test').run(
            FailedPlayer('one', ['かさ']), SequencePlayer('two', ['さる']), opening_kana='か')
        self.assertEqual(record.outcome, 'PLAYER_ERROR')
        self.assertIsNone(record.winner_index)
        self.assertEqual(len(record.turns), 2)
        self.assertEqual(record.error_metadata['attempts'], 3)

    def test_truncated_completion_is_logged_but_not_a_competitive_loss(self) -> None:
        class TruncatedPlayer:
            name = "truncated"
            kind = "fixture"

            def play(self, context):
                return PlayerResponse("かさ", {"finish_reason": "length"})

        journal = []
        record = MatchRunner(self.referee, vocabulary_version="test").run(
            TruncatedPlayer(), SequencePlayer("two", []), opening_kana="か",
            on_turn=journal.append)
        self.assertIsNone(record.winner_index)
        self.assertEqual(record.ending, "GENERATION_ERROR:length")
        self.assertEqual(len(journal), 1)


if __name__ == "__main__":
    unittest.main()
