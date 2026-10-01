# Data pipelines

Two offline pipelines that produce the precomputed layers in `data/processed/`. Raw downloads are cached in
`data/raw/` (gitignored), so re-runs are offline and polite.

## Setup

```bash
python3.11 -m venv pipelines/.venv
pipelines/.venv/bin/pip install pdfplumber requests shapely
```

All network calls send a descriptive User-Agent. Nominatim is rate-limited to 1 request per second. Chợ Tốt is
fetched in pages of 20 with 1.5 s between calls and a cap of 1,500 listings. Overpass uses the kumi mirror and
falls back to the maps.mail.ru mirror when kumi is saturated.

## Pipeline 1: VETC parking (`vetc_parking.py`)

```bash
pipelines/.venv/bin/python pipelines/vetc_parking.py
```

**Sources**
- VETC lot lists (PDF):
  - south: `…/Tong hop bai do 2026 - MIEN NAM.pdf`, 32 rows, 26 in HCMC
  - north: `…MIEN BAC.pdf`, 277 rows, none in HCMC
  - There is no central-region ("MIEN TRUNG") file; that URL returns 404.
- VETC article listing the 20 roadside streets (Q1 ×12, Q5 ×3, Q10 ×5). Their segment notes (e.g. "Đường Lê Lai - 200m")
  come from south-PDF rows 6–25.

**Outputs**
- `data/processed/vetc_lots_hcmc.geojson`: one Point per HCMC PDF row.
  - Properties: `name`, `address`, `vehicle` (car|motorbike|both), `lot_type` (open|closed|closed_building), `source_url`, `geocoder`, `geocode_confidence`, plus `roadside`, `operator`, `district_published`, `pdf_row`, `geocode_level`, `geocode_query` and `geocode_label`.
  - A row that could not be located has `geometry: null` and confidence 0.
- `data/processed/vetc_street_parking_hcmc.geojson`: LineString features.
  - Properties: `street`, `segment_note`, `fee_note`, `source_url`, plus `published_length_m`, `osm_way_ids` and `geometry_note`.
  - Geometry is the OSM street inside the named district. VETC publishes the length of the paid segment, not where it is, so the whole in-district street is drawn.

**Geocoding and swapping in Goong**
- `geocode.py` defines `Geocoder.geocode(query, viewbox) -> list[Candidate]`.
- `get_geocoder()` returns `GoongGeocoder` (`rsapi.goong.io/v2/geocode?address=…&api_key=…`) when `GOONG_API_KEY` is set in `.env.local` or the environment. Otherwise it returns `NominatimGeocoder`.
- The Goong class is untested because no key was available.

Old district names ("Quận 1") no longer exist in OSM after the 2025 merger, and Nominatim returns wrong streets for them. They are therefore turned into bounded viewboxes. A candidate is accepted only if its label contains the expected name.

Confidence levels:

| Confidence | Meaning |
|---|---|
| 0.9 | Named POI or building |
| 0.7 | Parent complex only |
| 0.6 | Nearby POI |
| 0.5 | Street-level |
| 0.4 | Midpoint of the OSM street, used when Nominatim fails |
| 0.0 | Not found |

## Pipeline 2: Chợ Tốt listings → Declared evidence (`chotot_listings.py`)

```bash
pipelines/.venv/bin/python pipelines/chotot_listings.py            # uses cached pages
pipelines/.venv/bin/python pipelines/chotot_listings.py --refresh  # re-download
pipelines/.venv/bin/python -m unittest pipelines/test_extract_regex.py
```

1. **Fetch.** `gateway.chotot.com/v1/public/ad-listing` with `cg=1020`, `house_type=3` ("Nhà ngõ, hẻm"), in this order until the cap:
   - Bình Thạnh sale (`area_v2=13109`)
   - Bình Thạnh rent
   - Phú Nhuận sale (`13111`)
   - Quận 1 sale (`13096`)

   The listing endpoint already carries the full body, so the per-ad detail endpoint, which also exposes phone numbers, is never called. Exact re-posts are dropped. Raw pages are kept in `data/raw/chotot/`.
2. **Extract** with regex-v1 (`extract_regex.py`), on accent-folded text:
   - `width_m` (+ `width_at_mouth`, `width_text`, `width_mentions_m`)
   - `access_claim`: the most restrictive claim wins, and "cách/gần hẻm xe hơi" is ignored
   - `car_to_door`
   - `through`
   - `alley_chain`: "123/45 X" → `["Hẻm 123 X", "Hẻm 123/45 X"]`, with an OSM street-name gazetteer plus common abbreviations (XVNT, ĐBP, NHC, CMT8…)

   When the text makes no access claim but Chợ Tốt's structured flag `pty_characteristics ∋ 2` ("Hẻm xe hơi") is set, `access_claim = "xe_hoi"` with `access_source = "chotot_flag"`.
3. **Match** to OSM alley-like ways (named Hẻm/Kiệt/Ngõ, `service=alley` or `living_street`) fetched once for the demo bbox ∪ listing bbox + 300 m:
   - `alley_chain`: the deepest chain level whose name exists in OSM, within 1 km
   - `alley_chain_parent`: only a parent level exists
   - `nearest_on_street`: the nearest alley named "… <listed street>" within 120 m of the listing coordinate
   - otherwise `unmatched`

**Caveat on `nearest_on_street`:** Chợ Tốt coordinates are shifted by about 90 m, and most are street- or ward-level points shared by many listings (1,498 listings sit on only 347 distinct coordinates). When `coord_shared_by > 1`, a proximity match only says "an alley on this street". Treat only the `alley_chain*` methods as alley-level evidence.

Output: `data/processed/listings_evidence_binhthanh.json`. All rows carry `extractor: "regex-v1"` and `evidence_tier: "Declared"`. Per decision-log Q10, a listing width is a **maximum** on the Width Range (it is quoted at the mouth), and "hẻm xe máy" is a maximum. The backend decides how to turn these into bounds; this file only records the claim.

## Where an LLM extractor fits (decision-log D22.1)

regex-v1 is the deterministic baseline and the fallback when no key exists. With an LLM key (Gemini via `GEMINI_API_KEY`, or OpenAI via `OPENAI_API_KEY`), an `extract_llm.py` would expose the same `extract(text, listing_street, gazetteer) -> dict` and set `extractor: "llm-<model>-v1"`. The field schema stays the same. The LLM should add:
- a quoted evidence span for every field, so a reviewer can see the exact words;
- disambiguation that regex cannot do reliably: which alley a width belongs to (front vs. main vs. side alley), distance vs. width ("HXH 10m ra mặt tiền"), and a nearby car alley vs. the house's own alley;
- addresses written in prose ("hẻm đối diện chợ Bà Chiểu").

**Review gate** (JEV states, from D22): every LLM row is compared with regex-v1 on the same text and gets a `review_state`.
- `ACCEPT`: every quoted span is found verbatim in the listing, and the fields agree with regex-v1 where both extracted a value (width within 0.25 m, same access class, same through/dead-end).
- `REVIEW`: a span is not found verbatim, LLM and regex disagree, a value is out of range (width < 1 m or > 15 m), or the text holds two conflicting claims (e.g. "hẻm xe máy" and "hẻm xe hơi").
- `INSUFFICIENT_INFORMATION`: the text makes no access claim at all. The model must be prompted to return this rather than guess.

Only `ACCEPT` rows become Declared evidence automatically. `REVIEW` rows wait for a human, and `INSUFFICIENT_INFORMATION` rows are dropped.
