# Imagery widths — paid-stage report, 17 October 2026

Implemented and run, **uncommitted**. No Observed evidence has been published.
This is a snapshot at 2026-10-17T00:17:23+00:00; the live worker and the demo agent can change the
operational ledgers after this snapshot.

## Outcome and blocker

- Target selection: top 1,000 queue alleys, all 556 alleys intersecting the HUTECH 500 m circles, and 40 preselected cadastral validation ways; latest pass has 1,551 unique targets. Additional exact-chain listing backlog ways are processed in queue order. Inventory/parcel state is being updated by other workers, so selections can change between restarts.
- Google Street View returned `REQUEST_DENIED`: **“You must enable Billing on the Google Cloud Project.”** No Static images were fetched. No Google Cloud configuration or cap was changed. Street View coverage/accuracy is therefore unproven. Once the project is configured, `--retry-google` retries the cached denial.
- 216 vision readings, covering 164 unique listing photos associated with 66 ways, including prompt development/audit. These are not all usable observations.
- Current strict v2 product: **52 readings on 18 ways; 3 pending candidates on 3 ways; 0 approved**. Other v2 readings fail the quality/reference/geometry gate. Listing capture dates are unknown, not replaced by posting dates.
- A visual spot-check found a confident v1 frontage false positive. All **164 v1 readings were quarantined** in `legacy_records`, and none was ever approved. V2 explicitly requires an along-alley view with opposing edges visible. Two retained v2 candidates were visually checked and do show along-alley scenes, but this is not physical width validation or human approval.

## Validation and publication decision

**Validation is unavailable; do not describe this as calibrated width evidence.**
Current v2 located comparisons against a valid cadastral `gap_m - 1` cut within
15 m: **n=0 ways, MAE unavailable, bias unavailable**. The weaker comparison of
unlocated listing views to a way's narrowest cadastral cut also has n=0 current
v2 ways. During the v1 audit, one such convenience overlap differed by +1.51 m;
that quarantined reading is not a calibration result. Independent surveyed Clear
Width and full-way coverage are absent.

D48 keeps everything REVIEW-only. Gate `ACCEPT` only means a structurally usable
reading; it stays pending. A named human must approve a candidate. Approved
imagery enters Observed as [0, visible upper bound], with incomplete coverage,
so the unseen remainder cannot be certified by a single photograph. Stronger
Measured/Official evidence keeps precedence. Pending writes do not churn live
plan/queue caches; approvals and rejections invalidate them.

## Money and detached continuation

- Imagery job ledger charge: **$0.911340**, including both prompt versions, with **$0 outstanding reservations**. The failed preliminary Vertex requests returned 400 and were uncharged. Existing conservative ledger token rates are retained; this is not a provider invoice.
- Job hard ceiling: $1.00 cumulative across restarts. A reservation must also keep shared spending/reservations below $1.10, leaving $1.90 of the original $3 pool unconsumed by this job. At this snapshot the shared ledger, including concurrent live-agent usage, has $0.997540 spent and **$2.002460 remaining**. The demo agent's own later spending changes that remainder.
- Google job SKU reservations: **5 metadata, 0 Static, 0 Nearby, 0 Details, 0 Maps grounding**. Metadata is free; Google spend from this run is $0. Existing daily/monthly caps are unchanged. Full counter/cap details are in `imagery-widths-run.json`.
- Worker **PID 35019** is detached and **waiting until 2026-10-17T14:00:00+07:00**. It will make one **free-only** continuation today, stopping on quota, provider failure, completion or the date limit. It cannot replenish its paid job allowance. A process/reboot interruption requires restarting the command below; cached readings and the paid ceiling persist.

```sh
PYTHONPATH=backend:. AGENT_ALLOW_PAID=1 python3 -u pipelines/imagery_widths.py --top-n 1000 --wait-for-free
```

Live status/log: `backend/cache/live/imagery/run.json` and `run.log`.
Review product: `backend/cache/live/imagery_widths.json`.
Validation: `backend/cache/live/imagery/validation.json`.

## Mapillary hookup

Skipped: no user token was provided. Set **`MAPILLARY_CLIENT_TOKEN`** in
`.env.local` and add **`--mapillary`** to the runner. Code path:
`backend/app/imagery_evidence.py::mapillary_images` → Mapillary Graph `/images`
with Authorization header → runner position/heading checks → thumbnail download
→ the same Gemini budget, cache and human review gate. This path has offline
adapter tests; live Mapillary authentication has not been tested. Tokens never
enter URLs, artifacts or logs.

## Checks and changed files

Latest targeted validation: **63 passed, 15 subtests passed**, including **16
imagery tests**. Tests cover job/reservation caps under concurrency, conservative
settlement, review rejection and reload, no pending cache invalidation, frontage/
night/blur/reference rejection, off-alley panoramas, non-cancelling MAE, raw gap
comparison, Vertex role/model/thinking/output configuration, Mapillary token
handling and unchanged Google caps. Python compilation and diff whitespace
checks pass.

The broader suite run finished **178 passed, 59 subtests passed, 1 failed**.
Failure: `pipelines/test_crawl_city.py::CityCacheTests::test_warm_path_keeps_destination_deep_scan_and_preserves_existing_deep`;
its `SimpleNamespace` graph lacks `edges` required by `parcels.measure_area`.
That parcel implementation/fixture is outside the imagery changes and was left
for its owner. The broad run preceded the last added imagery tests; the latest
targeted run above is the final check for this implementation.

Source/document changes made by this task:

- `pipelines/imagery_widths.py` — new ranked, resumable/detached worker, validation, review CLI, optional Mapillary path.
- `backend/app/imagery_evidence.py` — new strict prompt, low-cost/free-first adapter, atomic review/cache product, reviewed Observed loader.
- `backend/tests/test_imagery_evidence.py` — 16 offline checks.
- `backend/app/agent_budget.py` — optional persistent job reservations/settlements under the existing shared lock; existing $3 ceiling/rates unchanged.
- `backend/app/budget.py` — interprocess lock and atomic counters; caps unchanged.
- `backend/app/evidence.py` — small delimited load/refresh hooks, preserving existing concurrent edits.
- `backend/app/evidence_queue.py` — approved imagery content invalidates queue/coverage.
- `requirements.txt` — Pillow for bounded image resizing.
- `docs/decision-log.md` — D48 and the v1 failure/audit decision.
- `docs/evidence-engine.md` — run/review/Mapillary instructions.
- `docs/eval/imagery-widths-report.md` and `imagery-widths-run.json` — this report and machine-readable paid-stage snapshot.

Operational files also changed under `backend/cache/live/imagery*` and the
existing Google/Gemini usage ledgers. No keys were printed. No commits were
made and no running application server was restarted; loading new backend code
in a server still requires its normal reload/restart.
