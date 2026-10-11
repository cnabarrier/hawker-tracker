"""Convert Maskedsound's dish sheet (what Zumi ate, logged from the hawker VODs) into food.json.

build(csv_text, known=None) -> (dishes, warnings). Each dish is:
  {"n": [centre S/N, ...], "h": centre as Masked wrote it, "st": stall, "d": dish,
   "p": price as a number or None, "pt": price as written, "no": notes}

Her sheet names a centre (and a stall) only on its first row, so blank cells carry down from the row above.
Her centre names differ from Zumi's list, so they are matched through ALIASES only: guessing by shared words
links the wrong centres (Tiong Bahru/Geylang Bahru, AMK 628/Chong Boon, Hougang/Kovan were all checked).
A name not in ALIASES is a warning, never a guess: its dishes still show, just without a scorecard link.

A sheet that can't be read (missing headings, no dishes) raises SheetError so nothing is published.
"""
import csv
import io
import re
from html.parser import HTMLParser

from build_data import SheetError

# Headings in her sheet -> field. Matched by name, so columns can move or be added.
COLUMNS = [("hawker", "h"), ("stall name", "st"), ("dish", "d"), ("price", "pt"), ("notes", "no")]

# Masked's centre name (lowercase, spaces collapsed) -> Zumi's S/N(s). Checked by hand against Zumi's list,
# NEA's names and The Fat Guide's stall directories on 2026-10-10. Add new centres here as she adds them.
ALIASES = {
    "red hill food centre": [86],  # Blk 85 Redhill Lane; Zumi's #85 is the Blk 79 market next door
    "beo crescent market & food centre": [4],
    "maxwell food centre": [18],
    "bendemeer market & food centre": [47],
    "tiong bahru market": [26],
    "ang mo kio 628 market": [35],
    "chong boon market & food centre": [38],
    "whampoa makan place": [106, 107],  # spans Blk 90 (#106) and Blks 91/92 (#107); split per stall below
    "hougang hainanese village centre": [68],
    "chinatown complex": [52],
    "newton food centre": [19],
    "people's park food centre": [84],
    "golden mile food centre": [12],
    "toa payoh lorong 8 market & hawker centre": [102],
    "changi village hawker centre": [51],
    "ghim moh market & food centre": [63],
    "north bridge road market & food centre": [20],
    "kovan 209 market & food centre": [75],
}

# Centres that cover more than one of Zumi's entries: stall name prefix (lowercase) -> the one it's in.
# Whampoa blocks from The Fat Guide's per-block directories (Blk 91 = 320091, Blk 90 = 320090).
STALLS = {
    "whampoa makan place": [
        ("beach road fish head bee hoon", 107),
        ("whampoa soya bean", 107),
        ("mat noh & rose", 107),
        ("dapo", 106),
        ("ming ji", 106),
    ],
}

UNKNOWN = {"", "?", "??", "???"}
PRICE = re.compile(r"\$?\s*(\d+(?:\.\d{1,2})?)")


def key(s):
    return re.sub(r"\s+", " ", s.strip().lower())


def clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\r", " ").replace("\n", " ")).strip()


def price_options(text):
    """'$3.50/4/5' -> [3.5, 5.0] (lowest, highest); None unless every part is a plain amount."""
    parts = [s.strip() for s in text.split("/")]
    if len(parts) < 2:
        return None
    vals = [price(s) for s in parts]
    return [min(vals), max(vals)] if all(v is not None for v in vals) else None


def price(text):
    """'$4.00' -> 4.0; '??', '' or anything that isn't a single amount -> None (the text is still shown)."""
    m = PRICE.fullmatch(text)
    return float(m[1]) if m else None


def centres_for(h, st, warnings, warned):
    k = key(h)
    ns = ALIASES.get(k)
    if ns is None:
        if k not in warned:
            warned.add(k)
            warnings.append(f"centre {h!r} is not in ALIASES yet: its dishes show without a scorecard link")
        return []
    if k in STALLS:
        hit = next((n for prefix, n in STALLS[k] if key(st).startswith(prefix)), None)
        if hit is not None:
            return [hit]
        warnings.append(f"{h} stall {st!r} is not in STALLS yet: shown on all of {ns}")
    return list(ns)


