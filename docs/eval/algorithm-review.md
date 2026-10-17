# Ngõ Ngách core algorithm: independent read-only review

17 October 2026. Reviewed the working tree, including uncommitted changes. No engine, frontend, cache, flags, or vehicle-data file was edited by this audit. Python fixtures patch objects only inside their own process. All generated artifacts are under `docs/eval/`; the runnable harness is `pipelines/audit_algorithm.py`.

**Assessment:** the interval/graph architecture is understandable, but the current engine cannot yet defend a confident access-and-return guarantee. The largest implementation defect is Way Out: feasibility depends on one vehicle-weighted shortest-path tree and on how OSM ways happen to be split. Other priorities are preserving actual width bottlenecks, distinguishing missing flood/legal evidence from permission, and using one walking path for distance, geometry, and caps.

The cached sweep completed **300 destinations × 5 vehicles = 1,500 plans** without crashes. It found **84 plan monotonicity violations across 3,000 vehicle pairs**, affecting **19 destinations**; **26 door-feasibility reversals**, affecting six destinations; and **499 displayed walking geometries exceeding their intent's cap**. Width-fit classification itself had zero monotonicity failures. These are software invariants, not field-validation accuracy figures.

## Scope, reproducibility, and evidence

Read fully: `CONTEXT.md`, `docs/decision-log.md`, the requested eight engine modules, every file in `data/vehicles/`, `docs/eval/city-eval.md`, `agent2-report.md`, and `agent-exit-diagnosis.json`. Also inspected `config.py`, `parking_data.py`, relevant cached-area application/merge code in `live.py`, the cached flood/vehicle data, and existing tests. `data/vehicles/geometry.py` and `backend/app/geometry.py` are identical in this checkout.

No network, Gemini, Goong, Overpass, or planning-portal calls were made. The harness disables socket connections, replaces Overpass/portal entry points with exceptions, clears only the process-local Goong key, and calls `live.apply`, never `live.build`. Flags retain their cached production values: parcels and flood prior on, both footprint estimators off. Existing accepted cached evidence remains available; no inference API is invoked. A requests dependency warning appeared during imports; it did not interrupt execution.

```sh
# Run all minimal counterexamples, or print one named counterexample.
python3 pipelines/audit_algorithm.py --probes
python3 pipelines/audit_algorithm.py --case shortest-tree-exit
python3 pipelines/audit_algorithm.py --case width-bottleneck

# Property sweep; writes results incrementally every ten destinations.
python3 pipelines/audit_algorithm.py --sweep --n 300 --seed 3317

# Additional cached diagnostics, run after the sweep where applicable.
python3 pipelines/audit_algorithm.py --diagnose --profile --seams
python3 pipelines/audit_algorithm.py --explain --routes
```

Each **Probe** identifier below is a runnable failing input: use `--case IDENTIFIER`. The input construction, observed result, and expected behavior are in the harness and in [audit-probes.json](audit-probes.json). A probe reports the observed defect; it does not assert that a future fixed engine must retain it. Its `triggered` field is observational and is not a regression-test pass result.

Other artifacts:

- [audit-sweep.json](audit-sweep.json): all 300 coordinates, all 1,500 summaries, counts, examples, timings, source hashes.
- [audit-monotonic-explanations.json](audit-monotonic-explanations.json): evaluates the *same stop* for each vehicle, including rejection reasons and entry/exit geometry.
- [audit-220-diagnosis.json](audit-220-diagnosis.json): actual graph nodes, incident ways, widths, fits, reverse distances, and an alternative forward-path search.
- [audit-performance.json](audit-performance.json) and `audit-profile-{demo,campus,city}.txt`: cached latency and function profiles.
- [audit-seams.json](audit-seams.json): twelve adjacent-cell comparisons approximately 2.18 m apart.
- [audit-route-checks.json](audit-route-checks.json): focused inspection of returned entry paths on one destination per sampled cell.
- [audit-input-manifest.json](audit-input-manifest.json): end-of-run cache/data fingerprints. These are fingerprints, not frozen copies of mutable caches.

All eleven inspected engine/support source hashes matched between the beginning and end of the main sweep. Concrete line references below refer to that source revision, recorded in the JSON. Other agents can subsequently change these lines; compare hashes when reproducing.

Severity: **P1** affects access/return feasibility, a safety/legal assurance, or a core invariant; **P2** is material correctness or operational reliability; **P3** is a latent validation/provenance defect. This audit does not assert a production incident or a field-measured collision risk.

## 1. Width model and evidence fusion

### W1 — P1: a valid bottleneck is discarded as though it were a bad observation

**Location:** `backend/app/evidence.py:216`, `:218`, `:219`; `backend/app/plan.py:45`.

**Probe `width-bottleneck`:** five usable cuts `[1, 4, 4, 4, 4]` become Official **[4.0, 4.3] m**, and the Vios is labelled **fits**, although one valid cut is only 1 m. This faithfully implements D33's P20/P80 policy; the policy itself is not a defensible minimum-clearance guarantee. With five samples, even the maximum is retained as P80, so robustness is asymmetric at small sample sizes. At ten samples, two narrow cuts can be discarded.

A percentile describes the distribution of sampled locations; it is not uncertainty about the narrowest usable cross-section. `WidthRange.lo` is subsequently treated as a guaranteed lower bound throughout the whole OSM way. Sparse destination-prefix cuts can also certify the unmeasured remainder of a way, and the same way-level range is reused by other destinations. The live 220/9 range **5.49–5.79 m** comes from **one cut**, not a survey of its entire length.

**Proposed fix:** retain cut location, route span, validity, and coverage separately from measurement uncertainty. Filter geometry-invalid cuts first; preserve every credible bottleneck on the traversed span. Require confirmation or return unknown when the narrow cut is disputed. Do not remove it solely because its value is in a tail. Report quantiles as descriptive statistics, alongside a separate conservative bottleneck bound.

### W2 — P1: corners and intersections can produce geometrically inflated cuts

**Location:** `backend/app/parcels.py:89`, `:102`, `:111`, `:120`, `:146`.

**Probe `corner-cut`:** a genuine **4 m wide L-shaped corridor** cut exactly at its 90° bend yields a raw gap **5.66 m**, usable **4.66 m**. A straight section of that corridor would yield usable 3 m. `_cut_at` uses the bisector from points one metre before/after the cut; there is no bend/junction exclusion. Across intersections, the ray can measure the junction's open space or unrelated frontage rather than the alley corridor. The existing same-parcel, centre-in-parcel, minimum-side, and 15 m tests do not catch this case.

