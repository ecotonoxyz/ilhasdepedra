#!/usr/bin/env python3
"""Build site/data + site/media from qgis-proj/ and images/.

Re-run whenever photos are added or geodata changes:

    python3 scripts/build_data.py

Needs: GDAL CLI tools (ogr2ogr), exiftool, ffmpeg.
"""
import json
import math
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QGIS = ROOT / "qgis-proj"
IMAGES = ROOT / "images"
SITE = ROOT / "site"
DATA = SITE / "data"
MEDIA = SITE / "media"

# Display window: Jamari + Jaru basins with breathing room.
BBOX = (-64.6, -11.4, -61.9, -8.4)  # lonmin latmin lonmax latmax


def run(cmd, **kw):
    print("  $", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


def ogr(dst, src, *args):
    dst.unlink(missing_ok=True)
    run(["ogr2ogr", "-f", "GeoJSON", "-lco", "COORDINATE_PRECISION=5",
         dst, src, *args])
    print(f"    -> {dst.name}: {dst.stat().st_size/1e6:.2f} MB")


def build_ilhas():
    """High-confidence candidates within the display window, plus every
    human-confirmed ilha. `fid` is the public ID."""
    lonmin, latmin, lonmax, latmax = BBOX
    ogr(DATA / "ilhas.geojson", QGIS / "ilhas_v2.gpkg",
        "-t_srs", "EPSG:4326",
        "-sql",
        "SELECT geom, (fid + 0) AS iid, ROUND(p_ilha,3) AS p, "
        "CAST(ROUND(tophat_m) AS integer) AS th, "
        "CAST(ROUND(relief_m) AS integer) AS rel, "
        "CAST(ROUND(summit_m) AS integer) AS smt, "
        "CASE WHEN label='ilha' THEN 1 ELSE 0 END AS conf "
        "FROM candidates WHERE (p_ilha >= 0.9 OR label = 'ilha') "
        f"AND lon BETWEEN {lonmin} AND {lonmax} "
        f"AND lat BETWEEN {latmin} AND {latmax}")
    n = len(json.loads((DATA / "ilhas.geojson").read_text())["features"])
    (DATA / "stats.json").write_text(json.dumps({"ilhas": n}))
    print(f"    -> stats.json: {n} ilhas")


def build_streams():
    ogr(DATA / "streams.geojson", QGIS / "streams.gpkg",
        "-t_srs", "EPSG:4326",
        "-spat", *BBOX, "-spat_srs", "EPSG:4326",
        "-simplify", "0.0006",
        "-where", "strahler >= 5", "-select", "strahler", "streams")


def build_rivers_named():
    ogr(DATA / "rivers.geojson", QGIS / "osm.gpkg",
        "-spat", *BBOX,
        "-sql", "SELECT geom, name FROM lines WHERE waterway IN ('river') "
                "AND name IS NOT NULL",
        "-simplify", "0.0004")


def build_roads():
    ogr(DATA / "roads.geojson", QGIS / "osm.gpkg",
        "-spat", *BBOX,
        "-sql", "SELECT geom, name, highway AS cls FROM lines WHERE highway "
                "IN ('motorway','trunk','primary','secondary')",
        "-simplify", "0.0004")


def build_basins():
    ogr(DATA / "basins.geojson", QGIS / "basins_jamari_jaru.gpkg",
        "-t_srs", "EPSG:4326",
        "-simplify", "0.001",
        "-sql", "SELECT geom, name, ana_km2 FROM basins")


# Municipality seats for label layer (approximate, from public sources).
PLACES = [
    {"name": "Ariquemes",          "lat": -9.9133,  "lon": -63.0409, "rank": 1},
    {"name": "Porto Velho",        "lat": -8.7619,  "lon": -63.9039, "rank": 1},
    {"name": "Jaru",               "lat": -10.4392, "lon": -62.4664, "rank": 1},
    {"name": "Monte Negro",        "lat": -10.2570, "lon": -63.2900, "rank": 2},
    {"name": "Alto Paraíso",       "lat": -9.7147,  "lon": -63.3195, "rank": 2},
    {"name": "Buritis",            "lat": -10.2091, "lon": -63.8296, "rank": 2},
    {"name": "Cacaulândia",        "lat": -10.3389, "lon": -62.9037, "rank": 2},
    {"name": "Candeias do Jamari", "lat": -8.7898,  "lon": -63.7010, "rank": 2},
    {"name": "Itapuã do Oeste",    "lat": -9.1961,  "lon": -63.1809, "rank": 2},
    {"name": "Cujubim",            "lat": -9.3608,  "lon": -62.5850, "rank": 2},
    {"name": "Machadinho d'Oeste", "lat": -9.4426,  "lon": -61.9814, "rank": 2},
    {"name": "Rio Crespo",         "lat": -9.7031,  "lon": -62.9015, "rank": 2},
    {"name": "Ouro Preto do Oeste","lat": -10.7167, "lon": -62.2565, "rank": 2},
    {"name": "Nova União",         "lat": -10.9074, "lon": -62.5566, "rank": 2},
    {"name": "Theobroma",          "lat": -10.2481, "lon": -62.3543, "rank": 2},
    {"name": "Vale do Anari",      "lat": -9.8622,  "lon": -62.1815, "rank": 2},
]

# Landmark ranges named in the booklet; positions approximate.
SERRAS = [
    {"name": "serra da massangana\nou as mil ilhas de pedra",
     "lat": -10.315, "lon": -63.455},
    {"name": "serra ouro verde", "lat": -9.795, "lon": -63.055},
    {"name": "serra dos pacaás novos", "lat": -11.28, "lon": -62.95},
]


def build_places():
    fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
         "properties": {"name": p["name"], "rank": p["rank"], "kind": "city"}}
        for p in PLACES] + [
        {"type": "Feature",
         "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
         "properties": {"name": s["name"], "rank": 3, "kind": "serra"}}
        for s in SERRAS]}
    out = DATA / "places.geojson"
    out.write_text(json.dumps(fc, ensure_ascii=False))
    print(f"    -> {out.name}: {out.stat().st_size/1e3:.1f} kB")


