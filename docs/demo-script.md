# Demo script: Vào Được

## Purpose and evidence boundary

Use this runbook for a repeatable local review with three distinct claims. Before showing Hẻm 160, verbally disclose that its width scenario uses synthetic demo data; the audience-facing UI intentionally has no `Mock`/`Synthetic` label.

1. **Complete physical-access evidence:** Hẻm 160 demonstrates width coverage and routes in/out. Parking law remains determined by the real legality engine and may be unverified.
2. **Simulated flood risk:** the separate Hẻm 160 rain case makes modelled flood risk visible; it does not claim that water was observed.
3. **Repository-source comparisons:** Hẻm 220, Hẻm 328, and Hẻm 91 show what the repository's available OSM, IRD, and listing sources can and cannot establish without synthetic width rows.

The executable owner is [`backend/app/demo_fixture.py`](../backend/app/demo_fixture.py); the synthetic width rows are visibly marked in [`backend/tests/fixtures/synthetic_demo_measurements.csv`](../backend/tests/fixtures/synthetic_demo_measurements.csv). Normal `app.main:app` does not load this fixture. The field width and egress files, [`data/field/measurements.csv`](../data/field/measurements.csv) and [`data/field/egress.csv`](../data/field/egress.csv), currently contain headers only, so do not describe any alley as field-measured or fully verified.

## Start the isolated demo

Install dependencies using the root [run instructions](../README.md#run-it), then use two terminals from the repository root.

Terminal 1:

```bash
cd backend
../.venv/bin/python -m app.demo_fixture
```

The launcher prints the local URL and a randomly generated operator password for this run. It binds only to loopback, removes inherited provider credentials, and keeps store, cache, and flags under a unique temporary directory rather than the normal application paths.

Terminal 2:

```bash
cd frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Open <http://127.0.0.1:5173/?demo=1>. Vite forwards `/api` to the fixture backend according to [`frontend/vite.config.ts`](../frontend/vite.config.ts). The query parameter also shortens active parking-watch checks to 15 seconds.

## Core run of show

### 1. Complete Hẻm 160 physical-access evidence (parking law unverified)

1. In **Demo → Kịch bản**, choose `Quán cà phê gần đường hay ngập` at `Hẻm 160 Ngô Tất Tố, Bình Thạnh`.
2. Wait for the dry plan. The UI has no data-origin badge; verbally disclose that this Hẻm 160 scenario uses synthetic fixture data.
3. Show `Xe vào và ra được` and the adjacent parking-law uncertainty. The selected door result must show a vehicle fit, a usable way out, and passable flood checks; it does not assert that parking is legally permitted.
4. Open the stop details. The audience-facing UI hides the fixture tier; describe the displayed width as part of the synthetic demo scenario, never as a field measurement or safety advice. The local API retains `Synthetic` / `synthetic_demo_width` provenance.
5. Select **Toyota Vios** if it is not already selected, then open `Xem xe trong hẻm`. The BSK reference run shows a seven-step simulated maneuver with a `9,8 m` path. Describe it as a local 2D visualization, not a measurement or an access decision.

Reference captures for this tested fixture state:

- [`phase-06-h160-synthetic-success-desktop.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h160-synthetic-success-desktop.png)
- [`phase-06-h160-vios-maneuver-desktop.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h160-vios-maneuver-desktop.png)
- Pixel 7 result and stop badges: [`phase-06-h160-synthetic-success-pixel-7.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h160-synthetic-success-pixel-7.png)
- Pixel 7 evidence details: [`phase-06-h160-synthetic-provenance-pixel-7.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h160-synthetic-provenance-pixel-7.png)

### 2. Visible simulated flood risk: Hẻm 160

1. In **Demo → Kịch bản**, choose `Mưa giả định 45 mm/h · Hẻm 160`.
2. Wait for the plan and show the `Có thể ngập` badge. The overall verdict remains `Chưa đủ bằng chứng để khẳng định` because the exit and other criteria are not all verified; this is the flood-risk example, not the dry success case.
3. Keep the interpretation precise: this is model risk from simulated rain combined with the available flood and tide sources. It is not a camera, sensor, driver, or field observation of physical water.
4. The UI has no fixture-origin badge. Keep the verbal disclosure explicit: only the Hẻm 160 width rows are fixture data; parking legality remains unverified from actual sources.

The BSK reference capture for this state is [`phase-06-h160-simulated-rain-risk-desktop.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h160-simulated-rain-risk-desktop.png).

