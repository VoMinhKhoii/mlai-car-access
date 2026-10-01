# Research 02: Parking and stopping

Collected 2026-09-28 by a research agent. Tags: [tested] called or downloaded by the agent; [documented] official docs; [reported] news/secondary; [unverified]. Raw Overpass JSON: session scratchpad `parking/`.

## A. Google Maps Platform
- `parking`, `parking_lot` and `parking_garage` (Automotive), plus `park_and_ride`, are Table A types usable in `includedTypes` [documented] https://developers.google.com/maps/documentation/places/web-service/place-types
- `parkingOptions` has 7 booleans: free/paid lot, free/paid street, valet, free/paid garage. It is billed at **Enterprise + Atmosphere** in Place Details, Nearby Search and Text Search; the most expensive field in the FieldMask sets the SKU [documented] https://developers.google.com/maps/documentation/places/web-service/data-fields
- Pricing is global; only India has regional pricing [documented] https://developers.google.com/maps/billing-and-pricing/pricing
  - Nearby Search: Pro $32 per 1k (5k free/month), Enterprise $35, Enterprise + Atmosphere $40 (1k free).
  - Place Details Enterprise + Atmosphere: $25 per 1k (1k free).
  - Street View Static: $7 per 1k (10k free). **Street View metadata is free and unlimited.**
  - Nearby Search returns at most 20 results with no documented pagination, radius up to 50 km, and supports `rankPreference: DISTANCE` [documented].
- Reviews: at most 5 per place. AI review and place summaries are not offered for Vietnam [documented].
- Terms [documented]:
  - A place_id can be stored indefinitely. Latitude/longitude can be cached for up to 30 days.
  - **Places and Routes content may not be used with a non-Google map** (Service Terms §14.2, §19.2); Places UI Kit is exempt (§15.1). https://cloud.google.com/maps-platform/terms/maps-service-terms
  - GMP Terms §3.2.3 forbid saving reviews. Examples of banned uses include indexing objects from Street View imagery and using Places lat/lng as input to point-in-polygon analysis. Using content to train or test ML models is also banned. https://cloud.google.com/maps-platform/terms
- How often `parkingOptions` is filled in for Vietnam: no public data [unverified].
- Street View metadata returns status (OK/ZERO_RESULTS), pano_id, location and capture date, and is "accurate to 50 meters". The imagery parameters `radius` (default 50 m) and `source=outdoor` exist [documented; whether metadata applies them is unverified]. https://developers.google.com/maps/documentation/streetview/metadata
- Routes API has a WALK mode (beta; a warning must be shown to users). TWO_WHEELER covers Vietnam [documented].

## B. OSM via Overpass, 2026-09-28 [tested]

| | HCMC core (10.70–10.86N, 106.60–106.78E) | Hanoi core (20.95–21.09N, 105.75–105.90E) |
|---|---|---|
| amenity=parking | 295 | 409 |
| parking=* | 130: surface 64, underground 47, multi-storey 9, street_side 9 | 191: surface 106, street_side 41, multi-storey 18, lane 8 |
| fee / capacity / name | 27 / 9 / 27 | 45 / 13 / 44 |
| access | 58 (customers 23, private 13) | 123 (private 69) |
| motorcycle_parking | 115 | 113 |
| roads with parking:* / drivable ways | 52 / ~34,100 | 395 / ~18,400 (mostly no_parking/no_stopping) |

- **Whole admin areas:** HCMC has 567 car + 184 motorcycle parking features; Hanoi has 574 + 137.
- **Car vs motorbike:** separated by the amenity tag (`amenity=motorcycle_parking`); `motorcar=*` is almost never used.
- **Signs:** only ~30 traffic_sign nodes per city, including one P.130.
- **Spot check:** Tân Định market has no lot within 300 m. The nearest is 408 m away, unnamed, with unknown access.
- **Completeness:** OSM has ~710 parking features for Hanoi against ~3,000 official points, with almost no attributes.

