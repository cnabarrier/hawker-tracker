"""Tests for the sheet converter and sync guards. Run: python -m unittest discover -s scripts"""
import datetime as dt
import io
import os
import sys
import unittest

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SheetError, build, tier  # noqa: E402
from sync import describe, guard  # noqa: E402

TODAY = dt.date(2026, 9, 24)
HEADER = ["S/N", "Hawker Centre Name", "Address", "Food Variation 🫦/10", "Quality 👅/10",
          "Price 💸/10", "Comfy 🫶🏼/10", "Uniqueness 🍽/10", "Total Score/50", "Overall Rank",
          "Best time to go", "Notes", "Date Visited"]


def make_rows(n=110):
    rows = [[i, f"Centre {i}", f"{i}, Some Road, S(000{i:03})"] + [None] * 10 for i in range(1, n + 1)]
    rows[3][3:13] = [6, 7.5, 10, 9, 5, 37.5, "B", "AM to 5pm", "DYSON DRYER", dt.datetime(2026, 4, 20)]
    rows[13][3:13] = [10, 9, 8, 8.5, 6.5, 42, "A", "All Day ", "Wings BOMB \nNoodles yum", "2 Sept 2026"]
    return rows


def workbook(rows, header=HEADER, top=True, tab="Hawker Centre Ratings"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = tab
    if top:
        ws.append(["Singapore Hawker Centre Rating Tracker"])
        ws.append(["Official NEA list"])
        ws.append(["Scale", "10 = S Rank"])
    ws.append(header)
    for r in rows:
        ws.append(r)
    wb.create_sheet("Summary")
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def run(rows, **kw):
    return build(workbook(rows, **kw), today=TODAY)


def centre(centres, n):
    return next(c for c in centres if c["n"] == n)


def set_row(rows, n, values):
    rows[n - 1][3:13] = values


class Baseline(unittest.TestCase):
    def test_shapes_match_snapshot_conventions(self):
        centres, warnings = run(make_rows())
        self.assertEqual(warnings, [])
        self.assertEqual(len(centres), 110)
        self.assertEqual(centres[0], {"n": 1, "name": "Centre 1", "addr": "1, Some Road, S(000001)"})
        self.assertEqual(centre(centres, 4), {
            "n": 4, "name": "Centre 4", "addr": "4, Some Road, S(000004)", "s": [6, 7.5, 10, 9, 5],
            "t": 37.5, "rk": "B", "best": "AM to 5pm", "note": "DYSON DRYER", "d": "2026-04-20"})

    def test_text_is_trimmed_and_line_breaks_become_dots(self):
        c = centre(run(make_rows())[0], 14)
        self.assertEqual(c["best"], "All Day")
        self.assertEqual(c["note"], "Wings BOMB · Noodles yum")
        self.assertEqual(c["d"], "2026-09-02")

    def test_whole_numbers_are_ints(self):
        c = centre(run(make_rows())[0], 14)
        self.assertIsInstance(c["t"], int)
        self.assertEqual(c["s"], [10, 9, 8, 8.5, 6.5])

    def test_columns_found_by_name_even_if_reordered(self):
        order = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 12, 11, 10]  # swap Best time and Date Visited
        rows = [[r[i] for i in order] for r in make_rows()]
        centres, _ = run(rows, header=[HEADER[i] for i in order])
        self.assertEqual(centre(centres, 14)["d"], "2026-09-02")
        self.assertEqual(centre(centres, 14)["best"], "All Day")

    def test_header_row_located_without_title_rows(self):
        self.assertEqual(len(run(make_rows(), top=False)[0]), 110)


class Dates(unittest.TestCase):
    def date_of(self, value):
        rows = make_rows()
        rows[3][12] = value
        return centre(run(rows)[0], 4).get("d")

    def test_accepted_forms(self):
        for v in ["2 Sept 2026", "2 Sep 2026", "2 September 2026", "2nd Sept 2026", "02 sept 2026",
                  "2 Sept, 2026", "2026-09-02", "2/9/2026", dt.datetime(2026, 9, 2), dt.date(2026, 9, 2)]:
            with self.subTest(v=v):
                self.assertEqual(self.date_of(v), "2026-09-02")

    def test_blank_date_is_omitted(self):
        self.assertIsNone(self.date_of(None))
        self.assertIsNone(self.date_of("  "))

    def test_unreadable_or_impossible_dates_block_publishing(self):
        for v in ["Sept 2 2026", "yesterday", "31 Sept 2026", "2 Spt 2026", "30/2/2026",
                  "2 Oct 2026", "2 Sept 2023", "2/9/26", 12]:
            with self.subTest(v=v), self.assertRaises(SheetError):
                self.date_of(v)


