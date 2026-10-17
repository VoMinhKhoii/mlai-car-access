# Product branch and hackathon night merge — 17 October 2026

Merged `origin/fix/collapsible-result-cards` at
`339e6439b8a959fe9de9e5de752b246d76d49f18` into
`hackathon-night-2026-10-17` at `90129c1`. This target includes `origin/main`
(`f000823`) and access-safety hardening. The trial main-only merge was aborted
before edits; this is one merge with the corrected target. No push was performed.

The product branch owns UI/UX, safety verdicts, evidence authority, operator
review and bounded jobs. Night additions are integrated into those contracts.

## Conflict resolutions

All 26 conflicted files were resolved; no conflict markers remain.

| File | Resolution |
| --- | --- |
| `.gitignore` | Union of secret/runtime exclusions, city cache and lock exclusions; `.env*` stays ignored. |
| `backend/app/ai.py` | Product multi-image/model fallback and quota reservation, plus bounded night Gemini text retry and project quota accounting. Camera model fallback retains independent attempts. |
| `backend/app/budget.py` | Product provider/SKU hard caps, night Google file lock and separate agent dollar reservation ledger. |
| `backend/app/evidence.py` | Product immutable index and request overlays; add city/listings/reviewed imagery and advisory metadata. Parcel gaps remain Inferred, never clear-width certification. |
| `backend/app/flood.py` | Product missingness, departure/dwell and snapshot semantics, plus refreshed official bulletin parser. Measurements win; a newer bulletin supersedes an older marine-model fetch. Both timeline and plan use the same selection and retain provenance. |
| `backend/app/legality.py` | Product interval checks and access-versus-legal semantics retained. Night duplicate engine preserved separately. |
| `backend/app/live.py` | Product bounded server-owned build/publish jobs retained; merge city parcel cache, trusted listing/photo/news inputs and freshest queried records. No browser evidence promotion or global planner mutation. |
| `backend/app/main.py` | Product operator/reports/cameras/corridor/validation retained; add geocoding, evidence queue, AlleyAI and read-only MCP endpoints before static catch-all. |
| `backend/app/news.py` | Product bounded transport/deadline behavior retained. |
| `backend/app/osm.py` | Product bounded LRU plus atomic writes, file-stamp invalidation and offline/crawler helpers. |
| `backend/app/parcels.py` | Product full-way ingress/egress deep scan and D33 toggle remain primary; add shared portal backoff and crawler adapters. Failed cuts consume attempt budget. |
| `backend/app/plan.py` | Product solver, egress, flood/departure, hard checks and verdicts retained; add request-owned city cache overlay and advisory best estimate/confidence without elevating verified safety. |
| `backend/app/vehicles.py` | Product minimum body width with night envelope/unit/provenance normalization and caching. |
| `backend/cache/live/parcels.json` | Union by cache key: 202 night keys + 194 product keys = 238 merged keys; zero missing keys. |
| `docs/decision-log.md` | Entire product log preserved byte-for-byte as prefix; night entries appended as D37–D50. |
| `frontend/index.html` | Product Be Vietnam Pro, Ngõ Ngách title. |
| `frontend/src/App.tsx` | Product collapsible cards, route card, parking watch, operator controls, structured confirmation and voice report; add AlleyAI and Ngõ Ngách naming. |
| `frontend/src/MapView.tsx` | Product cameras, route/maneuver overlays and pin-to-card behavior; add night map-feature context/search after camera/flood hit handling. |
| `frontend/src/api.ts` | Canonical product API contracts plus agent streaming and advisory estimate types. |
| `frontend/src/index.css` | Product layout/font/layer styles retained with agent integration. Field UI also uses Be Vietnam Pro. |
| `frontend/src/components/Directions.tsx` | Product validated/cancellable direction flow plus map-context suggestions. |
| `frontend/src/components/Result.tsx` | Product component retained as primary, including collapsible stop cards and maneuver controls. |
| `frontend/src/components/TideTimeline.tsx` | Product observed/model/missingness UI plus official bulletin provenance link. |
| `frontend/vite.config.ts` | Product configurable backend proxy plus field entry-point build. |
| `pipelines/eval_city.py` | Canonical product plan API; night city evaluation retained with request-owned evidence. |
| `requirements.txt` | Dependency union, including product runtime dependencies and night PDF/image/QR tooling. |

