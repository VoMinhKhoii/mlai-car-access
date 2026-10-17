---
title: Access safety hardening plan
date: 2026-10-10
summary: "Plan-only branch, twelve requirements, single-backend decision and safety acceptance"
---

# Access safety hardening plan

## Context
Plan-only request after an evidence-backed code/UI review. New branch `fix/access-safety-hardening` created from local `main`; existing parcel cache modification preserved.

## What happened
Created `plans/261010-1154-access-safety-hardening/plan.md` and five phases through `ak plan` scaffolding. Defined R-01–R-12, file anchors, dependency order and behavioral verification. CLI validation succeeded; index reports five pending phases, zero implemented tasks. Three independent adversarial reviewers are examining the draft.

## Decisions
User selected one continuously running backend with a single process and persistent storage. Browser evidence is removed as an authority: server-owned areas plus request snapshots. Invalid dates remain invalid drafts rather than silently switching to now. Cadastral geometry is not a direct measured Clear Width. Real field data remains a human acceptance gate, not synthetic filler.

## Tooling limitation
Persistent active-plan pointer set by `ak plan use`. OMP hook adapter cannot load `ak-prefs-client.cjs`; alternate installed hook reports CK_SESSION_ID absent. Session hook context could not persist; absolute plan/report paths are supplied explicitly to every reviewer.

## Next
Finish red-team adjudication and whole-plan consistency, then offer validation or implementation. No product code implemented, tests/builds not claimed for the plan.

> Historical work record — not durable authority. Prefer docs/specs/ADRs for current decisions.
