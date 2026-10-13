---
phase: 5
title: "Field validation và release proof"
status: in-progress
priority: P1
effort: ""
dependencies: [4]
---

# Phase 5: Field validation và release proof

## Overview

Kết thúc bằng ground truth thật, không chỉ output đẹp hoặc test green. Field collection có owner là team; code agent chuẩn bị intake/evaluation và không tự bịa số đo. Release không hoàn tất nếu chưa đạt R-11/R-12.

## Current Behavior

- Modify: `data/field/measurements.csv:1`, `data/field/README.md:1-10`, `backend/app/evidence.py:188,295-328` — header-only; row uncertainty/schema thiếu; load Measured chưa có exclusion seam (phase3 thêm).
- Modify: `pipelines/eval_city.py:58-95,106-135` — city eval là A/B/C thay đổi output, không ground-truth accuracy; legacy evidence apply đã migrate phase 4.
- Modify: `docs/eval/city-eval.md:3-25` — 15 cases, build từng ca 74–3975s; không phải evidence real-time safety đúng.
- Modify: `README.md:13-51,53-61,63-69`, `docs/brief.md:27-37,43-53,85-109`, `docs/decision-log.md:221-236,281-318`, `CONTEXT.md:53-59,103-109,145-163` — contracts/docs phải phản ánh estimated width, missing flood, operator review, continuous-backend decision.
- Modify: `requirements.txt:1-6`, `vercel.json:10-22`, `api/index.py:1-7`, `frontend/vite.config.ts:4-6` — uvicorn startup dependency thiếu, serverless rewrite hiện hành, dev proxy localhost khác bind127.0.0.1.
Unknowns: chưa có field measurements/ảnh, credentials live Goong/AI và site hosting endpoint. Đây là prerequisites acceptance, không là dữ liệu để model tự bổ sung.

## Target Change

Dataset>=20 real distinct segments và structured egress/sign audit. Split10 calibration/10 held-out disjoint way IDs VÀ normalized-name/alley-chain groups, freeze trước calibration. Model-only pass suppress toàn Measured (way/name) qua snapshot seam phase3, no label access trong planning context; field-informed production mode separate. False-fit scored với uncertainty, missing labels là unknown không guessed.

## Requirements Covered

R-11, R-12 (integration gate cho R-01–R-10)

## Implementation Steps

1. [R-11] Team đo ≥20 ways vật lý, ≥20 nhóm alley-chain độc lập, đủ hẻm hẹp/rộng/cua/one-way/junction/dead-end/near-threshold. Mỗi measurement phải có osm_way_id, uncertainty, narrowest clear width, bottleneck/obstruction, complete endpoint coverage/cuts, ngày/người đo và ảnh tham chiếu. `egress.csv` ghi đúng 3 chiều `direction`, `turn_space`, `sign` cho từng way; mỗi chiều có observation hoặc `unknown` tường minh, provenance/time/photo. Không ép thử lái/ngập nguy hiểm; blur mặt/biển số, không lưu lịch sử cá nhân.
2. [R-11] Intake từ chối field thiếu/sai, duplicate IDs, coverage không đầy đủ, URL ảnh chứa PII/credential, và egress dimension thiếu. Split ban đầu cân bằng 10/10 nhóm, disjoint way IDs + normalized-name/alley-chain, frozen trước khi xem kết quả. Khi tập đo tăng, dùng split phiên bản con: giữ nguyên hàng/nhóm held-out cũ; hàng mới thuộc nhóm cũ kế thừa phía đó; nhóm mới chỉ vào calibration. Không overwrite parent hoặc tái tạo held-out từ dữ liệu đã xem. Model-only loại mọi Measured way/name trước indexing; field-informed chỉ giữ calibration và loại held-out.
3. [R-11/R-12] Báo interval gap/coverage trên range bounded, open-ended count/informative denominator để range chưa biết không thành overlap/accuracy hoàn hảo, confusion denominator, abstention, false verified fits, direction agreement/contradiction/unknown, và egress coverage theo dimension. Evaluator chỉ so sánh direction với OSM; turn-space/sign được báo `unscored/not_comparable`, blocking observation chỉ là sự kiện thực địa, không tự gán thành model contradiction. Gate không được pass nếu thiếu dimension held-out, direction unknown/contradiction, false fit, denominator rỗng, held-out dưới floor 10 nhóm/10 ways, hoặc model-only mọi prediction đều abstain. Report split ratio/counts; gate chỉ đo width + OSM direction, không chứng minh legal/turn-space. Report CPU/wall evaluation time và external/background runtime metric với missing status rõ nếu chưa đo. Không quảng bá zero-error thành accuracy; R-12 vẫn mở nếu legal/egress chưa được xác minh.
4. [R-12] Add uvicorn requirements. Vite proxy mặc định http://127.0.0.1:8787, override backend origin bằng server-side dev env; production same-origin serve dist bởi continuous backend. Nếu frontend Vercel: /api/** rewrite tới real HTTPS backend origin do operator cấu hình (không placeholder commit), API wrapper serverless removed; host-only Secure HttpOnly SameSite cookie forwarded qua proxy, Origin allowlist public frontend HTTPS; không Domain cross-host. README one worker, persistent VAODUOC_STORE/CACHE/FLAGS, operator secret/AI budgets, HTTPS/health/grace shutdown. Không deploy/push trừ yêu cầu riêng; missing real backend origin blocks Vercel smoke, local bundle proof vẫn làm.
5. [R-12] Sau integration chạy full Python suite và frontend build/lint một lần; regression tests deterministic no internet và temporary store. Run actual backend/UI (commands dưới), bsk desktop/iphone-14: search keyboard, 4 presets, model/class switch, park/pickup/dwell/time/midnight, date empty repair, layers/source/evidence, login/guest/operator, report pending→approved/rejected, camera job ready/error/expired, clear/swap request race, missing tide, live build timeout/retry. Drag timeline thật và verify POST committed datetime; không nhận screenshot slider là proof drag. Nếu keys thiếu ghi “not exercised” live upstream và giữ gate chưa đóng tương ứng.
6. [R-12] Sau smoke proof cập nhật docs current ownership và decision-log superseding D32/D33/D34 serverless assumptions. Save review evidence tại `plans/261010-1154-access-safety-hardening/reports/`: field-validation.md/json, bsk capture JSON và screenshots, command results, unresolved upstream limits; không secrets. Report exact data/version/time. Update docs/eval with new field report link; không rewrite historical city-eval numbers như fresh accuracy.
7. [R-12] Rollout/rollback: back up operator review/accepted files/quota/schema version trước start code mới; quarantine untrusted legacy evidence phase4, field data vẫn nguyên. On rollback code/API phải cùng phiên bản frontend; invalidate derived width cache tạo bởi old p20 logic, rebuild from preserved raw cuts, không restore old trusted interpretation. Smoke expected results theo evidence thật không pin17:15/19:15. Mark phases done chỉ khi mỗi checkbox có proof; human field gate chưa có thì giữ pending/blocked và nêu owner.

