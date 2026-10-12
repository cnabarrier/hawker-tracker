"""Tests for the "New visit needs a photo" reminder. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import sync  # noqa: E402


def centre(n, d, rated=True, name=None):
    c = {"n": n, "name": name or f"Centre {n}", "d": d}
    if rated:
        c["s"] = [7, 7, 7, 7, 7]
    return c


class Needed(unittest.TestCase):
    def test_newest_visits_without_a_photo_newest_first(self):
        cs = [centre(1, "2026-07-01"), centre(2, "2026-09-14"), centre(3, "2026-09-09")]
        self.assertEqual([c["n"] for c in sync.photos_needed(cs, {"1": {}})], [2, 3])

    def test_only_the_window_counts(self):
        cs = [centre(n, f"2026-08-{n:02d}") for n in range(1, 21)]
        need = sync.photos_needed(cs, {}, window=13)
        self.assertEqual(len(need), 13)
        self.assertEqual(need[0]["n"], 20)   # newest
        self.assertNotIn(1, [c["n"] for c in need])   # too old to reach the row

    def test_unrated_or_undated_centres_are_ignored(self):
        cs = [centre(1, "2026-09-20", rated=False), {"n": 2, "name": "No date", "s": [7] * 5}, centre(3, "2026-09-01")]
        self.assertEqual([c["n"] for c in sync.photos_needed(cs, {})], [3])

    def test_same_day_is_steady(self):
        cs = [centre(63, "2026-08-06"), centre(20, "2026-08-06")]
        self.assertEqual([c["n"] for c in sync.photos_needed(cs, {})], [20, 63])

    def test_all_covered_needs_nothing(self):
        cs = [centre(1, "2026-09-01"), centre(2, "2026-09-02")]
        self.assertEqual(sync.photos_needed(cs, {"1": {}, "2": {}}), [])

    def test_window_matches_the_page(self):
        with open(os.path.join(sync.ROOT, "index.html"), encoding="utf-8") as f:
            self.assertIn(f"const LV_COUNT = {sync.PHOTO_WINDOW - 1};", f.read())


class Check(unittest.TestCase):
    class Alerts:
        def __init__(self):
            self.log = []

        def problem(self, text):
            self.log.append(("problem", text))

        def healthy(self):
            self.log.append(("healthy",))

    def setUp(self):
        self.alerts = self.Alerts()

    def test_names_each_centre_in_the_issue(self):
        cs = [centre(25, "2026-09-09", name="Tanglin Halt Market")]
        sync.check_photos(cs, self.alerts, load=lambda: {})
        self.assertEqual(self.alerts.log, [("problem", "no photo yet for Tanglin Halt Market (#25, visited 2026-09-09)")])

    def test_closes_once_photos_are_in(self):
        sync.check_photos([centre(25, "2026-09-09")], self.alerts, load=lambda: {"25": {}})
        self.assertEqual(self.alerts.log, [("healthy",)])

    def test_unreadable_photos_file_is_only_logged(self):
        def broken():
            raise ValueError("bad json")
        sync.check_photos([centre(25, "2026-09-09")], self.alerts, load=broken)
        self.assertEqual(self.alerts.log, [])

    def test_no_ratings_yet_does_nothing(self):
        sync.check_photos(None, self.alerts, load=lambda: {})
        self.assertEqual(self.alerts.log, [])


if __name__ == "__main__":
    unittest.main()
