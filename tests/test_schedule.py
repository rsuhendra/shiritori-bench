from __future__ import annotations

import unittest

from shiritori_bench.schedule import round_robin_schedule


class ScheduleTests(unittest.TestCase):
    def test_balances_both_player_orders(self) -> None:
        schedule = round_robin_schedule(
            ["a", "b", "c"], ["か", "さ"], repetitions=2
        )

        self.assertEqual(len(schedule), 24)
        self.assertEqual(
            sum(match.player_one == "a" and match.player_two == "b" for match in schedule),
            4,
        )
        self.assertEqual(
            sum(match.player_one == "b" and match.player_two == "a" for match in schedule),
            4,
        )


if __name__ == "__main__":
    unittest.main()
