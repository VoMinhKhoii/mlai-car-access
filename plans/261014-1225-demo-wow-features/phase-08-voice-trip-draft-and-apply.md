---
phase: 8
title: "Voice trip draft và áp dụng thay đổi"
status: pending
priority: P2
effort: ""
dependencies: [7]
---

# Phase 8: Voice trip draft và áp dụng thay đổi

## Overview
Nói qua recorder/Gemini Audio của phase 7 hoặc gõ một câu để đổi xe, điểm đến, mục đích dừng/đỗ, giờ đến và thời gian ở lại. Transcript sửa được trước khi phân tích; chỉ bấm Áp dụng mới cập nhật form và tính Arrival Plan bằng engine hiện tại.

## Current Behavior
- `frontend/src/App.tsx:22-32,79-98,181-222` — trip nằm trong các useState; mỗi committed change tự chạy plan sau 220 ms, request mới có id/abort.
- `frontend/src/App.tsx:313-321,343-365,471-475` — `chooseDest` xóa demo scenario/story/build context; `loadPreset` batch nhiều setters; Directions nhận setters trực tiếp.
- `frontend/src/components/Directions.tsx:11-97,139-159,167-220` — PlaceField private có search/detail + generation/abort; catalogue xe, intent, datetime và dwell có UI tay. Pickup tính 15 phút, không phải quyền được phép dừng.
- `frontend/src/datetime.ts:3-29` — timestamp/toLocal/fromLocal kiểm ngày thực và diễn giải UTC+07:00, không dùng timezone máy.
- `backend/app/main.py:79-87,260-300,319-326,505-519` — Strict cấm extra; dwell integer 1..10080; timestamp timezone-aware; voice report endpoint chỉ đọc parse với deadline model 10 s, rate bucket riêng.
- `backend/app/ai.py:68-127,142-175`, `backend/app/budget.py:74-89` — multi-provider JSON wrapper đã reserve quota mỗi attempt; JSON mode hiện chưa có schema cưỡng chế; report parser chỉ hiểu confirmation/blockage.
- `backend/app/flags.py:54-58`, `backend/app/reports.py:86-98` — flag report default off và rate bucket 20/client/giờ đã có.
- `frontend/src/parkingWatch.ts:103-114,160-166` — ownership comparisons chưa có demo_scenario; cùng tọa độ nhưng fixture/real khác nhau vẫn có thể bị coi cùng trip.
Unknowns: độ chính xác trích xuất câu Việt và thời gian đáp ứng provider thật [UNVERIFIED]; cần corpus và live smoke phase 9. Không khẳng định confidence model là xác suất đúng.

## Target Change
- Create: `frontend/src/components/VoiceTrip.tsx` — panel nhập câu + draft review + giải quyết fields; dùng recorder/transcription từ phase 7, không có audio pipeline thứ hai.
- Modify: `backend/app/ai.py:142-175` — prompt/hàm trip cạnh report parser; reuse `_call` tại `68-127`, không đổi SDK/provider adapter. Report success schema giữ; failure status ở main migrate theo phase7.
- Modify: `backend/app/main.py:505-519` — thêm endpoint trip cùng vùng voice, schemas input/output có extra forbid và deterministic normalization. Giữ `/api/voice/parse` hiện tại.
- Modify: `backend/app/flags.py:54-58` — thêm `ai_voice_trip`, default false; operator toggle theo cơ chế hiện tại.
- Modify: `frontend/src/api.ts:215-231,272-288` — discriminated union trip result mới và `parseVoiceTrip(text, signal)`.
- Modify: `frontend/src/components/Directions.tsx:11-14,139-159,218-223` — tái sử dụng PlaceField bằng export có kiểu cho draft destination; thêm nút mở VoiceTrip từ Directions. Caller hiện có của Directions: `frontend/src/App.tsx:471-475`; PlaceField hiện có hai caller tại `frontend/src/components/Directions.tsx:156-159`, migrate cùng cutover.
- Modify: `frontend/src/App.tsx:22-32,91-98,160-164,181-222,313-321,471-475,606-615` — panel/context revision, apply một lần, mutual exclusion với report, stale-context guard.
- Modify: `frontend/src/index.css:474-506` — tái dùng voice field/chip/tokens cho draft, diff và trạng thái lỗi; không framework CSS mới.
- Modify: `backend/tests/test_api_validation.py:20-49,101-143,302-327` — mở rộng sandbox API hiện có cho trip validation/budget; có thể thêm test methods cùng class. Không tạo runner frontend.
- Modify: `frontend/src/parkingWatch.ts:103-114,160-166` — dùng chung so sánh ownership có demo_scenario cho cả UI mismatch và polling; rain vẫn là input được cập nhật riêng.