## C. Rules and official data
- **Law 36/2024/QH15, Art. 18(4)** (in force 2025-01-01) bans both stopping and parking [documented] https://xaydungchinhsach.chinhphu.vn/toan-van-luat-trat-tu-an-toan-giao-thong-duong-bo-119240909105718285.htm
  - on the left side of one-way roads
  - on blind curves or crests
  - on bridges and under overpasses
  - alongside another parked vehicle (double-parking)
  - less than 20 m from a car parked on the opposite side of a narrow street (40 m on roads with one lane each way)
  - on crosswalks
  - at intersections and within 5 m of their edge
  - at passenger pick-up points
  - in front of, and 5 m either side of, the gates of agencies and organizations
  - **where the roadway fits only one motor-vehicle lane**
  - in rail safety zones, or where the car blocks signs or signals
  - on bus lanes, drains, manholes and hydrant spots
- **Art. 18(6):** on urban streets, park on the right side only, with wheels no more than 0.25 m from the curb [documented].
- **QCVN 41:2024 signs:** P.130 no stopping or parking; P.131a no parking; P.131b no parking on odd days; P.131c no parking on even days. They apply until the next intersection unless a plate limits them [reported]. The car fine for parking at P.130/P.131 is 800k–1M VND under Decree 168/2024 [reported] https://vetc.com.vn/cuu-ho/bien-cam-dung-do
- **Hanoi:**
  - About 3,000 parking points; the 2026-07-01 non-stop payment mandate names VETC (Tasco) and ePass (Viettel) [reported] https://vnexpress.net/toan-bo-bai-giu-oto-tai-ha-noi-thu-phi-khong-dung-tu-thang-7-5092848.html
  - Plan 198/KH-UBND (2026-05-22): all car lots cashless non-stop from 2026-07-01; a central parking database; live vacancies published on the iHaNoi and VNeID apps [reported] https://luatvietnam.vn/an-ninh-trat-tu/ke-hoach-198-kh-ubnd-ha-noi-2026-ung-dung-cong-nghe-trong-trong-giu-xe-toan-thanh-pho-435472-d2.html
  - Licensed street parking as of 2025-09-16: 236 locations, 48 operators, 43,858 m². Another 352 locations (43,650 m²) had been licensed by districts before the administrative restructuring [reported] https://tuoitre.vn/plo/ha-noi-de-xuat-tang-tu-15-24-lan-phi-trong-giu-o-to-xe-may-o-long-duong-trong-vanh-dai-1-post907584.html
  - Street eligibility rules (Dec 2024, 234 streets): two-way streets ≥10.5 m wide allow parking on one side, ≥14 m on both; one-way streets need ≥7.5 m; at least 20 m from intersections; peak-hour bans [reported] https://www.vietnamplus.vn/ha-noi-bo-sung-191-tuyen-pho-du-dieu-kien-trong-giu-xe-duoi-long-duong-via-he-post1002789.vnp
  - The low-emission-zone pilot (from 2026-07-01) designates 220 parking points; the list is published only as infographics [reported].
  - iParking: a 17-point pilot was suspended in 2017 [reported]; no open data or API found [unverified].
- **HCMC:**
  - Paid roadside car parking on 20 streets in the former Districts 1, 5 and 10 (operator TNXP).
  - Since 2025-04-15, payment is by RFID through VETC, with a QR fallback, at 25,000 VND per session. The MyParking app was dropped.
  - 2020 to 2024-10: revenue 22.0bn VND against costs of 24.3bn [reported] https://tuoitre.vn/plo/tphcm-trien-khai-loat-giai-phap-de-thu-phi-do-xe-o-to-duoi-long-duong-post845083.html
  - Street names listed by VETC: https://vetc.com.vn/vetc-trien-khai-he-thong-20-bai-gui-xe-khong-tien-mat-dau-tien-tai-thanh-pho-ho-chi-minh-n257.html; no machine-readable list found [unverified].
  - Existing lists use pre-reorganization district names [reported].

