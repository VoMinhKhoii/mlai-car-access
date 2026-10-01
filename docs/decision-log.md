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
- **What's checked:** the route in, the Stop Point and the Way Out, across the whole window.
- **Drivers:** the tide forecast (daily bulletin, peak hours) and rain now plus the next few hours (gauges, radar).
- **History as a prior:** it says *which* streets flood at a given tide or rain level. The window says *whether* that happens during the stay.





## Q13: Flood depth vs vehicle (2026-09-28)

- **Depth Range vs Safe Water Depth.** Each segment gets a Depth Range for the Dwell Window, from tide level, rain intensity and street history. Compared with the car's Safe Water Depth:
  - passable: the whole range is below the limit
  - risky: the range straddles the limit; treated as Unverified
  - blocked: the whole range is above the limit

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
