# Footprint widths: implementation and validation — 17 October 2026

The pipeline and API integration are implemented, but **the proposed city-wide reliable width claim failed validation**. Only **18,268/100,388 drivable non-main OSM ways (18.2%)** pass the footprint sampling filter. Their calibrated uncertainty is **±11.41 m**, too broad to resolve normal car access. The new `footprint_widths` flag is **OFF by default**, separate from the older failed `building_gaps` experiment. It can be enabled for inspection. No paid Gemini, cadastral portal calls, crawler file writes, process interference or commits were performed.

## Data and licence

- Overture Maps **buildings release 2026-09-23.1**, public S3 GeoParquet via DuckDB, downloaded **17 October 2026, 00:55:59 ICT** (manifest: `2026-10-16T17:55:59.644003+00:00`). Downloading is not a new image acquisition date; imagery dates are not known.
- Bbox: west 106.55, south 10.68, east 106.88, north 10.90, with a 0.0003° building halo. This is the requested urban rectangle, **not every administrative part of HCMC**.
- **1,157,746** footprints: Microsoft ML Buildings **608,902**; Google Open Buildings **461,741**; OpenStreetMap **87,103**.
- Overture's combined buildings theme is **ODbL 1.0**. Microsoft and OSM upstream data are ODbL; Google Open Buildings is **CC BY 4.0**. The derived width database is offered under ODbL 1.0. Attribution: © OpenStreetMap contributors, Overture Maps Foundation; Microsoft; Google Open Buildings. [Overture licensing](https://docs.overturemaps.org/attribution/#buildings), [building geometry and sources](https://docs.overturemaps.org/guides/buildings/).
- Raw input: `data/raw/buildings/hcmc_buildings.parquet` (~88 MiB; gitignored); version, source counts, URI and SHA-256 in `manifest.json` and [footprint-calibration.json](footprint-calibration.json).
- OSM: reused `data/raw/overture/hcmc_small_roads.json` and **read-only** crawler `backend/cache/osm/city_batches/*.json`, plus four bbox edge strips (one was also diagnosed in two sequential halves). Cache ages differ; this is **not a fresh, synchronized OSM snapshot**. Edge response timestamps range from June to October 2026. The canonical combined snapshot is `data/raw/buildings/roads.json`; its hash and input provenance are recorded in the calibration report.
- Cadastral calibration: read-only snapshot of `city_parcels.json` and `areas/*.json`, deduplicated by way and coordinate: **242 ways / 431 cuts**. Snapshot input hashes are saved. No requests to the portal; no changes to its rate limits or gate.

## Measurement and coverage

- Cohort: **100,388** ways passing the backend's drivable/access rules, excluding main-road classes. Motorcar prohibitions, private access and motorbike-only ways are excluded. Not all of these ways are named alleys: **35,657** are named/tagged as alleys.
- Perpendicular cuts every **10 m**, ±15 m rays, 5 m junction offsets; short ways get a midpoint. Full polygons, multipolygons, holes and polygon interiors are preserved. Reject centreline-in-building, a shared building on both sides, and side distances under 0.3 m. No hit on either side is **open/unknown**, never evidence of a wide road.
- Shapely STRtree, **54 spatial tiles / 6 processes**. Raw per-cut gap, location along way, source pair and rejection status are retained under `data/raw/buildings/tiles_*` and `measurements.json`. P10, P20 and median are retained before calibration; the shipped estimate uses the conservative P10.
- **210,688** usable two-sided cuts, **797,472** open-side cuts, **3,996** centreline-in-building cuts, **3,378** misaligned cuts; **9** degenerate ways explicitly remain in the denominator.
- **55,677** ways have at least one valid two-sided cut. Shipping candidates require ≥3 valid cuts and ≥40% of cuts valid: **18,268** ways, including **7,650/35,657 named/tagged alleys (21.45%)**. The remainder stay unknown to this source. Sampling does not prove the narrowest point between cuts.
- Runtime: building download **152.7 s**; final local measurement **32.4 s**. First footprint fetch to first final calibrated product was approximately **8 minutes**, including OSM retries and the measurement correction/re-run; this is not a reproducible network SLA. Calibration and integration were developed interactively. Software: DuckDB 1.5.6, Shapely 2.1.2, NumPy 2.2.6; Matplotlib 3.9.2 for rendering.

## Calibration and credibility

At each cached cadastral coordinate, remeasure the perpendicular footprint gap on the same OSM way. Compare to **`gap_m` before the 1 m margin**, never `width_m`. Keep points ≤2 m from the OSM centreline. Only **170 cuts on 117 ways** have a usable matched footprint observation. This is all usable overlap in the snapshot, not a claim of hundreds of validated ways.

