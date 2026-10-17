---
phase: 2
title: "Flood knowledge và safe departure"
status: completed
priority: P1
effort: ""
dependencies: [1]
---

# Phase 2: Flood knowledge và safe departure

## Overview

Thiếu số liệu không biến thành an toàn; giờ rời được tính từ đường thật, full hard checks và cùng evidence snapshot. Không dùng thời gian demo 17:15/19:15 làm oracle.

## Current Behavior

- Modify: `backend/app/flood.py:121-161,224-256,260-326` — cached bulletin/IRD và expiring live reports; expired evidence/None dễ passable, worst_over tie không deepest.
- Modify: `backend/app/plan.py:23-35,190-209,280-339,394-429,438-509,609,727-735`, `backend/app/legality.py:31-48,62-110` — timing synthetic; lot prof arbitrary edge/name empty; legality chỉ arrive, flood route chỉ instant, leg provenance null.
- Modify: `backend/app/corridor.py:164-182,316-325` — bỏ depth None khỏi forecast, chưa thể hiện thiếu knowledge.
- Modify: `backend/app/config.py:48-64` — margins/routing constants hiện có; thêm conservative traversal margin cùng convention, không hardcode vào UI.
- Modify: `frontend/src/api.ts:39-69,98-112`, `frontend/src/components/Result.tsx:10-55,127-132,176-208`, `frontend/src/components/TideTimeline.tsx:37-44,106-112`, `frontend/src/MapView.tsx:139-141` — numeric depth và passable/risky/blocked; UI cần reason khi depth unknown.
- Modify: `frontend/src/components/Corridor.tsx:8,48-58,71-94` — status ok hiện ghi “Không ngập”; render nullable forecast knowledge/reason, không đồng nhất unknown coverage với dry.
- Modify: `backend/tests/test_hydro.py:58-69` — existing known/model uncertainty cases giữ behavioral coverage.
Unknowns: chưa có calibration street-depth đáng tin; không invent depth để bù missing tide.

## Target Change

Giữ FloodStatus passable|risky|blocked nhưng knowledge metadata riêng: known|missing_tide|missing_history|stale_positive_observation, nullable depth. Positive flood evidence vẫn blocked dù nguồn khác missing; expired positive report không thành clean. Missing/no-history/stale observation → risky/unverified, không “không ngập”; không bịa centimetres.

## Requirements Covered

R-03, R-04

## Implementation Steps

1. [R-03] Knowledge metadata độc lập numeric depth; measured/model/bulletin phải valid tại requested t. Positive report aged-out chưa có newer observation → stale_positive_observation/risky, không passable; retain lightweight last-positive provenance, không expire thành clean. No-history missing→risky; known positive bound vẫn blocked. Freshness generation invalidate tide_meta/_extremes/load_records/_FP khi input content thay đổi, không cache stale vô hạn.
2. [R-03/R-04] Request tide/rain/live-report snapshot+per-time depth cache. Arrival last-mile [arrive−t_in,arrive], exit [depart,depart+t_exit], conservative duration initial 2×(path metres/ALLEY_SPEED)+5min, named config constant và approximate label, tune bằng field timing. Sample interval boundaries/known peaks; nếu path đổi re-evaluate new interval, không claim instant snapshot là whole-trip safe. Lot access ways resolve deterministic, worst relevant connected ways+real names; no access→missing/unverified, không first-edge/name empty. Large-road forecast giữ temporal model riêng.
3. [R-04] Thêm failure codes và blocked-way provenance trong route/stop checks; bỏ substring “lúc rời đi”. Xác định flooding failure bằng code, không generic no-exit. Giữ depth/source/time ở từng leg; worst_over tie cùng status chọn depth.hi lớn nhất, missing knowledge không mất khi tổng hợp.
4. [R-04] Replace synthetic probe bằng sweep15min tối đa12h, reuse graph/evidence/context, không crawl/Goong mỗi tick. Publish before/after chỉ khi candidate hard checks passed VÀ stop+mọi decisive arrival/exit traversal leg knowledge known; missing/stale/risky không qualifying tick. Không qualified→reason/no clock time. Full dwell legality evaluate arrive/depart/day/sign schedule boundaries, worst status wins; P.131 parity đổi ngày phải chặn. Không kéo pickup15min thành nhiều giờ: only park có stay-until; UI đổi intent park explicit trước evaluate, không publish deadline ngầm đổi intent. Dead-end/no-fit không gán triều.
5. [R-03/R-04] Create tests.test_flood_safety và tests.test_plan_timing, giữ hydro behavioral cases: expired bulletin/no-history/aged-out positive report không qualifying timing; T+2h15m missing thay vì nước rút; known dry/positive-blocked/deepest tie; flood trong traversal dù departure instant dry; lot access live report/name/no-edge; P.131c odd→even midnight; pickup không multi-hour deadline; both timing directions+null depth rendering. Timing predicates rerun sau phase3 width cutover.

## Contract Consumers

Không có LSP configured; inventory bằng source search. depth_at: `flood.py:320`, `plan.py:320,547,727`, `corridor.py:178`, `tests/test_hydro.py:63,68`. flood_status: `flood.py:321`, `plan.py:320,734,735`, `corridor.py:182,273`. worst_over: `plan.py:191,397`.
Update all listed sites; API numeric depth access ở `_walk` `plan.py:547-550`, `_evaluate` `:401-404`, corridor `_score` `:318-325` và Result `:193-195` cần guards. Preserve known-depth checks, do not re-pin wording tests.

## Verification

- `cd backend && ../.venv/bin/python -m unittest tests.test_hydro tests.test_flood_safety tests.test_plan_timing tests.test_corridor -v` → cases kể trên pass, isolated/offline; new modules created trong phase.
- API smoke với `FLAG_LIVE_HYDRO=0`, chọn date ngoài shipped bulletin coverage: known tide-prone street risky, nullable depth + missing_tide reason, stop unverified, không numeric centimetres giả.
- Bsk Vios/Fortuner + changed time/rain: before/after mỗi nút ứng với trip committed; dead-end-only không hiện “triều làm ngập”. Timeline label cho biết ngày trip và ngày measurement, không gọi measurement ngày khác là evidence của ngày demo.
- Source/network check trong smoke: timing sweep không gọi Overpass, Goong hoặc AI thêm mỗi tick; timestamps của reason chỉ segment thật.
- Timing assertion: report40cm tạiT, T+2h15m không có newer evidence → không publish stay-until. Midnight parking ban/traversal flood/lot access flood đều ngăn verified time; file revision đổi làm freshness/cache generation đổi trong cùng process.

## Load-Bearing Assumptions & Risks

- 15-minute sampling không chứng minh safety liên tục — breaks if: event/peak hẹp giữa tick → include known peak/report boundary timestamps; vẫn hiển thị approximation và margin, adjust (R-04).
- Rechecking full plan mỗi tick có thể nặng — breaks if: warm local run >3s không external I/O → reuse graph and depth evaluations, profile actual hot path; không rút checks để nhanh (R-04/R-10, adjust).
- Numeric model dự báo vẫn approximate, không real-world guarantee. Missing-history và stale-positive đã fail strict checks ở phase2; không đợi field phase5 để chặn false-green.

## Accepted Red-Team Deltas

S1–S3/S5: expiry không chứng minh nước rút; publish tick cần known decisive-leg evidence; dwell legality/midnight/intent preserved; traversal intervals có margin; lot access provenance; tide/IRD generation invalidation và rerun timing sau width phase.

## Execution Checklist

- [x] R-03: knowledge/nullable depth và all-consumer cutover.
- [x] R-04: real leg provenance + full-check timing + regressions.
