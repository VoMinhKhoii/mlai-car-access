# Demo script: Vào Được

## Purpose
Show the three selected features in a repeatable 4–5 minute flow. Keep safety conclusions tied to the planner; mark simulation and incomplete evidence clearly.

## Prerequisites
- Run one backend worker with persistent temporary or demo `STORE`, `CACHE`, and flags; serve the frontend from the same origin in production.
- For local Vite, allow its exact origin in `APP_ORIGINS`.
- Open the application with `?demo=1` to make parking-watch checks run every 15 seconds. The normal interval is five minutes and only while the page is active.
- Load the `Quán cà phê gần đường hay ngập` preset in the Bình Thạnh demo area. This preset has a known dry-vs-rain change for the egress flood status in the current shipped demo graph.
- Keep `ai_voice_report` enabled only if demonstrating parser output. A model/API key is optional; without it the UI must fall back to manual choices.
- On a phone, use Android Chrome. Browser notifications are optional; the in-app banner is the fallback.

## Run of show

### 1. See the car in the alley (laptop, ≤ 90 seconds)
1. Select a preset and wait for the plan to finish.
2. Leave the selected stop card collapsed. Point out the verdict, stop name, and four compact status tags.
3. Open `Xem xe trong hẻm`.
4. Say what is actually shown: the dashed interval is uncertain; the footprint is a local 2D visualization; it is not a width measurement or an access decision. In the current demo preset, the narrow lower bound does not produce a turn path, so the UI states that rather than pretending the alley is safe.
5. Open the stop details to show the route, flood, and law evidence, then collapse them again.

### 2. Watch the exit while parked (Android Chrome, ≤ 90 seconds)
1. On the `Quán cà phê gần đường hay ngập` preset, open Demo and turn simulated rain **off**. Wait until the selected stop shows `Trong ngưỡng xe` for its departure flood check.
2. Tap `Bắt đầu` in `Theo dõi điểm đỗ`. This stores the plan and stop in this browser only. The selected stop remains labeled unverified; watch does not make it verified.
3. Optionally tap `Bật thông báo`. If permission is denied/unsupported, keep the app banner visible.
4. Open Demo and turn simulated rain **on** (45 mm/h). Close Demo. In demo mode, wait for the next check (or tap `Kiểm tra ngay`).
5. Expected: the stop’s departure flood state worsens from passable to risky and an in-app alert appears: `Ngập đường ra xấu hơn tại Hẻm 160 Ngô Tất Tố.` The message is a model/status change, not a measurement that water is physically present.
6. Tap `Kết thúc` to clear the local watch session.

### 3. Submit a reviewed driver report (Android Chrome, ≤ 90 seconds)
1. From the selected stop, open Demo and tap `Giả lập đã tới nơi`.
2. In `Báo cáo điểm dừng`, enter `Vào được nhưng phải gập gương, ra phải lùi` (or use the microphone if available). If the AI flag/model is off, use the manual chips.
3. Set result `Hơi chật` and exit `Lùi ra`. Inspect the review form, then tap `Gửi báo cáo`.
4. Expected: `/api/confirm` returns pending; no evidence is published yet.
5. In Demo → Điều hành, sign in and approve the confirmation. The egress claim appears as `Có thông tin lối ra`; it remains unverified and does not change `strict`, `decisive_clearance`, or `turn_verified`.

## Live run and fallback
- For an arbitrary HCMC address, expect a live area build only when enabled and available. If the area data is missing/stale, call that out and return to the prepared Bình Thạnh preset.
- If Gemini is unavailable, the voice parser returns `unclear`; manual chips/text still submit reports for review.
- If the camera/base-map network fails, omit unrelated camera/tiles claims; the three feature flows use the plan and review APIs, not camera CV.
- If a watch re-check fails, show the last successful check time and the failure. Never say the way out remains safe based on a failed request.

## Operator notes
- Confirmation reports are pending until approved. Approval reloads the evidence index and invalidates cached plans.
- Vehicle passage/turn observations are not clear-width measurements and do not verify a turn at the selected stop.
- Stop monitoring before changing the destination or vehicle; the session is local and can be ended from the result card.