def hfov_deg(focal35, width, height):
    """Horizontal FOV from 35mm-equivalent focal length.
    Full-frame is 36x24mm; the long side maps to the image's long side."""
    if not focal35:
        return None
    half = 18.0 if width >= height else 12.0
    return round(2 * math.degrees(math.atan(half / focal35)), 1)


def build_media():
    MEDIA.mkdir(parents=True, exist_ok=True)
    exts = {".jpeg", ".jpg", ".png", ".mov", ".mp4"}
    files = sorted(p for p in IMAGES.iterdir() if p.suffix.lower() in exts)
    if not files:
        print("  no media files found"); return

    raw = json.loads(subprocess.run(
        ["exiftool", "-json", "-n",
         "-GPSLatitude", "-GPSLongitude", "-GPSAltitude", "-GPSImgDirection",
         "-DateTimeOriginal", "-CreateDate", "-Model", "-FocalLength35efl",
         "-ImageWidth", "-ImageHeight", *[str(f) for f in files]],
        capture_output=True, check=True).stdout)

    # Existing narrative texts survive a rebuild.
    old = {}
    mj = DATA / "media.json"
    if mj.exists():
        old = {m["id"]: m for m in json.loads(mj.read_text())}

    items = []
    for meta in raw:
        src = Path(meta["SourceFile"])
        lat, lon = meta.get("GPSLatitude"), meta.get("GPSLongitude")
        if lat is None or lon is None:
            print(f"  !! {src.name}: no GPS, skipped"); continue
        stem, is_video = src.stem, src.suffix.lower() in (".mov", ".mp4")

        if is_video:
            out = MEDIA / f"{stem}.mp4"
            poster = MEDIA / f"{stem}_poster.jpeg"
            if not out.exists():
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                     "-c:v", "libx264", "-crf", "25", "-preset", "medium",
                     "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                     "-c:a", "aac", "-b:a", "96k", out])
                run(["ffmpeg", "-y", "-loglevel", "error", "-i", src,
                     "-ss", "1", "-frames:v", "1", "-q:v", "4", poster])
            fname = out.name
        else:
            out = MEDIA / src.name
            if not out.exists():
                shutil.copy2(src, out)
            fname = out.name

        prev = old.get(stem, {})
        w, h = meta.get("ImageWidth", 0), meta.get("ImageHeight", 0)
        alt = meta.get("GPSAltitude")
        heading = meta.get("GPSImgDirection")
        items.append({
            "id": stem,
            "file": fname,
            "poster": f"{stem}_poster.jpeg" if is_video else None,
            "type": "video" if is_video else "photo",
            "lat": round(lat, 6), "lon": round(lon, 6),
            "alt": round(alt, 1) if alt else None,
            "heading": round(heading, 1) if heading is not None else None,
            "hfov": None if is_video else hfov_deg(
                meta.get("FocalLength35efl"), w, h),
            "datetime": meta.get("DateTimeOriginal") or meta.get("CreateDate"),
            "camera": meta.get("Model"),
            # editorial fields — fill by hand, preserved across rebuilds
            "place": prev.get("place", ""),
            "title": prev.get("title", ""),
            "text": prev.get("text", ""),
        })

    mj.write_text(json.dumps(items, ensure_ascii=False, indent=1))
    print(f"    -> media.json: {len(items)} items")


if __name__ == "__main__":
    DATA.mkdir(parents=True, exist_ok=True)
    steps = {
        "ilhas": build_ilhas, "streams": build_streams,
        "rivers": build_rivers_named, "roads": build_roads,
        "basins": build_basins, "places": build_places, "media": build_media,
    }
    only = sys.argv[1:]
    for name, fn in steps.items():
        if only and name not in only:
            continue
        print(f"[{name}]")
        fn()
