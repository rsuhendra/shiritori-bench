"""Complete deterministic match execution and auditable result records."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Callable
import uuid

from .players import Player, TurnContext
from .referee import MoveOutcome, Referee, ValidationResult
from .http_retry import RetryExhausted


class MatchOutcome(StrEnum):
    PLAYER_ONE_WIN = "PLAYER_ONE_WIN"
    PLAYER_TWO_WIN = "PLAYER_TWO_WIN"
    TURN_LIMIT_DRAW = "TURN_LIMIT_DRAW"
    PLAYER_ERROR = "PLAYER_ERROR"


@dataclass(frozen=True, slots=True)
class TurnRecord:
    turn: int
    player_index: int
    player_name: str
    required_kana: str
    submitted: str
    normalized: str | None
    outcome: str
    next_required_kana: str | None
    jmdict_id: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MatchRecord:
    schema_version: int
    match_id: str
    started_at: str
    vocabulary_version: str
    opening_kana: str
    turn_limit: int
    players: tuple[dict[str, str], dict[str, str]]
    outcome: str
    winner_index: int | None
    loser_index: int | None
    ending: str
    turns: tuple[TurnRecord, ...]
    error_metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MatchRunner:
    def __init__(
        self,
        referee: Referee,
        *,
        vocabulary_version: str,
        turn_limit: int = 100,
    ) -> None:
        if turn_limit < 1:
            raise ValueError("turn_limit must be positive")
        self.referee = referee
        self.vocabulary_version = vocabulary_version
        self.turn_limit = turn_limit

    def run(
        self,
        player_one: Player,
        player_two: Player,
        *,
        opening_kana: str,
        match_id: str | None = None,
        on_turn: Callable[[TurnRecord], None] | None = None,
    ) -> MatchRecord:
        players = (player_one, player_two)
        required_kana = opening_kana
        used_words: set[str] = set()
        turns: list[TurnRecord] = []
        started_at = datetime.now(timezone.utc).isoformat()

        for turn_number in range(1, self.turn_limit + 1):
            player_index = (turn_number - 1) % 2
            player = players[player_index]
            context = TurnContext(
                required_kana=required_kana,
                used_words=frozenset(used_words),
                vocabulary_version=self.vocabulary_version,
                turn_number=turn_number,
                history=tuple(t.normalized for t in turns if t.outcome == "VALID" and t.normalized is not None),
            )
            try:
                response = player.play(context)
            except Exception as error:  # preserved as a match result for batch runs
                return self._finish(
                    match_id=match_id,
                    started_at=started_at,
                    opening_kana=opening_kana,
                    players=players,
                    turns=turns,
                    outcome=MatchOutcome.PLAYER_ERROR,
                    winner_index=None,
                    loser_index=player_index,
                    ending=f"PLAYER_ERROR:{type(error).__name__}:{error}",
                    error_metadata=error.transport_metadata if isinstance(error, RetryExhausted) else None,
                )

            validation = self.referee.validate(
                response.text, required_kana, used_words
            )
            turns.append(
                self._turn_record(
                    turn_number, player_index, player.name, validation, response.metadata
                )
            )
            if on_turn is not None:
                on_turn(turns[-1])

            if response.metadata.get("finish_reason") in {
                "length", "content_filter", "tool_calls",
                "insufficient_system_resource", "aborted",
            }:
                return self._finish(
                    match_id=match_id, started_at=started_at,
                    opening_kana=opening_kana, players=players, turns=turns,
                    outcome=MatchOutcome.PLAYER_ERROR, winner_index=None,
                    loser_index=player_index,
                    ending=f"GENERATION_ERROR:{response.metadata['finish_reason']}",
                )

            if validation.outcome is MoveOutcome.VALID:
                assert validation.normalized is not None
                assert validation.next_required_kana is not None
                used_words.add(validation.normalized)
                required_kana = validation.next_required_kana
                continue

            winner_index = 1 - player_index
            outcome = (
                MatchOutcome.PLAYER_ONE_WIN
                if winner_index == 0
                else MatchOutcome.PLAYER_TWO_WIN
            )
            return self._finish(
                match_id=match_id,
                started_at=started_at,
                opening_kana=opening_kana,
                players=players,
                turns=turns,
                outcome=outcome,
                winner_index=winner_index,
                loser_index=player_index,
                ending=validation.outcome.value,
            )

        return self._finish(
            match_id=match_id,
            started_at=started_at,
            opening_kana=opening_kana,
            players=players,
            turns=turns,
            outcome=MatchOutcome.TURN_LIMIT_DRAW,
            winner_index=None,
            loser_index=None,
            ending=MatchOutcome.TURN_LIMIT_DRAW.value,
        )

    @staticmethod
    def _turn_record(
        turn: int,
        player_index: int,
        player_name: str,
        validation: ValidationResult,
        metadata: dict[str, Any],
    ) -> TurnRecord:
        return TurnRecord(
            turn=turn,
            player_index=player_index,
            player_name=player_name,
            required_kana=validation.required_kana,
            submitted=validation.submitted,
            normalized=validation.normalized,
            outcome=validation.outcome.value,
            next_required_kana=validation.next_required_kana,
            jmdict_id=validation.jmdict_id,
            metadata=metadata,
        )

    def _finish(
        self,
        *,
        match_id: str | None,
        started_at: str,
        opening_kana: str,
        players: tuple[Player, Player],
        turns: list[TurnRecord],
        outcome: MatchOutcome,
        winner_index: int | None,
        loser_index: int | None,
        ending: str,
        error_metadata: dict[str, Any] | None = None,
    ) -> MatchRecord:
        return MatchRecord(
            schema_version=1,
            match_id=match_id or str(uuid.uuid4()),
            started_at=started_at,
            vocabulary_version=self.vocabulary_version,
            opening_kana=opening_kana,
            turn_limit=self.turn_limit,
            players=(
                {"name": players[0].name, "kind": players[0].kind},
                {"name": players[1].name, "kind": players[1].kind},
            ),
            outcome=outcome.value,
            winner_index=winner_index,
            loser_index=loser_index,
            ending=ending,
            turns=tuple(turns),
            error_metadata=error_metadata,
        )
