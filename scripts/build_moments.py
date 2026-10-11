"""Attach "the moment Zumi tastes it" to dishes, from Gummy's video-moments sheet.

The sheet has one row per moment, matched by heading so columns can move:
  Video link  a YouTube link with a time, e.g. https://youtu.be/snyN0zGEqR4?t=515
              (on YouTube: right-click the video -> "Copy video URL at current time")
  Dish        the dish exactly as Masked's sheet names it
  Stall       optional: only needed when that centre has two dishes with the same name

apply(dishes, csv_text, videos) -> (dishes, warnings). Each matched dish gains "w": [video id, seconds].
Masked's sheet stays the only source of dishes; this sheet only adds times. A row is attached only when its
video is one of 4ever's edits (videos.json) and its dish names exactly one dish at that video's centre;
anything else is a warning and left out, never guessed. A dish with no row simply has no "w".

A sheet that can't be read (missing headings) raises SheetError, so the sync reports it and keeps
publishing Masked's dishes without times.
"""
import csv
import io
import re
import urllib.parse

from build_data import SheetError
from build_videos import norm

COLUMNS = [("video link", "link", True), ("dish", "dish", True), ("stall", "stall", False)]
VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
HMS = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")


def seconds(t):
    """'515', '515s', '8m35s', '1h2m3s' -> seconds, or None."""
    m = HMS.fullmatch((t or "").strip().lower())
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x or 0) for x in m.groups())
    return h * 3600 + mi * 60 + s


def parse_link(link):
    """A YouTube link with a time -> (video id, seconds); (None, None) if it isn't one."""
    u = urllib.parse.urlparse((link or "").strip())
    host = (u.hostname or "").lower().removeprefix("www.").removeprefix("m.")
    q = urllib.parse.parse_qs(u.query)
    parts = [p for p in u.path.split("/") if p]
    vid = None
    if host == "youtu.be" and parts:
        vid = parts[0]
    elif host in ("youtube.com", "youtube-nocookie.com", "music.youtube.com"):
        if parts[:1] == ["watch"]:
            vid = (q.get("v") or [None])[0]
        elif len(parts) >= 2 and parts[0] in ("embed", "live", "shorts", "v"):
            vid = parts[1]
    if not vid or not VIDEO_ID.match(vid):
        return None, None
    t = (q.get("t") or q.get("start") or [None])[0]
    if t is None and u.fragment.startswith("t="):
        t = u.fragment[2:]
    return vid, seconds(t) if t is not None else None


def apply(dishes, csv_text, videos):
    rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if not rows:
        raise SheetError("the video moments sheet is empty (it needs the headings Video link and Dish)")
    headers = [norm(h) for h in rows[0]]
    col = {}
    for name, field, required in COLUMNS:
        hits = [i for i, h in enumerate(headers) if h == name]
        if len(hits) > 1 or (required and not hits):
            raise SheetError(f"expected exactly one column headed {name!r}, found {len(hits)} (headings: {rows[0]})")
        if hits:
            col[field] = hits[0]

    centres_of = {v["id"]: set(v["n"]) for v in videos or []}
    out = [{k: v for k, v in d.items() if k != "w"} for d in dishes]
    taken, warnings = {}, []
    for line, r in enumerate(rows[1:], start=2):
        get = lambda f: r[col[f]].strip() if f in col and col[f] < len(r) else ""
        link, dish, stall = get("link"), get("dish"), get("stall")
        if not link and not dish:
            continue
        where = f"row {line}"
        vid, at = parse_link(link)
        if vid is None:
            warnings.append(f"{where}: {link!r} is not a YouTube video link")
            continue
        if at is None:
            warnings.append(f"{where}: the link has no time in it (use \"Copy video URL at current time\")")
            continue
        if vid not in centres_of:
            warnings.append(f"{where}: video {vid} is not one of 4ever's edits in the playlist")
            continue
        if not dish:
            warnings.append(f"{where}: no dish named")
            continue
        here = [i for i, d in enumerate(out) if set(d["n"]) & centres_of[vid] and norm(d["d"]) == norm(dish)]
        if stall:
            here = [i for i in here if norm(out[i]["st"]).startswith(norm(stall))]
        if len(here) != 1:
            why = ("isn't on Masked's list for that centre (renamed?)" if not here
                   else f"matches {len(here)} dishes there; add the Stall to pick one")
            warnings.append(f"{where}: {dish!r}{f' ({stall})' if stall else ''} {why}")
            continue
        i = here[0]
        if i in taken:
            if out[i]["w"] != [vid, at]:
                warnings.append(f"{where}: {dish!r} already has a moment on row {taken[i]}; kept that one")
            continue
        out[i]["w"], taken[i] = [vid, at], line
    return out, warnings
