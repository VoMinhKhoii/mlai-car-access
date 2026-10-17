# English UI implementation handoff

Scope: English everything outside the files owned by Agents A and B; no commits/pushes and no Gemini/Goong calls. Branch: hackathon-night-2026-10-17.

## Integration findings for A / B

- Agent A: full backend test run initially failed in `agent.grounded_answer` when a compact stop has `flood=None` (`backend/app/agent.py`, access to `stop.get('flood', {}).get('depth')`). The same issue is documented in engine-agent-handoff.md. This file was not edited here.
- Agent B: `evidence.english_payload` currently translates legal citation strings (the full `Luật ... Điều 18 ...` citation and `QCVN ..., biển ...`). The user explicitly requested that legal citations stay as-is. Preserve the `citation` field in the output adapter. This file was not edited here.
- Agent A: `Directions.tsx` compact duration still uses `h`/`′`; user requested `m` and `min` with English 24h formatting. `fmtWidth` already uses the shared English decimal helper.
- Result.tsx now recognises Agent B’s `Stopping permission unverified:` prefix for the existing access-success UI logic.
- OSM source filters in declared_index.py and evidence_queue.py recognise both new English source labels and legacy Vietnamese labels.

## Owned frontend changed

`frontend/index.html`, `frontend/field.html`; `src/App.tsx`, `ErrorBoundary.tsx`, `LookupPanel.tsx`, `parkingWatch.ts`; `src/components/{Result,Evidence,TideTimeline,Corridor,VoiceReport}.tsx`; `src/ds/{ui.tsx,README.md}`; `src/field/{main,ArrivalConfirmation,Crowd,MiniMap,Review,Stage}.tsx`, `src/field/storage.ts`.

## Owned backend changed

`backend/app/{agent_budget,ai,auth,budget,cameras,config,corridor,coverage,crowd,crowd_routes,deadline,declared_index,demo_fixture,evidence_queue,field_evidence,field_routes,field_server,flags,flood,google_lookup,hydro,imagery_evidence,legality,live,news,official_widths,osm,parking_data,reports,tide_refresh,vehicles}.py`.

`CONTEXT.md`; `data/flood/tide_forecast.json` display metadata; cached news summaries and photo notes/references in `backend/cache/live/areas/{demo,10.856_106.784,10.788_106.696}.json`. Tests updated for owned output: `backend/tests/{test_camera_jobs,test_corridor,test_evidence_isolation,test_flood_safety,test_hydro,test_operator_access,test_field_kit,test_map_search,test_plan_timing}.py`.

## Remaining Vietnamese in owned live code

No known untranslated UI copy. Retained categories:

- Product/brands: Ngõ Ngách, Chợ Tốt; source/publisher proper names.
- Places: Chợ Bến Thành, Quận 1, Điện Biên Phủ · 475A, Phú An, sông Sài Gòn, Soài Rạp, Hẻm 160, Ngô Tất Tố, Nguyễn Hữu Cảnh, Xô Viết Nghệ Tĩnh, Bình Thạnh and street names in cached news summaries.
- Citations: `Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4`, `QCVN 41:2024/BGTVT, biển P.130/P.131a/P.131b/P.131c`, `Luật Bảo vệ dữ liệu cá nhân 91/2025`.
- Input matching/parsing: mapSearch accent normalisation; alley and motorbike-only OSM regexes; `hầm`/`cầu` legality name checks; Goong step-name regex; Google review keywords; Vietnamese news search keywords; Alonhadat HTML field names; tide bulletin extraction regexes; live street/alley-name parsing; legacy OSM source-name filters; legacy `đo tại` source prefix.
- Internal model instructions in ai.py/cameras.py/news.py remain Vietnamese where they explain Vietnamese input or schema enums. Prompts now explicitly request English free-text output while preserving place names and verbatim source quotes.
- `backend/app/experimental/night_engine/**` is an archived engine comparison implementation, not a served UI path; it was left unchanged, including its Vietnamese strings.

The comprehensive scan also uses `[À-ỹ]` because the sample regex misses uppercase and some acute-accent characters.

## Agent A / B remaining-string inventory

Full line-level inventory: `docs/eval/english-excluded-diacritics.txt` (read-only snapshot; excluded files were not edited).

- Agent A frontend: remaining accented strings are Ngõ Ngách and example destinations `Hẻm 113/4 Võ Duy Ninh`, `Hẻm 220/9 Xô Viết Nghệ Tĩnh`, `Hẻm 328 Xô Viết Nghệ Tĩnh`. No known untranslated UI copy remains at this snapshot.
- Agent A backend: `Hẻm 113/4 Võ Duy Ninh, Bình Thạnh`, `Ngô Tất Tố`, product name Ngõ Ngách; Vietnamese prompt examples and input support (`hẻm/ngõ/kiệt/ngách`, `Xe 7 chỗ`, `bán tải`, `16 chỗ`, `tối nay 7h`, `sáng mai`); legacy error detection strings `miễn phí`, `hạn mức`, `Gemini chưa`, `sau khi tự thử lại`; diacritic normalisation/guard regexes; legacy generic-name match `Trước cửa nhà`; geocoder parent query `Hẻm {parent} {street}`. These are names or internal input/compatibility code rather than untranslated UI copy.
- Agent B: `plan.py`, `width_samples.py` and `parcels.py` have no accented string hits in the snapshot. `evidence.py` retains Vietnamese keys in `ENGLISH_TEXT`, `ENGLISH_PREFIXES`, `ENGLISH_FRAGMENTS`, legacy generic-name matching, Chợ Tốt source branding, and the decision identifier `4582/QĐ-UBND`. The translation-table keys are intentional compatibility inputs. The citation adapter issue above is the required follow-up.
- Shared requested-regex scan: `docs/eval/english-diacritics-scan.txt`. This excludes the archived experimental engine and includes the live frontend/backend tree, including A/B files for the audit only.

## Final validation (11:07, UTC+07:00)

- `cd frontend && npm run build`: PASS; `dist` rebuilt. Log: `docs/eval/english-frontend-build.txt`. Existing large-chunk warning only.
- `cd frontend && npm test`: PASS, 4 tests (including Vietnamese input normalisation).
- `PYTHONPATH=backend:. python3 -m compileall -q backend/app`: PASS.
- `git diff --check` for frontend, backend app/tests, glossary, tide metadata and modified cached areas: PASS.
- `PYTHONPATH=backend:. python3 -m pytest backend/tests -q`: **327 passed, 77 skipped, 1 failed, 210 subtests passed**, 79.04 seconds. Log: `docs/eval/english-backend-tests.txt`.
- Sole remaining backend failure: `test_engine_estimate.py::EstimateTests::test_agent_compact_preserves_actual_caveats_and_never_invents_portal_disclaimer` → `agent.grounded_answer`, `stop.get('flood', {}).get('depth')` raises `AttributeError` because compact `flood` is `None`. Agent A owns this file; change the null handling to `(stop.get('flood') or {}).get('depth')` (or equivalent) and rerun. No protected files were edited here.
- Operator integration after assertion updates: 12 passed, 11 subtests passed.

No commits, pushes, manual Gemini calls or manual Goong calls were made.
