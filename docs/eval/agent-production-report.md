# Agent + MCP implementation report — 17 October 2026

The assigned agent, MCP and panel changes are implemented, uncommitted. The final 46-case **quota-recovery contract evaluation passes 46/46**, with 17 completed arrival plans and 29 safe clarifications/declines. This is **not** a 100% destination-resolution rate, a full Gemini understanding benchmark, or proof that any HCMC address has sufficient engine evidence. Free project quota exhaustion and an HTTP 403 on the single authorized paid attempt prevented those stronger claims.

**Evaluation and before/after**

`pipelines/eval_agent.py` contains 46 realistic queries covering every historical urban district plus Thủ Đức (including former Q2/Q9), house numbers and slash alleys, Chợ Rẫy and other POIs, classes/model names, Vietnamese/English, park/pickup, arrival/dwell, car/time/nearer/rain follow-ups, nonsense and destinations outside the supported area. It asserts tool order, destination query token properties, vehicle, intent, dwell, local date/hour, rain, successful plan/UI completion or genuine geocoder ambiguity, and terminal events. It logs calls/results, latency, model-number violations and visible answers. It does not assert exact answer prose.

| Run | Outcome | Latency p50 / p90 | Interpretation |
| --- | --- | --- | --- |
| Original code baseline, planned 12 | 1/2 completed cases passed; remaining run aborted | 15.08 / 16.35 s for the two completed cases | Daily 3.5-alias free quota exhausted; `agent-eval-before.log` is the available evidence. No valid 12/46-case original-code baseline was obtained. |
| Four-case real-model probe, free 2.5 Flash | 4/4 passed | 3.46 / 5.15 s | Real Gemini + geocoder; mostly clarification cases. `agent-eval-probe.json`. |
| First complete 46-case run, after initial hardening but before quota recovery | 8/46 (17.4%) | 0.001 / 4.51 s | 38 quota failures, 38 missing answers, 32 missing plans, 28 missing geocodes (overlapping categories). Short latency reflects immediate quota errors, not speed. `agent-eval-first-full.json`. |
| Final strict 46-case quota-recovery run | 46/46 (100%) | 1.858 / 3.482 s | 17 plans, 25 geocoder clarifications, 4 invalid/outside/missing-detail declines. All 46 used the conservative fallback; actual geocoder/engine calls, no mocked model responses. `agent-eval.json`. |

The original model alias returned a quota error identifying the served model as `gemini-3.6-flash` and the exhausted daily free request metric. A different free model (`gemini-2.5-flash`) worked, then also exhausted the shared project quota during the first complete run. Rotating keys cannot replenish project-level quota. The paid smoke ran concurrently with the first complete eval, so that eval’s shared-ledger delta includes the smoke’s one paid attempt; the evaluation process itself always had paid disabled. The final run deliberately set the absolute free-call ceiling to the current ledger count (186), verifying recovery without additional model attempts. Standard operation can still use Gemini when free quota is available.

An intermediate fallback run was invalidated after manual review found that “tối nay” was parsed as a destination introducer. The parser selected an unrelated address; the old harness did not check destination identity. That run is retained in `agent-eval-parser-bug.json` for audit and is **not** counted as a valid pass result. Destination assertions and a targeted regression now catch this. Another fixed regression confused the place name “Bến Vân Đồn” with the pickup verb “đón”. Final raw arguments identify the intended streets/alleys. Final emitted answers have zero numeric provenance violations. The model-probe artifacts retain any pre-repair violations.

**Agent behavior**

