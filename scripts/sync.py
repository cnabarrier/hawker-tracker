"""Poll Zumi's sheet and publish data.json when her ratings change; do the same for Masked's dish sheet (food.json).

Run by .github/workflows/sync-sheet.yml. Each poll downloads the workbook, converts it with
build_data.build(), and publishes only when:
  * the sheet passes every check in build_data (otherwise nothing is published and a GitHub
    issue explains why, so the site keeps showing the last good data), and
  * the same new content is seen on two polls in a row, so a half-finished edit isn't published.

The dish sheet goes through the same steps on its own (build_food.build(), its own guard and its own issue),
so a problem in one sheet never holds up the other.

Local dry run (writes data.json and food.json, no git):  python scripts/sync.py --once --no-git
"""
import argparse
import csv
import datetime as dt
import io
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SheetError, build  # noqa: E402
import build_food  # noqa: E402
import build_moments  # noqa: E402
import build_videos  # noqa: E402

FILE_ID = "187M20H66SRnpJwcI1akU25MzWcg_DjkW"
SOURCES = [
    f"https://docs.google.com/spreadsheets/d/{FILE_ID}/export?format=xlsx",
    f"https://drive.google.com/uc?export=download&id={FILE_ID}",
]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data.json")
ISSUE_TITLE = "Ratings sync paused: sheet needs a look"

# Maskedsound's dish sheet. Its download is switched off for viewers, but the gviz CSV endpoint still serves it.
FOOD_ID = "1YlQEw3d4N5i54ooPmlTU5X9K27IdhFfYmvWX7k8ZVgY"
FOOD_SRC = f"https://docs.google.com/spreadsheets/d/{FOOD_ID}/edit"
FOOD_URL = f"https://docs.google.com/spreadsheets/d/{FOOD_ID}/gviz/tq?tqx=out:csv&headers=1"
# the sheet's own web view: every cell exactly as she typed it (the CSV export above blanks mixed price cells)
FOOD_GRID_URL = f"https://docs.google.com/spreadsheets/d/{FOOD_ID}/htmlview/sheet?headers=true&gid=0"
# When Zumi tastes each dish in 4ever's edits: moments.csv in the repo, or a Google Sheet if MOMENTS_ID is set.
MOMENTS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "moments.csv")
MOMENTS_ID = ""
MOMENTS_URL = f"https://docs.google.com/spreadsheets/d/{MOMENTS_ID}/gviz/tq?tqx=out:csv&headers=1"
MOMENTS_ISSUE = "Video moments sheet needs a look"
FOOD = os.path.join(ROOT, "food.json")
FOOD_ISSUE = "Dish sync paused: Masked's sheet needs a look"
VIDEO_ISSUE = "New video needs a centre"
FOOD_MAX_DROP = 20
KEEPALIVE_DAYS = 50  # GitHub disables scheduled workflows after 60 days without commits


def log(msg):
    print(f"[{dt.datetime.now(dt.timezone.utc):%H:%M:%S}] {msg}", flush=True)


def download():
    errors = []
    for url in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hawker-tracker-sync"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            if body[:2] != b"PK":  # xlsx is a zip; Google serves an HTML page on errors
                raise ValueError(f"got {len(body)} bytes that are not a workbook")
            return body
        except Exception as e:
            errors.append(f"{url.split('/')[2]}: {e}")
    raise ConnectionError("; ".join(errors))


def download_food(url=FOOD_URL, what="dish sheet", html=False):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "hawker-tracker-sync"})
        with urllib.request.urlopen(req, timeout=60) as r:
            text = r.read().decode("utf-8")
    except Exception as e:
        raise ConnectionError(f"{what}: {e}")
    if not html and text.lstrip().startswith("<"):  # Google serves an HTML page (sign-in or error) instead of CSV
        raise ConnectionError(f"{what}: got a web page instead of CSV (is it still viewable by anyone with the link?)")
    return text


