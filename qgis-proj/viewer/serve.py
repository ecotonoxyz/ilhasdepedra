#!/usr/bin/env python3
"""Local viewer and annotation tool for the ilha-de-pedra candidates.

    python3 serve.py [port]        # default 8765, then open http://127.0.0.1:8765

Two kinds of feedback, kept in separate files:

  labels.csv        verdicts on candidates the detector found (fid, label)
                    -> measures PRECISION
  annotations.csv   free points clicked anywhere on the map (lat, lon, kind)
                    -> "missed" records an inselberg the detector did NOT find,
                       which is the only way to measure RECALL; "not" records a
                       confirmed non-inselberg outside the candidate set.

Endpoints:
  /                        the map page
  /points.geojson          all candidates with attributes and p_ilha
  /chip|/sat               ?fid= or ?lat=&lon=, plus &win= metres
  /labels        GET  ·  /label       POST {fid,label}
  /annotations   GET  ·  /annotation  POST {lat,lon,kind[,id,note]} · /annotation/delete POST {id}
  /labels.csv  ·  /annotations.csv    downloads
"""
import io
import json
import csv
import os
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import numpy as np
from osgeo import gdal, ogr, osr
from PIL import Image

gdal.UseExceptions()
ogr.UseExceptions()

HERE = os.path.dirname(os.path.abspath(__file__))
QGIS = os.path.dirname(HERE)
# Prefer the v2 candidate set (peak-based, no hard gates) when present.
GPKG = os.path.join(QGIS, "ilhas_v2.gpkg")
GPKG_LAYER = "candidates"
if not os.path.exists(GPKG):
    GPKG = os.path.join(QGIS, "ilhas_de_pedra.gpkg")
    GPKG_LAYER = None
DEM = os.path.join(QGIS, "dem.tif")
SLOPE = os.path.join(QGIS, "slope.tif")
PHASE_TXT = os.path.join(HERE, "phase-rgb.txt")
LABELS = os.path.join(HERE, "labels.csv")
ANNOTS = os.path.join(HERE, "annotations.csv")
PX = 30.0

FIELDS = ["tophat_m", "ring_relief_m", "plain_m", "summit_m", "relief_m",
          "near_relief_m", "area_km2", "slope_p95", "p_ilha", "label", "batch"]

_lock = threading.Lock()
_wlock = threading.Lock()
_dem = gdal.Open(DEM)
_slp = gdal.Open(SLOPE)
_gt = _dem.GetGeoTransform()
_inv = gdal.InvGeoTransform(_gt)
_W, _H = _dem.RasterXSize, _dem.RasterYSize
PHASE = np.loadtxt(PHASE_TXT) * 255.0

_wgs = osr.SpatialReference(); _wgs.ImportFromEPSG(4326)
_wgs.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
_utm = osr.SpatialReference(); _utm.ImportFromEPSG(31983)
_utm.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
_merc = osr.SpatialReference(); _merc.ImportFromEPSG(3857)
_merc.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
_to_merc = osr.CoordinateTransformation(_wgs, _merc)
_to_utm = osr.CoordinateTransformation(_wgs, _utm)


def load_points():
    ds = ogr.Open(GPKG)
    lyr = ds.GetLayerByName(GPKG_LAYER) if GPKG_LAYER else ds.GetLayer()
    have = {f.GetName() for f in lyr.schema}
    feats, xy = [], {}
    for f in lyr:
        g = f.GetGeometryRef()
        fid = f.GetFID()
        props = {"fid": fid}
        for k in FIELDS:
            if k in have:
                v = f.GetField(k)
                props[k] = round(v, 3) if isinstance(v, float) else v
        lat, lon = f.GetField("lat"), f.GetField("lon")
        props["lat"], props["lon"] = round(lat, 5), round(lon, 5)
        xy[fid] = (g.GetX(), g.GetY(), lat, lon)
        feats.append({"type": "Feature", "id": fid,
                      "geometry": {"type": "Point",
                                   "coordinates": [round(lon, 5), round(lat, 5)]},
                      "properties": props})
    return feats, xy


