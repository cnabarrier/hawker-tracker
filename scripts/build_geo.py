"""Build geo.json: where each hawker centre on Zumi's list is, and which official region it's in.

Every point must be confirmed by two official sources that agree within AGREE_M metres:
  * NEA's "Hawker Centres" dataset on data.gov.sg (d_4a086da0a5553be1d89383cd90d07ecd)
  * OneMap (Singapore Land Authority) search on the postal code in her address, or on the NEA
    postal code when her address has none
The region and planning area come from URA's Master Plan 2019 subzone boundaries
(d_8594ae9ff96d0c708bc2af633048edfb). A centre that can't be confirmed is left out and listed,
so the map never shows a guessed spot.

Run by hand when her list gains a centre:  python scripts/build_geo.py
geo.json is keyed by geo_key(): the first postal code in her address, else her name for it.
"""
import json
import math
import os
import re
import sys
import time
import urllib.parse
import urllib.request

NEA_ID = "d_4a086da0a5553be1d89383cd90d07ecd"
URA_ID = "d_8594ae9ff96d0c708bc2af633048edfb"
POLL = "https://api-open.data.gov.sg/v1/public/api/datasets/{}/poll-download"
ONEMAP = "https://www.onemap.gov.sg/api/common/elastic/search?searchVal={}&returnGeom=Y&getAddrDetails=Y&pageNum=1"
AGREE_M = 150
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# the site shows these names; URA spells them in capitals with "REGION"
REGIONS = {"CENTRAL REGION": "Central", "EAST REGION": "East", "NORTH REGION": "North",
           "NORTH-EAST REGION": "North-East", "WEST REGION": "West"}


def postal(addr):
    """First 6-digit postal code in 'S(123456)' or 'S(123456/123457)', else None."""
    m = re.search(r"S\((\d{6})", addr or "")
    return m[1] if m else None


def norm(name):
    s = re.sub(r"[^a-z0-9 ]", " ", (name or "").lower().replace("&", " and "))
    s = re.sub(r"\bcenter\b", "centre", s)
    return " ".join(s.split())


def geo_key(c):
    """Same rule as geoKey() in index.html."""
    return postal(c["addr"]) or norm(c["name"])


def metres(a, b):
    """Distance between (lat, lng) points."""
    la1, lo1, la2, lo2 = map(math.radians, (*a, *b))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def in_ring(lng, lat, ring):
    inside = False
    j = len(ring) - 1
    for i in range(len(ring)):
        xi, yi = ring[i][:2]
        xj, yj = ring[j][:2]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return inside


def in_geometry(lng, lat, geom):
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return any(in_ring(lng, lat, p[0]) and not any(in_ring(lng, lat, h) for h in p[1:]) for p in polys)


def locate(lat, lng, subzones):
    """(region, planning area) for a point, or (None, None) if it's in no subzone."""
    for f in subzones:
        if in_geometry(lng, lat, f["geometry"]):
            p = f["properties"]
            return REGIONS.get(p["REGION_N"], p["REGION_N"].title()), p["PLN_AREA_N"].title()
    return None, None


def nea_match(c, nea):
    """The NEA feature for her centre: same postal code, else same name. None unless exactly one."""
    pc = postal(c["addr"])
    hits = [f for f in nea if pc and f["properties"].get("ADDRESSPOSTALCODE") == pc]
    if not hits:
        n = norm(c["name"])
        hits = [f for f in nea if norm(f["properties"].get("NAME")) == n]
    return hits[0] if len(hits) == 1 else None


def onemap_point(results, pc):
    """OneMap's point for a postal code: only results with exactly that code, and they must sit together."""
    pts = [(float(r["LATITUDE"]), float(r["LONGITUDE"])) for r in results if r.get("POSTAL") == pc]
    if not pts or any(metres(pts[0], p) > AGREE_M for p in pts):
        return None
    return pts[0]


def resolve(c, nea, onemap_lookup, subzones):
    """(entry, problem). entry is None when the location can't be confirmed; problem says why."""
    f = nea_match(c, nea)
    if not f:
        return None, "not found (or found more than once) in NEA's list"
    lng, lat = f["geometry"]["coordinates"][:2]
    pc = postal(c["addr"]) or f["properties"].get("ADDRESSPOSTALCODE")
    if not pc:
        return None, "no postal code to check against OneMap"
    om = onemap_point(onemap_lookup(pc), pc)
    if not om:
        return None, f"OneMap has no single point for postal code {pc}"
    gap = metres((lat, lng), om)
    if gap > AGREE_M:
        return None, f"NEA and OneMap disagree by {gap:.0f} m"
    region, area = locate(lat, lng, subzones)
    if not region:
        return None, "point is outside every URA subzone"
    return {"lat": round(lat, 6), "lng": round(lng, 6), "region": region, "area": area,
            "nea": f["properties"].get("NAME")}, None


def build(centres, nea, onemap_lookup, subzones):
    out, problems = {}, []
    for c in centres:
        k = geo_key(c)
        if k in out:
            problems.append(f"S/N {c['n']} {c['name']}: shares key {k} with another centre")
            continue
        entry, why = resolve(c, nea, onemap_lookup, subzones)
        if entry:
            out[k] = entry
        else:
            problems.append(f"S/N {c['n']} {c['name']}: {why}")
    return out, problems


def fetch(url, tries=5):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hawker-tracker-geo"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(3 * (i + 1))


def dataset(did):
    for _ in range(6):   # data.gov.sg rate-limits the poll; it answers without a url until it's ready
        url = (json.loads(fetch(POLL.format(did))).get("data") or {}).get("url")
        if url:
            return json.loads(fetch(url))["features"]
        time.sleep(10)
    raise ConnectionError(f"data.gov.sg gave no download link for {did}")


def main():
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as fh:
        centres = json.load(fh)["centres"]
    nea, subzones = dataset(NEA_ID), dataset(URA_ID)

    def lookup(pc):
        time.sleep(0.3)   # stay well under OneMap's rate limit
        return json.loads(fetch(ONEMAP.format(urllib.parse.quote(pc)))).get("results", [])

    geo, problems = build(centres, nea, lookup, subzones)
    with open(os.path.join(ROOT, "geo.json"), "w", encoding="utf-8", newline="\n") as fh:
        fh.write('{"sources":"NEA Hawker Centres and URA Master Plan 2019 subzones (data.gov.sg), '
                 'checked against OneMap (SLA)","centres":{\n')
        fh.write(",\n".join(f"{json.dumps(k)}:{json.dumps(v, ensure_ascii=False)}" for k, v in geo.items()))
        fh.write("\n}}\n")
    print(f"{len(geo)} of {len(centres)} centres placed")
    for p in problems:
        print("  left off the map:", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
