# Goong recovery of unmatched source records — 17 October 2026

Implemented locally. I made no commit, no Gemini call, no planning-portal call, and did not restart the live demo server.

## Outcome and live verification

`GET http://127.0.0.1:8787/api/config` returns HTTP 200 and **14,881 ways with source evidence**, up from **14,863**, net **+18**. Its strongest Declared count is now 1,657. This was verified after atomic publication, through the existing mtime reload path. No restart is needed for the new count.

- QĐ 4582: **35 newly associated source entries / 35 ways**. Eighteen ways previously had no source evidence; the other seventeen already had some evidence. All remain **Declared [0.5, 3.5]**; fire-truck inaccessibility can reflect bends, wires or dead ends.
- Q9 gazette: **50 newly associated rows / 48 ways**, including **46 ways newly carrying official metadata**. Historical base widths and planned ROW stay in `official_width_records`, with `affects_clear_width:false`. They add zero ways to Clear Width coverage.
- Coordinate-less listings: **0 new matches**. Of 36 claims, 35 have no explicit alley-number/street chain and the other fails the returned-address gate. The separately retained 116 ambiguous listing texts remain excluded from width evidence.

All 6,550 original unmatched records have an audit result. **6,465 remain unresolved** (fire 5,683; Q9 746; listings 36). **6,428 have never received a successful Goong query response**; this includes missing/ambiguous addresses and absent named OSM targets. Under the updated preflight rules, **629 still have a queryable, unprocessed candidate**, including **22 high-value fire entries** identified by queue/campus priority. A skipped row is not a successful match or a network attempt.

## Calls and stop condition

