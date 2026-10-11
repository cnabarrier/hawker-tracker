"""Tests for attaching video moments to dishes. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SheetError  # noqa: E402
from build_moments import apply, parse_link, seconds  # noqa: E402

V1, V2, V3 = "AAAAAAAAAAA", "BBBBBBBBBBB", "CCCCCCCCCCC"
VIDEOS = [{"id": V1, "n": [18]}, {"id": V2, "n": [18]}, {"id": V3, "n": [26]}]


def dish(n, d, st=""):
    return {"n": [n], "h": "x", "st": st, "d": d, "p": None, "pt": "", "no": ""}


DISHES = [dish(18, "Chicken Rice", "Tian Tian #01-10"), dish(18, "Kopi", "Ah Seng #01-01"),
          dish(18, "Kopi", "Zhen Zhen #01-02"), dish(26, "Chicken Rice"), dish(18, "Curry Puff (Chicken & Egg)")]
HEAD = "Video link,Dish\n"


class Links(unittest.TestCase):
    def test_time_forms(self):
        self.assertEqual([seconds(t) for t in ["515", "515s", "8m35s", "1h2m3s", "8m", ""]], [515, 515, 515, 3723, 480, None])
        self.assertIsNone(seconds("abc"))

    def test_link_forms(self):
        self.assertEqual(parse_link(f"https://youtu.be/{V1}?si=xyz&t=515"), (V1, 515))
        self.assertEqual(parse_link(f"https://www.youtube.com/watch?v={V1}&t=8m35s"), (V1, 515))
        self.assertEqual(parse_link(f"https://m.youtube.com/watch?v={V1}#t=60"), (V1, 60))
        self.assertEqual(parse_link(f"https://www.youtube-nocookie.com/embed/{V1}?start=90"), (V1, 90))
        self.assertEqual(parse_link(f"https://youtu.be/{V1}"), (V1, None))
        self.assertEqual(parse_link("https://example.com/watch?v=AAAAAAAAAAA&t=5"), (None, None))
        self.assertEqual(parse_link("Chicken rice"), (None, None))


class Apply(unittest.TestCase):
    def run_sheet(self, *rows, head=HEAD):
        return apply(DISHES, head + "".join(",".join(f'"{c}"' for c in r) + "\n" for r in rows), VIDEOS)

    def test_attaches_to_the_dish_at_that_videos_centre(self):
        out, warnings = self.run_sheet([f"https://youtu.be/{V3}?t=100", "chicken  rice"])
        self.assertEqual(warnings, [])
        self.assertEqual(out[3]["w"], [V3, 100])
        self.assertNotIn("w", out[0])  # same name at another centre is untouched

    def test_two_videos_for_one_centre_each_keep_their_own(self):
        out, warnings = self.run_sheet([f"https://youtu.be/{V1}?t=10", "Chicken Rice"],
                                       [f"https://youtu.be/{V2}?t=20", "Curry Puff (Chicken and Egg)"])
        self.assertEqual(warnings, [])
        self.assertEqual((out[0]["w"], out[4]["w"]), ([V1, 10], [V2, 20]))

    def test_same_name_twice_needs_the_stall(self):
        out, warnings = self.run_sheet([f"https://youtu.be/{V1}?t=10", "Kopi"])
        self.assertIn("matches 2 dishes", warnings[0])
        self.assertFalse(any("w" in d for d in out))
        out, warnings = apply(DISHES, f'Video link,Dish,Stall\n"https://youtu.be/{V1}?t=10",Kopi,Zhen Zhen\n', VIDEOS)
        self.assertEqual(warnings, [])
        self.assertEqual(out[2]["w"], [V1, 10])

    def test_never_guessed(self):
        _, warnings = self.run_sheet([f"https://youtu.be/{V1}", "Chicken Rice"],               # no time
                                     [f"https://youtu.be/DDDDDDDDDDD?t=5", "Chicken Rice"],   # not 4ever's
                                     [f"https://youtu.be/{V1}?t=5", "Laksa"],                 # not on her list
                                     [f"https://youtu.be/{V3}?t=5", "Kopi"],                  # wrong centre
                                     ["not a link", "Chicken Rice"])
        self.assertEqual(len(warnings), 5)
        self.assertIn("no time", warnings[0])
        self.assertIn("not one of 4ever's edits", warnings[1])
        self.assertIn("isn't on Masked's list", warnings[2])
        self.assertIn("isn't on Masked's list", warnings[3])
        self.assertIn("not a YouTube video link", warnings[4])

    def test_first_row_wins_for_a_dish(self):
        out, warnings = self.run_sheet([f"https://youtu.be/{V1}?t=10", "Chicken Rice"],
                                       [f"https://youtu.be/{V1}?t=99", "Chicken Rice"])
        self.assertEqual(out[0]["w"], [V1, 10])
        self.assertIn("already has a moment on row 2", warnings[0])

    def test_old_times_are_replaced_and_inputs_untouched(self):
        old = [dict(DISHES[0], w=[V1, 5])] + DISHES[1:]
        out, _ = apply(old, HEAD, VIDEOS)
        self.assertNotIn("w", out[0])
        self.assertEqual(old[0]["w"], [V1, 5])

    def test_blank_rows_and_column_order(self):
        out, warnings = apply(DISHES, f'Dish,Notes,Video link\n,,\n"Chicken Rice",x,"https://youtu.be/{V1}?t=3"\n', VIDEOS)
        self.assertEqual((warnings, out[0]["w"]), ([], [V1, 3]))

    def test_missing_headings_is_a_sheet_error(self):
        with self.assertRaises(SheetError):
            apply(DISHES, "Link,Food\n", VIDEOS)
        with self.assertRaises(SheetError):
            apply(DISHES, "", VIDEOS)


class Sync(unittest.TestCase):
    """sync.with_moments: Masked's dishes always publish; times come and go only with Gummy's sheet."""

    class Alerts:
        def __init__(self):
            self.log = []

        def problem(self, text):
            self.log.append(("problem", text))

        def healthy(self):
            self.log.append(("healthy",))

    def setUp(self):
        import build_videos
        import sync
        self.sync, self.alerts = sync, self.Alerts()
        self._id, self._load = sync.MOMENTS_ID, build_videos.load
        sync.MOMENTS_ID = "sheet"
        build_videos.load = lambda: VIDEOS

    def tearDown(self):
        import build_videos
        self.sync.MOMENTS_ID, build_videos.load = self._id, self._load

    def test_attaches_and_reports_healthy(self):
        out = self.sync.with_moments(DISHES, None, self.alerts, get=lambda url, what: f'{HEAD}"https://youtu.be/{V1}?t=7",Chicken Rice\n')
        self.assertEqual(out[0]["w"], [V1, 7])
        self.assertEqual(self.alerts.log, [("healthy",)])

    def test_unreadable_sheet_keeps_last_times(self):
        old = [dict(DISHES[0], w=[V1, 7])] + DISHES[1:]

        def down(url, what):
            raise ConnectionError("offline")
        out = self.sync.with_moments(DISHES, old, self.alerts, get=down)
        self.assertEqual(out[0]["w"], [V1, 7])
        out = self.sync.with_moments(DISHES, old, self.alerts, get=lambda url, what: "Nope\n")
        self.assertEqual(out[0]["w"], [V1, 7])
        self.assertEqual(self.alerts.log[0][0], "problem")

    def test_unmatched_rows_raise_an_issue_but_dishes_publish(self):
        out = self.sync.with_moments(DISHES, None, self.alerts, get=lambda url, what: f'{HEAD}"https://youtu.be/{V1}?t=7",Laksa\n')
        self.assertEqual(len(out), len(DISHES))
        self.assertIn("Laksa", self.alerts.log[0][1])

    def test_no_file_and_no_sheet_changes_nothing(self):
        self.sync.MOMENTS_ID, file = "", self.sync.MOMENTS_FILE
        self.sync.MOMENTS_FILE = os.path.join(os.path.dirname(__file__), "no-such-moments.csv")
        try:
            self.assertEqual(self.sync.with_moments(DISHES, None, self.alerts), DISHES)
        finally:
            self.sync.MOMENTS_FILE = file

    def test_reads_moments_csv_in_the_repo(self):
        import tempfile
        self.sync.MOMENTS_ID, file = "", self.sync.MOMENTS_FILE
        with tempfile.TemporaryDirectory() as d:
            self.sync.MOMENTS_FILE = os.path.join(d, "moments.csv")
            with open(self.sync.MOMENTS_FILE, "w", encoding="utf-8") as f:
                f.write(f'Video link,Dish,Stall,Evidence\n"https://youtu.be/{V3}?t=42",Chicken Rice,,"0:42 quote"\n')
            try:
                out = self.sync.with_moments(DISHES, None, self.alerts)
            finally:
                self.sync.MOMENTS_FILE = file
        self.assertEqual(out[3]["w"], [V3, 42])
        self.assertEqual(self.alerts.log, [("healthy",)])

    def test_the_real_moments_file_matches_the_real_dishes(self):
        """Guards moments.csv itself: every row must attach to one of Masked's dishes in one of 4ever's videos."""
        import json
        import build_videos
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if not os.path.exists(os.path.join(root, "food.json")):
            self.skipTest("no food.json")
        with open(os.path.join(root, "food.json"), encoding="utf-8") as f:
            dishes = json.load(f)["dishes"]
        with open(os.path.join(root, "moments.csv"), encoding="utf-8") as f:
            out, warnings = apply(dishes, f.read(), self._load())
        self.assertEqual(warnings, [])
        self.assertTrue(all(isinstance(d["w"][1], int) for d in out if "w" in d))


if __name__ == "__main__":
    unittest.main()