## Requirements Covered
V-01, V-03, V-04, V-05, V-06, V-07, V-08

## Proposed Contract (new, not implemented)
`POST /api/voice/trip/parse` accepts `{text: string}` trimmed, 1..300 chars; unknown fields → 422. No coordinates, vehicle IDs, current plan, client clock, evidence or audio accepted.

Successful response: `{kind:"trip_update", reference_at:<ISO +07:00>, patch:{...}}`. Patch contains only fields explicitly mentioned; absent means preserve committed value, null is forbidden. Empty patch → `unclear`.

| Field | Type / boundary | Resolution before Apply |
|---|---|---|
| `vehicle_query` | nonempty string ≤80 | Match normalized label/id in loaded catalogue; multiple/zero matches require choosing a real catalogue entry. Never choose first fuzzy match or infer physical specs. |
| `destination_query` | nonempty string ≤200 | Prefill draft PlaceField; search/detail through existing APIs and explicit candidate selection; model never returns lat/lon. |
| `intent` | `park` or `pickup` | Show legal meaning in review; pickup always effective 15-minute assessment. |
| `arrival` | `{mode:"now"}` or `{mode:"at", at:<complete ISO +07:00>}` | Server resolves extracted today/tomorrow/date + explicit hour/minute against reference_at; show full local date/time. |
| `dwell_min` | strict integer 1..10080 | Preserve value if absent; pickup + stated dwell other than 15 is a conflict, not silently ignored. |

Unclear response: `{kind:"unclear", question:<one bounded Vietnamese question>}`. Forbidden or unexpected model fields, invalid semantic values, missing date/hour, contradictory instructions, no-change text or mixed report+trip intents fail the entire parse to unclear; do not apply the valid-looking subset.

Raw model extraction is separately validated: confidence finite 0.75..1 (reject bool/string/NaN); allowlisted fields; arrival raw `{mode:"now"}` or `{mode:"at", day:"today"|"tomorrow"|"date", date?:"YYYY-MM-DD", hour:0..23, minute:0..59}`. `date` only with `day=date`, must include full year/month/day; validate actual calendar date and build ISO server-side using `VN_TZ`. “6 giờ” without rõ sáng/chiều or 24-hour time → unclear; “chiều mai” without giờ → unclear. Server reference captured once on request, not model/client supplied. No rollover of past dates to tomorrow. At review/apply, explicit arrival in past → require user correction/now; preserve original trip until corrected.

## Implementation Steps
1. [V-03, V-05, V-08] Add flag, typed endpoint và trip-only extraction; reuse voice admission phase7:20 requests/IP/giờ, global persistent60/giờ VN, reserve_ai mỗi attempt. Rate/concurrency/provider budget→429; missing provider/model→424; flagoff403; semantic/shape/timeout→unclear. Report parser URL/success schema giữ, failure statuses migrate theo matrix phase7. Text model deadline10 s; audio deadline15 s từ route entry gồm upload; không hứa10 s toàn flow, không thêm retry.
2. [V-03, V-05, V-08] Validate every model value and all field combinations; normalize temporal tokens deterministically. Do not claim `_call` JSON mode is schema enforcement or confidence proves intent. Reject command/tool/privilege fields. Parser cannot call `reports.submit`, geocoder, plan engine, flags or evidence writers. Add deterministic API boundary cases using existing isolated subprocess; mock provider output only to test rejection/normalization, not to claim Vietnamese comprehension.
3. [V-01, V-03, V-04, V-06] Build VoiceTrip panel anchored to Directions, not hidden under Demo. Use shared recorder → explicit Chuyển thành chữ qua Gemini → editable transcript → explicit Phân tích. Review shows old → new values and full date, unresolved fields and Áp dụng/Hủy. Reuse exported PlaceField against draft state only; require explicit candidate selection even if search has one result. Match vehicles accent/case-insensitive against full catalogue; unresolved/ambiguous needs manual select. Typed entry remains usable without microphone; audio flag/key/model off preserves typing, text parser flag/model off directs to existing manual form, not fabricated results.
4. [V-04, V-05, V-07] Snapshot committed tripKey plus monotonic edit/context revision at draft open; manual edits (including changing away and back), presets, swap, selection/context changes invalidate draft and abort pending parse/search/detail. Editing transcript invalidates parsed fields. Before Apply validate revision, flag still on, resolved destination/catalogue, timezone/calendar, dwell and intent conflict. Draft expires on Vietnam date boundary to avoid yesterday’s “tomorrow”; if it expires, require new review. Unchanged fields remain unchanged.
5. [V-03, V-04, V-07] Parent `applyVoiceTrip` synchronously batches validated setters once, then closes draft; no direct `api.plan` from panel. Destination change goes through `chooseDest` and clears fixture scenario; vehicle sets correct model/class mode, never auto-links/unlinks VETC account. All changed fields commit together or none; existing 220 ms effect computes one new trip. Mark old plan stale immediately; invalidate/abort previous plan request at commit so a response arriving during debounce cannot publish as current. Arrival-now keeps existing five-minute rounding behavior. No voice change to rain, origin, permissions, rules or safety engine.
6. [V-06, V-07] Watch vẫn bound saved session; dùng chung ownership helper cho sameTrip/sameContext, gồm demo_scenario bên cạnh lat/lon/vehicle/intent/arrival/dwell/origin; rain giữ là mutable input như hiện tại. Voice chọn lại cùng tọa độ nhưng clear fixture→contextMatches=false, hiển thị mismatch; polling dùng saved request, không migrate/end session. Close report trước trip và ngược lại, callback kiểm context. Không lưu transcript/history mới.

