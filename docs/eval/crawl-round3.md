# HCMC crawl round 3 — breadth rebalance

Observed **2026-10-17T01:11:10.492858+07:00**. Measured **21.05 minutes**, beginning 2026-10-17T00:50:07.400688+07:00. Scope and scheduling are implemented and running; full campus completion is not claimed. **No commit, no frontend edits, no paid Gemini.**

## Operating handoff

- Crawler **PID 93693**, PPID 1, **nice 10**, deadline **17 October 2026 11:30 Asia/Ho_Chi_Minh**. API PID **88666**.
- Log: `backend/cache/live/crawl_city.log`; stdout: `backend/cache/live/crawl_city.out`.
- Stop: `kill -TERM 93693`. Accepted widths, partial deep progress, retry state and shared polygon/OSM caches persist atomically.
- Resume: `nohup nice -n 10 python3 -u pipelines/crawl_city.py --portal-interval 6 --stop-at 2026-10-17T11:30:00+07:00 >> backend/cache/live/crawl_city.out 2>&1 < /dev/null &`.
- Current adaptive minimum spacing: **13.5 s**. Recovery pause through **2026-10-17T01:26:25.911804+07:00**. Repeated crawler lock incidents increase quiet periods from 10 to 20, 40, then at most 60 minutes, and spacing by 1.5× up to 30 s. API-origin backoff stays separate.
- Read current metrics: `python3 pipelines/measure_crawl.py`; general cache sizes/status: `python3 pipelines/crawl_status.py`. The measurement script sums the monitored PIDs across graceful restarts; actual HTTP counts come from timing events, not the old lookup-miss counter.

## Revised scope and campus counts

**495 unique inner alleys / 8,528 planned 5 m cuts**, down from 3,433 alleys / 53,339 cuts at full depth. **2,938 unique ring alleys** remain after removing every inner-circle way. Each inner way intersects a 500 m campus circle; the whole intersecting OSM way is scanned to preserve evidence continuity. Ring alleys out to 2 km use one centre cut, with 10% / 90% cuts only when entirely answerable from the polygon cache. All six authoritative sites, exact Goong coordinates and source URLs remain in `hutech-campuses.json`.

| Facility | Inner alleys | Inner planned cuts | Inner full scans / with width | Individual ring alleys | Ring results / with width |
|---|---:|---:|---:|---:|---:|
| Sai Gon — 475A Điện Biên Phủ | 169 | 2,789 | 2 / 2 | 1,587 | 112 / 80 |
| Ung Văn Khiêm — 31/36 | 151 | 2,727 | 1 / 1 | 1,605 | 215 / 169 |
| Thu Duc — E1 | 19 | 454 | 0 / 0 | 456 | 3 / 0 |
| Hitech Park — Khu R | 0 | 0 | 0 / 0 | 208 | 1 / 0 |
| Medical — 276–282 Điện Biên Phủ | 189 | 3,170 | 0 / 0 | 2,219 | 149 / 126 |
| AIDT — 10/80C Song Hành | 19 | 454 | 0 / 0 | 458 | 3 / 0 |

Per-site circles overlap; rows must not be added. A ring way that falls in another campus inner circle shares that deeper scan. Khu R has zero drivable alleys named/tagged as alleys within 500 m in the current OSM extract; this is not a claim that every access road was surveyed. Other non-main drivable roads remain city-breadth candidates. None of the non-empty inner sets is complete yet. All six earlier `live.build` jobs remain completed and their area/listing/news caches are preserved.

## Fair scheduling and geometry

City turns are spread through the cycle: **8 city, 4 ring, 1 inner two-cut turn**. A long inner alley resumes in two-cut slices, with partial results stored separately; full-depth evidence appears only after every planned 5 m cut was attempted. Cache-only passes continue during cooldowns. The original tail clamp, parcel boundaries, source text and **gap − 1 m** margin remain unchanged. A missing first-side parcel now skips the unnecessary opposite query at that offset, while retaining later offsets. Forty offline centre-cut replays matched existing widths exactly: **median / max absolute difference 0.00 / 0.00 m**, no HTTP calls (`round3-cache-validation.json`).

## Lock findings and measured throughput

Instrumentation found a round-2 pacing bug: the append-mode shared rate file was read from EOF. Requests could start only 0.148 s and 0.630 s apart despite a configured interval. The fix seeks to the beginning under the cross-process rate lock; tests verify actual spacing. The pre-fix burst sent three requests and received two HTTP 200 land-lock messages, clustered as one incident. Those are reported separately from the corrected window.

During the corrected **21.05-minute window**, there were **3 actual HTTP starts**, **2 lock responses / 2 incidents**, and **0 transport errors**. A successful response was followed by a lock after a verified **6.0001 s** start gap. After another ten quiet minutes, the first retry configured at 9 s was also locked. **No safe requests-per-minute threshold was established.** These sparse HTTP 200 land-lock responses do not establish whether the cause is a rolling quota, a longer server ban, or a parcel-specific restriction. No burst was sent deliberately to provoke a threshold.

