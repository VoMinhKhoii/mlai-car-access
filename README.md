# Vào Được (working name)

**Xe bạn vào được, và ra được, không?** A T-Maps layer for HCMC that answers, for one specific car, whether it can reach an address in the hẻm network and get back out, given alley geometry, flood evidence during your stay, and parking law. If it can't, the layer says where to stop and how far to walk.

MLAI Hackathon 2026 · Tasco & Goong track.

- Domain language: [`CONTEXT.md`](CONTEXT.md)
- Every decision and why: [`docs/decision-log.md`](docs/decision-log.md)
- Research with sources: [`docs/research/`](docs/research/)

## Run it

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
npm --prefix frontend ci && npm --prefix frontend run build

# One backend process owns sessions, reviews, quotas and background jobs: always run a single worker.
cd backend
../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1
```

Open http://127.0.0.1:8787 (the backend serves `frontend/dist`) and pick a **Kịch bản demo**. While editing the UI, `npm --prefix frontend run dev` serves http://127.0.0.1:5173 and proxies `/api` to `BACKEND_ORIGIN` (default `http://127.0.0.1:8787`).

### Deploying

The backend is a stateful process, not a serverless function: run one `uvicorn --workers 1` behind HTTPS with persistent `VAODUOC_STORE`, `VAODUOC_CACHE` and `VAODUOC_FLAGS` directories, and serve the frontend from it (same origin). It refuses to start when `VERCEL` is set. If the frontend is hosted elsewhere, proxy `/api/**` to the backend's HTTPS origin and list the frontend origin in `APP_ORIGINS`; the operator cookie is host-only, so the proxy must keep both on one site.

Before upgrading a running deployment, back up `VAODUOC_STORE` (reviews, approved evidence, quotas). On the first start, unreviewed legacy community lines (driver confirmations, blockages, AI flood reports) are moved to `STORE/quarantine/` and queued for review; nothing is deleted.

### Operator access

Guests can plan, read corridors (forecast and cached camera readings) and submit reports; reports wait in a review queue. Anything that changes state, spends AI or paid-Google quota, or schedules background work (flags, area builds, camera reads, photo and report review, AI text/photo, Google lookups) needs an operator session. Set `OPERATOR_SECRET` or `OPERATOR_SECRET_FILE` on the server, then sign in from the **Demo** menu; without a secret those features are unavailable, not open. The executable owners are [`backend/app/auth.py`](backend/app/auth.py) and [`backend/app/reports.py`](backend/app/reports.py).

### Keys (all optional; the app degrades gracefully)

Put them in `.env.local` at the repo root (gitignored):

```
GOONG_API_KEY=...        # search, geocoding, Standard Route
GOONG_MAPTILES_KEY=...   # Goong base map (otherwise an open CARTO base map)
GEMINI_API_KEY=...       # or OPENAI_API_KEY / ANTHROPIC_API_KEY, for the AI text/photo/camera features
AI_MODEL=...             # optional model override
AI_DAILY_CAP_PER_KEY=200 # optional AI attempt caps per key and per model (backend/app/budget.py)
AI_DAILY_CAP_PER_MODEL=500
OPERATOR_SECRET=...      # or OPERATOR_SECRET_FILE=/path; enables operator features
APP_ORIGINS=...          # comma-separated extra browser origins allowed to change state (CSRF guard)
```

### Request provenance and isolated startup

- Arrival and departure request times are intentionally `string | null`: `null` means “now”, while a string must be a complete ISO 8601 timestamp with an explicit timezone. `dwell_min` is a strictly positive integer. This prevents partial browser-local dates from being guessed or silently shifted; the executable owners are `PlanRequest`, `CorridorRequest`, and `DurationMinutes` in [`backend/app/main.py`](backend/app/main.py), with the browser boundary in [`frontend/src/api.ts`](frontend/src/api.ts).
- The standard reference route carries a closed `osm | goong` source value so an OSM fallback is not presented as Goong. The owners are `_standard_route` in [`backend/app/plan.py`](backend/app/plan.py), `RouteSource` in [`frontend/src/api.ts`](frontend/src/api.ts), and the labels in `StandardRouteContrast` and `LayersMenu` in [`frontend/src/components/Result.tsx`](frontend/src/components/Result.tsx) and [`frontend/src/App.tsx`](frontend/src/App.tsx).
- Isolated backend startup can redirect the writable store directory, cache directory, flags file and frontend bundle with `VAODUOC_STORE`, `VAODUOC_CACHE`, `VAODUOC_FLAGS` and `VAODUOC_DIST`. Set them before importing the backend so derived paths share the same isolated root and do not touch normal local state; [`backend/app/config.py`](backend/app/config.py) owns these overrides.

### AI features: one flag each

Operators toggle them in the **Demo** menu, or set `FLAG_<NAME>=1|0` env vars; state persists in the `VAODUOC_FLAGS` file.

| Flag | What it does | Default |
|---|---|---|
| `ai_listings` | Chợ Tốt listings → alley-width Evidence (Declared tier) | on |
| `ai_flood_prior` | Per-street flood susceptibility from IRD history (percentile depths, alleys inherit from their flooded street) | on |
| `ai_text_rules` | Ordinance or news text → Stop Rules and flood reports, through the ACCEPT / REVIEW / INSUFFICIENT_INFORMATION gate | off |
| `ai_photo_evidence` | Driver photo → sign, alley width or flood depth | off |
| `ai_camera_flood` | ~800 public HCMC traffic cameras, two frames 13 s apart → traffic and flood now; picks the large-road route from A to B (D34) | on |

When a flag is off, the engine behaves as if that source didn't exist.

## How an answer is made

1. **Street graph** around the destination from OSM (the Bình Thạnh demo strip is cached offline; other HCMC addresses are fetched on demand).
2. **Width evidence per alley** keeps source tier separate from width basis and longitudinal coverage (`backend/app/evidence.py`).
3. **Alley Fit** uses decisive physical clear-width evidence for strict routing; parcel-gap or sparse evidence remains unverified (`backend/app/plan.py`, `backend/app/evidence.py`).
4. **Flood over the Dwell Window**: depth evidence from tide, rain and IRD history is evaluated with a separate knowledge status. Missing tide/history and expired positive observations are not treated as dry. The route in is checked over an approximate traversal interval before arrival, the Stop Point over the exact stay, and the Way Out over an approximate traversal interval after departure (`backend/app/plan.py`, `backend/app/flood.py`).
5. **Stop Legality** from Law 36/2024 Art. 18, signs and local lists, always with the citation (`legality.py`).
6. **Filter, then rank** Stop Points by walk time; unverified ones rank last and show grey (`plan.py`).
7. **Large-road route** from the start point: Goong's route and camera-via alternatives, scored by what each route's cameras see now (traffic, standing water) and the flood forecast along it (`corridor.py`, `cameras.py`).

## Data you can add

- `data/field/measurements.csv` and `data/field/egress.csv`: physical clear-width and way-out observations from the field team. Strict-fit evidence needs finite uncertainty and complete endpoint coverage; `pipelines/eval_field.py` freezes a held-out split and scores the planner against them. See `data/field/README.md`.
- `data/official/parcel_gaps.csv`: parcel-gap estimates from the HCMC planning portal (Inferred usable-width basis; official source provenance, not a clear-width measurement).
- `data/flood/tide_forecast.json`: update from each daily bulletin.
- `data/cameras/hcmc_cameras.json`: camera registry; refresh with `python3 pipelines/camera_registry.py`.
- `pipelines/`: VETC lots and Chợ Tốt listing extraction (see `pipelines/README.md`).