class Scores(unittest.TestCase):
    def test_partial_scores_stay_unrated_with_warning(self):
        rows = make_rows()
        set_row(rows, 20, [7, 8, None, None, None, 15, "F", "Lunch", "in progress", None])
        centres, warnings = run(rows)
        c = centre(centres, 20)
        self.assertNotIn("s", c)
        self.assertEqual(c["note"], "in progress")
        self.assertTrue(any("2/5 scores" in w for w in warnings))

    def test_total_must_equal_sum(self):
        rows = make_rows()
        set_row(rows, 4, [6, 7.5, 10, 9, 5, 38, "B", "", "", None])
        with self.assertRaisesRegex(SheetError, "does not equal"):
            run(rows)

    def test_blank_total_uses_sum_with_warning(self):
        rows = make_rows()
        set_row(rows, 4, [6, 7.5, 10, 9, 5, None, None, "", "", None])
        centres, warnings = run(rows)
        self.assertEqual((centre(centres, 4)["t"], centre(centres, 4)["rk"]), (37.5, "B"))
        self.assertTrue(warnings)

    def test_rank_must_match_total(self):
        rows = make_rows()
        set_row(rows, 4, [6, 7.5, 10, 9, 5, 37.5, "A", "", "", None])
        with self.assertRaisesRegex(SheetError, "does not match"):
            run(rows)

    def test_low_total_with_blank_rank_is_F(self):
        rows = make_rows()
        set_row(rows, 4, [4, 4, 4, 4, 4, 20, None, "", "", None])
        centres, warnings = run(rows)
        self.assertEqual(centre(centres, 4)["rk"], "F")
        self.assertEqual(warnings, [])

    def test_rated_centre_always_has_note_and_best_strings(self):
        rows = make_rows()
        set_row(rows, 4, [6, 7.5, 10, 9, 5, 37.5, "B", None, None, None])
        c = centre(run(rows)[0], 4)
        self.assertEqual((c["best"], c["note"]), ("", ""))
        self.assertNotIn("d", c)

    def test_scores_must_be_numbers_in_range(self):
        for bad in ["7.5", "seven", 11, -1, True]:
            rows = make_rows()
            rows[3][4] = bad
            with self.subTest(bad=bad), self.assertRaises(SheetError):
                run(rows)

    def test_tier_boundaries_follow_her_formula(self):
        cases = {50: "S", 45: "S", 44.5: "A", 40: "A", 39.5: "B", 35: "B", 34.5: "C", 30: "C",
                 29.5: "D", 21: "D", 20.5: "F", 0: "F"}
        for total, rk in cases.items():
            with self.subTest(total=total):
                self.assertEqual(tier(total), rk)


class Structure(unittest.TestCase):
    def test_missing_or_renamed_column_blocks(self):
        header = list(HEADER)
        header[3] = "Variety"
        with self.assertRaisesRegex(SheetError, "food variation"):
            run(make_rows(), header=header)

    def test_missing_tab_blocks(self):
        with self.assertRaisesRegex(SheetError, "not found"):
            run(make_rows(), tab="Sheet1")

    def test_gap_in_rows_blocks_but_trailing_blanks_ok(self):
        rows = make_rows()
        run(rows + [[None] * 13, [None] * 13])
        rows.insert(50, [None] * 13)
        with self.assertRaisesRegex(SheetError, "empty"):
            run(rows)

    def test_duplicates_and_bad_serials_block(self):
        rows = make_rows()
        rows[5][0] = 5
        with self.assertRaisesRegex(SheetError, "twice"):
            run(rows)
        rows = make_rows()
        rows[5][1] = "Centre 5"
        with self.assertRaisesRegex(SheetError, "twice"):
            run(rows)
        rows = make_rows()
        rows[5][0] = "6a"
        with self.assertRaisesRegex(SheetError, "whole number"):
            run(rows)

    def test_truncated_sheet_blocks(self):
        with self.assertRaisesRegex(SheetError, "only 50"):
            run(make_rows(50))

    def test_non_workbook_download_blocks(self):
        with self.assertRaisesRegex(SheetError, "not a readable workbook"):
            build(b"<html>Sign in</html>")

    def test_new_centre_added_is_published(self):
        rows = make_rows()
        rows.append([111, "Brand New Hawker Centre", "1 New Road"] + [None] * 10)
        self.assertEqual(run(rows)[0][-1]["name"], "Brand New Hawker Centre")


class SyncGuards(unittest.TestCase):
    def test_large_drop_in_rated_blocks(self):
        old = [{"n": i, "s": [1] * 5} for i in range(10)]
        guard(old, old[:7])  # 3 un-rated in one go is allowed
        with self.assertRaises(SheetError):
            guard(old, old[:6])

    def test_describe(self):
        old = run(make_rows())[0]
        rows = make_rows()
        set_row(rows, 30, [8, 8, 8, 8, 8, 40, "A", "Lunch", "Nice", "20 Sept 2026"])
        rows[3][11] = "changed note"
        new = run(rows)[0]
        self.assertEqual(describe(old, new), "Ratings: updated Centre 4; rated Centre 30 (40, A)")


if __name__ == "__main__":
    unittest.main()