There is also no retained parcel identity/polygon, ray geometry, or local centreline heading in each saved cut. That prevents later review from distinguishing a mis-snap from a real constriction. Multipolygons are reduced to the largest component and holes are discarded at `:102`; the selected component need not contain the queried side point.

**Proposed fix:** reject or separately model cuts near sharp bends/junctions; measure perpendicular to a stable local segment away from the junction; retain the component containing each query and its holes; verify both hits are opposing frontage. Save sufficient geometry/provenance to audit acceptance. A robust aggregator cannot substitute for these checks.

### W3 — P1: lower-tier evidence can turn a higher-tier conflict into a confident answer

**Location:** `backend/app/evidence.py:89`, `:101`, `:107`; `backend/app/plan.py:45`, `:55`, `:362`.

**Probe `tier-review`:** Measured `[0.9, 1.1]` and Measured `[4.0, 4.2]` first become their union `[0.9, 4.2]`, with `review=True`. A Declared listing `[4.0, 4.1]` then narrows that union to **[4.0, 4.1], top_tier=Measured, review=True**. `fit_class` ignores review and says **fits**. The weak listing has effectively decided which conflicting measurement to believe, while the answer still carries a Measured badge.

For **non-conflicting** higher-tier ranges, the intersection logic does honor the stated rule: a lower tier cannot widen the range or replace it with a disjoint range. Disjoint lower bounds are put in `overruled`. The defect is conflict handling and the subsequent certification, not a general reversal of tier order. Even without a lower tier, two conflicting wide measurements can leave a wide union whose minimum still produces a confident fit.

**Proposed fix:** unresolved conflicts in a decisive tier must propagate to fit, route strictness, stop verification, and the verdict. Prevent lower tiers from resolving that conflict. Keep alternatives and their locations/dates instead of calling the union a physical guaranteed interval. Do not blanket-block every harmless lower-tier conflict; identify which tier actually determines the vehicle decision.

### W4 — P1: stale deep scans can override newer observations

**Location:** `backend/app/live.py:256`, `:262`, `:264`, `:309`; `backend/app/evidence.py:201`, `:208`, `:224`.

**Probe `stale-deep`:** an ordinary January `deep=True` scan with usable width 7 m replaces an October city-cache scan of 2 m. Recency comparison exists only for `sample_strategy=campus-full-5m`. `_save_area` also replaces records according to `deep`, not source revision or time. EvidenceStore accumulates all loaded area keys, including overlapping observations of the same way; older conflicting rows can survive alongside fresh ones and enter W3. Live parcel bounds do not populate `observed_on`, even if a cached row has `queried_at`.

Q11 explicitly chooses **no automatic ageing in v1**. Old evidence existing is therefore not itself a specification violation. Silently preferring an older partial scan over a fresh contradictory scan, or losing its date, is the defect.

**Proposed fix:** select/merge at cut/span level using timestamps, source revision, and coverage, not a deep boolean. Mark contradictions for review. Keep one canonical observation identity across overlapping cells, and retain superseded observations as history. Propagate `queried_at` into displayed evidence dates.

### W5 — P2: the 1 m rule is consistent for current live cuts, but not every ingestion path

**Location:** `backend/app/parcels.py:30`, `:133`; `backend/app/evidence.py:215`, `:325`; `data/official/parcel_gaps.csv:2`; `backend/app/vehicles.py:70`.

All **330 city-cache cuts** and **295 saved-area cuts** inspected obey `width_m = max(0.5, gap_m - 1.0)` within rounding. The area cuts overlap the city data; these are not 625 independent measurements. Evidence ingestion uses those already usable `samples` and does **not** subtract a second metre.

**Probe `legacy-margin`:** the official CSV describes raw parcel gaps, but `_load_csv(..., pad=None)` produces `[0.5, raw_gap]`, with no 1 m conversion or schema marker. Its 2.25 m gap stays an upper bound of 2.25 m rather than the 1.25 m usable figure implied by D33. The 0.5 m floor also means gap-minus-margin is no longer literal for raw gaps below 1.5 m; treat that as a sentinel/unknown policy rather than measured clearance.

**Probe `double-encroachment`:** a 4 m parcel gap becomes 3 m usable, then Fortuner's `fits_min` still reserves an additional 0.7 m motorbike row. D33 already names parked motorbikes inside the 1 m deduction. This is a **model-policy ambiguity**, tending to conservatism, not proof that a particular alley is physically passable. The margin plus fits threshold requires raw gap ≥4.405 m for Fortuner.

**Proposed fix:** version raw-gap versus usable-width data and centralize conversion. Make the fixed-encroachment/motorbike budgets explicit and non-overlapping, then calibrate against field clearances. Preserve unknown instead of inventing a positive physical floor.

## 2. Vehicle profiles and manoeuvres

The five selected profiles match the numeric values stored in `data/vehicles/vn_car_profiles.csv:2`, `:5`, `:23`, `:30`, and `:33`. No millimetre/metre conversion error was found for these current rows. Manufacturer publications were not re-fetched; the audit checks the cached CSV and its source/variant notes.

| Vehicle | Body / mirrors, m | Mirrors estimated? | Radius, m | fits_min / tight_min, m | Current door_min, m | 3-point width, m | Safe water, m |
|---|---|---|---|---|---|---|---|
| VF 3 | 1.679 / 1.748 | No | 4.50 | 3.048 / 1.948 | 2.579 | 5.85 | .175 |
| Vios | 1.730 / 1.980 | Yes | 5.10 | 3.280 / 2.180 | 2.630 | 7.10 | .133 |
| Fortuner | 1.855 / 2.105 | Yes | 5.80 | 3.405 / 2.305 | 2.755 | 7.84 | .350 |
| Carnival | 2.010 / 2.260 | Yes | 5.80 | 3.560 / 2.460 | 2.910 | 8.03 | .172 |
| Transit van | 2.068 / 2.474 | No | 6.70 | 3.774 / 2.674 | 2.968 | 9.09 | .150 |

The loader uses published mirror width when present, otherwise **body +0.25 m total**, not per side (`vehicles.py:118`). This is correctly labelled estimated. **26/34 models** need this estimate; five use a peer-radius fallback. `fits_min=mirror+1.3` and `tight_min=mirror+0.2` implement D15 as written.

### V1 — P2: door threshold differs from D15, and manoeuvre uncertainty is hidden

