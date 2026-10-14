---
phase: 1
title: "Bóng xe + mô phỏng quay đầu"
status: pending
priority: P1
effort: "3d"
dependencies: []
---

# Phase 1: Bóng xe + mô phỏng quay đầu

## Overview
Khi chọn một điểm dừng, map vẽ thân xe đúng tỉ lệ đặt trong dải bề rộng `lo..hi` của way đó, và (khi đường ra là `turn_here`/`reverse`) phát hoạt ảnh quay đầu từ mô phỏng `k_turn` ở bề rộng `lo`.

## Requirements
- Functional:
  - Polygon xe theo đúng thành viên được mô phỏng: `body_width`, `mirror_width`, `length`; pose từ simulator đặt tại tâm cầu sau nên client cộng offset tâm thân do endpoint trả về.
  - Dải bề rộng: hai đường biên cách tâm `lo/2`; nếu `hi` hữu hạn, thêm biên mờ `hi/2`. Nét đứt khi `fit.width_range.decisive_clearance=false`.
  - Nhãn: khoảng hở mỗi bên `(lo - mirror_width)/2` m; "Mô phỏng · chưa phải bằng chứng" + tier.
  - Mô phỏng quay đầu: pose từ `k_turn` ở `D = lo`; endpoint tìm tối đa 9 nhịp; hiển thị đúng số nhịp hoặc "Mô hình không tìm thấy quỹ đạo trong giới hạn 9 nhịp". `three_point_width` chỉ là ngưỡng ổn định cho tối đa 3 nhịp, không được dùng để khẳng định không quay đầu ở bề rộng nhỏ hơn (mô phỏng không đơn điệu).
- UX: kết quả mới tính mặc định thu gọn chi tiết stop. Màn hình đầu ưu tiên verdict, điểm dừng, tag fit/ra/ngập/luật; chi tiết luôn mở được, không xoá bớt evidence. Sources, trạng thái khu vực, tuyến tham chiếu và giới hạn triều hiển thị ngắn, có disclosure.
- Non-functional: không đổi output `/api/plan`; endpoint mới chỉ đọc; tôn trọng `prefers-reduced-motion` (hiện pose cuối, không animate).
- Ngoài phạm vi: cung rẽ vào ở đầu hẻm (`min_alley_for_turn_in`). <!-- Updated: Validation Session 1 - user chọn giữ 2 hình -->

## Architecture
- `geometry.k_turn` (`geometry.py:67-105`) đã tính `(x, y, psi)` từng bước rồi bỏ. Tách lõi mô phỏng thành một hàm sinh pose; `k_turn` giữ API cũ bằng cách dùng hàm đó (không nhân đôi logic).
`GET /api/vehicles/{vehicle_id}/maneuver?width=<m>` → `{vehicle_id, width_m, moves, length_m, vehicle_length_m, vehicle_mirror_width_m, body_center_offset_m, poses, frame:"corridor"}`. Với `class`, mô phỏng một thành viên ứng với `three_point_width` lớn nhất và trả kích thước cùng thành viên đó. Width < 1.5 m chưa gọi endpoint; pose tối đa 120. Cache LRU theo vehicle và cm.
- Frontend: hàm chiếu hệ corridor → lat/lon quanh điểm dừng theo bearing way (đoạn way gần nhất trong `plan.layers.fit`). Source/layer MapLibre mới `footprint`, `maneuver`. Playback bằng `requestAnimationFrame`.

## Related Code Files
- Modify: `backend/app/geometry.py` (hàm sinh pose; `k_turn` dùng lại)
- Modify: `backend/app/vehicles.py` (chọn member worst-case cho class — tái dùng logic của `three_point_width`)
- Modify: `backend/app/main.py` (endpoint maneuver, `Strict`/`Field` bounds width 1.5–15)
- Modify: `frontend/src/api.ts` (type + call)
- Modify: `frontend/src/MapView.tsx` (sources/layers `footprint`, `maneuver`, playback)
- Modify: `frontend/src/App.tsx` (load maneuver for selected stop and pass to map)
- Modify: `frontend/src/index.css`
- Create: `backend/tests/test_maneuver.py`

## Implementation Steps
1. Refactor `k_turn` thành generator pose + wrapper giữ nguyên `(moves, length)`; chạy `min_width_for_moves` cũ để chắc kết quả không đổi.
2. Endpoint maneuver + cache + validate width.
3. Frontend: tính bearing tại điểm dừng, vẽ dải bề rộng và polygon thân xe.
4. Playback pose, nút phát lại, reduced-motion.
5. Nhãn trung thực (tier, nét đứt, "mô phỏng").

## Success Criteria
- [ ] `min_width_for_moves`/`three_point_width` cho kết quả y hệt trước refactor (so trên toàn catalogue).
- [ ] `/api/vehicles/toyota-fortuner/maneuver?width=1.5` trả `moves: null`; width 12 trả pose ≤120. Không suy ra bất khả thi chỉ từ so sánh với `three_point_width`.
- [ ] Trên khu demo: chọn điểm dừng → bóng xe ≤ 1 s; hoạt ảnh chạy; nét đứt khi không decisive.
- [ ] Thân xe overlay dùng đúng kích thước/offset của profile mô phỏng; pose wall-origin phải chuyển về tâm corridor (`x - width/2`) trước khi vẽ. Test pose xác nhận `0 ≤ x ≤ D`.
- [ ] Kết quả mặc định gọn, thẻ stop thu gọn sau mỗi plan/đổi lựa chọn; mở thẻ vẫn thấy đủ nội dung hiện có.
- [ ] `/api/plan` không đổi các kết luận access/fit/flood/legality do maneuver overlay; `/api/plan` có thể mở rộng additive bằng `way_out.observed` theo Phase 3, chỉ hiển thị claim đã duyệt.

## Risk Assessment
- Hẻm cong/nút giao: mô phỏng hành lang thẳng sai hình học → luôn nhãn "mô phỏng hành lang thẳng", chỉ đặt ở đoạn thẳng gần nhất. Tín hiệu hỏng: polygon cắt qua nhà trên nền map → giảm về chỉ vẽ dải + thân xe, bỏ hoạt ảnh.
- Mô phỏng chậm ở width lớn → cache + giới hạn width; đo ≤ 300 ms.
