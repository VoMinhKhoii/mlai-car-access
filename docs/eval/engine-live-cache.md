# Live parcel-cache follow-up — 17 October 2026

Baseline `e1444cb` on main. No commits or pushes. **:8787 has not been restarted or modified.** All verification ran in-process with FastAPI TestClient and isolated store/cache/flags; socket connections were denied. No Gemini, Goong, Overpass or planning-portal calls.

The cause is **(b), the server-owned area loader**, rather than cut rejection. `backend/cache/live/areas/10.788_106.696.json` is an older completed area build with `status.finished_at=2026-10-17T09:33:15+07:00`. It lacks the `schema_version`, revision and expiry fields required by `live._load_area`. `main.evidence_for_way` and `main.make_plan` both call `live.area_status`; the rejected record yields no overlay. Neither the door nor Cây Điệp is in `city_parcels.json`, so only the OSM class prior remains and the estimate becomes approximately 5 m, with no samples.

The prior engine stress harness explicitly replayed old area records as trusted overlays. That tested the estimate/fusion changes but missed the production cache-loader compatibility boundary. The new regression exercises the HTTP path itself.

## Minimal fix

`backend/app/live.py`: 23 added lines implement a read-only parcel-only compatibility projection. It accepts only an unversioned server-cache record whose top-level and build-status keys match the requested key, whose build is done without an error, and whose completion timestamp is timezone-aware and not in the future. It derives expiry from that original timestamp plus the existing 12-hour TTL. This record expires at **21:33:15 ICT**, rather than receiving a fresh lifetime when read.

The projected area is partial. It carries parcel cuts; legacy listings, photos and news are excluded. Nothing is written back to the cache. Existing versioned records, photo reviews, browser evidence rejection, stale-record exclusion, geometry filtering and strict clearance rules keep their existing behavior. Automatic cadastral geometry remains **Inferred**, with source “Cadastral parcel-gap estimate”; this fix does not relabel it Official.

## Actual cached HTTP proof

A separate runtime cloned the actual 1 MB OSM cell, original area JSON, city-parcel snapshot, flags and store before importing the app. The HTTP routes, area loader, graph loader, evidence overlay and cut validator run without patches. Providers are unavailable and socket calls fail immediately. No HTTP server was started.

- Door way 35115025 has **2 nodes**. **All 5 cuts accepted, 0 rejected**; samples **5.56–5.65 m**, five independent bottleneck supporters. Junction/misalignment filtering is not dropping these samples.
- `POST /api/evidence/way/35115025`: cadastral sample **5.56 m**, sampled band **5.26–5.86 m**; strict lower bound **0**, no decisive clearance.
- `POST /api/plan` at the requested `2026-10-17T12:00+07:00`, class-m, park 120 min: **“Park on Đường Trần Doãn Khanh, 60 m walk — low confidence”**. Basis: **“inferred ≈3.58 m (Đường Cây Điệp; OSM 35113132) · at the door ≈5.56 m (Đường Trần Doãn Khanh) · 6/10 segments sampled (60% of route length with samples) …”**. `verified=false`; the unchanged headline is expected because confidence and strict checks did not change.
- Area status is **partial**, collected **09:33:15**, expires **21:33:15**. Legacy photos/listings are absent.

[Actual evidence JSON](engine-live-cache/actual-evidence-after.json) · [Actual plan JSON](engine-live-cache/actual-plan-after.json) · [Network-denied check](engine-live-cache/actual-cache-check.txt).

## Regression and backend suite

`backend/tests/test_engine_live_cache.py` sends requests through FastAPI to the real `live.area_status → _load_area → plan.area → width_ranges → cut validation` path. Its self-contained fixture writes cached OSM geometry and a legacy area record under temporary directories. It asserts endpoint recovery, the plan's separate door/route samples, retained Inferred tier, strict zero floor, unverified result, no unreviewed legacy photos/listings, original expiry and unchanged cache bytes. Seven rejection cases cover expired, absent/naive/future timestamp, unfinished build, wrong key and unknown schema version.

Before the fix, the HTTP recovery regression fails because no parcel bound exists. After: **18 passed** across the eight new cases and the existing evidence-isolation suite. [Before log](engine-live-cache/regression-before.txt) · [After log](engine-live-cache/regression-after.txt).

**Full backend suite: 338 passed, 77 skipped, 210 subtests passed**, 150.91 seconds. [Full log](engine-live-cache/backend-tests.txt). Parked suites retain the repository’s default skips. Provider-specific tests use their normal mocked branches; all socket connections are denied. A forced cached-only-mode suite attempt was stopped because that mode bypassed mocked provider branches; it is not the final test configuration.

The actual OSM/area cache files remain byte-identical to the cloned inputs. The running crawler later updated an unrelated city-parcel row (517513511); neither target way entered the city snapshot. [Snapshot hashes](engine-live-cache/actual-inputs.json) record the cloned inputs separately from the later source snapshot.

## Restart handoff

**The full suite passed. Ready for the owner to commit and restart :8787 now. Agent B has not restarted it.** The running process has the old loader until it reloads. Then repeat the evidence and plan requests above; expect Inferred cadastral evidence at 5.56 m and 6/10 sampled segments. Do not expect an Official tier or a verified verdict. After 21:33:15 ICT, this legacy record correctly becomes stale and needs an authorized fresh build.

Changed: `backend/app/live.py`, new `backend/tests/test_engine_live_cache.py`, D55 and these follow-up eval artifacts. The plan, evidence-fusion, width-sample and parcel-computation code did not need changes.
