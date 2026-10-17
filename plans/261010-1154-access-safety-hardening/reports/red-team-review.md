---
title: "Red-team: access safety hardening"
date: 2026-10-10
status: completed
---

# Red-team: access safety hardening

## Summary

Three independent read-only reviewers: trust/security, safety/flow, deliverability/contracts. 15 findings: 5 Critical, 7 High, 3 Medium. Controller checked cited source and accepted all15 with bounded remedies; user selected apply accepted findings. No code implemented and no new runtime exploit attempted.

## Findings & Dispositions

| ID | Severity | Finding / checked source | Disposition / applied |
|---|---|---|---|
| T1 | Critical | Anonymous live build can call listing-photo AI: main.py:226-232, live.py:181-215,299-303 | Accept: operator-only scheduling, all-model budgets, guest cached/static, phase4 |
| T2 | High | Queue tail50 has no lifecycle/pagination: ai.py:196-200; accepted sinks evidence.py:307-322,347-358 | Accept: keyed state separate extraction log, cursor pagination, explicit sinks/crash reconciliation, phase4 |
| T3 | High | async photo calls blocking AI; unbounded per-build threads: main.py:327-330, live.py:335-358 | Accept: off-loop calls + bounded single-flight builds/server deadlines + concurrency smoke, phase4 |
| T4 | Medium | Google SKU budget not per-key/model AI quota: budget.py:20-58, ai.py:65-88 | Accept: same reservation mechanism, separate AI namespace/attempt accounting, phase4; no extra distributed service |
| T5 | Medium | Import seed writes permanent demo blockage: main.py:55-67 | Accept: read-only explicitly simulated fixture outside community accepted store, phase4/restart phase5 |
| S1 | Critical | Live flood expires ±2h; tide coverage can expire: flood.py:242-256,153-161 | Accept: stale-positive missing not clean; qualifying tick requires known decisive-leg data, phase2 |
| S2 | High | Legality evaluated at arrive only despite parity signs: plan.py:414-415, legality.py:44-48 | Accept: dwell/day/schedule boundaries worst legality; pickup no silent multi-hour extension, phase2 |
| S3 | High | fl_arr/fl_dep single instant: plan.py:193; ALLEY_SPEED plan.py:609 | Accept: bounded traversal intervals+margin, no new router, phase2 |
| S4 | Critical | Numeric predicates ignore tier/coverage: plan.py:44-86,480-507; parcels.py:111-126 | Accept: decisive width basis wired into strict fit/turn predicates; sparse cuts diagnostic; actual-predicate tests, phase3 |
| S5 | High | Lot uses arbitrary edge profile/name empty: plan.py:395-397,469-473 | Accept: deterministic access-way names/knowledge, unknown lot geometry not verified, phases2/3 |
| D1 | Critical | SPA FileResponse path has no containment: main.py:455-461 | Accept: encoded/symlink containment and API-before-SPA, fake-secret fixture only, phase4/prod smoke5. Static risk, NOT exploited against real secrets |
| D2 | Critical | Measured loads unconditional and aliases apply by name: evidence.py:188,295-328 | Accept: evaluation exclusion seam phase3; grouped split, uncertainty+bottleneck and egress schema phase5 |
| D3 | High | Corridor may request more cameras than job cap: corridor.py:234-236,128-151 | Accept: deterministic subset≤12 and explicit requested/scheduled/dropped/per-hotspot unknown coverage; no claimed measured actual50–150 count, phase4 |
| D4 | High | Derived store paths captured at import: config.py:6-21, ai.py:25-26, budget.py:16, evidence.py:34-35 | Accept: startup temp/persistent paths phase1; subprocess fixtures before imports; isolated restart/concurrency smoke phases4/5 |
| D5 | Medium | Dev proxy localhost but backend bind127.0.0.1: vite.config.ts:6; vercel.json:17-21 | Accept: explicit127.0.0.1 dev proxy + real production proxy/cookie contract, phase5. Prior bsk worked; IPv6 failure is conditional risk, not observed failure |

## Boundaries & Verification

Evidence is static source+prior review/bsk findings; no code tests/builds run as part of plan-only delivery. `ak plan validate` passed on draft; final consistency/schema gate recorded in plan.md. Reviewer outputs were proposals, not authority to change product scope. Existing pending cache edit preserved.

Operator cookie/review authority, backend ownership, and field collection accepted in plan; live keys/host and real data are implementation prerequisites. Session hook adapter could not persist (missing dependency/CK_SESSION_ID); `ak plan use` persistent pointer exists, absolute paths passed to reviewers. Journal CLI wrote wrong project path; only newly created journal relocated into this repo, reported tool issue.

## Remaining Prerequisites

- Team supplies real >=20 surveyed segment records+photos+egress/sign observations and alias-disjoint split.
- Operator configures secrets and actual HTTPS backend origin if choosing Vercel frontend; never commit placeholders or keys.
- Real Goong/AI upstream smoke only when credentials present; simulated boundary tests are not live-service proof.
