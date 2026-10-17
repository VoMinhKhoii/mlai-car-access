---
phase: 1
title: "UI input và truthful copy"
status: completed
priority: P1
effort: ""
dependencies: []
---
# Phase 1: UI input và truthful copy

## Overview

Loại crash do ngày giờ chưa hoàn chỉnh, giữ trip committed ổn định; lời kết luận không mạnh hơn evidence và tên nguồn không sai. [Plan](./plan.md), R-01/R-02.

## Current Behavior

- Modify: `frontend/src/components/Directions.tsx:133-141` — datetime-local cập nhật thẳng state mỗi lần sửa; `:19-49` — autocomplete không request generation hoặc keyboard selection.
- Modify: `frontend/src/App.tsx:13-15,74-105,335-340` — nối string datetime rồi truyền vào plan/timeline chưa kiểm tra invalid date; ErrorBoundary hiện chỉ bao MapView ở `:255-268`.
- Modify: `frontend/src/components/TideTimeline.tsx:9-13,37-44,73-75,106-110,139-145` — toISOString với NaN văng exception; latest reading có thể không thuộc ngày demo.
- Modify: `frontend/src/components/Result.tsx:33-37,127-132,163-164,193-208,214-230` — unverified ghi “Chắc nhất”; `minutes || 1` biến 0 thành 1; source Goong hardcoded; ul nằm trong p.
- Modify: `backend/app/main.py:146-177,361-381` — arrive_at/depart_at str parse trực tiếp; invalid date trả 500.
- Modify: `backend/app/plan.py:269-275,634-686,688-708` — standard route có fallback OSM nhưng fallback thiếu source.
- Modify: `frontend/src/api.ts:40-69,116-141` — shared result/request contracts; cần source và field lỗi có kiểu.
- Modify: `frontend/src/index.css:70,287-308` — error line và mobile sheet có sẵn; reuse, không redesign.
- Modify: `backend/app/config.py:6-21` — STORE/CACHE/FLAG_FILE paths bound lúc import, chỉ VERCEL có redirect; tạo isolation seam trước viết tests API.
Unknowns: thao tác native datetime theo browser khác nhau; acceptance cần desktop Chrome và viewport mobile, không tuyên bố đã test thiết bị thật.

## Target Change

Draft datetime nằm ở Directions, commit chỉ khi parse hợp lệ có timezone VN; lỗi inline giữ draft cho người sửa và trip cuối cùng chỉ rõ chưa cập nhật. Server dùng typed timezone-aware datetime và 422 cho input sai; không fallback now cho giá trị invalid. Source route explicit enum `osm|goong` và label theo source thật.

## Requirements Covered

R-01, R-02

## Implementation Steps

1. [R-01] Tách draft/committed datetime; khi Xong chỉ commit giá trị hợp lệ, empty/partial có lỗi aria-live và focus field. Giữ auto-plan cho input committed khác; không gửi date lỗi. Cô lập timeline qua ErrorBoundary hiện có, nhưng vẫn guard input trước date arithmetic.
2. [R-01] Validate arrive_at và corridor depart_at tại Pydantic boundary: null là now, malformed/naive datetime là 422, không sửa hộ thành giờ khác. Cập nhật api.ts để contract giữ ISO timezone; kiểm tra số duration hữu hạn/dương trong cùng request boundary.
3. [R-02] Gán source `osm` cho `_standard_route`, `goong` cho Goong result; cập nhật MapView labels tại `frontend/src/MapView.tsx:123-127` và layers menu `App.tsx:445-467` để không gọi OSM là Goong. Result dùng wording “Gợi ý chưa xác minh”, không “Chắc nhất”; các khoảng cách/thời gian zero không làm tròn ép thành 1 phút.
4. [R-02] Search dùng generation + AbortController, combobox/listbox/option semantics, ArrowUp/Down/Enter/Escape, selection giữ focus; error và no-result khác nhau. Không nhận response query cũ sau clear/blur/unmount. Thay container Check từ p sang div khi chứa list, giữ typography CSS.
5. [R-01/R-02] Thêm startup path overrides VAODUOC_STORE/VAODUOC_CACHE/VAODUOC_FLAGS trong config, resolve before any leaf-module import. Create backend/tests/test_api_validation.py; fixtures boot isolated app subprocess với TemporaryDirectory env trước import (derived ai/budget/cameras/evidence/flood paths phải cùng temp root), không patch config.STORE muộn. Cases invalid/naive date, null-now, HCMC422/unknown-vehicle404, invalid duration. Smoke browser bắt crash/copy/keyboard, không thêm frontend test framework cho wiring.

## Verification

- `cd backend && ../.venv/bin/python -m unittest tests.test_api_validation -v` → malformed/naive datetime 422; null valid; không 500. Module mới là output của bước 5, chưa tồn tại lúc planning.
- `npm --prefix frontend run build` → exit 0. Final full checks chỉ chạy sau integration, không chạy mỗi mid-edit.
- Bsk: start/debug/navigate/observe theo plan.md. Chọn pickup preset, mở giờ đến, xoá năm rồi blur/Xong: UI còn nguyên, lỗi inline, không POST /api/plan với datetime lỗi. Sửa lại rồi commit: đúng giờ mới.
- Search “Hẻm 328”: ArrowDown/Enter chọn option đang focus; clear trong khi search chạy không mở lại kết quả cũ.
- Goong absent: “Tuyến OSM”/“tuyến tham chiếu OSM”; Fortuner unverified không “chắc nhất”; stop 0 m hiển thị 0 phút. Screenshot desktop và iphone-14; console không Invalid time value hoặc invalid DOM nesting.

## Load-Bearing Assumptions &amp; Risks

- Native input có trạng thái partial/empty — breaks if: browser chỉ phát event rỗng → xử lý empty như invalid draft, không parse trong render (adjust).
- Existing timing có thể trả dwell ngoài options select — breaks if: đặt giờ rời không khớp 30/60/120/180/240 → thêm option đúng duration đã commit, không âm thầm đổi (R-01, adjust).
- Copy pháp lý trước gọi 15 phút là quyền được dừng: không xem đây là quyền do luật cấp; phase 3 rà rule/nguồn, UI giữ “thời gian kiểm tra dự kiến”, không khẳng định miễn trừ (R-02).
- Accepted D4: pre-import isolated state paths là prerequisite tests, không đợi phase4; production defaults vẫn giữ tới hosting cutover phase5.

## Execution Checklist

- [x] R-01: committed date + server validation + regression.
- [x] R-02: source/copy/zero/keyboard và bsk proof.

