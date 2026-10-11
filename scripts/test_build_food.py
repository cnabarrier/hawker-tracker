"""Tests for the dish-sheet converter and its sync guard. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SheetError  # noqa: E402
from build_food import build, price, price_options, rows_from_html  # noqa: E402
from sync import describe_food, guard_food  # noqa: E402

HEAD = '"Hawker","Stall Name","Dish","Price","Notes"\n'


def sheet(*rows, head=HEAD):
    return head + "".join(",".join(f'"{v}"' for v in r) + "\n" for r in rows)


SAMPLE = sheet(
    ["Red Hill Food Centre", "Redhill Pork Porridge #01-46", "Pork Porridge", "$4.00", ""],
    ["", "Xi De Li #01-14", "Youtiao", "$1.10", ""],
    ["", "", "Butterfly Bun", "$1.20", ""],
    ["Newton Food Centre ", "??", "Sugarcane Juice (Big Cup)", "$4.20", ""],
    ["Toa Payoh Lorong 8 Market & Hawker Centre", "Hock Kee #01-64", "Bak Kut Teh ", "", "price depending on portion size"],
    ["Kovan 209 Market & Food Centre", "", "", "", ""],
)


class Converter(unittest.TestCase):
    def test_centre_and_stall_carry_down(self):
        dishes, warnings = build(SAMPLE)
        self.assertEqual(warnings, [])
        self.assertEqual([(d["n"], d["st"], d["d"]) for d in dishes[:3]], [
            ([86], "Redhill Pork Porridge #01-46", "Pork Porridge"),
            ([86], "Xi De Li #01-14", "Youtiao"),
            ([86], "Xi De Li #01-14", "Butterfly Bun")])

    def test_new_centre_does_not_inherit_the_previous_stall(self):
        rows = sheet(["Maxwell Food Centre", "One Soy #01-12", "Soy Milk", "$2.50", ""],
                     ["Tiong Bahru Market", "", "Mystery Dish", "$3.00", ""])
        self.assertEqual(build(rows)[0][1]["st"], "")

    def test_text_is_trimmed_and_unknowns_blanked(self):
        newton, tpy = build(SAMPLE)[0][3:5]
        self.assertEqual((newton["n"], newton["h"], newton["st"]), ([19], "Newton Food Centre", ""))
        self.assertEqual((tpy["d"], tpy["p"], tpy["pt"], tpy["no"]),
                         ("Bak Kut Teh", None, "", "price depending on portion size"))

    def test_rows_without_a_dish_are_skipped(self):
        self.assertEqual(len(build(SAMPLE)[0]), 5)  # Kovan has a name but no dishes yet

    def test_prices(self):
        self.assertEqual(price("$4.00"), 4.0)
        self.assertEqual(price("$61.00"), 61.0)
        self.assertEqual(price("4.5"), 4.5)
        self.assertIsNone(price("$1-3"))
        self.assertIsNone(price(""))
        # her own text is kept for display; only a single amount becomes a number for the totals
        unknown = build(sheet(["Maxwell Food Centre", "X", "Y", "??", ""]))[0][0]
        self.assertEqual((unknown["pt"], unknown["p"]), ("??", None))
        ranged = build(sheet(["Maxwell Food Centre", "X", "Carrot Cake", "$3.50/4/5", "price depending on portion size"]))[0][0]
        self.assertEqual((ranged["pt"], ranged["p"], ranged["no"]), ("$3.50/4/5", None, "price depending on portion size"))
        self.assertEqual(ranged["pr"], [3.5, 5.0])   # lowest and highest of her options, for a range total
        self.assertNotIn("pr", unknown)
        self.assertEqual(price_options("$4/5/6"), [4.0, 6.0])
        self.assertIsNone(price_options("$4.00"))
        self.assertIsNone(price_options("4/abc"))

    def test_web_view_keeps_every_cell_as_written(self):
        """Google's CSV export blanks '$3.50/4/5' and '??'; the sheet's web view keeps them."""
        html = ('<table class="waffle"><thead><tr><th></th><th>A</th><th>B</th><th>C</th><th>D</th><th>E</th></tr></thead><tbody>'
                '<tr><th><div>1</div></th><td>Hawker</td><td>Stall Name</td><td>Dish</td><td>Price</td><td>Notes</td></tr>'
                '<tr><th><div>2</div></th><td rowspan="3">Ghim Moh Market &amp; Food Centre</td><td>Tom&#39;s Mee Pok #01-11</td>'
                '<td>Bak Chor Mee </td><td>$4.00</td><td></td></tr>'
                '<tr><th><div>3</div></th><td>Ghim Moh Carrot Cake #01-16</td><td>Carrot Cake (Mixed)</td><td>$3.50/4/5</td>'
                '<td class="softmerge"><div class="softmerge-inner">price depending on portion size</div></td></tr>'
                '<tr><th><div>4</div></th><td>??</td><td>Chee Cheong<br>Fun</td><td>??</td><td></td></tr>'
                '</tbody></table>')
        rows = rows_from_html(html)
        self.assertEqual(rows[0], ["Hawker", "Stall Name", "Dish", "Price", "Notes"])
        self.assertEqual(rows[2], ["", "Ghim Moh Carrot Cake #01-16", "Carrot Cake (Mixed)", "$3.50/4/5", "price depending on portion size"])
        dishes, _ = build(rows=rows)
        self.assertEqual([(d["h"], d["st"], d["d"], d["pt"], d["p"]) for d in dishes], [
            ("Ghim Moh Market & Food Centre", "Tom's Mee Pok #01-11", "Bak Chor Mee", "$4.00", 4.0),
            ("Ghim Moh Market & Food Centre", "Ghim Moh Carrot Cake #01-16", "Carrot Cake (Mixed)", "$3.50/4/5", None),
            ("Ghim Moh Market & Food Centre", "", "Chee Cheong Fun", "??", None)])

    def test_web_view_without_a_dish_table_is_a_sheet_error(self):
        with self.assertRaises(SheetError):
            rows_from_html("<html><body>Sign in</body></html>")

    def test_whampoa_is_split_by_stall(self):
        rows = sheet(["Whampoa Makan Place", "Beach Road Fish Head Bee Hoon #01-46", "Sliced Fish Bee Hoon", "$8.00", ""],
                     ["", "Dapo (Teochew Street) Braised Duck & Porridge #01-10", "Braised Duck", "$4.50", ""],
                     ["", "Brand New Stall #01-99", "Something", "$5.00", ""])
        dishes, warnings = build(rows)
        self.assertEqual([d["n"] for d in dishes], [[107], [106], [106, 107]])
        self.assertEqual(len(warnings), 1)
        self.assertIn("Brand New Stall", warnings[0])

    def test_lookalike_names_are_never_guessed(self):
        # Shared words linked the wrong centres when matching was fuzzy; only exact aliases count.
        for name in ["Geylang Bahru Food Centre", "Ang Mo Kio Ave 10 Food Centre", "Hougang 105"]:
            dishes, warnings = build(sheet([name, "Stall", "Dish", "$1.00", ""]))
            self.assertEqual(dishes[0]["n"], [])
            self.assertEqual(len(warnings), 1)

    def test_unknown_centre_warns_once(self):
        rows = sheet(["Old Airport Road Food Centre", "A", "Dish 1", "$1.00", ""], ["", "B", "Dish 2", "$2.00", ""])
        dishes, warnings = build(rows)
        self.assertEqual(len(dishes), 2)
        self.assertEqual(len(warnings), 1)

    def test_columns_found_by_heading_even_if_moved_or_added(self):
        head = '"Dish","Hawker","VOD link","Stall Name","Notes","Price"\n'
        rows = head + '"Pork Porridge","Red Hill Food Centre","https://youtu.be/x","Redhill Pork Porridge","","$4.00"\n'
        d = build(rows)[0][0]
        self.assertEqual((d["n"], d["d"], d["st"], d["p"]), ([86], "Pork Porridge", "Redhill Pork Porridge", 4.0))
        self.assertNotIn("VOD link", d)

    def test_missing_heading_is_an_error(self):
        with self.assertRaises(SheetError):
            build(sheet(["Maxwell Food Centre", "X", "Y", "$1", ""], head='"Hawker","Stall","Dish","Price","Notes"\n'))

    def test_dish_before_any_centre_is_an_error(self):
        with self.assertRaises(SheetError):
            build(sheet(["", "Stall", "Dish", "$1.00", ""]))

    def test_empty_sheet_is_an_error(self):
        with self.assertRaises(SheetError):
            build(HEAD)

    def test_alias_to_a_missing_centre_is_an_error(self):
        with self.assertRaises(SheetError):
            build(SAMPLE, known=[19, 102])  # 86 is missing


class Guards(unittest.TestCase):
    def dishes(self, k):
        return [{"n": [1], "h": "C", "st": "S", "d": f"Dish {i}", "p": 1.0, "pt": "$1", "no": ""} for i in range(k)]

    def test_big_drop_is_refused(self):
        with self.assertRaises(SheetError):
            guard_food(self.dishes(92), self.dishes(60))

    def test_small_drop_and_first_sync_are_fine(self):
        guard_food(self.dishes(92), self.dishes(80))
        guard_food(None, self.dishes(5))

    def test_describe(self):
        self.assertEqual(describe_food(None, self.dishes(92)), "Dishes: first sync from Masked's sheet (92 dishes)")
        self.assertEqual(describe_food(self.dishes(90), self.dishes(92)), "Dishes: +2 from Masked's sheet (92 in all)")
        self.assertEqual(describe_food(self.dishes(92), self.dishes(91)), "Dishes: -1 from Masked's sheet (91 in all)")
        old = self.dishes(3)
        new = [dict(d) for d in old]
        new[0]["pt"] = "$2"
        self.assertEqual(describe_food(old, new), "Dishes: edits from Masked's sheet (3 in all)")


if __name__ == "__main__":
    unittest.main()
