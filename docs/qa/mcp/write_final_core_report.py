import json,datetime
from pathlib import Path
root=Path(__file__).parent
rows=[json.loads(l) for l in (root/'final-core.jsonl').read_text().splitlines()]
latest=json.loads((root/'analysis.json').read_text())['final-core.jsonl']
log=(root/'inspector-final-public-plan.log').read_text()
inspector='PASS: official CLI returns isError:false' if '"isError": false' in log else 'PENDING'
text=f'''# Ngõ Ngách MCP QA — 2026-10-17

**PASS — latest requested public core checks.** Four plan/API comparisons agree; all 12 arrival-tool calls succeed. First pass was delivered at **12:59 +07:00**. Final core ran **13:13–13:15 +07:00** after the budget change, using listener PID **42127**. Report updated {datetime.datetime.now().strftime('%H:%M:%S')} +07:00.

| Check | Result | Evidence |
|---|---|---|
| Public tools/list | PASS | Six English tools, readOnlyHint=true |
| plan_arrival, two locations × two vehicles | PASS | 4/4, estimate/confidence, legal citations and verdict.profile preserved |
| check_alley_fit, same four inputs | PASS | Resolved door way IDs 610082023 and 610082009 |
| find_nearby_stops, same four inputs | PASS | 4/4; no tool errors |
| MCP vs public POST /api/plan | PASS | 4/4 exact headline + estimate-answer matches |
| Smaller-vehicle monotonicity | PASS | Both vehicles get fits plans; direct-fit answers equal within each location |
| Response size / compact_result_too_large | PASS | Maximum {latest['max_tool_bytes']:,} UTF-8 bytes; zero compact-budget errors, below 64 KiB |
| English generated text | PASS | Original Vietnamese place names and statutory citations retained |
| Latest official Inspector public plan call | {inspector} | inspector-final-public-plan.log |
| Earlier protocol sweep, both endpoints | PASS | Both requested protocol versions; list/ping, validation errors, Origin 403, GET 405 |
| Original local 65-request limiter test | PASS | 60×200 + 5×429, Retry-After:60; recovery ping 200 after 61 s |
| Later limiter retry during restart | INTERRUPTED | 65 connection-refused errors; later ping recovered. Not counted as a pass |
| Claude Code / local stdio Inspector | PASS | Claude health Connected over public HTTP and local stdio; Inspector list/plan pass |
| Codex non-interactive tool call | BLOCKED | Isolated home missing authentication; HTTP 401; no tool call occurred |
| Cursor application | NOT RUN | Portable stdio command verified via Inspector; no Cursor runtime claim |

## Exact latest inputs and observed results

Public MCP: `https://concerts-message-concerns-performer.trycloudflare.com/mcp`. All four use `intent=park`, `arrive_at=2026-10-17T14:00:00+07:00`, `dwell_min=120`. Coordinates were supplied explicitly in the final user instruction. Fit calls use the plan's resolved door way ID.

| Location / supplied pin | Vehicle | Plan estimate | Direct alley fit |
|---|---|---|---|
| Hẻm 441/53 Điện Biên Phủ — 10.8027513, 106.7128822 | vinfast-vf-3 | fits / medium | fits / low |
| Same | toyota-fortuner | fits / medium | fits / low |
| Hẻm 429 Điện Biên Phủ — 10.802498, 106.713094 | vinfast-vf-3 | fits / medium | tight / low |
| Same | toyota-fortuner | fits / medium | tight / low |

A full-plan estimate can describe a nearby stopping alternative; direct fit describes only the selected alley segment. Physical fit does not grant stopping permission. Exact JSON-RPC requests, full responses, HTTP headers, byte counts and matching **public** API responses: [final-core.jsonl](final-core.jsonl). Derived comparisons: [analysis.json](analysis.json).

## Before/after findings

- **Original 429 ranking bug:** Fortuner returned no while larger class-xl got fits at a nearby stop, for both park and pickup. The first post-restart core fixed that exact comparison. Latest user-specified VF 3/Fortuner pins also pass monotonicity. Exact original repros: [bug-429-monotonicity.json](bug-429-monotonicity.json).
- **Intermediate compact-budget regression:** after PID 25208 started, 220/9 Xô Viết Nghệ Tĩnh with Fortuner/park failed in both plan_arrival and find_nearby_stops; API succeeded. The latest requested inputs return 22–27 KB plans successfully with verdict.profile, demonstrating operation beyond the former 24 KB budget. **220/9 was not rerun after the budget change**, per the final instruction to test only 441/53 and 429. Exact JSON-RPC repro/response: [bug-after-compact.json](bug-after-compact.json); nearby-stop failure in [after.jsonl](after.jsonl).
- **Public Python trust-store issue:** default host Python CA trust rejects the public endpoint; bridge emits generic -32603. Public stdio list/plan both work with a trusted certifi CA bundle via SSL_CERT_FILE. TLS verification was never disabled.

The watcher detected PID **15333 → 25208** at 13:06:55 and **25208 → 42127** at 13:11:32. QA initiated no restart. `/api/config` has no top-level process start field, so listener PID is the restart signal. Monitoring and the supplementary matrix were stopped at the user's wrap-up instruction. The original full matrix completed 48 calls each of plan_arrival, nearby stops and alley fit, with 48/48 API matches. Full historical detail: [first-pass-and-restart-details.md](first-pass-and-restart-details.md); raw watcher: [restart-watch.jsonl](restart-watch.jsonl).

## Copy-paste client configs

**Claude Code `.mcp.json` and Cursor `.cursor/mcp.json`:** exact local stdio command/env verified with official Inspector list + plan before and after restart; Claude Code itself reports Connected. Cursor application execution was not tested.

```json
{{
  "mcpServers": {{
    "ngo-ngach": {{
      "command": "python3",
      "args": ["/Users/khoivo/Developer/mlai-car-access/mcp/vaoduoc_mcp.py"],
      "env": {{"VAODUOC_API": "http://127.0.0.1:8787"}}
    }}
  }}
}}
```

**Claude Code public HTTP:** registration and real Connected health verified.

```json
{{"mcpServers":{{"ngo-ngach":{{"type":"http","url":"https://concerts-message-concerns-performer.trycloudflare.com/mcp"}}}}}}
```

```sh
claude mcp add --transport http ngo-ngach https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

**Public stdio variant:** change VAODUOC_API to `https://concerts-message-concerns-performer.trycloudflare.com` and, on this host, add this verified trusted CA path to env:

```json
"SSL_CERT_FILE": "/Library/Frameworks/Python.framework/Versions/3.11/lib/python3.11/site-packages/certifi/cacert.pem"
```

**Codex `$CODEX_HOME/config.toml`:** CLI registration accepted. End-to-end tool execution could not be verified because the isolated home had no authentication; no existing credentials were copied into QA artifacts.

```toml
[mcp_servers.ngo-ngach]
url = "https://concerts-message-concerns-performer.trycloudflare.com/mcp"
```

```sh
codex mcp add ngo-ngach --url https://concerts-message-concerns-performer.trycloudflare.com/mcp
```

The isolated `codex exec` prompt explicitly requested plan_arrival for 441/14 with Fortuner; HTTP 401 occurred before a tool call. Logs: `codex-config.log`, `codex-client.jsonl`, `codex-client.stderr`. [Official Codex MCP configuration reference](https://developers.openai.com/learn/docs-mcp).

## Final Inspector command

```sh
npx -y @modelcontextprotocol/inspector --cli \\
  https://concerts-message-concerns-performer.trycloudflare.com/mcp \\
  --transport http --method tools/call --tool-name plan_arrival \\
  --tool-arg lat=10.8027513 --tool-arg lon=106.7128822 \\
  --tool-arg 'label=Hẻm 441/53 Điện Biên Phủ' \\
  --tool-arg vehicle_id=toyota-fortuner \\
  --tool-arg arrive_at=2026-10-17T14:00:00+07:00 \\
  --tool-arg dwell_min=120 --tool-arg intent=park
```

All QA writes were under `docs/qa/mcp/`; repo code was read-only. No paid Gemini call or server restart was initiated. No commit was made. Temporary **claude-state** and **codex-home** directories were removed; portable non-secret config examples and client evidence logs remain.
'''
(root/'mcp-test-2026-10-17.md').write_text(text)
