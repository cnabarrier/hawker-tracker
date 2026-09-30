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
- **Dashboard**: progress bar for all 123 centres, headline numbers, leaderboard with scorecard, "Find your hawker" picker, report card, food diary, a higher-or-lower guessing game, highlights and tier count.
- **Full list**: all 123 centres in a sortable, searchable table, like her sheet.
- **Map & regions**: every centre pinned on a OneMap (Singapore Land Authority) map that you can zoom and drag, with tier-coloured pins for rated centres and region-coloured rings for centres still to visit, filters for status and any mix of regions (with Clear filters), a Night market map style, and a "Region battle" ranking Singapore's five official regions by her average score. `#map` links straight to it.
- **Countdown show**: a slideshow styled like a hawker stall's "NOW SERVING" queue board, with a short quick recap and a full last-to-first countdown.

## How it works

```
Zumi's Google Sheet ──(every 45 s)──> scripts/sync.py ──checks──> data.json ──> index.html (GitHub Pages)
                                         │
                                         └── on a failed check: nothing is published, a GitHub issue explains why
```

| File | What it does |
|---|---|
| `index.html` | The whole website in one file (HTML, CSS and JavaScript, no build step; the Map tab loads Leaflet from cdnjs the first time it's opened). Loads `data.json` and falls back to a built-in copy of the data if that fails. While open, it checks for new data every 3 minutes. |
| `data.json` | The published ratings. Only the sync writes it, so don't edit it by hand. |
| `scripts/build_data.py` | Converts the downloaded workbook into `data.json` format and runs every check (totals add up, rank letter matches total, scores 0–10, real dates, no missing or duplicate rows). |
| `scripts/sync.py` | Downloads the sheet, runs the converter, and commits `data.json` only when the same change is seen on two polls in a row. Refuses big drops in rated centres unless forced. |
| `scripts/test_build_data.py` | Unit tests for the converter (run before every sync). |
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
