---
title: "Gemini voice extension: red-team và quyết định"
date: 2026-10-17
scope: "demo plan phases 7-9, không tái audit toàn bộ code cũ"
---

# Gemini voice extension: red-team và quyết định

## Summary
Ba code-reviewer độc lập đã review plan và source, không chạy build/lint/tests hay sửa code.10 findings:8High/2Medium. User chọn áp dụng đề xuất có điều chỉnh và **xác minh paid tier trước human-mic live**.10/10 accepted; quota/access xử lý bằng existing per-IP limiter + persistent global cap, không triển khai identity/token subsystem mới.

## Findings & Adjudication
| ID | Lens / severity | Evidence hiện tại | Quyết định và thay đổi trong plan |
|---|---|---|---|
| RT-01 | Security / High | `backend/app/main.py:505-519,618-630`; draft audio deadline ban đầu chỉ bắt đầu sau body | Accept: audio2-slot admission và outer15s từ route entry gồm chunked read; slowbody408, kill/await cleanup rồi release. Direct Uvicorn slow-client proof, không dựa proxy vô danh. Phase7/9. |
| RT-02 | Security / High | `backend/app/main.py:459-463`; `backend/app/reports.py:38-41,86-98`; `backend/app/auth.py:56-63`; `backend/app/budget.py:74-89` | Accept modified:20/IP/h hiện có chỉ là throttle RAM, không identity/auth. Thêm global60 requests/h VN persistent trong budget/storage, mọiIP/restart; caps provider/key vẫn có. Reject phần bắt buộc thêm capability/account vì chưa cần cho phạm vi đã chọn. Residual public DoS trong ceiling được nêu rõ. Phase7/8/9. |
| RT-03 | Security / High | [Gemini terms: unpaid và paid data use](https://ai.google.dev/gemini-api/terms); draft cho demo phrase khi tier chưa chốt | Accept theo user: human voice chỉ gửi sau verified paid project; unknown/unpaid giữ gate mở, không coi câu vô hại là non-personal voice. Server operator attestation `GEMINI_VOICE_PAID_CONFIRMED` default false + config boolean readiness; provider retention không được hứa zero. Phase7/9. |
| RT-04 | Security / High | `frontend/src/App.tsx:430-434,599-601,809`; `backend/app/main.py:522-535`; projection có sẵn `backend/app/plan.py:148-173` | Accept: report stop gửi tọa độ stop; EvidencePanel gửi click point. Server verify submitted way projection≤5m, giữ tọa độ+server label trong pending, queue show vị trí. Body shape giữ, semantics stricter; cả2 callers và tests migrate. Không giả location attestation. Phase7/9; V-02 làm rõ confirmation có vehicle, blockage có vị trí/way. |
| RT-05 | Security / Medium | `backend/app/main.py:509-519` bắt OverBudget thành200 unclear, trái429 mới của audio | Accept: một error matrix cho cả3 voice endpoints; rate/busy/provider budget429, missing key/model/decoder424, flagoff403, slowupload408; semantic/shape/pipeline timeout mới unclear. Migrate existing tests và client messages, không che spend shutdown bằng “không hiểu”. Phase7/8/9. |
| RT-06 | Failure Mode / High | `frontend/src/components/VoiceReport.tsx:92-127`; draft thiếu cleanup ở constructor/start/error | Accept: stream reference lưu trước recorder construction; cleanup idempotent ở mọi success/error/cancel path. Inject constructor/start/recorder errors + late grant/events, require all tracks ended và no upload. Phase7/9. |
| RT-07 | Failure Mode / High | `frontend/src/App.tsx:91-97,313-317`; `frontend/src/parkingWatch.ts:103-114,160-166` thiếudemo_scenario | Accept: phase8 sở hữu cảwatch comparison; cùng helper có demo_scenario cho UI/poll, rain vẫnmutable. Samecoords synthetic→real phải mismatch, polling giữ saved request. Phase8/9. |
| RT-08 | Assumption / High | `backend/app/ai.py:59-74`; `frontend/src/api.ts:16-28`; audio model mới khác AI_MODEL | Accept: audio và text readiness/provider/model/tier riêng; UI disclose2 bước và proof ghi2 model. Config chỉ public boolean/model, khôngkeys. Không đổi provider SDK/text adapter hoặc ngầm đổi STT. Phase7/9. |
| RT-09 | Assumption / Medium | `README.md:11-26`; `requirements.txt:1-7`; ffmpeg mới chỉ có trên host khảo sát | Accept: deployment operator cài ffmpeg và preflight captured browser clip decode; README/runbook là owner instruction. Local direct Uvicorn ghi rõ no proxy; nếu có proxy, lưu owner/config path thật và kiểmoversize/slowchunk qua deployedboundary. Không bịa Docker/proxy sẵn có. Phase7/9. |
| RT-10 | Assumption / High | draft corpus chỉ yêu cầu final đúng sau sửa; `backend/tests/test_api_validation.py:101-143,302-327` dùng mock output | Accept:9 cleartrials (3flows×3), rawSTT semantic slots≥8/9 và≥2/3 mỗiflow, parser từuncorrected transcript≥8/9, reviewed mutation9/9. Ambiguous/adversarial không autoaction100%; sửa tay không nâng rawfail thànhpass. Live batches tôn trọng20/IP/h, không reset/đổiIP. Phase9. |

## Decision Notes
- Các chỉnh sửa trên là nội dung kế hoạch; **không có code ứng dụng được triển khai** trong phiên này.
- Paid-confirmation là server operator attestation sau kiểm billing project, không phải app tự suy ra tier từ API key. Key không xuất hiện trong artifact.
- Global hourly voice cap là fixed Vietnam-hour bucket; không hứa rolling quota/per-user fairness hoặc chống distributed DoS. Per-provider/key attempt ceilings vẫn độc lập và persistent.
- Blockage mapping chỉ kiểm sự nhất quán point/way và cho operator đủ context; không chứng minh vật cản thực sự tồn tại hoặc tài xế có mặt ở đó.
- Missing key/model/tier/physical device vẫn [UNVERIFIED] ở live acceptance. Validation plan format và fake audio/container smoke không thay thế nó.

## Whole-Plan Consistency Sweep
- Inputs: plan.md, phases01–09, safety-plan overlap note,10 decision deltas ở bảng trên.
- Reconciled: old SpeechRecognition baseline vs Gemini cutover; old report NoModel/OverBudget fallback vs new424/429; upload-start deadline; public IP/global quotas; paid audio+text readiness; blockage context; watch fixture identity; decoder/proxy owner; raw quality gate.
- Historical implementation/validation logs giữ nguyên và được đánh dấu snapshot; completed phase3/4 không mở lại,9 extension checkboxes vẫn pending.
- Không có contradiction quyết định chưa giải quyết sau sweep. Đây là plan review, không phải approval/review của code chưa viết.

## Verification Performed This Session
- CLI scaffold phases7–9, format validation và reindex/status nhận9phases.
- Phase contract/Modify anchors/requirement mapping kiểm cơ học; không missing/out-of-bounds source anchors sau sửa.
- Actual isolated endpoint smoke: report parser flagoff403, no-provider200unclear (baseline trước cutover), overlong text422, pending rỗng.
- In-memory WebM/Opus synthetic-tone decode:10,122 encoded bytes→32,000 PCM bytes=1s mono16kHz. Không có Gemini call/human recording.
