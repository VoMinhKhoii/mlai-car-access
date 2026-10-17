---
phase: 7
title: "Gemini audio và ngữ cảnh báo cáo"
status: pending
priority: P1
effort: ""
dependencies: [4]
---

# Phase 7: Gemini audio và ngữ cảnh báo cáo

## Overview
Thay SpeechRecognition bằng thu âm ngắn qua MediaRecorder và Gemini Audio ở backend; transcript được sửa trước khi phân tích báo cáo hoặc chuyến đi. User đã chọn Gemini, sẽ cung cấp key sau; không cần key để hoàn thiện plan, nhưng live acceptance không thể đóng khi thiếu key/model access.

## Current Behavior
- `frontend/src/components/VoiceReport.tsx:20-38,59-62,92-127` — SpeechRecognition `vi-VN` đặt trong component; cleanup gọi stop, chưa có context/generation guard cho kết quả trễ.
- `frontend/src/components/VoiceReport.tsx:64-89,101-112,129-146,160-170` — nhận transcript là tự parse khi flag bật; parse chưa kiểm transcript revision/stop identity. Chỉ bấm Gửi mới submit nhưng chưa khóa gửi lúc đang nghe.
- `frontend/src/App.tsx:421-434,606-615` — report dùng selected stop/vehicle; component chưa key theo identity của điểm dừng.
- `frontend/src/api.ts:263-264,286-290` — JSON post hỗ trợ signal; parseVoice chưa nhận signal, chưa có audio API.
- `backend/app/main.py:50-55,459-463,505-519,618-630` — có origin guard, voice quota, mẫu capped-upload + threadpool cho AI ảnh; chưa có audio endpoint.
- `backend/app/ai.py:48-65,68-127`, `backend/app/budget.py:74-89` — có Gemini keys/rotation, JSON extraction và per-attempt budget; `_call` hiện nhận image, không có audio API chuyên biệt.
- `backend/app/flags.py:54-58`, `requirements.txt:1-7` — report flag default off, httpx và multipart đã có; chưa có flag audio/model riêng. Host hiện có ffmpeg; deployment khác chưa kiểm.
- `backend/app/main.py:522-535`, `frontend/src/App.tsx:430-434,599-601,809` — blockage chỉ kiểm way thuộc cached area, bỏ tọa độ khỏi payload; report từ stop đang gửi tọa độ destination; queue chỉ hiện reason/way/date.
- `backend/app/reports.py:38-41,86-98` — giới hạn hiện tại là20/IP/giờ trong RAM, reset khi restart; không phải danh tính người dùng hay auth.
Unknowns: key/tier/model audio do user cung cấp sau, quality tiếng Việt và latency thật [UNVERIFIED]. Không dùng key khác trong máy để tự chạy live.

## Target Change
- Create: `frontend/src/voice.ts` — hook recorder dùng chung, giới hạn clip và hủy/cleanup; không framework voice.
- Create: `backend/app/voice.py` — module hàm decode/normalize và Gemini transcription có bounds/semaphore; không service/queue mới.
- Modify: `frontend/src/components/VoiceReport.tsx:20-38,59-127,129-146,149-199` — xóa SpeechRecognition types/handlers; recorder → explicit Chuyển thành chữ → transcript sửa được → explicit Phân tích → review → Gửi.
- Modify: `frontend/src/api.ts:16-28,263-264,288-290` — Config thêm voice_audio metadata, transcribeVoice(blob, signal), parseVoice(signal); migrate parse calls `frontend/src/components/VoiceReport.tsx:85,108`. Blockage giữ body lat/lon/way_id/reason nhưng tọa độ phải khớp way được server xác minh.
- Modify: `frontend/src/App.tsx:430-434,599-601,606-615,809` — context identity/audioEnabled; gửi stop coordinates cho report, giữ click-point cho EvidencePanel và show server-mapped location trong queue.
- Modify: `backend/app/main.py:145-163,447-456,505-535` — config public readiness metadata không secret, async audio route/shared status matrix và blockage projection≤5m trước pending.
- Modify: `backend/app/flags.py:54-58` — `ai_voice_input` default false, operator bật qua cơ chế hiện tại.
- Modify: `backend/tests/test_api_validation.py:20-49,101-143,302-327` — API audio bounds/failure/quota, sandbox state và fake provider; không gọi Gemini thật trong suite.
- Modify: `backend/app/budget.py:18-20,74-89` — persistent global voice-request counter60/giờ VN, tái dùng lock/atomic storage/fail-closed; độc lập per-key/model attempt caps.
- Modify: `backend/tests/test_budget_limits.py:22-89`, `backend/tests/test_operator_access.py:195-199` — global voice cap/restart/corruption/multi-IP và blockage coordinate mismatch/queue payload; giữ rate limit trước graph.

