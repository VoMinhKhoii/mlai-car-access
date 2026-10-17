---
phase: 10
title: "Voice-requested rerouting"
status: pending
priority: P1
effort: ""
dependencies: [7, 8]
---

# Phase 10: Voice-requested rerouting

## Overview
Allow a driver to explicitly say that the current road is congested, obtain a fresh foreground GPS fix, calculate alternatives with the existing corridor router, switch to its best available route, and hear a short spoken result. This is a user-requested reroute, not always-on listening or autonomous traffic monitoring.

## Current Behavior
- `frontend/src/App.tsx:323-331` — `locate()` gets one high-accuracy fix but falls back to `DEMO_ORIGIN` on denial/error; unsuitable as a live reroute origin.
- `frontend/src/App.tsx:227-255,491-492` — corridor is requested from current origin/destination and rendered as selectable alternatives; no voice-triggered reroute or spoken response.
- `frontend/src/api.ts:198-215` — corridor request/route response types already expose candidates, chosen route, live-data status and source.
- `backend/app/main.py:756-780` — `/api/corridor` accepts bounded origin/destination/vehicle and queues camera reads only for an operator.
- `backend/app/corridor.py:205-278,305-310,402-416` — existing route alternatives are scored by ETA, flood and cached traffic; stale/unknown traffic is explicitly disclosed.
- `frontend/src/voice.ts` — shared Gemini audio capture/transcription exists; planned Phase 8 `VoiceTrip.tsx` will also use it. Reroute must reuse transcription, not create another microphone/provider path.
Unknowns: actual GPS accuracy, freshness, device/browser support and current camera coverage at drive time; these must fail closed to the existing route and be reported, not guessed.

## Target Change
- Create: `frontend/src/components/VoiceReroute.tsx` — explicit voice action, transcript/intent status, reroute state and spoken outcome.
- Modify: `backend/app/ai.py:161-165` — constrained text intent parser returning only reroute-vs-unclear; no free-form actions.
- Modify: `backend/app/main.py:511-518` — trip-independent intent endpoint using existing guest voice limits and provider error semantics.
- Modify: `backend/app/flags.py:59-62` — add `ai_voice_reroute`, default off.
- Modify: `frontend/src/App.tsx:22-25,55-58,91-98,227-255,323-331,471-492` — one-shot live position, separate corridor origin, route selection and stale-request protection.
- Modify: `frontend/src/api.ts:198-215,314-316` — typed intent and cancellable corridor request.
- Modify: `frontend/src/index.css:474-506` — accessible reroute control/status using current voice design tokens.
- Modify: `backend/tests/test_api_validation.py:70-96,335-348` — isolated API contract tests for intent, flags, bounds and budgets.

## Requirements Covered
V-10

## Implementation Steps

1. [V-10] Add `ai_voice_reroute`, default off, and a strict text parser returning only `reroute_avoid_congestion` or `unclear`; use configured text provider on the user-confirmed transcript, reserve AI budget and share existing voice rate/global caps. No destination, coordinates, route options or arbitrary action fields accepted.
2. [V-10] Add `POST /api/voice/reroute/parse`; explicit recording action reuses Phase 7 Gemini transcription. Only a clear reroute intent proceeds; unclear speech asks for a concise restatement and never calls corridor.
3. [V-10] After clear intent, obtain `getCurrentPosition` in foreground with high accuracy; require callback fix age ≤10 s and reported accuracy ≤50 m. Reject outside-HCMC point, errors, timeout, stale/poor fix; never use `DEMO_ORIGIN` or saved manual origin as live location.
4. [V-10] Keep GPS reroute origin separate from saved trip origin and `/api/plan` state. Call existing cancellable `/api/corridor` with the live fix, committed destination and current vehicle; do not change destination, vehicle, intent, dwell, watch, reports or evidence.
5. [V-10] On latest request only, select server-chosen route if `available`, route status is not `blocked`, and traffic is sufficiently current/known to claim a reroute; otherwise keep prior selected route and report uncertainty. Existing camera scheduling remains operator-only; do not circumvent Operator authorization.
6. [V-10] Announce concise route label and ETA once with browser `speechSynthesis`; visible result remains usable if TTS is unavailable. No Gemini speech generation, background mic or turn-by-turn navigation.
7. [V-10] Add isolated API intent/flag/rate tests and browser cases for GPS permission/accuracy/age, unchanged saved trip fields, abort/stale requests, no safe alternatives, unknown traffic, duplicate command and TTS fallback.

## Verification

- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_api_validation.py' -v` → exit 0; reroute flag-off/config/budget/parser errors distinct; malformed/ambiguous intent never triggers route logic.
- `PYTHONPATH=backend .venv/bin/python -m unittest discover -s backend/tests -p 'test_corridor.py' -v` → exit 0; existing traffic/flood scoring and unknown-data behavior unchanged.
- `npm --prefix frontend run build` → exit 0; shared recorder reused, no duplicate audio/provider path.
- Browser on trusted loopback/HTTPS: explicit voice command → editable transcript → bounded intent parse → one fresh GPS fix → one corridor call → safe chosen route selected and announced once. Verify manual origin/destination/vehicle/intent/dwell and evidence are unchanged.
- Denied/timeout/out-of-area/old (>10 s)/inaccurate (>50 m) location, unclear intent, stale response, unknown/stale traffic, blocked/unavailable alternatives or TTS denial → previous route remains active, no unsupported claim, visible fallback; no demo-origin substitution or duplicate request.

## Load-Bearing Assumptions & Risks

- One-shot browser GPS is available only in secure contexts and permission can be denied — breaks if no fresh fix → preserve old route and announce failure; never fall back to demo/saved location.
- `/api/corridor` uses existing ETA/flood/cached-camera policy; camera readings may be absent and new reads are operator-only — breaks if traffic confidence/freshness is insufficient → do not claim congestion avoidance, preserve old route.
- Browser speech synthesis may lack a Vietnamese voice — breaks if no usable `vi-VN` voice → show route result without blocking.
- Current app is not turn-by-turn navigation; this delivers one-shot route recalculation and spoken summary only — breaks if acceptance requires live maneuver instructions → separately scope navigation provider and driving mode.
- Gemini key is secret — never read it into chat/artifacts or bundle it; configure only server-side after verifying paid-project status.
