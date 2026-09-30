"""Tests for the map locations builder. Run: python -m unittest discover -s scripts"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_geo import build, geo_key, locate, metres, postal  # noqa: E402

SQUARE = {"type": "Polygon", "coordinates": [[[103.8, 1.3], [103.9, 1.3], [103.9, 1.4], [103.8, 1.4], [103.8, 1.3]]]}
SUBZONES = [{"geometry": SQUARE, "properties": {"REGION_N": "NORTH-EAST REGION", "PLN_AREA_N": "HOUGANG"}}]


def nea(name, pc, lat=1.35, lng=103.85):
    return {"geometry": {"coordinates": [lng, lat]}, "properties": {"NAME": name, "ADDRESSPOSTALCODE": pc}}


def om(pc, lat=1.35, lng=103.85):
    return lambda q: [{"POSTAL": pc, "LATITUDE": str(lat), "LONGITUDE": str(lng)}] if q == pc else []


class Keys(unittest.TestCase):
    def test_postal(self):
        self.assertEqual(postal("2, Adam Road, S(289876)"), "289876")
        self.assertEqual(postal("Blks 160/162, Ang Mo Kio Ave 4, S(560160/560162)"), "560160")
        self.assertIsNone(postal("Closed for redevelopment till 2029 (tentative)"))

    def test_key_falls_back_to_name(self):
        self.assertEqual(geo_key({"name": "Bukit Timah Market", "addr": "Closed"}), "bukit timah market")
        self.assertEqual(geo_key({"name": "X", "addr": "1 Road, S(123456)"}), "123456")


class Geometry(unittest.TestCase):
    def test_metres(self):
        self.assertAlmostEqual(metres((1.3, 103.8), (1.301, 103.8)), 111, delta=1)

    def test_locate(self):
        self.assertEqual(locate(1.35, 103.85, SUBZONES), ("North-East", "Hougang"))
        self.assertEqual(locate(1.5, 103.85, SUBZONES), (None, None))


class Build(unittest.TestCase):
    C = {"n": 1, "name": "Some Food Centre", "addr": "1 Road, S(111111)"}

    def test_agreeing_sources_are_placed(self):
        geo, problems = build([self.C], [nea("Other Name", "111111")], om("111111", 1.3505), SUBZONES)
        self.assertEqual(problems, [])
        self.assertEqual(geo["111111"]["region"], "North-East")
        self.assertEqual(geo["111111"]["lat"], 1.35)   # NEA's point is the one kept

    def test_disagreeing_sources_are_left_off(self):
        geo, problems = build([self.C], [nea("X", "111111")], om("111111", 1.36), SUBZONES)
        self.assertEqual(geo, {})
        self.assertIn("disagree", problems[0])

    def test_missing_from_either_source_is_left_off(self):
        self.assertEqual(build([self.C], [], om("111111"), SUBZONES)[0], {})
        self.assertEqual(build([self.C], [nea("X", "111111")], om("999999"), SUBZONES)[0], {})

    def test_closed_centre_matches_by_name_and_nea_postal(self):
        c = {"n": 6, "name": "Bukit Timah Market", "addr": "Closed for redevelopment"}
        geo, _ = build([c], [nea("Bukit Timah Market", "222222")], om("222222"), SUBZONES)
        self.assertIn("bukit timah market", geo)

    def test_outside_every_subzone_is_left_off(self):
        geo, problems = build([self.C], [nea("X", "111111", lat=1.5)], om("111111", lat=1.5), SUBZONES)
        self.assertEqual(geo, {})
        self.assertIn("subzone", problems[0])


if __name__ == "__main__":
    unittest.main()