## Requirements Covered
V-01, V-02, V-06, V-07, V-08

## Proposed Audio Contract (new, not implemented)
- `POST /api/voice/transcribe`: raw audio bytes; Content-Type lấy từ recorder.mimeType, không JSON/base64 hay URL/file path từ client. Browser chọn `audio/webm;codecs=opus`, kế đến `audio/ogg;codecs=opus` theo isTypeSupported; không có format chung thì gõ tay. Không đổi MIME một blob để giả format khác. iOS audio/mp4 chưa cam kết hỗ trợ trong phạm vi Android Chrome.
- Client auto-stop sau 19 s, tối đa 1 MiB; server capped-stream ≤1 MiB, container/MIME allowlist + decoder xác nhận; decode tối đa 21 s rồi reject nếu PCM thực >20 s, không tin duration client/metadata. Normalize mono PCM 16 kHz → WAV memory. Không cắt phần lời thừa rồi lặng lẽ chấp nhận.
- Bộ decode dùng ffmpeg, argv cố định (không shell), input/output pipes, protocol whitelist chỉ pipe, không URL/filename user, không video; timeout3 s và output bound21×16000×2 bytes. Không log audio. Thiếu ffmpeg→424; operator cài binary và preflight decode clip browser thực trước demo. App read/decode limits là bắt buộc dù không có proxy; ingress bổ sung do deployment operator sở hữu, không coi reverse proxy chưa cấu hình là lớp bảo vệ sẵn có.
- Response matrix chung transcription/report-parse/trip-parse: flag off403; per-IP/global rate, busy, persistent budget hoặc provider429→429; thiếu key/model/decoder424; body rỗng422; quá bytes413; MIME/container/decode sai415; quá duration422; slow upload quá deadline408; semantic/provider-shape hoặc pipeline timeout sau body→200 unclear. Migrate report endpoint và tests cũ từ NoModel/OverBudget→unclear sang424/429; giữ URL và success schema. Không log body/transcript; Cache-Control no-store.
- Success `{kind:"transcript", text:<trimmed Vietnamese ≤300 chars>}`; silence/unclear/overlong text→unclear, không truncate rồi parse một phần. Input/quota/config errors theo matrix, UI nêu đúng lỗi thay vì “không hiểu” và không tự retry.
- Ba flag audio/report/trip độc lập default off. Ba endpoint chia sẻ20 requests/IP/giờ trong RAM và thêm persistent global60 requests/giờ VN (`STORE/voice_usage.json`, fixed hourly bucket); global counter qua lock+atomic write, restart không reset, file hỏng fail-closed429. Flag/config kiểm trước reserve; không refund requests đã nhận. Global cap áp mọi IP/kể cả client không Origin; IP từ proxy chỉ tin đúng trusted-proxy config README, không coi Origin là auth. Không thêm account/token; chấp nhận denial-of-service trong ceiling, không hứa fairness/danh tính. Audio→parse thường2 slots; mỗi upstream attempt vẫn reserve_ai riêng.
- Hai readiness contracts: audio `(GEMINI_API_KEY, GEMINI_VOICE_MODEL, verified paid project)`; text parsing `(ai.provider() provider/model dùng AI_MODEL, data-use readiness)`. Model audio phải hỗ trợ audio+JSON trong catalog và live key. Inline WAV qua Gemini REST, key header, max output512 tokens; reuse gemini_keys/reserve_ai, không ép audio vào image của `_call`, không SDK mới. UI/proof nêu provider/model của từng bước; không âm thầm fallback STT/provider. Khi có Gemini key, text adapter ưu tiên Gemini như code hiện tại; không mặc định text model bằng audio model.
- `/api/config` thêm `voice_audio:{configured:boolean, model:string|null}`: configured chỉ khi key/model/ffmpeg/paid-confirmation đủ; không gửi key/project secret. Đây là readiness cấu hình, không chứng minh model access/live quality. UI kết hợp flag input và configured để bật mic/upload. Text disclosure dùng `ai_provider` đã có; raw POST vẫn server recheck mọi guard, không tin config client.
- Audio admission2 slots nonblocking trước body read, giữ slot suốt upload/decode/provider/cleanup; không queue. Outer asyncio.timeout15 s bắt đầu ở route entry, bao cả bounded stream read; slow body timeout408, pipeline sau body timeout unclear. Decode subprocess timeout3 s, kill+await finally; async httpx hủy/đóng khi deadline hết. Cleanup xong mới release slot; không tuyên bố response luôn về đúng15 s. Browser abort không bảo đảm provider chưa tính phí, không tự retry.
- Gemini chỉ trả transcript JSON; không phân tích hay thực thi ý định trong audio call. Nội dung lệnh trong audio là dữ liệu để chép lại; no tools/functions/evidence writes. Sau user sửa/xác nhận transcript, parser text hiện tại hoặc phase 8 mới tạo draft.

