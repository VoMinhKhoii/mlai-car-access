# Agent C — MCP finalisation report

Completed 17 October 2026, 10:45 Asia/Ho_Chi_Minh, before the 12:15 time box. Branch `hackathon-night-2026-10-17`, starting HEAD `8775ef4`. Changes are uncommitted; no push. The public :8787 server and tunnel were not restarted.

## Compliance checklist

- [x] Stable [MCP 2025-11-25 Streamable HTTP](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports), also negotiating 2025-06-18 and 2025-03-26. `serverInfo.name = ngo-ngach`, tools capability, `initialize`, initialized notification, `ping`, `tools/list`, `tools/call`.
- [x] JSON responses; notification/client-response acknowledgement is 202/empty. GET and DELETE are 405, `Allow: POST`. Parse/invalid-request/method/parameter/internal JSON-RPC errors have standard codes; source/execution errors have `isError`, text and `structuredContent`.
- [x] Stateless session mode, allowed by the transport specification: no session issued or required; valid `Mcp-Session-Id` supplied by a client is ignored without reflection, malformed IDs are rejected. No stateful-session or server-initiated SSE support is claimed.
- [x] Origin validation on every `/mcp` method, optional bearer authentication, strict media/version headers, bounded request-body reads and 60 requests/minute per resolved client IP. Limiter state is loaded once and memory is bounded.
- [x] Six tools with Vietnamese/English descriptions, examples, closed schemas and read-only annotations. Finite HCMC service-area coordinates, timestamp/timezone/year, positive bounded dwell, rain, query length and way-ID checks run before execution.
- [x] Dedicated read-only engine boundary; stdio forwards to that same `/mcp` endpoint. No agent model loop, paid Google endpoint, write tool, area build or crawl. Cache misses fail before planning. No paid or free Gemini calls were made by this task.
- [x] Compact engine projections: no GeoJSON/route coordinate arrays; full canonical top-level verdict estimate, confidence, basis and source references; stop/door checks, walking, exit, flood, all returned legal rules/citations, evidence tiers and caveats. Extra alternatives/evidence have explicit omission counts. Oversized safety-critical results fail explicitly rather than dropping safety checks. Every verified tool response was below 8,000 UTF-8 bytes including its JSON-RPC envelope.
- [x] Read the merged engine's live output after concurrent engine changes: the current estimate includes `coverage`, `limiting_width` and `stop_width`. Preserve these at `verdict.estimate`; per-stop projections omit duplicate width/coverage details. The access-versus-legality synthetic regression preserves `estimate.access_answer`, `legal_status` and actual legal rules independently. The actual current engine still emitted `answer`/confidence/basis plus separate `legality` in the verified plan; MCP does not invent an access pass or legal permission.
- [x] Claude Desktop, Claude Code and Cursor stdio/public HTTP setup, all six example calls, tool contract, limits and the “any agent — T-Maps voice, Xanh SM dispatch” pitch are in `mcp/README.md`.

The HCMC location gate follows the engine's service-area bounding box, not an administrative polygon. `Unverified` legality remains unverified, and unknown exit/flood remains unknown.

## Real-client proof

The official Inspector package was available online this time (`@modelcontextprotocol/inspector` 1.0.2). Its CLI emitted a deprecation notice recommending its latest major; all four requested operations succeeded. Raw stdout and stderr are retained separately:

- HTTP `tools/list`: all six tools, `inspector-http-list.json`.
- HTTP `tools/call lap_ke_hoach`: `isError: false`, `inspector-http-plan.json`.
- Stdio `tools/list`: all six tools, `inspector-stdio-list.json`.
- Stdio `tools/call lap_ke_hoach`: `isError: false`, `inspector-stdio-plan.json`.

Both plan calls used Hẻm 113/4 Võ Duy Ninh, coordinates 10.792106 / 106.716661, `toyota-fortuner`, 2026-10-17 18:00 +07:00, park 120 minutes. Both returned `verdict.estimate.answer = tight`, `confidence = low`, overall `code = unverified`, and one retained nearby stop. That alternative is on Đường Võ Duy Ninh, walking 39 m; legality is `Unverified`. The destination-door estimate is `unknown`. These are estimates with caveats, not a certified legal stopping recommendation.

Commands:

```sh
npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8797/mcp --transport http --method tools/list

npx -y @modelcontextprotocol/inspector --cli \
  -e VAODUOC_API=http://127.0.0.1:8797 \
  python3 /Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py \
  --method tools/list
```

For each transport, the successful plan invocation replaced `--method tools/list` with:

```sh
--method tools/call --tool-name lap_ke_hoach \
  --tool-arg lat=10.792106 --tool-arg lon=106.716661 \
  --tool-arg 'label=Hẻm 113/4 Võ Duy Ninh' \
  --tool-arg vehicle_id=toyota-fortuner \
  --tool-arg arrive_at=2026-10-17T18:00:00+07:00 \
  --tool-arg dwell_min=120 --tool-arg intent=park
```

Claude Code setup succeeded with the exact requested command:

```sh
claude mcp add --transport http ngo-ngach http://127.0.0.1:8797/mcp
```