def read_food_rows():
    """Masked's sheet exactly as she wrote it, from its web view. Google's CSV export blanks any price cell that
    isn't a single number ("$3.50/4/5", "??"), so it's only used if the web view can't be read."""
    try:
        return build_food.rows_from_html(download_food(FOOD_GRID_URL, "dish sheet (web view)", html=True))
    except (ConnectionError, SheetError) as e:
        log(f"dish sheet web view not read, using the CSV export (multi-price cells will be blank): {e}")
    text = download_food()
    return list(csv.reader(io.StringIO(text.lstrip("﻿"))))


def keep_moments(dishes, old):
    """The moments sheet couldn't be read this time: keep each dish's last known moment rather than dropping it."""
    last = {(tuple(d["n"]), d["d"], d["st"]): d["w"] for d in old or [] if "w" in d}
    return [dict(d, w=last[k]) if (k := (tuple(d["n"]), d["d"], d["st"])) in last else d for d in dishes]


def read_moments_file(url=None, what=None):
    try:
        with open(MOMENTS_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        raise SheetError("moments.csv is missing")


def with_moments(dishes, old, alerts, get=None):
    """Masked's dishes plus the moment Zumi tastes each one: moments.csv in the repo (checked against the videos'
    captions), or a moments sheet if MOMENTS_ID is set. Her dishes never wait on it."""
    if get is None:
        get = download_food if MOMENTS_ID else read_moments_file
    if not MOMENTS_ID and not os.path.exists(MOMENTS_FILE) and get is read_moments_file:
        return keep_moments(dishes, old)
    try:
        text = get(MOMENTS_URL, "video moments sheet")
        out, warnings = build_moments.apply(dishes, text, build_videos.load() or [])
    except ConnectionError as e:
        log(f"moments not read this poll (keeping the last ones): {e}")
        return keep_moments(dishes, old)
    except SheetError as e:
        alerts.problem(str(e))
        return keep_moments(dishes, old)
    if warnings:
        alerts.problem("These rows were left out: " + "; ".join(warnings))
    else:
        alerts.healthy()
    return out


def load_published():
    try:
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)["centres"]
    except FileNotFoundError:
        return None


def write_data(centres):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = ",\n".join(json.dumps(c, ensure_ascii=False, separators=(",", ":")) for c in centres)
    with open(DATA, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'{{"updated":"{now}","centres":[\n{lines}\n]}}\n')


def load_food():
    try:
        with open(FOOD, encoding="utf-8") as f:
            return json.load(f)["dishes"]
    except FileNotFoundError:
        return None


def write_food(dishes):
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    lines = ",\n".join(json.dumps(d, ensure_ascii=False, separators=(",", ":")) for d in dishes)
    with open(FOOD, "w", encoding="utf-8", newline="\n") as f:
        f.write(f'{{"updated":"{now}","src":"{FOOD_SRC}","dishes":[\n{lines}\n]}}\n')


def describe_food(old, new):
    if not old:
        return f"Dishes: first sync from Masked's sheet ({len(new)} dishes)"
    diff = len(new) - len(old)
    what = f"{diff:+d}" if diff else "edits"
    return f"Dishes: {what} from Masked's sheet ({len(new)} in all)"


def guard_food(old, new):
    if old and len(new) < len(old) - FOOD_MAX_DROP:
        raise SheetError(f"dishes dropped from {len(old)} to {len(new)}; that looks like data loss, so it was not "
                         "published (run the workflow with force=true if it is intentional)")


def describe(old, new):
    """Short human summary of what changed, for the commit message."""
    if not old:
        return f"Ratings: first sync from Zumi's sheet ({sum('s' in c for c in new)} rated)"
    old_by = {c["n"]: c for c in old}
    parts = []
    for c in new:
        o = old_by.get(c["n"])
        if o == c:
            continue
        if "s" in c and (not o or "s" not in o):
            parts.append(f"rated {c['name']} ({c['t']}, {c['rk']})")
        elif o and "s" in o and "s" not in c:
            parts.append(f"unrated {c['name']}")
        else:
            parts.append(f"updated {c['name']}")
    gone = set(old_by) - {c["n"] for c in new}
    parts += [f"removed {old_by[n]['name']}" for n in sorted(gone)]
    if not parts:
        return "Update ratings from Zumi's sheet"
    head = "; ".join(parts[:4]) + (f"; +{len(parts) - 4} more" if len(parts) > 4 else "")
    return f"Ratings: {head}"