POINTS, XY = load_points()
GEOJSON = json.dumps({"type": "FeatureCollection", "features": POINTS},
                     separators=(",", ":")).encode()
print(f"loaded {len(POINTS):,} candidates from {os.path.basename(GPKG)}")

_labels = {}
if os.path.exists(LABELS):
    for r in csv.DictReader(open(LABELS)):
        try:
            _labels[int(r["fid"])] = r["label"]
        except (ValueError, KeyError):
            pass
else:
    for p in POINTS:
        if p["properties"].get("label"):
            _labels[p["id"]] = p["properties"]["label"]

_annots = {}
_next_id = 1
if os.path.exists(ANNOTS):
    for r in csv.DictReader(open(ANNOTS)):
        try:
            i = int(r["id"])
            _annots[i] = {"id": i, "lat": float(r["lat"]), "lon": float(r["lon"]),
                          "kind": r["kind"], "note": r.get("note", "")}
            _next_id = max(_next_id, i + 1)
        except (ValueError, KeyError):
            pass
print(f"labels on file: {len(_labels)}   annotations on file: {len(_annots)}")


def save_labels():
    with _wlock:
        tmp = LABELS + ".tmp"
        with open(tmp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["fid", "lat", "lon", "label"])
            for fid, v in sorted(_labels.items()):
                if fid in XY:
                    w.writerow([fid, round(XY[fid][2], 5), round(XY[fid][3], 5), v])
        os.replace(tmp, LABELS)


def save_annots():
    with _wlock:
        tmp = ANNOTS + ".tmp"
        with open(tmp, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["id", "lat", "lon", "kind", "note"])
            for i, a in sorted(_annots.items()):
                w.writerow([i, round(a["lat"], 5), round(a["lon"], 5),
                            a["kind"], a.get("note", "")])
        os.replace(tmp, ANNOTS)


def render_dem(z, s_pct):
    lo, hi = np.nanmin(z), np.nanmax(z)
    u = (z - lo) / max(hi - lo, 1e-6)
    rgb = PHASE[np.clip((u * 255.0).astype(int), 0, 255)]
    sm = max(np.nanpercentile(s_pct, 98) / 100.0, 0.15)
    gray = 1.0 - np.clip((s_pct / 100.0) / sm, 0, 1)
    return np.clip(rgb * gray[..., None], 0, 255).astype("uint8")


def utm_of(fid=None, lat=None, lon=None):
    if fid is not None and fid in XY:
        return XY[fid][0], XY[fid][1], XY[fid][2], XY[fid][3]
    x, y, _ = _to_utm.TransformPoint(lon, lat)
    return x, y, lat, lon


def dem_chip(x, y, win_m, out_px=384):
    k = max(int(win_m / 2 / PX), 4)
    col = int(_inv[0] + _inv[1] * x + _inv[2] * y)
    row = int(_inv[3] + _inv[4] * x + _inv[5] * y)
    c0, r0 = max(col - k, 0), max(row - k, 0)
    c1, r1 = min(col + k, _W), min(row + k, _H)
    if c1 <= c0 or r1 <= r0:
        img = Image.new("RGB", (out_px, out_px), (24, 27, 33))
    else:
        with _lock:
            z = _dem.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0)
            s = _slp.GetRasterBand(1).ReadAsArray(c0, r0, c1 - c0, r1 - r0)
        z = z.astype("float64"); s = s.astype("float64")
        bad = z == -9999
        if bad.all():
            img = Image.new("RGB", (out_px, out_px), (24, 27, 33))
        else:
            z[bad] = np.nan; s[bad] = np.nan
            z = np.where(np.isnan(z), np.nanmedian(z), z)
            s = np.where(np.isnan(s), 0.0, s)
            img = Image.fromarray(render_dem(z, s)).resize((out_px, out_px), Image.BICUBIC)
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def sat_chip(lat, lon, win_m, out_px=384):
    xm, ym, _ = _to_merc.TransformPoint(lon, lat)
    half = (win_m / 2.0) / np.cos(np.radians(lat))
    url = ("https://services.arcgisonline.com/arcgis/rest/services/World_Imagery"
           f"/MapServer/export?bbox={xm-half},{ym-half},{xm+half},{ym+half}"
           f"&bboxSR=3857&imageSR=3857&size={out_px},{out_px}&format=jpg&f=image")
    with urllib.request.urlopen(url, timeout=45) as r:
        return r.read()


