---
title: "Vào Được: safety, evidence trust và demo reliability"
description: "Sửa các kết luận an toàn sai, lỗi UI và ranh giới evidence; chứng minh bằng regression, bsk và đo thực địa."
status: in-progress
priority: P1
effort: ""
branch: fix/access-safety-hardening
tags: [bugfix, frontend, backend, api, critical]
blockedBy: []
blocks: []
created: 2026-10-10
---

# Vào Được: safety, evidence trust và demo reliability

## Overview

Plan tạo trên nhánh `fix/access-safety-hardening` từ local `main`; implementation bắt đầu 2026-10-11. Giữ nguyên thay đổi sẵn có trong `backend/cache/live/parcels.json`; không reset, stage hay dùng nó làm ground truth.
**Outcome:** câu trả lời đúng giới hạn bằng chứng, không báo an toàn khi thiếu dữ liệu, không sập UI và không để client sửa evidence của người khác.
**Constraints:** giữ FastAPI, React/Vite, MapLibre, HCMC-only, vehicle-specific và 3 hard checks ngập theo thời gian; không bịa dữ liệu thực địa. User chọn một backend chạy liên tục, một process, storage bền vững; Vercel chỉ frontend nếu dùng.
**Non-goals:** viết lại router, mở rộng địa bàn/persona, thêm doanh thu, thêm DB/queue phân tán, cam kết xe thật chắc chắn đi qua được. Không bỏ tính năng camera/live crawl/community hiện có.
**Acceptance:** R-01–R-12 bên dưới, bsk desktop/mobile và tập đo thực địa thật. Phase1 đã đạt R-01/R-02 theo evidence dưới đây; phase2–5 chưa triển khai.

## Requirements

| ID | Requirement / bằng chứng hoàn tất | Phase |
|---|---|---|
| R-01 | Xoá/sửa dở ngày giờ không trắng UI; draft lỗi không đổi trip; API ngày lỗi trả 422, không 500 | 1 |
| R-02 | Copy không khẳng định điểm chưa xác minh; 0 m là 0 phút; tuyến OSM/Goong ghi đúng nguồn; autocomplete dùng keyboard và bỏ response cũ | 1 |
| R-03 | Missing tide/history hoặc aged-out positive observation → risky/unverified, không clean; reason/freshness không bịa depth | 2 |
| R-04 | Publish giờ rời chỉ full hard checks + known decisive traversal legs; dwell legality qua midnight; dead-end không gán triều; leg provenance/worst depth | 2 |
| R-05 | Bottleneck/sparse/derived-only cuts không strict fits/turn_here; source thửa đất không phải Measured Clear Width; field-exclusion seam không leak | 3 |
| R-06 | Way Out không ngược chiều; chỗ quay được kiểm tra không chỉ đếm tên way; junction mouths không né rule 5 m; không có walk edge trả kết quả có lý do | 3 |
| R-07 | Browser không tự nâng photo/listing/parcel lên trusted evidence; hai request/area không nhiễm nhau; reload/caches dùng snapshot nhất quán | 4 |
| R-08 | Operator-only builds/flags/review/reload/costly AI; guest reports pending; reviewed state crash-safe/paginated; SPA containment và secret/path/CORS bounds | 4 |
| R-09 | Cached/forecast trước background camera; bounded single-flight + coverage requested/scheduled/dropped; ready không gọi unscheduled hotspots clear | 4 |
| R-10 | Stale request không ghi đè UI; bounded builds/jobs/caches và separate AI/Google quota; off-loop I/O; isolated startup paths có từ phase1 | 4 |
| R-11 | >=20 real survey rows có ID/uncertainty/bottleneck/photo và egress audit; split by way+name groups, model-only no Measured label leak | 5 |
| R-12 | Full regression + bsk desktop/mobile + rollout/rollback và docs hiện hành; không tuyên bố verified trên held-out false-fit hoặc legal/egress chưa xác minh | 5 |

## Phases

| # | Phase | Status |
|---|-------|--------|
| 1 | [UI input và truthful copy](./phase-01-start.md) | Pending |
| 2 | [Flood knowledge và safe departure](./phase-02-flood-safety.md) | Pending |
| 3 | [Width bottlenecks và legal egress](./phase-03-width-and-egress.md) | Pending |
| 4 | [Evidence trust và non-blocking runtime](./phase-04-evidence-trust-and-runtime.md) | Pending |
| 5 | [Field validation và release proof](./phase-05-field-validation-and-release.md) | Pending |

