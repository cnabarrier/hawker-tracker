"""Tests for linking 4ever's edits to centres. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempfile  # noqa: E402
from build_videos import build, chapters, describe, load, match, names, parse_feed, parse_seed, update  # noqa: E402

CENTRES = [
    {"n": 3, "name": "Bedok Food Centre"},
    {"n": 14, "name": "Old Airport Road Food Centre"},
    {"n": 18, "name": "Maxwell Food Centre"},
    {"n": 44, "name": "Blk 85 Bedok North Street 4"},
    {"n": 82, "name": "Blk 51 Old Airport Road"},
    {"n": 86, "name": "Redhill Food Center"},
    {"n": 92, "name": "Tekka Market"},
    {"n": 106, "name": "Whampoa Food Centre"},
    {"n": 107, "name": "Blks 91/92 Whampoa Drive"},
]
KNOWN = names(CENTRES)

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015" xmlns:media="http://search.yahoo.com/mrss/" xmlns="http://www.w3.org/2005/Atom">
 <title>Zumi hawker edits</title>
 <entry><yt:videoId>AAAAAAAAAAA</yt:videoId><title>Zumi at Maxwell Food Centre 🍗</title>
  <published>2026-09-01T10:00:00+00:00</published></entry>
 <entry><yt:videoId>BBBBBBBBBBB</yt:videoId><title>hawker day 2</title>
  <published>2026-09-08T10:00:00+00:00</published>
  <media:group><media:description>Makan or Meh? | TEKKA
0:00 Arriving
1:05 Biryani
10:43 Final rating</media:description></media:group></entry>
</feed>"""


def entry(vid, title, at="2026-09-01T00:00:00+00:00", ds=""):
    return {"id": vid, "t": title, "at": at, "ds": ds}


class Matching(unittest.TestCase):
    def test_full_and_short_names(self):
        self.assertEqual(match("Zumi tries Maxwell!", KNOWN)[0], [18])
        self.assertEqual(match("TEKKA | chicken rice", KNOWN)[0], [92])
        self.assertEqual(match("Old Airport Road Food Centre", KNOWN)[0], [14])

    def test_center_spelling_and_masked_names(self):
        self.assertEqual(match("Redhill Food Centre", KNOWN)[0], [86])
        self.assertEqual(match("Red Hill Food Centre", KNOWN)[0], [86])  # Masked's spelling, via ALIASES

    def test_a_short_name_shared_with_another_centre_is_never_guessed(self):
        self.assertEqual(match("Bedok 85 day", KNOWN), ([], 0))          # "bedok" is in two names
        self.assertEqual(match("Old Airport Road", KNOWN), ([], 0))      # also Blk 51 Old Airport Road

    def test_a_centre_with_two_entries_links_both(self):
        self.assertEqual(match("Whampoa Makan Place", KNOWN)[0], [106, 107])

    def test_two_centres_in_one_title_is_ambiguous(self):
        self.assertEqual(match("Maxwell then Tekka", KNOWN), ([], 2))

    def test_no_centre_named(self):
        self.assertEqual(match("Zumi eats chicken rice", KNOWN), ([], 0))


class Parsing(unittest.TestCase):
    def test_feed(self):
        self.assertEqual(parse_feed(FEED), [
            entry("AAAAAAAAAAA", "Zumi at Maxwell Food Centre 🍗", "2026-09-01T10:00:00+00:00"),
            entry("BBBBBBBBBBB", "hawker day 2", "2026-09-08T10:00:00+00:00",
                  "Makan or Meh? | TEKKA\n0:00 Arriving\n1:05 Biryani\n10:43 Final rating")])

    def test_seed_skips_lines_that_are_not_a_video(self):
        self.assertEqual(parse_seed("AAAAAAAAAAA Maxwell visit\n\n# notes\nnot-an-id x\n"),
                         [{"id": "AAAAAAAAAAA", "t": "Maxwell visit", "at": "", "ds": ""}])


