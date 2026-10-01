# Vào Được (working name): team brief

*MLAI Hackathon 2026 · Tasco & Goong track · Demo Day 17/10 at HUTECH*

## One line

**Xe bạn vào được, và ra được, không?** A T-Maps layer that answers, for *your* car, whether it can reach an address in HCMC's alley network and get back out, given alley width, the tide and rain during your stay, and stopping law. If it can't, it says where to stop and how far to walk.

## The problem

- **Maps draw hẻm as lines.** 85% of HCMC residents live on hẻm. Maps show them as thin lines, with no width, no dead ends and no turnaround. Google Maps routes cars into alleys "chỉ vừa thân xe" (Thanh Niên, 3/2026). Its narrow-road detection exists only in 8 Indian cities.
- **Car ownership is exploding in cities built for motorbikes.** 7.1M cars nationwide, 1.4M in HCMC, and +16% new registrations in 2026. Public parking covers about 10% of demand. New drivers know every alley, but only from a motorbike.
- **Floods trap cars, and insurers don't pay.** HCMC had more than 75 days above tide alarm level 1 in 2025. Engine water damage (*thủy kích*) is excluded from standard car insurance, and the add-on pays nothing if you restarted the engine.
- **Ride-hailing loses trips at the alley mouth.** In one VOZ thread, GrabCar drivers cancelled at the alley entrance in about 5 of 10 bookings, although the alley fit two cars.

## Who it's for

| Persona | Stop Intent | Their question |
|---|---|---|
| **Private Driver** (primary), often a new car owner | Park (*đỗ*) | Can I get in? If not, where do I leave the car, and how far do I walk? |
| **Ride-hailing Driver** (primary) | Pickup/Drop-off (*dừng*) | Where can I stop for the passenger, and can I get out without reversing 50 m? |
| Delivery Driver (secondary) | Park / unload | Same engine, bigger vehicle |
| Emergency Vehicle (deferred; disabled in UI) | – | Fire-truck access (Hanoi Decision 2613 lists 7,955 unreachable alleys) |

## The answer: an Arrival Plan

For one destination, one vehicle and one Stop Intent:

- A **Verdict** headline: to the door / stop nearby / not enough evidence / no suitable stop.
- **Up to 3 ranked Stop Points**, each passing every Hard Check:
  1. **Get in:** a route that uses only alleys this car fits (the Fit Network).
  2. **Get out:** drive through, turn around, or reverse ≤ 30 m.
  3. **Flood:** the route in at arrival, the stop across the stay, the way out at departure, each against this car's Safe Water Depth.
  4. **Stop Legality:** Law 36/2024 Art. 18, signs, and local lists, **always shown with the citation, never as advice**.
  5. **Walk Leg:** under 400 m for Park, 150 m for Pickup (placeholders).
- **Ranking:** filter, then rank by walk time. Unverified options rank last and show grey: "no record ≠ no risk".
- **When the tide traps the car:** *"rời trước 17:15 hoặc ở lại tới sau 19:15"* (leave before 17:15 or stay until after 19:15).

## Why it's vehicle-specific

The same alley is green for a VF 3 and grey or red for a Fortuner, and the same flooded street is passable for a Fortuner (350 mm) and a trap for a Vios (133 mm). Drivers pick a **Size Class** (worst case in the class) or an exact **Vehicle Model** (34 popular VN models with published specs), or link their **VETC** account (mocked; no public API).

## Data: evidence, not guesses

Every alley has a **Width Range** (metres) shown with a familiar label: *hẻm xe máy / ba gác / xe hơi / ô tô tránh*. Sources are combined by **Evidence Tier**: the strongest sets the range, and weaker tiers can only narrow it.

