# English MCP interface follow-up

The primary tool names are `find_place`, `plan_arrival`, `check_alley_fit`, `find_nearby_stops`, `list_vehicles`, and `tide_levels`. These six names alone appear in `tools/list`.

The six original Vietnamese names remain accepted aliases. Alias resolution happens before schema validation and calls the same canonical tool. The existing engine tide adapter retains its internal Vietnamese identifier; the conversational agent and engine modules were not changed.

Tool descriptions, MCP-generated messages, failures and `content[].text` are English. Plan summaries use structured estimate/confidence values instead of echoing the engine's source-language headline. Original geographic names, engine evidence and legal citations remain verbatim in `structuredContent`; no unverified translation of source evidence is substituted. The server title is exactly **Ngõ Ngách — alley access for vehicles in HCMC**. README examples use the new tool names and document the accepted aliases.

Validation:

- **42 tests passed**: the MCP suite plus the existing raw HTTP MCP regression. New cases exercise all six legacy aliases and verify that source-language headlines/errors never leak into the English text presentation.
- Official Inspector HTTP `tools/list` succeeded and returned exactly the six English names: `english-inspector-http-list.json`.
- Official Inspector HTTP `tools/call plan_arrival` succeeded for Hẻm 113/4 Võ Duy Ninh / Toyota Fortuner: `isError: false`, estimate `tight`, confidence `low`. Its text is: “Arrival estimate: tight. Confidence: low. Physical access does not authorize stopping. Check the legal status, evidence and caveats in structuredContent.” See `english-inspector-http-plan.json` and the corresponding stderr files. The compact tool result is 7,664 bytes before the small JSON-RPC envelope.
- Live `list_vehicles` and legacy `danh_sach_xe` both succeeded with identical English text and 39 catalogue entries: `english-alias-http-proof.json`.
- Python compile checks and scoped `git diff --check` passed. Existing dependency warnings remain.

Verification used the same isolated store/cache/flags on :8797, restarted with cached-only mode, paid disabled, and `--lifespan off` (PID 58869). No Goong or LLM calls were made. The public :8787 process was not restarted. No commit or push was made.

Files changed for this follow-up: `mcp/protocol.py`, `mcp/server.py`, `mcp/README.md`, the MCP test module, the English discovery expectation in the existing raw HTTP MCP test, and these verification artifacts. No change to `agent.py`, `geocoding.py`, `plan.py`, `evidence.py` or frontend files was made.
