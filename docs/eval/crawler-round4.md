# Crawler round 4 — ranked, conservative overnight schedule

Verified **2026-10-17T07:46:53.070002+07:00**. No commit, no paid Gemini, no frontend edits. No IP rotation, proxies, extra machines, endpoint swaps or header changes. The live API was not restarted.

## One-shot schedule

- Detached waiting process **PID 69173**, PPID 1, own process group, **nice 10**, launched with `nohup` and `start_new_session=True`.
- **Start: 2026-10-17 21:00 Asia/Ho_Chi_Minh. Stop/pause: 2026-10-18 07:00 Asia/Ho_Chi_Minh.**
- Current status: **waiting**. It has no active crawler lease, no parcel client, and no network loop before the start. The same PID execs the real crawler at 21:00.
- Stop or cancel before/after start: **`kill -TERM 69173`**.
- Schedule/status: `backend/cache/live/crawl_night_schedule.json`; detached stdout: `backend/cache/live/crawl_night.out`; actual crawler log after start: `backend/cache/live/crawl_city.log`.
- At 07:00 the deadline saves accepted results and retry state, marks `paused_window_end`, releases its lease and exits. There is **no recurrence**, no daytime work and no second-night run installed.
- Resume this same authorized window after cancellation: `nohup nice -n 10 python3 -u pipelines/schedule_crawl.py --start-at 2026-10-17T21:00:00+07:00 --stop-at 2026-10-18T07:00:00+07:00 >> backend/cache/live/crawl_night.out 2>&1 < /dev/null &`. After 07:00 that command does not launch a crawler.
- Existing city results preserved: **305 ways / 213 with width samples**. Existing polygons and 500 m campus membership are reused.

## Fixture fixed; engine unchanged

`pipelines/test_crawl_city.py::CityCacheTests::test_warm_path_keeps_destination_deep_scan_and_preserves_existing_deep` now supplies a real-shaped `edges` list with `way_id/u/v`. The fixture represents a single ordinary alley edge, so the current junction exclusion runs normally. **`backend/app/parcels.py` was not edited in this round.** The test passes.

## Queue order and single-cut selection

`GET /api/evidence/queue?limit=1000` is the first priority source. The scheduler keeps that snapshot order exactly, skips its own recently completed selections across resumes, then offers HUTECH 500 m inner ways, then other drivable non-main ways in the cached inventory. Queue snapshots refresh every 30 minutes; at 21:00 a fresh snapshot is fetched, so demand gathered during the hackathon can change the order. If the local HTTP API is unavailable, the exact same `evidence_queue.queue` implementation runs in process; a failure of both pauses work instead of querying an unranked source.

**First 20 planned ids equal the API's first 20: `True`. All 20 cuts are ready; 16 use a cached narrow footprint station and 4 use a straight interior section because no located width hint exists.** The dry plan made **zero portal requests**. Evidence: `crawler-round4-plan.json`; API snapshot: `crawler-round4-queue.json`.

The selection prefers the narrowest suspected cached footprint/parcel station that passes the engine’s corner guard and the graph’s 5 m junction exclusion. The selected point and straddled vehicle thresholds are recorded. No even-spacing scan is performed in this scarce-request mode, including in the 500 m campus fallback. A single cut can require more than one parcel-side POST; every POST, including transport retries, passes the same conservative gate. Raw footprint locations are only query hints and never become Official widths.

Successful results use the current `parcels.measure(..., fractions=(selected_fraction,))` geometry and schema. Existing cuts are retained, new partial data has `coverage.complete=false` and `deep=false`, and failed/no-frontage results retain an unresolved coverage record. A single cut never certifies whole-way clearance.

