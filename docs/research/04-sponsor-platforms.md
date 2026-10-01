# Research 04: What Goong, Tasco/VETC and the MLAI hackathon provide

Collected 2026-09-28 by a research agent without API keys. Tags: [tested]; [documented]; [reported]; [unverified].

## Headlines
- **VETC vehicle import:** the demo cannot pull a driver's vehicle from VETC for real. VETC has no public API or "Login with VETC" for outside apps; use a mocked consent flow.
- **Tasco brief:** the official brief lists per-vehicle routing, parking suggestions and flood/tidal detection as example ideas, so our idea is on-brief.
- **Goong coverage:** Goong knows alleys (hẻm/ngõ) as named places but publishes nothing on alley width or car restrictions in narrow alleys.

## A. Goong (Công ty CP Công nghệ và Dịch vụ IMAP)

**Docs.** docs.goong.io is dead ("Site not found") [tested]. Current docs: https://help.goong.io (API v1 and v2) [tested].

**REST APIs** (rsapi.goong.io, responses shaped like Google's) [documented]:
- **Directions, `/v2/direction`:**
  - Parameters: origin, destination (`;` separates extra stops), vehicle, alternatives.
  - Each step gives an instruction naming the road, a turn type, geometry, distance and duration. A `warnings` array flags restricted, banned or toll segments.
  - **It returns no road class and no width, and has no "avoid" parameter.**
  - Vehicle values: v1 car, bike, taxi, truck, hd (ride-hailing); v2 page cut off after "car, bike"; the overview page also claims walking. goong-sdk additionally accepts `type=fastest|shortest`.
  - https://help.goong.io/kb/rest-api-v2/directions-rest-api-v2/directions-v2/
- **Distance Matrix, `/v2/distancematrix`:** car, bike, motorcycle, truck.
- **Trip, `/v2/trip`:** multi-stop route optimisation. Its response uses OSRM's field `weight_name:"routability"`, so the routing engine is probably OSRM [unverified inference].
- **Geocoding and places:**
  - `/v2/geocode`: forward, reverse and lookup by place_id. `has_vnid` adds official admin-unit codes.
  - `/v2/geocode/street`: turns a coordinate into a street name plus the street's line geometry.
  - `/v2/place/autocomplete`: takes location, radius and `origin`; `origin` adds a distance to each result.
  - `/v2/place/detail`: name, address, location, types and a URL. No photos, reviews or opening hours documented.
  - `/v2/place/children`: gates and pick-up points inside a larger place.
- **Place types include `alley`.** "Ngõ 298 Ngọc Lâm" comes back typed `alley`; other types are house_number, building and site.
- **No category or "nearby" search**, so no direct "parking near X" query.
- **Post-merger addresses:** v2 returns the new admin units. `has_deprecated_administrative_unit=true` adds the old district and commune.
- **Speed limit:** `speedlimit.goong.io/api/v1/speedlimit` (lat/lon, optional bearing), available by contacting sales.

**Car restrictions.** Goong's marketing says its routing handles car-ban hours, one-way-by-time rules and no-turn junctions [documented]. Nothing published about alley width; no community reports either way [unverified].

**Map styles and tiles:**
- Styles: goong_map_web, goong_map_highlight and goong_satellite, plus dark and light (five in total). All return 403 without a key [tested]. The map key and the REST API key are separate keys.
- A public 2022 copy of the goong_map_web style (https://github.com/minhanh29/optimal-meeting-point/blob/main/goong_map_web.json) [tested]:
  - Road classes run motorway down to street, service, path and pedestrian, with road/bridge/tunnel and one-way fields.
  - **No alley class and no building layer.**
- 2026 additions: 3D buildings nationwide; elevation tiles at `dem.goong.io/{z}/{x}/{y}.png` (terrarium encoding, up to zoom 15) [documented]. Third-party code reads a `VN_Building` layer with a height field [reported].

**SDKs.** Goong now recommends MapLibre or Mapbox GL with Goong styles, on web and mobile [documented]. The npm packages date from 2021–22 [tested]: goong-js (a Mapbox GL v1 fork), goong-map-react (a react-map-gl fork) and goong-sdk.

**Not offered.** Traffic, flood data, parking data and street-level imagery.

**Pricing** (USD per 1,000 requests): directions and matrix 2.50, map load 3.00, autocomplete 1.40, place detail 7.00, forward geocode 3.50. https://goong.io/bang-gia/
- Signup gives a one-time $100 credit and a free tier of 30k requests/month.
- The account is disabled automatically once unbilled usage passes 25% of the balance.
- **Since April 2026, new accounts must be activated by phoning Goong support** [documented].

**Terms.** The only terms page (https://goong.io/dieu-khoan/) is a licence for Goong's navigation app. It says nothing about caching API results or overlaying other data.

## B. Tasco

**VMAP / "T Maps" app.** iOS release 2026-05-17, now v1.5.0. The Android listing shows 100+ installs, and the app calls itself "in testing" [tested].
- Release notes list [documented]:
  - voice navigation, speed and camera alerts, traffic, weather and planning-map layers, HD map;
  - crowdsourced place edits with photos, opening hours and a leaderboard;
  - **sign-in with a VETC account**.
- Its privacy policy names MapLibre, OpenStreetMap and Tasco-run search and routing services. **It does not mention Goong** (https://tasco-tmaps.web.app/chinh-sach-bao-mat.html).
- No public API found.

**Tasco and Goong.** The track sponsor is listed as "Tasco & Goong" [documented]. No ownership or investment link found, and Goong's blog has no Tasco posts [tested].

**Ecosystem** [reported, https://www.nguoiduatin.vn/he-sinh-thai-cua-tasco-lam-an-ra-sao-204260421012515185.htm]:
- VETC: 4.3M app users, about 75% of electronic toll collection.
- Tasco Auto: 220+ locations (showrooms plus Carpla), brands including Geely, Lynk & Co and Volvo.
- Tasco Insurance: 7th largest in motor insurance.
- Roadside rescue: 300+ trucks, 24/7.
- 2026 plan: AI, digital maps and a "Tasco Mobility" platform.

**VETC e-parking.** Cashless payment at 400+ lots, 300+ of them in Hanoi. Entry and exit use windshield RFID tags and plate cameras; fees are charged in 60-minute blocks [documented, https://vetc.com.vn/hoi-dap-ve-giai-phap-gui-xe-thanh-toan-dien-tu-vetc-n365.html].
- VETC publishes PDF lists: about 277 lots in the north and 32 in the south [tested, https://vetc.com.vn/upload_images/files/Tong%20hop%20bai%20do%202026%20-%20MIEN%20BAC.pdf].
- Each row has an address (e.g. "Hẻm 51 Thành Thái – 320m"), open or closed lot, and car or motorbike.
- **No coordinates**; addresses would need geocoding.

## C. MLAI Hackathon 2026 [documented]
- Run by the southern AI university network (Mạng lưới AI), hosted by HCMUT. 891 participants on Devpost. Tracks: Tasco, VNG, TMA. https://mlai-hackathon.devpost.com/
- **Demo Day is 2026-10-17: an 8-hour onsite build at HUTECH (HCMC).**
- **Tasco brief** (https://docs.google.com/document/d/11fRaBedWrh4XwWld9_dqoMTgj-lNi88Buzr5y3i0QOE/edit):
  - Example ideas include per-vehicle routing, parking suggestions and flood/tidal detection.
  - Mock data standing in for government datasets is explicitly allowed.
  - Resources: Codex and Goong credits, plus "organizer-provided data and APIs" that are not listed anywhere.
  - Prizes include "Best Use of Goong", worth $2,000 in Goong credit.
  - A workshop on "GIS & Tasco data" is part of the programme.

## D. Can the demo pull a driver's vehicle from VETC?
1. **Public or partner API, SDK, "Login with VETC", mini-app platform: none found.**
   - VETC's sitemap (444 pages) has no developer docs, and robots.txt blocks `/api/` [tested].
   - VETC sign-in exists only inside Tasco's own VMAP app [documented].
   - Public certificate logs show dev-/uat-car-sso.vetc.com.vn, which looks like an unreleased sign-on service [tested].
   - Partner links (parking operators, fuel, banks, insurers) are private business deals.
2. **What a VETC account holds per vehicle:**
   - Signup collects plate, vehicle type, chassis and engine numbers, payload and seat count [documented].
   - The app lists each vehicle with its RFID tag.
   - The privacy policy (https://vetc.com.vn/chinh-sach-bao-ve-du-lieu-ca-nhan-vetc-n382.html) says VETC logs vehicle location at toll stations and may share data with its parent company and partners.
   - **Make, model and dimensions are not explicit fields** [unverified].
3. **Public lookup by plate:**
   - The Vietnam Register lookup needs plate + inspection sticker number + captcha [tested, https://app.vr.org.vn/ptpublic/].
   - Traffic-police lookups need plate + chassis number or vehicle type, plus a verified (level-2) VNeTraffic login [tested, https://csgt.bocongan.gov.vn/tra-cuu-dang-kiem].
   - No anonymous plate-to-model lookup.
4. **Personal data law:**
   - Decree 13/2023 classes a plate number as basic personal data and location from positioning services as sensitive [documented, https://datafiles.chinhphu.vn/cpp/files/vbpq/2023/4/13nd.signed.pdf].
   - The Personal Data Protection Law 91/2025 and Decree 356/2025 have applied since 2026-01-01 [reported].

**Verdict:** real VETC integration within the hackathon is not possible unless the organizers supply a VETC sandbox. A credible mocked flow:
1. "Đăng nhập VETC" button.
2. Consent screen listing what is shared: vehicle list, masked plate, type and seats.
3. The app receives e.g. "30A-***.12 · Fortuner · 7 chỗ".
4. Our own spec table maps the model to width, length, turning radius and wading depth.
5. The user confirms. Fallback: a manual make/model picker.

## Agent's implications
- **Access:** Goong knows where alleys are and their shape, but not how wide they are, so the evidence-based width layer is ours to build. Comparing Goong's car route with its bike route into the same alley is a cheap signal.
- **Flood:** Goong's elevation tiles and satellite imagery give terrain context; flood evidence must come from other sources.
- **Parking:** geocoding VETC's published lot lists with Goong gives a sponsor-native parking layer.
- **Budget:** use the v2 endpoints. $100 of credit covers about 40k direction calls, so cache results, keeping in mind the caching terms are unclear.

## Test calls to run once we have keys
- `tiles.goong.io/sources/goong.json?api_key=MAPKEY`: its `vector_layers` section lists every tile attribute, which shows whether road width or lanes exist.
- `/v2/direction` with `vehicle=car` and then `vehicle=bike` into a known narrow hẻm, comparing where each route ends.
- `/v2/place/autocomplete?input=bãi đỗ xe&location=…&radius=1`: tests keyword-based parking search.

## Open questions for the organizers
1. What are the "organizer-provided data and APIs"? A VMAP API or tiles, a VETC sandbox, traffic or weather feeds?
2. How much Goong credit does each team get, which key types, and how fast can accounts be activated?
3. Does Goong's car routing exclude narrow hẻm? Can Goong share road width, lane or class attributes?
4. Should the demo render maps with VMAP or with Goong?
5. What do Goong's terms allow for caching results and overlaying our data?
6. Can Tasco share VETC lot coordinates or occupancy, aggregated flood or hydrolock insurance claims, or rescue locations?
7. Are the "Tasco data" files from the workshop available to teams?

## Tested with keys (2026-09-28)
- **Style and tiles:** `goong_map_web` loads. Sources `base` and `composite` (`goong.json`). The road layer `streets` has only `class`, `layer`, `oneway`, `structure`, with **no width or lane attributes**. `streets_label` has `st_name`.
- **Autocomplete v2** returns alleys with new ward names, e.g. "Hẻm 220 Xô Viết Nghệ Tĩnh, Thạnh Mỹ Tây, Hồ Chí Minh".
- **Place detail v2** returns `formatted_address` like "Xô Viết Nghệ Tĩnh/Hẻm 328 Tổ 56, Khu phố 3, Thạnh Mỹ Tây", plus `geometry.location` and `compound`.
- **Car vs bike Direction v2 are identical** into Hẻm 328 Xô Viết Nghệ Tĩnh:
  - Both are 268 m via Hẻm 378 → Hẻm 306.
  - OSM tags this alley `motorcar=no`, and a VF 5 can't open its doors there.
  - Into Hẻm 220/9, both are 1,521 m via Hẻm 220.
  - So **Goong's car routing does not model alley width**. It sends cars wherever bikes go, which is the gap Vào Được fills. It also means the car/bike-disagreement signal (evidence source 4) is empty for Goong.