| Tier | Sources we already have |
|---|---|
| Measured | Team tape-measure field trip (Bình Thạnh strip), driver photos with a reference object |
| Official | Land-parcel gaps from the HCMC planning portal; fire-truck no-access lists (HCMC 4582/2026) |
| Observed | OSM car tags on 37% of alley length (mostly Grab's mappers); after-arrival confirmations; later T-Maps GPS traces |
| Declared | 1,498 Chợ Tốt listings in Bình Thạnh ("hẻm xe hơi", "hẻm 4m", "hẻm thông/cụt") → AI extraction |
| Inferred | OSM road class; AI on imagery; router disagreement |

Flood data:
- **IRD Historical flood DB HCMC 2002–2026:** 425 records, 45 in the demo strip.
- **Đài KTTV Nam Bộ daily tide bulletin:** alarm levels and peak hours.
- **Rain:** vrain gauges and radar.
- **Public traffic cameras.**

Parking data:
- **VETC's own lot list:** 28 HCMC lots, geocoded.
- **VETC-paid roadside streets.**
- **OSM car parks.**

## AI, each piece behind a flag

1. **Listings → Evidence:** extraction from Chợ Tốt text; regex now, LLM-ready.
2. **Flood prior:** per-street susceptibility from IRD against tide and rain.
3. **Text → Stop Rules / flood reports:** through Trí's review gate, ACCEPT / REVIEW / INSUFFICIENT_INFORMATION.
4. **Driver photos → sign / width / depth:** vision model.
5. **Traffic cameras → flood now:** vision model.

The model extracts; deterministic rules decide. Every answer traces back to its sources.

## Why Tasco (business model: Tasco-native only)

Free inside **T-Maps**, with VETC login. Revenue flows through Tasco's own businesses:
1. **VETC parking:** VETC already processes payment for HCMC's paid roadside parking and one of Hanoi's two e-parking rails. We route cars to the lots they pay at.
2. **Tasco Insurance** (top-7 motor): fewer thủy kích claims, plus a flood add-on offered at the moment of risk.
3. **VETC rescue** (300+ trucks, 24/7): one tap when a car does get stuck.

Data flywheel: every T-Maps arrival becomes Observed evidence ("vào được / chật / không vào được"). At scale, consented GPS traces tell us which alleys cars actually use.

## Demo script (5 minutes)

1. **The problem (30 s):** a Google Maps-style route into Hẻm 220/9 Xô Viết Nghệ Tĩnh.
2. **Vios, park, 16:30, 2 h:** the tide peak at 18:10 (1.66 m, above alarm level 3) floods the way out. The Vios gets "rời trước 17:15 hoặc sau 19:15". Tap the tide chart to move the time.
3. **Switch to Fortuner** (exact model, 350 mm): the door works. Same alley, different car, different answer.
4. **Ride-hailing pickup at Hẻm 328** (tagged no cars): the door is ruled out (no room to open doors), so the pickup is at Xô Viết Nghệ Tĩnh, 109 m away. Show the legality panel with the law citation.
5. **Evidence drawer:** tap an alley to see its tiers (OSM, listing, measured) and IRD flood history. Report a funeral tent and watch the plan reroute.
6. **AI flags:** switch listings extraction off and on to show its effect.
7. **Tasco slide:** VETC parking, insurance, rescue, and the T-Maps flywheel.

## Known gaps (honest list)

- Width evidence is thin until the **field trip** fills `data/field/measurements.csv`. Today most alleys are Unverified (grey).
- The tide curve is modelled from bulletin peaks; highs and lows between peaks are interpolated.
- The one-way-street side rule and sign data (P.130/131) are almost absent from open data.
- Goong keys are pending: search uses OSM/Nominatim and the base map is CARTO until then.
- The VETC login, live free-space counts and GPS traces are mocked and labelled "mô phỏng".
- Interior alley bends aren't modelled; turning radii come from manufacturers and the reference point is unspecified.

## Next steps

1. **Field trip:** measure 20–30 alleys in the Bình Thạnh strip (with photos), fill the CSV, and re-run.
2. **Goong keys:** turn on Goong tiles, search and the Standard Route, and test Goong car vs bike routing into known narrow alleys.
3. **LLM key:** turn on the text, photo and camera AI features for the live demo.
4. **Pitch deck** from this brief, iterating on look and business.
