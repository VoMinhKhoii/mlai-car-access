# Ngõ Ngách MCP — an arrival engine any agent can call

Ngõ Ngách turns “can this car reach this alley?” into a sourced arrival decision: a vehicle-specific estimate and confidence, a place to stop, a walking leg, a way out, flood uncertainty and stopping restrictions. Any agent — **T-Maps voice, Xanh SM dispatch**, Claude or a fleet workflow — can call Ngõ Ngách through the same six read-only MCP tools. It runs the arrival engine directly, without an LLM call; evidence gaps remain visible instead of becoming promises of access or permission to park.

Public Streamable HTTP endpoint:

```text
https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

Local production endpoint: `http://127.0.0.1:8787/mcp`. Isolated verification endpoint: `http://127.0.0.1:8797/mcp`. The running public server must reload the changed Python modules before it serves this implementation; see the final verification report in `docs/eval/mcp-final/`. This tunnel URL lasts only as long as its current tunnel process.

## Claude Desktop, Claude Code and Cursor: stdio

The bridge needs Python 3 and a running HTTP backend. It forwards MCP messages to `/mcp`, so both transports get identical schemas, validation, rate limiting and read-only engine behavior. No MCP Python package is required. stdout contains only UTF-8 newline-delimited JSON-RPC.

Use this configuration in Claude Desktop's `claude_desktop_config.json` (macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`), Claude Code's project `.mcp.json`, or Cursor's project `.cursor/mcp.json` / global `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ngo-ngach": {
      "command": "python3",
      "args": ["/Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py"],
      "env": {"VAODUOC_API": "http://127.0.0.1:8787"}
    }
  }
}
```

To use this same stdio bridge against the public HTTP server, change `VAODUOC_API` to `https://concerts-message-concerns-performer.trycloudflare.com` (without `/mcp`). All three clients support this command-based configuration. Restart/reconnect the client's MCP server after changing it.

Claude Code CLI equivalent:

```sh
claude mcp add --transport stdio ngo-ngach-local \
  --env VAODUOC_API=http://127.0.0.1:8787 \
  -- python3 /Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py
```

## Claude Code: native public HTTP

