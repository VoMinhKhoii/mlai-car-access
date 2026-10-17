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

## D37: City footprint calibration fails vehicle-access accuracy; keep opt-in (2026-10-17)

- **Open data, no portal requests:** Overture buildings release 2026-09-23.1, downloaded 17 October ICT: 1,157,746 footprints over 10.68–10.90 N / 106.55–106.88 E plus a 30 m halo. Combined theme ODbL 1.0; Microsoft/OSM ODbL, Google Open Buildings CC BY 4.0. Attribution and provenance are recorded in `docs/eval/footprint-report.md` and `footprint-calibration.json`. Existing crawler OSM batches and cadastral results are read only; four OSM bbox edge strips complete the rectangle. No paid AI.
- **Breadth, with missing observations explicit:** 100,388 drivable non-main ways sampled at 10 m, ±15 m perpendicular rays, STRtree, 54 tiles / 6 local processes, 32.4 s compute. Full polygons and multipolygons; reject roofs covering the centreline and shared/misaligned buildings. Open sides remain unknown. 18,268 ways (18.2%) pass ≥3 two-sided cuts and ≥40% valid cuts; 7,650 of 35,657 named/tagged alleys (21.45%). This does not satisfy “every alley has a reliable width”.
- **Compare raw gaps, not usable widths:** snapshot 242 cadastral ways / 431 cuts; 170 exact-location footprint matches on 117 ways. Raw way-weighted footprint-minus-`gap_m`: median +6.611 m, mean bias +6.773 m, MAE 7.286 m, P90 absolute error 14.220 m. Source-pair breakdown is in the report.
- **Correction is not enough:** way-disjoint split 74 fit / 19 calibration / 24 test. Subtract fitted median bias 6.227 m. Test median absolute error 3.609 m, MAE 4.917 m, P90 10.664 m. Residual/bottleneck calibration needs ±11.413 m; 23/24 test medians covered. A constant training-median cadastral gap has MAE 1.810 m; raw held-out gap correlation r=0.063. Imagery does not reliably separate narrow and wide alleys. Geographic transfer and clear-width obstacles remain unvalidated.
- **Tier Inferred, never Observed/Official:** Q11 classifies algorithmic imagery as inference. Bound uses corrected P10 to corrected median, the calibrated radius, the same 1 m encroachment assumption as D33 and an explicit extra ±0.5 m obstacle allowance. This is not a physical measurement. Generic OSM class priors cannot truncate this calibrated band. Measured/Official evidence excludes footprints from combination entirely, even if intervals overlap; the footprint stays visible as overruled.
- **Ship the research product; default OFF:** new `footprint_widths` flag is separate from D31's `building_gaps`. Atomic `backend/cache/live/footprint_widths.json`, mtime reload before plan-cache lookup, source/date text and uncertainty, live `/api/config.coverage` strongest-tier counts. Broad intervals should leave vehicle fit unknown. No confident width-class or “all alleys resolved” pitch claim is justified.
- **Verification and image:** six real cached-graph HTTP plans via FastAPI TestClient: Q8/Gò Vấp/Tân Phú expose Inferred footprint bounds and unknown door fit; three Bình Thạnh Official overlaps are unchanged when footprints are toggled. No OSM/Goong/AI/portal calls in verification. `docs/eval/coverage-footprints.png` is a 3840×2160 experimental point-estimate map, explicitly labelled with ±11.4 m error and unknown coverage. Detailed requests, metrics, tier counts, limitations and reproduction commands: `docs/eval/footprint-report.md`.

## D38: Missing legal coverage is Unverified (2026-10-17)

- Replaces Q6's/D25's implicit permission from absence of a recorded ban. Streets without affirmative authorization remain Unverified for both intents: “Không thấy quy định cấm đã biết trong dữ liệu hiện có”. Existing prohibitions and Restricted pickup rules retain precedence.
- A mapped or VETC-listed lot alone does not establish admission or operating hours. Until authorization is explicitly verified, lot legality is Unverified; customer/private access cannot be certified by a listing.
- The no-rule fallback appears only when there is no applicable rule; it is never appended beside a known prohibition or restriction.
- “Được phép” is reserved for affirmative authorization. This is a knowledge-policy correction, not a claim of complete statutory coverage; exact local legal clauses/curb/sign scope still require archived evidence.

