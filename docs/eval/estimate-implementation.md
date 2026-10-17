# Ngõ Ngách estimate implementation — 17 October 2026

Implemented in the shared working tree, **no commit**. No portal calls were made by this implementation/verification task. Parallel official-data and imagery modules were not edited; their small evidence.py hooks were retained. The live 8787 server was restarted with the exact demo-day environment from agent-vertex-report.md; 8788 is the cached-only review server.

## Validation

- Backend: **123 passed, 3 warnings, 38 subtests passed in 20.72s**. This includes the inherited engine safety tests plus 15 estimate regressions.
- Extended suite: **1 failed, 194 passed, 4 warnings, 59 subtests passed in 53.02s**. The sole failure is `pipelines/test_crawl_city.py::CityCacheTests::test_warm_path_keeps_destination_deep_scan_and_preserves_existing_deep`: its pre-existing SimpleNamespace graph lacks `edges`, required by the existing junction-exclusion code in parcels.measure_area. This task did not edit parcels.py or weaken the survey gate.
- `npm run build` passed and frontend/dist was rebuilt. `npm run lint` exited successfully with existing React fast-refresh/purity warnings. Vite retains the existing bundle-size warning.
- Frozen audit: **1500/1,500 plans**, **3000** ordered size comparisons, **3750** offered stops. All required invariant counts are zero: `{"crashes": 0, "plan_monotonicity": 0, "door_monotonicity": 0, "fit_monotonicity": 0, "reported_walk_over_cap": 0, "walk_geometry_over_cap": 0, "walk_geometry_mismatch": 0, "stop_not_ok": 0, "stop_fit_no": 0, "stop_exit_none": 0, "stop_reverse_over_60": 0, "verdict_inconsistent": 0}`.
- Original engine source-file fingerprints stable across final sweep: **True**. The original 300 coordinates/intents and five profiles were reused; graph/range objects were fixed per cached cell within the sweep. This is a software invariant check, not field accuracy validation.
- HTTP/UI: all six demo vehicle cases plus five seeded random cached destinations checked through the real /api/plan on 8788. Screenshots below use production components. The review-only Demo menu supplies exact frozen coordinates/times; responses are not replaced. Unknown Way Out badges were inspected as `tag muted`; unknown flood renders “Chưa rõ ngập”, and legal Unverified renders “Không thấy quy định cấm đã biết”.
- MCP: real stdio bridge → HTTP engine checked Fortuner, VF 3 and Restricted pickup; structured verdict estimate, verification, caveats and citations preserved in estimate-mcp-proof.json.
- Gemini: **8 paid attempts**, **$0.086079** recorded by the existing ledger, no free calls for these checks. Per-call provider usage/charges are in estimate-paid-calls.jsonl. Rejected HTTP 429 attempts are included and charged zero under the ledger policy. The parallel imagery job’s spending is excluded from this task total. These are ledger charges, not a provider invoice.
- The initial normal Vertex conversation completed the Fortuner question and VF 3 follow-up; exact signed function-call parts survived the follow-up. The final follow-up was rechecked after the detour fix; see the retained NDJSON event evidence and any rejected attempt artifact. No standalone Gemini transport was used.

## Verdicts, verbatim before → after

| Case | Before | After | Screenshot |
|---|---|---|---|
| Hẻm 113/4 Võ Duy Ninh, Bình Thạnh · toyota-fortuner | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Đường Võ Duy Ninh, đi bộ 39 m — độ tin cậy thấp | [113-fortuner](estimate-113-fortuner.png) |
| Hẻm 113/4 Võ Duy Ninh, Bình Thạnh · vinfast-vf-3 | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Đường Võ Duy Ninh, đi bộ 39 m — độ tin cậy thấp | [113-vf3](estimate-113-vf3.png) |
| 220/9 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Hẻm 220/9 Xô Viết Nghệ Tĩnh, đi bộ 6 m (khá chật) — độ tin cậy trung bình | [220-vios](estimate-220-vios.png) |
| 220/9 · toyota-fortuner | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Hẻm 220/9 Xô Viết Nghệ Tĩnh, đi bộ 6 m (khá chật) — độ tin cậy trung bình | [220-fortuner](estimate-220-fortuner.png) |
| 220/9 · vinfast-vf-3 | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Hẻm 220/9 Xô Viết Nghệ Tĩnh, đi bộ 6 m (khá chật) — độ tin cậy trung bình | [220-vf3](estimate-220-vf3.png) |
| 328 · vinfast-vf-5 | Chỉ có điểm dừng hạn chế theo luật | Luật cấm dừng tại Hẻm 306 Xô Viết Nghệ Tĩnh — độ tin cậy cao | [328-vf5](estimate-328-vf5.png) |
| Điểm cache 10.812_106.692 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Có thể vào tận cửa — độ tin cậy thấp | [random-1](estimate-random-1.png) |
| Điểm cache 10.764_106.668 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Nên dừng đón/trả ở Nguyễn Tiểu La, đi bộ 4 m — độ tin cậy thấp | [random-2](estimate-random-2.png) |
| Điểm cache 10.792_106.660 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Ước tính vào tận cửa khá chật — độ tin cậy thấp | [random-3](estimate-random-3.png) |
| Điểm cache 10.788_106.668 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Có thể vào tận cửa — độ tin cậy thấp | [random-4](estimate-random-4.png) |
| Điểm cache 10.764_106.608 · toyota-vios | Chưa đủ bằng chứng để khẳng định | Nên đỗ ở Hẻm 132/21 Mã Lò, đi bộ 60 m — độ tin cậy thấp | [random-5](estimate-random-5.png) |

