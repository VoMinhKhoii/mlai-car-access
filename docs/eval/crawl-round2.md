# HCMC crawl round 2 — live status and handoff

Observed **2026-10-17T00:38:20.517891+07:00**. The implementation is running; full campus cadastral completion is **not** claimed. No commit was created. No frontend file was edited by this task. No paid Gemini request was made; the regular crawler uses no AI, and the explicitly requested campus `live.build` jobs allow only the free Gemini keys.

## Operation

- Crawler **PID 65505**, parent PID 1, **nice 10**. Console: `backend/cache/live/crawl_city.out`; log: `backend/cache/live/crawl_city.log`.
- API **PID 66342**, serving `http://127.0.0.1:8787`. It has the new coverage fields, tide refresher, atomic graph reload, and full-campus evidence precedence.
- Automatic stop: completion of campus priority followed by the city sweep, or **17 October 2026, 13:00 Asia/Ho_Chi_Minh**, whichever comes first. The deadline watchdog saves accepted results and terminates remaining workers.
- Stop: `kill -TERM 65505`. The cache and state are atomically persisted; uncompleted ways retry on resume. A writer lock prevents a duplicate crawler.
- Resume from an interactive terminal: `nohup nice -n 10 python3 -u pipelines/crawl_city.py --cuts 1 --stop-at 2026-10-17T13:00:00+07:00 >> backend/cache/live/crawl_city.out 2>&1 < /dev/null &`. This run was detached using `subprocess.Popen(start_new_session=True)` as well as nohup.
- Read current progress: `python3 pipelines/crawl_status.py`. Refresh the report snapshot: `python3 pipelines/crawl_status.py --output docs/eval/crawl-round2.json`.

## Bulk parcel investigation

**No usable public bulk cadastral geometry endpoint was found.** This is an observed access limit, not a claim that no internal bulk service exists.

The planning app's `js/guest.map.demo.js` and actual browser resources were inspected. Its `https://sqhkt-qlqh.tphcm.gov.vn/api/tiles/bandoso/{z}/{x}/{y}` layer is **256 px PNG**, including the sampled z17 tile. It cannot support survey-grade alley gaps. The app's `/computing/930/api/v3.1/a-z/all` exposes Lat/Lon point queries, and the coordinate-report form did not return a collection of parcels. Other declared routes concern planning projects, legends and downloads, rather than a parcel bbox collection. The declared `gis.vlab.tech:8443/geoserver/...` service refused connections; the 443 endpoint returned 404.

The [official TNMT GeoServer](https://geodata-stnmt.tphcm.gov.vn/geoserver/wms?service=WMS&request=GetCapabilities) was also inspected. WMS advertises district `ranhthua_*` groups and underlying `v_binhthanh_p*` layers, but WFS `GetFeature` for those names returns **feature type unknown**. WMS `GetFeatureInfo` returned zero features, and the MVT GetMap request returned **unsupported format**. The public city-map app at `bando.tphcm.gov.vn` returned a permission-denied response for its layer catalog; no bypass was attempted. Its building vector tiles are not cadastral parcels. The visible citywide TNMT cadastral WMS metadata says **updated through 2010**, so it would not establish current parcel geometry even if it were extractable.

The successful TNMT WFS district-boundary response supplies **2021** polygons/populations for scheduling only. Those dated boundaries are not parcel evidence or a parcel-freshness claim. See `data/official/hcmc_urban_districts_2021.geojson`.

Bulk requests/km² and bulk-vs-point validation differences are **N/A**. Instead, **40 saved shallow ways** were replayed offline using cached official point-response polygons: median absolute width difference **0.00 m**, maximum **0.00 m**, zero network requests. This checks cache/geometry equivalence, not a second bulk source. Evidence: `cadastral-cache-validation.json`.

## Faster fallback and honesty

The previous crawler actually used two cuts per way, not a 5 m scan. The city phase now uses **one centre cut** for breadth (`deep=false`); `--cuts 3` supports 10%, 50%, 90% sampling. Existing results are preserved. Persistent HTTP connections and a **24 h SQLite WAL/RTree cache** under `backend/cache/parcels_points/` reuse an official parcel only when the new query point lies inside its polygon. Exact no-data point replies are cached; locks and transport failures remain retryable.

The original OFFSETS, boundary rays, minimum side distance, gap acceptance, and **gap − 1 m** usable margin remain unchanged. The Official source string remains **Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)**. Retrieval time is recorded; the portal does not publish a survey/update date, so a recent retrieval is not advertised as a recent survey.

A shared cross-process gate limits the API and crawler together to **two portal requests**. Starts are spaced at least 0.5 s in a clean run; after observed locks this run uses **1 s**, increasing up to 2 s after later incidents. A lock pauses new portal work for ten minutes. Locked ways also defer for an hour instead of monopolizing retries. During cooldowns a cache-only full-scan pass makes **zero portal requests**; a missing cache lookup aborts that way and leaves it unknown/retryable.