**Location:** `backend/app/vehicles.py:78`, `:96`, `:122`, `:136`, `:153`, `:183`, `:195`; `backend/app/geometry.py:5`, `:17`, `:108`.

- **Probe `vehicle-door`:** Vios `door_min` is **body +.3 +.6 =2.63 m**. D15 defines W including mirrors and asks for **2.88 m**. All street candidates are subjected to this threshold at `plan.py:375`, for both intents. Reconcile the intended door-opening geometry before changing the constant; code and decision log presently disagree.
- **Probe `confirmation-mirror`:** an “in” Vios confirmation sets an Observed minimum of **1.93 m = body+.20**, rather than the **1.98 m mirror width** specified by Q10 (`evidence.py:344`). This is conservative relative to an unfolded-mirror confirmation, but not the documented conversion. Capture folded-mirror context and use a consistent physical envelope.
- **Probe `vehicle-provenance`:** the CSV explicitly marks the new VF 8's 5.34 m turning radius **DERIVED**, but the profile says `turning_radius_estimated=False`. Class profiles unconditionally say false too. Missing ground clearance silently defaults to 150 mm. Fortuner's 700 mm wading value is an Australian diesel reference while the selected VN variant is petrol; that qualification is in the CSV note, but the output safe-water basis does not say “reference”. Xpander's source note says 5.5 m is the conservative choice from a published 5.2/5.5 ambiguity; the numeric row/engine use 5.2 (`vn_car_profiles.csv:27`).
- **Probe `turn-cache-version`:** `three_point.json` is keyed solely by model ID. Changing dimensions under that ID retains the old threshold. The fixture's Transit length change to 12 m still returns 9.09 m, even below its body-diagonal lower bound of 12.78 m. This demonstrates invalidation, not an assertion that any current Transit is 12 m long.
- **Probe `vehicle-water-units` — P3:** `_safe_water` compares a millimetre value with `gc` in metres at `vehicles.py:98`. An invalid 0.2 mm input with 0.15 m clearance activates the published-wading branch and returns 0.0001 m. Current selected rows do not exercise this latent unit bug.

The turn model uses body corners, estimated overhangs, instantaneous steering, flat ground, and a tyre-radius interpretation. It is a useful idealized model, not validated swept-path clearance. Mirrors are not explicitly represented; the 0.3 m body buffer covers some mirror projection but is not 0.3 m of mirror clearance. The K-turn simulator computes corridor length used, but `three_point_width` discards it and `_way_out` tests width only. A single broad cut or very short widening does not establish the approximately 10–13 m longitudinal space these simulations use. Unknown radius reference points and body-builder dimensions for cab-chassis trucks need visible uncertainty.

**Proposed fix:** make source/variant/derived/assumed fields explicit; use interval or conservative vehicle envelopes; hash specs, margins, and solver version in manoeuvre-cache keys. Return required width **and length** and check a spatial turning area. Resolve the door policy and unit comparison with targeted fixtures.

### R1 — P1: Way Out tests one shortest tree, not existence of a valid forward path

**Location:** `backend/app/plan.py:89`, `:203`, `:208`, `:462`, especially `:483`.

**Probe `shortest-tree-exit`:** a 200 m alley has a fitting 240 m forward loop; the stop is halfway along the alley. VF 3 gets **none** because the exit tree's preferred path from the forward endpoint returns over the candidate edge. Carnival classifies that edge tight, pays the 1.3 length penalty, selects the loop in its shortest tree, and gets **through**. No physical road changed. The smaller vehicle has every fitting way available to the larger one, yet loses its exit.

Rejecting `pred[b].edge == candidate_edge` does not prove there is no other path. Similarly, the algorithm chooses an arrival side before exit feasibility, so a different arrival approach can be feasible even when its selected one is not.

**Real cached examples:**

| Destination / intent | Smaller result | Wider result | Same-stop trace |
|---|---|---|---|
| 10.814506566, 106.704339755 / pickup | VF 3 and Vios: 149 m walk | Fortuner: 139 m walk | Smaller cars: entry side v, exit none; Fortuner: same side, through |
| 10.817012413, 106.707749969 / pickup | VF 3, Vios, Fortuner, Carnival: no stop | Transit: 48 m walk | Same candidate, entry side u; smaller exits none, Transit through |

**Proposed fix:** search for a feasible directed forward path excluding the backtracking move, not just inspect one predecessor tree. Evaluate relevant arrival orientations jointly with egress. Add heading/previous-edge state for legal turns and reversal transitions. Optimization cost must not change the existential feasibility answer when a vehicle's feasible network expands.

### R2 — P1: reversing and turning depend on OSM way segmentation

**Location:** `backend/app/plan.py:491`; `backend/app/osm.py:135`; `backend/app/plan.py:411`.

**Probe `way-split`:** at an unchanged physical T junction, parent `[2,4,5]` plus branch `[4,6]` counts as two incident **ways**. The stop is rejected for needing >60 m reverse. Split the parent into `[2,4]` and `[4,5]`: the identical junction now has three way IDs, and the same stop gets **reverse 20 m**. Conversely, three short fitting stubs are accepted as turning space without a manoeuvre-envelope test.

**Probe `junction-degree`:** the same physical degree-three junction returns `drive_degree=2`; the legal five-metre intersection check is then not applied. In addition, the distance calculation checks only the current tiny edge's endpoints, so a junction four metres away through a shape node on the same way can be missed.

**220/9 diagnosis:** the current range is **5.49–5.79 m**, below both VF 3's **5.85 m** and Fortuner's **7.84 m** three-point thresholds, so identical rejection of an *on-the-spot three-point turn* is understandable. The identical **224 m reverse** in `agent-exit-diagnosis.json` is not a physical minimum. The local diagnostic at 10.79924, 106.71239 finds:

- A fitting physical T junction at node **1497313006**, only **47.4 m** back, with three physical neighbors but two way IDs. Both vehicles fit the adjoining branch, with different fit classes.
- The first node meeting the engine's way-count/main-road heuristic is **366381336**, **226.3 m** back at this coordinate; the previous artifact used a slightly different setup and recorded 224 m.
- A directed node-path from the forward endpoint to a main road exists with the candidate edge excluded, **376.1 m** from that endpoint for both cars. This is topological evidence of a missed alternative; it does not validate the turns along that path.

The **60 m cutoff is implemented** (`plan.py:500`), and no offered sweep stop exceeds it. The problem is the incorrect reverse distance/turning-space premise feeding the cutoff. Raising the cutoff would mask the defect. Neither accepting the 47 m T junction nor claiming the loop is physically drivable is justified until turning geometry is checked.