### 3. Repository-source uncertainty: Hẻm 220, Hẻm 328, and Hẻm 91

For each comparison below, select the preset, wait for the plan, and open the selected stop's evidence details:

1. `Nhà bạn trong hẻm, giờ triều cường` — Hẻm 220/9 Xô Viết Nghệ Tĩnh.
2. `Đón khách trong hẻm không vào được ô tô` — Hẻm 328 Xô Viết Nghệ Tĩnh.
3. `Hẻm gần Nguyễn Hữu Cảnh` — Hẻm 91 Nguyễn Hữu Cảnh.

These cases receive no synthetic width rows. No provenance badge appears in the audience-facing UI; verify the API reports `synthetic_demo_data=false` and no `Synthetic` width rows, then read the actual source, status, and missing-evidence messages rather than infer a measured width or verified route. Use Hẻm 328 to discuss the current OSM access restriction, Hẻm 220 to discuss the tide-window scenario, and Hẻm 91 to discuss the available flood history; preserve every uncertainty shown by the planner.

Current BSK reference captures:

- H220 uncertainty: [`phase-06-h220-real-data-uncertain.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h220-real-data-uncertain.png).
- H328 uncertainty: [`phase-06-h328-real-data-uncertain.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h328-real-data-uncertain.png).
- H91 flood-data gap: [`phase-06-h91-real-data-flood-gap.png`](../plans/261014-1225-demo-wow-features/reports/phase-06-h91-real-data-flood-gap.png).

These captures describe the current repository fixture/source state, not a promise that external data will never change.

## Optional feature flows

### Watch the exit while parked

1. Return to the dry `Quán cà phê gần đường hay ngập` Hẻm 160 preset. Ensure simulated rain is off and wait for `Trong ngưỡng xe`.
2. Tap `Bắt đầu` under `Theo dõi điểm đỗ`. Notifications are optional; the in-app banner is the fallback.
3. In **Demo**, turn simulated rain on and set it to `45 mm/h`, then close the menu.
4. Tap `Kiểm tra ngay`, or keep the page visible for the next 15-second demo check.
5. Expected: the departure flood state worsens and the app shows `Ngập đường ra xấu hơn tại Hẻm 160 Ngô Tất Tố.` This alert reports a model/status change, not observed water. The watch also does not turn an unverified stop into verified evidence.
6. Tap `Kết thúc` before changing destination or vehicle.

If a re-check fails, show its failure and the last successful check time. Do not claim the way out remains safe from a failed request.

### Submit and review a driver report

Run this after the comparison cases so the new temporary observation does not alter their presentation.

1. From a selected stop, open **Demo** and tap `Đã tới nơi`.
2. In `Báo cáo điểm dừng`, enter `Vào được nhưng phải gập gương, ra phải lùi`. The isolated launcher supplies no provider credentials, so use the manual choices rather than promising AI parsing.
3. Set result `Hơi chật` and exit `Lùi ra`, inspect the review form, then tap `Gửi báo cáo`.
4. The report is pending and is not published as evidence yet.
5. In **Demo → Điều hành**, sign in with the one-run password printed by the backend launcher and approve the confirmation.
6. The claim appears as `Có thông tin lối ra`; it remains a driver observation, not a clear-width measurement or verified turn.

## Fallbacks and shutdown

- The fixture intentionally removes paid-provider credentials. Do not promise live search, provider routing, AI parsing, cameras, or provider map tiles during this run.
- If a base-map or other network request fails, keep the review on the cached Bình Thạnh plans and their evidence panels.
- Before shutdown, tap `Kết thúc` for any active parking watch.
- Stop the frontend and backend with `Ctrl-C`. Exiting the backend removes its temporary fixture state; no normal store, cache, or flags path is written by this launcher.