## Implementation Steps
1. [V-01, V-06, V-07] Shared getUserMedia({audio:true,video:false}) + MediaRecorder; states idle/requesting/recording/recorded/transcribing/error. Xin mic qua click; store stream ngay sau current-generation grant, trước constructor. Late grant sau Cancel/unmount phải stop tracks ngay. Một panel active, transcript editable.
2. [V-01, V-07] Một cleanup idempotent sở hữu stream độc lập recorder; gọi cả khi constructor/start throw, recorder error, stop/cap, cancel, close, hidden, context change và unmount. Stop chủ đích giữ final blob hợp lệ sau dataavailable nhưng stop mọi tracks; cancel/error vô hiệu generation/handlers, clear timer/chunks/blob/refs. Late event không hồi sinh draft. Không auto-upload, chỉ Chuyển thành chữ qua click.
3. [V-01, V-08] Implement shared rate/budget matrix và audio2-slot admission trước body; outer deadline từ route entry. Async subprocess/Gemini không chặn event loop; validate MIME/bytes/duration, normalize WAV, reserve_ai mỗi attempt; quota file I/O offload khỏi async loop. Không audio trong STORE/CACHE/tempfile; clear buffers. ffmpeg prerequisite có operator preflight, không Node/Multix service.
4. [V-02, V-07] Báo cáo chuyển sang explicit transcription rồi explicit parse; AbortController + transcript revision + context token cho cả hai bước. Edit, nói lại, đóng, đổi stop/trip vô hiệu draft AI cũ. Parse thay toàn bộ result/exit/reason tương ứng, unclear không giữ chip lần trước. Sau tối đa một câu hỏi làm rõ chuyển chip/gõ; không auto parse/submit trong recorder callback.
5. [V-02, V-07] Gửi disabled khi requesting/recording/transcribing/parsing/submitting; validate context trước callback. Sau success giữ pending message và khóa gửi lại cùng draft; draft mới mới mở gửi. Không tự retry POST không rõ đã nhận; không hứa exactly-once mạng.
6. [V-06, V-08] Disclosure hai bước: audio→Gemini, transcript→text provider/model đang cấu hình; app không lưu audio lâu dài, provider có terms/retention riêng. User chốt **verified paid Gemini project trước mọi human-mic live run**; unknown/unpaid giữ live gate mở, không gửi human audio kể cả câu demo vô hại. Gate triển khai `GEMINI_VOICE_PAID_CONFIRMED` server-only default false, operator xác minh billing project ngoài app; false→424 và UI chặn upload, không tin client khai tier. Không lưu key vào artifact/chat/bundle/URL. Text provider data-use cũng phải được kiểm trước gửi thông tin cá nhân. Thiếu cấu hình giữ gõ/chip, không fallback SpeechRecognition.
7. [V-02, V-07, V-08] Blockage clean cutover: report stop gửi selectedStop lat/lon, EvidencePanel gửi clicked point; server `_graph_with` rồi reuse `backend/app/plan.py:148-156` projection predicate đúng submitted way và distance≤WALK_SNAP_M(5m), mismatch422 không pending. Persist stop_lat/stop_lon + way_id + server way_label, queue hiện context này; không giả chứng minh tài xế thật đã đứng đó. Hai consumer `frontend/src/App.tsx:432,599` và API wrapper `frontend/src/api.ts:289-290` cùng migrate. Confirmation contract không đổi; operator vẫn quyết định nội dung quan sát có đáng tin.

