# Phase 2 verification — 2026-10-11

Status: implementation and executable checks pass; final independent review retry was blocked by provider rate limits. Phase checkboxes remain open pending the interactive approval gate. This is phase evidence, not production or field-validation sign-off.

## Acceptance coverage

- **R-03:** flood knowledge is independent of nullable depth. Missing tide/history and an aged-out positive observation are risky/unverified; an expired dry report does not clear an older positive; only a newer still-valid dry report supersedes it. Positive known flood bounds remain blocked. Assessment provenance preserves `at`, `source`, and `freshness` at leg granularity.
- **R-04:** entry, stay, and egress have distinct flood assessments; traversal intervals use a conservative named duration and are explicitly approximate, while the requested dwell interval is exact. Flood failure codes distinguish arrival, stop, and exit from dead end/no-fit/legality. Timing sweep only starts when no stop is usable and a flood-specific failure exists; a clock requires verified hard checks and known/passable decisive legs. Pickup does not get a park-style stay-until; its response instructs changing the requested arrival instead of claiming a departure sweep.
- Timing, corridor, tide chart, result cards, and map popups show nullable depth and knowledge/reason without substituting fake centimetres. Known-dry results use the normal in-threshold label; missing knowledge remains visibly unverified.

## Executed backend checks

- Targeted: `python -m unittest tests.test_hydro tests.test_flood_safety tests.test_plan_timing tests.test_corridor tests.test_api_validation -v` — **53 tests passed**.
- Full backend discovery: **53 tests passed**, `OK`.
- Isolated API smoke used a temporary store/cache/flags and copied only the shipped demo OSM graph. Provider keys were blank; `.env.local` reads were masked; outbound `httpx` methods were blocked.
- Friend-house Vios `/api/plan`: HTTP 200, 3 stop points, `timing: null`; cold request 7.093 s, warm request 0.949 s. The plan's performance acceptance is the warm local run (<3 s); cold OSM graph initialization exceeded 3 s and remains visible as a cold-start risk.
- Expired flood report at T−10 h plus dry report at T−9 h, evaluated at T: HTTP response remains unverified/risky, `knowledge=stale_positive_observation`, `depth=null`; no numeric depth was fabricated. A still-valid dry control is known/passable with `depth=null`.
- Pickup request with a 120-minute dwell was accepted by the API boundary; product timing returned no clock and instructed the driver to select a different arrival time. Unit coverage verifies that pickup does not run an unexecuted 12-hour departure sweep.
- External HTTP calls during isolated tests/smoke: **0**.

## Frontend and browser evidence

- `npm --prefix frontend run build`: passed; 1,900 modules, 572 ms. Vite reports a 1,345.02 kB minified JS chunk (>500 kB warning).
- `npm --prefix frontend run lint`: exit 0; **14 warnings**, no errors.
- Browser smoke exercised the rainy Ngô Tất Tố preset at 14:00 and a committed 15:00 arrival on desktop and iPhone-14 viewport emulation. The result shows the 45 mm/h scenario, a 10–40 cm modeled segment at the rain time, a 10–100 cm dwell-window range, dated per-leg evidence, nullable depths where evidence is absent, and no fabricated dry status. Mobile screenshot: `phase2-vios-rain-mobile-committed.png`; desktop screenshots: `phase2-vios-rain-desktop-final.png` and `phase2-vios-rain-desktop.png`.
- Physical-device/touch behavior was not exercised. Viewport emulation is not device proof.

## Review and verification history

- Initial integrated phase-2 verification found a corridor `NameError`, dropped measured rain, a >280 s request, timing published on healthy plans, and an expired-dry/stale-positive hole. The implementation was repaired; these failures are retained here as history, not current results.
- The latest successful independent review approved the code but blocked phase sign-off on three stale documentation statements. Those statements were corrected afterward. A focused reviewer retry then failed due provider rate limits; no post-correction review verdict was produced. The earlier review is retained in session history `PhaseTwoLastReview`; it did not execute tests.
- A subsequent backend test scaffold was removed; `.coverage` is ignored and absent. `backend/cache/live/parcels.json` was left unchanged/un-staged. No commit or push of phase 2 occurred.

## Remaining limits

- No real field calibration; R-11/R-12 remain mandatory release gates.
- 15-minute sampling plus traversal margin is an approximation, not proof of continuous safety.
- Cold plan startup measured above 3 s; warm plan met the plan target.
- 14 lint warnings, large bundle warning, and pre-existing `vehicles.py` CSV `ResourceWarning` remain.
- Current parking-sign timing data is day-parity based; hour-scoped sign schedules are not present in the source data.
