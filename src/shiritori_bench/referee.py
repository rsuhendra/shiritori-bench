"""Deterministic move validation against a pinned SQLite vocabulary."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import sqlite3

from .normalize import initial_kana, is_hiragana_word, normalize_reading, terminal_kana


class MoveOutcome(StrEnum):
    VALID = "VALID"
    INVALID_WORD = "INVALID_WORD"
    WRONG_START = "WRONG_START"
    REPEATED_WORD = "REPEATED_WORD"
    ENDS_IN_N = "ENDS_IN_N"
    MALFORMED_OUTPUT = "MALFORMED_OUTPUT"
    PASS_WITH_LEGAL_MOVE = "PASS_WITH_LEGAL_MOVE"
    PASS_NO_LEGAL_MOVE = "PASS_NO_LEGAL_MOVE"


@dataclass(frozen=True)
class ValidationResult:
    outcome: MoveOutcome
    submitted: str
    normalized: str | None
    required_kana: str
    next_required_kana: str | None = None
    jmdict_id: int | None = None


class Referee:
    def __init__(self, database_path: str) -> None:
        self.connection = sqlite3.connect(database_path)
        self.connection.row_factory = sqlite3.Row

    def close(self) -> None:
        self.connection.close()

    def has_legal_move(self, required_kana: str, used_words: set[str]) -> bool:
        placeholders = ",".join("?" for _ in used_words)
        query = "SELECT 1 FROM words WHERE start_kana = ?"
        parameters: list[str] = [required_kana]
        if used_words:
            query += f" AND reading NOT IN ({placeholders})"
            parameters.extend(sorted(used_words))
        query += " LIMIT 1"
        return self.connection.execute(query, parameters).fetchone() is not None

    def validate(
        self,
        submitted: str,
        required_kana: str,
        used_words: set[str],
    ) -> ValidationResult:
        raw = submitted.strip()

        if raw == "PASS":
            outcome = (
                MoveOutcome.PASS_WITH_LEGAL_MOVE
                if self.has_legal_move(required_kana, used_words)
                else MoveOutcome.PASS_NO_LEGAL_MOVE
            )
            return ValidationResult(outcome, raw, None, required_kana)

        if "\n" in raw or not is_hiragana_word(raw):
            return ValidationResult(
                MoveOutcome.MALFORMED_OUTPUT, raw, None, required_kana
            )

        reading = normalize_reading(raw)
        if initial_kana(reading) != required_kana:
            return ValidationResult(
                MoveOutcome.WRONG_START, raw, reading, required_kana
            )

        if reading in used_words:
            return ValidationResult(
                MoveOutcome.REPEATED_WORD, raw, reading, required_kana
            )

        row = self.connection.execute(
            "SELECT jmdict_id, end_kana FROM words WHERE reading = ?",
            (reading,),
        ).fetchone()
        if row is None:
            return ValidationResult(
                MoveOutcome.INVALID_WORD, raw, reading, required_kana
            )

        ending = terminal_kana(reading)
        outcome = MoveOutcome.ENDS_IN_N if ending == "ん" else MoveOutcome.VALID
        return ValidationResult(
            outcome=outcome,
            submitted=raw,
            normalized=reading,
            required_kana=required_kana,
            next_required_kana=ending,
            jmdict_id=row["jmdict_id"],
        )

