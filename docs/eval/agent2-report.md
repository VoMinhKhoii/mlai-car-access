# Agent round 2 verification, 16/10/2026

Implemented without a commit. Uvicorn is running on :8787 with `AGENT_ALLOW_PAID=0`; the temporary test-only free-call ceiling has been removed from the server launcher. `frontend/dist` is rebuilt. No city-crawl process was restarted, and this round did not edit `pipelines/crawl_city.py`, `backend/app/live.py`, city parcel data/logs, or `docs/decision-log.md`. Pre-existing workspace changes were preserved.

## Demo outcome

`tim_dia_diem` now checks the curated house-end point for **Hẻm 113/4 Võ Duy Ninh, Bình Thạnh**, lat **10.792106**, lon **106.716661**, before presets or search. This is the end of way 464839531 near the houses, not the mouth on Ngô Tất Tố.

The engine returns:

- Toyota Fortuner: **Đỗ tại Ngô Tất Tố, đi bộ 300 m (~4 phút)**.
- Toyota Vios: **Đỗ tại Ngô Tất Tố, đi bộ 300 m (~4 phút)**.
- VinFast VF 3: **Xe vào tận cửa được**, 0 m walking, Official cadastral width **6.97–7.27 m**.

Live browser requests to `POST /api/agent` verified Fortuner followed by “Còn xe VF 3 của vợ tôi thì sao?”. The follow-up kept the coordinates, arrival time (16/10 23:16 +07:00), 120-minute stay and park intent, changed only the vehicle, and updated the map/vehicle selector. Both final requests used the updated official tide data and source metadata. Raw streams: `agent2-fortuner.ndjson`, `agent2-vf3.ndjson`; request bodies are saved beside them.

## Both live answers, verbatim

### Fortuner

Xe Toyota Fortuner không nên chạy vào tận cửa hẻm do không có đường ra phù hợp khi rời đi (hẻm cụt hoặc ngập lúc về). 

Bạn nên đỗ xe tại đường Ngô Tất Tố (theo dữ liệu OSM phân loại đường), sau đó đi bộ khoảng 300 m (mất khoảng 4 phút) vào Hẻm 113/4 Võ Duy Ninh.

### VF 3 follow-up

Xe VinFast VF 3 có thể vào và đỗ ngay trước cửa Hẻm 113/4 Võ Duy Ninh (đi bộ 0 m). 

Theo dữ liệu từ Cổng thông tin quy hoạch TP.HCM (thửa đất hai bên hẻm), khu vực trước nhà rộng khoảng 7,0 m, đủ không gian cho xe quay đầu tại chỗ khi ra về.

## Tide path: official forecast, no harmonic fallback