**Proposed fix:** build split-invariant physical directed arms at junctions; distinguish a bend, a junction, and a validated turn-around area. Search bounded feasible reversing manoeuvres using vehicle geometry. Test that splitting/merging or adding a collinear shape node cannot change egress or intersection buffers.

### R3 — P1: reversing/turning can leave against a one-way road

**Location:** `backend/app/plan.py:478`, `:479`, `:487`; `backend/app/osm.py:101`, `:326`.

**Probe `oneway-exit`:** a one-way u→v dead-end alley, stop 20 m from u, returns **reverse to u** at 4 m width and **turn_here then drive to u** at 9 m width. Both travel against the one-way restriction. The forward-through branch observes direction, but these two branches do not. A legal node path from u to a main road does not legalize the missing stop→u partial edge.

**Proposed fix:** encode permitted direction for the full manoeuvre, including the partial stop edge and any reversal; do not infer permission to reverse against traffic from the existence of a reverse-search predecessor. Keep backing direction distinct from driving direction and define the legal policy explicitly.

### R4 — P1: corner turning is not a route transition constraint

**Location:** `backend/app/plan.py:59`, `:61`, `:65`; `backend/app/vehicles.py:184`.

**Probe `junction-turn`:** two 4 m alleys meeting at 90° are both **fits** for Carnival, while the engine's own one-arc model needs **4.59 m** for the receiving alley. Equal-width parents are skipped. Interior shape-node bends are not considered. At a checked wider-parent mouth, failure only downgrades fits to tight, and tight remains routable; there is no proof that a multi-point manoeuvre is possible in the actual junction polygon.

D25 intentionally relaxed turn-in failure, and D16 already disclosed interior bends as a gap. Those decisions explain the implementation; they do not support an unconditional physically feasible route claim.

**Proposed fix:** attach vehicle-dependent feasibility/uncertainty to directed junction transitions, using angle and local free-space geometry. Evaluate a permitted multi-point turn if the one-arc check fails; otherwise mark the transition unknown or unavailable. Do not use a way-wide width class as a substitute.

## 3. Routing, restrictions, and cache boundaries

For **intermediate driving edges**, Dijkstra correctly rejects `fit in {no, blocked}` and flood blocked; its strict pass also rejects unknown fit/risky flood (`plan.py:81`, `:203`). Unknown candidates are intentionally retained in the permissive pass and labelled. Normal entry direction for `oneway=yes/1/-1` is respected by adjacency and the partial-edge endpoint selection. The principal errors are manoeuvre transitions, tag coverage, source/connector assumptions, and the exit exceptions described above.

A focused rerun of one destination per sampled cell, all five vehicles (**150 plans**), inspected **323 returned entry routes, 1,521 full steps, and 315 partial steps**. It found zero no/blocked-fit steps and zero wrong-direction full steps. No unmapped lot link occurred in that sample, so the lot counterexample remains a separate synthetic finding. This check does not validate exit manoeuvres or the external approach.

### R5 — P1: access and bridge restrictions are incomplete

**Location:** `backend/app/osm.py:85`, `:97`, `:101`, `:172`, `:289`; `backend/app/parking_data.py:38`.

**Probes `access-tags`, `gate`, `private-walk`:**

- `access=private/no` on a way is excluded, unless explicitly overridden by `motorcar=yes/destination`; plain private ways are **not** generally admitted.
- `motorcar=no`, `motor_vehicle=no`, and the Vietnamese/English motorbike-only name regex reject cars. However, `motor_vehicle=no` still wins over more specific `motorcar=yes`, contrary to normal tag specificity. `vehicle=no` is ignored.
- A private gate **node** on an otherwise residential way leaves its edges drivable. Barrier tags are stored but never used. The Overpass query also has no explicit barrier-node selector; recursively fetched nodes use skeleton output.
- An implicit `junction=roundabout` without an explicit oneway tag is treated as two-way. Restriction relations are neither fetched nor enforced. Conditional vehicle/time restrictions are unsupported.
- A bridge tagged **maxweight=1** is drivable for every profile, including Transit. Profiles contain no mass, axle-load, or height field; `maxweight`, `maxaxleload`, `maxheight`, and vehicle-specific dimensional limits are unused. A width evidence upper bound is not enforcement of a legal `maxwidth` limit, particularly when stronger physical-width evidence overrules it.
- `walkable` ignores `access=private/no` and gate restrictions; a road excluded for car access can still be used for an asserted foot route. Some lots omit the `motor_vehicle=no` check too.

**Proposed fix:** implement mode-specific OSM access precedence, barriers, implicit directions, and turn restrictions. Separate legal restrictions from physical width evidence so stronger measurements cannot erase a sign. Add vehicle envelope/weight fields with explicit unknown handling; never certify a known restrictive bridge when vehicle compliance is unknown. Honor corresponding restrictions in the pedestrian graph.

### R6 — P1 for lots; P2 for street diagnostic consistency: partial connectors are unvalidated

**Location:** `backend/app/plan.py:212`, `:219`, `:234`, `:437`, `:450`, `:467`.

**Probe `lot-connector`:** a lot 70 m from a main-road node, with no mapped access road, gets `strict=True` and a straight 70 m entry. The same geometry could cross a canal, wall, restricted gate, or unfit driveway. Exit unconditionally assumes room to turn inside any lot; flood samples a neighboring way instead of the entrance/lot surface. A car-park centroid is not necessarily its entrance, and Transit/van dimensions are not checked inside it.

**Probe `partial-route`:** `_route_in` can return a strict path into the final partial edge even when that edge was excluded by the search; it checks endpoint reachability, not the edge's own fit/flood status. For **street stops**, `_evaluate` separately rejects no/blocked fit and checks stay flooding including arrival, so this alone did **not** establish an offered unfit street stop. It does make the route object on rejected candidates misleading. Lots lack the corresponding connector checks.

Main-road nodes are all zero-cost sources (`plan.py:194`), even when their containing road is disconnected or blocked. This is a local handoff model, not proof of a drivable origin-to-stop route. The external Goong approach is not evaluated by this offline audit.

**Proposed fix:** snap to mapped entrances and split actual drivable edges; check every partial edge with the same rules as a full edge. Keep off-network connectors unverified until surveyed/mapped. Require evidence for lot access and internal turnaround; retain source-road feasibility at handoff.

