"""Deterministic balanced schedule construction."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations


@dataclass(frozen=True, slots=True)
class ScheduledMatch:
    player_one: str
    player_two: str
    opening_kana: str
    repetition: int

    @property
    def match_id(self) -> str:
        return (
            f"{self.player_one}__{self.player_two}__"
            f"{self.opening_kana}__r{self.repetition}"
        )


def round_robin_schedule(
    player_ids: list[str],
    opening_kana: list[str],
    *,
    repetitions: int = 1,
) -> list[ScheduledMatch]:
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not opening_kana:
        raise ValueError("at least one opening kana is required")

    schedule: list[ScheduledMatch] = []
    for left, right in combinations(sorted(player_ids), 2):
        for opening in opening_kana:
            for repetition in range(1, repetitions + 1):
                schedule.append(ScheduledMatch(left, right, opening, repetition))
                schedule.append(ScheduledMatch(right, left, opening, repetition))
    return schedule
