#!/usr/bin/env python3
"""Build site/gallery + site/data/gallery.json from images/ai-curated/.

The curated originals carry their ~30-word description embedded in
XMP-dc:Description / IPTC Caption (see README). This script:
  - writes web copies   site/gallery/<stem>.jpeg   (max 1600 px, q82)
  - writes thumbnails   site/gallery/t/<stem>.jpeg (256 px square crop)
  - assembles gallery.json with lat/lon/heading/datetime/description.
Images without GPS borrow the position of the nearest-in-time photo that
has one (the cameras were side by side); those get "approx": true.
"""
import json
import math
import subprocess
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageOps


def hfov_deg(focal35, width, height):
    """Horizontal FOV from 35mm-equivalent focal length (36x24mm frame)."""
    if not focal35:
        return None
    half = 18.0 if width >= height else 12.0
    return round(2 * math.degrees(math.atan(half / focal35)), 1)

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "images" / "ai-curated"
OUT = ROOT / "site" / "gallery"
THUMB = OUT / "t"
DATA = ROOT / "site" / "data"
BORROW_WINDOW_S = 45 * 60


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    THUMB.mkdir(parents=True, exist_ok=True)
    files = sorted(SRC.glob("*.jpeg"))
    meta = json.loads(subprocess.run(
        ["exiftool", "-json", "-n", "-GPSLatitude", "-GPSLongitude",
         "-GPSImgDirection", "-DateTimeOriginal", "-Model",
         "-FocalLength35efl", "-ImageWidth", "-ImageHeight",
         "-XMP-dc:Description", "-IPTC:Caption-Abstract",
         *[str(f) for f in files]],
        capture_output=True, check=True).stdout)

    items = []
    for m in meta:
        p = Path(m["SourceFile"])
        dt = m.get("DateTimeOriginal")
        ts = None
        if dt:
            try:
                ts = datetime.strptime(dt[:19], "%Y:%m:%d %H:%M:%S").timestamp()
            except ValueError:
                pass
        items.append({
            "id": p.stem,
            "lat": m.get("GPSLatitude"), "lon": m.get("GPSLongitude"),
            "dir": m.get("GPSImgDirection"),
            "hfov": hfov_deg(m.get("FocalLength35efl"),
                             m.get("ImageWidth", 0), m.get("ImageHeight", 0)),
            "dt": dt, "_ts": ts, "approx": False,
            "camera": m.get("Model"),
            "desc": m.get("Description") or m.get("Caption-Abstract") or "",
            "_src": p,
        })

    anchors = [i for i in items if i["lat"] is not None and i["_ts"]]
    borrowed = 0
    for i in items:
        if i["lat"] is not None or not i["_ts"]:
            continue
        best = min(anchors, key=lambda a: abs(a["_ts"] - i["_ts"]), default=None)
        if best and abs(best["_ts"] - i["_ts"]) <= BORROW_WINDOW_S:
            i["lat"], i["lon"], i["approx"] = best["lat"], best["lon"], True
            borrowed += 1

    for i in items:
        im = ImageOps.exif_transpose(Image.open(i["_src"]))
        web = im.copy()
        web.thumbnail((1600, 1600))
        web.save(OUT / f"{i['id']}.jpeg", quality=82, optimize=True)
        i["w"], i["h"] = web.width, web.height
        t = ImageOps.fit(im, (256, 256))
        t.save(THUMB / f"{i['id']}.jpeg", quality=75, optimize=True)

    items.sort(key=lambda i: i["_ts"] or 0)
    for i in items:
        del i["_src"], i["_ts"]
        if i["lat"] is not None:
            i["lat"], i["lon"] = round(i["lat"], 6), round(i["lon"], 6)
        if i["dir"] is not None:
            i["dir"] = round(i["dir"], 1)

    (DATA / "gallery.json").write_text(
        json.dumps(items, ensure_ascii=False, indent=1))
    placed = sum(1 for i in items if i["lat"] is not None)
    nodesc = [i["id"] for i in items if not i["desc"]]
    size = sum(f.stat().st_size for f in OUT.rglob("*.jpeg")) / 1e6
    print(f"{len(items)} items, {placed} placed ({borrowed} borrowed), "
          f"{size:.1f} MB; missing desc: {nodesc or 'none'}")


if __name__ == "__main__":
    main()
