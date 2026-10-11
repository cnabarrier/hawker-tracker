# Makan or Meh? — Singapore Hawker Centre Rating Tracker

A website for Zumi's 2026 quest to visit and rate all 123 official hawker centres in Singapore.

**View it here:** https://cnabarrier.github.io/hawker-tracker/

## Goal

Turn Zumi's personal rating spreadsheet into a fun, easy-to-read public website, without asking her to change how she works:

1. **She keeps using her Google Sheet exactly as she does now.** She never has to touch the site or the code.
2. **The site updates itself** within a few minutes of her editing the sheet.
3. **A broken or half-typed sheet never reaches the site.** Every change is checked first, and the site keeps showing the last good data until the sheet is fixed.
4. **Anyone can use it on any device** (iPhone, Android such as Samsung, tablet, computer) with no login or app.
5. **It's easy to show**: a countdown slideshow of her ratings that fits phones (tall) and computers (wide) by itself.

All scores, notes and visit dates come from Zumi's own spreadsheet. The site is waiting on her approval, so for now it asks search engines not to list it (`noindex`).

## What's on the site

- **About the quest**: a short intro card at the top of the Dashboard for new viewers (live counts, how scoring works, links to Zumi's public channels). `#about` (and the older `#pitch`) link straight to it.
- **Dashboard**: progress bar for all 123 centres, headline numbers, leaderboard with scorecard, "Find your hawker" picker, report card, "Worth a return trip" (every centre she graded A or above, as queue tickets with her own notes), the "Hawker turf war" (which of Singapore's five official regions holds the Golden Ladle: best average among sides with 3+ rated centres; tap a side to see it on the map), food diary, a higher-or-lower guessing game, highlights and tier count.
- **Search**: a box in the header on every tab (press `/` to jump to it; on phones, the magnifying glass). It finds centres by name, short name, area, region, postcode, address, Zumi's notes or best time, and understands tier and status words like "A tier", "Must makan", "unrated" or "closed". Results are grouped Rated / Still to visit / Closed with her score and rank. Picking one opens its scorecard, or flies to it on the map if she hasn't rated it yet. A typo gets a "Did you mean" button, never a guessed result. A short wok-and-queue-ticket animation plays on the first search (Skip, Enter or the down arrow cut it short; it's off with reduced motion). The Full list keeps its own box, which uses the same matching, so the header box steps aside on that tab.
- **Full list**: all 123 centres in a sortable, searchable table, like her sheet.
- **Map & regions**: every centre pinned on a OneMap (Singapore Land Authority) map that you can zoom and drag, with tier-coloured pins for rated centres and region-coloured rings for centres still to visit, filters for status and any mix of regions (with Clear filters), a Night market map style, and a "Region battle" ranking Singapore's five official regions by her average score. `#map` links straight to it.
- **Dishes she ate**: every dish from her hawker streams, grouped by centre (newest visit first) with the price she paid, searchable, with Food / Drinks filters and a few headline stats. Each centre's scorecard also lists what she ate there. The dish list is compiled by **Maskedsound** from Zumi's stream VODs, in her own Google Sheet (Zumi approved it). `#food` links straight to it.
- **Countdown show**: a slideshow styled like a hawker stall's "NOW SERVING" queue board, with a short quick recap and a full last-to-first countdown.

## How it works

```
Zumi's Google Sheet ──(every 45 s)──> scripts/sync.py ──checks──> data.json ──> index.html (GitHub Pages)
                                         │
                                         └── on a failed check: nothing is published, a GitHub issue explains why
Masked's dish sheet ──(every 45 s)──> scripts/sync.py ──checks──> food.json ──> index.html (Dishes tab, scorecards)
```

The two sheets are synced independently: a problem in one never holds up the other, and each has its own GitHub issue.

| File | What it does |
|---|---|
| `index.html` | The whole website in one file (HTML, CSS and JavaScript, no build step; the Map tab loads Leaflet from cdnjs the first time it's opened). Loads `data.json` and falls back to a built-in copy of the data if that fails. While open, it checks for new data every 3 minutes. |
| `data.json` | The published ratings. Only the sync writes it, so don't edit it by hand. |
| `scripts/build_data.py` | Converts the downloaded workbook into `data.json` format and runs every check (totals add up, rank letter matches total, scores 0–10, real dates, no missing or duplicate rows). |
| `scripts/sync.py` | Downloads the sheet, runs the converter, and commits `data.json` only when the same change is seen on two polls in a row. Refuses big drops in rated centres unless forced. |
| `scripts/test_build_data.py` | Unit tests for the converter (run before every sync). |
| `food.json` | The published dish list. Only the sync writes it. |
| `scripts/build_food.py` | Converts Masked's dish sheet (read as CSV, matched by column heading) into `food.json`. Her centre names are linked to Zumi's list through a hand-checked `ALIASES` map, never by guessing; Whampoa Makan Place is split by stall into Blk 90 and Blks 91/92. A centre that isn't in the map yet still shows, without a scorecard link, and the sync logs a note to add it. |
| `scripts/test_build_food.py` | Unit tests for the dish converter. |
| `videos.json` | Video edits of Zumi's hawker visits by **4everhugging**, from the Makan or Meh playlist on Zumi's YouTube channel: one video per centre visit, with its length and chapters. Shown as a tap-to-play card on the scorecards and the Dishes tab. Linked, never hosted. Without the file, nothing shows. |
| `scripts/build_videos.py` | Builds `videos.json` from the playlist (`python scripts/build_videos.py`); the sync runs it once per run, so new edits appear by themselves. A video is matched to a centre by name in its title, then its description, never guessed; one that names no centre, or two, raises a "New video needs a centre" issue and is added to `VIDEO_CENTRES` by hand. Chapters come from the timestamps in the description. The playlist feed only shows the newest 15, so each run merges and never drops a known video. |
| `scripts/test_build_videos.py` | Unit tests for the video matcher. |
| `moments.csv` | When Zumi tastes each dish in 4ever's edits: a YouTube link with the time, the dish exactly as Masked names it, an optional stall, and the **evidence** (the caption line at that moment). Times are only added where the video's captions show her trying that dish; anything unclear is left out. |
| `scripts/build_moments.py` | Applies `moments.csv` (or a Google Sheet with the same headings, if `MOMENTS_ID` is set in `scripts/sync.py`) to Masked's dishes on every sync. Each matched dish in `food.json` gets `"w": [video id, seconds]` and shows a ▶ time button that jumps the video there (YouTube IFrame Player API). A row whose video isn't in the playlist, or whose dish doesn't match exactly one of Masked's dishes at that centre, is left out and raises a "Video moments sheet needs a look" issue. |
| `scripts/test_build_moments.py` | Unit tests for the moments sheet and its sync step. |
| `geo.json` | Where each centre is and its official region, for the Map tab. Written by `scripts/build_geo.py`, not by hand. |
| `scripts/build_geo.py` | Builds `geo.json`. Keeps a location only when NEA's hawker centre list (data.gov.sg) and OneMap agree within 150 m, and takes the region from URA's Master Plan 2019 boundaries. Anything it can't confirm is left off the map and listed. Run it by hand when her list gains a centre. |
| `scripts/test_build_geo.py` | Unit tests for the locations builder. |
| `.github/workflows/sync-sheet.yml` | Runs the sync on GitHub Actions: polls for 30 minutes, then queues the next run so it keeps going. |

## Running locally

```bash
pip install openpyxl==3.1.5

# Tests
python -m unittest discover -s scripts

# One-off sync into data.json (no git, no publishing)
python scripts/sync.py --once --no-git

# Rebuild the map locations (only needed when her list gains or renames a centre)
python scripts/build_geo.py

# View the site (data.json needs a web server, not file://)
python -m http.server 8000   # then open http://localhost:8000
```
