# Ilhas de Pedra do Vale do Jamari

Single-page interactive geospatial experience for the *Ilhas de Pedra do Vale
do Jamari* exhibit — thousands of granite inselbergs around Ariquemes (RO),
their geology, and geolocated field photos/videos. Hosted at
`www.ecotono.xyz/ilhasdepedra`.

## Layout

```
site/            the deployable static page (index.html + data/ + media/ + terrain/)
scripts/         build_data.py (site/data + site/media) · build_terrain.py (3D tiles)
images/          original field photos/videos (EXIF GPS is the source of truth)
assets/          the printed booklet (PDF)
qgis-proj/       geodata + detection work (see its ilha-pedra-detection.md)
```

## The page

- **Basemap** — the booklet's phase×slope relief, served live by
  `cameratopo.pedalhidrografi.co` (FABDEM 30 m, `elevMin=80 elevMax=350`);
  Esri World Imagery as the satellite toggle. Tiles are render-on-demand and
  CDN-cached; after changing tile params, pre-warm the cache (loop over the
  z6–12 tiles with curl) or first visitors wait ~9 s per cold tile.
- **Ilhas** — `site/data/ilhas.geojson`: detector candidates with
  `p_ilha ≥ 0.9` inside the display window, plus every field-confirmed ilha
  (`conf: 1`). The public ID (`iid`) is the feature `fid` in
  `qgis-proj/ilhas_v2.gpkg` — stable as long as that file isn't rewritten.
- **Fotos/vídeos** — markers built from `site/data/media.json`; FOV cones are
  drawn for items with a compass heading (`GPSImgDirection`), aperture from
  the 35 mm-equivalent focal length.
- Streams (Strahler ≥ 5), named OSM rivers, main roads, basin outlines and
  place labels complete the cartography.
- **3D terrain** — `site/data/terrain/`: terrarium-encoded raster-dem tiles
  (z6–12) baked from `qgis-proj/dem.tif` by `scripts/build_terrain.py`
  (needs the DEM locally — it is not in git). Elevation quantized to 0.25 m,
  exaggeration 1.6 set in the map style.

## Updating content

1. Drop new photos/videos into `images/` (keep GPS EXIF — beware exports
   that strip it).
2. `python3 scripts/build_data.py` (needs GDAL CLI, exiftool, ffmpeg —
   pass step names to run a subset, e.g. `... build_data.py media`).
3. Fill `place`, `title`, `text` (the narrative) for each item in
   `site/data/media.json`. These fields survive rebuilds.

Approximate label coordinates (municipality seats, serras) live in
`scripts/build_data.py` — correct them there, not in the generated files.

`site/zine.pdf` is the web version of the booklet, regenerated with
`gs -dPDFSETTINGS=/ebook` from `assets/ilhas de pedra do jamari.pdf`.
The in-site viewer reads page images from `site/zine/p%02d.jpg`
(`gs -sDEVICE=jpeg -r120`); if the page count changes, update the `ZN`
constant in `site/index.html`.

## Preview and deploy

```
python3 -m http.server 8811 -d site    # → http://localhost:8811
```

Production is the `www.ecotono.xyz` Cloud Run server, which serves the
`ecotono-data` GCS bucket's `site/` directory as web root. Deploy is just:

```
gcloud storage rsync --recursive site gs://ecotono-data/site/ilhasdepedra
```

Content is live on the next request (the bucket is mounted at /data).
**Caveat:** `gcs-push.sh --mirror` in the www.ecotono.xyz repo mirrors *its*
`site/` over the bucket and would delete `site/ilhasdepedra` — re-run the
rsync above after any `--mirror` push.

Share links: `…/ilhasdepedra/#m/IMG_8941` opens straight onto that photo.
