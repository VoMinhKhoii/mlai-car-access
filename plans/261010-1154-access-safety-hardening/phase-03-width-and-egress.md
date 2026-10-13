---
phase: 3
title: "Width bottlenecks và legal egress"
status: completed
priority: P1
effort: ""
dependencies: [2]
---

# Phase 3: Width bottlenecks và legal egress

## Overview

Không bỏ nút thắt hẹp và không đánh đồng nguồn thửa đất với phép đo Clear Width. Chứng minh vào/ra tuân chiều đường, turning space và walk graph; giữ unknown khi dữ liệu thiếu.

## Current Behavior

- Modify: `backend/app/evidence.py:89-112,164-190,212-223,295-328` — parcel percentile/tier và same-tier review; FIELD_FILE load unconditional, by-name aliases gây leakage.
- Modify: `backend/app/parcels.py:12-15,29-33,94-126` — gap trừ cố định 1m, cuts mỗi 5m; không thực sự thấy mọi bottleneck/obstruction.
- Modify: `backend/app/plan.py:44-86,212-236,364-379,407-429,463-509`, `backend/app/vehicles.py:199-214` — routing/turn predicates chỉ numeric bound; thiếu basis/coverage guard và lot geometry proof.
- Modify: `backend/app/osm.py:119-135` — drive_degree đếm way IDs, continuous street + alley cho degree 2 thay vì T-junction.
- Modify: `backend/app/legality.py:62-110` — 5m guard phụ thuộc topology; lane-width heuristic và no-known-rule vẫn có thể Permitted.
- Modify: `frontend/src/components/Evidence.tsx:24-30,39-46`, `frontend/src/api.ts:31-38` — source/tier hiện có nhưng thiếu derived-width basis; cập nhật copy D32/D33 trong `docs/decision-log.md:281-295` sau proof.
Unknowns: thửa đất không mô tả vật cản thực tế hoặc sai số centreline; không có calibration field. One-way reverse legality không được giả định hợp lệ.

## Target Change

Range ước lượng min CỦA CÁC CUT đã quan sát, không gọi whole-segment measured minimum nếu coverage thiếu. Raw cadastral geometry Official provenance, usable-gap estimate Inferred. Derived-only hoặc sparse/uncertain width→unknown ở strict fit/routing/turn predicates; relaxed suggestions phải visibly unverified. Chỗ quay/lot gate chưa evidence→unverified/no exit, không verified sai chiều.

## Requirements Covered

R-05, R-06

## Implementation Steps

1. [R-05] Valid cuts giữ min lower/upper sample bound, không p20/p80 bỏ narrow cut. Track endpoint coverage+spacing+truncated segments cho arrival và egress; incomplete (2 cuts L/3,2L/3 hoặc60-cut cap) diagnostic only, không đủ hard-check clearance. Scan both endpoints và paths khi budget cho phép, nếu thiếu remain unknown; full cuts≤5m vẫn không chứng minh mọi obstruction. Validate finite/nonempty/matching samples; suspect centreline→review, không silently drop narrow. [1.5,4,4,4,4] không strict fits; two interior4m cuts không prove mouth2.3m passes.
2. [R-05] Add width_basis/coverage/decisive-clearance metadata ngoài top_tier; derived-only lo không thỏa fits/turn hard check. Wire fit_class→compute_fit→_usable, _evaluate door-clearance, _way_out turn_here/turn-node predicates; no strict fits/turn_here với only derived/sparse support. Measured/physical Observed support có uncertainty và clear-width basis mới decisive; review/conflict cross-tier hạ unknown. p20/p80 diagnostics only. Add evaluation-only EvidenceStore snapshot constructor/exclusion seam: exclude_measured_way_ids+normalized-name groups before by_way/by_name insertion, không public API flag; phase5 uses để held-out không leak labels.
3. [R-06] Distinct incident edges/neighbours topology independent OSM splitting. Chặn wrong-way turn/reverse trên all reversed edges±oneway; through directed search. Turn node needs width/space evidence; only junction topology→unverified/no verified turn. Lot entrance/turn/exit geometry chưa chứng minh cũng unverified, không mặc định quay đầu trong bãi.
4. [R-06] Junction restriction dùng boundary/geometry biết được; nếu chỉ biết node centreline, conservative buffer tính thêm nửa bề rộng parent road trước ngưỡng 5m, hoặc Unverified khi boundary unknown. Không tuyên bố code hiện tính từ mép đường trong khi chỉ node distance. Park/pickup legality citations giữ theo rule thật, unknown sign không được xác minh chỉ vì không thấy sign.
5. [R-06] Guard walk edge None/far: return no suitable stop với reason `missing_walk_connection`; dùng cap 35m cho nearest connection unless explicit mapped gate/path proves connector. Không vẽ một walk shortcut qua building; guard mọi dereference cùng path.
6. [R-05/R-06] New test_evidence_safety/test_egress_safety/test_plan_boundaries: bottleneck strict fits predicate (không chỉ badge), 2-wide-cuts/narrow-mouth, sparse/derived no turn_here, Measured override, cross-tier conflicts, eval exclusion by way+name, continuous/split T-junction, one-way±1, reverse30/60m, unknown-turn/lot entrance geometry, absent/far walk. Rerun tests.test_plan_timing từ phase2 sau width changes.

