---
phase: 4
title: "Báo bằng giọng nói"
status: pending
priority: P2
effort: "2d"
dependencies: [3]
---

# Phase 4: Báo bằng giọng nói

## Overview
Nút micro trên màn hình kết quả: người dùng nói tự nhiên ("vào được nhưng phải gập gương, ra phải lùi" / "đầu hẻm có ba gác chắn"); app chuyển thành `confirmation` (schema phase 3) hoặc `blockage`, cho người dùng xem lại rồi gửi. Mọi report vẫn pending chờ duyệt.

## Requirements
- Functional:
  - STT bằng Web Speech API (`SpeechRecognition`/`webkitSpeechRecognition`, `lang="vi-VN"`); không hỗ trợ → ô gõ chữ.
  - `POST /api/voice/parse` (`text ≤ 300`) → intent chuẩn hoá. Dùng quota riêng cho parser (20 lần/client/giờ, không tiêu quota gửi report) và deadline tổng 10 s kể cả xoay key; provider lỗi/hết quota/quá deadline/cấu trúc sai → `unclear`. Kết quả qua cổng deterministic với confidence ≥ 0.75.
  - Frontend hiển thị thẻ xem lại dạng chip đã điền sẵn (sửa được); người dùng bấm "Gửi" mới gọi `/api/confirm` hoặc `/api/blockage`. Không bao giờ tự gửi.
  - Hỏi lại tối đa 1 lần khi `unclear` (giống Waze hỏi lại).
  - Flag `ai_voice_report` trong `flags.AI_FEATURES` (default False); tắt → chỉ chip/ô gõ.
  - Lỗi model/quota hoặc phản hồi provider sai cấu trúc (ví dụ danh sách candidate rỗng) → `unclear` + chip thủ công, không 500.
- Non-functional: không lưu audio; text chỉ gửi tới endpoint parse; không đưa text tự do vào evidence (chỉ trường đã chuẩn hoá; `reason` blockage ≤ 200 ký tự như schema cũ).

## Related Code Files
- Modify: `backend/app/ai.py` (prompt + hàm `parse_voice_report`)
- Modify: `backend/app/flags.py` (`ai_voice_report`)
- Modify: `backend/app/main.py` (endpoint, `Strict` model)
- Create: `frontend/src/components/VoiceReport.tsx`
- Modify: `frontend/src/api.ts`, `frontend/src/App.tsx`, `frontend/src/index.css`
- Modify: `backend/tests/test_api_validation.py` (parse: flag tắt, quota hết, text dài)

## Implementation Steps
1. Prompt phân loại tiếng Việt + schema JSON; ánh xạ sang `result`/`exit`/`reason`.
2. Cổng deterministic + fallback lỗi model.
3. Endpoint + rate limit + flag.
4. Component micro → xem lại → gửi; fallback gõ chữ/chip.
5. Tests (mock `ai._call`).

## Success Criteria
- [ ] Câu "vào được nhưng phải gập gương, ra phải lùi" → thẻ xem lại `tight` + `reversed`; gửi → report pending.
- [ ] Câu "đầu hẻm có xe ba gác chắn" → `blockage` với reason chuẩn hoá.
- [ ] Flag tắt, Gemini lỗi hoặc provider trả danh sách candidate rỗng/sai cấu trúc → chip thủ công, không lỗi 500.
- [ ] 20 lần parse không tiêu quota gửi report; parse thứ 21 trong một giờ bị 429.
- [ ] Deadline model tổng ≤ 10 s; deadline hết hạn vẫn trả `unclear`, không HTTP 500.
- [ ] Không request nào gửi report khi người dùng chưa bấm "Gửi".

## Risk Assessment
- Thiết bị demo đã chốt: Android + Chrome (Validation Session 1). Trình duyệt không có `SpeechRecognition` → ô gõ chữ.
- Quota Gemini thấp (`cameras.py` ghi ~20 req/key/ngày cho flash) → demo dùng model lite trong `CAMERA_MODELS` hoặc key riêng; đo số call trước buổi demo.
