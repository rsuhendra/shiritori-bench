"""Deterministic, vocabulary-aware reference players for ShiritoriBench."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sqlite3
from typing import Iterable


MATE_SCORE = 1_000_000


@dataclass(frozen=True, slots=True)
class Word:
    """One playable reading from the pinned benchmark vocabulary."""

    reading: str
    start_kana: str
    end_kana: str
    common: bool

    @property
    def immediately_loses(self) -> bool:
        return self.end_kana == "ん"


@dataclass(frozen=True, slots=True)
class GameState:
    """The information required to choose a deterministic move."""

    required_kana: str
    used_words: frozenset[str] = frozenset()

    def after(self, word: Word) -> GameState:
        return GameState(
            required_kana=word.end_kana,
            used_words=self.used_words | {word.reading},
        )


@dataclass(frozen=True, slots=True)
class SearchResult:
    """A SearchBot decision and reproducibility metadata."""

    word: str
    score: int
    completed_depth: int
    nodes: int
    budget_exhausted: bool


class _Bound(StrEnum):
    EXACT = "EXACT"
    LOWER = "LOWER"
    UPPER = "UPPER"


@dataclass(frozen=True, slots=True)
class _TableEntry:
    value: int
    bound: _Bound


class VocabularyGraph:
    """Immutable in-memory view of a JMdict-derived SQLite vocabulary."""

    def __init__(self, words: Iterable[Word]) -> None:
        by_start: dict[str, list[Word]] = {}
        by_reading: dict[str, Word] = {}
        for word in words:
            by_start.setdefault(word.start_kana, []).append(word)
            by_reading[word.reading] = word

        # The database's row order is deliberately ignored.
        self._by_start = {
            kana: tuple(sorted(items, key=lambda item: item.reading))
            for kana, items in by_start.items()
        }
        self._by_reading = by_reading

    @classmethod
    def from_sqlite(cls, database_path: str) -> VocabularyGraph:
        connection = sqlite3.connect(database_path)
        try:
            rows = connection.execute(
                """
                SELECT reading, start_kana, end_kana, common
                FROM words
                ORDER BY reading
                """
            ).fetchall()
        finally:
            connection.close()

        return cls(
            Word(
                reading=row[0],
                start_kana=row[1],
                end_kana=row[2],
                common=bool(row[3]),
            )
            for row in rows
        )

    def word(self, reading: str) -> Word:
        return self._by_reading[reading]

    def remaining_word_count(self, used_words: frozenset[str]) -> int:
        return len(self._by_reading) - len(
            self._by_reading.keys() & used_words
        )

    def legal_moves(self, state: GameState) -> tuple[Word, ...]:
        return tuple(
            word
            for word in self._by_start.get(state.required_kana, ())
            if word.reading not in state.used_words
        )

    def safe_moves(self, state: GameState) -> tuple[Word, ...]:
        return tuple(
            word for word in self.legal_moves(state) if not word.immediately_loses
        )


class GreedyBot:
    """Choose the move that leaves the fewest non-losing replies."""

    name = "GreedyBot"

    def __init__(self, vocabulary: VocabularyGraph) -> None:
        self.vocabulary = vocabulary

    def choose(self, state: GameState) -> str | None:
        legal = self.vocabulary.legal_moves(state)
        if not legal:
            return None

        safe = tuple(word for word in legal if not word.immediately_loses)
        candidates = safe or legal

        # min() plus this complete key makes the answer independent of SQLite
        # ordering. Common words win a strategic tie, followed by reading.
        chosen = min(
            candidates,
            key=lambda word: (
                self._opponent_safe_replies(state, word),
                not word.common,
                word.reading,
            ),
        )
        return chosen.reading

    def _opponent_safe_replies(self, state: GameState, word: Word) -> int:
        return len(self.vocabulary.safe_moves(state.after(word)))


class _BudgetExhausted(Exception):
    pass


class SearchBot:
    """Iterative-deepening negamax with alpha-beta pruning.

    The fixed node budget, stable move ordering, and stable tie-breaking make
    the result reproducible. Terminal values are exact; positions at the depth
    boundary use a mobility heuristic.
    """

    def __init__(self, vocabulary: VocabularyGraph, node_budget: int = 10_000) -> None:
        if node_budget < 1:
            raise ValueError("node_budget must be positive")
        self.vocabulary = vocabulary
        self.node_budget = node_budget
        self.name = f"SearchBot-{node_budget // 1_000}K"
        self._nodes = 0
        self._table: dict[tuple[GameState, int], _TableEntry] = {}

    def choose(self, state: GameState) -> str | None:
        result = self.analyze(state)
        return None if result is None else result.word

    def analyze(self, state: GameState) -> SearchResult | None:
        legal = self.vocabulary.legal_moves(state)
        if not legal:
            return None

        fallback_reading = GreedyBot(self.vocabulary).choose(state)
        assert fallback_reading is not None
        best_word = self.vocabulary.word(fallback_reading)
        best_score = self._heuristic_after_move(state, best_word)
        completed_depth = 0
        self._nodes = 0
        self._table.clear()
        budget_exhausted = False

        # A game cannot exceed the number of unused words. In practice the
        # node budget stops iterative deepening much earlier.
        maximum_depth = self.vocabulary.remaining_word_count(state.used_words)
        for depth in range(1, maximum_depth + 1):
            try:
                word, score = self._search_root(state, depth)
            except _BudgetExhausted:
                budget_exhausted = True
                break
            best_word = word
            best_score = score
            completed_depth = depth
            if abs(score) >= MATE_SCORE - depth:
                break

        return SearchResult(
            word=best_word.reading,
            score=best_score,
            completed_depth=completed_depth,
            nodes=self._nodes,
            budget_exhausted=budget_exhausted,
        )

    def _search_root(self, state: GameState, depth: int) -> tuple[Word, int]:
        alpha = -MATE_SCORE
        beta = MATE_SCORE
        best_word: Word | None = None
        best_score = -MATE_SCORE

        for word in self._ordered_moves(state):
            self._consume_node()
            if word.immediately_loses:
                score = -MATE_SCORE
            else:
                score = -self._negamax(
                    state.after(word), depth - 1, -beta, -alpha, ply=1
                )
            if score > best_score:
                best_word = word
                best_score = score
            alpha = max(alpha, score)

        assert best_word is not None
        return best_word, best_score

    def _negamax(
        self,
        state: GameState,
        depth: int,
        alpha: int,
        beta: int,
        ply: int,
    ) -> int:
        self._consume_node()
        original_alpha = alpha
        original_beta = beta
        cache_key = (state, depth)
        cached = self._table.get(cache_key)
        if cached is not None:
            if cached.bound is _Bound.EXACT:
                return cached.value
            if cached.bound is _Bound.LOWER:
                alpha = max(alpha, cached.value)
            else:
                beta = min(beta, cached.value)
            if alpha >= beta:
                return cached.value

        legal = self.vocabulary.legal_moves(state)
        safe = tuple(word for word in legal if not word.immediately_loses)
        if not legal or not safe:
            return -MATE_SCORE + ply
        if depth == 0:
            return self._heuristic(state)

        value = -MATE_SCORE
        for word in self._ordered_moves(state, safe):
            score = -self._negamax(
                state.after(word), depth - 1, -beta, -alpha, ply + 1
            )
            value = max(value, score)
            alpha = max(alpha, score)
            if alpha >= beta:
                break

        if value <= original_alpha:
            bound = _Bound.UPPER
        elif value >= original_beta:
            bound = _Bound.LOWER
        else:
            bound = _Bound.EXACT
        self._table[cache_key] = _TableEntry(value, bound)
        return value

    def _ordered_moves(
        self,
        state: GameState,
        moves: tuple[Word, ...] | None = None,
    ) -> tuple[Word, ...]:
        candidates = moves if moves is not None else self.vocabulary.legal_moves(state)
        return tuple(
            sorted(
                candidates,
                key=lambda word: (
                    word.immediately_loses,
                    len(self.vocabulary.safe_moves(state.after(word))),
                    not word.common,
                    word.reading,
                ),
            )
        )

    def _heuristic_after_move(self, state: GameState, word: Word) -> int:
        if word.immediately_loses:
            return -MATE_SCORE
        return -self._heuristic(state.after(word))

    def _heuristic(self, state: GameState) -> int:
        safe = self.vocabulary.safe_moves(state)
        if not safe:
            return -MATE_SCORE

        # Evaluate from the perspective of the player whose turn it is.
        # Mobility is useful, while the minimum reply count measures whether
        # that player can immediately force a constrained kana.
        reply_counts = [
            len(self.vocabulary.safe_moves(state.after(word))) for word in safe
        ]
        common_moves = sum(word.common for word in safe)
        return 4 * len(safe) - 3 * min(reply_counts) + min(common_moves, 20)

    def _consume_node(self) -> None:
        if self._nodes >= self.node_budget:
            raise _BudgetExhausted
        self._nodes += 1
