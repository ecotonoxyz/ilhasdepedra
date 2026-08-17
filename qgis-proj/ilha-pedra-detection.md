# Detecting *ilhas de pedra* in the Jamari region

Session record — 2026-08-08. Method, results, and what should not be trusted.

**Objective.** Count the granite inselbergs (*ilhas de pedra* — bornhardts) in
a region of Rondônia / southern Amazonas / NW Mato Grosso, starting from a bare
DEM and four example coordinates.

**Headline result.** Roughly **7,000** inselbergs in the Rio Jamari + Rio Jaru
watersheds at the model's high-confidence threshold, and a design-based estimate
of **19,000–31,000** across the full study extent. Both figures carry real
caveats, set out in §9.

---

## 1. Area of interest and coordinate system

Final extent: **lat −12.9540 to −7.7775, lon −65.6420 to −60.4892**, reached by
two extensions during the session (originally lat −11.2556 north, lon −64.6015
to −60.7118). Covers FABDEM tiles S08–S13 × W061–W066 (36 tiles).

All rasters are **EPSG:31983** (SIRGAS 2000 / UTM 23S) at the user's request.

> **Known distortion.** EPSG:31983's valid band is lon −48° to −42°. This extent
> sits 16–22° west of zone 23's central meridian — three zones over. The
> geographically correct zone is EPSG:31980 (UTM 20S). Measured on the delivered
> raster, projected distances are inflated **~4.8%** (5.7% at the west edge,
> 3.6% at the east) and the extent is skewed 2–4°.
>
> This was independently confirmed later: the ANA basin polygons reprojected to
> 31983 give 32,199 km² against ANA's published 29,090 km² for the Jamari — a
> ratio of **1.107**, exactly the 1.05² area inflation predicted by a 5% linear
> bias. Jaru matches at 1.096.
>
> **Consequence:** any *area*, *length* or *slope* read off these rasters is
> biased by that amount. Cell *counts* and topology are unaffected.

## 2. Base data

| Product | Source | Notes |
|---|---|---|
| `dem.tif` | FABDEM V1-2, 36 tiles | 20881 × 21181, 30 m, Float32, COG/DEFLATE |
| `slope.tif` | `gdaldem slope -p` | percent gradient, same grid |
| `accum.tif` | Whitebox D8 | 6960 × 7060, 90 m, cells |
| `streams.gpkg` | Whitebox | 242,981 links, Strahler 1–9 |
| `osm.gpkg` | Overpass | 60,764 lines: `highway`, `waterway`, `natural=ridge` |
| `basins_jamari_jaru.gpkg` | ANA BHO 2017 5K | 2 basins, network-walked |

Acquisition notes worth keeping:

- **FABDEM tiles arrive silently truncated.** 4 of the first 25 downloads were
  cut short by connection resets and `curl -f` still exited 0. Every tile must
  be checked against its `content-length`. All 36 were verified byte-complete.
- **Overpass 504s on a full-extent query** at this size (~60k ways). Fetch as a
  2×2 grid of sub-bboxes and merge with `osmium merge`, which dedupes by object
  id. Always confirm the closing `</osm>`.
- **The kumi.systems Overpass mirror runs a stale database** — 1–2 months behind
  on 2026-08-02. Using it as a fallback silently mixed data vintages across
  tiles; caught by comparing `<meta osm_base>` per tile and re-fetching. Prefer
  overpass-api.de with retries.
- **Flow accumulation over-captures here.** Derived FABDEM routing put the Rio
  Jamari at ~50,900 km² against ANA's 29,090. Verified *not* to be a sampling
  artefact (centre-pixel and 3×3-window sampling agree). Suspected cause:
  over-aggressive Whitebox breaching (`dist=200` cells = 18 km) jumping low
  divides in flat terrain. **Trust ANA over derived accumulation.**

## 3. Detection

### 3.1 The morphometric signature

The four labelled positives are small steep domes: summits 180–262 m rising
77–160 m above a plain at ~101 m, with footprints only 225–495 m across. The two
labelled negatives (a plateau and a range peak) are an order of magnitude wider
— the plateau is already 48 km² just 20 m below its summit.

The discriminator is therefore **scale-selective relief**, not height. A **white
top-hat** transform delivers exactly that:

```
tophat = DEM − opening(DEM, structuring element)
opening = max_filter(min_filter(DEM))
```