Flags are a union. `parcel_deep_scan` stays on; `footprint_widths` and
`building_gaps` stay off. Be Vietnam Pro is inherited by AlleyAI as well.

## Reconciliation of overlapping systems

1. **Width engine/audit:** product width coverage, clear-width authority, egress,
   flood and legality remain active. Night estimates are advisory additions. The
   superseded night engine is preserved in `backend/app/experimental/night_engine`
   behind an import guard, off by default; no production route imports it.
2. **Field intake versus field kit/crowd QR:** product pending field reports and
   operator approval are active. Night field/crowd/QR routes require
   `ENABLE_NIGHT_FIELD_KIT=1` and are not mounted by the main app. QR integration
   with canonical review remains unfinished.
3. **Evidence review:** product operator review and idempotent projection are the
   only active publication authority. Night city queue uses the canonical Store
   view; legacy imagery review status alone cannot publish evidence.
4. **Driver confirmation versus arrival prompt:** product structured confirmation,
   voice parsing and pending reports are active. The old arrival flow remains in
   the disabled field bundle, with no second active confirmation endpoint.
5. **Parcel crawler versus live builds:** product bounded live jobs remain primary;
   night crawler feeds the city cache. Plans merge trusted cache data per request.
   Old global `set_live`/`live.build` callers were migrated to canonical paths.
6. **Tide sources:** one flood module selects measurements, freshest bulletin/model,
   and missingness; background official refresh invalidates the shared wrappers.
7. **AI quotas:** product per-attempt quota reservation remains mandatory. AlleyAI
   adds Vertex paid opt-in and its own dollar cap; model calls require operator
   access. Guests use deterministic cached tools. No second open spend endpoint.
8. **UI:** product route/camera/cards/maneuver UI remains primary. AlleyAI is one
   additional panel, and its tool plan updates the same destination/result state.
9. **Unfinished night work:** map-feature search compiles and is retained in the
   active UI. `width_samples.py` outlier assessment is retained for diagnostics;
   its parcel adapter is not called by the production width-combination path.

## Decision renumbering

All product numbers, including D33, D34 cameras, D35 hydro and D36 server-owned
authority, remain unchanged. Our night references in code, CONTEXT, docs and eval
reports were updated. Street names, source snapshots and opaque embedded assets
were preserved rather than treated as decision references.

| Night old | Merged new |
| --- | --- |
| D34 | D37 |
| D35 | D38 |
| D36 | D39 |
| D37 | D40 |
| D38 | D41 |
| D39 | D42 |
| D40 | D43 |
| D41 | D44 |
| D42 | D45 |
| D43 | D46 |
| D44 | D47 |
| D45 | D48 |
| D46 | D49 |
| D47 | D50 |

These appended entries record the night implementation history. The integration
choices above supersede conflicting prototype behavior.

## Verification

- `PYTHONPATH=backend:. python3 -m pytest backend/tests pipelines -q`:
  **393 passed, 77 explicitly skipped, 258 subtests passed, 2 warnings**, 78.96 s.
  Skips are old duplicate engine/field contracts pending migration, documented in
  root `conftest.py` and the experimental README. Product safety, evidence,
  operator, budget, camera, corridor, flood, maneuver and report tests remain on.
  Warnings: local Requests dependency versions and AnyIO alias deprecation.
- `python3 -m compileall -q backend/app pipelines`: passed, including parked code.
- `cd frontend && npm ci && npm run build`: passed; `frontend/dist` rebuilt on
  disk (ignored build output). Existing large JavaScript chunk warning remains.
- Staged additions and complete staged files were scanned for `AIza…` and
  `AQ.…` key patterns: zero matches; no `.env.local`, `.env` or `key.txt` staged.
  Whitespace checks only flag the unchanged product PDF's binary content and an
  existing blank line at the end of its phase-01 plan; source changes are clean.
