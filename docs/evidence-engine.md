# City evidence engine

This engine collects listing claims, joins explicit alley address chains to the cached OSM network, publishes `backend/cache/live/declared_index.json`, and ranks ways that need better evidence. It makes **no planning-portal requests**, uses no paid provider, and does not change the cadastral crawler or its lease/cache. Results and limitations are in [the city evaluation](eval/evidence-city.md).

## Run and resume

From the repository root, using the existing Python environment:

```sh
python3 pipelines/listings_city.py run
python3 pipelines/listings_city.py run --loop --interval-hours 12
```

`run` fetches then builds. `fetch` and `build` can be run independently. Default: all 22 Chợ Tốt source districts, both sale and rent, 50 ads/page, up to 100 pages per partition, at least 1.5 seconds between sequential request starts. `--max-pages` changes the explicit safety cap. Partitions are fetched round-robin so a large district cannot monopolize the initial pass. Short, empty and repeated pages stop pagination. API failures stop the affected partition; HTTP 403/429/5xx set a **persisted host cooldown**, honoring Retry-After or exponential backoff from 15 minutes to one day. There is no proxy, identity rotation, browser bypass, or retry storm.

Pages are cached for 12 hours (`--ttl-hours`). On restart, fresh pages are read locally and deeper pagination resumes. `data/raw/listings_city/listings.sqlite` retains immutable sanitized listing revisions. Disappearing ads and later refreshes do not erase earlier Evidence; there is no implicit ageing policy. Raw pages, review diagnostics and hashes are gitignored under `data/raw/`. Personal account ids become hashes; the public index contains only listing links, dates, claims and aggregate counts. One process owns `data/raw/listings_city/engine.lock`; the file contains its PID. This lock is unrelated to the cadastral crawler.

The repeating process publishes `backend/cache/live/evidence_engine_status.json` with its PID, last successful cycle and next run. To stop **only this engine**, obtain the PID from that status file and send TERM. The existing cadastral crawler's PID and lease must not be used. A cycle finishes safely before the engine exits. The detached process is local to this machine and is not an installed launch-at-login service.

The default consumes **zero LLM calls**. To inspect ambiguous text with free keys:

```sh
python3 pipelines/listings_city.py build --llm-budget 50
```

Only environment names `GEMINI_API_KEY*` qualify. The paid key and any free-named alias with the paid key's value are excluded. There is no fallback to `app.ai`, OpenAI, grounding, photos or paid credentials. The pipeline has a transactionally enforced **1,500-call lifetime cap**, including failed attempts and interrupted reservations, in `llm_cache.sqlite`. Every result/error is cached by SHA-256 of model, recipe and prompt. Quota/configuration errors stop further calls in that build, without rotating keys. `--llm-budget 0` also reuses existing cached results. Only quoted, source-supported, baseline-compatible results pass the gate; ambiguous or unsupported claims remain REVIEW and are excluded.

