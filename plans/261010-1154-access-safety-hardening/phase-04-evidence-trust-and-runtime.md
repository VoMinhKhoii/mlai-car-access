---
phase: 4
title: "Evidence trust và non-blocking runtime"
status: pending
priority: P1
effort: ""
dependencies: [3]
---

# Phase 4: Evidence trust và non-blocking runtime

## Overview

Backend liên tục một process là owner của evidence/review/quota. Client chỉ chọn area identity; không gửi evidence có quyền quyết định. Camera two-frame chạy nền bounded; corridor không chờ camera sleep.

## Current Behavior

- Modify: `backend/app/main.py:25-27,55-67,146-177,204-218,226-250,253-330,351-381,384-461` — CORS wildcard, area dict trusted, mutations/public AI không auth; seed demo ghi accepted file và SPA fallback thiếu containment.
- Modify: `backend/app/live.py:177-178,218-236,245-309,335-360` — client-key path, global apply, per-build daemon thread; area trả toàn payload.
- Modify: `backend/app/evidence.py:164-237,307-322`, `backend/app/plan.py:23-39,174-186` — clear/reload mutable shared store; per-version width cache và per-request live source lẫn nhau.
- Modify: `backend/app/cameras.py:208-253`, `backend/app/corridor.py:208-252` — process-wide lock giữ qua snapshot/sleep/AI; corridor trực tiếp read_many.
- Modify: `backend/app/ai.py:24-26,65-88,138-200`, `backend/app/budget.py:20-67`, `backend/app/config.py:6-21` — queue tail50 không lifecycle; model ACCEPT publish; path/quota disk import-time, writes chưa atomic.
- Modify: `frontend/src/api.ts:72-84,91-113,125-169`, `frontend/src/App.tsx:58-62,82-159,217-245,343-352,474-503`, `frontend/src/components/Evidence.tsx:11-14,66-71,93-96`, `frontend/src/components/Corridor.tsx:13-43,99-154` — optimistic approval/client area, no cancellation/job status.
- Modify: `pipelines/eval_city.py:75-95` — set_live/apply consumers; phải migrate sang explicit overlay, không shim.
- Modify: `backend/tests/test_corridor.py:43-51` — mock read_many hiện hành; rewrite consumer contract nhưng giữ behavioral route-selection cases.
Unknowns: production keys/limits chưa cấu hình; integration live quota path chỉ được claim exercised khi có keys.

## Target Change

Server-owned bounded area cache, immutable evidence snapshot + request overlay; no signing client evidence needed vì user đã chọn persistent backend. Reuse live crawler, flags, camera TTL và AI extraction log. Pending reports là file state keyed-by-ID riêng `STORE/pending_reports.json`, không nhét lifecycle vào tail50 log. Create một module `backend/app/auth.py` cho operator session; không thêm external DB/queue/framework.

## Requirements Covered

R-07, R-08, R-09, R-10

## Implementation Steps

