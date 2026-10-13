# Decision log

Running record of decisions from the grilling session. Glossary lives in `../CONTEXT.md`.

## Q1: Personas (2026-09-28)

- **Primary:** Private Driver (parks, then walks) and Ride-hailing Driver (brief pickup/drop-off, stays with the car). Both are cars, but they stop differently.
- **Secondary:** Delivery Driver, sharing the large-vehicle size group.
- **Deferred:** Emergency Vehicle. The UI shows it as a disabled "coming soon" option so the team remembers it.

## Q2: Answer shape (2026-09-28)

Chosen: **B + C + D** (not A, a bare yes/no verdict).

- **B, Arrival Plan:** up to 3 ranked Stop Points, each carrying get-in, get-back-out, flood-now, Walk Leg and evidence. A one-line Verdict stays only as the plan's headline.
- **C, alley-fit layer:** alleys coloured by fit for the chosen vehicle (fits / tight / doesn't fit / unknown), plus a flood overlay.
- **D, fit-aware routing:** the route to each Stop Point avoids alleys the vehicle doesn't fit. Open question for the architecture step: can Goong's Direction API be told to avoid specific alleys, or do we route the last few hundred metres on our own alley graph?

## Q3: Vehicle input (2026-09-28)

- **Quick path:** pick a Size Class.
- **Precise path:** pick a Vehicle Model from a catalogue of popular Vietnamese models with published specs; answers get more precise.
- **VETC link (added):** the vehicle can come from the driver's VETC account. Research found no public API, partner SDK or "Login with VETC" (see `research/04-sponsor-platforms.md`), so the demo uses a clearly labelled mock consent flow: Đăng nhập VETC → consent screen → "30A-***.12 · Fortuner · 7 chỗ" → our spec table fills the Vehicle Profile → the driver confirms. VETC holds plate, vehicle type, seats and payload, not make/model/dimensions, so the model mapping is ours.
- **Not in scope:** typing dimensions by hand.

## Q4: Size Class assumptions (2026-09-28)

- **Worst case per limit:** a Size Class takes the widest width, largest turning radius and lowest wading depth among its common models. We never say "fits" when the driver's real car might not.
- **Nudge:** when an exact Vehicle Model could change the answer, prompt the driver to pick it.

## Q5: Getting back out (2026-09-28)

- **Three ways out:** drive through, turn around, or reverse. All are computed on the vehicle's Fit Network, not the raw map.
- **Reverse Limit:** starts at ~30 m (placeholder, to tune). Beyond it the Stop Point is downgraded to "tight exit" but still shown.
- **Later tuning allowed:** separate limits per Stop Intent, or relaxed for confident drivers, without changing the structure.

## Q6: Ranking the Arrival Plan (2026-09-28)

- **Filter, then rank.** Hard Checks remove candidates: the route in stays on the Fit Network, a Way Out exists, flooding stays within the wading limit, Stop Legality allows the Stop Intent, and the Walk Leg is under its cap. Survivors are ranked by walk time.
- **Confidence is a badge.** It never changes the rank.
- **Unknown is not filtered out.** Unverified candidates rank after every verified one, labelled "unverified" and drawn grey. This applies Trí's "no record ≠ no risk" rule to access.
- **Walk caps (placeholders):** ~400 m for Park, where the driver walks; ~150 m for Pickup/Drop-off, where the passenger walks.
- **Stop Legality is its own check**, combining traffic law (Law 36/2024 Art. 18), road signs (P.130/P.131a/b/c, including odd/even days), and local ordinances such as licensed parking streets and peak-hour bans. AI is expected to help read signs and ordinances; designed in the AI step.

## Q7: Law vs practice (2026-09-28)

- **Park is strict:** only Permitted places qualify.
- **Pickup/Drop-off is graded:** a place the law forbids only because the roadway fits one lane (most hẻm) is kept as Restricted and ranked after every Permitted option.
- **Prohibited is always removed:** signed no-stopping (P.130), crosswalks, within 5 m of an intersection, bus stops, and the other Art. 18(4) cases.
- **Show the law, never advise.** A Restricted place shows the rule and its citation (e.g. "Luật 36/2024, Điều 18(4): không dừng, đỗ nơi phần đường chỉ đủ một làn xe") and nothing else. No tips like "keep it brief", no nudging to break the rule.
- **Shared evidence:** "is this alley single-lane?" comes from the same width evidence as Alley Fit.

## Q8: City (2026-09-28)

- **HCMC.** It wins on alley evidence: car tags on 37% of alley length, legal widths from land parcels, 8,732 "hẻm xe hơi" listings. It has the only flood history (IRD 2002–2026) and a forecastable tide, which makes "get back out later" demonstrable. Demo Day is at HUTECH in HCMC.
- **Hanoi as an optional stretch:** its official live flood-point feed could become a small "works in Hanoi too" proof if time allows. *(Dropped in Q9: HCMC only.)*

## Q9: Coverage and demo area (2026-09-28)

- **Coverage:** the engine is region-agnostic, runs on any OSM extract, and is deployed for all of HCMC. Any HCMC address gets an Arrival Plan; thin evidence shows as Unverified (grey), never as "outside demo area".
- **Demo depth:** the Bình Thạnh strip (Điện Biên Phủ, Xô Viết Nghệ Tĩnh, Nguyễn Hữu Cảnh, Bạch Đằng; bbox 10.790–10.810N, 106.695–106.722E).
  - Evidence there: 1,646 alleys, car tags on 31% (141 tagged "no cars"), 16 public car parks, and 45 IRD flood records (19 precise; 22 tide, 11 rain, 12 both).
  - Recurrent flood streets: Ngô Tất Tố, Nguyễn Hữu Cảnh, Xô Viết Nghệ Tĩnh, Bạch Đằng, Ung Văn Khiêm.
  - Analysis: `data/analysis/`.
- **Ground truth:** a team field trip in the strip to tape-measure 20–30 alleys with photos, for validation and pitch footage.
- **HCMC only:** no Hanoi stretch.

## Q10: Unit of access evidence (2026-09-28)

- **Unit:** a Width Range on Clear Width, in metres. Each piece of Evidence sets a minimum and/or maximum. Legal width (lộ giới), width at the mouth and parcel gap are evidence *about* Clear Width, not the Clear Width itself.
- **Display:** the range shown with its Alley Label, e.g. "Hẻm xe hơi · 3.0–3.5 m".
- **Placeholder label bands (to tune):**
  - hẻm xe máy < 2.0 m
  - hẻm ba gác 2.0–3.0 m
  - hẻm xe hơi 3.0–5.0 m
  - ô tô tránh ≥ 5.0 m
- **How sources become limits (initial mapping):**
  - OSM `motorcar=destination|yes` → minimum ≈ one car.
  - OSM `motorcar=no` and listing "hẻm xe máy" → maximum.
  - Listing "hẻm N m" → maximum N, because it's measured at the mouth.
  - Parcel gap → maximum, because buildings encroach.
  - Tape measure → narrow range.
  - Driver confirmation "my <model> got in" → minimum = that model's width including mirrors.
  - Listing "hẻm thông" / "hẻm cụt" → Way Out evidence.
- **Conflicts:** a minimum above a maximum is flagged for review, never averaged away.

## Q11: Combining evidence (2026-09-28)

- **Trust tiers, then intersect.** Tiers, strongest first:
  1. Measured: tape measure, or a driver's measured photo.
  2. Official: parcel gap, fire-truck no-access lists.
  3. Observed: a driver confirmation, OSM car tags, and later T-Maps GPS traces.
  4. Declared: listing claims.
  5. Inferred: AI on imagery, router disagreement.
- **Precedence:** the highest tier present sets the range. Lower tiers may only narrow it.
- **Same-tier conflicts** are flagged for review (Trí's REVIEW state).
- **Unverified depends on the vehicle:** an alley is Unverified for a vehicle when its range can't decide that vehicle's fit.
- **Dates:** every piece of Evidence keeps its date and shows it. No automatic ageing in v1.

## Q12: Flood time window (2026-09-28)

- **The Dwell Window.** Park asks how long the driver stays (default 2 h); Pickup/Drop-off uses ~15 min.
- **Three flood-check windows (D25 refinement).**
  1. **Route in:** `[..., arrive]`, using a conservative traversal duration of `2 × route length / ALLEY_SPEED_MPS + FLOOD_TRAVERSAL_MARGIN_MIN`; durations are rounded up to the `FLOOD_TIMING_STEP_MIN` sampling bucket.
  2. **Stop Point:** the exact requested Dwell Window `[arrive, depart]`.
  3. **Way Out:** `[depart, ...]`, with the same conservative traversal-duration rule.
- Route-in and Way-Out windows are approximate; the checks include sampled interval boundaries and known tide, rain, and report boundaries, but do not prove continuous real-world conditions. `backend/app/plan.py` owns the windows and `backend/app/flood.py` owns evidence assessment.
- **Drivers:** the tide forecast (daily bulletin, peak hours) and rain now plus the next few hours (gauges, radar).
- **History as a prior:** it says *which* streets flood at a given tide or rain level. The window says *whether* that happens during the stay.

## Q13: Flood depth vs vehicle, and observation validity (2026-09-28)

- **Depth Range vs Safe Water Depth.** A Depth Range is the expected minimum and maximum water depth for a street and Dwell Window. A missing numeric range is not a verdict by itself; interpret it together with Flood Knowledge and the status.
  - **passable:** valid evidence supports staying within the limit; no Depth Range may mean no flood depth was estimated, not missing evidence.
  - **risky:** the range straddles the limit, or required knowledge is incomplete (missing history, tide, or a stale positive observation); treated as Unverified.
  - **blocked:** known evidence puts even the lower bound at or above the vehicle limit.
- **Knowledge dimension (R-03/R-04).** A Flood Status is only "known" when all required evidence is valid:
  - **known:** assessment is sound, all required sources present and valid
  - **missing_history:** no past flood records exist for this street
  - **missing_tide:** tide is required for this street but unavailable at the required time
  - **stale_positive_observation:** the latest positive flood observation has expired, and no newer, still-valid dry observation has arrived; expiry or a dry report that has itself expired does not prove the water receded.
- When knowledge is not "known" and status would be "passable", status is elevated to "risky". See `FloodAssessment` / `FloodSnapshot` in `backend/app/flood.py`.
- **Observation validity and persistence (R-03/R-04).** A flood or dry report is valid within `FLOOD_REPORT_VALID_H` from observation. The latest expired positive persists as stale evidence until a newer, still-valid dry observation clears it. This is not "no record = no risk"; it is "knowledge incomplete until proven dry". `FloodSnapshot` in `backend/app/flood.py` owns report validity and stale-positive handling.

---

From here on the user delegated the common-sense decisions to Claude ("you can decide by yourself"). Each entry below is a proposal the team can veto.

## D14: Safe Water Depth rule

- **Published wading depth** (exact Vehicle Model only): 50% of it, because published figures assume still water at a steady 7 km/h. So Ranger/Everest 400 mm; Fortuner 350 mm (from the AU diesel figure; label it "reference").
- **VinFast / EVs:** ground clearance, per VinFast's own manuals.
- **Any other car:** min(ground clearance, 250 mm), per Toyota VN's 25 cm guidance.
- **Size Class:** the lowest value in the class, as computed by `backend/app/vehicles.py` from the spec table: XS 151 (Morning), S 133 (Vios), M 140 (Camry), L 130 (Porter H150), XL 150 mm (Transit).
- **Moving water:** any rain-flood segment with a Depth Range reaching ≥300 mm is blocked for every car.

## D15: Alley Fit thresholds

Let W = width incl. mirrors (body + 0.25 m where not published).
- **Fits:** Width Range minimum ≥ W + 0.6 m (0.3 m per side) + 0.7 m (a row of parked motorbikes, the everyday hẻm reality).
- **Tight:** the minimum is ≥ W + 0.2 m but below "fits".
- **Doesn't fit:** the maximum is < W + 0.2 m.
- **Otherwise:** unknown, which makes it Unverified for that vehicle.
- **Getting out at the door:** Park at a door also needs W + 0.3 + 0.6 m to open a door. If not, the Stop Point becomes "drop-off only".

## D16: Turning in and turning around

- **Turn-in check:** applied at every alley mouth where the parent street's width is known, using `geometry.py` formula 4. If it fails, that alley doesn't fit even when its width is fine. Interior bends aren't modelled in v1; that's a known gap.
- **Way Out:** computed on the Fit Network.
  - Drive through if the segment connects onward.
  - Turn around at the first junction with another fitting segment, or a known space ≥ the 3-point-turn width.
  - Otherwise reverse. Reverse Limit 30 m (the median dead-end branch in HCMC is 27 m).

## D17: Temporary blockages

- **Cause:** weddings, funerals, morning markets and parked motorbikes at night block hẻm for hours.
- **Handling:** a driver's "blocked now" report is Observed evidence that expires at the end of the day.
- **Demo:** one scripted funeral-tent report.

## D18: Stop Point candidates

- **Park:**
  - VETC lots (national PDF list, geocoded with Goong).
  - OSM public car parks.
  - The 20 VETC-paid roadside streets.
  - Kerb segments that pass the Art. 18 geometry rules on streets ≥ two lanes wide.
  - Doors in alleys where Park is Permitted.
- **Pickup/Drop-off:** the door, alley mouths, junction widenings, and Permitted kerbs.
- **Excluded:** Google Places, because its terms forbid showing it on a Goong map.
- **Parking availability:** VETC's live free-space count, mocked and labelled "mô phỏng".

## D19: Walk Leg

- **Routing:** OSM foot routing.
- **Flood on the walk:** if the walk crosses a segment with a Depth Range above 150 mm, the walk is marked "lội nước" (wading). This shows the law of the street, not advice.

## D20: Routing architecture

- **Fit-aware routes:** a self-hosted GraphHopper on the HCMC OSM extract. We write each segment's Width Range into the graph (custom attributes), and each request filters by the Vehicle Profile.
- **Goong provides:**
  - base map tiles (MapLibre + Goong style)
  - search and autocomplete
  - geocoding, including new ward names
  - geocoding of VETC lot addresses
  - `place/children` for gates
- **The "standard route" from Goong Direction:** drawn next to ours as the contrast ("a normal map sends you here"). Goong is used in every visible step, which targets the "Best Use of Goong" prize.

## D21: Stack

- **Frontend:** Next.js + MapLibre GL + Goong styles; Vietnamese UI.
- **Backend:** Python (FastAPI) running `geometry.py`, the evidence engine and the flood window.
- **Layers:** precomputed as GeoJSON/PMTiles.
- **Routing:** GraphHopper in a container.
- **Hosting:** one Google Cloud VM for the demo.

## D22: AI components (brief criterion 4: 20 pts)

1. **Listings to Evidence:** an LLM reads Chợ Tốt "hẻm xe hơi" listings and extracts width, through vs dead end, and the alley chain. These become Declared evidence matched by the parsed address.
2. **Text to Stop Rules and flood evidence:** an LLM reads ordinances (parking-street lists, peak-hour bans) and news or social flood reports. A review gate (Trí's JEV: ACCEPT / REVIEW / INSUFFICIENT_INFORMATION) applies before anything is published.
3. **Photos to Evidence:** a vision model reads driver-submitted photos: a sign becomes a Stop Rule, an alley with a known object gives a width bound, and a flood photo gives a depth class.
4. **Cameras to flood-now evidence:** a vision model reads the public HCMC traffic-camera stills near flood hotspots during rain or tide peaks.
5. **Flood prior:** per-street susceptibility learned from the IRD history against tide level and rain.

- **Not used:** Google Street View or Places content, because Google's terms ban it.
- **LLM API:** whichever key the team has (Gemini via the paid Google account). Codex is for building.

## D23: Data flywheel

- **Arrival confirmation:** after each arrival, a one-tap "Xe bạn có vào được không? Vào được / Chật / Không vào được" (Did your car get in? Yes / Tight / No). It becomes Observed evidence tied to the Vehicle Profile.
- **At scale:** T-Maps/VETC GPS traces that end inside alleys become Observed evidence, with consent under PDPL 91/2025. For the demo this is synthetic and labelled "mô phỏng".

## Q14: Business model (2026-09-28)

- **Tasco-native only.** Free for drivers inside T-Maps (Linked Vehicle via VETC login). Revenue flows through Tasco's own businesses:
  1. VETC parking: a fee on each parking session at the lots the Arrival Plan recommends.
  2. Tasco Insurance: fewer thủy kích claims, plus a flood add-on offered at the moment of risk.
  3. VETC rescue: dispatched when a car does get stuck.
- **Not pitched:** a B2B API for ride-hailing or logistics, and data licensing. The Ride-hailing Driver persona stays in the product, but not as a revenue line.

## Q15: Name (2026-09-28)

- **Deferred.** Working name in documents: **Vào Được**.

## Q16: Build (2026-09-28)

- **Build now,** with Claude building independently.

## D24: Implementation changes (Claude)

- **Replaces D20's GraphHopper:** the backend builds a local street graph (OSM via Overpass) around each destination, cached on disk, and routes the last stretch on it with the Fit Network. The Bình Thạnh strip is prefetched so the demo runs offline. Goong still handles the map, search, geocoding and the Standard Route.
- **Replaces D21's Next.js:** a Vite + React + TypeScript frontend with MapLibre, served by the FastAPI backend.
- **No Goong keys yet:** the app runs on an open base map and switches to Goong styles and APIs once `.env.local` has `GOONG_API_KEY` and `GOONG_MAPTILES_KEY`.

## D25: Build refinements (Claude)

- **Flood timing by leg:** the route in is checked at arrival, the Stop Point across the whole stay, and the Way Out at departure (refines Q12's "across the whole window"). This is what lets "arrive fine, can't get out" show up.
- **Turn-in never fails an alley on its own:** failing the one-arc turn-in downgrades "fits" to "tight", because drivers can still enter with several manoeuvres (D16).
- **Ramps and expressways:** `*_link` ramps, motorways and trunks are Prohibited for stopping.
- **Main roads:** Park on primary/secondary roads without a VETC-paid listing is Unverified, because sign data is missing.
- **Ranking:** Restricted and Unverified share the last tier and are sorted by walk (Q6/Q7 left their relative order open).
- **Tide timing:** when the tide traps the car at departure, the verdict adds "leave before HH:MM or stay until after HH:MM". The leave-before option is re-checked with the full engine.
- **Demo blockage:** one scripted funeral-tent report (Hẻm 124 Xô Viết Nghệ Tĩnh), labelled "Mô phỏng", always active.
- **AI flags:** every AI feature sits behind its own flag, switchable at runtime (user request).

## D26: Google look-up, display only (user-approved)

- **Scope:** the "Tra cứu thêm" panel in the evidence drawer shows Street View looking down the alley, eateries within 80 m with their reviews (car and parking keywords highlighted) and Google's parking options, plus a Gemini answer grounded on Google Maps with source links.
- **Display only, per the Google Maps Platform terms:** Google content is never stored or scored, and never becomes Evidence. The driver's own Arrival Confirmation is what we store.
- **Flags:** `google_lookup` and `ai_maps_grounding`, both off by default. Keep them off in the main pitch run: the story is Goong + Tasco + our own evidence.
- **Spend guard** (`backend/app/budget.py`): monthly and daily counters on disk, capped well below Google's free allowances. Street View images 4,000/month, nearby search 800, place details 400, grounding 300. The Street View imagery check is free.
- **Gemini:** 12 AI Studio keys rotate round-robin, moving to the next key on a rate limit.

## D27: Live Area Build replaces the prepared listings file (user request, 2026-10-01)

- **On demand:** planning a destination starts a background build for its area. It fetches the OSM graph, pulls Chợ Tốt alley-house listings (sale and rent) from the 2 nearest districts, extracts claims and matches them to this area's alleys by alley-chain name. Results are cached for 12 hours. The plan is returned at once and re-planned automatically when the build finishes. The UI shows each step's progress.
- **Matching:** Chợ Tốt has no geo search, so listings are kept only if their street is in the area graph. The structured house number ("694/33") is used as the alley chain when the text has none. Coordinates are never used for matching (shifted ~90 m).
- **Listing photos:** with `ai_photo_evidence` on, Gemini reads up to 12 photos of matched alleys per build. A reading becomes Inferred evidence only through the ACCEPT gate. A human approval in the evidence drawer makes it Observed; a rejection removes it.
- **Flag:** `live_crawl` (on). When off, the prepared Bình Thạnh file is used as before.
- **Model:** Gemini 3.5 Flash. Most AI Studio keys can no longer call 2.5 Flash. The rotation skips keys that return 403/404 or an invalid-key error.

## D28: Map-first redesign and design system (user request, 2026-10-01)

- **Layout:** the Goong map fills the screen, with its places visible. A floating directions card (start, destination, my location, swap) has chips for vehicle, purpose and time, and plans run automatically on every change (newest request wins). The result sheet shows a decision-first verdict, total trip time, live data status and stop rows with four status tags (fit, way out, water, law). Evidence opens as a side panel. Demo presets, rain simulation, AI switches and "arrived" confirmation live in a Demo menu. Mobile uses a bottom sheet.
- **Start point:** with an origin, Goong Direction v2 drives each Stop Point's approach, and the trip shows total minutes (drive + alley stretch + walk). Right-click or long-press sets start or destination; reverse geocoding via Goong.
- **Tide timeline:** the stay is a draggable band over the tide curve, with the leave-before / stay-until marks.
- **Design system:** `frontend/src/ds/` (tokens, primitives, README). Informed by two independent usability reviews (Codex and Fable).
- **Goong contrast:** an alley counts as "on Goong's route" only if the route runs along it (2+ samples), not if it just passes the alley's mouth.

## D29: Car-only rules found on the RMIT test (2026-10-01)

- **Motorbike-only roads and lots:** OSM often tags motorbike-parking lanes as plain driveways or parking. A way or lot whose name says "xe 2 bánh / xe hai bánh / xe máy / motorbike" (or tagged `motorcar=no`, `motor_vehicle=no`) is not drivable for cars, unless it is explicitly tagged `motorcar=yes/destination`.
- **Reversing:** reversing beyond 2× the Reverse Limit (60 m) is not a Way Out at all (previously it only downgraded the stop). Between 30 and 60 m it still counts as a tight exit.
- **One Stop Point per way:** the three suggestions come from three different ways.
- **Overpass:** all mirrors are queried in parallel and the first valid answer wins. Without the `Accept: application/json` header, overpass-api.de answers in ~1–3 s instead of 406. A new area went from ~35 s to ~3.5 s.

## D30: HCMC only (user decision, 2026-10-01)

- Plans and live builds outside Ho Chi Minh City are refused with "Vào Được hiện chỉ hỗ trợ điểm đến trong TP.HCM" (HCMC bbox 10.35–11.20 N, 106.30–107.10 E). Search returns HCMC results only and is ranked around the trip, not around Bình Thạnh. Chợ Tốt is pulled from the 2 nearest HCMC districts. The Bình Thạnh files remain the offline demo and fallback only.

## D31: More sources for width and the area around a destination (2026-10-01)

- **Building gaps (citywide, offline):** 1.08 M Overture building footprints (Microsoft ML, Google Open Buildings, OSM) for urban HCMC. For each small road, rays every 6 m measure the building-to-building gap. Per way: median, 25th percentile, sample count, share of samples walled on both sides. Evidence tier Inferred, bound [p25 − 1.2 m, median + 0.8 m], ways ≥ 40 % walled. Pipelines: `overture_buildings.py`, `building_gaps.py`.
  - **Validation failed, so the flag `building_gaps` is OFF by default.** 33,620 ways measured (19,008 ≥ 40 % walled). The gap overstates width (+4.2 m vs 26 OSM `width=` tags, +2.0 m vs 9 listing widths) and does not separate alleys tagged `motorcar=no` (median 8.2 m) from `motorcar=yes` (8.1 m). Points on no-car alleys are not inside merged footprints either (0.4 % vs 0.6 %). ML footprints from satellite imagery do not resolve HCMC alleys (roof overhangs, merged rows). Revisit with street-level imagery or field data for calibration.
- **Alonhadat listings (live):** structured "Đường trước nhà" (road in front) and "Loại BDS: Nhà trong hẻm" (house in alley) fields, 5 pages per nearest district, cached 12 h, robots.txt-allowed pages only. Declared tier, same alley-chain matching as Chợ Tốt. Yield is low because house numbers are hidden.
- **News (live):** Google News RSS search (no key) for flooding, roadworks, barriers and car bans on the named streets within 450 m, last 12 months. Gemini keeps items about that street in HCMC (keyword filter when no model). Shown with source and date; not Width Evidence.
- **Not used:** Gemini grounding with Google Search (free keys have zero quota), batdongsan.com.vn (403), Google Maps content (D26).

## D32: Official width sources: fire-access list and cadastral parcels (2026-10-02)

- **QĐ 4582/QĐ-UBND (24/7/2026), Phụ lục 2:** roads and alleys fire trucks cannot enter, ward by ward. Parsed 6,742 items in 50 wards from the luatvietnam.vn text (PDF-converted: numbering restarts per ward, stray spaces in words). Ward centres geocoded with Goong. Matched 1,024 items → 1,354 OSM ways by space- and accent-insensitive name, nearest the ward centre (≤ 3 km; ≤ 1.5 km for short generic names). Pipeline `fire_access_4582.py`.
  - **Encoded as Declared [0.5, 3.5 m], not Official.** QCVN 06:2022 needs 3.5 m for a fire truck, but validation shows the list is not width alone: of 20 listed alleys with a listing width, 11 are ≤ 3.5 m and 9 are 6–8 m (long dead ends, bends and low wires also qualify). A conflict with a listing at the same tier asks for review instead of silently overriding.
- **Cadastral parcel gaps (live, per destination):** the HCMC planning portal returns the land parcel at a point; cross-sections measure the gap between the two parcels. The gap is an **Inferred `parcel_gap_estimate`**, not a measured clear width: official provenance does not make it Official-tier width evidence. Flag `parcel_widths` (on). Module `backend/app/parcels.py`.
  - **Validation (earlier, before this revision):** consistent with listings on the same alleys ("xe hơi" 2.7–5.6 m, "ba gác" 2.6–3.4 m). That supports the estimate as a hint, not as strict-fit proof; the earlier demo claim that parcels turn "tight" into "fits" no longer holds.

## D33: Parcel widths: usable = gap − 1 m; narrowest cut kept; coverage tracked (revised 2026-10-12)

- **How a cut works:** draw the line across the alley, query 1.5 m (then 3 m, 5 m) to each side, and measure from the centreline to each parcel boundary; left + right = parcel gap. A cut is rejected if one side is under 0.3 m or both queries return the same parcel.
- **Usable estimate = parcel gap − 1.0 m** (steps, ramps, stalls, parked motorbikes). It is an estimate: it cannot see obstructions between cuts.
- **Bound = the narrowest valid cut**, not a percentile: dropping the narrow cut hides the bottleneck a car actually hits. Malformed or mismatched cuts mark the way for review instead of being dropped silently.
- **Coverage is evidence:** each result records endpoint coverage, maximum spacing and truncation. Deep scan samples both endpoints and about every 5 m (shared cap of 60 cuts) over full ways on the legal ingress **and** egress paths. Sparse or truncated scans are diagnostic only.
- **Decisive clearance** needs a physical measured/observed basis, finite uncertainty, complete endpoint coverage and no cross-tier conflict (`backend/app/evidence.py`). Anything weaker is Unverified in strict fit, turn and legality predicates; relaxed suggestions stay visibly unverified. Not yet calibrated against field data.
- **Way Out and Walk Leg (R-06):** one-way ±1 is honoured on entry, exit and reverse; a turn or lot exit is never marked verified without swept-space or gate evidence; the 5 m junction rule subtracts half the crossing road's width or is Unverified; a stop with no walk connection within 35 m is rejected with `missing_walk_connection`; unmapped connectors are flagged and not drawn.
- **Toggle (2026-10-05):** the deep scan is its own switch, `parcel_deep_scan`. Flipping either parcel switch re-runs the area build in the open page; a build that started before the flip is discarded.

## D34: Large-road route choice from live traffic cameras (user request, 2026-10-05)

- **Why:** the arrival plan only judged the last stretch. A driver going home from Quận 1 at 17:30 also needs to know which large road to take, e.g. Phạm Văn Đồng instead of a Hàng Xanh / Cầu Sài Gòn that has not moved for an hour, and whether standing water on the way is deeper than the car can wade.
- **Cameras:** the ~800 public cameras of Cổng thông tin giao thông TP.HCM, read straight from the portal: the backend refreshes its camera layer hourly in a bounded background worker while requests continue using the last published registry; the shipped `data/cameras/hcmc_cameras.json` is the cold-start/outage fallback. The public map page's request is anonymous AjaxPro `FolderAjax.SearchQuery`; the 5 Oct sample had 684 `UP`, 112 `NOT_IMAGE`, and portal status matched 40 sampled images. Stills come from `render/ImageHandler.ashx` (`:8007` CameraHandler answers 403); a still refreshes every ~12–13 s with ~4 s lag (clock burned into the frame). A camera that returns the fixed 2,638-byte `IMAGE NOT AVAILABLE` placeholder is never sent to the model.
- **Reading:** the job tries for two frames one refresh apart, so "kẹt cứng" (not moving) is based on movement between frames, never on one still. If the bounded job deadline cannot cover the next refresh, it may use one frame for observable flooding only; traffic is forced to `khong_ro`, not used to score route delay. The reading and any promoted flood observation record the frame count; the UI shows it. A one-frame flood observation does not verify traffic flow. Gemini returns, per camera: printed clock, usable, flooded and depth class (wet ≠ flooded), traffic, evidence, confidence. A frame whose clock is more than 10 min off is stale and ignored. Readings are cached 3 min and logged to `store/camera_readings.jsonl`. A confident flooded reading also becomes flood-now evidence for the arrival plan (same ACCEPT gate as before).
- **Alternatives:** Goong returns one car route and ignores `alternatives`. Other routes come from routing through cameras that lie to either side of Goong's route mid-trip (cameras sit on arterials); a route more than 1.6× longer or overlapping another by ≥ 80 % is dropped. Vạn Phúc City ↔ Quận 1 gives Xô Viết Nghệ Tĩnh (Goong), Điện Biên Phủ, Phan Đăng Lưu and Phạm Văn Đồng.
- **Score:** Goong's time × a traffic factor on the stretch each camera watches (±700 m: thông thoáng 1.0, đông 1.3, ùn ứ 2.0, kẹt cứng 4.0) plus a queue a still cannot measure (ùn ứ +3, kẹt cứng +10 min). Stretches no camera watches take the median factor of all cameras read, so a route is not "faster" just because fewer cameras watch it. Water from a camera or from the flood forecast along the route (tide, rain, IRD history at the time the car passes, the alley model) deeper than the car's Safe Water Depth blocks the route; risky water adds 5 min. Alleys more than 400 m from either end add 2 min and a "width not checked" note. Fastest unblocked route wins, with its biggest reason stated.
- **A group of cameras at one junction** is rated by the lower median of its confident traffic readings (one camera catching a passing queue no longer rates a junction its neighbours see moving; a real jam shows on most of them) and by the deepest water any of them sees. The group is shown under the camera that set its rating. Found on a live walk-through (5 Oct, 11:06): Đinh Bộ Lĩnh – Bạch Đằng 3 read a red-light queue as "ùn ứ" and added 7 min to every route while Bạch Đằng 2 next to it read clear. The prompt asks for the more congested direction when the two differ. (A red-light rule was tried and removed: on a 07:02 frame it turned a carriageway packed end to end at Hàng Xanh into "đông". Missing a real jam costs far more than a few minutes of detour, and the median already absorbs one camera fooled by a red light.)
- **Time:** cameras describe now, so they count only for departures from 15 min ago to 45 min ahead; later trips are chosen on the flood forecast alone, and the card says so.
- **Flag:** `ai_camera_flood`, now on by default. With it off, routes still compare on Goong time and the flood forecast.
- **Model quota:** the free tier gives `gemini-3.5-flash` only 20 requests per key per day (11 valid keys → ~220 calls, ~25–35 route checks). Camera reads now fall back model by model (`CAMERA_MODELS`, default `gemini-3.5-flash,gemini-3.1-flash-lite`): a model that answers 429 on every key rests 10 min (503: 1 min) and the next one reads; each model has its own daily quota. Check on 36 rush-hour frames (5 Oct, 07:07–07:37, one frame each): `3.1-flash-lite` matched `3.5-flash` on 28, never more than one level off (1 jam missed, 2 extra). `3.5-flash-lite` called a busy road gridlocked; `3.6-flash` timed out on 2 of 6 batches.
- **Placeholders to tune from the reading log:** traffic factors, queue minutes, coverage, the 0.5 confidence floor.

## D35: Tide and rain near real time (user request, 2026-10-05)

- **Why:** the tide came from a bulletin copied by hand into `data/flood/tide_forecast.json`. It ran out on 3 Oct, so from then on no street flooded from the tide, and nothing said so. Rain was only the app's what-if toggle, so a real downpour counted for nothing unless the user switched it on.
- **Tide:** the measured Saigon River level at Phú An (station 71600, the station BĐ1–3 refer to) from the national disaster-monitoring portal vndms.gov.vn, read the way its public map does (visitor session, `POST /home/detailRain`, 7 days). It has about one reading every 3–6 h, 1–3 h behind. Between and after readings, the level follows Open-Meteo's sea-level model at the Soài Rạp mouth, shifted and scaled to fit the last 7 days of readings. Best of three coastal points, 5 Oct: lag 2.5–3 h, scale ~1.1, offset ~−0.65 m, error on 2 held-out days 0.14 m RMSE. The model is pinned to the readings on both sides between two readings, so that stretch counts as measured. After the last reading its offset fades over 6 h. A model hour carries a ±0.15 m band in the depth range, so a level of 1.45 m reads as anywhere from below BĐ1 to above BĐ2. Check: on 5 Oct the model put the 9 Oct peak at 1.56 m, and the official bulletin forecast 1.55–1.60 m. The bulletin file is the fallback when the portal and the model are unreachable.
- **Rain:** hourly totals from the HCMC gauges on the same portal that report every hour through the current hour: 18 VRAIN street gauges and 22 citizen gauges. KTTV and hydrology stations report daily, so they are not used. The wetter of the two nearest gauges within 5 km counts, because rain is patchy and missing a downpour costs more than a false alarm. Hours after the last reading use Open-Meteo's hourly forecast for the point. Each wet hour keeps counting for 1 h after it ends, because streets drain slowly. That 1 h is an estimate.
- **What-if:** the rain toggle still overrides live rain. With it off, plans and route checks use the measured and forecast rain at the destination, or at each flooding street along a route.
- **Shown:** the tide timeline draws measured hours solid, with dots for the readings, and model hours dashed. It shows the latest reading and the model band, and draws rain bars (measured dark, forecast pale) with the latest measured wet hour and its gauge.
- **Flag:** `live_hydro`, on by default. With it off, the app uses the bulletin file and what-if rain only. Sources are cached 15 min (tide readings), 10 min (each gauge), 30 min (rain forecast), 1 h (sea-level model) and 1 day (gauge list). The last good answer is kept while a source is down, and a failure is retried after a minute.
- **Not yet:** street-level water still comes only from cameras, photos and reviewed text. Neither the portal nor Open-Meteo measures street flooding. The depth bands per alarm level and rain rate are still our estimates (D14).

## D36: One persistent backend owns evidence, reviews, quotas and jobs (2026-10-12)

- **Why:** the browser carried each area build back with every plan, so any client could send made-up listings, parcel cuts or "approved" photos and the plan would reason from them. Any visitor could also flip flags, approve photos, write confirmations and blockages straight into evidence, schedule unbounded crawls and spend AI quota. A corridor request waited 13–19 s inside the request for camera frames.
- **Deployment:** one continuously running `uvicorn --workers 1` with persistent store, cache and flags directories, serving the frontend from the same origin. It supersedes the serverless deployment that `vercel.json` and `api/index.py` set up for the Vercel function: per-instance state cannot hold sessions, reviews or quotas, so the backend refuses to start on Vercel and those files are removed. Scaling past one process needs a shared store first.
- **Area evidence is server-owned:** an operator schedules a build; it runs in a bounded pool (one per area, 2 running, 4 waiting, 300 s monotonic job budget) and only a completed build is published as a versioned record (12 h). Every upstream attempt receives a timeout capped by the remaining budget; retries, inter-attempt waits and steps check the deadline. Individual HTTP phase timeouts do not prove a strict end-to-end 300 s wall-clock ceiling. Plans read the record from the server and say when it is missing, partial or stale; an expired record is not used. The static evidence index is rebuilt off to the side and published by one reference swap; an area build is a per-request overlay and never mutates the shared index.
- **Operator access:** a server-side secret, a random session in an HttpOnly SameSite=Strict cookie, logout revokes, and an Origin check on every state-changing request. Without a configured secret operator features are unavailable, never open. Guests plan, read cached camera readings and submit reports.
- **Reviewed reports:** guest confirmations and blockages, and AI text and driver-photo extractions, become pending reports keyed by id. Only an operator approval publishes; the approved state is written before its projection and every projected line carries the report id, so a crash or a repeated approval never publishes twice or loses one. Expired reports never promote. Old unreviewed community lines were moved to `store/quarantine/` and queued, not deleted. The demo funeral-tent blockage is a read-only fixture labelled as simulated.
- **Exception: camera flood sightings still publish immediately** (gated by the deterministic ACCEPT rule). They come from the city's own camera portal, not from users, and holding a positive flood sighting back could let a plan call a flooded street dry.
- **Cameras:** a corridor answers at once from the forecast and cached readings. An operator request queues at most 12 unread cameras (Goong route's stretches first, one camera each, then alternatives); the rest are listed as dropped and their stretches stay "unknown", never "clear". 2 jobs run at once, at most 24 cameras wait, a camera already being read is not read twice, and a failed or model-less reading stays unknown.
- **Spend:** every upstream AI attempt reserves quota first (per provider/model/key fingerprint, configurable daily caps), including retries on another key or model; an unreadable counter stops spending. Paid Google calls keep their per-SKU caps. These protect this backend's own spend, not a shared billing account.
