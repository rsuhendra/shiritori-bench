from collections import Counter
import unittest

from scripts.run_cognitive_bots import make_schedule


class CognitiveScheduleTests(unittest.TestCase):
    def test_default_schedule_has_balanced_pairings(self):
        schedule = make_schedule(["か", "さ", "ず"], 3, 17)
        self.assertEqual(len(schedule), 180)
        counts = Counter(tuple(sorted(s["profile"] for s in g["seats"])) for g in schedule)
        self.assertEqual(len(counts), 10)
        self.assertTrue(all(n == 18 for n in counts.values()))

    def test_swapping_preserves_each_profile_seed(self):
        schedule = make_schedule(["か"], 2, 17)
        for first, swapped in zip(schedule[::2], schedule[1::2]):
            self.assertEqual(first["seats"], swapped["seats"][::-1])
            self.assertNotEqual(first["seats"][0]["seed"], first["seats"][1]["seed"])

    def test_schedule_is_reproducible(self):
        self.assertEqual(make_schedule(["か", "ず"], 2, 17), make_schedule(["か", "ず"], 2, 17))


if __name__ == "__main__":
    unittest.main()
