# City listing Evidence and measurement queue — 17 October 2026

Implemented and running locally, with **no commit**, **zero planning-portal requests**, **zero paid calls**, and **three free Gemini attempts / zero accepted LLM extractions**. Chợ Tốt completed a full polite pass without throttling. Alonhadat returned 429 and was stopped. The new index adds **773 previously unsourced ways**; it does not establish reliable Clear Width city-wide.

## Listings: coverage, acquisition and validation

- **22/22 Chợ Tốt source districts, sale + rent: 44/44 partitions.** Natural short/empty/repeated-page termination occurred before the 100-page safety cap; the deepest partition reached page index 29. **357 sequential network pages / 16,796 listing rows**, 1.5 s minimum request-start spacing, no Chợ Tốt 403/429/5xx. No detail/phone endpoint, geocoder or new Overpass request.
- **16,837 unique source/ad ids** across fresh pages and retained caches; **16,828 deduplicated listing texts**: 16,791 Chợ Tốt, 37 retained Alonhadat. These are different denominators from the 16,796 fresh page rows. Immutable sanitized revisions remain in SQLite for future refreshes.
- **12,138/16,828 (72.13%)** have an accepted deterministic own-alley width/access claim after excluding ambiguity. **791 exact-chain + 656 parent-chain claims** reach **1,080 OSM ways**. Parent matches propagate car lower bounds only. **116 ambiguous texts** remain REVIEW/excluded; 96 matched parent numeric/no-car claims do not propagate, and 36 claims without coordinates fail city-wide name uniqueness.
- `backend/cache/live/declared_index.json`: **690,648 bytes**. Per way: all claim URLs/dates, number of listings, estimated independent groups, agreement, first/last posting and conservative hull. Shared seller/address/content joins duplicates. These are estimated independence groups, not verified different properties or people.
- Alonhadat made two network requests before **HTTP 429**, then persisted a host cooldown; later cached refresh cycles issued no retry in cooldown. Its 37 retained listings produced **zero accepted way matches** under the strict chain/coordinate-ambiguity gate. No unsupported expansion, CAPTCHA/proxy bypass or repeated blocked scraping.

Cadastral validation is a **small convenience overlap**, not a city-wide or held-out accuracy estimate. Compare to raw `gap_m`, before the 1 m encroachment assumption; no fresh cadastral queries. Four bands: xe máy <2 m, ba gác 2–3 m, xe hơi 3–5 m, ô tô tránh ≥5 m.

| Declared label | Parcel gap xe máy | ba gác | xe hơi | ô tô tránh |
|---|---:|---:|---:|---:|
| xe hơi | 1 | 1 | 6 | 3 |

- **11 claims / 9 ways** overlap cadastral cuts. Exact band agreement **54.55%**; Declared-bound versus Official usable-width interval overlap **72.73%**. A car-access claim is a lower bound, so a wider parcel-gap band need not contradict it. Conversely, legal parcel space is not obstacle-free Clear Width.
- Exact-chain-only overlap: **6 claims / 6 ways**; band agreement **50.0%**, interval overlap **66.67%**. Parent cases are identified separately in machine-readable rows.
- Numeric widths: only **4** paired claims; signed mean listing-minus-gap error **-0.062 m**, MAE **2.737 m**. Too few and too inaccurate for a strong precision claim. Numeric widths remain upper bounds at Declared tier. Measured/Official Evidence excludes the new listing bound entirely, including compatible overlaps.

## Other sources

| Source | Cached-city coverage | Cadastral validation | Decision |
|---|---:|---|---|
| OSM `width` | 100 tagged non-main ways, 89 existing numeric bounds | 0 overlapping ways | Retain existing Observed semantics; do not add a new precision rule |
| OSM `est_width` | 0 | 0 | No additional coverage |
| OSM `maxwidth` | 6 existing bounds | 0 overlapping ways | Retain existing Observed upper bounds |
| OSM `lanes` | 2,443 tagged non-main ways | No supported Clear Width conversion | Do not turn lanes into new width Evidence |
| QĐ 4582 fire access | 1,024/6,742 parsed entries → 1,353 current-cache ways | One cadastral overlap; existing D32 validation already rejects width-only interpretation | Retain Declared semantics; one supplemental way match |
| Mapillary | 0 | Not run | Skipped: no configured account client token |

**Every parsed fire entry was attempted and accounted for. 5,718 remain unmatched**: 4,948 have no named OSM match; 770 fail the ward-distance gate. These are unresolved source/OSM gaps, not silently discarded entries or successful matches. The old file references 1,354 ways; the fresh cache audit finds 1,353, including one new id and two old ids not recovered by this snapshot/gate. The existing official source file is untouched. Full per-item reasons: `data/raw/listings_city/fire_audit.json`. Matching every listed alley is not possible from the available named OSM cache without fabricating associations.