Opening with a 500 m element erases any positive landform narrower than ~1 km
while preserving anything broader. An 8 km plateau leaves a residual near zero
regardless of how tall it is; a 400 m dome leaves its full relief. Measured on
the examples: positives 52–128 m, negatives 29–37 m.

A square structuring element is used because scipy's rectangular filters are
separable and therefore tractable at 442 M pixels; a disk would be ~30× slower
for the same scale selection. Computed in tiles with a halo of 2×radius, which
is the full extent of the opening's influence, so tile seams are exact.

### 3.2 Detection v1 — and why it was wrong

v1 thresholded the top-hat at 45 m, took connected components, and filtered on
footprint area (0.02–5 km²) and an "isolation" criterion (relief in a 2–5 km
annulus ≤ 150 m). It produced **12,349 candidates**, recovered all 4 positives
and rejected both negatives.

It was still badly broken, and only the user's *missed-inselberg* annotations
revealed it. Of 56 points marked as inselbergs the detector had missed, **none**
was within 300 m of a candidate — median distance 3.3 km. Yet 48 of 56 sat
*inside* a ≥45 m top-hat component whose representative point was a median of
only 126 m away. The top-hat had found them; the filters threw them away:

| cause of loss | count |
|---|---|
| rejected by the ring-relief ≤ 150 gate | **26 / 56** |
| top-hat below the 45 m gate | 8 / 56 |
| component exceeded the 5 km² area cap | 10 |
| one point per component (representative >1 km from the dome) | 13 / 48 |

The ring gate was the main destroyer. It had been calibrated on four positives
that all sat in a single locality with ring relief 53–58 m; the missed points
run to 241 m. **Lesson: a threshold calibrated on a spatially clustered handful
of examples encodes that locality, not the landform class.**

### 3.3 Detection v2

Three changes, each traceable to the failure analysis above:

1. **Peaks, not components.** Every local maximum of the top-hat surface becomes
   its own candidate (240 m minimum separation), so a cluster of domes joined
   above threshold no longer collapses to one point.
2. **Threshold 45 → 30 m.**
3. **No ring gate, no area cap.** Filtering moved downstream into the
   classifier, where evidence decides, rather than into thresholds fixed before
   seeing any labels.

Result: **63,815 candidates**, recovering **56/56** of the missed points (44
within 150 m, median 67 m) while still ignoring 19 of 20 points marked as
non-inselberg. Recall fixed without simply flooding the map.

## 4. Human-in-the-loop review

Two tools were built, because morphometry alone cannot settle what is granite.

**Triage artifact** (published web page) — a stratified sample of candidates,
each shown as a 2×2 of DEM and satellite at 2 km and 10 km, with keyboard
verdicts and CSV export. DEM rendering follows `cameratopo.pedalhidrografi.co`:
elevation through the cyclic **cmocean.phase** palette (auto range, 1 cycle),
multiplied by a black-and-white slope layer so steep ground darkens. `slopeMax`
is resolved per window — the site's 16% default renders every dome flank solid
black at this scale.

**Local viewer** (`viewer/serve.py`, `http://127.0.0.1:8765`) — the full
candidate set on a map, coloured by probability, over the user's own cameratopo
relief tiles, Esri imagery or OSM. Chips are rendered live from `dem.tif` and
`slope.tif` rather than pre-baked. Three feedback modes:

| mode | records | measures |
|---|---|---|
| Inspect → ilha / not / unsure | `labels.csv` | **precision** |
| + Missed ilha (click anywhere) | `annotations.csv` | **recall** |
| + Non-ilha (click anywhere) | `annotations.csv` | true negatives outside the candidate set |

The separation matters: verdicts on detections can only ever measure precision.
The missed-inselberg annotations were the single most valuable input of the
session — they exposed the v1 filter failure, which no amount of labelling
detections would have revealed.

Final feedback: **409 labels** (196 ilha, 184 not, 29 unsure) and **78
annotations** (58 missed, 20 non-ilha).

## 5. Features

| group | features |
|---|---|
| shape | `tophat_m`, `ring_relief_m`, `plain_m`, `summit_m`, `relief_m`, `near_relief_m` |
| drainage | `d_chan_km`, `d_river_km`, `acc_near` |
| pack | `n_2km`, `n_5km`, `n_10km`, `d_3rd_km`, `nb_tophat`, `n_strong_5km` |