### C1 — P1: graph refresh leaves dependent caches stale

**Location:** `backend/app/osm.py:277`; `backend/app/plan.py:27`, `:30`; `backend/app/parking_data.py:64`.

**Probe `graph-revision-cache`:** replace way 10 with way 20 under the same `g.source`. `build_graph` can refresh from a disk stamp, but `plan.area` returns widths still keyed only by way 10. The next `compute_fit` can raise KeyError, or unchanged IDs can retain stale widths/flood attachments. Width/flood/paid-street/near-way caches use the source string rather than graph revision. `_WR` also retains all old evidence versions without eviction.

**Proposed fix:** include an immutable graph content/version token in every derived-cache key, and evict old revisions. Use bounded LRU caches; do not just clear `_GRAPHS` while leaving its dependents intact.

### Cell-edge assessment: overlap exists; no universal seam defect demonstrated

**Location:** `backend/app/osm.py:221`, `:240`, `:246`; `backend/app/config.py:75`.

A 0.004° key spans approximately **438×445 m** at HCMC. On-demand graph fetches are centred at the **first requested point**, not the rounded cell centre. Another request at the opposite corner can be about **624 m** away, leaving only about **576 m** of the nominal 1.2 km radius beyond it in that direction. Crawler caches inspected here record a centre and roughly 1,235 m coverage; those are better bounded around the cell centre. Complete way-node expansion can also extend beyond the nominal radius.

The graph is **not clipped at the 0.004° cell edge**. Neighboring queries overlap, so merely crossing a cell boundary does not disconnect the network. In twelve cached east/west boundary pairs, all nearest door-way IDs and verdict codes were stable; best walks changed by at most three reported metres. This is useful negative evidence, not proof of complete connectivity. The code neither merges neighboring cell graphs nor expands a search that requires a long detour/turning space beyond the cached area. A clipped loop or missing main-road connection can therefore become a false “no Way Out”; source seeding can produce the opposite kind of assurance.

**Proposed fix:** normalize fetch centres or persist a coverage envelope; require the destination's needed halo to be covered. Expand/stitch cached neighbors for searches reaching the boundary, deduplicate by OSM IDs, and distinguish incomplete coverage from an established dead end. Re-run boundary tests with a required detour outside the initial halo.

## 4. Flood, tide, rain, and dwell

D25 is implemented in timing structure: entry at arrival, stop at 15-minute samples throughout the stay, exit at departure. This refines the earlier whole-window requirement and is not itself a missed specification. Official October tide extrema are used; outside the published interval `tide_level` correctly returns None. The defect is what the flood engine does with that missing value.

### F1 — P1: missing tide/observations becomes “passable” / “Không ngập”

**Location:** `backend/app/flood.py:141`, `:236`, `:247`, `:274`, `:282`; `backend/app/plan.py:518`.

**Probe `missing-tide`:** a historically tide-flooded street at a 2027 timestamp, outside forecast coverage, returns `tide=None`, `depth=None`, **passable**. The stop can then be verified and display “Không ngập”. A missing profile has the same positive default. This contradicts the product's “no record ≠ no risk” treatment of unknown checks.

**Proposed fix:** distinguish observed/modelled dry, predicted passable, and insufficient hydrological coverage. Propagate missing forecast or absent susceptibility evidence to Unverified. Preserve the official forecast's validity interval in each answer. Do not silently revive an invented harmonic forecast.

### F2 — P1: stay sampling misses event peaks; rain is instantaneous and order-dependent

**Location:** `backend/app/plan.py:182`, `:393`; `backend/app/flood.py:190`, `:236`, `:294`.

- **Probe `rain-pulse`:** 60 mm/h from minute +1 through +14 of a 15-minute stay on a recorded rain-flood street is **blocked** at +7, but the engine's `[arrival, +15]` samples return **passable**. Water also instantly disappears one minute after the scenario ends; no accumulation or recession is modeled.
- **Probe `dwell-extrema`:** a tide peak at +7 minutes gives **blocked** while both 15-minute endpoints give **passable**. Include actual extrema and threshold crossings rather than relying exclusively on an arrival-anchored grid. The synthetic extremum tests sampling, not the current bulletin's forecast skill.
- **Probe `rain-order`:** overlapping intervals of 10 and 60 mm/h return either 10 or 60 solely according to list order. The parser takes the first matching interval.

**Probe `worst-depth` — P2:** `worst_over` retains **1–2 cm** when a later sample reaches **10–12 cm**, because both are passable for the test vehicle. Displayed “worst” depth/time can therefore be misleading even when the pass/risk/block class is unchanged. `_flood_timing` also probes a generic tide street, not the actual exit bottleneck; its leave-before result is rechecked, but stay-until-after is not equivalently validated. That timing design is a source-level limitation, not a new field-validated counterexample.

**Proposed fix:** build event-aware dwell evaluation from scenario boundaries, tide extrema, and threshold crossings. Validate/reconcile overlapping rain intervals. Add an explicit conservative accumulation/recession model or label instantaneous scenario outputs as such. Compute timing suggestions from the actual affected route and validate both alternatives through the full planner.

### F3 — P1: moving-water rule differs from D14; absence of history gets an unsupported 10 cm ceiling

**Location:** `backend/app/flood.py:257`, `:270`, `:285`, `:289`; `docs/decision-log.md`, D14.

**Probe `moving-water`:** rain-driven `[.10, .30] m` water for a .40 m-safe vehicle is **risky**, hence retained as Unverified. D14 says a rain-flood range **reaching ≥.30 m blocks every car**. The implementation blocks only if the lower bound reaches .30; the upper-bound test merely makes it risky.

**Probe `rain-no-history`:** 100 mm/h with no historical flood profile gives `[0,.10] m`, and VF 3 is **passable**. The data does not establish that every undocumented street is bounded by 10 cm under this rainfall. The claimed “learned” prior is counts, historical depth quantiles, fixed tide alarm bands, and spatial/name borrowing; no fitted conditional model or held-out prediction error is present in this engine. Rain+tide adds a fixed .10 m, and any existing `drivers` entry, including a live report rather than tide, triggers that increment.

**Proposed fix:** implement the chosen .30 m hard policy consistently or explicitly revise D14 with supporting evidence. Treat unknown street response as unknown; calibrate depth intervals and recession against independent events. Publish coverage/calibration limits rather than portraying fixed heuristic bands as validated street-level forecasts. The current tide transcription tests are valuable but do not validate street depths.

## 5. Stop legality and wording