- Goong autocomplete/detail, cached local OSM alley-name fallback, then Nominatim. Broad house-number mismatches also fall through instead of silently becoming exact entrances. Nominatim has a bounded timeout, cache, per-process serialization and minimum request spacing. Duplicate labels/nearby points are collapsed; exact house-number candidates are preferred.
- Multiple matches ask for a short clarification. With an explicit origin, the nearest candidate can be selected and its selection reason is surfaced. Unresolved house branches request confirmation/ghim.
- Vehicle names/classes normalize at the adapter boundary. ISO and explicit relative times use UTC+07:00; the fallback handles tonight/tomorrow, dwell, pickup, rain and plan-preserving follow-ups. Missing morning arrival hour asks for clarification. Dwell hours are excluded from arrival-clock parsing.
- Gemini free-key rotation/cooldown, a shared absolute call ceiling, optional paid reservations and rejection accounting. The comparison remains tool-free and cannot use paid fallback. `AGENT_ALLOW_PAID` remained 0 except the one isolated paid smoke scope.
- Model/tool waits are bounded; NDJSON progress continues during waits. Duplicate calls are suppressed. Errors terminate with an error event. Stop/cancel prevents subsequent rounds. The fallback uses the same tools, never invents geographic coordinates, and produces plans only after successful resolution.
- Every numeric token in a tool-backed final answer is compared with tool results, including address/model digits and times. Unsupported numbers produce a logged validation event and a tool-derived replacement; replacement output is checked again. This checks provenance membership, **not semantic attribution of an already-known number**. The system prompt additionally prohibits unsupported measurements and causes. Baseline answers are intentionally unchecked.
- Compact results retain evidence lists and way IDs/coordinates for chips. Missing tide forecasts and weaker/unverified cadastral evidence remain qualified. Cadastral lock/wait behavior is contained by the tool deadline, not repaired in the engine.

**MCP proof**

`mcp/protocol.py` is a dependency-free shared JSON-RPC dispatcher for stdio and `POST /mcp` on FastAPI. HTTP uses stateless JSON response mode, pinned stable protocol 2025-11-25 (also 2025-03-26 and 2025-06-18). Notifications return 202/empty; GET/DELETE return 405; invalid media/version/origin and JSON-RPC parse/method/argument errors are tested. No SDK dependency, sessions, server-initiated SSE, authentication discovery or OAuth implementation is claimed. Optional bearer authentication and explicit deployed-origin allowlisting are documented.

Actual HTTP proof on isolated port 8788: initialize 200, initialized notification 202, tools/list 200 with all six tools, vehicle listing 200/isError false, real OSM way 464839531 + VF3 fit 200/isError false with evidence. Real stdio subprocess produced three valid response lines for initialize/list/call and no notification response. See `agent-mcp-http-proof.json` and `agent-mcp-stdio-proof.ndjson`.

Added bilingual tools: `kiem_tra_xe_vao_hem`, `tim_cho_do_gan`, `danh_sach_xe`. Single-alley fit delegates to the existing engine and explicitly excludes whole-route/exit/flood/legal certification. Stop-only output omits door and standard-route payloads. Both have adapter regression coverage. Offline Inspector attempt returned `ENOTCACHED`; its npm package was unavailable, so no Inspector success is claimed (`agent-mcp-inspector.txt`). Setup/examples are in `mcp/README.md`.

**Panel changes and verification**

| Before | After |
| --- | --- |
| `Agent.tsx`: in-memory conversation only | Versioned localStorage restore/save with try/catch; bounded complete-turn history preserves tool-call/response pairs and signed parts. |
| No stop control | “Dừng” aborts the reader, sends request-ID cancellation, clears busy state and exposes retry. Provider requests already in flight cannot be recalled. |
| Error text only | “Thử lại” resubmits the failed question using the last completed conversation history. |
| Answers had no actionable source references | Evidence chips open the existing `EvidencePanel` with actual way evidence. |
| Tool waits could look frozen | Progress text is streamed and shown while waiting; unterminated/error streams fail cleanly. |
| Some mobile controls smaller than 40 px; 14 px textarea | Minimum 40 px targets, visible keyboard focus, 16 px textarea, wrapped chips and contained overflow. Existing Enter/Shift+Enter/Escape behavior retained. |

Browser proof (`agent-ui-proof.json`): restored a seeded conversation across reload; actual evidence API opened “Hẻm 113/4 Võ Duy Ninh”; a browser-local streaming fixture showed stop, aborted and sent cancel, then retry completed. These interaction checks cost zero Gemini calls. No horizontal overflow at 1280×800 or 390×844; mobile compose bottom equals viewport bottom. Screenshot: `agent-production-mobile.png`. Test fixture storage was cleared afterward.

**Money and checks**