Each way has equal calibration weight: the median of its paired cut errors. Raw footprint-minus-cadastre errors across 117 ways:

- Signed median **+6.611 m**; mean bias **+6.773 m**.
- Median absolute error **6.611 m**; MAE **7.286 m**; P90 absolute error **14.220 m**.
- Cut-weighted values are separately retained in JSON; deep scans do not dominate the fit.

Raw errors by nearest-building source pair, in metres:

| Source pair | Ways | Mean bias | Median absolute | MAE | P90 absolute |
|---|---:|---:|---:|---:|---:|
| Google Open Buildings | 8 | 8.78 | 8.85 | 9.61 | 17.52 |
| Google Open Buildings + Microsoft ML Buildings | 23 | 7.09 | 6.05 | 7.09 | 14.86 |
| Google Open Buildings + OpenStreetMap | 7 | 6.97 | 6.79 | 7.50 | 14.31 |
| Microsoft ML Buildings | 54 | 6.82 | 7.10 | 7.34 | 13.26 |
| Microsoft ML Buildings + OpenStreetMap | 21 | 5.53 | 5.28 | 6.54 | 11.16 |
| OpenStreetMap | 4 | 6.51 | 7.30 | 6.51 | 10.35 |

Deterministic **way-disjoint** 60/20/20 SHA-256 split: **74 fit / 19 residual calibration / 24 test** ways. Median fitted bias correction: subtract **6.227 m**. A finite-sample 90% split-conformal absolute residual rank gives the error radius; it is widened when needed by P10-versus-official-P20 residuals on **10** eligible bottleneck-calibration ways. There is not enough data for credible source-specific corrections or geographic holdouts.

On the untouched test ways: signed median error **+0.434 m**, mean bias **+1.772 m**, median absolute error **3.609 m**, MAE **4.917 m**, P90 absolute error **10.664 m**. Radius **±11.413 m**, covering **23/24 (95.8%)** held-out matched way medians. That coverage is an empirical result, not a city-wide guarantee or validation of each way's bottleneck/clear width.

**A constant training-median cadastral gap beats the footprint correction:** held-out MAE **1.810 m**, P90 **3.833 m**; held-out raw gap correlation **r = 0.063**. These data do not reliably distinguish narrow from wide alleys. No substitute constant width is published as if it were a measurement. The calibration is geographically concentrated around existing scans and does not test obstacles or roof-overhang errors against physical tape measurements.

Tier **Inferred** follows CONTEXT/Q11: algorithmic imagery is an inference; it is not a direct driver observation or official survey. Clear Width estimate = `max(0.5, p10 − bias − 1 m)` using the same encroachment assumption as cadastral widths. The interval extends from that bottleneck estimate minus the calibrated radius to the corrected median plus the radius, with an additional **±0.5 m** obstacle allowance. This allowance is an explicit assumption, not a calibrated obstacle measurement.

## Integration

- `backend/cache/live/footprint_widths.json` (~11 MiB): compact per-way bounds, P10/median, counts, source, calibration, cohort and provenance. Raw cut diagnostics remain gitignored.
- `backend/app/footprints.py` reloads on mtime/size change after atomic publication, retains a last good cache after malformed replacement, and clears removed files.
- Evidence loads bounds with Vietnamese source/date/details and feature `footprint_widths`. `plan.area()` refreshes the store **before** using its version in the width cache. Flag changes also change the plan cache key.
- A Measured/Official bound causes footprint evidence to be recorded as overruled and **excluded from combination entirely**, even when intervals overlap. Generic OSM class priors are excluded when an enabled footprint interval is used, so they cannot shrink calibrated uncertainty. Stronger Observed/Declared evidence otherwise keeps the established tier ordering.
- `/api/config.coverage` reports unique ways and named/tagged alleys with source width evidence, strongest tier, candidate stats, quality and flag state. It **excludes generic OSM road-class priors** from the coverage claim. Counts do not mean a vehicle verdict is resolved.
- Verification snapshot with the experiment enabled: **23,840/100,388 ways (23.75%)**, **12,524/35,657 alleys (35.12%)** have some source width evidence. With footprints disabled: **7,156 ways (7.13%)**, **6,265 alleys (17.57%)**. These counts depend on source flags and concurrent cadastral growth. [Both snapshots](footprint-coverage.json).

Strongest tier, experiment enabled (mutually exclusive):

| Tier | All non-main drivable ways | Named/tagged alleys |
|---|---:|---:|
| Measured | 0 | 0 |
| Official | 247 | 244 |
| Observed | 6,040 | 5,161 |
| Declared | 866 | 857 |
| Inferred | 16,687 | 6,262 |

## Six HTTP plan checks