### L1 — P1: absence of a known prohibition is displayed as affirmative permission

**Location:** `backend/app/legality.py:87`, `:103`, `:107`, `:113`; `backend/app/plan.py:523`.

**Probe `no-rule-permitted`:** an 8 m tertiary street with no applicable recorded rule returns **Permitted**, a rule saying “Không có quy định cấm ... được biết”, and the badge **“Được phép”**. Main-road sign uncertainty is added only to Park on primary/secondary, so tertiary/residential roads and pickups can receive this assurance with equally missing signs/curb data. A generic parking lot is also always Permitted even for customer-only access, with no entitlement or operating-hours check.

The broad `LAW` string correctly identifies Law 36/2024/QH15, Article 18(4) as the cited family for many cached stopping prohibitions. It does **not** establish positive authorization at this place and time. This audit had only the cached legal research summary (`docs/research/02-parking.md:40`), not a complete locally archived authoritative statute/sign standard; no fresh legal-source verification was possible under the no-network instruction. Exact point-level citations and sign rules therefore remain unverified. A claim of fully certified statutory correctness would exceed the available evidence.

The engine covers some Art. 18 cases (single lane, intersections, crossings, bus stops, bridge) but lacks curb side, left side of one-way roads, organization gates, blind curves/crests, opposing parked cars, rail safety zones, hydrants/manholes, and obstruction of signs. A fixed **5.5 m usable-width threshold is a lane-count proxy**, not an observation of the legally relevant roadway/lane configuration. **Probe `legal-road-proxies`:** either `highway=trunk` or `covered=yes` creates a Prohibited legal assertion with the blanket Article 18(4) citation. The former is an OSM functional class, not proof that a road is legally an expressway; the latter is not proof of a road tunnel.

**Proposed fix:** represent legality as restriction knowledge plus coverage/authorization. Use “Chưa thấy quy định cấm trong dữ liệu hiện có” and Unverified when coverage is incomplete. Reserve “Được phép” for sufficiently supported authorization/check coverage. Keep Restricted pickup's prohibition explicit, as Q7 requires. Cite the exact applicable legal point and source text; distinguish geometric proxies from established legal facts.

### L2 — P1: junction/sign scope and the parked interval are modeled incorrectly

**Location:** `backend/app/plan.py:410`, `:413`; `backend/app/legality.py:31`, `:38`, `:45`, `:65`.

- **Probe `junction-degree`:** a normal unsplit T intersection has way-count degree two; the five-metre exclusion is skipped. Even when detected, distance is to the centreline graph node rather than the **edge of the intersecting roadway**, as the displayed rule says. Shape nodes can also hide a nearby junction.
- **Probe `junction-shape-node`:** a stop four metres from a detected three-way junction, with an intervening shape node at three metres, returns **Permitted**. The candidate's immediate endpoints are not junctions; the check does not look through the shape node.
- **Probe `sign-extent`:** P.130 at x=0 vanishes for a stop 60 m down the same uninterrupted road because signs are applied only within a 40 m circle. There is no side, facing, direction, supplementary plate, or until-next-intersection model.
- **Probe `sign-unrelated`:** an unassociated P.130 20 m away is applied to the candidate road because `g.node_ways.get(nid, {w.id})` defaults to admitting every nearby way. It can affect the opposite carriageway or a parallel street.
- **Probe `legality-window`:** Park at 23:00 on October 17 through 01:00 October 18 beside P.131c is allowed at arrival although the departure-day check is prohibited. `_evaluate` passes only arrival to legality, not the dwell interval. Time-limited rules/lot hours have the same structural gap.

**Proposed fix:** use physical junction polygons and distance along connected street geometry; model curb side and directed sign scope; require an association for unattached signs. Evaluate all rule transitions during Park's dwell window, and use the appropriate short stopping interval for pickup. The exact sign-standard timing details should be checked against the archived authoritative text before hard-coding them.

### L3 — P2: unrelated parking-tag values are treated as bans

**Location:** `backend/app/legality.py:52`.

**Probe `parking-tag-fee`:** `parking:both:fee=no` produces **Prohibited/no parking**, although this value means no fee. The parser scans every `parking:*` value and interprets any `no` as a parking ban, regardless of key. Side-specific restrictions are also flattened onto a centreline point.

**Proposed fix:** parse supported restriction keys semantically; keep fee, access, markings, conditionals, and side separate. Add free-parking and mixed-side fixtures.

## 6. Stop ranking, walking, and empty graphs

Ranking matches the chosen D25 structure: verified tier 0; verified tight-exit tier 1; Restricted or otherwise Unverified tier 2; then ascending walk distance (`plan.py:254`, `:421`). Fit being tight does not itself add a ranking penalty. The selection then enforces one stop per way and 45 m geographic separation, so the three shortest individually passing candidates are not necessarily all shown. These choices are deliberate. Ranking cannot repair incorrect hard-check inputs.

### P1 — P1: walking distance, geometry, flood exposure, and caps use different paths

**Location:** `backend/app/plan.py:211`, `:223`, `:229`, `:235`, `:527`, `:534`, `:538`; `backend/app/osm.py:97`, `:331`.

**Probe `walk-edge`:** destination at offset 90 m and stop at 80 m on the same 100 m edge have a true connected sub-edge path of **10 m**. Endpoint-only distance gives **30 m**. `_walk_geometry` chooses u without considering cost and draws approximately **170 m**. At other stops it can pick a different predecessor from the numeric minimum. Lot geometry re-snaps again using membership in `wpred`, while numeric distance used `wdist`; roots need not be in `wpred`. `_walk_wade` chooses yet another start (always edge.u for a street) and omits final partial-edge flood exposure.

Footways, paths, steps, and pedestrian ways are included in `walk_adj`, and motorway/trunk are excluded. But the graph also walks both directions along ordinary vehicle centreline edges. It does not model which sidewalk/curb the stop occupies, legal/safe crossings of a divided main road, a median barrier, or a lot/door entrance connector. Non-connected geometric road crossings are not automatically joined, which is good; a shared vehicle junction still permits a pedestrian centreline traversal without crossing evidence. `foot=no` excludes a full walking edge, but street-candidate tail distances are added on drivable edges without rechecking their foot permission.

**Proposed fix:** insert virtual stop/destination/entrance nodes on the relevant edges, including direct same-edge paths. Store the exact chosen pedestrian edge sequence and endpoint once; derive metres, geometry, flood exposure, and cap from it. Check partial-edge foot access and qualify unverified straight connectors. Add crossing/sidewalk/barrier support before asserting these are verified pedestrian routes. Round only after the hard cap is checked.