def guard(old, new):
    """Refuse changes that look like a broken or truncated sheet rather than a real edit."""
    if not old:
        return
    rated_old = sum("s" in c for c in old)
    rated_new = sum("s" in c for c in new)
    if rated_new < rated_old - 3:
        raise SheetError(f"rated centres dropped from {rated_old} to {rated_new}; that looks like "
                         "data loss, so it was not published (run the workflow with force=true "
                         "if it is intentional)")
    if len(new) < len(old) - 3:
        raise SheetError(f"centre count dropped from {len(old)} to {len(new)}; not published")


def sync_videos(centres, alerts, no_git):
    """4ever's playlist, once per run (it changes a few times a month). Videos are optional: a failed fetch
    is only logged. A video that can't be placed is left off the site and raises an issue to add it by hand."""
    if not centres:
        return
    old = build_videos.load()
    try:
        changed, videos, warnings = build_videos.update(centres)
    except Exception as e:  # network, or YouTube changed the feed
        log(f"video playlist not checked this run: {e}")
        return
    if warnings:
        alerts.problem("; ".join(warnings))
    else:
        alerts.healthy()
    if changed:
        msg = build_videos.describe(old, videos)
        if no_git:
            log(f"wrote videos.json: {msg}")
        else:
            commit("videos.json", msg)


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check, text=True, capture_output=True)


def publish(centres, message):
    write_data(centres)
    commit("data.json", message)


def publish_food(dishes, message):
    write_food(dishes)
    commit("food.json", message)


def commit(path, message):
    git("add", path)
    git("commit", "-m", message)
    for attempt in range(4):
        if git("push", check=False).returncode == 0:
            log(f"published: {message}")
            return
        git("pull", "--rebase", "--autostash", check=False)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"could not push {path}")


def keepalive():
    last = int(git("log", "-1", "--format=%ct").stdout.strip() or 0)
    if time.time() - last > KEEPALIVE_DAYS * 86400:
        git("commit", "--allow-empty", "-m", "Keep scheduled sync alive (no sheet changes)")
        git("push")
        log("pushed keepalive commit")