Numerical source: [Đài KTTV Nam Bộ, Bản tin dự báo đặc trưng thủy triều 5 ngày, số 289/2026](https://kttvnb.vn/attachments/article/29368/HCMC_TVHN_20261016.pdf), issued **2026-10-16 09:08 +07:00**. This is Phú An on the Sài Gòn river. [Bulletin 138-SG, issued 09:00 on 16/10](https://kttvnb.vn/attachments/article/29367/HOCM_TBTC_20261016_0900.pdf) corroborates that the tide is falling; it is not the numerical five-day source.

Official source PDFs, extracted text and SHA-256 hashes are archived under `data/flood/snapshots-2026-10-16/`. Public downloads required a local certificate-verification override because the official site's TLS certificate was expired. Application and Gemini TLS verification were not changed.

Copied all **23** published Phú An extrema: four observations on 15/10 and 19 forecast extrema on 16–20/10. The last published value is the low at **18:00 on 20/10**; later hours return missing data. The `ct` high on 18/10 is omitted. Original JSON fields are retained; an optional `lows` array adds the actual, unequal official lows. `flood.py` accepts it and still supports legacy highs plus a scalar low. Between published points the app uses cosine interpolation, explicitly qualified in the file note and visible UI source line. The curve is not an official continuous forecast or street-level flood observation.

Validation: all 23 extrema reproduced, RMS difference **8.35e-17 m** (floating-point zero), peak timing reproduction error **0 minutes**. These are transcription/interpolation checks, not forecast-skill estimates. **Held-out RMSE/peak error: not applicable**, because no harmonic model was fitted. Details: `agent2-tide-validation.json` and `agent2-tide-schema.json`.

### Hẻm 220/9, Vios, 17/10/2026

At **16:30–18:30**, interpolated Phú An levels are **-1.18 m → -0.14 m**, neither reaches BĐI. The engine returns **no timing warning** (`timing: null`), with the existing 53 m walking recommendation at Hẻm 294/22 Đường Xô Viết Nghệ Tĩnh. Its door rejection remains the way-out limitation; the tide is not an additional failure for this window.

There is **no dramatic tide-warning window anywhere on 17/10** under this official forecast. All 96 quarter-hour arrival windows of 120 minutes pass the tide timing check. The day's highest tide is **1.20 m at 22:00**, below BĐI **1.40 m** (and BĐII 1.50/BĐIII 1.60). Chip (c) was changed to **20:00** so the stay includes that peak: **0.70 m → 1.20 m**, still `timing: null`. The official data cannot support a trapped-by-tide demo on that date. No thresholds or levels were inflated to force it.

Exact chip (c): `Vios tới Hẻm 220/9 Xô Viết Nghệ Tĩnh lúc 20:00, ở 2 tiếng`. Like the requested chip, it uses today's date when no day is spoken. For an explicit rehearsal of demo day, specify `ngày 17/10/2026` in the question. Evidence: `agent2-tide-220.json` and `agent2-tide-validation.json`.

## Files changed in this round

| File(s) | Before | After |
| --- | --- | --- |
| `frontend/index.html`, `frontend/src/App.tsx` | Vào Được / VĐ | Ngõ Ngách / NN in title, metadata, header, boot, welcome and VETC panel; tagline retained |
| `frontend/src/components/Agent.tsx` | Trợ lý Vào Được, old chips and baseline labels; blank trace before first event | AlleyAI button/title/answer label, requested comparison/baseline wording, four ordered chips, immediate “Hiểu câu hỏi” row; old turns do not animate during a new run |
| `frontend/src/components/Agent.css` | Small chip targets and empty argument gaps | 40 px chip targets, tabular step numbers, no empty argument gap |
| `backend/app/agent.py` | Generic resolver and self-name; deadline could be omitted; exhausted keys retried each round | Curated endpoint, AlleyAI/Ngõ Ngách prompt, verdict priority, official tide provenance, exact leave-before safeguard in answer and history, successful free-key preference |
| `backend/app/main.py` | Old public API title/errors | Ngõ Ngách public API title/errors; other edits preserved |
| `mcp/vaoduoc_mcp.py`, `mcp/README.md` | Old server display name and documentation | Ngõ Ngách server name/description/errors and setup documentation; filenames, API paths and environment variable names retained |
| `data/flood/tide_forecast.json`, `backend/app/flood.py` | Late-September highs with invented constant lows | Official October extrema with actual lows, bounded interpolation and honest provenance |
| `frontend/src/components/TideTimeline.tsx`, `frontend/src/index.css` | Unattributed curve | Linked bulletin source and interpolation qualification beneath timeline header |
| `backend/tests/test_agent2.py` | No round-two regression coverage | Five offline regressions: curated resolver precedence, extrema/bounds, all-day no-false-warning check, omitted-deadline repair/history, successful free-key reuse |
| `data/flood/snapshots-2026-10-16/*`, `docs/eval/agent2-*` | No round-two evidence | Archived official sources, raw requests/streams, engine/tide evidence, budget/build/lint/test logs, screenshots and this report |
| `frontend/dist` (ignored/generated) | Prior build | Final TypeScript/Vite build |

Code identifiers, filenames, API paths and decision-log content were not renamed. `backend/app/agent_budget.py` and the prior test suite were not edited this round.

## Checks and cost

- **11 backend tests pass**, offline, including the six previous guard/history/baseline tests.
- `npm run build` passes; `frontend/dist` rebuilt. Existing large-bundle warning remains.
- `npm run lint` exits 0 with existing warnings in Directions, Result and ds/ui; no new Agent/TideTimeline warning.
- `git diff --check` passes.
- MCP initialize, curated place lookup and 24-hour tide query pass; tide query has **0 missing points** on 17/10 and returns the official source URL.
- Exact leave-before safeguard verified offline with a model response that omits **17:45**: both visible answer and follow-up history contain `rời trước 17:45`. This official five-day forecast has no real tide deadline to exercise that branch live.
- Browser: real Fortuner → VF 3 `POST /api/agent` flow, immediate progress row, vehicle/map update, no visible app error, no horizontal overflow at desktop width. No further model requests were made after the successful follow-up.
- Gemini ledger **41 → 74** free attempts: **33 free attempts**, including failed-key retries and the earlier Fortuner run; **0 paid calls**, **$0.00**. Paid access remained disabled. A temporary server-only ceiling prevented exceeding 39 test attempts; it has been removed, and the final normal uvicorn process still uses `AGENT_ALLOW_PAID=0`. Budget evidence: `agent2-budget.json`.

## Screenshots

- `docs/eval/agent2-mid-run.png`: first “Hiểu câu hỏi” row before any tool event, desktop 1440 × 1000.
- `docs/eval/agent2-fortuner.png`: final Fortuner recommendation and trace, 1440 × 1000.
- `docs/eval/agent2-vf3-mid-run.png`: follow-up while running, 1440 × 1000.
- `docs/eval/agent2-vf3.png`: completed VF 3 follow-up with updated map/selector, 1440 × 1000.
- `docs/eval/agent2-full-flow.png`: entire real two-turn conversation, trace, final map and source attribution together, 1440 × 1600.

The browser viewport is restored to 1440 × 1000. Screenshot PNGs are scaled by the preview tool while preserving the desktop layout.