Alonhadat is attempted only on robots-authorized pages, sale and rent. Robots Crawl-delay is honored. A blocked host is left alone until its cooldown expires. Existing listing caches remain usable. Mapillary is skipped without an account client token; [its official instructions require an account and registered application](https://github.com/mapillary/mapillary-js#installation-and-usage). No account is created automatically.

## Evidence contract

- An explicit own-alley numeric width is an **upper bound**, not a measurement of Clear Width. “Hẻm xe hơi”, “xe hơi ngủ trong nhà” and the Chợ Tốt HXH flag provide the existing conservative car lower bound. Nearby-car-alley claims are not promoted to own-alley access.
- Matching uses the existing deepest-chain matcher and its 1 km same-name disambiguation limit. Shifted coordinates alone are never a match. Without a coordinate, city-wide name ambiguity is rejected. An unmatched numeric width or no-car claim cannot propagate to a parent alley; a car lower bound can.
- Each way retains all listing claims, source URLs, dates, first/last posting, independent-listing estimate and agreement. Shared seller, exact property address or identical content joins listings into one independence group. This is an estimate, not verified independent property ownership.
- Disagreement keeps the **hull** of claimed bounds and raises REVIEW. Neither a repeated live listing nor a generic OSM road-class prior can collapse that hull. Even compatible index claims are completely overruled by Measured/Official bounds. Stronger Observed evidence follows the established tier combiner.
- The index uses the existing `ai_listings` flag. Atomic publication plus mtime/size reload updates the EvidenceStore **before** the existing plan width-cache version check. A malformed replacement retains the last good index; deletion removes its Evidence.
- The entire QĐ 4582 annex is audited, with every parsed entry assigned matched ids or an explicit unresolved reason. No-access remains Declared, because width, bends, low wires and dead ends can all explain it. Missing OSM names are not forced onto nearby unrelated ways. Detailed per-item diagnostics: `data/raw/listings_city/fire_audit.json`.
- OSM `width`, `est_width` and `maxwidth` reuse their existing Observed semantics. Coverage audits do not manufacture new tags. `lanes` alone does not become new Clear Width Evidence. News remains contextual information, rather than Width Evidence. The failed footprint experiment remains disabled by default.

## Measurement queue

```http
GET /api/evidence/queue?limit=100
GET /api/evidence/queue?limit=100&bbox=106.65,10.75,106.75,10.85&min_score=3
```

`bbox` is west,south,east,north. `limit` is 1–1,000. Each item includes `way_id`, name, representative coordinates, Width Range (`hi:null` means open), strongest source tier, request count, score, review flag and vehicle thresholds straddled. Ties prefer named/tagged alleys, then stable way id. A read does not reserve work or contact a source.

```
score = (1 + log2(1 + plan_requests))
      × (1 + number_of_thresholds_straddled)
      × tier_scarcity
      × (1.5 if REVIEW else 1)
```

Rounded common `tight_min` thresholds: VF 3 **1.95 m**, sedan **2.18 m**, SUV **2.31 m**. A threshold is straddled when `lo < threshold <= hi`; reaching it at the lower bound already resolves that threshold. Tier scarcity: Measured .05, Official .15, Observed .7, Declared 1, Inferred 1.3, no sourced width 1.5. This is an operational value-of-information heuristic, not a calibrated expected-utility model. Unknown ways can enter the queue before any plan uses them.

Successful `/api/plan` responses log explicit door/stop ids and ways overlapping returned route geometry, once per way per request. Merely appearing in the map layer does not count. Geometry crossing at a junction is insufficient. The SQLite aggregate in `backend/store/evidence_usage.sqlite` stores only way id, request count and last-seen time; it does not store destinations, drivers or vehicle history. Logging errors never break an Arrival Plan. The HTTP response hook is installed by the new router module, without editing `plan.py` or `agent.py`. Direct internal plan calls and plans returned by the separate agent stream are not counted unless their owner explicitly calls `record_way_ids`; do not interpret HTTP counts as total product demand.

The cadastral crawler now consumes the local queue with `pipelines/crawl_city.py --ranked`.
It preserves the API's top-1,000 snapshot order, then offers the HUTECH 500 m inner
set, then the remaining cached-city inventory. Snapshots refresh every 30 minutes;
recent completed selections are skipped across resumes. A failed queue read falls
back to the same in-process ranking implementation, not an unranked source query.

Each way receives one targeted cut: the narrowest located cached footprint/parcel
hint that passes the current corner and junction guards, or a valid straight
interior station when there is no located hint. Hints choose a query location;
they do not become Official evidence. A single cut never certifies whole-way
coverage. `pipelines/crawl_ranked.py` writes a no-portal dry plan proving its first
20 ids match `GET /api/evidence/queue`.

The one-shot `pipelines/schedule_crawl.py` waits without a crawler lease or network
activity until **2026-10-17 21:00 +07**, then execs the ranked crawler with the same
PID/nice level. It saves and pauses at **2026-10-18 07:00 +07**. No daily recurrence
is installed. Portal requests remain direct, with the existing User-Agent and
shared two-slot gate. Spacing starts at at least three minutes, never decreases
below persisted/history-derived pacing, and doubles after a lock. Crawler lock
recovery is 2 h, 4 h, then 8 h maximum. API backoff remains separate; crawler
waiting does not hold the shared rate lock. See `docs/eval/crawler-round4.md`.

Field teams can use name/coordinates as a measurement itinerary, record a narrowest Clear Width with source/date/photo in the existing measurement workflow, and reload Evidence. AI photo reading should use the existing review gate and source tier; it must not publish Measured/Official Evidence by itself. Completed measurements change the way's tier/range and reduce its queue priority on the next snapshot. There is deliberately no competing reservation protocol in this read API.

## Coverage and reproducible checks

`/api/config.coverage` gains `evidence_*` fields for unique non-main ways, drivable non-main ways, named/tagged alleys, source counts, mutually exclusive strongest-tier counts and unknowns. Generic road-class/lanes priors are excluded. Existing coverage fields retain their original, smaller footprint/crawler scopes; use the explicitly prefixed fields for the full cached-city union. These counts indicate source availability, not resolved vehicle fit or physical measurement.

The inventory is built from **every cached routing cell**, city batches and the demo graph, with no new Overpass or portal requests. It describes the union of cached urban HCMC, not every administrative part of the city. Outer districts can have listing claims with no cached named OSM way, and remain unmatched. `backend/cache/live/evidence_inventory.json` is generated street geometry and tags; rebuild it with `--force-inventory` when needed.

```sh
PYTHONPATH=backend:. python3 -m pytest -q pipelines/test_evidence_city.py backend/tests/test_footprints.py
PYTHONPATH=backend:. python3 pipelines/verify_evidence_city.py
python3 pipelines/render_evidence_city.py
```

The verifier makes actual ASGI `/api/plan`, `/api/config` and queue requests while blocking **all external HTTP**. Its demand database is temporary. The renderer writes [the strongest-tier map](eval/coverage-evidence.png) and `eval/evidence-coverage.json`. Refresh the map after a successful build to update the published evaluation artifact.

## Street-level imagery worker

`pipelines/imagery_widths.py` consumes this same ranked queue without needing a
running HTTP server. It adds every named/tagged alley intersecting a HUTECH 500 m
circle and 40 preselected cadastral validation ways. It reuses exact-chain Chợ Tốt
matches and original photo URLs already cached by `live.py`; shifted listing
coordinates are never treated as camera positions.

```sh
PYTHONPATH=backend:. AGENT_ALLOW_PAID=1 python3 -u pipelines/imagery_widths.py --top-n 1000 --wait-for-free
PYTHONPATH=backend:. python3 pipelines/imagery_widths.py --validate-only
PYTHONPATH=backend:. python3 pipelines/imagery_widths.py --review OBSERVATION_ID --reviewer 'Human name'
# Add --reject to record a human rejection instead.
```

The persistent job id is `imagery-widths-2026-10-17`. Restarting never resets its
$1 ceiling. Reservations and settlements use `agent_budget`'s shared lock, with
an additional shared $1.10 ceiling so this job cannot consume the live agent's
$1.90 reserve. Accounting deliberately retains the ledger's conservative token
rates. Free keys are tried first after the persisted project cooldown expires;
`--wait-for-free` keeps the detached worker alive until today's reset and makes
one free-only continuation. No Google budget caps are changed.

Progress/log: `backend/cache/live/imagery/run.json` and `run.log`. The review
product is `backend/cache/live/imagery_widths.json`; validation is also written
to `backend/cache/live/imagery/validation.json`. Pending/ACCEPT readings never
enter planning. A named human approval activates Observed evidence with incomplete
coverage and no whole-way minimum-width guarantee (D48). Rejected, blurred,
night-time, off-alley or reference-free readings cannot be approved. A listing's
posted date does not establish image capture time.

Mapillary is skipped by default. Add `MAPILLARY_CLIENT_TOKEN` to `.env.local`
and run the worker with `--mapillary`. `app.imagery_evidence.mapillary_images`
uses the Graph `/images` endpoint with the token in an Authorization header;
the runner checks the camera position and alley-axis alignment, downloads the
thumbnail, and sends it through the same budget/review path. No token is written
to products or logs. This optional token path has offline coverage but has not
been authenticated during this run.

## Official bulk historical widths and planned ROW (D49)

The separate [official bulk research/import](eval/official-bulk.md) publishes
`backend/cache/live/official_widths.json`. `app.official_widths` exposes these as
`WidthRange.official_width_records`, with original dates, sources, rights notes,
`tier: Official` and `affects_clear_width: false`. Historical base/road widths and
planned lộ giới never enter `Bound` or `_combine`, never certify vehicle fit and
never increase current-width strongest-tier coverage. Source-date uncertainty and
planning semantics require this separation. The loader reloads metadata before
cached plan serialization is reused; malformed replacements retain the last good
product. The importer performs no point-portal or LLM calls. The source audit,
zero-overlap cadastral validation and Vietnamese data-request drafts are linked
from the report. No citywide current Clear Width completeness is claimed.