class Alerts:
    """One GitHub issue while the sync is blocked; closed automatically once it recovers."""

    def __init__(self, enabled, title=ISSUE_TITLE, sheet="Zumi's sheet", lead=None):
        self.enabled = enabled and bool(os.environ.get("GH_TOKEN"))
        self.title, self.sheet = title, sheet
        self.lead = lead or (f"The automatic sync found a problem in {sheet} and **did not publish** it. "
                             f"The site keeps showing the last good data.")
        self.state = None  # last reported problem text, or "" once known healthy

    def _gh(self, *args):
        return subprocess.run(["gh", *args], cwd=ROOT, text=True, capture_output=True)

    def _open_issue(self):
        r = self._gh("issue", "list", "--state", "open", "--search", f'in:title "{self.title}"',
                     "--json", "number,title,body,comments")
        for i in json.loads(r.stdout or "[]"):
            if i["title"] == self.title:
                return i
        return None

    def problem(self, text):
        log(f"NOT PUBLISHED: {text}")
        if not self.enabled or self.state == text:
            return
        self.state = text
        body = (f"{self.lead}\n\n> {text}\n\n"
                f"It keeps checking and closes this issue itself once the sheet is fine again.")
        issue = self._open_issue()
        if issue is None:
            self._gh("issue", "create", "--title", self.title, "--body", body)
        else:
            latest = issue["comments"][-1]["body"] if issue["comments"] else issue["body"]
            if f"> {text}\n" not in latest:
                self._gh("issue", "comment", str(issue["number"]), "--body", body)

    def healthy(self):
        if not self.enabled or self.state == "":
            return
        self.state = ""
        issue = self._open_issue()
        if issue:
            self._gh("issue", "close", str(issue["number"]), "--comment",
                     "The sheet passes all checks again and the sync has resumed.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=0, help="keep polling for this long")
    ap.add_argument("--interval", type=float, default=60, help="seconds between polls")
    ap.add_argument("--once", action="store_true", help="single poll, publish without waiting for a 2nd")
    ap.add_argument("--no-git", action="store_true", help="only write data.json locally")
    ap.add_argument("--force", action="store_true", help="skip the data-loss guard")
    a = ap.parse_args()

    alerts = Alerts(enabled=not a.no_git)
    food_alerts = Alerts(enabled=not a.no_git, title=FOOD_ISSUE, sheet="Masked's dish sheet")
    moment_alerts = Alerts(enabled=not a.no_git, title=MOMENTS_ISSUE, sheet="the video moments sheet",
                           lead="Something in the video moments sheet needs a look, so the dishes it covers show no "
                                "\"watch\" button (or keep their last one). Masked's dishes are published as normal.")
    published = load_published()
    pending = None
    downloads_ok = 0
    food_published, food_pending, food_ok = load_food(), None, 0
    deadline = time.time() + a.minutes * 60
    if not a.no_git:
        keepalive()
    sync_videos(published, Alerts(enabled=not a.no_git, title=VIDEO_ISSUE, sheet="4ever's playlist",
                                  lead="A video in 4ever's playlist couldn't be matched to a centre, so it isn't on "
                                       "the site yet. Add it to VIDEO_CENTRES in scripts/build_videos.py."), a.no_git)

    while True:
        try:
            raw = download()
            downloads_ok += 1
        except ConnectionError as e:
            log(f"download failed (will retry): {e}")
        else:
            try:
                centres, warnings = build(raw)
                if not a.force:
                    guard(published, centres)
            except SheetError as e:
                alerts.problem(str(e))
                pending = None
            else:
                for w in warnings:
                    log(f"note: {w}")
                alerts.healthy()
                if centres == published:
                    pending = None
                elif a.once or centres == pending:
                    msg = describe(published, centres)
                    if a.no_git:
                        write_data(centres)
                        log(f"wrote data.json: {msg}")
                    else:
                        publish(centres, msg)
                    published, pending = centres, None
                else:
                    log(f"change seen, confirming on next poll: {describe(published, centres)}")
                    pending = centres

        try:
            rows = read_food_rows()
            food_ok += 1
        except ConnectionError as e:
            log(f"download failed (will retry): {e}")
        else:
            try:
                dishes, warnings = build_food.build(rows=rows, known=[c["n"] for c in published or []] or None)
                dishes = with_moments(dishes, food_published, moment_alerts)
                if not a.force:
                    guard_food(food_published, dishes)
            except SheetError as e:
                food_alerts.problem(str(e))
                food_pending = None
            else:
                for w in warnings:
                    log(f"note (dishes): {w}")
                food_alerts.healthy()
                if dishes == food_published:
                    food_pending = None
                elif a.once or dishes == food_pending:
                    msg = describe_food(food_published, dishes)
                    if a.no_git:
                        write_food(dishes)
                        log(f"wrote food.json: {msg}")
                    else:
                        publish_food(dishes, msg)
                    food_published, food_pending = dishes, None
                else:
                    log(f"change seen, confirming on next poll: {describe_food(food_published, dishes)}")
                    food_pending = dishes
        if a.once or time.time() + a.interval > deadline:
            break
        time.sleep(a.interval)

    if food_ok == 0:
        food_alerts.problem("could not download Masked's dish sheet at all during this run "
                            "(is it still viewable by anyone with the link?)")
    if downloads_ok == 0:
        alerts.problem("could not download the sheet at all during this run "
                       "(is it still shared as 'anyone with the link can view'?)")
        sys.exit(1)


if __name__ == "__main__":
    main()