## Dependencies & Execution

Thực hiện tuần tự 1 → 2 → 3 → 4 → 5: các phase cùng sửa `plan.py`, `main.py`, `App.tsx`, `api.ts`; một integration owner, không chạy sibling edits trên các file này. Team có thể bắt đầu đo thực địa trong lúc sửa code, nhưng phase 5 chỉ đóng khi dữ liệu thật và code mới đều đạt.
Không có unfinished plan trong project khi quét `ak plan list/resolve` và `plans/**/plan.md`; cross-plan deps rỗng.
Research reused: hai review backend độc lập và bsk ở phiên trước; đối chiếu lại source trước lập plan. Mode: hard, không lập lại nghiên cứu tổng quan; red-team sau draft.

## Verification Environment

Từ repo root: `python3 -m venv .venv`; `.venv/bin/pip install -r requirements.txt uvicorn`; `npm --prefix frontend ci`. `uvicorn` chưa có trong `requirements.txt:1-6`: phase 5 cập nhật startup dependency.
Backend regression: `cd backend && ../.venv/bin/python -m unittest discover -s tests -v`. Frontend: `npm --prefix frontend run build` và `npm --prefix frontend run lint`.
Browser smoke: bsk session start --json, giữ ID thật; debug start/navigate/observe desktop rồi emulate iphone-14; screenshot/export trong reports, stop debug/session cả success/failure. Operator đăng nhập thủ công ngoài capture; debug không ghi credential input/body, dùng fake secret trong deterministic fixtures, không đọc/exploit .env.local thật.

## Decision Corrections & Risks

Không dùng fallback ngày lỗi thành now. ErrorBoundary chỉ là lớp cô lập cuối cùng, không thay validation.
Không đưa secret operator vào config/bundle/URL. Request-scoped data chưa đủ chống giả mạo: backend phải sở hữu writer của area cache và reviewed evidence, không nhận browser evidence envelope.
Bsk trước chỉ quan sát slider, chưa chứng minh drag; Goong/AI chưa cấu hình nên camera lock là static finding, không phải nguyên nhân đã chứng minh của plan latency 9,55–27,26 s.
20th percentile có thể bỏ bottleneck đã tái hiện độc lập. Min của cadastral estimate cũng không tự chứng minh Clear Width; cần tầng estimate và field calibration.
Field collection là phần việc thật của team, không thể hoàn thành bằng script/ảnh giả. Chưa có dataset (CSV header-only); nếu thiếu, giữ phase 5 mở và gọi rõ prototype chưa qua acceptance.

## Review State

Red-team: 15 findings (5 Critical/7 High/3 Medium), user chấp thuận áp dụng; [adjudication](./reports/red-team-review.md). Đã bổ sung vào cả5 phases, không production code thay đổi.
Whole-plan consistency sweep: reread plan.md + cả5 phase files; checked15 decision deltas; no unresolved cross-file contradiction. CLI format/index/status gate chạy sau sweep.
Active worktree pointer qua ak plan use; session hook không persist (adapter missing module/CK_SESSION_ID absent), absolute paths được truyền rõ cho reviewers/next workflow.

## Execution Evidence — 2026-10-11

- Phase1 R-01/R-02: checklist checked qua `ak plan check`; `ak plan status` reports 1/5 phases, 2/13 tasks (15%). Overall remains in-progress.
- [Phase1 verification](./reports/phase1-verification.md): targeted10/10, full Python28/28, frontend build pass/lint0errors11warnings; real non-finite duration request422; native desktop/mobile datetime and source/zero/keyboard/cancellation smoke. Live Goong search/detail/plan200.
- Independent re-review approved with no phase1 blockers. User approved two baseline test-only repairs: camera fixture provider identity and hydro frozen clock; production camera/hydro unchanged.
- User requested phase1 commit/push before phase2. Secrets, root .venv and pre-existing parcel cache must not enter the commit. No deployment or PR requested.
- CLI limitation: `check` updates checkboxes and `status` derives completion, but does not rewrite the legacy phase frontmatter or Phases table. Those pending labels above are the planning snapshot; checked phase files plus this evidence record carry current execution progress. No unsupported hand-edited status mutation.
- Remaining risks belong to later phases: typed rain/coordinate boundaries and bounded dwell/runtime; field collection and live-release acceptance remain open.