def probe(lat, lon):
    """Elevation and slope at a clicked point, so free annotations get numbers too."""
    x, y, _ = _to_utm.TransformPoint(lon, lat)
    col = int(_inv[0] + _inv[1] * x + _inv[2] * y)
    row = int(_inv[3] + _inv[4] * x + _inv[5] * y)
    if not (0 <= col < _W and 0 <= row < _H):
        return {}
    with _lock:
        z = _dem.GetRasterBand(1).ReadAsArray(col, row, 1, 1)
        s = _slp.GetRasterBand(1).ReadAsArray(col, row, 1, 1)
    zv, sv = float(z[0][0]), float(s[0][0])
    return {"summit_m": None if zv == -9999 else round(zv, 1),
            "slope_p95": None if sv == -9999 else round(sv, 1)}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _send(self, body, ctype, code=200, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200):
        self._send(json.dumps(obj).encode(), "application/json", code)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path in ("/", "/index.html"):
                with open(os.path.join(HERE, "index.html"), "rb") as fh:
                    return self._send(fh.read(), "text/html; charset=utf-8")
            if u.path == "/points.geojson":
                return self._send(GEOJSON, "application/geo+json")
            if u.path == "/labels":
                return self._json(_labels)
            if u.path == "/annotations":
                return self._json(list(_annots.values()))
            if u.path in ("/labels.csv", "/annotations.csv"):
                if u.path == "/labels.csv":
                    save_labels(); path = LABELS
                else:
                    save_annots(); path = ANNOTS
                if not os.path.exists(path):
                    return self._send(b"", "text/csv")
                with open(path, "rb") as fh:
                    return self._send(fh.read(), "text/csv", extra={
                        "Content-Disposition":
                            f'attachment; filename="{os.path.basename(path)}"'})
            if u.path in ("/chip", "/sat"):
                win = float(q.get("win", ["2000"])[0])
                if "fid" in q:
                    x, y, lat, lon = utm_of(fid=int(q["fid"][0]))
                else:
                    lat, lon = float(q["lat"][0]), float(q["lon"][0])
                    x, y, lat, lon = utm_of(lat=lat, lon=lon)
                if u.path == "/chip":
                    return self._send(dem_chip(x, y, win), "image/png")
                return self._send(sat_chip(lat, lon, win), "image/jpeg")
            if u.path == "/probe":
                return self._json(probe(float(q["lat"][0]), float(q["lon"][0])))
            self._send(b"not found", "text/plain", 404)
        except Exception as e:
            self._send(f"{type(e).__name__}: {e}".encode(), "text/plain", 500)

    def do_POST(self):
        global _next_id
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length", 0))
            d = json.loads(self.rfile.read(n) or b"{}")

            if u.path == "/label":
                fid = int(d["fid"])
                v = d.get("label") or ""
                if v:
                    _labels[fid] = v
                else:
                    _labels.pop(fid, None)
                save_labels()
                return self._json({"ok": True, "total": len(_labels)})

            if u.path == "/annotation":
                i = int(d["id"]) if d.get("id") else _next_id
                if not d.get("id"):
                    _next_id += 1
                _annots[i] = {"id": i, "lat": float(d["lat"]), "lon": float(d["lon"]),
                              "kind": d.get("kind", "missed"), "note": d.get("note", "")}
                save_annots()
                return self._json({"ok": True, "annotation": _annots[i],
                                   "total": len(_annots)})

            if u.path == "/annotation/delete":
                _annots.pop(int(d["id"]), None)
                save_annots()
                return self._json({"ok": True, "total": len(_annots)})

            self._send(b"not found", "text/plain", 404)
        except Exception as e:
            self._send(f"{type(e).__name__}: {e}".encode(), "text/plain", 500)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"\n  ilhas de pedra viewer  ->  http://127.0.0.1:{port}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        save_labels(); save_annots()
        print("\nsaved", LABELS, "and", ANNOTS)
