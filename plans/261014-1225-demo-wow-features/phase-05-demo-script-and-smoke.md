---
phase: 5
title: "Kịch bản demo + smoke"
status: in-progress
priority: P1
effort: "1-2d"
dependencies: [1, 2, 4]
---

# Phase 5: Kịch bản demo + smoke

## Overview
Chốt kịch bản 3 × 90 s trên khu demo, chạy thử trên laptop + điện thoại, và kiểm mọi fallback khi mất mạng/Gemini.

## Requirements
- Kịch bản cố định: một điểm đến trên khu demo (`DEMO_CENTER`), một xe (vd. Fortuner/`class-l` để ra kết quả "chật/không quay được"), giờ đến trùng triều cao.
  1. Laptop: chọn điểm dừng → bóng xe + khoảng hở → hoạt ảnh quay đầu hoặc "không quay được".
  2. Điện thoại: "Tôi đã đỗ ở đây" → bật mưa giả lập → thông báo "rời trước HH:MM".
  3. Điện thoại: nói xác nhận → thẻ xem lại → gửi → laptop (operator) duyệt → evidence panel hiện claim "Lối ra".
- Live: một địa chỉ ngoài khu demo chạy được (#1, #2); nếu Overpass chậm thì nói rõ và quay về kịch bản.
- Fallback: chặn mạng tới Gemini → #4 dùng chip; #1, #2 không bị ảnh hưởng.

## Related Code Files
- Create: `docs/demo-script.md`

## Implementation Steps
1. Viết `docs/demo-script.md` (bước, câu nói, kết quả mong đợi, fallback).
2. Smoke laptop (Chrome) + Android Chrome qua LAN; quay màn hình làm bằng chứng vào `plans/261014-1225-demo-wow-features/reports/`.
3. Chạy `pytest backend/tests` và build frontend.
4. Chạy lại kịch bản với Gemini bị chặn.

## Success Criteria
- [ ] 3 kịch bản mỗi cái ≤ 90 s, chạy 3 lần liên tiếp không lỗi.
- [x] Ảnh/clip smoke lưu trong reports của plan.
- [ ] `pytest` xanh, `npm run build` xanh.

## Risk Assessment
- Mạng hội trường yếu → toàn bộ kịch bản chạy trên backend local + cache khu demo; điện thoại nối hotspot laptop.