1. [R-07/R-08/R-10] Persist server-built area result có schema version, area_key, revision, collected_at/expiry atomic; chỉ successful build publish, partial error không done-valid. Scheduling `/api/area/build` cần operator; guest đọc cache/static với reason và nút xin operator thu thập, không auto-schedule. Build single-flight per area_key, max2 running/max4 queued, 300s server deadline; excess429 với retry_after. Stream chỉ theo dõi job, disconnect không tạo thread mới. Model calls/parcel crawl có budgets. Client chỉ gửi area_key/revision; server derive key, check coverage/TTL; stale/missing → unverified + reason, không auto verified.
2. [R-07] Loại `live.apply`/`EvidenceStore.set_live` public/global cutover. Build base EvidenceStore dictionaries cục bộ rồi publish một immutable snapshot/generation; mỗi plan/evidence/pipeline giữ đúng snapshot reference suốt request + own validated area overlay. Cache static widths bằng graph identity + snapshot/flags generation, bounded LRU; không lưu client overlay vào global _WR. Review changes không invalidate bằng mid-clear. Migrate main.py 2 callers và eval_city.py 2 apply callers + global live.clear, all function consumers bên dưới.
3. [R-08] Add operator login/logout/status endpoints trước SPA fallback; auth.py verify OPERATOR_SECRET constant-time, issue expiring HttpOnly SameSite cookie (Secure HTTPS), bounded server session nonce cho revoke/logout. Không secret qua config/bundle/URL/log; login manual input trong Demo menu. POST Origin/CSRF validation, APP_ORIGINS allowlist, missing secret → admin unavailable. Harden SPA resolve+containment kể cả symlink/percent-encoded traversal; ngoài dist→404, unknown /api/**→JSON404, mọi API routes registered trước catch-all. Regression dùng temporary fake secret file, không đọc .env.local thật.
4. [R-08] Operator gate flags/photo review/reload/build scheduling/AI text-photo/review queue/paid Google/uncached cameras. Guest confirmation/blockage→pending_reports.json keyed stable report_id: type,payload,status,created_at,expires_at,reviewer,revision,publish_target; không sửa accepted files. GET /api/ai/review mở rộng state-filtered cursor pagination (không tail50), migrate legacy extraction entries giữ raw log. POST /api/ai/review/{id} lock transition pending→approved|rejected, reject expired, idempotent. Approved state committed atomic trước derived projections; restart reconciles projections keyed report_id, tránh duplicate/lost publication. Type map: confirmation→confirmations.jsonl; blockage→blockages.jsonl; reviewed flood→live_flood_reports.jsonl; photo width→server photo review record. Stop-rule extracts tiếp tục review-only tới khi có existing rule consumer, không giả vờ publish. Operator UI có list/review; guest “chờ duyệt”. Model ACCEPT là extraction quality; ảnh tin rao/user inputs pending không làm decisive width tới khi duyệt. Camera server-owned source giữ threshold/provenance riêng.
5. [R-08] Validate finite coords/duration/rain, area key regex+containment, IDs thuộc graph; rate limits bounded buckets. Text≤12k, image≤8MiB capped read, JPEG/PNG/WebP header/content validation;413/415 trước model. Không synchronous AI/httpx trong event loop: async photo dispatch off-loop sau bounded upload read. Reject trusted-status client fields422. Quarantine old community accepted files, giữ backup; migrate ID/status idempotent. Remove import-time _seed_demo accepted mutation: demo blockage read-only fixture tách community store, marked mô phỏng, không duplicate restart; ngoài demo không làm evidence thật. Legacy parsing lỗi fail closed/quarantine, không abort mọi plan.
6. [R-09/R-10] Camera cached result hoặc202 job, GET /api/camera-jobs/{job_id}. Corridor trả forecast/cache ngay. Chọn subset deterministic max12 unique cameras/logical batch: chosen-route clusters trước, mỗi cluster camera usable gần route nhất, rồi alternatives; remainder explicit unknown. Payload singular camera_job quản lý subset, kèm cameras_requested/scheduled/dropped+reason và per-hotspot coverage; ready chỉ subset, không mọi tuyến đã đọc. Executor max2 active jobs, queue max24 cameras; per-camera futures coalesce overlapping batches, locks chỉ state. Frames≥13s, existing6s retry identical, không infer movement từ1 frame. TTL5min job/3min reading; restart interrupted/expired; authorized retry, no_model/error không “clear”. Persist metadata cho restart recovery; không Redis/worker service.
7. [R-08/R-10] Giữ Google SKU namespace budget.py; thêm AI usage namespace riêng keyed provider/model/key-fingerprint trong STORE/ai_usage.json, report riêng không raw keys. Reservation tại ai._call trước MỖI actual upstream attempt (retry sang key/model tính riêng), áp dụng camera/listing-photo/text/photo, không double-reserve caller. Explicit configurable per-key/model daily caps; corruption fail closed. Atomic quota/flags/cache writes; bounded max32 graph/width/flood/area caches revision/flags/IRD/tide content-generation aware. Dùng VAODUOC_STORE/CACHE/FLAGS paths phase1, fixtures/process smoke set env TRƯỚC app import; không patch config.STORE sau leaf constants capture. Single-backend caps không $0 billing guarantee.
8. [R-09/R-10] App/api AbortController cho plan/corridor/area stream và polling, generation invalidation khi clear/swap/dest/time/vehicle/flags/unmount. UI polls only active job mỗi2s, timeout120s, stops terminal/hidden/unmount; tab visible có thể resume existing ID, không schedule duplicate. Build race không ghi progress area cũ vào trip mới; retry resets failed build key. Deadline client không để old response undo new trip; abort không đồng nghĩa server job cancelled.
9. [R-07/R-08/R-09/R-10] Create backend/tests/test_evidence_isolation.py, test_operator_access.py, test_camera_jobs.py, test_budget_limits.py. Fixtures/subprocess local upstream dùng temp env before import, no internet/quota thật. Smoke concurrent builds/camera/photo upload+bsk; separate foreground CPU/external I/O/background. Add >50 pending pagination, crash giữa approval-state/projection, request40 cameras coverage, encoded SPA traversal tới fake secret và unknown API JSON.
10. [R-09/R-10] Propagate monotonic job deadline tới crawler/photo/model loop và HTTP timeouts=min(source limit,remaining deadline); check cancel/deadline trước mỗi subcall/retry. Logical timeout không giải phóng executor slot khi thread còn chạy; slot chỉ release worker exit, không unbounded orphan tasks. Stream là async status watcher không occupy sync threadpool suốt300s; shared build survives observer disconnect trong bounded lifetime, reuse by next authorized observer.

## Contract Consumers & Clean Cutover

Area: `main.py:170,212`, `live.py:235,359`, `App.tsx:89-99,148-158,223-228`, `api.ts:72,138,144-164`, `eval_city.py:78-91`. Replace function arguments/callers, remove obsolete global APIs/comments, no legacy accepted `area` shim.
Camera: `main.py:356`, `corridor.py:236`, `api.ts:169`, `App.tsx:142-145,114-135`, `Corridor.tsx:111-154`, `tests/test_corridor.py:49`. Update fixtures to cache/job contract, preserve route switch/jam/flood behavior.
Admin status/credential contract: config exposes boolean permissions only; Evidence photo action + Demo flags/review buttons require granted session, logout revokes UI access; blocked request preserves state and surfaces error.

## Verification

- `cd backend && ../.venv/bin/python -m unittest tests.test_evidence_isolation tests.test_operator_access tests.test_camera_jobs tests.test_budget_limits tests.test_corridor -v` → forged input rejected, cross-request isolation, unauthorized unchanged-state, expiry/quota/job coalescing/recovery pass.
- API smoke isolated server/local fixtures: A không đổi B; N=8 concurrent authorized builds (2 running/4 queued, excess429) và cold camera/photo task không delay GET config/vehicles/static (>1s failure); cached local plan<3s. Same area/camera requests coalesce, upstream vượt server deadline terminal-error, không giữ infinite threadpool tasks.
- Guest flags/build scheduling/AI/uncached camera→401; cached plan/corridor đọc được. Valid operator cookie, logout/replay revoked cookie401; cross-origin mutation403. Fake dist+encoded traversal/symlink tới temp secret404; job handler JSON, unknown API JSON404. Upload8MiB+413 trước model, key traversal422; no secret config/capture.
- Guest report pending không đổi plan; >50 reports paginated đều truy xuất. Approve→one accepted projection; duplicate approval/simulated crash+restart không double publish. Expired/rejected không promote; demo không reseed community log. Listing-photo/key-retry calls debit correct AI namespace once per upstream attempt.
- Bsk guest/operator build quyền rõ, photo/report lifecycle, forecast→pending→ready/error/expired; request40 cameras schedules≤12 và dropped hotspots unknown, ready không gọi toàn tuyến clear. Clear dest không resurrect result; no keys explanatory forecast-only. Mobile actions+screenshot.
- Warm local plan CPU-path target <3s; foreground API return không cộng 13–19s camera wait. External I/O latency reported by source, không gọi tất cả slow plan là camera contention.

## Load-Bearing Assumptions & Risks

- User chọn one continuously running backend, one process+persistent storage. VERCEL/multiworker full-state unsupported: startup guard/deployment check, replan shared store trước scaling; Vercel frontend proxy backend HTTPS, same-origin cookie không Domain (R-07–R-10).
- Area graph cache identity phải có source + coords/tile, không chỉ source='cache' — breaks if two areas collide → explicit graph-key contract and two-area tests (adjust).
- TTL/job budgets không phải truth guarantee — stale/missing camera không “clear road”; expired cache nguồn không verified (adjust).
- Single-process memory/job caps chosen initial, tune bằng measured cold/warm/concurrency smoke; không bỏ checks hay add distributed service để đạt mục tiêu (adjust).

## Accepted Red-Team Deltas

T1–T5, D1/D3/D4: operator-only builds/all-AI attempt budgets; paginated keyed review+crash-safe projections; bounded builds/off-loop uploads; separate AI quota; demo fixture isolation; SPA containment/API ordering; explicit camera subset coverage; pre-import isolated state paths. User chấp thuận plan corrections, không là code đã triển khai.

## Execution Checklist

- [ ] R-07: server-owned area, immutable snapshot, all callers cutover.
- [ ] R-08: operator auth, pending/review lifecycle, validation, quota.
- [ ] R-09: bounded background camera jobs + immediate corridor.
- [ ] R-10: cancellation/retry/caches và real runtime smoke.
