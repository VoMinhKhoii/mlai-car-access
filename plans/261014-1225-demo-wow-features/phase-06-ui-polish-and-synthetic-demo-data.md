---
phase: 6
title: "UI polish and synthetic demo data"
status: in-progress
priority: P1
effort: "2d"
dependencies: [1, 2, 3, 4, 5]
---

# Phase 6: UI polish and synthetic demo data

## Overview
Polish the map-first result UI using `origin/main` as a visual reference, then add an opt-in local-only synthetic fixture so the demo can show complete width evidence alongside deliberately incomplete and narrow cases. The fixture is never field truth.

## Requirements
- Result hierarchy: keep map primary; headline + best actionable stop first; four concise status tags; detailed evidence on demand. Reuse `frontend/src/ds/README.md` tokens/components and main’s concise “best stop + walk time” phrasing.
- Synthetic fixture: never write to `data/field/measurements.csv`; load only through the isolated, loopback-only launcher. Gate each overlay by the H160 preset ID, destination proximity, and fixture way IDs. Keep the audience-facing UI free of `Mock`/`Synthetic` labels; the presenter discloses the demo data verbally. Preserve internal `Synthetic` provenance and `synthetic_demo_width`; never relabel fixture evidence `Measured` / `Đo thực tế`.
- Scenarios: Hẻm 160 has a complete access-evidence dry case (width coverage across the stop/ingress/egress, dry baseline) without inventing parking-law permission; the existing legality engine may still report uncertainty. A separate 45 mm/h rain preset shows modeled flood risk without claiming observed water. Hẻm 328, 220, and 91 receive no fixture rows and preserve repository-source uncertainty.
- Safety: normal field ingestion rejects synthetic basis rows, safety thresholds and legality rules stay unchanged, fixture evidence never becomes a genuine measurement, missing flood/legal/egress statuses remain visible, and synthetic demo mode is not the default.

## Implementation Steps
1. Separate physically verified entry/exit from parking-law status in the concise result card; never replace an unknown legal result with a demo permit.
2. Add fixture-only backend loading and explicit config signal; keep normal `app.main` on real `data/field/measurements.csv`.
3. Add a marked synthetic CSV in `backend/tests/fixtures/` and a loopback-only launcher with temporary store/cache.
4. Update the demo runbook with the fixture warning and scenario sequence.
5. BSK-check desktop and Pixel 7 emulation: successful Hẻm 160 dry flow, Hẻm 160 rain-risk flow, and Hẻm 328/220/91 with unmodified repo data; verify no visible `Mock`/`Synthetic` labels and no cross-scenario fixture leakage.

## Success Criteria
- [x] With demo fixture off, config says synthetic data is false and normal field CSV remains the only measured-width source.
- [x] H160 dry shows the complete physical access path only when width, entry, exit, and all flood windows are positively supported; any unverified parking-law result remains explicit. H160 rain keeps a cautious flood-risk result. H220/H328/H91 have no fixture rows; API provenance stays request-scoped `Synthetic`, never `Measured`.
- [ ] Desktop BSK shows the physical-access headline, legal uncertainty, and flood-risk state. At 375px, the result and evidence panels fit without horizontal scrolling or audience-facing `Mock`/`Synthetic` labels.
- [x] No fixture data, operator report, or cache is written into the real field-data directory or tracked production store.

## Risk Assessment
- A simulated success can be mistaken for real access advice. Keep the demo loopback-only, impossible to activate through the normal app entrypoint, and internally traceable as synthetic; presenter disclosure is verbal. Never use the fixture to override parking-law checks.
- OSM IDs can change; launcher must fail clearly when fixture ways are absent instead of silently marking another way as measured.
