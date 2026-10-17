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
**Acceptance:** R-01–R-10 đã hoàn tất theo evidence liên kết; R-11 và phần còn lại của R-12 vẫn mở. Plan chỉ hoàn tất sau dataset thực địa, egress audit, live Goong/AI và production-hosting proof.

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
| 1 | [UI input và truthful copy](./phase-01-start.md) | Completed |
| 2 | [Flood knowledge và safe departure](./phase-02-flood-safety.md) | Completed |
| 3 | [Width bottlenecks và legal egress](./phase-03-width-and-egress.md) | Completed |
| 4 | [Evidence trust và non-blocking runtime](./phase-04-evidence-trust-and-runtime.md) | Completed |
| 5 | [Field validation và release proof](./phase-05-field-validation-and-release.md) | In progress |

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
Independent reviews found and drove follow-up fixes to deadline propagation, camera registry nonblocking reads, field-evaluator gate semantics, open-ended width metrics, and truthful single-frame camera copy. The latest review's two Medium findings were corrected; one final targeted review of those last corrections remains pending.

## Execution Evidence — 2026-10-13

- Current status: phases 1–4 complete; phase 5 in progress. `ak plan status` reports 4/5 phases and 11/13 checklist items (84%). Phase commits pushed to `origin/fix/access-safety-hardening`: `a64c393`, `5516d12`, `bca247b` (Phase 4 hardening), and `640c388` (Phase 5 evaluator/evidence hardening). Only the user-owned untracked `plans/journals/` remains outside commits.
- R-01–R-10 checklists remain checked against phase evidence. Latest checks: backend 129/129, evaluator 26/26, TypeScript pass, production build pass, lint 0 errors/14 warnings. Full command/output and current caveats: [superseding Phase 4/5 verification](./reports/phase-04-05-verification.md#superseding-local-verification--2026-10-13).
- Isolated production-bundle browser evidence: [primary interaction capture](./reports/phase45-browser-capture.json), [desktop screenshot](./reports/phase45-local-desktop.png), [390×844 mobile emulation](./reports/phase45-local-mobile.png). The primary capture verified timeline drag/committed `arrive_at`, guest report 202 pending, operator approve/reject, logout and zero console/page errors; it predates final runtime/corridor changes. A later current-build desktop smoke confirmed the Demo menu’s one-frame caveat, but live Goong corridor/footer and the full browser matrix remain unexercised. This is partial local proof, not physical-device or live/hosted result.
- R-11 remains blocked, owner field team: measurement and dimensioned egress CSVs are headers only. Need ≥20 valid surveyed ways, ≥20 independent alley-chain groups, three explicit egress dimensions per held-out way, frozen grouped split and successful field evaluation. No survey values/split/report were fabricated.
- R-12 remains open, owner release/operator team: live Goong/AI, hosted HTTPS origin/proxy/persistence/rollback, full interaction matrix and physical mobile proof are unavailable/unexercised. Local unit/build/browser evidence does not close those gates.
- Phase 5 evaluator now rejects omission of egress dimensions, keeps turn/sign not-comparable, blocks unknown direction, preserves parent held-out splits with append-only children, and excludes open-ended predictions from interval coverage rates. Gate measures physical width + OSM direction only; it does not verify turning space or law.
- Docs/hosting cutover and rollback/state-migration documentation are present; rollback and forwarded-header behavior have not been exercised in production. The browser artifact is valid JSON and declares the later code changes it does not cover.
- Final review refresh was attempted but provider usage limits prevented completion. The latest successful review found no Critical/High code blocker and its remaining actionable findings were addressed; do not treat that as a clean review of the very latest diff. R-11/R-12 acceptance gates remain open irrespective of review status.