Ledger **74 → 186 free attempts: 112/250 allowed**, including failed-key rotations and probes. **One paid fallback attempt**, HTTP **403**, **$0.000000**, no outstanding reservations, paid disabled afterward. The requested successful paid inference + real token-spend proof **could not be completed** with the configured paid key; no retry was made under the one-attempt authorization. `agent-paid-smoke.json` and `agent-production-budget.json` contain the evidence. Offline tests cover successful token accounting (including thinking tokens), reservation refusal and release on rejection. Reservation rates are conservative bounds, not an invoice; see [official pricing](https://ai.google.dev/gemini-api/docs/pricing) and the ledger documentation.

22 agent/MCP backend tests pass (`agent-production-tests.txt`). TypeScript/Vite production build passes and `frontend/dist` was rebuilt (`agent-production-build.txt`). Lint passes with existing warnings in Directions/Result/ds/ui, none in Agent (`agent-production-lint.txt`). Python compile checks and `git diff --check` pass. Protocol behavior follows the [stable Streamable HTTP specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

**Engine issues for the algorithm owner**

1. The final engine produced “Chưa đủ bằng chứng để khẳng định” for 5/17 completed plans. That is an honest outcome; broader cached geometry does not establish clear width, a way out, flood or stop legality. Resolve evidence/geometry gaps in the engine rather than relaxing the agent prompt. Live crawl/cache changes can alter rankings during eval; results are point-in-time observations, not an immutable benchmark dataset.
2. Door fail reasons combine alternatives (“hẻm hẹp hoặc ngập”, “hẻm cụt hoặc ngập”). The agent preserves that uncertainty instead of assigning one cause. Structured, independent failure codes would permit a more precise explanation.
3. Walking prose may say `~0 phút` for a short nonzero distance (e.g. 9 m or 12 m). The agent cannot invent a corrected number. Prefer “dưới một phút” in engine formatting, sourced from the actual walk duration.
4. The service-area gate is a bounding box, not the official administrative polygon. Some adjacent provinces are inside that box, and the city has changed boundaries; explicit named outside destinations are declined by the adapter, but an engine polygon gate is still needed for arbitrary coordinates.
5. Python cannot kill a timed-out portal/engine thread safely. The adapter returns after a deadline and caps admission at eight outstanding workers; eight permanently hung workers leave the process safely refusing work until restarted. A production engine should expose cancellable/deadline-aware I/O or run isolated jobs. Nominatim rate limiting/cache is also per process; multi-worker deployment needs shared coordination.
6. “Còn chỗ nào gần hơn?” recomputes the current ranked plan and explicitly says that no closer point has been newly verified. The engine has no dedicated alternative-search/pagination contract. Do not claim a new closer stop merely from repeating the same plan.
7. Deployment follow-up outside this ownership: `vercel.json` currently rewrites only `/api/(.*)` to the Python function, so hosted `/mcp` also needs an explicit rewrite to `/api/index`. The FastAPI endpoint is tested on the direct server; no claim is made that the current Vercel static deployment exposes it. `vercel.json` was not edited.
8. 25 geocoder clarifications remain: broad POI/branch ambiguity and weak house matches are not solved by cached street geometry. An address/POI index with stable IDs, ward aliases, house-branch precision and a selection-resume contract would improve completion rate.

**Files changed by this task**

`backend/app/agent.py`, `backend/app/agent_budget.py`; only the agent route block plus the explicitly requested `/mcp` endpoint in `backend/app/main.py`; `mcp/protocol.py`, `mcp/vaoduoc_mcp.py`, `mcp/README.md`; `frontend/src/components/Agent.tsx`, `Agent.css`; agent helpers/types only in `frontend/src/api.ts`; `backend/tests/test_agent.py` (updated accounting expectation), `backend/tests/test_agent_production.py`; `pipelines/eval_agent.py`; named artifacts under `docs/eval/`; generated `frontend/dist`.

No commit was made. No crawler/engine source or flags were edited, and the running city crawler (PID 93693 when checked) was left running. The existing 8787 server was not restarted; it must reload the changed Python modules before serving the new implementation. Browser/HTTP proof used a separate test server on 8788, reloaded with the final code. It remains available for review with paid disabled and an absolute free-call ceiling of 186 (quota fallback only). Latest actual HTTP `/api/agent` proof: 200 with progress → answer → done in `agent-production-stream.ndjson`.