**Drainage** was added after the user observed many false positives along rivers.
The observation is real — river bluffs and terrace scarps are narrow, steep and
stand above their surroundings, so nothing in the shape features could reject
them:

| | within 1 km of a ≥500 km² river | ≥1000 km² accumulation within 600 m |
|---|---|---|
| ilha | 1.0% | 0.5% |
| not | **19.3%** | **17.1%** |

A near-perfect *exclusion* rule. Across all candidates only 2.8% are so affected,
so river artefacts are conspicuous but not numerous.

**Pack** was added after the user observed that inselbergs come in groups —
bornhardt fields mark an exposed pluton. The refinement that emerged: it is not
*company* that signals an ilha but *good* company. Raw neighbour counts carry
almost nothing (AUC 0.51–0.53) because the candidate set is dense everywhere
(median 41 neighbours within 5 km). The calibre of neighbours does:
`nb_tophat` 0.642, `n_strong_5km` 0.631.

All pack features derive from candidate geometry and top-hat only — never from
labels or probabilities — so nothing leaks from the training set.

## 6. Classification and validation

Gradient boosting (`HistGradientBoostingClassifier`, depth 3, 250 iterations)
on 377 matched training rows (196 ilha, 181 not; `unsure` excluded).

Validation used **25 km spatially-blocked** cross-validation as the decisive
metric. Random folds put near-neighbours in both train and test, which inflates
every spatially smooth feature:

| feature set | random-fold AUC | spatial-block AUC |
|---|---|---|
| shape only | 0.960 | 0.919 |
| shape + drainage | 0.954 | 0.920 |
| **shape + pack** (selected) | 0.970 | **0.945** |
| shape + drainage + pack | 0.964 | 0.940 |

> **Correction recorded.** An earlier reading of this session credited the
> drainage features with a jump from AUC 0.739 to 0.954. That comparison was
> confounded — the *model* changed (logistic → boosted) at the same time as the
> features. Controlled, drainage adds **+0.001** blocked AUC. The gain was the
> switch to boosting, which can express threshold relationships that logistic
> regression cannot. The river labels remain valuable; the attribution was wrong.

Two honest limits on the selected model:
- The pack margin (+0.026) is roughly 1.3–1.7 standard errors at n=377.
  Suggestive, not established.
- Pack features are spatially smooth and `n_10km` reaches 10 km against 25 km
  blocks, so some leakage survives blocking. Larger blocks would settle it.

`p_ilha` is written to `ilhas_v2.gpkg`. **It is a ranking, not a calibrated
probability** — boosted outputs are uncalibrated, so `p ≥ 0.9` means "top tier",
not "90% likely".

## 7. Counting

Model probabilities cannot be summed to a population total: they are
uncalibrated, and the labels were gathered opportunistically (clicked where the
eye went), so no weighting recovers a population estimate from them.

Instead, a **stratified random sample** of 400 candidates was drawn — 40 from
each `p_ilha` decile — and marked `batch=2`. Because the strata are equal-sized
deciles with equal allocation, **every candidate has the same inclusion
probability**: the design is self-weighting and the simple ratio *is* the
design-based estimator. Stratification only trims variance, so the intervals
below are, if anything, conservative.

At **92 / 400 labelled** (27 ilha, 48 not, 17 unsure):

| `unsure` treated as | rate | total | 95% CI |
|---|---|---|---|
| not | 0.293 | **18,728** | 12,795 – 24,662 |
| half | 0.386 | **24,624** | 18,281 – 30,968 |
| ilha | 0.478 | **30,520** | 24,011 – 37,029 |

The rate barely moved as the sample grew from 39 to 92 (0.308 → 0.293), which
suggests the labelled subset is not badly biased. Completing batch 2 would cut
the half-width from ±6,520 to ≈±3,127. The 27 `unsure` verdicts are the largest
single source of uncertainty — they swing the total by ~12,000.

## 8. Basin results

Basins were built from **ANA BHO 2017 5K**, walking the drainage network upstream
through `COTRECHO`/`NUTRJUS` from each outlet (Jamari `COBACIA 463611`, Jaru
`4634411`), then dissolving the corresponding incremental drainage-area polygons.

