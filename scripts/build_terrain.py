#!/usr/bin/env python3
"""Bake terrarium-encoded terrain-RGB tiles from the FABDEM mosaic.

    python3 scripts/build_terrain.py            # zooms 6-12 over the site window

Output: site/data/terrain/{z}/{x}/{y}.png, consumed by MapLibre as a
raster-dem source (encoding: terrarium). Zoom 12 (~38 m/px here) matches
FABDEM's native 30 m; MapLibre overzooms beyond that.
"""
import math
from pathlib import Path

import numpy as np
from PIL import Image
from osgeo import gdal

gdal.UseExceptions()

ROOT = Path(__file__).resolve().parent.parent
DEM = ROOT / "qgis-proj" / "dem.tif"
OUT = ROOT / "site" / "data" / "terrain"

BBOX = (-64.6, -11.4, -61.9, -8.4)  # lonmin latmin lonmax latmax (site window)
ZMIN, ZMAX = 6, 12
TILE = 256
ORIGIN = 20037508.342789244  # web-mercator half-world


def tile_of(lon, lat, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def main():
    src = gdal.Open(str(DEM))
    total = 0
    for z in range(ZMIN, ZMAX + 1):
        x0, y0 = tile_of(BBOX[0], BBOX[3], z)
        x1, y1 = tile_of(BBOX[2], BBOX[1], z)
        span = 2 * ORIGIN / (2 ** z)          # meters per tile
        bounds = (x0 * span - ORIGIN, ORIGIN - (y1 + 1) * span,
                  (x1 + 1) * span - ORIGIN, ORIGIN - y0 * span)
        w, h = (x1 - x0 + 1) * TILE, (y1 - y0 + 1) * TILE
        res = span / TILE
        # average when downsampling well below native 30 m, else bilinear
        alg = "average" if res > 60 else "bilinear"
        mem = gdal.Warp("", src, format="MEM", dstSRS="EPSG:3857",
                        outputBounds=bounds, width=w, height=h,
                        resampleAlg=alg, dstNodata=float("nan"))
        elev = mem.GetRasterBand(1).ReadAsArray().astype(np.float64)
        elev = np.nan_to_num(elev, nan=0.0)

        # quantize to 0.25 m — far below FABDEM's real precision, and the
        # near-constant blue channel lets PNG compress ~3x better
        v = np.round(np.clip(elev + 32768.0, 0, 65535.996) * 4.0) / 4.0
        r = np.floor(v / 256.0)
        g = np.floor(v) % 256
        b = np.floor((v - np.floor(v)) * 256.0)
        rgb = np.stack([r, g, b]).astype(np.uint8)

        for tx in range(x0, x1 + 1):
            d = OUT / str(z) / str(tx)
            d.mkdir(parents=True, exist_ok=True)
            for ty in range(y0, y1 + 1):
                i, j = (ty - y0) * TILE, (tx - x0) * TILE
                tile = rgb[:, i:i + TILE, j:j + TILE]
                Image.fromarray(np.moveaxis(tile, 0, -1)).save(
                    d / f"{ty}.png", optimize=True)
                total += 1
        print(f"z{z}: {(x1-x0+1)*(y1-y0+1)} tiles ({alg})")
    size = sum(f.stat().st_size for f in OUT.rglob("*.png")) / 1e6
    print(f"{total} tiles, {size:.1f} MB -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
