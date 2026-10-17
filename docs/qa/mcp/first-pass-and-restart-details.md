# Ngõ Ngách MCP end-to-end QA — 2026-10-17

**Result: FAIL after restart.** The original 429 vehicle-ranking failure is fixed in the restarted process, but both arrival tools now fail with `compact_result_too_large` at 220/9 Xô Viết Nghệ Tĩnh for Fortuner/park. Public and local protocol and real-client smoke tests pass.

First pass was published at **12:59 +07:00**, before the 13:00 deadline. Last report refresh: 13:12:57 +07:00. Monitor remains active through 13:20.

## Scope and execution

- Endpoints: `http://127.0.0.1:8787/mcp` and `https://concerts-message-concerns-performer.trycloudflare.com/mcp`.
- Bridge: `python3 /Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py`, with `VAODUOC_API` set to the backend base URL.
- Repo code was read-only. QA scripts, npm cache, isolated client state and evidence were written only under `docs/qa/mcp/`. npm installation caches were removed after client runs.
- No server restart, paid Gemini, `/api/agent`, area build or crawl was initiated by QA. `/api/plan` was called only for the requested engine comparison; ordinary engine readers can refresh caches.
- First matrix: six alleys × four vehicles (`vinfast-vf-3`, `toyota-vios`, `toyota-fortuner`, `class-xl`) × `park`/`pickup`, arriving **2026-10-17 14:00 +07:00**, dwell **120 minutes** for both intents. This yields **48 calls each** to `plan_arrival`, `find_nearby_stops` and `check_alley_fit`, plus 48 `/api/plan` comparisons. Fit calls use each plan's resolved door OSM way ID; the fit schema has no intent/time fields.
- Post-restart core: protocol on both endpoints, all six canonical tools, representative Fortuner/park checks for all six alleys, the four 429 regression combinations, aliases and matching API calls. It includes 11 canonical plan responses (local/public and repeated 441/14 smoke inputs), 10 nearby-stop responses, 9 direct-fit calls, and 3 arrival-tool alias calls. The other three aliases were verified before restart.

## Pass/fail table

| Check | Before restart | After restart |
|---|---|---|
| Initialize 2025-06-18 and 2025-11-25, local + public | PASS | PASS |
| tools/list: six English tools, readOnlyHint; ping | PASS | PASS |
| Invalid method / unknown tool / missing params | PASS: -32601 / -32602 / -32602 | PASS |
| Wrong JSON-RPC version / params array / extra args | PASS: -32600 / -32602 / -32602 | PASS |
| Initialized notification | PASS: empty HTTP 202 | PASS |
| Hostile Origin / GET /mcp | PASS: 403 / 405, Allow: POST | PASS |
| Local burst of 65 + recovery | PASS: 60×200, 5×429, Retry-After:60; ping 200 after 61 s | INTERRUPTED: 65 connection-refused errors during second restart; later ping 200 |
| No unexpected tool errors | PASS: all 144 matrix tool calls | **FAIL: two compact-budget errors at 220/9** |
| Estimate + confidence | PASS: all 144 arrival-tool calls | PASS for successful responses; unavailable in two errors |
| Legal citations | PASS: all 48 full plans | PASS for successful full plans; unavailable in failed plan |
| English generated descriptions/messages/text | PASS; original names, source labels and legal citations retained | PASS |
| Envelope response size | PASS: maximum 18,001 UTF-8 bytes | Maximum 20,207 bytes among core responses; budget errors are 362 bytes |
| No compact_result_too_large | PASS | **FAIL** |
| /api/plan headline + estimate answer agreement | PASS: 48/48 exact-input pairs | 10/11 MCP plan responses agree; failed plan cannot supply either field |
| Vehicle-size monotonicity | **FAIL: 429, Fortuner → class-xl, both intents** | PASS for that exact regression: both sizes now fits |
| Direct alley-fit size monotonicity | PASS: all six ways | Representative Fortuner recheck passes |
| Official Inspector public HTTP list + plan | PASS | PASS, both exit 0 |
| Official Inspector local stdio list + plan | PASS | PASS, both exit 0 |
| Public stdio with explicit trusted CA bundle, list + plan | PASS | Not repeated; local stdio + public native HTTP repeated |
| Claude Code real health check | PASS: native public HTTP and local stdio Connected | Not repeated; Inspector covers both transports |
| Cursor application | Not available/tested; portable stdio transport verified | Not run |
| Codex isolated non-interactive prompt | BLOCKED: missing authentication, HTTP 401; no tool call | Not repeated; same missing credential prerequisite |

## Restart evidence and comparison