DEM delineation was attempted first and abandoned. An OSM centreline ends *at*
its confluence, so its last vertex sits on the trunk: the first pour point
snapped onto the Madeira and returned **163,971 km²** for the Jamari.
Accumulation-jump detection overshot the other way to **12,194 km²** — the reach
above the Rio Candeias junction. ANA's network walk reproduces the published
outlet areas exactly.

At `p_ilha > 0.9`:

| basin | area (ANA) | candidates | **p > 0.9** |
|---|---|---|---|
| Rio Jamari | 29,090 km² | 10,210 | **5,620** |
| Rio Jaru | 7,274 km² | 3,087 | **1,335** |
| **Combined** | 36,364 km² | 13,297 | **6,955** |

≈ one per 5.2 km². The two basins hold 21% of all candidates but 36% of the
p > 0.9 ones.

## 9. Comparison with published densities

| study | density | one per |
|---|---|---|
| Southern Zimbabwe, younger granitoids | 2.2 / 10 km² | 4.5 km² |
| Atlantic Forest + Caatinga, Brazil (3,612 over 15,000 km²) | 0.241 / km² | 4.2 km² |
| **This work (Jamari + Jaru)** | 0.191 / km² | **5.2 km²** |

Same order of magnitude, on the conservative side — 87% of the Zimbabwe density
and 79% of the Brazilian one. But the comparison is softer than it looks:

- Both comparators are **pre-selected inselberg country** (six 50×50 km grids
  chosen to sample inselberg habitat; younger granitoid outcrop only). This work
  covers entire watersheds including floodplain and sedimentary cover. Normalised
  to granite outcrop, this density would come out *higher* than both.
- **Size thresholds do not match** and could not be recovered from either source.
  A 30 m DEM catches smaller features than air-photo mapping.
- Both are **modelled, not field-verified** — the Brazilian count came from a
  gradient-boosting model on remote sensing, methodologically close to this work,
  so it is not independent confirmation.

Sources: Geomorphology 72:156 (2005) and 87:1-2 (2007) for Zimbabwe;
*Perspectives in Ecology and Conservation* (2022) for Brazil.

## 10. What should not be trusted

1. **`p_ilha` is not a probability.** Ranking only.
2. **6,955 is a threshold count, not an estimate.** The defensible statement is
   "on the order of 7,000".
3. **Lithology is unverified.** Nothing here confirms granite. A CPRM geology
   intersect would make "ilha de pedra" a claim about rock rather than shape, and
   would also allow the density comparison above to be done properly.
4. **Recall beyond the annotated points is unmeasured.** v2 recovers 56/56 known
   misses, but those were found by eye in areas the user chose to inspect.
5. **Areas and lengths inherit the EPSG:31983 bias** (§1).
6. **Derived flow accumulation over-captures** (§2).

## 11. Files

```
dem.tif                    30 m DEM, EPSG:31983
slope.tif                  percent gradient, same grid
accum.tif                  90 m D8 flow accumulation, cells
streams.gpkg               242,981 stream links, Strahler + accumulation
osm.gpkg                   60,764 OSM lines (highway/waterway/ridge)
ilhas_de_pedra.gpkg        v1 candidates (12,349) — superseded, kept for comparison
ilhas_v2.gpkg              v2 candidates (63,815) + features + p_ilha + batch
basins_jamari_jaru.gpkg    ANA-derived basins, with ana_km2 and proj_km2
ana_bho.gpkg               ANA BHO trechos, original extent only
viewer/                    serve.py, index.html, labels.csv, annotations.csv
```

## 12. Reproducing / continuing

```bash
cd viewer && OMP_NUM_THREADS=1 python3 serve.py     # → http://127.0.0.1:8765
```

`OMP_NUM_THREADS=1` is required: sklearn and GDAL abort each other in one
process on this machine (exit 134). For the same reason, model fitting and
GeoPackage writing are run as **separate processes**.

**Highest-value next steps, in order:**

1. **Finish batch 2** (308 candidates remaining). The only thing that narrows
   the count. Use the "Only review batch 2" filter; label them in map order, not
   by which look decidable, or the estimate reacquires the bias the random sample
   was drawn to avoid.
2. **Resolve the `unsure` verdicts** — 29 of them, swinging the total by ~12,000.
3. **Intersect with CPRM geology** to make the result about granite.
4. **Re-check the count after any refit**: the model was last fitted at 377
   training rows (404 labels); the files now hold 409. A refit will shift
   `p_ilha` and therefore the basin counts slightly.
