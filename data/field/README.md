# Field measurements (Evidence Tier: Measured)

Filled by the field team; no tool may invent, repair or default a value. Use the existing CSV headers; the backend
and `pipelines/eval_field.py` read columns by name.

## `measurements.csv`: one row per physically measured OSM way

- `osm_way_id` (required): from the app's evidence panel ("OSM way"). Each way appears once.
- `alley_name`: as signed, e.g. `Hẻm 123/45 Xô Viết Nghệ Tĩnh`. Sub-alleys of one chain form one evaluation group.
- `lat`, `lon`: a point on that way (GPS), used to load its street graph.
- `width_m`: narrowest physical clear width along the whole segment, wall to wall or step to step; not a cadastral gap and not the width at the mouth only.
- `uncertainty_m` (> 0): the tool's and method's error in metres; a perfect measurement does not exist.
- `bottleneck_at_m`: distance of that narrowest point from the segment start; `obstruction`: what forms it (step, ramp, stall, parked bikes…).
- `cut_count`, `start_covered`, `end_covered`, `max_spacing_m`, `truncated`, `complete`: coverage of the same segment. Mark `complete=true` only when both endpoints and the whole segment were measured at spacing ≤ 5.1 m and nothing was skipped.
- `width_basis`: `measured_clear_width` for a physical clear-width measurement. Incomplete coverage is kept for review but cannot authorise strict fit.
- `date`, `measured_by` (required), `note`, `photo_url` (a stable link; blur faces and plates, no personal history).

## `egress.csv`: what the way out looks like

`way_id` (a measured way), `observation` (one of `turn_space`, `no_turn_space`, `oneway_forward`, `oneway_backward`,
`two_way`, `sign_no_stopping`, `sign_no_parking`, `no_sign`, `unknown`), `observed_at`, `observer`, `provenance`,
`photo_url`. Do not test-drive anything dangerous to find out; `unknown` is a valid answer.

## Evaluation

1. With at least 20 rows, freeze the split once and commit it before looking at any result:
   `python3 pipelines/eval_field.py --measurements data/field/measurements.csv --make-split data/field/eval-split.json`
2. Score: `python3 pipelines/eval_field.py --measurements data/field/measurements.csv --egress data/field/egress.csv --split data/field/eval-split.json --output <report>.json`

The script refuses fewer than 20 rows, a missing or re-frozen split, and alley groups split across sides. The gate is:
no definite false fit for any vehicle, no wrong-way contradiction, and not everything abstaining. The model-only and
field-informed modes are reported separately (see the module docstring).

The backend reloads evidence on start and when an operator calls `POST /api/evidence/reload`.