The listener changed from **PID 15333**, process start **11:27:09**, to **PID 25208**, process start **13:06:36**. The 20-second watcher detected the changed PID at **13:06:55** and automatically ran the core checks once. `/api/config` exposes no top-level process start/uptime field; nested build/crawl timestamps are not used as restart evidence. One pre-restart config poll timed out and recovered with the same PID. A second restart was detected at **13:11:32**, listener PID **42127**. It interrupted the post-restart rate burst: all 65 attempts at 13:11:00 received connection refused; the 13:12:02 ping recovered. The complete first-restart core remains separately captured. Additional later-process matrix evidence is in `after-matrix.jsonl` and `latest-complement.jsonl`; it is not silently merged into PID 25208 results. Raw timestamps/PIDs: `restart-watch.jsonl`.

Same Fortuner/park input before and after:

| Destination | Before estimate | After estimate / result |
|---|---|---|
| 441/14 Điện Biên Phủ | fits, low confidence; 34 m walk | fits, medium confidence; 34 m walk |
| 429 Điện Biên Phủ | no, low confidence; door selected | fits, medium confidence; alternative 96 m walk |
| 479 Điện Biên Phủ | fits, low confidence; 24 m walk | fits, medium confidence; alternative 42 m walk |
| 220/9 Xô Viết Nghệ Tĩnh | unknown, low confidence | **compact_result_too_large** |
| 246 Xô Viết Nghệ Tĩnh | fits, low confidence; door | fits, medium confidence; alternative 36 m walk |
| 356 Xô Viết Nghệ Tĩnh | fits, low confidence; 43 m walk | fits, medium confidence; alternative 156 m walk |

Changes are observed outputs, not attributed to any particular source edit. Source readers/cache contents can also change between runs.

## Bugs and exact JSON-RPC reproductions

### 1. Post-restart: compact response failure at 220/9 (open)

POST the following to either MCP endpoint using `Content-Type: application/json`, `Accept: application/json, text/event-stream`, and `MCP-Protocol-Version: 2025-11-25`. Captured failure is from local; the identical public 220/9 input was not separately rerun.

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "plan_arrival", "arguments": {"lat": 10.7992432, "lon": 106.7123911, "label": "Hẻm 220/9 Xô Viết Nghệ Tĩnh, Bình Thạnh", "vehicle_id": "toyota-fortuner", "intent": "park", "arrive_at": "2026-10-17T14:00:00+07:00", "dwell_min": 120}}}
```

Repeat with `params.name` set to `find_nearby_stops`; that also fails. Both return HTTP 200 with MCP `isError:true` and:

```json
{"error":"compact_result_too_large","note":"Result exceeds the compact response budget. No safety conclusion; request a single-alley check."}
```

The identical `/api/plan` input succeeds with headline **“Park on Branch beside Xô Viết Nghệ Tĩnh, 101 m walk — medium confidence”**. Before restart, MCP returned a valid plan for the same arguments. Exact responses: `bug-after-compact.json` (plan), `after.jsonl` (both tools + API). This fails the explicit no-errors/no-compact-result-too-large requirement even though the error safely declines a conclusion.

### 2. Pre-restart: 429 vehicle recommendation non-monotonicity (fixed in core retest)

```json
{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "plan_arrival", "arguments": {"lat": 10.80204457691327, "lon": 106.71296886819937, "label": "Hẻm 429 Điện Biên Phủ, Thạnh Mỹ Tây, Hồ Chí Minh", "vehicle_id": "toyota-fortuner", "intent": "park", "arrive_at": "2026-10-17T14:00:00+07:00", "dwell_min": 120}}}
```

Run with `vehicle_id: "toyota-fortuner"` and `"class-xl"`, for both `intent: "park"` and `"pickup"` (the remaining arguments identical). Before restart, Fortuner receives top-level `answer:no` / “Door access unlikely — low confidence”; class-xl receives `answer:fits` at a main-road stop 63 m away. Both door estimates are no. Fortuner's own `stop_points` already includes the same nearby fits alternative, pointing to candidate selection rather than a dimension-fit inversion. `/api/plan` agrees with each MCP result. Exact four request/response records: `bug-429-monotonicity.json`.

After restart, both vehicles receive `fits` for both intents. The full 48-combination matrix was not repeated after restart; the core includes the exact four failing comparisons.

### 3. Public Python bridge: default host CA trust fails (environment workaround verified)

Using public `VAODUOC_API` with this host's default Python CA store makes bridge initialize fail with `-32603`, “MCP HTTP service unavailable.” Direct urllib exposes `CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`; Node Inspector works against the same public URL. This is a client trust-store issue, not evidence of a server protocol fault. No TLS verification was disabled.

Exact input:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"qa","version":"1"}}}
```