class _Grid(HTMLParser):
    """The sheet's own web view (htmlview/sheet): every cell exactly as she typed it. A merged cell (rowspan)
    fills the rows below it with "", the same as the CSV export does, so the carry-down works the same."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell, self.span, self.is_th, self.pending = [], None, None, 1, False, {}

    def _fill(self):
        while len(self.row) in self.pending.get(len(self.rows), set()):
            self.row.append("")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self.row = []
        elif tag in ("td", "th") and self.row is not None:
            if tag == "td":
                self._fill()
            self.cell, self.span, self.is_th = [], int(a.get("rowspan") or 1), tag == "th"
        elif tag == "br" and self.cell is not None:
            self.cell.append(" ")

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self.cell is not None:
            if not self.is_th:  # th is the row number / column letter
                col = len(self.row)
                for r in range(1, self.span):
                    self.pending.setdefault(len(self.rows) + r, set()).add(col)
                self.row.append("".join(self.cell))
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self._fill()
            self.rows.append(self.row)
            self.row = None


def rows_from_html(html_text):
    """The table rows (heading row first) from the sheet's htmlview/sheet page."""
    g = _Grid()
    g.feed(html_text)
    rows = [r for r in g.rows if any(c.strip() for c in r)]
    if not rows or not any(key(c) == "dish" for c in rows[0]):
        raise SheetError("the dish sheet's web view has no table with a Dish heading")
    return rows


def build(csv_text=None, known=None, rows=None):
    """known: Zumi's S/Ns (from data.json), to catch an alias pointing at a centre that doesn't exist.
    rows: the sheet as read from its web view (rows_from_html), which keeps every cell exactly as she wrote it.
    csv_text is Google's CSV export, used only if the web view can't be read: it blanks any price cell that
    isn't a single number (e.g. "$3.50/4/5" or "??")."""
    if rows is None:
        rows = list(csv.reader(io.StringIO(csv_text.lstrip("﻿"))))
    if not rows:
        raise SheetError("the dish sheet is empty")
    headers = [key(h) for h in rows[0]]
    col = {}
    for name, field in COLUMNS:
        hits = [i for i, h in enumerate(headers) if h == name]
        if len(hits) != 1:
            raise SheetError(f"expected exactly one column headed {name!r}, found {len(hits)} (headings: {rows[0]})")
        col[field] = hits[0]

    dishes, warnings, warned = [], [], set()
    h = st = ""
    for r in rows[1:]:
        get = lambda f: clean(r[col[f]]) if col[f] < len(r) else ""
        if get("h"):
            h, st = get("h"), ""  # a new centre starts with no stall carried over
        if get("st"):
            st = get("st")
        d = get("d")
        if not d:
            continue  # blank row, or a centre she has started but not filled in yet
        if not h:
            raise SheetError(f"dish {d!r} comes before any centre name")
        pt = get("pt")
        dish = {"n": centres_for(h, st, warnings, warned), "h": h,
                "st": "" if st in UNKNOWN else st, "d": d,
                "p": None if pt in UNKNOWN else price(pt), "pt": pt,  # shown exactly as she wrote it
                "no": get("no")}
        opts = None if dish["p"] is not None or pt in UNKNOWN else price_options(pt)
        if opts:
            dish["pr"] = opts  # "$3.50/4/5": she paid one of these, so totals show a range, never a guess
        dishes.append(dish)

    if not dishes:
        raise SheetError("no dishes found in the dish sheet")
    if known is not None:
        bad = sorted({n for x in dishes for n in x["n"]} - set(known))
        if bad:
            raise SheetError(f"ALIASES points at S/N {bad}, which are not in Zumi's list")
    return dishes, warnings
