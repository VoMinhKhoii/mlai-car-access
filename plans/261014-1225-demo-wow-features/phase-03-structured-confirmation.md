---
phase: 3
title: "Xác nhận có cấu trúc (vào/ra) + thân hẹp nhất của nhóm"
status: completed
priority: P1
effort: "2d"
dependencies: []
---

# Phase 3: Xác nhận có cấu trúc

## Overview
Mở rộng `/api/confirm`: server tự xác định đoạn chứa điểm dừng cho bound xe, tính đường ra để gắn claim cách ra; thêm lựa chọn "ra bằng cách nào"; loader dùng thân hẹp nhất của nhóm xe; plan hiển thị claim đã duyệt mà không đổi kết luận.
<!-- Updated: Validation Session 1 - way_ids do server tính (parcels.path_into/path_out), client không gửi way_ids -->

## Requirements
- Functional:
  - `Confirmation`: thay `way_ids` (client gửi) bằng `stop_lat`, `stop_lon` (điểm dừng đã chọn); thêm `exit: Literal["through","turned","reversed","unknown"] = "unknown"`. Clean cutover: bỏ field `way_ids` khỏi request, sửa caller duy nhất `App.tsx:330`.
  - Server: kiểm tra TP.HCM và cached graph; chỉ nhận stop được ánh xạ trực tiếp (≤5 m) lên way OSM `is_alley`. `path_into`/`path_out` do server tính từ tọa độ; bound chiều rộng gắn đúng đoạn cuối `path_into` chứa stop, exit claim dùng các way trên `path_out`. Stop đường lớn, bãi đỗ hoặc không map được → 422, không tạo report. Client không gửi/chọn way IDs.
  - Loader `_load_confirmations`: cận dưới tính từ `vehicles.min_body_width(vehicle_id)` (thân hẹp nhất của class; không tin `body_width` trong payload; profile không tồn tại → bỏ dòng). Cận trên giữ `mirror_width` của profile như hiện tại (xem Risk).
  - `exit != unknown` và `result != "no"` → thêm `Bound(0, OPEN_HI, "Observed", "Xác nhận sau khi đến", detail, width_basis="unknown")` vào `way_out_by_way` cho mỗi `way_out_ids` (detail: "Tài xế {label}: đi thẳng ra / quay đầu ra / lùi ra").
  - Plan: mỗi stop point có `way_out.observed` = claims của các `way_ids` trên đường ra (lấy từ `wrs[wid].way_out_claims`). Không đọc vào `strict`/`turn_verified`/`tight_exit`.
  - Frontend: form xác nhận có 3 chip kết quả vào + 4 chip cách ra; `exitShort` thêm "Có thông tin lối ra" khi `observed` có claim, tone vẫn muted/unverified như cũ.
- Non-functional: dòng `confirmations.jsonl` cũ (không có `exit`) vẫn đọc được.

## Architecture
`POST /api/confirm` (stop lat/lon) → server tính đường vào/ra, chỉ gắn bound thân xe lên đoạn chứa điểm dừng → `reports.submit("confirmation")` → operator duyệt → `_project_line` ghi `CONFIRM_FILE` → `EvidenceIndex._load_confirmations` → bound `Observed`/`width_basis="unknown"` + `way_out_claims` → `plan` gắn `way_out.observed` để hiển thị. Các claim không nâng mức xác minh tuyến.
Lưu ý: `path_out` là đường ngắn nhất hợp lệ, có thể khác tuyến tài xế đã đi; claim lối ra chỉ hiển thị, không xác minh toàn tuyến.

## Related Code Files
- Modify: `backend/app/main.py` (`Confirmation`, `confirm`)
- Modify: `backend/app/evidence.py` (`_load_confirmations`)
- Modify: `backend/app/vehicles.py` (hàm `min_body_width(pid)` dùng `_members`)
- Modify: `backend/app/plan.py` (gắn `observed` vào `way_out_output`)
- Read: `backend/app/parcels.py` (`path_into`, `path_out` sẵn có; không sửa)
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx` (`confirmArrival` gửi toạ độ điểm dừng đã chọn), `frontend/src/components/Result.tsx`
- Modify: `backend/tests/test_evidence_safety.py`, `backend/tests/test_egress_safety.py`, `backend/tests/test_api_validation.py`, `backend/tests/test_operator_access.py` (request cũ `way_ids` bị từ chối; stop ngoài HCMC → 422)

## Implementation Steps
1. `vehicles.min_body_width`.
2. Loader dùng nó; thêm claim lối ra.
3. Đổi `Confirmation` (stop lat/lon + exit); server lấy way cuối của `path_into` cho bound chiều rộng và toàn bộ way của `path_out` cho exit.
4. `plan.py` gắn `observed` (chỉ đọc).
5. Frontend: gửi toạ độ điểm dừng đã chọn + chip exit.
6. Tests.

## Success Criteria
- [x] Test: confirmation `class-l` result `in` → bound `lo == 1.94`.
- [x] Test: thêm confirmation `exit=turned` cho way trên đường ra → `_way_out` trả cùng `mode`, `strict`, `turn_verified` như không có claim; `observed` có 1 phần tử.
- [x] Test: `exit` lạ → 422; field `way_ids` từ client → 422 (extra forbid); điểm dừng ngoài area → 422.
- [x] Main road, way không phải `is_alley`, hoặc stop cách projection >5 m → 422 rõ nghĩa, không tạo pending report.
- [x] Test: report chứa đúng đoạn cuối `path_into` trong `way_ids` và toàn bộ `path_out` trong `way_out_ids`; client không gửi các ID này.
- [x] Dòng jsonl cũ không có `exit` vẫn nạp được.

## Risk Assessment
- Cận trên cho "no"/"tight" dùng `mirror_width` của profile (với class là gương **rộng nhất**) → cận trên lỏng hơn cho xe nhỏ trong nhóm, tức là hướng an toàn (claim yếu hơn). Giữ nguyên.
<!-- Updated: Validation Session 1 - sửa đánh giá rủi ro cận trên: lỏng = an toàn -->
- Xung đột với plan hardening nếu nó còn sửa `evidence.py` → rebase trước khi bắt đầu.
