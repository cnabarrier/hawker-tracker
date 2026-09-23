"""Poll Zumi's sheet and publish data.json when her ratings change.

Run by .github/workflows/sync-sheet.yml. Each poll downloads the workbook, converts it with
build_data.build(), and publishes only when:
  * the sheet passes every check in build_data (otherwise nothing is published and a GitHub
    issue explains why, so the site keeps showing the last good data), and
  * the same new content is seen on two polls in a row, so a half-finished edit isn't published.

Local dry run (writes data.json, no git):  python scripts/sync.py --once --no-git
"""
import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build_data import SheetError, build  # noqa: E402

FILE_ID = "187M20H66SRnpJwcI1akU25MzWcg_DjkW"
SOURCES = [
    f"https://docs.google.com/spreadsheets/d/{FILE_ID}/export?format=xlsx",
    f"https://drive.google.com/uc?export=download&id={FILE_ID}",
]
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data.json")
ISSUE_TITLE = "Ratings sync paused: sheet needs a look"
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


def git(*args, check=True):
    return subprocess.run(["git", *args], cwd=ROOT, check=check, text=True, capture_output=True)


def publish(centres, message):
    write_data(centres)
    git("add", "data.json")
    git("commit", "-m", message)
    for attempt in range(4):
        if git("push", check=False).returncode == 0:
            log(f"published: {message}")
            return
        git("pull", "--rebase", "--autostash", check=False)
        time.sleep(5 * (attempt + 1))
    raise RuntimeError("could not push data.json")


def keepalive():
    last = int(git("log", "-1", "--format=%ct").stdout.strip() or 0)
    if time.time() - last > KEEPALIVE_DAYS * 86400:
        git("commit", "--allow-empty", "-m", "Keep scheduled sync alive (no sheet changes)")
        git("push")
        log("pushed keepalive commit")


class Alerts:
    """One GitHub issue while the sync is blocked; closed automatically once it recovers."""

    def __init__(self, enabled):
        self.enabled = enabled and bool(os.environ.get("GH_TOKEN"))
        self.state = None  # last reported problem text, or "" once known healthy

    def _gh(self, *args):
        return subprocess.run(["gh", *args], cwd=ROOT, text=True, capture_output=True)

    def _open_issue(self):
        r = self._gh("issue", "list", "--state", "open", "--search", f'in:title "{ISSUE_TITLE}"',
                     "--json", "number,title,body,comments")
        for i in json.loads(r.stdout or "[]"):
            if i["title"] == ISSUE_TITLE:
                return i
        return None

    def problem(self, text):
        log(f"NOT PUBLISHED: {text}")
        if not self.enabled or self.state == text:
            return
        self.state = text
        body = (f"The automatic sync found a problem in Zumi's sheet and **did not publish** it. "
                f"The site keeps showing the last good data.\n\n> {text}\n\n"
                f"It keeps checking and closes this issue itself once the sheet is fine again.")
        issue = self._open_issue()
        if issue is None:
            self._gh("issue", "create", "--title", ISSUE_TITLE, "--body", body)
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
    published = load_published()
    pending = None
    downloads_ok = 0
    deadline = time.time() + a.minutes * 60
    if not a.no_git:
        keepalive()

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
        if a.once or time.time() + a.interval > deadline:
            break
        time.sleep(a.interval)

    if downloads_ok == 0:
        alerts.problem("could not download the sheet at all during this run "
                       "(is it still shared as 'anyone with the link can view'?)")
        sys.exit(1)


if __name__ == "__main__":
    main()