## D39: Spatial bottlenecks and coverage replace width quantiles (2026-10-17)

- Replaces D33's P20/P80 certification rule. Every credible valid cut constrains the bottleneck upper bound; quantiles remain descriptive. Sample uncertainty is ±0.3 m, an explicit uncalibrated modelling allowance, separate from the 1 m usable-width deduction.
- Legacy cuts and destination prefixes carry no whole-way lower guarantee. An incomplete Official survey cannot be certified by lower-tier listing/class bounds. Complete coverage must be explicit, valid, and cover the whole OSM way; current automatic sampling does not assert continuous clear-width coverage.
- A conflict at the decisive tier propagates as unknown vehicle fit. Lower tiers cannot choose a winner; conflicts wholly below an uncontested stronger tier do not poison that stronger survey. Dates are retained.
- Reject cadastral cross-sections within 5 m of a bend greater than 15 degrees; destination/nearby scans also reject frontage cuts within 5 m of a known physical junction; preserve polygon holes and select the component containing the actual side query. New cuts expose schema, heading, margin, attempted locations and coverage. Intersections without validated frontage/coverage cannot certify a whole corridor. Existing crawler processes retain their imported code; `measure()` remains call-compatible.

## D40: Directed joint arrival and Way Out search (2026-10-17)

- Replaces D16/D25's way-wide turn downgrade and D29's single predecessor exit test. Routing now carries incoming-edge heading; arrival side and departure feasibility are selected jointly. Alternative directed paths are searched, with physical angles independent of OSM way IDs. Immediate reversal is a manoeuvre, not an ordinary forward graph edge.
- A failed/unsupported one-arc turn is explicitly unknown; it cannot certify an assumed multi-point turn. A physical three-arm junction within 60 m permits an Unverified manoeuvre hypothesis only. The 30/60 m reverse policy is unchanged. Reversing and turning may not traverse a one-way edge against its direction.
- A modelled turnaround needs both width and contiguous straight corridor length; one broad sample or short widening is insufficient. The required ideal corridor length conservatively includes the simulator's extent and vehicle length plus turning diameter. This remains a kinematic model awaiting field/swept-area validation.
- Vehicle manoeuvre cache keys include dimensions, track, mirror width, margins and solver revision. Old ID-only disk values are not reused. Lot access/internal turning is explicitly unknown until mapped/surveyed.

## D41: One pedestrian path defines the Walk Leg (2026-10-17)

- Replaces endpoint-only distance plus separately reconstructed geometry. Virtual stop/destination edge positions support direct same-edge walking; one chosen edge sequence supplies metres, drawn geometry, partial-edge flood exposure and the unrounded intent cap.
- `foot=no` and private/no-access tails are unavailable. Unmapped connectors and pedestrian centreline paths without sidewalk/crossing evidence are Unverified. No claim of surveyed pedestrian entrances/curb crossings is implied.
- Missing drive/walk projections or main-road coverage return insufficient-data wording without a fabricated path or a crash.

## D42: Flood missingness, dwell events and timing verification (2026-10-17)

- Missing street response or an out-of-forecast tide is `unknown`, not predicted dry. Unknown depth serializes null bounds and reasons, propagates to Unverified routes/stops, and never produces a “Không ngập” badge. Known historical profiles under inactive modelled drivers may be predicted passable; this remains a heuristic, not a validated depth forecast.
- D14's hard policy now uses the rain-driven upper bound reaching 0.30 m to block every vehicle. A missing rain-history profile no longer receives an unsupported 0.10 m ceiling. Rain-on-tide increment requires an actual tide driver, not any live report.
- Dwell evaluation includes actual tide extrema, rain start/end boundaries and both sides of discontinuities. Overlaps combine by maximum intensity, independent of input order. Rain water is conservatively retained for 60 minutes after the scenario ends; this explicit assumption is uncalibrated and does not claim a hydrological recession model. The deepest depth/time is selected even when status ties.
- Timing alternatives no longer use a generic tide street. Both earlier and later departures require a full nested planner recheck for the same destination/door and revised dwell; unknown or failed plans suppress the instruction. The bounded search covers two hours earlier and twelve hours later in 15-minute steps. No timing guarantee is emitted from insufficient evidence.
- Flood calculations/live-report reads are memoized per request; nested rechecks retain their own time keys. Negative dwell and invalid rain intervals are rejected independently of rule evaluation.