Fire-truck no-access can reflect bends, low wires and dead ends, so it remains **Declared [0.5, 3.5]**, never Official width. [Mapillary's own instructions](https://github.com/mapillary/mapillary-js#installation-and-usage) require an account and registered application for a client token; no account was created and no image-derived width was invented. News is not Width Evidence. The failed footprint experiment remains disabled by default.

## Coverage snapshot

**14,862/125,867 (11.81%) non-main ways have source Evidence**; **111,005** remain without a source. Generic OSM road-class/lanes priors do not count. The cohort includes prohibited/non-drivable ways so motorcar=no Evidence is not hidden: **109,952** are currently drivable; **41,877** are named/tagged alleys. These are overlapping subsets.

| Strongest source tier | All non-main ways | Named/tagged alleys |
|---|---:|---:|
| Measured | 0 | 0 |
| Official | 247 | 244 |
| Observed | 12,974 | 10,819 |
| Declared | 1,639 | 1,630 |
| Inferred | 2 | 2 |

Source-tier counts are mutually exclusive in this table. The API also returns non-exclusive per-tier counts. The before/after comparison keeps all older live listing/fire/OSM Evidence: **14,089 → 14,862**, net **+773**. New-index ways can overlap existing sources, so 1,080 index ways is not the net coverage gain.

All cached routing cells were read, **2,769 routing files at the final snapshot** (the requested baseline was 2,768; caches grew concurrently). Scope is their union in urban HCMC, **not every administrative part of HCMC**. The render uses actual street geometry and strongest source tier, not a width-class guess: [coverage-evidence.png](coverage-evidence.png), 3840×2160. The map explicitly marks unknowns and its scope. `/api/config.coverage` adds `evidence_*` fields for this scope; older unprefixed fields retain their earlier, smaller footprint/crawler scopes.

## Engine and API handoff

- New `GET /api/evidence/queue`: persistent way-use counts × threshold uncertainty × lack of strong Evidence, with a REVIEW multiplier. Optional bbox/min-score, stable ties, limit 1–1,000. Thresholds: **1.95 / 2.18 / 2.31 m**. Full formula and consumer example: [evidence-engine.md](../evidence-engine.md).
- Successful HTTP `/api/plan` responses count actual door/stops and route-overlapping way ids, once per request. A visible map layer alone is not demand; junction crossings do not count. SQLite stores only way/count/last-seen. Direct internal and streamed-agent plan calls are not counted by the HTTP hook; the agent owner can explicitly call `record_way_ids` if desired.
- Measured/Official widths are protected; disagreements widen and retain REVIEW; lower OSM priors cannot shrink the index hull. Atomic mtime/size reload happens before the **existing** plan cache-version lookup, through a small EvidenceStore hook. No `plan.py`, `vehicles.py`, `parcels.py`, agent/MCP/frontend or crawler changes by this task.
- Detached refresh engine **PID 20860**, last success **2026-10-16T18:41:06+00:00**, next run **2026-10-17T06:41:06+00:00** (12-hour cadence, **zero LLM budget**). Status: `backend/cache/live/evidence_engine_status.json`; log: `data/raw/listings_city/engine.log`. Source pages/checkpoints, immutable listing revisions, LLM results and host cooldowns survive restarts. This is a local process, not a launch-at-login service.
- **The existing shared server on :8787 still serves its previous module**: the new queue path currently falls through to SPA HTML. Its owner must perform the normal backend reload to activate the new include. It was intentionally not restarted during parallel agent work. The new app/router was verified independently through real ASGI requests. The cadastral crawler process/files/lease were not touched; queue consumption is documented, not wired into it.

## Validation and runtime

**25 automated checks passed** (`pipelines/test_evidence_city.py` plus existing footprint safety tests), including stronger-tier precedence, hull/REVIEW preservation, atomic replacement/deletion/last-good reload, existing plan-cache invalidation, flags, persistent demand, route crossings, HTTP response hooks, host cooldowns, immutable revisions, paid-key alias exclusion, result caching and the 1,500 lifetime cap. Existing dependency/deprecation warnings are unchanged. `git diff --check` and Python compilation passed.

Five real cached-graph `/api/plan` requests all returned HTTP 200, with **all external HTTP blocked**. Three listing-only ways expose Declared bounds; two cadastral overlaps retain identical Official widths with listings switched off. Config and queue returned HTTP 200 and tier totals partitioned correctly. The response hook logged **22 distinct touched ways** in a temporary database, leaving production demand unpolluted. Results: [evidence-verification.json](evidence-verification.json).

Network fetch: **539 s**. Full post-pagination build: **32.46 s**; latest cached publication: **9.29 s**. First fetch to latest published product: roughly **13 min 31 s**, including implementation and verification pauses, not a repeatable network benchmark. The first inventory pass read ~1.3 GB of existing OSM caches; subsequent unchanged inventories reuse their product. Free Gemini: **3 attempted, 0 accepted, all hash-cached**; final/recurring builds **0 new calls**; **0 paid calls, 0 portal calls**.

## Files changed by this task

New implementation: `backend/app/declared_index.py`, `backend/app/evidence_queue.py`, `backend/app/evidence_routes.py`; `pipelines/listings_city.py`, `pipelines/render_evidence_city.py`, `pipelines/verify_evidence_city.py`, `pipelines/test_evidence_city.py`.

Small existing-file hooks only: `backend/app/evidence.py` (load/refresh/protect the index), `backend/app/main.py` (add module import and one router include). Both files already had unrelated edits, which were preserved. `live.py` required no edit because the existing EvidenceStore refresh path already runs before width-cache lookup.

Products and docs: `backend/cache/live/declared_index.json`, `backend/cache/live/evidence_inventory.json`, `backend/cache/live/evidence_engine_status.json`; `docs/evidence-engine.md`, this report, `evidence-city.json`, `evidence-fetch.json`, `evidence-coverage.json`, `evidence-coverage-delta.json`, `evidence-verification.json`, `coverage-evidence.png`, and its HTML wrapper. Raw caches/archives/diagnostics are under already-gitignored `data/raw/listings_city/`. No secrets were printed; no commit was made.