## Verification
- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_api_validation.py' -v` → exit 0 including existing report checks and new trip contract cases.
- New API cases: explicit today/tomorrow/date+time→đúng +07ISO frozen clock; invalid dwell/calendar/fields/confidence/mixed intent→unclear hoặc422 theo contract. Ba endpoints cùng rate/global budget, 21st cùngIP→429, global cap không bypass bằng IP mới/restart; provider budget429 và missing-provider424 không gắn nhãn semantic unclear. Không pending/evidence writes.
- `npm --prefix frontend run build` → exit 0; no new provider SDK or frontend test framework.
- UI with live or typed phrase `Đổi sang Toyota Fortuner, đỗ xe hai tiếng, đến lúc 18 giờ hôm nay`: review catalogue model + park +120 min + explicit date 18:00; choose future date/time if already past. Before Áp dụng: zero voice-triggered plan/report POST and unchanged committed inputs. After Áp dụng: one new plan request for all approved values, no report POST. “Đi ngay” uses existing arriveNow behavior.
- UI `Đổi điểm đến sang Hẻm 160 Ngô Tất Tố`: candidate selection stays draft until Apply; HCMC-only planning remains authoritative. Query error/0 candidates/outside service area do not auto-select coordinates or mutate trip.
- UI delayed parse/detail/plan + manual change/preset/close/midnight/double Apply→không stale/duplicate commit; unresolved disable Apply. Saved synthetic watch→voice chọn đúng cùng tọa độ→demo_scenario cleared, contextMatches=false, mismatch visible, polling vẫn saved session; rain không tự nhập nhầm từ current real trip.

## Acceptance Checklist
- [ ] Typed trip parser has bounded quota/flags, explicit time normalization and reject-all ambiguous contract.
- [ ] Voice/typed draft resolves real vehicle/place; Apply atomically updates only approved trip fields and recomputes once.
- [ ] No plan/report action before confirmation; stale response/context, pickup conflict and midnight cannot silently mutate trip.

## Load-Bearing Assumptions & Risks
- Current `_call` returns JSON but not provider-enforced schema — breaks if: valid JSON carries invented/extra fields → local strict validation + explicit review; never accept by confidence alone.
- Gemini may mishear address/vehicle/number yet satisfy schema — breaks if: live corpus shows silent wrong values → keep editable transcript + manual resolution/review, improve prompt/UX; no model choice guarantees correctness.
- >8 touched files justified by API/schema/flag/audio/UI/state/test boundaries; three new production files across phases 7–8 (`voice.ts`, backend `voice.py`, `VoiceTrip.tsx`), zero new services/SDKs; ffmpeg là runtime dependency có kiểm chứng. Avoid App rewrite, generalized action bus or second planner.
- New guest AI parser is an explicit bounded extension of existing voice-report exception; not authorization for other paid/operator actions — breaks if: parsed content reaches mutation endpoints → stop/replan trust boundary.