Setting `SSL_CERT_FILE` to `/Library/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages/certifi/cacert.pem` fixes public stdio list and plan calls, verified with Inspector. Logs: `inspector-stdio-list.log` (failure), `inspector-stdio-public-cert-list.log`, `inspector-stdio-public-cert-plan.log` (success).

## Address and source behavior

`find_place` resolves 441/14 and 429 Điện Biên Phủ. `137/41/18 Trần Đình Xu` returns mapped alley 137/41 with `house_unpinned:true` and an English warning that house 18/final branch is not checked. `HUTECH` returns three campuses, including 475A, with `requires_clarification:true`; clients must select the campus. All six tested alley coordinates are geocoder/demo results, not invented pins. `list_vehicles` and today's 24-hour `tide_levels` succeed, including source/coverage metadata. Saved candidates: `before-places.json`.

All six aliases succeed: `tim_dia_diem`, `lap_ke_hoach`, `kiem_tra_xe_vao_hem`, `tim_cho_do_gan`, `danh_sach_xe`, `muc_trieu`.

## Verified client configurations

### Claude Code and Cursor: local stdio

Claude Code `.mcp.json`; Cursor `.cursor/mcp.json`:

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

The exact command/env was verified with official Inspector list + plan, before and after restart. Claude Code itself reports Connected. Actual Cursor execution is not claimed; its portable configuration is supplied in `client-configs/cursor/mcp.json`.

For public stdio, change `VAODUOC_API` to `https://concerts-message-concerns-performer.trycloudflare.com`; on this host also add the verified `SSL_CERT_FILE` path above to `env`.

### Claude Code: native public HTTP

Verified real CLI registration and Connected health:

```sh
claude mcp add --transport http ngo-ngach https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

Equivalent `.mcp.json`:

```json
{"mcpServers":{"ngo-ngach":{"type":"http","url":"https://concerts-message-concerns-performer.trycloudflare.com/mcp"}}}
```

### Codex: native public HTTP (registration verified; tool execution blocked)

`$CODEX_HOME/config.toml`:

```toml
[mcp_servers.ngo-ngach]
url = "https://concerts-message-concerns-performer.trycloudflare.com/mcp"
```

Verified registration:

```sh
CODEX_HOME=/Users/khoivo/Developer/mlai-car-access/docs/qa/mcp/codex-home   codex mcp add ngo-ngach --url https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

A real `codex exec --skip-git-repo-check --json -s read-only` prompt explicitly asked to call plan_arrival at 441/14 with Fortuner and the resolved coordinates. The isolated home has no authentication: model startup returns **401 Missing bearer or basic authentication**, and no MCP tool call occurs. Existing credentials were not copied into the repository. Thus this is a verified accepted config, **not an end-to-end verified Codex tool execution**. Evidence: `codex-config.log`, `codex-client.jsonl`, `codex-client.stderr`. [Official Codex MCP configuration reference](https://developers.openai.com/learn/docs-mcp).

## Re-running official Inspector

Inspector version is recorded in `inspector-version.json`. Use `npm_config_cache` under the allowed QA directory if retaining the same write boundary.

```sh
npx -y @modelcontextprotocol/inspector --cli   https://concerts-message-concerns-performer.trycloudflare.com/mcp   --transport http --method tools/list

npx -y @modelcontextprotocol/inspector --cli   -e VAODUOC_API=http://127.0.0.1:8787   python3 /Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py   --method tools/call --tool-name plan_arrival   --tool-arg lat=10.802092539999743 --tool-arg lon=106.71365960299639   --tool-arg 'label=Hẻm 441/14 Điện Biên Phủ'   --tool-arg vehicle_id=toyota-fortuner   --tool-arg arrive_at=2026-10-17T14:00:00+07:00   --tool-arg dwell_min=120 --tool-arg intent=park
```

All four post-restart Inspector tests exit 0 in `inspector-after-status.json`.

## Evidence index

- `before.jsonl`: complete initial matrix, protocol, aliases, rate burst and recovery; public default-CA failures retained.
- `public-certifi.jsonl`: successful local/public protocol and public/local core using verified CA trust.
- `after.jsonl`: automatic post-restart core, regression, all six alleys and exact API comparisons.
- `protocol-extra.jsonl`, `after-extra.jsonl`, `after-rate.jsonl`: supplemental validation and post-restart rate evidence.
- `analysis.json`, `tool-quality.json`: comparison counts, mismatches, estimates, citations, size checks and English summaries.
- `inspector-*.log`, `claude-health-both.log`, `codex-client.*`: real-client evidence.
- `restart-watch.jsonl`: bounded polling, listener PID and config availability; QA did not restart a server.
