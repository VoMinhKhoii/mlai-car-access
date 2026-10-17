# Demo geocoder fix — 17 October 2026

Uncommitted. The API and agent now share `backend/app/geocoding.py`, extracted from the agent resolver. API fallback order: Goong (3-second total lookup budget) → curated demo addresses/HUTECH → citywide cached OSM names → Nominatim. The agent keeps its existing offline-first curated-address behavior. House-number and ambiguity checks remain in the shared resolver.

- All search results have coordinates and a source; no follow-up place request is needed.
- Startup indexes all 2,770 current OSM JSON files (including the cached cells and demo data): 50,394 named ways/places, about 15.8 MB on disk. Subsequent starts load the index after checking the cache-file manifest. No Overpass download or area-graph build is needed for search.
- `backend/store/geocoding.sqlite` stores successful Goong autocomplete/detail/reverse responses, resolved query results, Nominatim results, and a shared 30-minute Goong quota breaker. Query locations are rounded to 0.001° for Goong cache keys. Successful cached results remain usable while the breaker is open.
- HTTP 429 or `OVER_RATE_LIMIT` opens/logs the persisted breaker across API search/place/reverse and the agent geocoder. It is already seeded from the exhausted quota reported for this demo; no probe is needed.
- Nominatim search uses an HCMC-bounded viewbox, application User-Agent, disk cache, and shared ≥1.05-second request spacing for search/reverse.
- Reverse falls back to the nearest cached OSM way segment (within 250 m), then Nominatim reverse, then coordinates.
- An old opaque Goong place ID uses cached detail or a local match for its cached autocomplete description. An unknown uncached ID returns HTTP 424 with a retry-search instruction.

## Verification

Final result: **52 tests passed**. All five required searches passed on 8791 (1–129 ms with the local/provider caches warm); HUTECH returns all six campus/facility entries. The market is ranked before its nearby bus stop.

Mocked regression suite (all external Goong/Gemini transports denied by the runner):

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=0 PYTHONPATH=backend:. python3 tmp/run_geocoding_tests.py
```

The normal unittest invocation covers the same five modules:

```sh
AGENT_ALLOW_PAID=0 PYTHONPATH=backend python3 -m unittest \
  backend.tests.test_geocoding backend.tests.test_agent_production \
  backend.tests.test_agent backend.tests.test_agent2 backend.tests.test_agent_vertex
```

Port **8791** was started with the documented demo environment except `AGENT_ALLOW_PAID=0`. Its test-only transport mocks Goong 429 and forbids Gemini. The persistent breaker prevents even mock Goong transport attempts during the HTTP checks. Artifacts:

- `tmp/geocoding-tests.txt`: mocked suite output.
- `tmp/geocoding-8791-results.json`: query results with coordinates, sources, latency, and reverse response.
- `tmp/geocoding-8791-verification.txt`: readable verification output.
- `tmp/geocoding-8791.log`: test server log.
- `tmp/geocoding_demo_server.py`: guarded server wrapper; `tmp/verify_geocoding_8791.py`: HTTP checks.

Required queries: `475A Điện Biên Phủ`, `Hẻm 220/9 Xô Viết Nghệ Tĩnh`, `Hẻm 113/4 Võ Duy Ninh`, `Chợ Bến Thành`, `HUTECH`. Also checks `Tô Ngọc Vân` from the citywide disk index, OSM reverse, repeated searches, and HTTP 424 for an uncached place ID.

**Test incident:** The first regression run made one unintended real Goong request from an existing curated-agent test after the resolver extraction; it returned 429. The agent's original offline-first curated behavior was restored, that regression now explicitly forbids HTTP, and subsequent verification uses an outbound guard. No Gemini request was made.

## Exact restart steps — user runs these

8787 and 8789 were left running with their original PIDs. Run the following only when ready to replace those processes. These commands use the live demo settings from `docs/STATUS-2026-10-17.md` (including paid-agent opt-in); use `AGENT_ALLOW_PAID=0` instead if keeping paid AI disabled.

```sh
cd /Users/khoivo/Developer/mlai-car-access

# Re-arm from the already known quota exhaustion; this makes no HTTP request.
PYTHONPATH=backend python3 - <<'PY'
from app.geocoding import block_goong
block_goong('known exhausted demo quota; manual restart')
PY

for port in 8787 8789; do
  for pid in $(lsof -tiTCP:"$port" -sTCP:LISTEN); do
    kill "$pid"
  done
  while lsof -tiTCP:"$port" -sTCP:LISTEN >/dev/null; do
    sleep 1
  done
  nohup env \
    AGENT_ALLOW_PAID=1 AGENT_PAID_LIMIT_USD=3.00 AGENT_FREE_CALL_LIMIT=0 \
    AGENT_FREE_MODEL=gemini-2.5-flash \
    AGENT_PAID_ENDPOINT=https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.5-flash:generateContent \
    PYTHONPATH=backend \
    python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$port" \
    >"backend/store/api-$port.log" 2>&1 </dev/null &
done
```

Wait for `Application startup complete` in each log (allow the documented 2–3 minutes of warm-up). Check search without calling the agent:

```sh
for port in 8787 8789; do
  curl -fsSG "http://127.0.0.1:$port/api/search" \
    --data-urlencode 'q=475A Điện Biên Phủ'
done
```

The isolated test server can be stopped when finished:

```sh
for pid in $(lsof -tiTCP:8791 -sTCP:LISTEN); do kill "$pid"; done
```