| Queue rank | Way id | Score | Selected distance along way | Selection |
|---:|---:|---:|---:|---|
| 1 | 610102928 | 28.202638 | 5.0 m | cached footprint bottleneck |
| 2 | 1114843254 | 28.202638 | 30.231 m | straight interior; no located hint |
| 3 | 1330786039 | 28.202638 | 5.0 m | cached footprint bottleneck |
| 4 | 517513511 | 24.0 | 25.0 m | cached footprint bottleneck |
| 5 | 517513552 | 24.0 | 55.0 m | cached footprint bottleneck |
| 6 | 517523880 | 24.0 | 25.0 m | cached footprint bottleneck |
| 7 | 517523885 | 24.0 | 105.0 m | cached footprint bottleneck |
| 8 | 517523902 | 24.0 | 25.0 m | cached footprint bottleneck |
| 9 | 610980178 | 24.0 | 45.0 m | cached footprint bottleneck |
| 10 | 193085738 | 23.615674 | 305.0 m | cached footprint bottleneck |
| 11 | 1082471455 | 18.0 | 7.893 m | straight interior; no located hint |
| 12 | 35114992 | 18.0 | 445.0 m | cached footprint bottleneck |
| 13 | 502338681 | 12.509775 | 55.0 m | cached footprint bottleneck |
| 14 | 511936345 | 8.0 | 85.0 m | cached footprint bottleneck |
| 15 | 604837651 | 7.871891 | 15.0 m | cached footprint bottleneck |
| 16 | 609967226 | 7.871891 | 75.0 m | cached footprint bottleneck |
| 17 | 668284520 | 6.254888 | 77.651 m | straight interior; no located hint |
| 18 | 668284524 | 6.254888 | 15.0 m | cached footprint bottleneck |
| 19 | 668284534 | 6.254888 | 64.682 m | straight interior; no located hint |
| 20 | 511936347 | 6.0 | 15.0 m | cached footprint bottleneck |

## Backoff and learning

- Crawler lock recovery starts at **2 hours**, then **4 hours**, then **8 hours maximum**, persisted across pauses/restarts. Concurrent copies of the same incident are clustered; a new real API lock is also adopted by the crawler’s stricter recovery policy.
- Starts are separated by **at least 180 seconds**. The gate uses the larger of that floor, twice the configured spacing seen in historical lock responses, and persisted learned spacing. A new lock doubles spacing again. It never automatically speeds back up.
- History-derived initial spacing: **180 s**; largest failed configured spacing observed: **30 s**. Long ban-recovery gaps are not mistaken for a quota measurement. **A safe quota has not been established**; this is conservative adaptive pacing, not a claim that three minutes is proven safe.
- `spacing_learned`, each actual `request_start`, `response`, and `lock_incident` are logged in `backend/cache/parcels_points/portal_events.jsonl`; the crawler log also records chosen spacing and recovery times.
- Portal access is direct using the existing endpoint and unchanged User-Agent/Referer. The ranked parcel client sets `trust_env=False`; the scheduled process also removes proxy and paid-provider environment settings. This pipeline makes no AI calls.

## API isolation and shared locking

The shared two-slot request locks and cross-process rate timestamp remain. Crawler waiting releases the rate lock and HTTP slots between attempts, so a three-minute wait cannot hold up an API request.

Crawler-only cooldowns persist in `backend/cache/parcels_points/crawler_backoff.json`; API backoff remains in `cooldown.json`. The same shared `crawler_lease.json` retains PID/deadline and records `crawler_interval_s` separately. Its legacy `interval_s` stays 0.5 s for compatibility with the already-running API. Old crawler-owned cooldown metadata migrates at the scheduled start, preserving its remaining recovery for the crawler. API-owned cooldowns remain intact. This prevents both current and already-loaded API implementations from inheriting crawler hours-long pauses, without restarting the demo server. A genuine server-side ban can still affect a live request; local state isolation cannot remove it.

Schedule validation found an empty live lease and **0 crawler request starts since scheduling**. The existing API returned HTTP **200** in **0.0435 s**. Proof: `crawler-round4-schedule-validation.json`.

## Validation and files

- **58 unique crawler/gate checks passed**: 10 crawler, 12 round-3, 20 round-2 and 16 round-4 checks. These include the repaired fixture, actual runner order for 20 ways, bottleneck selection, unchanged corner/junction exclusion, 2/4/8 h recovery, history learning, active/legacy API isolation, cross-process request limits, API access during crawler wait, no early/late dispatch, and one-shot exec with a fixed deadline.
- Python compilation and whitespace checks pass. No portal probe was sent to test the new spacing, and no daytime crawler was started.
- Added: `pipelines/crawl_ranked.py`, `pipelines/schedule_crawl.py`, `pipelines/test_crawl_round4.py`.
- Modified: `backend/app/portal_gate.py`, `backend/app/parcel_points.py`, `pipelines/crawl_city.py`, `pipelines/crawl_status.py`, `pipelines/test_crawl_city.py`, `pipelines/test_crawl_round3.py`, and the queue-integration section of `docs/evidence-engine.md`. Other agents’ engine edits were preserved.
- Artifacts: this report, `crawler-round4-plan.json`, `crawler-round4-queue.json`, `crawler-round4-operation.json`, and `crawler-round4-schedule-validation.json`.
