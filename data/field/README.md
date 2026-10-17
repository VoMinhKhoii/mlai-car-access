# Field measurements (Evidence Tier: Measured)

Filled only by the field team; no tool may invent, repair, or default a value. Keep the documented CSV headers; the
backend and `pipelines/eval_field.py` read columns by name. The evaluator refuses incomplete observations rather than treating them as ground truth.

## `measurements.csv`: one row per physically measured OSM way

- `osm_way_id` (required): from the app's evidence panel ("OSM way"). Each way appears once.
- `alley_name`: as signed, e.g. `Hẻm 123/45 Xô Viết Nghệ Tĩnh`. Sub-alleys of one chain form one evaluation group.
- `lat`, `lon`: a point on that way (GPS), used to load its street graph.
- `width_m`: narrowest physical clear width along the whole segment, wall to wall or step to step; not a cadastral gap and not the width at the mouth only.
- `uncertainty_m` (> 0): the tool's and method's error in metres; a perfect measurement does not exist.
- `bottleneck_at_m`: distance of the narrowest point from the segment start; `obstruction`: what forms it (step, ramp, stall, parked bikes…).
- `cut_count`, `start_covered`, `end_covered`, `max_spacing_m`, `truncated`, `complete`: coverage of the same segment. Release evaluation requires both endpoints and the whole segment measured at spacing ≤ 5.1 m with at least two cuts and nothing skipped (`complete=true`, `truncated=false`).
- `width_basis`: must be `measured_clear_width` for physical clear-width measurements; cadastral gaps and road-width estimates are not ground truth.
- `date`, `measured_by`, `note`, `photo_url`: retain the source context; note may be empty. `photo_url` must be a stable HTTPS link without credentials, query parameters, fragments, email addresses, phone numbers, or secret-bearing path components. Blur faces and plates; record no personal history.

## `egress.csv`: three explicit dimensions per evaluated way

Each held-out way requires exactly one row for each `dimension`: `direction`, `turn_space`, and `sign`. `unknown` is
an explicit observation within one dimension; it is coverage, not a substitute for an omitted row.

- `way_id`: a measured OSM way.
- `dimension=direction`: `observation` is `oneway_forward`, `oneway_backward`, `two_way`, or `unknown`.
- `dimension=turn_space`: `observation` is `turn_space`, `no_turn_space`, or `unknown`.
- `dimension=sign`: `observation` is `sign_no_stopping`, `sign_no_parking`, `no_sign`, or `unknown`.
- `observed_at`: timezone-aware ISO-8601; `observer` and `provenance` are required.
- `photo_url`: a stable HTTPS reference under the same no-PII/no-credentials rules as measurement photos.

Duplicate or conflicting `(way_id, dimension)` rows and observations outside that dimension's vocabulary are
rejected. Do not test-drive anything dangerous to find out. `no_sign` is not evidence that parking or stopping is
legal.

Direction is the only comparable egress dimension: field direction is compared with the OSM `Way.oneway` value used
by route entry/exit, and a contradiction blocks the gate. Turn-space and sign rows are always reported as
`unscored`/`not_comparable`; the evaluator has no corresponding model claim. `no_turn_space`, `sign_no_stopping`, and
`sign_no_parking` are retained as descriptive blocking observations, but do not by themselves fail this evaluator
gate. They are not verified outputs, and legal/turn-space behavior remains unverified for R-12.

## Frozen split lifecycle

1. Require at least 20 valid distinct measured ways and 20 independent normalized alley-chain groups. Freeze the
   balanced initial split before inspecting results, using a versioned filename:
   `python3 pipelines/eval_field.py --measurements data/field/measurements.csv --make-split data/field/eval-split-v1.json`
2. If the measurement dataset later grows, preserve the parent file and create a new version:
   `python3 pipelines/eval_field.py --measurements data/field/measurements-v2.csv --extend-split data/field/eval-split-v1.json --make-split data/field/eval-split-v2.json`
   Every parent row must remain semantically unchanged. Parent held-out IDs/groups stay held-out, parent calibration
   stays calibration, new rows in an existing group inherit that side, and entirely new groups enter calibration.
   Append-only children may be calibration-heavy, but the gate retains at least 10 held-out independent groups and
   10 held-out ways and reports the held-out/calibration ratio; never re-freeze or overwrite the parent.
3. Score with a structured egress CSV and the matching frozen split:
   `python3 pipelines/eval_field.py --measurements data/field/measurements.csv --egress data/field/egress.csv --split data/field/eval-split-v1.json --output <report>.json`

The evaluator rejects incomplete or duplicate survey rows, missing dimension coverage/provenance, stale or malformed
splits, altered/removed parent rows, unknown split assignments, and label leakage. Reports separate model-only and
field-informed width results. Interval errors/coverage use bounded predictions only; open-ended ranges are counted
separately and cannot inflate overlap or truth-coverage rates. Reports also show abstentions and per-dimension
unknown/unscored/blocking counts.

The gate requires complete held-out coverage of all three egress dimensions, known and comparable direction for every
held-out way, no direction contradiction, complete nonempty width scoring, zero definite false verified fits, and at
least one non-abstaining model-only result. Turn-space and sign rows cannot be omitted to improve the result, but their
unscored facts do not claim verification or independently fail the gate. A zero-error result is not an accuracy claim;
the gate is limited to physical clear width and OSM direction.

The report's `latency.evaluation_command` records measured CPU/wall time. A cold OSM graph load may fetch Overpass; that wait is included in `wall_seconds` and is not separately instrumented. `external_upstream.duration_seconds` is null with `not_separately_instrumented`; `background_jobs.duration_seconds` is null because this field-evaluation command schedules no jobs. Neither null means zero or live-service proof.

The backend reloads evidence on start and when an operator calls `POST /api/evidence/reload`.
