# Field kit implementation report

Implemented teammate measurements, Arrival Confirmation, anonymous crowd collection, moderation and QR stage, using a separate Vite entry and a field-only FastAPI app. No Gemini or cadastral portal calls were made. No cloudflared tunnel was started. Implementation did not run git commit; concurrent repository work advanced HEAD during this task, including files already written here. No concurrent commits were reverted.

## Files authored / integrated

- Backend: `backend/app/field_routes.py`, `field_server.py`, `field_evidence.py`, `crowd.py`, `crowd_routes.py`.
- Shared hooks only: `backend/app/main.py` (one router inclusion), `backend/app/evidence.py` (delimited field load, cross-process refresh, crowd load and disagreement hooks; existing fusion untouched).
- Frontend: `frontend/field.html`, `frontend/vite.config.ts` (second build entry), `frontend/public/field-sw.js`, `frontend/src/field/{main.tsx,storage.ts,ArrivalConfirmation.tsx,arrival.css,field.css,Crowd.tsx,Review.tsx,Stage.tsx,MiniMap.tsx}`.
- Tests: `backend/tests/test_field_kit.py`, `backend/tests/test_crowd_field.py`.
- Docs/dependencies: `docs/field-kit.md`, `PRODUCT.md`, `requirements.txt` (qrcode).
- QA: `docs/eval/field-*.txt`, `field-e2e.json`, `field-browser.json`, and mobile/stage PNGs.

Did not edit `plan.py`, `legality.py`, `agent.py`, `frontend/src/App.tsx`, `Result.tsx` or `Agent.tsx`. Production `data/field/measurements.csv` still has its original seven-column header and no fabricated rows. The first real write extends the schema compatibly.

## Verification

- 12 field integration tests passed, including authenticated endpoints, validation, original photo bytes + GPS EXIF, atomic concurrent CSV append, deduplication, confirmation bounds, independent-process hot reload, and actual `/api/plan` returning Measured 2.3–2.5 m after a synthetic 2.4 m submission for queue Way 610102928. Temporary data only; sockets blocked in the plan E2E.
- 12 crowd tests passed, including signed cookies/no login, required photo/GPS/attestation, 0.8–12 m, no pacing, IP and device hourly limits, lifetime per-way cap, PENDING isolation, consensus, moderation, revocation, Official by Way ID and alley name, conflict hull + REVIEW, EXIF removal, QR/counter privacy.
- 6 existing width regression tests passed.
- `npm --prefix frontend run build` passed. Vite retains the pre-existing main-bundle size warning.
- Mobile Chromium viewport 390×844: crowd GPS/snap/map/photo/PENDING/review/stage flow; teammate offline localStorage retry and quota-failure form retention; arrival prompt. No horizontal overflow. Synthetic GPS and photo, isolated temporary browser server storage. Actual iPhone Safari / Android hardware GPS/camera remain to be checked on the field trip.

## Run (prepared, tunnel not executed)

```sh
cd /Users/khoivo/Developer/mlai-car-access
npm --prefix frontend run build
export FIELD_TOKEN='replace-with-long-random-team-secret'
export FIELD_TRUST_CLOUDFLARED=1
python3 -m uvicorn app.field_server:app --app-dir backend --host 127.0.0.1 --port 8790
```

Only when the operator decides to expose it, in a second terminal:

```sh
cloudflared tunnel --url http://127.0.0.1:8790
```

Keep the tunnel running; restart only the field server in its original terminal after setting the returned URL:

```sh
export FIELD_PUBLIC_URL='https://ACTUAL-URL.trycloudflare.com'
python3 -m uvicorn app.field_server:app --app-dir backend --host 127.0.0.1 --port 8790
```

Routes: `/field`, `/field?crowd=1`, `/field/review`, `/field/qr`. Team APIs and review use FIELD_TOKEN; crowd collection is anonymous. Stage QR contains the public crowd URL without a token. The separate field server has no AI/agent/admin/planning endpoints.

Consensus additionally requires different IPs and different sanitized photos. Shared venue Wi-Fi goes to teammate review. Signed browser cookies are practical device identifiers, not hardware identity. Pending submissions do not affect Measured evidence; accepted crowd points never certify whole-way coverage. Crowd metadata is stripped except GPS/time; teammate original photos retain EXIF per the initial brief.

Full Vietnamese setup, safety, measurement, privacy and main-app ArrivalConfirmation mounting instructions: `docs/field-kit.md`.