## Verification
- `ffmpeg -version` → binary khả dụng trên runtime deploy; thiếu binary phải thấy 424/fallback, không 500.
- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_api_validation.py' -v` và `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_budget_limits.py' -v` → exit0; audio bounds/status matrix, persistent global cap multi-IP/restart/corrupt, providerOverBudget429 và missing-key424 cho cả3 endpoints. Mock outbound request kiểm key header, không URL; không gọi Gemini thật.
- `npm --prefix frontend run build` →exit0; production không còn SpeechRecognition. Confirm/ảnh giữ contract; blockage body shape giữ nhưng semantics vị trí chặt hơn, cả2 callers/queue cùng migrate.
- Browser: stop→zero upload; transcribe→text; parse→review; Send→pending. Inject constructor/start throw, recorder error, permission grant sau close và dataavailable trễ: mọi tracks ended, no upload/blob hồi sinh. StopA→close→stopB không dùng text/chip A.
- Direct Uvicorn slow chunked không Content-Length: slot có từ trước read, timeout408, cleanup/release; request thứ3 khi2 upload đang giữ slot→429. Bytes1MiB+1, invalid media, PCM>20s, decode timeout đều không gọi Gemini/ghi audio.
- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_operator_access.py' -v` →exit0; blockage point/way mismatch422 không pending; valid mapped point202 payload có tọa độ+server label, queue đủ để operator kiểm.
- Android Chrome + trusted origin + verified paid project + audio/text readiness: actual Vietnamese transcript, mic indicator tắt sau stop/error/cancel/hidden. Thiếu key/tier/model→[UNVERIFIED], không dùng unpaid human recording để đóng gate.

## Acceptance Checklist
- [ ] Audio bounded từ upload tới cleanup, persistent global/IP/provider budgets và matrix lỗi nhất quán.
- [ ] Mọi recorder failure/late response dừng mic và không nhầm draft/điểm; blockage có server-validated location cho queue.
- [ ] Explicit transcript/parse/send, hai-provider disclosure, paid-readiness gate và fallback tay quan sát được.

## Load-Bearing Assumptions & Risks
- Key/model/paid project user cung cấp sau — breaks if: audio/JSON access hoặc paid status chưa xác minh → chưa gửi human audio, giữ live gate mở; model chọn sau catalog/live proof.
- MediaRecorder/ffmpeg deploy cần preflight clip thực — breaks if: không format/decoder →gõ tay, operator sửa runtime trước mic acceptance; không thêm STT service.
- Per-IP không là identity/fairness, global cap vẫn có thể bị tiêu hết — breaks if: cần public abuse resistance/SLA →replan auth/capability riêng, không giấu tradeoff bằng Origin guard. Paid tier không đồng nghĩa zero provider logging.

## Sources
- [Gemini audio understanding, inline data và formats](https://ai.google.dev/gemini-api/docs/audio).
- [MediaRecorder: formats và events](https://developer.mozilla.org/en-US/docs/Web/API/MediaRecorder).
- [getUserMedia: HTTPS, quyền mic và permission promise có thể chờ mãi](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia).
- [Gemini data-use terms](https://ai.google.dev/gemini-api/terms).