## Verification

- `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`; `npm --prefix frontend ci`; sau phase này uvicorn có sẵn qua requirements.
- `cd backend && ../.venv/bin/python -m unittest discover -s tests -v` → exit0, new safety/trust/job/quota modules included, no disk pollution/shared external state.
- `npm --prefix frontend run build && npm --prefix frontend run lint` → exit0; không xem build là proof behavior.
- `.venv/bin/python -m unittest pipelines.test_eval_field -v` → intake/split extension/leakage/false-fit/egress scope and CLI report behaviors pass using temporary synthetic mechanics only. Evaluator exit contract: 0 split created or scored gate passed; 1 scored gate failed (report exists); 2 invalid/insufficient input; 3 evaluation/report infrastructure failure (no report). Header-only real files must refuse; never create a synthetic acceptance dataset.
- Terminal1: `cd backend && ../.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1`; terminal2: `npm --prefix frontend run dev -- --host 127.0.0.1`. Bsk workflow tại plan.md; original native date-year-deletion reproduction không còn crash, screenshot desktop/mobile và active job states.
- Production bundle: serve frontend/dist bằng backend `http://127.0.0.1:8787`, repeat primary bsk flow; không chỉ Vite dev.
- Restart smoke isolated VAODUOC_STORE/CACHE/FLAGS before import: accepted review/quota survives, in-flight interrupted, projection reconciliation idempotent, no demo reseed. Prod dist traversal to fake secret404; real job GET returns JSON. All temp data excluded real repo store.

## Load-Bearing Assumptions & Risks

- Human field dataset không thể discover bằng tools hiện tại — breaks if team không cung cấp >=20 validated rows+photos → phần code/docs reachable vẫn làm, phase này blocked; không fabricate completion (R-11/R-12).
- Held-out small sample chỉ là release gate cho vùng đo, không generalization all-HCMC; mở vùng verified mới cần proof mới (R-12).
- Production frontend/backend origins phải cùng proxy hoặc explicit CORS/cookie policy — breaks if login loop/401 trên production host → fix origin/HTTPS cookie, không wildcard hay expose secret (R-12).
- Dataset raw shared cache hiện đang modified trên nhánh — preserve diff; chỉ regenerate derived outputs sau export provenance, không stage incidental cache chung (R-12).

## Accepted Red-Team Deltas

D2/D4/D5: require field ID/uncertainty/bottleneck and structured egress; group-based split với measured-exclusion seam phase3; pre-import temp paths phase1; explicit Vite bind/prod proxy/cookie contract. D1 SPA checks carried into production-bundle gate.

## Execution Checklist

- [ ] R-11: >=20 real measurements + frozen split + field/model evaluation. **Blocked on the field team**: intake schema, `egress.csv` and `pipelines/eval_field.py` are ready; `measurements.csv` is still header-only and the script refuses < 20 rows.
- [ ] R-12: full suite/build/lint + bsk dev/production + live/limit evidence. Latest local automated checks: backend 129/129, evaluator 26/26, TypeScript/build pass, lint 0 errors/14 warnings. Local production-bundle browser smoke is a subset and predates final runtime/UI copy changes; live Goong/AI and production hosting remain unexercised, so this stays open.
- [x] R-12 (partial): hosting cutover docs + restart/state-migration smoke. Serverless removed, single-worker deploy + backup/quarantine documented (README, D36); restart smoke kept review state and did not reseed demo data. Production rollback procedure itself remains unexercised (see open R-12 above).

Evidence: `reports/phase-04-05-verification.md`.