The key's actual plan, account-wide quota and other live-demo traffic are **unknown**. The original brief allowed <=5 requests/s and required checking the Free allowance first. `docs.goong.io` REST URLs returned 404; [Goong's official FAQ](https://help.goong.io/kb/qa/question/nhung-cau-hoi-thuong-gap-trong-qua-trinh-tich-hop-goong-map-api/) states Free 30,000/month, equivalent to 1,000/day. The initial run conservatively reserved at most 499 requests per rolling 24 hours.

That run used **421 Goong requests: 420 HTTP 200 and one HTTP 429**, all `/v2/geocode`. The last response said `OVER_RATE_LIMIT`: “You have exceeded your rate limit.” **Zero requests followed that refusal.** Minimum request-start spacing was 0.300046 s; at most four starts occurred within a second, within the original <=5/s instruction.

The subsequent user instruction sets an explicit **2,000-request job cap and <=2 requests/s**. The implementation now uses that cap through `GOONG_JOB_MAX_REQUESTS` or `--max-requests` (alias `--max-calls`), enforced cumulatively across process restarts in a rolling 24-hour ledger. Fresh request starts are at least 0.5 s apart. **421/2,000 used; 1,579 nominally unspent. The persisted refusal makes that balance unavailable.** Cache-only replays after the instruction made zero additional Goong requests.

`data/raw/geocode_unmatched/STOP.json` persists HTTP 403/429 and quota/limit messages, even when returned with HTTP 200. It has no automatic expiry, retry, key rotation or reset flag. Raising the budget cannot bypass it. Responses, including refusals and transport errors, are cached by endpoint plus query; the ledger reserves a call before sending. Keys and credential-bearing exception URLs are never logged or cached. A scan found the API key absent from all 426 scanned response/product/report files.

## Matching and priority

Fresh calls now follow this order: QĐ 4582 candidates appearing in the saved `GET /api/evidence/queue?limit=1000` response or within 2 km of a campus in `docs/eval/hutech-campuses.json`; then other entries in descending district population density. Geometry, queue ids, priority reasons and preflight exclusions are in the private `priority.json` audit. The queue snapshot contains the endpoint's maximum 1,000 returned items, not all city ways.

Ambiguous source chains, missing administrative context, missing alley-number/street pairs, and absent eligible same-chain OSM targets are rejected before a fresh request. A fresh entry uses one autocomplete call. Predictions must contain the exact number chain and street and identify HCMC; multiple qualifying predictions stop before detail. Place detail is requested only for a single qualifying prediction missing coordinates. Previously cached geocode responses are replayed without opening new geocode requests.

Queries retain source-date ward/district context; old district names are included for post-2025 administrative changes. The legacy cache also retains district-only variants. Street matching normalizes accents and whitespace but never drops child alley numbers, fuzzes street names, invents a missing street, or assigns unnamed ways by proximity alone. A coordinate must be inside the cached urban HCMC district polygons. The nearest same-chain service/residential alley must be <=40 m away, with >=15 m margin to the second candidate, including a second candidate beyond 40 m. Multiple accepted Goong-way correspondences remain unresolved.

Scope is the existing urban cached graphs, not the whole enlarged post-2025 municipality. Source ward headings/centres may themselves contain parsing or administrative errors. Geocoding does not repair those source records or validate their width claims.

## Validation

A fixed seed (4582) selected **100 previously name-matched fire entries before seeing Goong results**. One source-date geocode query per entry was used under the original run. **54 passed all gates; all 54 selected a way in the original reference way-id set; zero accepted snaps differed.** Precision proxy among accepted snaps is **100% (54/54)**, while recovery across the complete sample is **54% (54/100)**. The other 46 were rejected: 37 returned-name failures, eight insufficient margins, one distance over 40 m. The reference associations can themselves be wrong; this is not independent accuracy or validation of Q9 rows, listings, or the newly configured autocomplete path. Updated autocomplete behavior is covered by offline tests and was not exercised against the blocked sponsor key.

All newly accepted records were compared to current cached cadastral cuts: **zero overlapping ways** for fire/listings and Q9. The available snapshot has 244 reference ways / 433 cuts, including 213 city-reference ways. Width agreement or error cannot be estimated; no accuracy statistic was invented. Raw parcel gap and usable Clear Width retain their existing distinct meanings.

**61 targeted tests pass**, including persistent caps, rate spacing, cache-only behavior, HTTP/body refusals, exact names, snap margins, autocomplete/detail conditions, priority, provenance, hull/REVIEW preservation, Measured/Official precedence, metadata exclusion and atomic mtime reload. Existing dependency/deprecation warnings remain. Python compilation and `git diff --check` pass.

## Files changed by this work

Code and tests:
- `pipelines/geocode_unmatched.py`
- `pipelines/test_geocode_unmatched.py`
- `pipelines/listings_city.py` — preserve recoveries on future index builds
- `pipelines/official_bulk.py` — preserve metadata recoveries; isolated cadastral snapshot output
- `backend/app/declared_index.py` — expose listing match provenance
- `backend/app/evidence.py` — expose fire match provenance without changing tiers

Published data and reports:
- `data/processed/geocode_unmatched.json` — 85 accepted records, source rows and full snap provenance
- `data/official/fire_access_4582.json` — durable fire associations, so an already-running older listing builder cannot erase coverage
- `backend/cache/live/declared_index.json`
- `backend/cache/live/official_widths.json`
- `docs/eval/geocode-unmatched.json`
- `docs/eval/geocode-unmatched.md`

Private/ignored audit: `data/raw/geocode_unmatched/` contains every response, `calls.sqlite`, `STOP.json`, initial/final coverage, fixed validation sample, per-item audit, source entries, priority/queue snapshots and quota documentation. The pre-existing official-bulk cadastral snapshot was also refreshed during initial comparison; subsequent snapshots are isolated under this job's directory. Test/run logs are under `tmp/geocode-unmatched-*`.

## Reproduce without touching the blocked key

```sh
python3 pipelines/geocode_unmatched.py prepare
GOONG_JOB_MAX_REQUESTS=2000 python3 pipelines/geocode_unmatched.py run
PYTHONPATH=backend:. python3 -m pytest pipelines/test_geocode_unmatched.py pipelines/test_evidence_city.py backend/tests/test_official_widths.py pipelines/test_official_bulk.py backend/tests/test_engine_width.py -q
```

`run` defaults to cache-only. `--network --max-requests 2000` enables network only when there is no persisted refusal; it is intentionally blocked now. No restart command is required for the current live coverage count. If the owner later needs to load changed Python code, the documented backend command is `cd /Users/khoivo/Developer/mlai-car-access/backend && uvicorn app.main:app --port 8787`; this task did not run it or stop the occupied port.
