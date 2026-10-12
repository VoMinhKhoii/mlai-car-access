# Phase 4 and 5: verification evidence (2026-10-12)

Runs on an isolated store (`/tmp/p4smoke`), the demo OSM cache, no AI or Goong keys, `live_hydro` off. No secret
values are recorded here.

## Automated

| Check | Result |
|---|---|
| `cd backend && ../.venv/bin/python -m unittest discover -s tests -t .` | 100 tests, OK |
| `npx tsc -b` | no errors |
| `npm run build` | built |
| `npm run lint` | 14 warnings, all pre-existing (same count as before this phase); 0 errors |
| Repository `backend/store`, `backend/cache` | unchanged by tests and smoke |

New modules: `test_operator_access`, `test_evidence_isolation`, `test_camera_jobs`, `test_budget_limits`;
`test_corridor` migrated to the cached-readings contract.

## Runtime smoke (one uvicorn worker, production bundle served by the backend)

| Check | Observed |
|---|---|
| Plan with a forged `area` field | 422 |
| Guest: area build, camera read | 401, 401 |
| Operator build, repeated request | 202, joined the same job (single flight) |
| Foreground `/api/config`, `/api/vehicles`, `/api/operator/status` during a build | 0 calls over 1 s |
| Build against the real (slow) planning portal | parcels stopped at 150 s with 0 ways; listings and news finished; record published as `partial`, revision 1 |
| Earlier, before the parcel sub-budget | the slow portal consumed the full 300 s deadline and lost the whole build; fixed |
| Warm demo plan | 15.3 s before, 0.86 s after (same 775 candidates; exact reach pre-filter) |
| Guest confirmation | 202 `pending`; operator approved; projected once |
| Restart with the same store | pending/approved state kept, no demo blockage reseeded |
| Operator camera read without an AI model | 202 job → `ready`, reading state `offline`; never "clear" |
| Unknown API / SPA / encoded traversal | 404 JSON / 200 / 404 |

Browser (desktop 1280×800, mobile 390×844): guest sees the partial-area line and "Cần người điều hành"; flag switches
disabled; guest blockage report shows "chờ người điều hành duyệt"; wrong secret rejected; operator login shows the
review queue with the guest report; approval empties it; operator cookie not readable from JS; logout restores the
guest view and the server reports `operator: false`; no console or page errors.

## Not exercised (missing prerequisites)

- Corridor live path and camera subset in a real browser: no `GOONG_API_KEY` on this machine, so `/api/corridor`
  answers `available: false`. The 12-camera subset, dropped list and per-hotspot coverage are covered by
  `test_corridor.CameraJobScheduling` only.
- Live AI calls (camera reading, listing photos, text/photo extraction): no model keys. Quota reservation per attempt
  is covered by `test_budget_limits` with a stubbed upstream.
- Production hosting: no backend origin configured; nothing deployed.

## Phase 5 field gate (R-11): blocked on data, owner: field team

`data/field/measurements.csv` and `data/field/egress.csv` contain headers only. `pipelines/eval_field.py` refuses to
run with fewer than 20 rows (checked: exit 2). Its mechanics (frozen group split, re-freeze refused, leak check,
interval-aware false-fit scoring, gate) were exercised once on a throwaway synthetic file outside the repository;
those numbers are not evidence and are not recorded as results.
