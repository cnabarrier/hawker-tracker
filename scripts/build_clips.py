"""Cut a short clip for every photo in the albums, so the photo viewer plays it from the site itself (no YouTube player,
so no ads). 4ever OK'd clips from his edits on 2026-11-08.

Source: his visit videos, downloaded once into a folder outside the repo (default ../hawker-tracker-sources, one
<video id>.mp4 each, e.g. with yt-dlp). Each still in stills.json (key "<video id>@<second>") gets a clip that starts
where the viewer's ▶ starts it (start_of below, the same rule as stillStart in index.html) and runs CLIP_LEN seconds.

Writes assets/clips/<video id>-<second>.mp4 (H.264 + AAC, 720p, fast start for the web) and clips.json:
  {"note": ..., "clips": {"<still key>": {"src": "assets/clips/....mp4", "at": <start second>, "len": <seconds>}}}
Clips already cut are kept (pass --force to cut them again). A still whose video isn't in the source folder is
reported and left out, so the viewer plays YouTube for it as before. Banners aren't opened in the viewer: no clip.

Run:  python scripts/build_clips.py [--src DIR] [--force]
New clips need `git add -f assets/clips` (assets/ is excluded locally).
"""
import argparse
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CLIP_LEN = 8
NOTE = ("Made by scripts/build_clips.py from stills.json: a short clip per photo, played in the photo viewer "
        "instead of YouTube. Key = the still's key; at = where the clip starts in the video, in seconds.")


def start_of(key, still):
    """The second the viewer's ▶ starts at for this still (stillStart in index.html)."""
    sec = int(key.split("@")[1])
    return sec if still.get("kind") == "dish" and not still.get("dish") else max(0, sec - 3)


def plan(stills):
    """[(key, video id, start, output name)] for every still the viewer can open."""
    out = []
    for key, s in stills.items():
        if s.get("kind") == "banner":
            continue
        vid, sec = key.split("@")
        out.append((key, vid, start_of(key, s), f"{vid}-{sec}.mp4"))
    return out


def cut(src, start, dest):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-i", str(src), "-t", str(CLIP_LEN),
                    "-vf", "scale=-2:720", "-c:v", "libx264", "-preset", "slow", "-crf", "28", "-maxrate", "1400k", "-bufsize", "2800k", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", str(dest)], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT.parent / "hawker-tracker-sources"))
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    stills = json.loads((ROOT / "stills.json").read_text(encoding="utf-8"))["stills"]
    outdir = ROOT / "assets" / "clips"
    outdir.mkdir(parents=True, exist_ok=True)
    clips, missing = {}, set()
    for key, vid, start, name in plan(stills):
        src = pathlib.Path(a.src) / f"{vid}.mp4"
        if not src.exists():
            missing.add(vid)
            continue
        dest = outdir / name
        if a.force or not dest.exists():
            cut(src, start, dest)
            print(f"cut {name} from {start}s ({dest.stat().st_size // 1024} KB)")
        clips[key] = {"src": f"assets/clips/{name}", "at": start, "len": CLIP_LEN}
    for vid in sorted(missing):
        print(f"warning: no source video {vid}.mp4 in {a.src}; its photos keep playing YouTube", file=sys.stderr)
    body = ",\n".join(f"{json.dumps(k)}:{json.dumps(v, separators=(',', ':'))}" for k, v in sorted(clips.items()))
    (ROOT / "clips.json").write_text(f'{{"note":{json.dumps(NOTE)},"clips":{{\n{body}\n}}}}\n', encoding="utf-8")
    print(f"{len(clips)} clips in clips.json")


if __name__ == "__main__":
    main()
