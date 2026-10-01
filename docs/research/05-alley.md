# Research 05: Alley access evidence (can a car get in and back out?)

Collected 2026-09-28 by a research agent. Samples, each 2×2 km:
- **HCMC:** 10.786–10.804N, 106.676–106.694E (Phú Nhuận / Q3 / Tân Định)
- **Hanoi:** 20.996–21.014N, 105.812–105.832E (Đống Đa / Thanh Xuân)

Copies of the data and scripts are in `../../data/alley/`. Tags: [tested]; [documented]; [reported]; [unverified]. The agent's web-search quota ran out partway, so some items are [unverified].

## A. OpenStreetMap (Overpass, data 2026-09-28) [tested]
- **Way counts (HCMC / Hanoi):**
  - service 1,544 / 1,264, of which `service=alley` 1,326 / 601
  - residential 418 / 118
  - footway 91 / 312
  - living_street 3 / 0; path 3 / 5; pedestrian 1 / 11
  - unclassified and track: 0 / 0
- **Alley-like ways** (`service=alley`, or name starting Hẻm/Ngõ/Ngách/Kiệt): 92 km in HCMC, 60 km in Hanoi. Share of that length carrying each tag:

  | Tag | HCMC | Hanoi |
  |---|---|---|
  | `motorcar` | 37% | 30% |
  | `motor_vehicle` | 1% | 7% |
  | `width` / `maxwidth` / `est_width` | 0.8% | 1.5% |
  | `access` | 0.1% | 0.5% |
  | Any car signal | 38% | 38% |
  | `noexit` on ways | 0 | 0 |

  - HCMC values by length: `destination` 25.6 km, `no` 7.8 km.
  - Hanoi values: `no` 10.7 km plus `motor_vehicle=no` 3.7 km; `destination` 7.1 km.