## D43: Scope legal evidence and evaluate the parked interval (2026-10-17)

- Junction exclusions use physical neighbor arms and along-road distance through shape nodes, subtracting an available intersecting-road half-width; changing OSM way IDs cannot create/remove a T junction. This is still a corridor proxy, not a surveyed curb polygon.
- Signs require association to the candidate way; unassociated nearby signs are not attached by radius. An associated sign is retained beyond the old 40 m cutoff. Full directed curb-side and until-next-intersection scope remains incomplete and is not claimed as legally complete.
- Park and pickup legal checks evaluate arrival, departure and each midnight transition for the currently supported odd/even-day signs. Fee/access/marking keys are not blanket bans; side-only restriction tags remain Unverified without a curb side.
- `covered=yes`, a name beginning “cầu/hầm”, and the functional class `trunk` alone no longer assert a bridge/tunnel/expressway prohibition. Explicit bridge/tunnel/motorway evidence retains the existing rule. Exact archived point-level legal clauses remain outstanding; the engine does not claim statutory completeness.

## D44: Mode restrictions, cache revisions and parcel budgets (2026-10-17)

- The engine's routing view now applies `motorcar > motor_vehicle > vehicle > access`, private/no-access gate nodes, and implicit one-way roundabouts. Known maxwidth restrictions remain independent of physical evidence. Weight/axle/height/length limits without adequate vehicle attributes are Unverified; a measured wide bridge cannot certify an unknown-weight Transit. Fetching/enforcing relation-based and conditional turn restrictions remains outstanding in the graph loader.
- Off-network lot links and internal turnaround are Unverified. Real mapped/surveyed entrance paths remain outstanding.
- Width/flood caches include graph content revisions and are bounded to 16 entries each; a refreshed graph cannot reuse the prior way-ID dictionary. Manoeuvre caches include specs/solver/margins. This does not yet canonicalize or reconcile stale deep cuts in live.py, nor stitch coverage at graph boundaries.
- Parcel destination scans consume attempted locations, not successful cuts, from the 60-cut/300 m budget; path ways cannot re-enter as nearby samples. A city `deep` boolean alone cannot skip destination-specific coverage. Failed samples retain attempt locations/validity and no positive clearance floor is invented. `measure()` arguments are unchanged, and no portal/HTTP transport code was changed.
- Driving preference penalties remain search costs; reported driving metres come from the selected physical geometry.

## D45: Vehicle envelope, units and provenance (2026-10-17)

- Door clearance now follows D15's mirror-inclusive width +0.3+0.6 m. An arrival confirmation uses mirror width unless folded mirrors are explicitly recorded. The published-wading comparison uses metres on both sides.
- Derived VF 8 radius and composite Size Class geometry are labelled estimated; CSV assumptions are exposed, missing ground-clearance fallback is visible, Fortuner water depth explicitly identifies the Australian diesel reference, and Xpander uses the CSV note's conservative 5.5 m radius.
- Legacy raw parcel CSV gaps are converted once using the same 1 m usable-width deduction and explicit raw-to-usable schema. Their unobserved span has no guaranteed lower width. Current live cut values are already usable and are not deducted twice.
- The additional 0.7 m D15 operating margin remains conservative and uncalibrated alongside D33's deduction; resolving overlap against field observations remains outstanding. No accuracy claim is based on these assumptions.

## D46: Preserve failed-survey uncertainty and avoid positive wording (2026-10-17)

- A parcel survey with no valid cuts remains an unresolved Official coverage bound [0, open], rather than disappearing and allowing a weaker listing/class prior to certify the whole way. Rejected geometry does not contribute a width; it does retain the missing-coverage fact.
- A permissive through/turn route gets “Chưa xác minh đường ra”, rather than a positive Way Out badge, even when the map contains a topological path.
- Restricted pickup verdicts state the place, walk and prohibition/citation without the former “Gợi ý” stopping advice. This preserves Q7's law-vs-practice policy while removing advice to stop where the displayed rule forbids it.

