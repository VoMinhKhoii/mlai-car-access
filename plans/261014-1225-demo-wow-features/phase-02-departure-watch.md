---
phase: 2
title: "Cảnh báo giờ về"
status: pending
priority: P1
effort: "2d"
dependencies: []
---

# Phase 2: Cảnh báo giờ về

## Overview
Người dùng bấm "Tôi đã đỗ ở đây" trên một điểm dừng; app định kỳ chạy lại plan với cùng request và báo (banner + Notification) khi điểm đó không còn qua kiểm tra ngập hoặc `timing.leave_before_at` sớm hơn giờ rời đã định.

## Requirements
- Functional:
  - Lưu "phiên đỗ" trong `localStorage`: request `/api/plan` gốc (lat, lon, vehicle_id, intent, arrive_at, dwell_min, rain), toạ độ điểm dừng đã chọn, `leave_before_at` lúc lưu.
  - Kiểm tra lại mỗi 5 phút khi app mở (và ngay khi tab hiện lại `visibilitychange`); chế độ demo: 15 s.
  - Ghép điểm dừng theo toạ độ (≤ 15 m) trong `stop_points` mới.
  - Báo khi: điểm dừng mất (`verified` false hoặc biến mất), `way_out.flood.status` xấu hơn, hoặc `leave_before_at` sớm hơn. Nội dung nêu rõ đó là thay đổi dự báo, không phải đo nước.
  - Xin quyền Notification chỉ khi người dùng bấm nút; từ chối/không hỗ trợ → banner trong app.
  - Nút "Kết thúc phiên đỗ".
  - Chống spam: một thông báo cho mỗi trạng thái xấu đang liên tục hoạt động; sau khi trạng thái hồi phục, cùng loại xấu đi lần nữa được thông báo lại.

## Architecture
- Hook React `useParkingWatch` trong frontend; dùng `api.plan` sẵn có.
- Mưa: request lưu `rain` giả lập nếu có; mưa live được server lấy khi `live_hydro` bật (không đổi).
- Demo: bật mưa giả lập trên điện thoại → phiên đỗ cập nhật `rain` → lần kiểm tra kế tiếp báo. Cần UI cho phép sửa `rain` của phiên đỗ (dùng lại toggle mưa hiện có).

## Related Code Files
- Create: `frontend/src/parkingWatch.ts` (hook + so sánh trạng thái)
- Modify: `frontend/src/App.tsx` (state phiên đỗ, banner)
- Modify: `frontend/src/components/Result.tsx` (nút trong `StopRow`/`StopChecks`)
- Modify: `frontend/src/index.css`

## Implementation Steps
1. Kiểu `ParkingSession` + lưu/đọc `localStorage` (version field; dữ liệu hỏng → bỏ).
2. Hàm thuần `compareStop(prev, next) -> alert | null`; frontend chưa có test runner (không có vitest trong `package.json`) → kiểm bằng smoke script, không thêm runner.
3. Hook interval + `visibilitychange` + backoff khi `/api/plan` lỗi (giữ trạng thái cũ, hiện "không kiểm tra được lúc HH:MM").
4. Notification + banner + nút kết thúc.
5. Chế độ demo (query `?demo=1` → chu kỳ 15 s).

## Success Criteria
- [ ] Trên Android Chrome: bật theo dõi với preset khô, bật mưa giả lập → banner ≤ 60 s; nếu permission Notification được cấp thì notification hệ thống cũng tới ≤ 60 s.
- [ ] Từ chối quyền thông báo → banner vẫn hiện.
- [ ] `/api/plan` lỗi → không báo sai, hiện thời điểm kiểm tra cuối.
- [ ] Không có thông báo lặp khi trạng thái không đổi.
- [ ] Khi điều kiện xấu hồi phục rồi tái diễn → thông báo lại đúng một lần; trạng thái xấu liên tục không spam.
## Risk Assessment
- Thiết bị demo đã chốt: Android + Chrome (Validation Session 1). iOS ngoài phạm vi demo; nếu ai mở trên iOS thì chỉ có banner.
- Tab nền bị trình duyệt hãm timer → chấp nhận; kiểm tra lại khi `visibilitychange`. Nếu user cần báo khi đóng app → replan với Web Push (ngoài phạm vi).