- **Who added the car tags:** in HCMC, 63% of car-tagged ways were last edited by accounts named Grab… (GrabVN_*, Grab_Cong; edits 2023–26). In Hanoi it is 11%.
- **Road type is already a rough width class** [documented]. The OSM Vietnam guide defines `residential` as fitting at least two cars, and `service=alley` as "one car or two scooters" (https://wiki.openstreetmap.org/wiki/Vietnam_Mapping_Guide).
- **Naming follows the alley hierarchy:**
  - HCMC: "Hẻm 134/109 Lý Chính Thắng".
  - Hanoi: "Ngõ 164 Phố Vương Thừa Vũ", "Ngách 128/10 …", "Hẻm 426/48/52 Đường Láng", and also the style "Hẻm 28 Ngách 130 Ngõ 162 Khương Trung".
  - 89% of HCMC "Hẻm A/B X" names have a parent "Hẻm A X" in OSM; 94% of Hanoi "Ngách N/M" names have their "Ngõ N".
  - So an HCMC address "12/34/5 Đường X" parses to the chain Hẻm 12 X → Hẻm 12/34 X, and those names match OSM.
- **OSM addresses are sparse and inconsistent:** 523 and 721 address objects per 4 km². For example, '220/68' is paired with street 'Hẻm 220 Lê Văn Sỹ', but '73/12' is paired with 'Hoàng Văn Thụ'.
- **Dead ends are detectable from network shape** (car-legal network, per 4 km²):
  - HCMC: 963 dead ends; branch length median 27 m; 176 longer than 50 m; 17 longer than 100 m.
  - Hanoi: 627 dead ends; median 38 m; 229 longer than 50 m; 47 longer than 100 m.
  - All 159 nodes tagged `noexit=yes` are dead ends, but they cover only about 10% of them.
- **Routers already respect these tags:**
  - Public OSRM car server: all 12 sampled `motorcar=destination` alley midpoints snapped onto the alley. For `motorcar=no`, 8/12 (HCMC) and 7/12 (Hanoi) snapped to another way 5–31 m away [tested].
  - OSRM car profile [documented, source code]: vehicle width 1.9 m; blocks ways tagged `maxwidth`/`width` ≤1.9 m; penalises width ≤3 m and `service=alley`.
  - GraphHopper custom models can filter on `max_width` [documented]. Valhalla has a vehicle width option (car default 1.6 m) [documented].
  - All of this only works where width tags exist, which is about 1% of alleys.
- **Full Vietnam extract:** Geofabrik, 329 MB, updated daily [tested].

## B. Building footprints as a width proxy [tested]
- **Coverage in the 2×2 km samples:**

  | Source | HCMC | Hanoi |
  |---|---|---|
  | Overture 2026-09-23.1 total | 12,185 | 12,241 |
  | – of which Google | 10,315 | 5,950 |
  | – of which Microsoft | 998 | 2,337 |
  | – of which OSM | 872 | 3,954 |
  | Full Google v3 (VIDA GeoParquet, confidence ≥0.65) | 34,791 (median 33 m²) | 26,607 (median 40 m²) |
  | Microsoft raw tile | 3,931 (median 223 m²) | not checked |
  | OSM buildings | 915 | 4,096 |

- **Row houses:** full Google v3 often separates individual row houses (nhà ống). Microsoft merges them into block-sized polygons. Google itself lists "settlements with many contiguous buildings" as a weakness [documented].
- **The width test failed.**
  - 27% (HCMC) and 39% (Hanoi) of alley centreline points fall inside a Google footprint, because of roof overhangs and misalignment.
  - Where a gap could be measured, the median gap between facing buildings was about 7.6–8 m for both `motorcar=no` and `motorcar=destination` alleys. Footprints cannot tell 2–6 m alleys apart.
- **Open Buildings 2.5D Temporal:** 4 m effective resolution from Sentinel-2 [documented], far too coarse.
- **Precedent:** Google Maps in India (Jul 2024) estimates road width with AI from satellite imagery, Street View and "distance between buildings", then shows narrow-road alerts and avoids them in routing, in 8 cities [documented]. No academic literature search was done.

## C. Imagery
- **Esri World Imagery** metadata [tested]:
  - HCMC: WorldView-2, 0.5 m, 2024-12-29.
  - Hanoi: Legion-2, 0.34 m, 2025-06-11.
  - Stated positional accuracy 8.47 m; maximum zoom level 19.
- **Visual check** of zoom-19 crops (agent's own vision inspection) [tested, qualitative]:
  - Narrow hẻm/ngõ show only as shadow lines between roofs, so their width cannot be measured.
  - Parked cars are visible on streets and lots, rarely inside alleys.
  - Obstacles: roofs, awnings and overhangs, trees, building lean, shadows.
- **Mapbox Satellite:** 50 cm global base; zoom 18 at 0.3–0.6 m in some regions; nothing specific on Vietnam [documented].
- **Bing Maps for Enterprise:** retired for free (Basic) accounts; Enterprise until 2028-06-30 [documented].
- **Google satellite maximum zoom** needs an API key. Test: `staticmap?center=10.78877,106.68404&zoom=21&maptype=satellite`, or `MaxZoomService`.
- **Google Street View exists in Vietnam now.**
  - Google's schedule feed lists HCMC capture July–November 2025 and Hanoi February 2026 [tested].
  - Coverage was published in June 2025. It includes Gen-4 motorbikes and walking "trekker" cameras in alleys "where access by cars is not possible" [reported]. So Street View imagery inside an alley does not prove a car can get in.
  - The Street View metadata API is free and uses no quota [documented].
  - Google Maps Platform Terms §3.2.3 forbid bulk-downloading Street View images, building datasets from Maps content, and using it to train, test or validate ML models [documented].
- **KartaView** (open API) [tested]: sparse. The nearby-photos call returned 337 photos from 178 sequences within 1.5 km in HCMC, and 231 photos from 102 sequences in Hanoi, mostly from 2019 and 2025.
- **Mapillary** needs a token. Test: `graph.mapillary.com/images?fields=id,captured_at,computed_geometry&bbox=106.67585,10.786,106.69415,10.804`.
- **Vietnamese street-view products** (Vietmap, Goong): none found [unverified].

## D. Official and planning data
- **HCMC planning portal** (thongtinquyhoach): clicking the map sends `Lat/Lon` to an undocumented endpoint, `https://sqhkt-qlqh.tphcm.gov.vn/computing/930/api/v3.1/a-z/all`. It returns the land parcel polygon and area, the zoning plan, and a "LoGioi" field (road name plus planned right-of-way width, lộ giới) [tested].
  - For 10 parcels beside 5 alleys, no alley lộ giới came back. The only value returned was for a street: Lý Văn Phức, 10 m.
  - The gap between facing parcels does give a legal alley width:
    - Hẻm 53/86 Trần Khánh Dư: 2.25 m
    - Hẻm 71 Nguyễn Công Hoan: 2.65 m
    - Hẻm 134/109 Lý Chính Thắng: 5.2 m (OSM tags it `motorcar=destination`)
  - Parcels were 21–50 m². The portal still uses pre-2025 district/ward units.
  - The page code also references a current ground-elevation layer (read from the code, not called), relevant to the flood pillar.
- **Hanoi planning portal** (quyhoach.hanoi.vn): a map viewer showing raster images only (zoning, detailed plans, Đống Đa parcel maps). No queryable data API found [tested].
- **QĐ 88/2007/QĐ-UBND** (HCMC alley planning) [documented]:
  - Main alley ≥6 m (4.5 m allowed by exception).
  - Branch and dead-end alleys by length: under 25 m → 3.5 m; 25–50 m → 4 m; 50–100 m → 4.5 m; 100–200 m → 5 m; over 200 m → 6 m.
  - Shared passage ≥2 m.
  - Dead ends over 150 m should have a turnaround: triangle with ≥7 m sides, square ≥12 m, circle ≥10 m, or a T-end wider than 3.5 m with 5 m corner radius.
  - Repealed entirely by QĐ 563/QĐ-UBND on 2026-01-26; no replacement found.
  - Lộ giới is planned width, not built width.
- **QCVN 06:2022/BXD (fire safety)** [documented]:
  - Fire-truck road clear width ≥3.5 m (clause 6.2.1.1); clear height ≥4.5 m.
  - A dead end longer than 46 m needs a turnaround (6.2.5). Clause 6.4 set triangle 7 m / square 12 m / circle 10 m / 5×20 m; the 2023 amendment changed it to "must suit local fire vehicles".
  - Single-lane roads need an 8×7 m passing bay at least every 100 m (6.5).
- **Rules banning cars from specific alleys:** [unverified].

## E. Text evidence (listings and reviews)
- **Chợ Tốt / Nhà Tốt public JSON API** (`gateway.chotot.com/v1/public/ad-listing`) [tested]:
  - Fields: `house_type` ("Nhà ngõ, hẻm"); `pty_characteristics`, where 2 = "Hẻm xe hơi" and 3 = "Nhà nở hậu"; lot width and length; street; ward in both old and new-2025 names; lat/lng; title and body.
  - Active listings: HCMC has 8,732 alley-house listings flagged "Hẻm xe hơi". Hanoi has 271 flagged out of 1,219 alley-house listings.
  - Coordinates are deliberately shifted by 0.0008° (about 90 m) and street numbers are usually missing, so matching to a specific alley has to come from the text, e.g. "HẺM 3,5M HUỲNH TẤN PHÁT".
- **batdongsan.com.vn** returned a Cloudflare 403 challenge to curl [tested]. alonhadat and muaban not checked.
- **Google reviews:** the Places API returns at most 5 reviews per place, and the terms forbid copying or saving reviews [documented].
- **Pitfalls for an extraction pipeline:**
  - Sellers exaggerate: "hẻm xe hơi" may mean a car reaches the alley mouth, and widths are often quoted at the entrance.
  - Addresses are vague and listings are duplicated.
  - There are no negative labels.
  - Old and new administrative units have to be normalised.

## F. Routing engines
- **Goong Directions** vehicle options are car, bike, taxi and hd [documented, SDK docs]; it needs a key. Test: `rsapi.goong.io/Direction?origin=10.7897,106.6851&destination=10.78872,106.68404&vehicle=car` versus `vehicle=bike`, then compare how far the last step ends from the destination.
- **Google Routes API** supports `TWO_WHEELER` in Vietnam [documented], so a gap between the DRIVE and TWO_WHEELER routes is a usable signal.
- **Complaints about Google routing cars into narrow hẻm:** [unverified].

## Agent's implications
- The team's hunch holds in part: "someone drove a car there" evidence already exists at scale as OSM `motorcar` tags, largely Grab-curated in HCMC.
- Width in metres is the weak link. It is almost never tagged, and satellite imagery and building footprints cannot recover it for 2–6 m alleys.
- A realistic output is a car-access class with a confidence level and the evidence behind it, not a width in metres.
- Routing a car profile against a foot profile gives the point where the car must stop plus the remaining walking distance, which feeds the parking pillar directly.
- Dead-end topology plus branch length flags alleys where the car would have to reverse out. The QĐ 88 and QCVN turnaround sizes are citable reference thresholds for that.
- Legal constraints: Google content cannot be used to build a dataset or train ML. The planning endpoint is undocumented, and listing sites have ToS and bot protection.
- User confirmations ("I drove in" / "couldn't pass") could be written back to OSM tags. That is the data-update and community-data story the judging asks for.

## Evidence sources ranked for a short hackathon

| Rank | Source | Coverage | Accuracy |
|---|---|---|---|
| 1 | OSM road type + `motorcar`/`motor_vehicle` tags + dead-end topology, run through self-hosted OSRM or GraphHopper | Road type: 100% of mapped alleys; explicit car tag: ~38% of alley length | Moderate to good; not validated against ground truth |
| 2 | Chợ Tốt listing labels plus LLM extraction, matched to the alley chain by name | Thousands of listings in HCMC, hundreds in Hanoi | Weak, positive-only, located to street level |
| 3 | HCMC parcel-gap width from the planning portal (one call per parcel) | HCMC only | Good for legal width; misses encroachments; legal/rate-limit risk |
| 4 | Router disagreement: Goong car vs bike; Google DRIVE vs TWO_WHEELER | Wherever the router has data | Opaque; storage restricted by ToS |
| 5 | Street View for one-off visual checks | HCMC and Hanoi, including alleys | Human or VLM judgement; ToS-limited; presence does not prove car access |
| 6 | Satellite imagery (parked cars; roads ≥5–6 m only) | Full | Poor for hẻm |
| 7 | Building footprints | Partial | Not usable for width |

## Questions only the team or organizers can answer
1. Can Tasco (VETC, T-Maps, Carpla, insurance telematics) provide car GPS traces or trip endpoints? Traces ending inside alleys would be the strongest evidence that a car got in.
2. Is Goong's road network built from OSM, and does its car profile respect `motorcar` tags? Do Goong or T-Maps expose road-width or road-class attributes?
3. Which city? HCMC has richer car tags and the queryable parcel data. Hanoi has better OSM building coverage and more long dead ends.
4. Can the organizers provide alley lộ giới or cadastral data, or fire-police lists of alleys fire trucks can't reach? What is the replacement for QĐ 88?
5. Is scraping listings or calling government portals allowed for the demo? Is Google Maps Platform in scope?
6. Which car models should be supported? Their width including mirrors sets the pass/fail thresholds.