This added a **local project entry in `~/.claude.json`**, pointing to the isolated server. `claude-add.txt` records it. A non-interactive `claude -p` then emitted exactly one `tool_use` for `mcp__ngo-ngach__lap_ke_hoach`, a successful tool result and a final answer reporting `tight` / `low` with the lack of measured route widths and unverified legality. `claude-proof.json` is the concise evidence; `claude-plan.ndjson` retains the actual client events. The CLI used its own configured Claude model; the MCP server made no LLM call.

An earlier Claude attempt overlapped the private server reload and failed with `ECONNREFUSED`; it is retained as `claude-plan-first-attempt.json` and is not counted as successful proof. The final attempt was successful.

Raw HTTP checks (`http-proof.json`) additionally measured these full response sizes:

- `tools/list`: 6,205 bytes.
- `lap_ke_hoach`: 7,607 bytes, `isError: false`.
- `tim_cho_do_gan`: 4,912 bytes, `isError: false`.
- `kiem_tra_xe_vao_hem`: 1,492 bytes, `isError: false`.
- `danh_sach_xe`: 7,758 bytes, `isError: false`.
- `muc_trieu`: 1,210 bytes, `isError: false`.

These are point-in-time outputs from the copied engine evidence. The real search tool was not used for client proof because the geocoder startup/index issue below is owned by Agent A; search filtering and dispatch are covered offline.

## Isolation, tests and cost

Verification used separate copies of `backend/store`, `backend/cache` and `backend/flags.json` under `/tmp/ngo-ngach-mcp-mr5teh4k`. No hard links or shared mutable store with :8787. The running private server is PID 46687 on `127.0.0.1:8797`, with:

```sh
VAODUOC_STORE=/tmp/ngo-ngach-mcp-mr5teh4k/store \
VAODUOC_CACHE=/tmp/ngo-ngach-mcp-mr5teh4k/cache \
VAODUOC_FLAGS=/tmp/ngo-ngach-mcp-mr5teh4k/flags.json \
NGONGACH_CACHED_ONLY=1 AGENT_ALLOW_PAID=0 AGENT_FREE_CALL_LIMIT=0 \
python3 -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8797 --workers 1 --no-proxy-headers --lifespan off
```

**Normal startup is currently blocked by a concurrent, out-of-ownership geocoder change:** `geocoding.initialize_name_index()` raises `KeyError: 20675274` at `backend/app/geocoding.py:214`. A named non-way/non-node OSM object reaches the node-only `nodes[e['id']]` branch. Agent A should restrict the object types or skip objects without a corresponding node. I did not edit Agent A's file. The first HTTP discovery proof ran with normal lifespan before this change; final client proof used `--lifespan off` to test the real HTTP/engine implementation independently of that startup failure. No synthetic plan or mocked live engine response was substituted.

Cached-only verification prevents upstream OSM/Goong/hydrology requests; **Goong calls: 0 of the allowed 30. Gemini calls: 0. Paid Google calls: 0.** Offline tests block external HTTP GETs and mock source/engine boundaries. `tests.txt` records **35 passing tests**: 34 MCP cases plus the existing raw HTTP MCP regression in `test_agent_production.py`. Coverage includes all six adapters, protocol errors, negotiation, notification/response semantics, session headers, Origin/media/auth validation, rate limiting, numerical/timestamp bounds, cache-miss refusal, secret-safe errors, source tiers/legal citations/access separation, real merged engine projection and the complete 8 KB response budget. Two existing dependency deprecation/version warnings remain. Compile checks and scoped `git diff --check` pass. Proof artifacts were scanned against configured credential values without printing them; no matches.

## Files changed by Agent C

- `mcp/protocol.py` — JSON-RPC/schema validation, safe tool result envelopes, rate limiter.
- `mcp/server.py` — six-tool catalogue, guarded read-only engine execution, compact projections.
- `mcp/vaoduoc_mcp.py` — UTF-8 stdio-to-HTTP bridge, sanitized transport errors.
- `mcp/testdata/arrival_plan.json` — current engine regression fixture, without map geometry.
- `mcp/README.md` — client configurations, pitch, contracts, examples and verification commands.
- `backend/app/main.py` — delimited MCP route block plus the single middleware exception that lets `/mcp` perform its own Origin allowlisting. Legacy `/api/agent/tool/*` endpoints were not changed.
- `backend/tests/test_mcp_protocol.py` — offline protocol/tool/safety regressions.
- `docs/eval/mcp-final/*` — this report and named proof/test artifacts.

Other dirty files in the shared workspace belong to the other agents and were not edited by Agent C. No commit/push was made.

## Deployment handoff: public :8787 must reload

The existing public process still has the old Python modules loaded. Do not start a second backend on its store. After Agent A fixes the startup issue and the team intentionally stops/replaces the existing :8787 process, run from the repo root with the **same existing production environment and VAODUOC paths**:

```sh
AGENT_ALLOW_PAID=0 python3 -m uvicorn app.main:app --app-dir backend \
  --host 127.0.0.1 --port 8787 --workers 1
```

Do not copy the verification `--lifespan off` workaround into production; normal lifespan initializes the geocoder and tide refresh. Keep the existing tunnel running or repoint its replacement to :8787 as usual. I did not execute this deployment command or modify the tunnel. Once reloaded, the documented public URL will serve the new MCP implementation.