Both 113/4 vehicles now use a plausible approach to the same 39 m stop. VF 3 no longer gets a negative estimate merely because its larger permissive graph contains a shorter doubtful bottleneck. Neither vehicle is advised to park at the door; the door’s prohibition/citation remains visible. No 224 m reversing instruction is emitted. 220/9 remains medium confidence with incomplete whole-way/flood/legal coverage. 328 states the stopping prohibition and citation, with no stopping advice.

## Confidence / limitations

The exact policy is [D50](../decision-log.md). Fits/tight/no/unknown are best hypotheses; verified remains the strict engine result. High positive confidence requires complete strong width coverage plus strict entry/exit, passable model flood, affirmative legality and verified walking. Sample support on at least half the traversed metres can support medium confidence; unknown checks cap it. The displayed sample-supported fraction counts way-associated observations, not continuously measured metres. Strong cited prohibitions or measured/official own upper bounds below the vehicle need stay hard negatives. Planning right-of-way metadata never supplies current Clear Width. No field-calibrated probability or swept-path/hydrology accuracy is claimed.

## Changed files

| File | Before | After |
|---|---|---|
| `CONTEXT.md` | Old missing-evidence / Permitted glossary | Best-estimate vocabulary; affirmative legal coverage |
| `backend/app/plan.py` | Blanket unverified headlines | Per-stop/verdict estimates, path coverage, ordinal confidence; plausible detour search with original Hard Checks |
| `backend/app/evidence.py` | Partial measurements retained only as intervals | Separate sampled/stated estimate_m; no positive lower guarantee added; parallel hooks preserved |
| `backend/app/agent.py` | Fixed cadastral disclaimer; incomplete compact verification | Estimate + actual caveats and all legal rules; canonical plan prose, signed-history guard; no Restricted advice |
| `backend/tests/test_engine_estimate.py` | No estimate rubric/property fixtures | 15 offline regressions, including 250 randomized narrower-vehicle comparisons and progressive same-value evidence |
| `frontend/src/api.ts` | No estimate / unknown flood contract | Estimate types; unknown flood and null depths; manoeuvre status and tool-result estimate |
| `frontend/src/components/Result.tsx` | UI replaced engine headlines; unknown exit could be green | Engine headline + confidence/basis; muted unknown exit/flood; affirmative-only legal badge |
| `frontend/src/components/Agent.tsx` | No explicit confidence in answer header | Persist/show confidence from actual tool-result estimate |
| `frontend/src/App.tsx` | Restricted list called stopping suggestions | Restricted list headed “Các vị trí đã kiểm tra” |
| `frontend/src/index.css` | No estimate typography | Compact basis and stop-row spacing using existing tokens |
| `mcp/protocol.py` | Generic uncertainty instruction | Estimate/confidence/basis contract; explicit unknown and Restricted handling |
| `docs/decision-log.md` | No precise estimate confidence policy | D50 rubric, thresholds, coverage semantics and invariants |
| `pipelines/serve_cached_estimate.py` | No isolated live-like review harness | 8788 real app/agent with cached-only builds and portal/Overpass denial; shared-ledger calls capped at ten across restarts |
| `pipelines/verify_estimate_sweep.py` | Random cell selection can move with crawler | Reuse original 300 frozen points; freeze graph/ranges per cell while calling audit_algorithm.sweep |
| `frontend/dist/` | Previous frontend bundle | Rebuilt production assets, current HTML points to the new hash |

Verification artifacts: estimate-before.json, estimate-after.json, estimate-http.log, estimate-agent-*.json, estimate-paid-calls.jsonl, estimate-mcp-proof.json, estimate-backend-tests.txt, estimate-all-tests.txt, estimate-frontend-build.txt, estimate-sweep/{audit-sweep.json,summary.json}, estimate-sweep.log, estimate-live-restart.json and estimate-*.png. The agent screenshot replays actual HTTP events into the normal local history UI, without another inference call.

Commands: `PYTHONPATH=backend:. python3 -m pytest backend/tests -q`; `PYTHONPATH=backend:. python3 pipelines/verify_estimate_sweep.py`; `cd frontend && npm run build`. The review harness command and live restart evidence are in the respective artifact files.