class Build(unittest.TestCase):
    def test_description_names_the_centre_when_the_title_doesnt(self):
        videos, warnings = build(parse_feed(FEED), CENTRES, overrides={})
        self.assertEqual([(v["id"], v["n"]) for v in videos], [("BBBBBBBBBBB", [92]), ("AAAAAAAAAAA", [18])])
        self.assertEqual(warnings, [])

    def test_title_wins_over_description(self):
        videos, _ = build([entry("AAAAAAAAAAA", "Maxwell Food Centre", ds="next time: Tekka Market")], CENTRES, overrides={})
        self.assertEqual(videos[0]["n"], [18])

    def test_unmatched_is_kept_but_warned_newest_first(self):
        videos, warnings = build([entry("AAAAAAAAAAA", "hawker day", "2026-09-01"), entry("BBBBBBBBBBB", "Tekka", "2026-09-08")],
                                 CENTRES, overrides={})
        self.assertEqual([(v["id"], v["n"]) for v in videos], [("BBBBBBBBBBB", [92]), ("AAAAAAAAAAA", [])])
        self.assertEqual(len(warnings), 1)
        self.assertIn("doesn't name a centre", warnings[0])

    def test_a_description_naming_two_centres_is_not_guessed(self):
        videos, warnings = build([entry("AAAAAAAAAAA", "day out", ds="Maxwell then Tekka Market")], CENTRES, overrides={})
        self.assertEqual(videos[0]["n"], [])
        self.assertIn("more than one", warnings[0])

    def test_a_match_from_an_old_description_is_kept_once_off_the_feed(self):
        old, _ = build(parse_feed(FEED), CENTRES, overrides={})
        videos, warnings = build([], CENTRES, old, overrides={})
        self.assertEqual(next(v for v in videos if v["id"] == "BBBBBBBBBBB")["n"], [92])
        self.assertEqual(warnings, [])

    def test_override_wins_over_the_title(self):
        videos, warnings = build(parse_feed(FEED), CENTRES, overrides={"BBBBBBBBBBB": [92], "AAAAAAAAAAA": [3]})
        self.assertEqual({v["id"]: v["n"] for v in videos}, {"BBBBBBBBBBB": [92], "AAAAAAAAAAA": [3]})
        self.assertEqual(warnings, [])

    def test_override_to_an_unknown_centre_is_refused(self):
        videos, warnings = build([entry("AAAAAAAAAAA", "x")], CENTRES, overrides={"AAAAAAAAAAA": [999]})
        self.assertEqual(videos[0]["n"], [])
        self.assertIn("999", warnings[0])

    def test_merge_keeps_videos_that_fell_off_the_feed(self):
        old, _ = build([entry("OLDOLDOLD11", "Tekka Market", "2026-01-01T00:00:00+00:00")], CENTRES, overrides={})
        videos, _ = build(parse_feed(FEED), CENTRES, old, overrides={})
        self.assertEqual([v["id"] for v in videos], ["BBBBBBBBBBB", "AAAAAAAAAAA", "OLDOLDOLD11"])

    def test_details_asked_once_per_new_video(self):
        asked = []
        ask = lambda vid: asked.append(vid) or {"e": vid != "BBBBBBBBBBB", "len": 600}
        old, _ = build(parse_feed(FEED), CENTRES, overrides={}, details=ask)
        self.assertEqual({v["id"]: (v["e"], v["len"]) for v in old},
                         {"AAAAAAAAAAA": (True, 600), "BBBBBBBBBBB": (False, 600)})
        build(parse_feed(FEED), CENTRES, old, overrides={}, details=ask)
        self.assertEqual(asked, ["AAAAAAAAAAA", "BBBBBBBBBBB"])

    def test_chapters_come_from_the_feed(self):
        videos, _ = build(parse_feed(FEED), CENTRES, overrides={})
        self.assertEqual(videos[0]["c"], [[0, "Arriving"], [65, "Biryani"], [643, "Final rating"]])
        self.assertEqual(videos[1]["c"], [])

    def test_a_seed_without_dates_keeps_the_feed_date(self):
        old, _ = build(parse_feed(FEED), CENTRES, overrides={})
        videos, _ = build(parse_seed("AAAAAAAAAAA Maxwell Food Centre"), CENTRES, old, overrides={})
        self.assertEqual(next(v for v in videos if v["id"] == "AAAAAAAAAAA")["at"], "2026-09-01T10:00:00+00:00")


class Chapters(unittest.TestCase):
    def test_minutes_and_hours(self):
        self.assertEqual(chapters("intro text\n0:00 Start\n5:05 Fish soup\n1:02:03 - Final rating\n#tags"),
                         [[0, "Start"], [305, "Fish soup"], [3723, "Final rating"]])

    def test_needs_three_starting_at_zero_in_order(self):
        self.assertEqual(chapters("0:00 a\n1:00 b"), [])
        self.assertEqual(chapters("0:10 a\n1:00 b\n2:00 c"), [])
        self.assertEqual(chapters("0:00 a\n2:00 b\n1:00 c"), [])
        self.assertEqual(chapters(""), [])


class Update(unittest.TestCase):
    def test_writes_only_on_change_and_describes_new_edits(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "videos.json")
            no_details = lambda vid: {"e": True, "len": None}
            changed, videos, _ = update(CENTRES, path, "PL", get=lambda url: FEED, details=no_details)
            self.assertTrue(changed)
            self.assertEqual(load(path), videos)
            self.assertIn("2 new edits", describe(None, videos))
            changed, _, _ = update(CENTRES, path, "PL", get=lambda url: FEED, details=no_details)
            self.assertFalse(changed)


if __name__ == "__main__":
    unittest.main()