### P2 — P2: a graph with no walkable edge crashes

**Location:** `backend/app/plan.py:212`, `:213`.

**Probe `no-walk-crash`:** a cached motorway-only graph raises **AttributeError: 'NoneType' object has no attribute 'u'**. Empty/isolated graphs have the same unchecked projection structure. There were zero crashes in the sampled populated cached cells; that does not cover this valid sparse-coverage input.

**Proposed fix:** guard missing drive/walk projections and missing main-road sources; return insufficient coverage with no fabricated path. Distinguish missing graph coverage from a verified “no suitable stop”.

### P3 — P2: penalty-weighted route costs are reported as physical metres

**Location:** `backend/app/plan.py:89`, `:204`, `:444`, `:451`, `:625`.

**Probe `weighted-meters`:** 100 m of tight approach plus 10 m of final edge is reported as **140 m**, rather than approximately **110 m**. `_cost` is useful for route selection, but its Dijkstra distance is serialized as metres and then used in trip distance/time. The final partial edge is not weighted consistently either.

**Proposed fix:** keep optimization cost and physical length separately, or reconstruct physical metres from the selected edge sequence. Do not use a preference penalty as driving distance or elapsed time.

## 7. Property sweep and performance

### Sweep method and counts

Seed **3317**, **30 cached routing cells**, ten random destinations per cell. Ordinary cells use uniform offsets within ±.00199° of their centres; the larger demo key uses a uniform inner rectangle (10.792–10.810 N, 106.696–106.722 E). Selection includes the three saved live-area keys and available cadastral cells, then seeded urban cached cells. Points remain within each actual routing key, not substituted from other areas. Park/Pickup alternates by sample index: **150 destinations each**; each cell consequently has one intent in this sweep. Every destination is planned for VF 3, Vios, Fortuner, Carnival, and Ford Transit. Arrival **2026-10-17 12:00 +07:00**, dwell 120/15 minutes, no simulated rain. The current tide is below flood alarm activation, so differing safe-water limits do not explain these monotonic failures. A general narrower-is-better assertion during flooding would be invalid: Vios's .133 m safe limit is lower than Fortuner's .350 m.

For the selected profiles in this dry test, body/mirror width, length, and turning requirements increase in the stated order. All **ten smaller/wider pairs** per destination are checked. “Worse plan” means a worse first-stop ranking tuple `(tier, reported walk metres)`, or no stop when the wider vehicle has one. Door monotonicity is checked separately before ranking. Fit comparisons include repeated ways across sampled destinations and should not be described as four million independent road measurements.

| Invariant / observation | Count |
|---|---:|
| Completed plans / requested | 1,500 / 1,500 |
| Exceptions on sampled destinations | 0 |
| Smaller vehicle has a worse best-stop ranking | **84 / 3,000 pairs**, 19 destinations |
| Smaller has no stop while wider has one | **8 pair instances** |
| Wider door passes while smaller door fails | **26 pair instances**, six destinations |
| Smaller has a worse way fit class | **0 / 4,005,700 repeated way comparisons** |
| Returned stop has `ok=False`, fit no/blocked, or exit none | **0 / 3,288 stops** |
| Returned stop reverses >60 m | **0 / 3,288 stops** |
| Verdict contradicts stop availability/verified-door state | **0 / 1,500 plans** |
| Reported walk exceeds 400 m Park /150 m Pickup cap | **0 / 3,288 stops** |
| Drawn walk length differs from reported by >5 m | **2,244 / 3,288 stops** |
| Drawn walk length exceeds cap by >1 m | **499 / 3,288 stops** |

The geometry violations show inconsistent displayed paths/caps, not field proof that every actual shortest legal walk exceeds its cap. The synthetic same-edge example establishes the implementation cause. Example at **10.803923978, 106.711828967**, Park, VF 3: a stop reports **63 m** but draws **224.0 m**. Other geometries are shorter than the reported number, so taking the longer of the two numbers is not a principled repair.

Verdict counts: **659 nearby, 531 unverified, 247 none, 63 door**. These are descriptive coverage outcomes, not ground-truth labels. The sweep is deterministic property exploration over cached cells, not a statistically representative citywide accuracy evaluation. It does not establish manufacturer manoeuvre accuracy, real encroachments, legality completeness, real flood depths, or the external origin approach.

### Cached latency

Main sweep wall time: **170.4 s**, including cache application, JSON output, and extra invariant work. Per-vehicle plan-only times:

| Vehicle | Median | P95 | Maximum |
|---|---:|---:|---:|
| VF 3 | 68 ms | 377 ms | 650 ms |
| Vios | 61 ms | 341 ms | 580 ms |
| Fortuner | 59 ms | 339 ms | 455 ms |
| Carnival | 59 ms | 368 ms | 594 ms |
| Transit | 57 ms | 330 ms | 550 ms |

`live.apply` cached application median was .27 ms, P95 164 ms, maximum 269 ms; first application to a new cell can build a graph and reload the evidence store. API/network/background-build latency is excluded.

Five additional Vios/Park runs per selected location:

| Cached graph | Ways / edges | Candidates | Plan median | Slowest of five |
|---|---:|---:|---:|---:|
| Bình Thạnh demo | 4,968 /20,561 | 740 | 427 ms | 685 ms |
| 10.840,106.808 campus | 605 /3,186 | 161 | 54 ms | 85 ms |
| 10.744,106.760 sparse cell | 73 /411 | 0 | 2.7 ms | 6.2 ms |

The sparse cell's speed partly reflects no stop candidates, not a universally fast successful plan. Profiling adds overhead: the representative demo cProfile call takes **1.496 s**, versus about .427 s unprofiled. Its inclusive breakdown is:

| Work | Profiled cumulative time | Interpretation |
|---|---:|---|
| Candidate evaluation | .834 s | Includes the rows below; do not sum inclusive times |
| Street legality | .702 s | About 47% of total; two full node-tag scans per candidate |
| Six Dijkstra searches | .217 s | Four vehicle searches plus walk and standard route |
| Flood interval evaluations | .166 s | Repeated way/time calculations |
| Two projections | .093 s | Full edge scans |
| Way Out | .025 s | Predecessor/path work per candidate |
| Layer output | .035 s | All nearby ways |

