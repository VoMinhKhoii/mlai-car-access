# Ngõ Ngách MCP

Six Vietnamese/English tools share the web agent's validated adapters and arrival engine:

- `tim_dia_diem`: Goong → local OSM alley names → Nominatim. Multiple matches require clarification, or disclose selection nearest an explicit origin. An unresolved house branch is never replaced silently with a street centroid.
- `lap_ke_hoach`: arrival/exit, width evidence, flood window, legal stop points and walking legs.
- `kiem_tra_xe_vao_hem`: one OSM way's vehicle fit and evidence list. Does **not** certify the entire route, flood, exit or stopping legality.
- `tim_cho_do_gan`: nearby stop points only (park or pickup); no full route/door payload.
- `danh_sach_xe`: models/classes, physical limits, source URLs and conservative assumptions.
- `muc_trieu`: official bulletin extrema, bounded to the published forecast window.

Run the API (no MCP package/new Python dependencies):

```sh
cd /Users/khoivo/Developer/mlai-car-access
AGENT_ALLOW_PAID=0 python3 -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8787
```

## Claude Desktop / Claude Code: stdio

Put this in `claude_desktop_config.json` (Desktop) or `.mcp.json` (Code):

```json
{
  "mcpServers": {
    "ngo-ngach": {
      "command": "python3",
      "args": ["/Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py"],
      "env": { "VAODUOC_API": "http://127.0.0.1:8787" }
    }
  }
}
```

The stdio bridge uses only Python's standard library. stdout contains newline-delimited JSON-RPC only; importing the module doesn't start reading stdin.

## Streamable HTTP

URL: **http://127.0.0.1:8787/mcp** (replace the host with your FastAPI deployment URL). The repo’s existing Vercel configuration only rewrites `/api/*`; that deployment also needs an explicit `/mcp` → `/api/index` rewrite, which is outside this task’s file ownership.
Claude Code `.mcp.json`:

```json
{
  "mcpServers": {
    "ngo-ngach": {
      "type": "http",
      "url": "http://127.0.0.1:8787/mcp"
    }
  }
}
```

Or: `claude mcp add --transport http ngo-ngach http://127.0.0.1:8787/mcp`.
Desktop can use the stdio configuration above; remote connector configuration uses this same HTTPS endpoint where supported.

Implemented against the [stable 2025-11-25 transport spec](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports): stateless JSON response mode, protocol negotiation, request IDs, tool error results, 202 empty responses for notifications, 405 for GET/DELETE (no unsolicited SSE or sessions), JSON-RPC parse/invalid params/unknown method errors. Also supports HTTP protocol versions 2025-03-26 and 2025-06-18; stdio additionally supports 2024-11-05. Newer/draft protocol versions are not advertised.

```sh
curl -s http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
curl -s http://127.0.0.1:8787/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"danh_sach_xe","arguments":{}}}'
```

Origin headers are checked against loopback app/dev origins. Set `MCP_ALLOWED_ORIGINS` to an explicit comma-separated list of deployed frontend/Inspector origins. If `MCP_AUTH_TOKEN` is configured, HTTP clients must send `Authorization: Bearer …`; configure authentication before exposing an unrestricted public endpoint. Transport only: no Gemini call or model fee is incurred by MCP itself. Each tool has a bounded wait (default 40 s, `AGENT_TOOL_TIMEOUT`). A timed-out engine thread cannot be killed safely by Python; admission is capped at eight workers until existing work finishes.

Nominatim requests are cached, serialized and spaced at least one second apart **per process**. Multi-worker public deployments need a shared resolver/rate limiter. Current service evidence covers the pre-merger HCMC urban area; the engine's bounding-box check is not an administrative polygon.

## Web agent budget and recovery

The web agent uses free `GEMINI_API_KEY*` keys only by default, rotating on 429/403/503, cooling down rejected keys. `AGENT_FREE_MODEL` defaults to `gemini-2.5-flash` because the previous 3.5 alias's daily quota was exhausted during this evaluation. The model is configurable without changing tool behavior. Recognizable driver requests fall back conservatively to the same tools when free quota is exhausted; unfamiliar requests ask for clarification.

`AGENT_ALLOW_PAID=0` remains the default. Paid fallback uses `PROD_GEMINI_API_KEY` only with an explicit `AGENT_ALLOW_PAID=1`; the tool-free comparison never uses it. Ledger: `backend/store/gemini_paid_usage.json`; `/api/budget` exposes counters and reservations. `AGENT_FREE_CALL_LIMIT` is an absolute ledger ceiling, and `AGENT_PAID_LIMIT_USD` can lower the default $3 paid cap. Reservation rates are conservative bounds ($1.50/M input, $9/M output including thinking), not a billing invoice; rejected requests release reservations at $0. Paid calls default to Vertex express mode (`https://aiplatform.googleapis.com/v1/publishers/google/models/gemini-3.5-flash:generateContent`); `AGENT_PAID_ENDPOINT` can override the complete URL. Free calls remain on AI Studio. A daily project-quota response stops rotation across all free keys and persists a cooldown in the shared ledger until the next midnight in `America/Los_Angeles`, including DST. A local free-call ceiling also permits the opt-in paid fallback. See [Vertex fix and smoke evidence](../docs/eval/agent-vertex-report.md) for the successful plain inference and the incomplete function-calling smoke.

The web panel persists conversations locally, supports stop/cancel and retry, and opens the existing EvidencePanel from source chips. Stop aborts the reader and sends `/api/agent/cancel/{request_id}`; it prevents subsequent model/tool rounds, but cannot retract a provider request already in flight.

Validation artifacts: `docs/eval/agent-mcp-http-proof.json`, `agent-mcp-stdio-proof.ndjson`, `agent-mcp-inspector.txt`, `agent-production-report.md`. The offline Inspector attempt was unavailable (`ENOTCACHED`); raw HTTP/stdio and automated protocol tests provide the protocol evidence.