Real FastAPI ASGI `/api/plan` requests, Vios, pickup, 17 October 2026 10:00 ICT, 15-minute stay. Real cached OSM graphs and `live.apply` cadastral merge; OSM network fetch is blocked and Goong is disabled in the verifier. No lifespan background refresh, AI or portal calls. Request coordinates and summaries are in [footprint-verification.json](footprint-verification.json); full response bodies remain in `data/raw/buildings/verification_*.json`.

| District / alley | OSM way | Width Range m | Top tier | Door fit | Plan verdict |
|---|---:|---|---|---|---|
| Q8 · Hẻm 689 Đường Ba Đình | 193729286 | 0.50–19.49 | Inferred | unknown | Dừng đón/trả tại Ba Đình, đi bộ 36 m (~1 phút) |
| Gò Vấp · Hẻm 1446/2 Lê Đức Thọ | 327452981 | 0.50–18.33 | Inferred | unknown | Dừng đón/trả tại Lê Đức Thọ, đi bộ 97 m (~1 phút) |
| Tân Phú · Hẻm 137 Trịnh Đình Trọng | 373721652 | 0.50–19.29 | Inferred | unknown | Dừng đón/trả tại Trịnh Đình Trọng, đi bộ 110 m (~2 phút) |
| Bình Thạnh · Hẻm 441/14 Điện Biên Phủ | 610082013 | 1.50–3.97 | Official | unknown | Dừng đón/trả tại Hẻm 441 Điện Biên Phủ, đi bộ 78 m (~1 phút) |
| Bình Thạnh · Hẻm 441/32 Điện Biên Phủ | 610082016 | 1.50–1.61 | Official | no | Dừng đón/trả tại Hẻm 69/35 đường D2, đi bộ 120 m (~2 phút) |
| Bình Thạnh · Hẻm 29 Nguyễn Gia Trí | 192512348 | 3.36–6.44 | Official | tight | Dừng đón/trả tại Hẻm 29/2 Nguyễn Gia Trí, đi bộ 32 m (~1 phút) |

The three footprint-only doors are **1.76 km, 6.44 km and 2.50 km** from the nearest calibration snapshot cut. They return actual footprint source text and keep fit unknown. All three cadastral cases contain overruled footprint evidence and return **identical Official bounds when footprints are switched off**. Each plan returns HTTP 200 and offers a nearby pickup instead of promising entry at the uncertain door.

## Visual and checks

- [coverage-footprints.png](coverage-footprints.png), **3840 × 2160**. Colours represent the corrected conservative point estimates, not validated vehicle permissions. The image explicitly states experimental status, ±11.4 m error, grey unknown coverage, bbox limits and attribution. Class thresholds: <2 m xe máy, <3 m ba gác, <5 m xe hơi, ≥5 m ô tô tránh. Because uncertainty overlaps classes, it is **not a ground-truth width-class map**.
- **20 tests passed, 23 subtests passed**, including 9 footprint safety regressions and existing agent tests. Six plan checks and `/api/config` partition assertions passed. `git diff --check` passed. Existing dependency/deprecation warnings were not changed.

## Files added or changed by this task

`backend/app/footprints.py`, `backend/app/evidence.py`, `backend/app/flags.py`, `backend/app/plan.py`, `backend/app/coverage.py`, `backend/tests/test_footprints.py`, `backend/cache/live/footprint_widths.json`, `pipelines/footprints_city.py`, `pipelines/render_footprints.py`, `pipelines/verify_footprints.py`, `pipelines/requirements-footprints.txt`, `docs/decision-log.md`, `docs/eval/footprint-report.md`, `docs/eval/footprint-calibration.json`, `docs/eval/footprint-verification.json`, `docs/eval/footprint-coverage.json`, `docs/eval/coverage-footprints.png`. Raw building/road/measurement/snapshot files are under already-gitignored `data/raw/buildings/`. Pre-existing changes elsewhere in the worktree were preserved.

## Reproduce

```sh
python3 -m pip install -r pipelines/requirements-footprints.txt
python3 pipelines/footprints_city.py all --workers 6
PYTHONPATH=backend:. python3 pipelines/verify_footprints.py
python3 pipelines/render_footprints.py
PYTHONPATH=backend:. python3 -m pytest -q backend/tests/test_footprints.py backend/tests/test_agent.py backend/tests/test_agent2.py
```

A cached cadastral snapshot is reused for deterministic evaluation; remove **only this pipeline's** `data/raw/buildings/cadastral_snapshot.json` to take a newer read-only snapshot. Tile cache keys include the building hash, road hash, snapshot hash and recipe. To inspect evidence, enable `footprint_widths` via the existing flag UI/API or `FLAG_FOOTPRINT_WIDTHS=1` on a separate backend process. It is intentionally disabled by default after the failed accuracy check.
