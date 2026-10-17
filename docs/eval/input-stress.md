# Input stress report — Agent A, 17 October 2026

Completed before the 12:15 handoff. Branch `hackathon-night-2026-10-17`, baseline `8775ef4`. No commits or pushes. Port **8787 was not restarted**. Verification used **8792**, an isolated cloned cache/store/flags, `AGENT_ALLOW_PAID=0`, deterministic mode and cached-only backend requests.

## Result and scope

**179/395 (45.3%) → 395/395 (100%)** on the same generated corpus, including **374 distinct input strings**. Sources: 50,430 real cached OSM names (36 named POIs after reindexing). Expected points/way IDs come from the source ways used to generate each request, not from resolver answers. See [corpus](input-stress/corpus.json), [before](input-stress/before-summary.json) and [after](input-stress/after-summary.json).

This is an input-understanding score, not an access-safety accuracy score. Resolver cases require the source label and a point within 150 m of the generating way, without unnecessary clarification. Nineteen journey cases mock the planner and require `lap_ke_hoach`, the correct source point/vehicle, and an estimate with confidence. A separate live-engine request verifies the complete reported GLC flow. Ward suffixes are normalization variants, not validation of administrative boundaries.

## Failure clusters (passed / cases)

| Resolver step / input pattern | Before | After | Fix |
|---|---:|---:|---|
| Exact, bare, ASCII, old/new ward suffixes | 110/120 | 120/120 | Structured chain/street parsing; preserve alphanumeric house components |
| ngõ / kiệt / ngách / English alley | 8/96 | 96/96 | Normalize alley vocabulary before matching |
| Single street-token typo | 2/24 | 24/24 | Constrained typo recovery only with the same chain and street-token structure |
| Trailing unpinned house, known parent alley | 0/15 | 15/15 | Longest known chain prefix; explicit unpinned-house disclosure; still plan |
| Vehicle + travel/pickup/time prose | 27/57 | 57/57 | Catalogue/family/class aliases, intent and time extraction |
| Address first, vehicle after a dash | 0/19 | 19/19 | Preserve full destination before the vehicle suffix |
| Vehicle follow-up | 9/19 | 19/19 | Keep previous point/time/duration; replace only requested vehicle |
| Known-point + vehicle planning policy | 0/19 | 19/19 | Complete the plan if the model stops after geocoding |
| Street-only | 8/8 | 8/8 | Preserve street search; add numbered-street regression |
| Cached OSM POI names | 10/10 | 10/10 | Index named amenities, shops, offices and visitor features |
| Vương Phạm wrong-match gate | 2/2 | 2/2 | ≥70% distinctive-token coverage in one label section; no cross-name/address token mixing |
| Motorcycle decline | 0/3 | 3/3 | Explicit English car-only explanation |
| Unknown vehicle (including nonexistent VF4) | 3/3 | 3/3 | Ask for a known model or size class |

| Chain depth | Before | After |
|---|---:|---:|
| 1 | 20/60 | 60/60 |
| 2 | 65/149 | 149/149 |
| 3 | 40/95 | 95/95 |
| 4 | 31/65 | 65/65 |
| Street/POI/non-address | 23/26 | 26/26 |

| Other dimension | Before | After |
|---|---:|---:|
| Accented inputs | 156/370 | 370/370 |
| No diacritics | 23/25 | 25/25 |
| Outside-catalogue vehicle families | 0/35 | 35/35 |
| Catalogue models | 21/45 | 45/45 |
| Generic size classes | 6/15 | 15/15 |

## Required examples and browser proof

1. `137/41/18 Trần Đình Xu, Cầu Ông Lãnh, Hồ Chí Minh, Vietnam - Merc GLC 200`
   - Resolves to **Hẻm 137/41 Trần Đình Xu**, Goong point **10.76193523, 106.68747717**, with **house 18 not pinned**. The checked raw OSM name cache does not contain this exact branch; Goong and the loaded map tiles do. No fabricated OSM house pin was added.
   - Maps to **class-m** with the English note that Mercedes GLC has no dedicated catalogue specs and uses a conservative class M envelope.
   - [Real isolated HTTP flow](input-stress/reported-flow-en.json) calls **tim_dia_diem → lap_ke_hoach**, returns **“Estimate: access appears possible. Low confidence.”**, a suggested stop and the actual width/exit/flood/legal uncertainties. The estimate concerns the mapped alley, not an assertion that the final branch to house 18 is checked.
2. `Cong ty CP Vuong Pham` resolves via Goong to the named company at **10.7617409, 106.6874995**. `Vương Phạm` does not match `Trường Đại học Sư phạm … An Dương Vương`.
3. [Browser request/answer proof](input-stress/map-feature-proof.json), [search screenshot](input-stress/map-search.png), [assistant screenshot](input-stress/assistant.png). Destination search for `Vuong Pham` shows **“Cong Ty Cp Vuong Pham — On the map”** first, immediately, before the API returns. Clicking the map POI sets it as destination. The assistant’s recorded request contains the actual map centre/zoom and the matching `point_map` candidate; its tool trace then resolves from that map feature and runs the plan.
4. `5/2A`, four-level chains and mixed alphanumeric `137/3A31` have direct mocked regressions. The cached-data corpus additionally uses actual alphanumeric source chains. Latin `Ð` in old OSM spellings is normalized without changing street labels.

