# Vào Được (working name)

**Xe bạn vào được, và ra được, không?** A T-Maps layer for HCMC that answers, for one specific car, whether it can reach an address in the hẻm network and get back out, given alley geometry, flood evidence during your stay, and parking law. If it can't, the layer says where to stop and how far to walk.

MLAI Hackathon 2026 · Tasco & Goong track.

- Domain language: [`CONTEXT.md`](CONTEXT.md)
- Every decision and why: [`docs/decision-log.md`](docs/decision-log.md)
- Research with sources: [`docs/research/`](docs/research/)

## Run it

```bash
# 1. backend (Python 3.11: fastapi, uvicorn, httpx, python-multipart)
cd backend
uvicorn app.main:app --port 8787

# 2. frontend (Node 22)
cd frontend
npm install
npm run build        # the backend serves frontend/dist at http://localhost:8787
# or, while editing the UI:
npm run dev          # http://localhost:5173, proxies /api to :8787
```

Open http://localhost:8787 and pick a **Kịch bản demo** (demo scenario).

### Keys (all optional; the app degrades gracefully)

Put them in `.env.local` at the repo root (gitignored):

```
GOONG_API_KEY=...        # search, geocoding, Standard Route
GOONG_MAPTILES_KEY=...   # Goong base map (otherwise an open CARTO base map)
GEMINI_API_KEY=...       # or OPENAI_API_KEY / ANTHROPIC_API_KEY, for the AI text/photo/camera features
AI_MODEL=...             # optional model override
```

### AI features: one flag each

Toggle them in the UI footer ("Tính năng AI") or with `FLAG_<NAME>=1|0` env vars; state persists in `backend/flags.json`.

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
2. **Width Range per alley** from Evidence tiers: Measured > Official > Observed > Declared > Inferred (`backend/app/evidence.py`).
3. **Alley Fit for this vehicle** (fits / tight / doesn't fit / unknown) against width including mirrors and margins, plus the turn-in check at alley mouths (`vehicles.py`, `geometry.py`).
4. **Flood over the Dwell Window**: tide forecast (Đài KTTV Nam Bộ bulletin) and rain scenario against each street's IRD history, compared with the car's Safe Water Depth. Route in at arrival, the Stop Point across the stay, the Way Out at departure (`flood.py`).
5. **Stop Legality** from Law 36/2024 Art. 18, signs and local lists, always with the citation (`legality.py`).
6. **Filter, then rank** Stop Points by walk time; unverified ones rank last and show grey (`plan.py`).
7. **Large-road route** from the start point: Goong's route and camera-via alternatives, scored by what each route's cameras see now (traffic, standing water) and the flood forecast along it (`corridor.py`, `cameras.py`).

## Data you can add

- `data/field/measurements.csv`: tape-measured alleys from the field trip (tier Measured). See `data/field/README.md`.
- `data/official/parcel_gaps.csv`: legal widths from the HCMC planning portal (tier Official).
- `data/flood/tide_forecast.json`: update from each daily bulletin.
- `data/cameras/hcmc_cameras.json`: camera registry; refresh with `python3 pipelines/camera_registry.py`.
- `pipelines/`: VETC lots and Chợ Tốt listing extraction (see `pipelines/README.md`).