Effective newly completed-way rate: **0.00 ways/min**, including recovery and restart pauses; **0 new complete way results**. Existing coverage is **299 cached way results / 211 with width**. Inner progress is **3 completed full scans / 41 cuts**, plus **3 partial ways / 12 completed partial cuts**. The partial work remains retryable and is not counted as completed widths.

Polygon-hit ratio for eligible network-capable lookup attempts: **70.59%** (12 polygon hits, 5 misses, no exact-empty hits). Cache-only probes and a local test-lease outage are excluded from this ratio. Using actual HTTP starts instead of lookup misses gives **80.0%**; neither ratio substitutes for completed-way throughput. Raw counters, exclusions and definitions are preserved in `crawl-round3.json` / `round3-operation.json`.

A deadline regression test initially used the live lease directory, which caused local gate rejections without sending HTTP. It was corrected to use temporary gate/SQLite paths, competing live leases can no longer be replaced, and the legitimate server cooldown was restored. The wall-clock pause stays in the measured throughput. Local lease rejections were removed from server-lock counts and fake way deferrals were repaired; the actual HTTP event log is independent. No cache evidence was discarded.

## Projection to 11:30

| Category | Current completed | Target | Observed new ways/min | Linear completed count at 11:30 |
|---|---:|---:|---:|---:|
| Campus inner — full depth | 3 | 495 | 0.00 | 3 |
| Campus ring — breadth | 136 | 2938 | 0.00 | 136 |
| Urban city outside campus sets — breadth | 73 | city inventory | 0.00 | 73 |

At the measured zero completed-way rate, the literal projection is **299 total cached results**, with the category counts above. This is a pessimistic zero-rate extrapolation, not a calibrated whole-night prediction. **No defensible positive campus/ring/city completion forecast is available from this lock-dominated window.** There are already 90 shallow-or-deep inner results (83 with width), including the three full scans; the 87 remaining shallow results are not added to the full-depth column. City breadth includes non-main drivable roads beyond explicitly tagged alleys. No city/campus completion promise is made under the current server responses.

## OSM breadth and API hygiene

**2,768 / 2,768 scheduled routing keys are cached**, plus 1 extra key. The city schedule still covers 17 former urban districts and is ordered by population / alley density. Every visited measurement cell has a graph. Shared fresh Overpass batches are materialized locally, with one Overpass fetch at a time and backoff. Exact target matching is saved in `round3-osm-target-coverage.json`.

The crawler lease contains PID and deadline. API requests ignore crawler-origin cooldown files when the lease is released, dead or expired. TERM, deadline and natural completion release the lease; even an orphaned cooldown file cannot impose a long API pause after 11:30. This clears local inherited backoff; it cannot cancel a server-side ban. The 11:30 cutoff leaves 30 minutes before noon for server recovery.

Validation against the actual lease, with time advanced past its deadline, returned **cooldown=0 / API interval=0.5 s**. The isolated deadline test preserved the live lease. Cached `/api/plan` returned HTTP 200 in **2.565 / 0.595 s cold / warm**. Startup and six-hour tide refresh and `/api/config.coverage` remain enabled. No additional AI builds were required.

## Artifacts, checks and changes

- `docs/eval/coverage-hcmc-round3.png` and `.html`: refreshed coverage, 500 m deep circles, 2 km breadth rings, observed timestamp and explicit unknown areas. Re-render with `nice -n 10 python3 pipelines/render_coverage.py --output docs/eval/coverage-hcmc-round3`.
- `crawl-round3.json`, `round3-window-samples.jsonl`, `round3-operation.json`, `round3-api-gate-validation.json`, `round3-api-plan-validation.json`, `round3-cache-validation.json`, and `round3-osm-target-coverage.json` preserve evidence.
- **53 automated checks passed** (12 round-3, 20 round-2, 10 crawler, 11 backend), plus the 40-way offline replay. Tests cover real pacing, competing-process limits, expired/dead/released leases, test isolation, escalating quiet periods, fair scheduling, chunk resume/tail geometry, no extra HTTP for optional cuts, atomic caches and preserved evidence.
- Modified: `backend/app/portal_gate.py`, `backend/app/parcel_points.py`, `backend/app/parcels.py`; `pipelines/campus_priority.py`, `pipelines/crawl_city.py`, `pipelines/crawl_status.py`, `pipelines/render_coverage.py`, `pipelines/test_crawl_city.py`. Added `pipelines/crawl_scheduler.py`, `pipelines/measure_crawl.py`, `pipelines/test_crawl_round3.py`, and the round-3 report/artifacts. Existing edits by other agents were preserved.
- **No commit. No frontend edits. No paid Gemini.**
