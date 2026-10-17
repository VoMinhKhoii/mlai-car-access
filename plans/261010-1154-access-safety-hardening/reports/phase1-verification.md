# Phase 1 verification — 2026-10-11

Status: phase1 approved after post-repair verification and independent re-review; user requested commit/push before phase2. Initial failures below are retained as historical evidence.

## Executed checks

- `cd backend && ../.venv/bin/python -m unittest tests.test_api_validation`: failed in setUpClass, zero assertions executed. Rejected non-finite dwell input is included in FastAPI validation errors; JSON response serialization raises `ValueError: Out of range float values are not JSON compliant`.
- `cd backend && ../.venv/bin/python -m unittest discover -s tests`: 22 tests, 19 passed, 1 failure, 2 errors. APIValidation setup error above; `test_corridor.ModelFallback.test_next_model_reads_when_the_first_is_out_of_quota` errors at cameras.py:299 (`TypeError: can only join an iterable`); `test_hydro.Rain.test_no_gauge_nearby_uses_the_forecast_only` fails because sample points are empty. Attribution of camera/rain failures awaits diagnosis.
- `npm --prefix frontend run build`: passed. Large-bundle warning remains.
- `npm --prefix frontend run lint`: exit 0, 11 warnings, no errors.
- Actual isolated uvicorn HTTP requests: malformed/naive datetime 422; null/aware datetime 200; zero/fractional duration 422; non-finite duration 500. Real state and .env.local were excluded.

## Browser smoke

Chrome desktop, Vite development surface, temporary backend STORE/CACHE/FLAGS:

- Pickup preset rendered after planning.
- Native year deletion followed by Xong left the application and committed trip intact, with an inline error and focus returned to the date field.
- Native year repair and hour increment committed 11:00. Capture request `db178276e62e5:n71` contains `2026-09-29T11:00:00+07:00`; HTTP 200.
- Between initial pickup request and valid repair, capture contains no invalid-date plan POST.
- Result/footer/button label used OSM for the OSM reference route.
- Screenshots: phase1-desktop.png, phase1-mobile.png.
- Capture: phase1-browser-capture.json. Started before navigation and stopped/exported before session cleanup. Response bodies over capture size limit were omitted, not assumed empty.

## User-authorized live Goong retest

Keys loaded only into the temporary backend process from user-provided key.txt. Keys were not printed, copied into tracked config, or included in a new request capture. Backend state remained isolated.

- Configuration booleans confirmed Goong API and map tiles enabled.
- Live autocomplete `Hẻm 328`: HTTP 200, Goong suggestions returned (observed 0.68 s).
- Live place detail: HTTP 200 with coordinates and address.
- Actual plan HTTP request: 200, `standard_route.source = goong` (observed 3.96 s).
- Browser live search `Hẻm 328 Xô Viết Nghệ Tĩnh`: six Goong options. ArrowDown/Enter selected `8E Hẻm 328/76 Xô Viết Nghệ Tĩnh, Thạnh Mỹ Tây, Hồ Chí Minh`; address and plan rendered.
- Result/footer/button labels used Goong for the Goong reference route.
- Type then immediately erase query and Tab: suggestions did not reopen; committed address was preserved after blur. This exercises cancellation before the debounce completes, not a deterministic delayed-response race.
- iPhone-14 viewport emulation: native year deletion and Xong showed inline invalid-date explanation over the still-rendered plan; arrival chip remained “Đi ngay”. Screenshot: phase1-goong-mobile-invalid-date.png. Keyboard was used to open mobile menus; pointer targeting after emulation did not reliably open the intended control.
- Both browser sessions stopped. No physical-device verification claimed.

## Initial remaining gate work (superseded by post-repair evidence below)

- Fix non-finite validation response and obtain passing API regression/full-suite proof.
- Resolve review findings and diagnose camera/rain failures without assuming they are unrelated.
- Deterministic in-flight search/detail response races; zero-distance and unverified Fortuner scenarios; 90-minute dwell representation; console-error audit and remaining phase1 browser criteria.
- Plan remains in-progress, phase1 acceptance open. Phases2–5 untouched. Live Goong success does not change the existing non-finite-duration failure.