**O(n²)-type hotspots:** `legality_on_street` and `_sign_rules` scan all tagged nodes for every candidate (`legality.py:33`, `:67`), giving **O(candidates × tagged nodes)**. With both growing with the area, this is quadratic. The demo profile performs **346,175 haversine calls** and **12,483 live-report existence checks**. `flood_profiles` is **O(ways × nearby flood records × sampled way points)** (`flood.py:84`), and flood-at-stay recomputes the same way/time result per candidate. Nearest-node scans are **O(lots × nodes)**; repeated predecessor reconstruction is **O(candidates × path length)**. Core Dijkstra is the expected approximately O(E log V), not an all-pairs road search.

**Probe `deep-budget` — P2:** `parcels.measure_area` subtracts only the number of **successful cuts** from its budget (`parcels.py:207`, `:215`, `:220`). Two long ways with one valid cut each schedule **60 +59 =119 attempted cuts**, despite a stated 60-cut/300 m budget. Failed cuts are absent from saved coverage, so missingness and latency cannot be interpreted reliably. City deep-cache reuse can also bypass the destination-specific coverage check.

**Proposed fixes:** index legal features spatially and cache way-level rules; precompute tide/rain/live-report state once per request; memoize per-way dwell and flood results; retain predecessor/metric reuse; bound derived caches. Count **attempted locations** and total path span against parcel budgets, not successes, and save failed attempts/reasons. Keep cold cache-building and warm planning metrics separate. No portal performance was measured during this audit.

## Ranked implementation list: top 10

1. **P1 — Replace shortest-tree Way Out with feasible manoeuvre/path search (R1–R3).** Evaluate arrival/exit orientation jointly; search alternatives; enforce direction throughout reversing and turning. **Acceptance:** `shortest-tree-exit` gives both vehicles a forward exit; `oneway-exit` offers neither illegal return; `way-split` is invariant; the 300-destination dry sweep has zero best-plan and door-feasibility monotonicity failures. Re-explain 220/9 with actual junction/manoeuvre evidence; do not just increase 60 m.

2. **P1 — Make width a conservative spatial bottleneck with review propagation (W1–W3).** Separate sample quantiles, usable-width uncertainty, and route coverage; validate corner/intersection cuts. **Acceptance:** `[1,4,4,4,4]` never certifies a car across the 1 m location; the 4 m L corridor does not become 5.66 m raw width; `tier-review` cannot become a verified Measured fit via a listing; a one-cut prefix cannot certify an unobserved whole way.

3. **P1 — Add directed junction/turn-area feasibility (R2,R4).** Use physical arms, bend angle, turning width and longitudinal clearance, with an explicit unknown state for unsupported multi-point turns. **Acceptance:** the 4 m/90° Carnival example is not confidently routable without additional manoeuvre evidence; way splits/shape-node changes preserve answers; turning in a short widening fails when the required corridor length is absent.

4. **P1 — Make flood missingness and hard policies explicit (F1,F3).** Distinguish unknown from predicted dry and apply D14 consistently. **Acceptance:** out-of-forecast tide-prone streets and 100 mm/h/no-history streets are Unverified; rain-driven ranges reaching .30 m are blocked under the existing decision; no “Không ngập” badge is generated solely from missing data.

5. **P1 — Evaluate dwell events and actual flood bottlenecks (F2).** Include rain boundaries, tide extrema, recession assumptions, and rule-independent interval validation; validate both timing alternatives against actual routes. **Acceptance:** rain-pulse and +7-minute tide-peak fixtures are detected; overlapping rain scenario order cannot change the result; the displayed worst depth/time matches the evaluated maximum; both leave-before and stay-until suggestions pass full-engine rechecks.

6. **P1 — Use one pedestrian path for every walk field/check (P1).** Introduce virtual edge positions, consistent entrance snaps, foot access, and qualified crossings/connectors. **Acceptance:** the same-edge example reports and draws approximately 10 m; zero >5 m geometry/metric mismatches and zero over-cap returned paths in the sweep; wading is computed over that identical path, including partial edges; private/foot=no tails are not silently certified.

7. **P1 — Correct legality knowledge, geometry, sign scope and time (L1–L3).** Separate unknown from affirmative permission; use physical junction/curb geometry and dwell validity. **Acceptance:** `no-rule-permitted` is Unverified with accurate wording; the T-junction five-metre buffer is split-invariant and measured from the road edge; same-road/unrelated-sign fixtures have correct scope; the midnight P.131 fixture is checked across the stay; `parking:both:fee=no` is not a ban. Attach locally archived exact legal clauses to each rule before claiming legal completeness.

8. **P1 — Enforce complete access/vehicle restrictions and real lot connectors (R5,R6).** Add mode-specific precedence, gate nodes, roundabouts/turn relations, width/weight/height restrictions and entrance paths. **Acceptance:** private gate and vehicle=no fixtures reject unauthorized entry; motorcar-specific overrides are handled deliberately; a 1 t bridge is not certified for Transit; the 70 m unmapped lot link is Unverified; all full and partial route edges pass the same checks. Keep legal limits independent of width-tier fusion.

9. **P1/P2 — Version evidence, graph, and vehicle-derived caches (W4,W5,C1,V1).** Canonicalize observations across cells; reconcile freshness and coverage; include graph/spec/solver revisions in cache keys; fix door-policy/unit/provenance discrepancies. **Acceptance:** stale-deep preserves/reconciles the fresh contradiction; graph revision contains way 20 and cannot KeyError; changed dimensions recompute three-point limits; all parcel paths declare raw/usable schema and conversion; derived/foreign-variant assumptions remain visible. Bound cache growth and verify coverage/neighbor expansion at cell boundaries.

10. **P2 — Harden sparse inputs and remove avoidable repeated work (P2,P3,performance).** Guard no-edge/no-source cases, separate cost/metres, index legality features, memoize hydrological evaluation, and budget attempted parcel cuts. **Acceptance:** motorway-only/empty graphs return coverage uncertainty without crashing; weighted-meters reports physical length; deep-budget never schedules >60 attempted cuts or >300 m under that policy; cached representative plans preserve decisions while reducing full legal-feature scans from per candidate to spatial queries. Record cold/warm latency and maintain zero original-sweep crashes.

The remaining requirement for a defensible physical engine is independent field validation: tape-measured clear bottlenecks, manoeuvre envelopes, entrance/curb evidence, and flood outcomes. Passing these software acceptance criteria will remove demonstrated logic failures; it will not by itself validate the 1 m margin, a manufacturer's radius reference, a street's water-depth interval, or a legal permission claim.
