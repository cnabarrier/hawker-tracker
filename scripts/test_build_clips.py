"""Tests for the photo-viewer clips. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_clips import plan, start_of  # noqa: E402

V = "AAAAAAAAAAA"


class StartOf(unittest.TestCase):
    # the same rule as stillStart in index.html, so a clip starts where the ▶ used to start the video
    def test_dish_tasting_moment_starts_on_the_second(self):
        self.assertEqual(start_of(f"{V}@120", {"kind": "dish"}), 120)

    def test_dish_frame_named_by_dish_starts_three_seconds_early(self):
        self.assertEqual(start_of(f"{V}@120", {"kind": "dish", "dish": "Kopi"}), 117)

    def test_scene_starts_three_seconds_early_but_not_before_zero(self):
        self.assertEqual(start_of(f"{V}@40", {"kind": "scene"}), 37)
        self.assertEqual(start_of(f"{V}@1", {"kind": "zumi"}), 0)


class Plan(unittest.TestCase):
    def test_banners_get_no_clip_and_names_follow_the_key(self):
        got = plan({f"{V}@120": {"kind": "dish"}, f"{V}@5": {"kind": "banner"}, f"{V}@40": {"kind": "scene"}})
        self.assertEqual(got, [(f"{V}@120", V, 120, f"{V}-120.mp4"), (f"{V}@40", V, 37, f"{V}-40.mp4")])


if __name__ == "__main__":
    unittest.main()