## Independent review and diagnosis

- Review requests changes: `Result.tsx` now suppresses the flood warning when the best stop is unverified, while still showing the departure-time action. Restore the hazard explanation without implying the stop is verified.
- `key.txt` and `.venv/` are not ignored. No staging/commit occurred. Ignore credentials before any future staging operation; do not publish keys.
- Diagnosis traced camera failure to the existing test mocking successful AI calls without a provider identity; traced hydro failure to a fixed 2026-10-05 forecast fixture compared against real wall-clock time. Both files/tests are unchanged by phase1, with defects present in existing commits. No failure was rerun to confirm.
- Proposed baseline repairs are test-only: provide an explicit mocked camera provider, and freeze the hydro test clock. These require a scope decision before implementation.
- The mandatory regression decision remains unresolved: the user requested live Goong retesting instead of choosing a repair option. Live retesting succeeded but did not repair the non-finite 500 or the copy regression.

## Approved repairs and post-repair evidence

User approved phase1 blocker fixes and two baseline test repairs.

- Request-validation errors now return 422 with `loc/msg/type`, excluding unsafe rejected input/context echoes. Strict positive-integer validation remains unchanged.
- Result hazard presentation again applies to unverified stops, with an explicit unverified qualifier; a suggested departure time does not imply clearance/egress proof.
- Camera fallback fixture owns its mocked provider identity; hydro fixture owns its clock. Production camera/hydro behavior unchanged.
- `.gitignore` excludes key.txt and root .venv/. No staging or commit.
- Targeted backend checks: API validation 6/6, camera fallback 1/1, hydro rain 3/3; total 10/10.
- Full Python suite: 28/28 passed in 12.335 s. ResourceWarning for existing unclosed vehicle CSV remains.
- Frontend build passed; lint exit 0, 11 warnings, no errors. Existing large-bundle warning remains.
- Independent real uvicorn request with raw numeric `dwell_min: 1e309`: HTTP 422, detail contains only JSON-safe `loc/msg/type`.

### Post-repair browser proof

- Actual Fortuner workflow (no plan mock): “Gợi ý chưa xác minh”, walk 0 m / 0′ / 0 phút; no “Chắc nhất” claim. Screenshot phase1-postfix-fortuner-zero.png.
- Actual cafe preset: dwell chip 1 giờ 30 phút; native select value 90 retained. Mobile emulated screenshot phase1-postfix-mobile-dwell.png.
- OSM reference route label observed in the layers menu, result, and footer.
- Explicit temporary UI-only fixture: an unverified stop plus a leave-before hazard renders both flood warning and unverified qualifier. This fixture proves presentation precedence, not timing safety or real field evidence. Screenshot phase1-postfix-hazard-zero.png.
- Controlled 1500 ms search-response fixture: clear and blur after the request starts both abort the request (`ERR_ABORTED`); waiting past its response delay does not reopen suggestions or restore a destination. Capture requests dfc63ac90e857:n79/n80.
- Console capture: website entries are Vite debug messages; warnings and one resource error are attributed to browser extensions. No website Invalid time value or invalid DOM nesting diagnostic observed.
- Final capture phase1-postfix-browser-capture.json includes marked mock interventions. Browser session and both servers stopped; all temporary fixtures/state removed.
- Physical-device/touch behavior and a separate delayed place-detail response scenario were not exercised. Native keyboard datetime behavior on the emulated mobile viewport was exercised in the earlier live-Goong smoke.

## Publication hygiene

Before commit, both captures were parsed for authenticated URI userinfo and exact supplied Goong-key matches: zero of either. The scanner's URI signatures matched source/URL syntax, not proven credentials. Non-business resource response bodies (Vite/client/bundled source and other assets) were removed from published captures; API request/response evidence and operation metadata remain, with removed bodies explicitly marked omitted. This also removes development-tool source content unnecessary for acceptance evidence.