## D47: Main-road handoffs must pass the junction turn (2026-10-17)

- Arrival source states include actual incoming main-road headings. An unspecified local handoff can align with a main road, but cannot certify an arbitrary main-to-alley turn; an unsupported turn remains unknown.
- Reaching a main-road junction is not sufficient for a verified Way Out: the incoming alley heading must have a permitted feasible transition onto a main-road arm. This closes a source/target boundary exception to the directed-turn checks.
- The one-arc model covers turns up to 90 degrees. Sharper turns remain unknown without additional manoeuvre evidence, even when widths look generous; no 100-degree tolerance is treated as a validated model.


## D48: Street-level width observations require human review (2026-10-17)

- The explicitly requested imagery batch uses the demand-ranked evidence queue, all named/tagged alleys intersecting HUTECH's 500 m circles, and a preselected cadastral validation pool. This research batch differs from D26's display-only Google lookup; the existing lookup UI and saved flags remain unchanged. Google Maps terms §3.2.3 restrict creating content from Maps content; this implementation is not a determination of permission under those terms (https://cloud.google.com/maps-platform/terms). No raw Google image is stored.
- Reject off-centreline (>3 m), frontage/endpoints (<8 m), ambiguous nearby-way panoramas before fetching Static images. Vision must identify daylight, inside-alley placement and a visible reference object. Wall-to-wall space and visible obstruction-adjusted clearance are separate. Dates come from source metadata; a listing post date is not an image capture date. Cache provider/pano/heading readings, including rejected results, rather than repeatedly paying for a failed image.
- A visual spot-check found a confident v1 false positive on a straight-on building frontage. All 164 v1 readings were quarantined in `legacy_records`, with none approved or loaded into Evidence. The v2 prompt/gate requires `view_axis=along_alley` and `opposing_edges_visible=true`; the worker re-reads candidates within the same unchanged cumulative job cap. This concrete failure is an additional reason to require human review.
- **REVIEW-only, no auto-approval.** The gate's ACCEPT means structurally usable, not published. Every usable reading remains pending. A named human review is required to activate an Observed bound. Poor or unavailable validation never promotes a reading. Cadastral gap minus 1 m is an encroachment proxy, not independently surveyed clear-width truth, and a small local convenience sample cannot validate geographic transfer.
- Validation uses visible clear-width midpoint against the nearest valid cadastral gap minus 1 m within 15 m, way-weighting absolute errors for MAE and signed errors for bias without cancelling opposite errors. Unlocated listing views versus the way's narrowest cadastral cut are reported separately as a weaker proxy, never evidence of spatial accuracy. Zero pairs means MAE/bias unavailable, not zero error.
- Human-approved imagery contributes only [0, visible width_hi] with incomplete coverage. A few images cannot certify the unseen remainder of an alley. Original local intervals, references, obstructions, provenance, capture-date missingness and review decisions remain in the review product. Evidence and queue caches reload after approval/rejection. Existing Measured/Official precedence remains intact.
- **Money:** every Google metadata/Static request still reserves through budget.spend(), with caps unchanged; added interprocess locking prevents batch/live lost updates. Gemini uses gemini-2.5-flash, ≤640 px JPEG, zero thinking budget and ≥2048 output tokens. Free AI Studio is tried first whenever the shared project cooldown expires. Vertex calls reserve/settle through agent_budget in one locked transaction with a persistent imagery job ceiling of $1.00 and an additional shared ceiling of $1.10, leaving $1.90 of the $3 pool unconsumed by this job. Existing conservative ledger token prices are retained. No reservation or allowance resets on worker restart.
- The worker is detached, resumes cached work, stops Google on denial/caps, and can wait until today's free-project reset before one free-only continuation. Mapillary is skipped without MAPILLARY_CLIENT_TOKEN; its discovery/download/position-check/vision path is available via --mapillary.

## D49: Official bulk road widths and planned right-of-way stay separate from current Clear Width (2026-10-17)

- Public HCMGIS WFS supplies 2021 Phước Long A road lines with `chieurong`; the official Quận 9 QĐ 01/2009 annex separately lists historical road/base width and planned lộ giới. Store sourced, dated numeric fields as **Official metadata**, exposed in `WidthRange.official_width_records`, outside `Bound` and `_combine`. A file retrieval date is not a survey date.
- Planned lộ giới is a planning/legal corridor, not today's narrowest usable passage. It cannot establish a positive lower bound. It is also not necessarily an upper bound on today's physical width: implementation, later amendments, source extent and correspondence are unverified. A separate field avoids an unsupported upper-bound assumption, and cannot change fits/blocked decisions, strongest-tier coverage or measurement-queue scarcity. Historical base/road widths also remain metadata until present-day meaning and validation are established.
- The gazette describes QĐ 01/2009 as partly amended by QĐ 09/2012 (hẻm 301, 8 m; ambiguous identity retained for review). The generic QĐ 88/2007 rule was repealed by QĐ 563/QĐ-UBND on 26 January 2026; never manufacture way widths from its minima. Retain original dates and current legal-status caveats.
- Match exact explicit alley/street chains through the existing normaliser/matcher, rejecting parent fallback, cross-ward duplicate source names and multiple distant OSM clusters. WFS matching requires at least 15 m of way, ≥90% within 3 m, compatible direction and no competing qualifying source. These gates identify candidate correspondence, not a validated current survey.
- The current 213-way city cadastral reference becomes 244 ways after deduplicating area caches. Compare raw `gap_m`, not the gap-minus-1 usable estimate. Neither imported source overlaps this reference, so agreement and width errors are **N/A**, never zero-error/100%-agreement. Current Clear Width coverage gain is **zero**. Detailed import/matching counts and source rights are in `docs/eval/official-bulk.md` and its validation JSON.
- WFS advertises `Fees=NONE` and `AccessConstraints=NONE`, but no explicit redistribution licence was found. Keep original geometries in the private research cache and expose only dated, attributed factual metadata; request written terms before external redistribution. The city open-data catalogue's relevant PDF is a data dictionary with unspecified licence and restrictive site terms. The newer advertised ArcGIS parcel FeatureServer returned application status 401; no token, credential, alternate path or workaround is used. A formal account/data request is the next step for city-wide data.

## D50: Best estimate with explicit confidence, without weakening Hard Checks (2026-10-17)

- Product-owner option 1: every evaluated stop (including a rejected door) and every verdict carries `estimate = {answer: fits|tight|no|unknown, confidence: high|medium|low, basis}`. `verified`, `unverified_reasons`, strict fit, Hard Checks, ranking, legal exclusions, water limits and walk caps remain separate and unchanged. The verdict estimate describes its first stop; the door's own estimate describes the door. No returned stop is promoted to verified by an estimate. A missing graph produces unknown/low; no eligible stop produces no/low, meaning none found in the available network, not proof about the whole neighborhood.
- Width hypothesis: use the minimum valid sampled bottleneck at the decisive tier when available (legacy raw gaps use the already-converted gap minus 1 m, not half of the missing-coverage interval; a numeric Declared listing retains its stated width for estimation only), clamped inside the fused Width Range. Otherwise use `(lo + min(hi, lo+3 m))/2`. The cap avoids treating an open upper bound as an implausibly wide road. An entirely unresolved survey may retain a non-overruled weaker prior for a low-confidence hypothesis only. A decisive conflict has no point estimate. A sample point is never installed as a lower bound. Existing upper-bound bottlenecks and no/blocked fit exclusions remain hard.
- If the selected permissive route uses a width hypothesis below `tight_min`, a request-local secondary search excludes those doubtful edges and looks for a plausible detour. It reuses all original fit, flood, turn and access checks; no unknown edge is upgraded to a strict pass. Joint selection still prioritizes strictness and exit tightness, then a plausible width hypothesis before distance. This prevents a smaller car’s larger permissive network from turning a short doubtful shortcut into a worse estimate than a wider car’s detour. Hard Checks and stop ranking remain intact.
- The path scope is the union of actual traversed arrival and known exit edges, with partial-edge metres. Reused edges take the maximum traversed length rather than double-counting. `sample_supported_fraction` is the length fraction on OSM edges whose way has quantitative Measured/Official/Observed evidence (a finite numeric bound or a valid sample); it is explicitly **sample support**, not a claim of continuous survey of every traversed metre. `sampled_segments/total_segments` counts those edges. `complete_strong_fraction` separately counts only non-conflicting Measured/Official ways with a positive lower guarantee and complete coverage. Unknown exit geometry supplies no additional certified scope.
- Answer: fits if all path hypotheses meet `fits_min` and the stop meets `door_min`; tight if all meet `tight_min` and the stop meets `door_min`; otherwise no. A missing/conflicted point makes the answer unknown. Existing hard-check failures override the answer to no. A lot without a measured entrance/internal manoeuvre stays unknown. These hypotheses never override an excluded path or open a prohibited stop.
- Confidence starts low. Medium requires quantitative sample support on at least 50% of traversed metres and no decisive width conflict. High positive confidence additionally requires 100% complete strong coverage, every path lower bound at least `fits_min`, the stop lower bound at least `door_min`, strict arrival and Way Out, model-passable dwell flood, affirmative Permitted legality, and a verified walk. Unknown flood/legal coverage, permissive routing or an unsurveyed walk therefore cap positive confidence at medium. `way_out.mode=unknown|none`, a missing arrival, a failed non-legal hard check, a missing width hypothesis or a decisive conflict cap it at low. `manoeuvre_status=unknown` on a topological through route cannot receive high because it is non-strict; both UI and prose say “Chưa rõ đường ra”. An uncertain tight fit is never high under this rubric.
- A cited Prohibited/Restricted rule, a non-conflicting Measured/Official observation whose own upper bound is below the vehicle need (`tight_min` along the path, `door_min` at the stop; a weaker cap cannot borrow the stronger tier’s confidence), or blocked dwell flood overrides to no/high: confidence in the explicit negative, not an access assurance. Restricted pickup remains visible under Q7 only to state the prohibition and citation, with no stopping advice. Other rejected checks remain no/low. Confidence is ordinal evidence adequacy, not a calibrated probability or field-validation claim.
- Positive-confidence comparisons use only monotone width thresholds and vehicle-independent evidence coverage. On the same path/check states a narrower vehicle cannot lose a fits answer or its confidence, and adding consistent same-valued evidence cannot lower confidence. Dedicated randomized and progressive-tier regression fixtures enforce both properties.
- Verdicts name the best available action and confidence instead of blanket missing-evidence wording. Frontend stop rows show estimate/confidence/basis. Unknown manoeuvres and floods are muted. “Được phép” requires affirmative Permitted; Unverified displays “Không thấy quy định cấm đã biết”. Agent/MCP preserve strict verification, actual caveats and all cited rules. Arrival-plan prose is canonically rendered from the current engine result, including in signed follow-up histories; no unconditional cadastral disclaimer is appended.

## D51: Revalidate cached automatic cuts before width fusion (2026-10-17)

- Wire the previously unused `width_samples.assess` into the active evidence path. Reject cached automatic cuts displaced more than 1.5 m from their way, within 5 m of a physical three-arm junction, or within 5 m of a bend over 15°. Retain the rejected cuts and reasons in `sample_quality`; do not query the portal. Unlocated legacy cuts cannot be geometry-rejected. Normalize numeric cache strings before checking geometry; malformed supplied locations remain unresolved/reviewable.
- MAD identifies a lone low cut only when it lies more than `max(0.6 m, 3 × 1.4826 × MAD)` below the median and lacks two independent supporters. It removes eligibility for a confident automatic bottleneck, **not the credible constriction or its conservative upper bound**. Rejecting a number solely because it is narrow would violate D39. Supporters must be within 0.6 m of the narrowest cut and at least 1 m apart; duplicate or unlocated numbers cannot corroborate it. These are uncalibrated modelling thresholds.
- Confident automatic negative width claims require at least two such consistent cuts. A legacy raw-gap CSV row counts as a single unlocated sample and cannot borrow high confidence from Official provenance. A separate cited prohibition, blocked flood, or adequate physical negative keeps its own precedence.
- Preserve the merged product's **Inferred** classification of computed parcel gaps. Official parcel provenance does not turn gap-minus-1 m into a physical clear-width observation. A geometry-checked automatic cap supersedes a generic Inferred road-class prior, which otherwise creates spurious same-tier conflicts or restores an unsupported lower floor. Actual stronger-source conflicts remain reviewable. Empty/rejected surveys retain an unresolved bound rather than a zero-width measurement.

## D52: Sampled width and limiting-segment provenance are explicit (2026-10-17)

- For geometry-checked automatic cuts, keep the strict whole-way lower bound at zero and the sampled bottleneck upper cap at narrowest usable sample +0.3 m. `WidthRange.sampled_estimate` separately exposes the sample point and its ±0.3 m band, source, tier, conflict status, and `guarantees_clearance=false`. It is a sampled bottleneck estimate, not continuous coverage. No sample is installed as decisive clearance or legal lane-count evidence.
- Estimates retain their selected source's actual numeric sample; a missing-coverage interval midpoint or a weaker fused cap must not be relabelled as an Official cut. An unresolved survey may use an explicitly labelled weaker road-class hypothesis for a low-confidence estimate, even when that prior is suppressed from strict width fusion. Fully unresolved width labels say “Width unknown” (English copy updated in D54).
- `estimate.limiting_width` names/links the actual limiting arrival/exit way. `estimate.stop_width` describes the destination/stop independently; the basis states both when different. At the cached Ministop Trần Doãn Khanh case, the door samples are 5.56–5.65 m, its sampled bottleneck band is 5.26–5.86 m, and Cây Điệp's own 3.58 m samples limit the selected route. Automatic geometry remains Inferred, so this is fits/low and unverified on this merged product, not a new clearance assurance.

## D53: Estimate the selected route before public serialization (2026-10-17)

- The merged active engine had discarded route edge IDs before constructing estimate scope, leaving only a 0.01 m stop-edge placeholder. Pass the original arrival and Way Out objects to the estimate. Retain actual partial-edge lengths and strictness internally; remove them only from public route serialization. Repeated traversed edges retain D50's maximum-length union policy. Driving metres sum physical edge lengths; routing preference costs still select the path.
- Missing walking/network projections with no evaluated door now receive an explicit unknown/low estimate. Every verdict therefore has an estimate even when no stop can be generated. None found in an otherwise available cached network remains no/low rather than a neighbourhood-wide impossibility claim.
- These changes do not upgrade strict fit, manoeuvres, flood, stopping permission, pedestrian connectors, or `verified`; walk caps, hard exclusions and returned-stop ranking retain the active product's semantics. Frozen cached stress inputs, the historical/current-HEAD distinction, regression fixtures and results are recorded in `docs/eval/engine-stress.md`.

## D54: English engine output preserves names and evidence semantics (2026-10-17)

- Product-owner decision: generated engine copy is English. Verdicts name the action and confidence, for example “Park on Võ Duy Ninh, 39 m walk — low confidence” and “Can reach the door — medium confidence”. Restricted stopping remains a prohibition/citation, never a stopping recommendation. Fit, exit and flood labels, estimate bases, unverified reasons and source descriptions are English; tier names are Measured, Official, Observed, Declared and Inferred. Numeric formatting uses decimal points.
- `evidence.py` centralizes a cached-description adapter in `ENGLISH_TEXT`, `ENGLISH_PREFIXES` and `ENGLISH_FRAGMENTS`. It handles legacy legal/flood/source descriptions during output serialization. It leaves legal citations verbatim (including the full Luật 36/2024/QH15 and QCVN 41:2024/BGTVT citations), street/alley names, destination labels, identifiers, URLs, raw source material and numerical/enum decisions intact. Rule summaries are translated separately from their citations. Unrecognized free-form historical evidence notes/source titles remain original text for a follow-up dictionary extension; no unknown text is hidden or treated as new evidence. All controlled user-facing literals in `plan.py`, generated width descriptions in `evidence.py`, and existing `width_samples.py`/`parcels.py` copy are English.
- The JSON compatibility key `tier_vi` now carries the English tier label. Existing strict `lo/hi`, coverage/confidence gates and verification meanings do not change. `all_sampled_segments` and `all_sample_supported_fraction` provide the descriptive count including automatic Inferred parcel estimates for the English basis; existing `sampled_segments`/`sample_supported_fraction` retain their Measured/Official/Observed adequacy meaning, so displaying an automatic cut never raises confidence.