## Verification

- `cd backend && ../.venv/bin/python -m unittest tests.test_evidence_safety tests.test_egress_safety tests.test_plan_boundaries tests.test_plan_timing -v` → all boundary predicates và full-check timing pass; new modules create tại owning phases.
- Isolated own store/graph: [1.5,4,4,4,4] không strict fits, only2 interior4m cuts+mouth2.3m không fits/turn_here. Assert actual strict predicates, không chỉ verified=false badge; raw source+coverage trong drawer; no global/disk mutation.
- Bsk pickup preset hiển thị walk metres/legality/egress riêng; các ô “Được phép”/“Quay đầu được” chỉ hiện khi proven, unknown vẫn có citation/why. Chọn evidence shows estimated parcel vs Measured, narrow location và coverage.
- Rà primary law nguồn ở repository trước sửa legal wording. “15 phút” là dwell model, không quyền miễn cấm dừng; nếu nguồn luật phủ định Restricted policy đã khóa ở CONTEXT.md thì escalation tới user, không tự viết rule mới.

## Contract Consumers

Decisive width: `plan.py:44-51,54-75,80-86,364-379,480-507`, `vehicles.py:199-214` threshold consumer; include turn-in and lot gates. `_combine` `evidence.py:89-112`, field ingestion `:188,295-328`; all use same basis/coverage, no UI-only demotion. Evaluation exclusion seam nội bộ snapshot reused phase4; no global FIELD_FILE monkeypatch.

## Load-Bearing Assumptions & Risks

- Một cut hẹp có thể sai do centreline — breaks if: repeated survey/photo disproves cut → mark conflict, require human resolution; không lọc outlier bằng percentile (adjust).
- Không có swept-path data tại ngã ba — breaks if: width-only claim không đủ space thật → keep unverified; calibration phase 5, không nâng scope sang simulator mới (adjust).
- Phiên review trước nói “hẻm 1 làn cho dừng 15 phút” không phải pháp lý đã chứng minh. Giữ citation-based uncertainty, không lặp lại claim đó trong pitch (R-06/R-12).

## Execution Checklist

- [x] R-05: segment bottleneck + derived-width provenance + regressions.
- [x] R-06: directed egress, junction/turn/walk boundaries + UI proof.

Verified 2026-10-12: backend suite 68/68 OK; frontend `tsc` + build OK, lint warnings only; API smoke (demo address → unverified stops, far point → `missing_walk_connection`); desktop and mobile UI checked. Independent code review unavailable (provider limits). Not field-calibrated.