```sh
claude mcp add --transport http ngo-ngach \
  https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

Or use `.mcp.json`:

```json
{
  "mcpServers": {
    "ngo-ngach": {
      "type": "http",
      "url": "https://concerts-message-concerns-performer.trycloudflare.com/mcp"
    }
  }
}
```

For the isolated verification server, the tested command is:

```sh
claude mcp add --transport http ngo-ngach http://127.0.0.1:8797/mcp
```

See [Claude Code's MCP configuration reference](https://code.claude.com/docs/en/mcp).

## Cursor: native public HTTP

Place this in `.cursor/mcp.json` or `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ngo-ngach": {
      "url": "https://concerts-message-concerns-performer.trycloudflare.com/mcp"
    }
  }
}
```

Reconnect the server in Cursor's MCP settings. See [Cursor's MCP documentation](https://cursor.com/docs/context/mcp).

## Claude Desktop: public HTTP

Where remote connectors are available, add a custom connector with the public `/mcp` URL in Settings → Connectors. For a portable JSON configuration, use the Python stdio configuration above with the public `VAODUOC_API`; it bridges to the public HTTP endpoint without an additional proxy package. Desktop's command-based JSON configuration is different from Claude Code's native `"type":"http"` configuration.

## Tools and example calls

Only the six English names below appear in `tools/list`. Existing clients may still call these accepted legacy aliases: `tim_dia_diem` → `find_place`, `lap_ke_hoach` → `plan_arrival`, `kiem_tra_xe_vao_hem` → `check_alley_fit`, `tim_cho_do_gan` → `find_nearby_stops`, `danh_sach_xe` → `list_vehicles`, and `muc_trieu` → `tide_levels`. Aliases receive the same validation and execute the same read-only tool.

Server title: **Ngõ Ngách — alley access for vehicles in HCMC**. Tool descriptions, MCP-generated messages and text content are English. Original place names, source labels and legal citations in structured data are retained verbatim so their provenance remains traceable.

Every tool has English descriptions, an example, a closed object schema and `readOnlyHint: true`. Model aliases such as `Fortuner` normalize to catalogue IDs. Locations use the engine's current HCMC service-area bounds; they are not a surveyed administrative polygon. Coordinates must come from a resolved search result or an explicit user pin.

- `find_place`: search HCMC addresses/POIs; up to three candidates. If `requires_clarification` is true, ask the user to choose before planning. Example arguments: `{"query":"Hẻm 113/4 Võ Duy Ninh, Bình Thạnh"}`.
- `plan_arrival`: full arrival plan, including the canonical engine `verdict.estimate` with confidence/basis, destination `door`, `stop_points`, walking, way out, flood, legality, citations, tiers and caveats. Access and legal status remain separate where the engine supplies them. `Unverified` is not permission; physical fit alone does not authorize stopping.
- `check_alley_fit`: one segment's fit and width evidence, not a whole-trip guarantee. Example arguments: `{"lat":10.792106,"lon":106.716661,"way_id":464839531,"vehicle_id":"Fortuner"}`.
- `find_nearby_stops`: the same arrival arguments as `plan_arrival`, but only nearby stopping alternatives and their checks; no destination-door or standard-route payload.
- `list_vehicles`: vehicle models and size classes XS–XL with metre dimensions. Example arguments: `{}`. `source_ref` indexes `sources`; `defaults` supplies omitted model/estimated-mirror flags. Size classes use conservative envelopes. Alley clearance still requires evidence.
- `tide_levels`: tide extrema, published alarm thresholds, source and missing-point count; at most 36 hours. Example arguments: `{"start":"2026-10-17T12:00:00+07:00","hours":24}`. Missing coverage is unknown, not a zero tide or flood-free street.

Full plan / nearby-stop example arguments:

```json
{
  "lat": 10.792106,
  "lon": 106.716661,
  "label": "Hẻm 113/4 Võ Duy Ninh, Bình Thạnh",
  "vehicle_id": "toyota-fortuner",
  "arrive_at": "2026-10-17T18:00:00+07:00",
  "dwell_min": 120,
  "intent": "park",
  "rain_mm_per_h": 0
}
```

Use `intent: "pickup"` for passenger pickup/drop-off. Timestamps require an explicit timezone (normally `+07:00`); years 2000–2100, dwell 1–2160 minutes and rain 0–300 mm/h are accepted. A historical timestamp is allowed for replay, but never extends the forecast source's coverage.

Tool calls return both `structuredContent` and a short text summary. The **entire serialized tool-call response stays below about 24 KB (UTF-8)**, including the JSON-RPC envelope. The engine's GeoJSON, route coordinates and edge arrays are excluded. The best stopping alternative is retained first; duplicate evidence and extra alternatives may be omitted with explicit counts. Every returned legal rule/citation, estimate confidence and safety caveat remains. If those cannot fit, the tool returns an explicit error rather than removing safety information. Width evidence exposes its tier, source, URL, width basis and clearance status. Detailed map geometry remains available through the web UI, outside MCP.

## Protocol and safety contract

Implemented against the [stable MCP 2025-11-25 Streamable HTTP transport](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports) and [tools contract](https://modelcontextprotocol.io/specification/2025-11-25/server/tools):

- `POST /mcp`: single JSON-RPC request, notification or client response. `initialize` negotiates 2025-11-25, 2025-06-18 or 2025-03-26; unknown proposals get the latest supported version. `serverInfo.name` is `ngo-ngach`; capability is tools only. `ping`, `tools/list` and `tools/call` are implemented.
- `notifications/initialized` and other notifications return HTTP 202 with an empty body. JSON-RPC parse, invalid request, method-not-found, invalid-params and internal errors use their standard codes. Tool execution/source failures use `isError: true` plus text and structured content; transport exceptions are never exposed.
- Stateless JSON response mode: no server-issued `Mcp-Session-Id`, no session requirement or session store. A valid client-supplied ID is ignored and never echoed; malformed IDs get 400. This is the spec's optional-session mode. `GET /mcp` and `DELETE /mcp` return 405 with `Allow: POST`; no server-initiated SSE is advertised.
- Clients send `Content-Type: application/json` and `Accept: application/json, text/event-stream`. Subsequent requests send `MCP-Protocol-Version`; missing headers fall back to 2025-03-26, unsupported values get 400. Request bodies are capped at 64 KB, including chunked bodies.
- Every connection validates a supplied `Origin` against explicit loopback/public origins plus comma-separated `MCP_ALLOWED_ORIGINS`. Absent Origin is allowed for native clients; an invalid Origin gets 403. Optional `MCP_AUTH_TOKEN` requires a bearer token; the bridge reads it from its environment. Secrets never belong in committed configs.
- `/mcp` permits 60 requests/minute per resolved client IP, with 429/`Retry-After: 60`. The in-process limiter has bounded memory and does not read caller-supplied forwarded headers. Run one backend worker; configure ASGI trusted proxies narrowly when deployed behind a proxy.
- MCP cannot write reports, change flags, call the model, invoke paid Google endpoints, launch an area build or start a crawl. An OSM cache miss returns `area_not_cached` before calling the plan engine. It can read existing evidence, geocode through the configured resolver, and use ordinary engine source readers. Goong geocoding/directions remain ordinary provider calls in a normal non-cached server; verification used cached-only mode and made zero Goong calls.
- The existing bounded engine worker gate limits concurrency and waits to at most 40 seconds (`AGENT_TOOL_TIMEOUT` can lower this). Timed-out Python threads continue until their work exits and retain their admission slot; they cannot accumulate without bound.

The conversational `/api/agent` and legacy `/api/agent/tool/*` adapters are separate interfaces; the stdio bridge intentionally uses `/mcp` so it cannot bypass the MCP read-only boundary.

## Inspector and offline tests

Both commands below launch the official MCP Inspector CLI. No GUI or additional Python dependency is needed:

```sh
npx -y @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8797/mcp --transport http --method tools/list

npx -y @modelcontextprotocol/inspector --cli \
  -e VAODUOC_API=http://127.0.0.1:8797 \
  python3 /Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py \
  --method tools/list
```

For a plan call on either transport, replace `--method tools/list` with:

```sh
--method tools/call --tool-name plan_arrival \
  --tool-arg lat=10.792106 --tool-arg lon=106.716661 \
  --tool-arg 'label=Hẻm 113/4 Võ Duy Ninh' \
  --tool-arg vehicle_id=toyota-fortuner \
  --tool-arg arrive_at=2026-10-17T18:00:00+07:00 \
  --tool-arg dwell_min=120 --tool-arg intent=park
```

Offline protocol/tool tests:

```sh
PYTHONPATH=backend NGONGACH_CACHED_ONLY=1 AGENT_ALLOW_PAID=0 \
  python3 -m pytest backend/tests/test_mcp*.py -q
```

Verification artifacts and deployment notes: [MCP final report](../docs/eval/mcp-final/report.md). The public :8787 process was not restarted during verification.

English interface follow-up: [current tests and Inspector proof](verification/english-followup.md). Earlier proof artifacts in the final report document the previous primary names.
