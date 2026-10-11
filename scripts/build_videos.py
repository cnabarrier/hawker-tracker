"""Link 4ever's hawker edits (a YouTube playlist on Zumi's channel) to her centres and write videos.json.

The site only links to the videos and shows YouTube's own thumbnails; nothing is downloaded or hosted.
One video belongs to a centre visit, not to a dish.

build(entries, centres, old=None, overrides=None, details=None) -> (videos, warnings). Each video is:
  {"id": YouTube video id, "t": title, "at": published (ISO), "n": [centre S/N, ...],
   "e": can play on the site, "len": length in seconds or null, "c": [[seconds, chapter], ...]}

A video is matched to a centre by name: Zumi's centre names, their short forms ("Maxwell") and Masked's names
(build_food.ALIASES), in the title first and then in the description. It must name exactly one centre;
otherwise it is kept with n: [] and listed as a warning, never guessed. Fix it with one line in VIDEO_CENTRES.
Chapters are the timestamps 4ever puts in the description, shown as he wrote them.

YouTube's playlist feed only lists the newest 15 videos, so each run merges into the existing videos.json
and never drops a video it already knows. scripts/sync.py runs update() once per sync run.

  python scripts/build_videos.py                  # update from 4ever's playlist
  python scripts/build_videos.py --seed list.txt  # add videos from a pasted "video_id title" list
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from build_food import ALIASES

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "videos.json")
PLAYLIST = "PLgqiNTVlXYeLT0UIF-S5i_HlePEf7fqhj"  # sent by 4ever on 2026-10-10
FEED = "https://www.youtube.com/feeds/videos.xml?playlist_id={}"
WATCH = "https://www.youtube.com/watch?v={}"

# How 4ever asked to be credited ("Video edits by 4everhugging").
CREDIT = "4everhugging"

# Videos that don't name exactly one centre: YouTube video id -> Zumi's S/N(s). Checked by hand.
VIDEO_CENTRES = {
    # "Red Hill Hawker Center" covers both places Zumi rated that day: Redhill Food Centre (#86) to 12:37, then
    # Redhill Market (#85) next door from 12:50 (checked against the video's captions on 2026-10-10).
    "q5oVUrCQcs8": [85, 86],
}

# Where a video's part about a centre starts, when one video covers more than one: id -> {S/N: seconds}.
VIDEO_STARTS = {
    "q5oVUrCQcs8": {85: 770},
}

# Name endings dropped to get a short form, like the site's autoShort() in index.html.
SUFFIX = re.compile(r"\s+(market and (food|hawker) centre|cooked food centre|food centre|"
                    r"hawker centre( and market)?|food village|market)$")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
STAMP = re.compile(r"^\s*(?:(\d{1,2}):)?(\d{1,2}):(\d{2})\s*[-–—|:]?\s+(.+?)\s*$")


def norm(s):
    """Lowercase words only: '&' reads as 'and', punctuation and emoji become spaces."""
    s = s.lower().replace("&", " and ").replace("’", "'")
    s = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9' ]", " ", s)).strip()
    return re.sub(r"\bcenter\b", "centre", s)


def names(centres):
    """Every name a video might use -> the S/N(s) it means."""
    out = {}

    def add(name, ns):
        name = norm(name)
        if len(name) >= 4:
            out.setdefault(name, set()).update(ns)

    full = {c["n"]: norm(c["name"]) for c in centres}
    for c in centres:
        add(c["name"], [c["n"]])
        short = SUFFIX.sub("", full[c["n"]])
        # a short form only counts if no other centre's name has the same words ("bedok" is in seven)
        if short != full[c["n"]] and not any(f" {short} " in f" {f} " for n, f in full.items() if n != c["n"]):
            add(short, [c["n"]])
    for alias, ns in ALIASES.items():
        add(alias, ns)
    return out


def match(text, known):
    """(S/Ns the text names, how many different centres it names). [] unless exactly one."""
    t = f" {norm(text)} "
    hits = [n for n in known if f" {n} " in t]
    hits = [h for h in hits if not any(h != o and h in o for o in hits)]  # "bedok" inside "bedok 85 market"
    found = {frozenset(known[h]) for h in hits}
    return (sorted(next(iter(found))) if len(found) == 1 else []), len(found)


def chapters(desc):
    """[[seconds, label], ...] from description lines like '1:05 Fishball noodles'. YouTube only makes chapters
    when the list starts at 0:00 and has at least three, so anything else is left alone."""
    out = []
    for line in (desc or "").splitlines():
        m = STAMP.match(line)
        if m:
            h, mi, s, label = int(m[1] or 0), int(m[2]), int(m[3]), m[4]
            out.append([h * 3600 + mi * 60 + s, label])
    if len(out) < 3 or out[0][0] != 0 or any(b[0] <= a[0] for a, b in zip(out, out[1:])):
        return []
    return out


def parse_feed(xml_text):
    root = ET.fromstring(xml_text)
    return [{"id": e.findtext("yt:videoId", namespaces=NS), "t": e.findtext("a:title", namespaces=NS) or "",
             "at": e.findtext("a:published", namespaces=NS) or "",
             "ds": e.findtext("media:group/media:description", namespaces=NS) or ""}
            for e in root.findall("a:entry", NS)]


def parse_seed(text):
    out = []
    for line in text.splitlines():
        vid, _, title = line.strip().partition(" ")
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            out.append({"id": vid, "t": title.strip(), "at": "", "ds": ""})
    return out


def build(entries, centres, old=None, overrides=None, details=None):
    """details(id) -> {"e": bool, "len": int or None}, asked only for videos not seen before."""
    overrides = VIDEO_CENTRES if overrides is None else overrides
    known, valid = names(centres), {c["n"] for c in centres}
    videos = {v["id"]: {"len": None, "c": [], **v} for v in old or []}
    desc = {}
    for e in entries:
        v = videos.get(e["id"])
        if v is None:
            d = details(e["id"]) if details else {}
            v = videos[e["id"]] = {"id": e["id"], "t": "", "at": "", "n": [],
                                   "e": d.get("e", True), "len": d.get("len"), "c": []}
        v["t"] = e["t"] or v["t"]
        v["at"] = e["at"] or v["at"]
        if e.get("ds"):
            desc[e["id"]] = e["ds"]
            v["c"] = chapters(e["ds"])

    warnings = []
    for v in videos.values():
        v.pop("s", None)
        if v["id"] in VIDEO_STARTS:
            v["s"] = {str(n): s for n, s in VIDEO_STARTS[v["id"]].items()}
        if v["id"] in overrides:
            v["n"] = sorted(overrides[v["id"]])
            bad = [n for n in v["n"] if n not in valid]
            if bad:
                warnings.append(f"VIDEO_CENTRES points {v['id']} at S/N {bad}, which are not in Zumi's list")
                v["n"] = []
            continue
        ns, count = match(v["t"], known)
        if not ns and count == 0:
            if v["id"] in desc:
                ns, count = match(desc[v["id"]], known)
            elif v["n"]:
                continue  # off the feed now: keep what its description said last time
        v["n"] = ns
        if not ns:
            why = "names more than one centre" if count > 1 else "doesn't name a centre"
            warnings.append(f"{v['id']} {v['t']!r} {why}: add it to VIDEO_CENTRES to show it")
    return sorted(videos.values(), key=lambda v: (v["at"], v["id"]), reverse=True), warnings


def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (hawker-tracker)", "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8", "replace")


def page_field(html, name):
    i = html.find(f'"{name}":')
    if i < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(html, i + len(name) + 3)[0]
    except ValueError:
        return None


def video_details(vid):
    """Length and whether the owner allows playing it on other sites, from the public watch page."""
    try:
        html = fetch(WATCH.format(urllib.parse.quote(vid)))
    except Exception:
        return {"e": True, "len": None}  # can't tell; the site always offers "Watch on YouTube" as well
    secs = page_field(html, "lengthSeconds")
    return {"e": page_field(html, "playableInEmbed") is not False,
            "len": int(secs) if str(secs or "").isdigit() else None}


def load(path=OUT):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)["videos"]
    except FileNotFoundError:
        return None


def write(videos, path=OUT):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = ",\n".join(json.dumps(v, ensure_ascii=False, separators=(",", ":")) for v in videos)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'{{"updated":"{now}","credit":{json.dumps(CREDIT, ensure_ascii=False)},'
                f'"playlist":"{PLAYLIST}","videos":[\n{lines}\n]}}\n')


def update(centres, path=OUT, playlist=PLAYLIST, get=fetch, details=video_details, seed=None):
    """Fetch the playlist, merge into videos.json. -> (changed, videos, warnings). Writes only on change."""
    entries = parse_seed(seed) if seed else []
    if playlist:
        entries += parse_feed(get(FEED.format(urllib.parse.quote(playlist))))
    old = load(path)
    videos, warnings = build(entries, centres, old, details=details)
    changed = videos != old
    if changed:
        write(videos, path)
    return changed, videos, warnings


def describe(old, new):
    known = {v["id"] for v in old or []}
    added = [v["t"] for v in new if v["id"] not in known and v["n"]]
    if added:
        return f"Videos: {len(added)} new edit{'s' if len(added) > 1 else ''} ({'; '.join(added)[:120]})"
    return f"Videos: playlist updated ({len(new)} in all)"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--playlist", default=PLAYLIST, help="YouTube playlist id (the list=... part of the link)")
    ap.add_argument("--seed", help="text file with one 'video_id title' per line")
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    seed = None
    if a.seed:
        with open(a.seed, encoding="utf-8") as f:
            seed = f.read()
    with open(os.path.join(ROOT, "data.json"), encoding="utf-8") as f:
        centres = json.load(f)["centres"]
    changed, videos, warnings = update(centres, a.out, a.playlist, seed=seed)
    print(f"{len(videos)} videos, {sum(1 for v in videos if v['n'])} linked to a centre"
          f"{'' if changed else ' (no change)'}")
    for w in warnings:
        print("  not shown:", w)
    for v in videos:
        if v["n"] and not v["e"]:
            print(f"  {v['id']} can't play on the site (embedding is off); it opens on YouTube instead")
    return 0


if __name__ == "__main__":
    sys.exit(main())