The normal destination build retains its 5 m path scan. Fresh full-campus way results take precedence over older partial area scans. `deep-campus-plan-validation.json` proves way **610082030** reaches `/api/plan` with **seven valid 5 m samples** out of 15 attempted cuts, Official evidence, and the unchanged source/margin. Cold/warm requests took **2.687 / 0.562 s**. Missing cuts are not fabricated.

## Every confirmed HUTECH site first

The [official Medical Campus site](https://truongy.hutech.edu.vn/) lists a five-campus ecosystem; the [registrar](https://daotao.hutech.edu.vn/default.aspx) corroborates addresses, while the [main footer](https://www.hutech.edu.vn/) confirms four longstanding sites. The [AIDT official contact page](https://aidt.hutech.edu.vn/vi/contact) adds 10/80C Song Hành. All six were cross-checked through the app's **`/api/search` and `/api/place` Goong endpoints**, including the broad searches “HUTECH” and “Đại học Công nghệ TP.HCM”. The confirmed manifest, individual source URLs, addresses, aliases and exact returned coordinates are in **`hutech-campuses.json`**. The AIDT exact-address pin is about 15 m from E1; these remain distinct facilities with shared scan work. Goong's “F Campus” is an alias for the officially named Hitech Park/Khu R site, not a seventh location.

Every drivable OSM way explicitly named/tagged as an alley and intersecting a site's ~2 km circle gets a **full-way 5 m scan**, including unnamed `service=alley` ways. Other unclassified non-main roads keep the later city-breadth policy. A campus full-way scan has **no 60-cut / 300 m cap**. Overlap is deduplicated. Combined target: **3,433 unique alleys / 53,339 planned cuts**. No city-breadth portal work starts until this priority set is complete.

| Campus/facility | Goong coordinates | Alleys within ~2 km | Any cadastral width* | Full 5 m width | live.build time | Full scan finished |
|---|---|---:|---:|---:|---:|---|
| Sai Gon Campus — Trụ sở Điện Biên Phủ | 10.8016170, 106.7144550 | 1,756 | 162 | 3 | 25.8 s | pending |
| Ung Van Khiem Campus | 10.8095728, 106.7149885 | 1,756 | 171 | 3 | 35.5 s | pending |
| Thu Duc Campus — Trung tâm Đào tạo Nhân lực chất lượng cao | 10.8551459, 106.7853645 | 475 | 0 | 0 | 21.5 s | pending |
| Hitech Park Campus — Viện Công nghệ Cao HUTECH | 10.8408888, 106.8089804 | 208 | 0 | 0 | 0.7 s | pending |
| Medical Campus — Trường Y và Khoa học Sức khỏe HUTECH | 10.7994680, 106.7069006 | 2,408 | 126 | 3 | 24.2 s | pending |
| Viện Trí tuệ Nhân tạo và Chuyển đổi số HUTECH | 10.8550176, 106.7853313 | 477 | 0 | 0 | 18.7 s | pending |

*“Any cadastral width” includes the preserved earlier shallow measurements. Full 5 m completion is tracked separately. **16** full-scan attempts are complete, **3** have valid full-scan widths, and **41** cuts have been attempted on completed ways. Very short/degenerate segments can complete without a possible cut and remain no-data. A width is never invented for these. None of the campus circles is fully complete yet; their finish times and elapsed seconds will be written automatically when they finish.

All six `live.build` jobs finished successfully. Bình Thạnh jobs were refreshed after adding atomic area merging so one centre cannot drop another centre's listings/news. The shared demo area now holds **59 listings / 4 news items**; Thủ Đức industrial sites legitimately have zero matched listings. Build status/timing is in `hutech-area-builds.json`, and area files are in `backend/cache/live/areas/`. The regular API and forced campus builds use atomic locked merges for destination caches.

## OSM breadth and freshness

The urban schedule includes former Q1–Q12, Bình Thạnh, Phú Nhuận, Tân Bình, Tân Phú, Gò Vấp, Bình Tân, and all of 2021 Thủ Đức (including former Q2/Q9/Thủ Đức). It round-robins districts in population-density order, prioritizes available OSM alley density within each, and does not sort outward from HUTECH. It has **348 measurement cells** and **2,768 routing keys**.

A .036° core plus .014° halo is fetched once from Overpass, then spatially materialized into the normal per-key graph files. The planned **50 supercells** replace roughly 2,768 overlapping requests before retries. The crawler uses one Overpass request at a time, sequential mirrors and backoff. Each measurement cell must have a cached graph before it is visited. Extra map warming continues independently during portal cooldowns. Whole ways and their external nodes are retained when they cross a routing circle.

The shared demo bbox was refreshed from current Overpass batches too (**4,984 ways / 18,732 nodes**), preserving all preset IDs. Atomic graph replacement now invalidates the API's memory cache. Fresh successful batch timestamps began at **16 October 16:50 UTC** and continue through this run. A 24 h batch freshness window is used. There is no old 1.8 GB warming cap; the current projection is around 2 GB of area files plus shared batches, within available disk.

Current snapshot: **298 ways attempted, 211 with cadastral width**, **11 visited measurement cells / 0 complete**, **1,889 cached OSM area files** totaling **1026.2 MB**, plus **31 shared batches / 147.5 MB**. These counts have timestamps; warming continues.

## Throughput and 13:00 projection

Before the campus steering, the new breadth runner added **61 ways in 3 min 56 s (15.5 ways/min)**, including cold OSM waits, versus the old recent locked-run rate of 5.6/min (the previous report's earlier average was 9.64/min). That is an observed short breadth interval, not a guaranteed all-night rate or a benchmark of the later slower adaptive gate.

The first two full-way campus scans completed **23 attempted cuts**, with 11 valid cuts, before another lock. Their interval used **67 cache-miss lookup attempts and 170 polygon-cache hits**, including in-flight failed ways. The internal `requests` statistic counts cache misses, including calls blocked before HTTP send, and is not an HTTP request counter. Repeated ten-minute locks dominate the deep scan, so there is **no defensible combined city-wide 13:00 forecast yet**. The campus task alone has 53,339 cuts; it can consume the remaining window. City breadth starts only after campus priority completes, as requested.

Conditional arithmetic: finishing the campus priority adds up to **3,208 not-yet-attempted campus ways** to the current count. After that, the previously observed 15.5/min would add about **930 breadth ways per remaining hour** if the portal stays healthy. Neither full campus completion nor “most of HCMC has cadastral widths by 13:00” is promised under the observed locks. Current shared cooldown: **2026-10-17T00:46:11.865036+07:00**. The crawler remains active and resumable, rather than treating locked ways as no-data.

## Tide and backend coverage

The latest official [five-day Phú An attachment](https://kttvnb.vn/attachments/article/29368/HCMC_TVHN_20261016.pdf) was rediscovered from the official hydrology listing and parsed without AI. **Bulletin 289/2026, issued 16 October 09:08 +07**, matches all **11 highs / 12 lows** in the existing schema; the missing `ct` high is omitted. No numerical change was needed. The parser rejects malformed, incomplete, older or future bulletins and preserves the last good JSON on any failure.

FastAPI lifespan launches a non-blocking daemon refresh at startup and every six hours. Status: **current**, last checked **2026-10-17T00:31:28.403756+07:00**, next **2026-10-17T06:31:33.091700+07:00**. A narrowly scoped public-download fallback handles the official host's expired certificate and records `tls_verified=false`; no global TLS setting changed. Run manually: `python3 pipelines/refresh_tide.py`. PDF extraction is declared in `requirements.txt`.

`/api/config.coverage` now exposes the “Dữ liệu” label, cadastral-way/alley counts, deep-width count, visited/complete/target cells, OSM cache count, phase, per-campus progress/builds, last crawl timestamp, and tide issue/refresh times. It contains no credentials. The frontend was left to its owner. Current API config and full-depth plan proofs are saved as `api-coverage-validation.json` and `deep-campus-plan-validation.json`.

## Artifacts and validation

- **`docs/eval/coverage-hcmc-round2.png`** and self-contained `.html`: measured ways with/without data, reference OSM streets, district outlines, all six priority circles, and a density inset. The timestamp and unknown coverage are explicit. Render again for the deck with `nice -n 10 python3 pipelines/render_coverage.py`.
- **41 automated checks** passed across the crawler/cache suites and existing backend suites, including cross-process request concurrency, retryable/null separation, exact polygon containment, mtime reload, atomic writes, cache-only cooldown scans, deep scans beyond 300 m, overlapping campus accounting, full-way evidence precedence, tide parsing/failure retention, and the deadline. The 40-way offline numerical replay is additional validation.
- Validation commands: `python3 pipelines/test_crawl_city.py`; `python3 pipelines/test_crawl_round2.py`; `PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p 'test*.py'`.

## Files changed by this round

Code: `.gitignore`, `requirements.txt`, `backend/app/main.py`, `backend/app/live.py`, `backend/app/osm.py`, `backend/app/parcels.py`; new `backend/app/coverage.py`, `parcel_points.py`, `portal_gate.py`, `tide_refresh.py`; `pipelines/crawl_city.py`, `test_crawl_city.py`; new `pipelines/campus_priority.py`, `city_scope.py`, `osm_city_cache.py`, `refresh_tide.py`, `prebuild_hutech.py`, `crawl_status.py`, `render_coverage.py`, `test_crawl_round2.py`, and `pipelines/fixtures/tide_289_2026_expected.json`.

Data/artifacts: `data/official/hcmc_urban_districts_2021.geojson`, `docs/eval/hutech-campuses.json`, this report, JSON validation/status files and coverage PNG/HTML. Runtime caches include fresh `backend/cache/osm/demo_binhthanh.json`, area/supercell graph files, `parcels_points/` SQLite/backoff state, atomic `live/city_parcels.json` / crawl state, destination parcel/area caches, and tide-refresh status/PDF cache. Existing edits by other agents were preserved. No frontend edit, no commit, and no paid Gemini use.