All owned UI strings, assistant answers, clarifications, summaries and geocoding source labels are now English. Vietnamese input, voice input and proper place/street names remain supported. Old localized assistant history uses a separate storage key so it does not reappear as current English output.

## Startup and verification

- **61 agent/geocoding regressions pass**: [log](input-stress/agent-regressions-final.log). Every test provider call is mocked or disabled by fixture. Tests now mock the numbered key pool, not only the primary configuration value.
- **2 startup regressions pass**: [log](input-stress/boot-tests.log). One covers relation **20675274**, missing nodes and partially cached ways. The other imports `app.main`, forces a cold rebuild over the real OSM cache, enters FastAPI lifespan and serves `/api/vehicles`. Cold run: 190.46 s. Missing geometry is skipped/logged; named POI relations cannot be indexed as nodes. A later fresh **8792 startup completed** with the English tree; a [fresh lifespan/API check](input-stress/final-lifespan.log) also passes.
- **4 frontend tests + 6 additional map-chain/relevance checks pass**: [tests](input-stress/frontend-tests.log), [chain checks](input-stress/frontend-chain-checks.log).
- **`npm run build` passes and `frontend/dist` is rebuilt**. Existing bundle-size warning remains.
- Two old `test_agent2` tide tests assert historical bulletin extrema and no extrapolation; they fail against the current tide model. Loading `flood.py` directly from baseline `8775ef4` reproduces those same two test failures (21 subtest/assertion failures): [baseline proof](input-stress/tide-baseline.log). No tide-engine changes were made here.
- New-address history regression ensures that a previous turn’s geocode cannot be substituted for a new destination. Vehicle-only punctuation such as `Còn VF3?` is never parsed as an address. Accented `tôi`/`tới` and unaccented travel verbs are not mistaken for `tối` when parsing morning clocks.

## Goong and AI usage

**18 known Goong geocoding HTTP requests total**, below 150. **16 used key 3**, including six early boundary-test lookups which were later mocked. A later legacy-test escape made **2 unintended requests**, using the exhausted primary key and then **key 2**. This violated the key-3-only instruction; it is recorded explicitly, and default provider mocks plus a parser regression now prevent recurrence. [Usage ledger](input-stress/goong-usage.json). No credentials are included in logs or this report. Normal map-tile asset loads are separate from geocoding requests.

Manual checks and the isolated server made **zero Gemini calls, paid or free**. The project free cooldown was still active (until 14:00 Vietnam time), so verification used deterministic fallback. Unit tests use fake model responses and temporary ledgers.

Rotation covers the configured primary and numbered API keys 1–9, deduplicates values and excludes tile key 10. `GOONG_KEY_NAMES` can restrict a verification process to `GOONG_API_KEY_3`. Unauthorized keys are skipped with a per-key 30-minute breaker; HTTP 429 keys are parked until the next Vietnam calendar day. Cache hits still work while keys are parked. State stores credential hashes only. An observed breaker remains committed even if the next key times out.

## Files changed by Agent A

- `backend/app/geocoding.py`
- `backend/app/agent.py`
- `backend/app/vehicle_aliases.py` (new; `vehicles.py` unchanged)
- `frontend/src/MapView.tsx`
- `frontend/src/components/Directions.tsx`
- `frontend/src/components/Agent.tsx`
- `frontend/src/api.ts` (search/agent helper and stream messages)
- `backend/tests/test_geocoding.py`, `test_geocoding_startup.py`
- `backend/tests/test_agent.py`, `test_agent2.py`, `test_agent_vertex.py`, `test_agent_production.py`, `test_agent_inputs.py`
- `pipelines/stress_inputs.py`
- This report and evaluation artifacts; rebuilt `frontend/dist`.

Agent B’s engine/evidence files and Agent C’s MCP/routes were not edited. The shared English migration briefly exposed an incomplete `english_payload` import; it resolved when its owner landed the helper, and the current tree boots.

## Reproduce

Use an isolated store/cache/flags for any server, never the live store. All corpus runs themselves disable HTTP/model calls internally:

```sh
PYTHONPATH=backend AGENT_ALLOW_PAID=0 python3 pipelines/stress_inputs.py \
  --index tmp/input-stress/server/store/osm_name_index.json \
  --output tmp/input-stress/after.json --corpus tmp/input-stress/corpus.json

PYTHONPATH=backend AGENT_ALLOW_PAID=0 python3 pipelines/stress_inputs.py \
  --index tmp/input-stress/server/store/osm_name_index.json \
  --baseline-ref 8775ef4 --output tmp/input-stress/before-replay.json
```

`--baseline-ref` loads the original owned modules in memory; it never checks out a branch or changes another agent’s files. Baseline and final results use the same source corpus. The recorded corpus is retained so the examples remain reviewable if local caches change.