- Quick audit: **100 plans**, 20 cached destinations × 5 vehicles, 31.8 s;
  **0 crashes, 0 fit/plan monotonicity violations, 0 reported/drawn walks over cap,
  0 geometry mismatches**. See [summary](merge-quick-sweep/summary.json) and
  [compressed details](merge-quick-sweep/audit-sweep.json.gz). Final source hashes
  match the audit. Full 1,500-plan sweep omitted per time box.
- Audit geometry comparison was adapted to the product's intentionally undrawn
  off-network connectors: route length is checked against drawn geometry plus
  those explicit connectors; planner caps were not relaxed.

The test server runs only on **127.0.0.1:8794**, with isolated temporary store,
flags/operator secret, `NGONGACH_CACHED_ONLY=1`, `AGENT_ALLOW_PAID=0`, live hydro
and crawl disabled, and no Goong backend key. It uses the product's isolated H160
fixture app; synthetic widths never enter production storage.

Sanitized API results are in [merge-smoke.json](merge-smoke.json):

| Check | Result |
| --- | --- |
| `/api/config` | 200; expected flags and synthetic test provenance |
| `/api/search?q=HUTECH` | 200, 6 results |
| `/api/plan`, Hẻm 113/4, Fortuner | 200, 3 stops, conservative unverified verdict and advisory estimate |
| `/api/cameras` | 200, 796 cameras |
| Camera JPEG | Expected 404, no cached still in offline smoke |
| Camera read | Guest 401; temporary operator login 200 and bounded read job 202 |
| `/api/corridor` | 200, explicit unavailable without Goong backend key |
| Maneuver API | 200, 8 moves / 120 poses for Vios at width 6 m |
| H160 fixture plan | 200, 3 stops, synthetic marker; unverified safety remains conservative |
| AlleyAI | 200, tool calls/results, UI plan, answer, done |
| Tide | 200, 97 points from official bulletin 289/2026 |
| Evidence queue | 200, available, 3 items |
| Paid model calls | 0; no paid ledger created, USD 0 spent |

Browser proof from the final built app:

- [Camera layer + font](merge-camera-font.png): visible camera markers, checked
  camera layer and camera details. Missing live still is explicitly shown.
- [AlleyAI + plan](merge-alleyai.png): assistant response, same Fortuner plan,
  Ngõ Ngách branding and product result cards.
- [Maneuver preview](merge-maneuver.png): H160 Vios trajectory replay, car footprint
  and route overlay. Be Vietnam Pro loaded successfully (`document.fonts.check`)
  and is the computed UI font.

## Remaining limits and restart commands

Live camera imagery/AI and a real Goong corridor were not exercised with upstream
credentials in this cached-only smoke. Paid Vertex calls were intentionally not
made. Crowd QR intake and legacy engine contracts remain parked. H160's shipped
preset uses 29 September; current bulletin coverage is absent on that date and
the app correctly shows missing tide data/unverified rather than claiming safety.
Regenerable raw sweep output and pre-existing untracked browser/cache/tmp files
were left out of the commit. The scheduler's runtime status change is also left
unstaged; no crawler is started by this merge.

Ports **8787 and 8789 were left running unchanged** (PIDs 24991 and 24992 at
verification); port **8790 had no listener** and was not started. The temporary
8794 smoke server remains available for inspection. Stop each existing process
yourself before using its restart command, in separate terminals:

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=0 PYTHONPATH=backend:. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
```

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=0 PYTHONPATH=backend:. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8789 --workers 1
```

Port 8790 is the parked field surface; its default command does not enable field
APIs. Use canonical report intake in the main app for the demo:

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=0 PYTHONPATH=backend:. python3 -m uvicorn app.field_server:app --host 127.0.0.1 --port 8790 --workers 1
```

Paid AlleyAI requires the existing operator login plus explicit
`AGENT_ALLOW_PAID=1` and the previously configured Vertex budget/endpoint. No
credentials are included here. Do not run multiple workers over the local store.