## D. VETC/Tasco and others
- The VETC app has a "Bãi đỗ" (parking) tab showing nearby lots, price, hours, **real-time free spaces** and directions (post dated 2026-07-22) [documented by VETC] https://vetc.com.vn/huong-dan-tim-kiem-diem-gui-xe-thanh-toan-dien-tu-tren-ung-dung-vetc%C2%A0-n364.html. VETC publishes its lot lists only as images.
- VETC has ~5M customers, described as ">70%" of cars on the road (2026-08) [reported].
- Electronic toll collection works for entry at Nội Bài, Tân Sơn Nhất, Đà Nẵng, Cát Bi and Phú Bài airports (10,000 VND per stay of up to 10 min, cars under 9 seats). 108 Hospital takes VETC/ePass [reported].
- ePass (Viettel) reports >300 lots in Hanoi and ~500 nationwide [reported by ePass] https://giaothongso.com.vn/tu-1-7-thu-phi-etc-diem-do-xe-tai-ha-noi/

## E. Problem validation
- Hanoi: 1.07M cars and 6.6M motorbikes. Land for parking and other "static traffic" is 0.6% of urban land against a 4% target (CAND, 2024-04-27) [reported] https://cand.vn/Giao-thong/ha-noi-tiep-tuc-cang-thang-diem-trong-giu-xe-oto-i729478/. No HCMC figure found [unverified].
- Drivers use Google Maps (locations but not availability), mall apps and car-dealer blog lists of lots [reported] https://xetv.vn/threads/ung-dung-tim-bai-do-xe-o-to-o-tp-hcm-va-ha-noi-cai-nao-nhanh-nhat.6848/
- Facebook groups and Otofun not checked; the search quota ran out [unverified].

## F. Goong
- docs.goong.io was unreachable from the agent's network, so these points come from Goong's official SDK, which may be out of date [documented via SDK] https://github.com/goong-io/goong-sdk
  - Autocomplete takes input, location, radius, limit, sessiontoken and more_compound. There is **no category filter**.
  - Direction and Distance Matrix take vehicle = car, bike, taxi, truck or hd. There is **no walking mode**.
- Goong says its routing models car-ban hours and banned turns [vendor claim].
- The public OSRM foot router (routing.openstreetmap.de) works in HCMC: Bến Thành→Nguyễn Huệ is a 700 m walk against a 1.38 km drive [tested]. It is a demo server only.

## Agent's implications
1. A rule-based legal-curb layer can be built from street geometry: 5 m intersection buffers, crosswalks, bus stops, the left side of one-way streets, bridges and gates. The single-lane rule makes stopping and parking illegal in most hẻm/ngõ, so "drop-off only" and "can park" need separate evidence.
2. Sign-based bans (P.130/131, odd/even days) are almost missing from open data. Label them "unknown" and show the Street View image and date. Reading signs automatically from Street View appears to be prohibited by Google's terms.
3. Google Places is the richest "this business has parking" source, but it bills at Enterprise + Atmosphere, cannot be drawn on a Goong/Vmap base map, and cannot be intersected with flood polygons.
4. VETC's live-availability data is the strongest Tasco-native parking layer.
5. Walk leg: Routes WALK (only on a Google map) or an OSM-based foot router (OSRM/GraphHopper).

## Test calls needing a key
- `POST https://places.googleapis.com/v1/places:searchNearby`, FieldMask `places.id,places.displayName,places.location,places.primaryType,places.parkingOptions`, body `{"includedTypes":["parking","parking_lot","parking_garage"],"rankPreference":"DISTANCE","maxResultCount":20,"languageCode":"vi","locationRestriction":{"circle":{"center":{"latitude":10.7740,"longitude":106.7035},"radius":800}}}`. The fill rate is the share of results that include `parkingOptions`.
- `https://maps.googleapis.com/maps/api/streetview/metadata?location=10.7740,106.7035&radius=50&source=outdoor&key=KEY`
- `https://rsapi.goong.io/Place/AutoComplete?api_key=KEY&input=bãi đỗ xe ô tô&location=10.7740,106.7035&radius=1&limit=10`

## Open questions
- Can the organizers or Tasco provide VETC parking data (location, price, hours, live spaces) or parking POIs from T-Maps/Vmap?
- Will the base map be Google or Goong/Vmap? That decides which Google content is allowed.
- HCMC or Hanoi? Hanoi has richer policy data; HCMC has 20 paid streets.
- Does Hanoi's Plan 198 database have a public feed?
- Do the current Goong docs offer category search or walking routes?
