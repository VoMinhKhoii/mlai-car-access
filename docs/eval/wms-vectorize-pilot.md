# TNMT rendered-cadastre width pilot — stopped at terms gate

Reviewed 17 October 2026 (Asia/Ho_Chi_Minh). **NO-GO for this run: Step 0 was not cleared.** Public WMS discovery is available, but permission for the proposed automated raster acquisition and derived parcel-gap research was not established for the Bình Thạnh layer. No GetMap or WMTS tiles were requested. Technical accuracy remains **untested**, not disproved.

This follows the requested instruction to stop if the gate fails. No pilot box was acquired, no raster was vectorized, and no engine integration, commit, Gemini call, account use or permission request was made. There were zero requests to the throttled planning point endpoint and zero requests to the ArcGIS FeatureServer.

## Terms and metadata evidence

### Public WMS: access advertised, dataset permission unresolved

[Live WMS 1.3.0 GetCapabilities](https://geodata-stnmt.tphcm.gov.vn/geoserver/ows?service=WMS&version=1.3.0&request=GetCapabilities), fetched successfully on this run, contains these exact service fields:

```xml
<Fees>NONE</Fees>
<AccessConstraints>NONE</AccessConstraints>
```

It advertises GetMap with PNG output and the parcel-only layer `tnmt:ranhthua_binhthanh`, with default style `default-style-tnmt:ranhthua_binhthanh`. Its geographic extent is 106.68382545715697–106.75151966598428 E, 10.785361283548115–10.839164476316993 N. This establishes advertised anonymous map-service access; no image request was needed to check the declaration. The service contact is the generic GeoServer example contact, so the global `NONE` fields are insufficient to resolve separate dataset conditions.

The district layer has an empty abstract and no MetadataURL in the inspected layer element. A [GeoNetwork search for its exact service name](https://geoportal-stnmt.tphcm.gov.vn/geonetwork/srv/search?any=ranhthua_binhthanh) returned zero records. The [Bình Thạnh catalogue search](https://geoportal-stnmt.tphcm.gov.vn/geonetwork/srv/search?any=B%C3%ACnh%20Th%E1%BA%A1nh) returned 96 results, but its first page did not identify the district parcel layer's rights record. This is a bounded search result, not proof that no such record exists.

The [public cadastral GeoNetwork record for Bến Nghé, identifier 246a5939-530d-47e7-84b4-99d686e73811](https://geoportal-stnmt.tphcm.gov.vn/geonetwork/srv/api/records/246a5939-530d-47e7-84b4-99d686e73811), linked by the [cadastral catalogue search](https://geoportal-stnmt.tphcm.gov.vn/geonetwork/srv/search?any=ranh%20th%E1%BB%ADa), was read in full. Both Access constraints and Use constraints say **“Copyright”**. Its Other constraints include these exact excerpts:

> Dữ liệu này được khai thác và sử dụng miễn phí.

> phải thực hiện nghĩa vụ tài chính theo quy định

The complete intervening sentence, preserved in the cached original, applies the financial obligation to commercial applications and projects, works and tasks using the data. The record also describes temporary reference use for developing other data/applications and disclaims legal value for land-management decisions. This supports some reuse, but does not settle the conditions for this research project or for automated raster reconstruction. **Bến Nghé is in Quận 1; its terms are contextual evidence, not a licence for Bình Thạnh.** Neither a research exemption from the financial condition nor fulfilment of that condition was established.

The inspected GeoPortal catalogue and record pages did not expose a separate general terms-of-use link; their About link points to GeoNetwork software. Absence of a visible prohibition is not affirmative clearance of the unresolved dataset conditions. No conclusion that all automated requests are prohibited is made.

### HCMC open-data terms: restrictive, with uncertain cross-site scope

The [city open-data terms](https://opendata.hochiminhcity.gov.vn/dieu-khoan-su-dung) returned HTTP 200. In the intellectual-property section, exact excerpts include **“sao chép, tái tạo, phân phối”** and **“sự đồng ý và cho phép bằng văn bản”**. The provision requires the owner's written consent for copying/reproduction/distribution; the following provision also requires written approval for third-party cooperative use. A later section restricts download/sharing services to supplied accounts. No applicable research exception or dataset-specific override was established.

These are the published terms on the city open-data website, whose text describes its integrated base-map sharing system. **Their contractual applicability to the separately hosted TNMT service was not established.** They are not represented here as an automatic citywide prohibition. Together with the unresolved TNMT dataset conditions, they prevent a positive answer to the user's strict permission gate; public accessibility alone does not clear it.

### Robots

Robots was checked before direct retrieval on each host:

- [GeoPortal robots.txt](https://geoportal-stnmt.tphcm.gov.vn/robots.txt): HTTP 404.
- [GeoData/WMS robots.txt](https://geodata-stnmt.tphcm.gov.vn/robots.txt): HTTP 404.
- [City open-data robots.txt](https://opendata.hochiminhcity.gov.vn/robots.txt): HTTP 404.

No published robots directives were returned at those URLs. No robots restriction was bypassed; a missing robots file is not a reuse licence. Normal TLS verification was retained, redirects were not followed automatically, and no authentication or limit workaround was attempted.

## Data date

The live capabilities' city aggregate `tnmt:v_ranhthua_TPHCM` says exactly **“Dữ liệu được cập nhật đến năm 2010”**: updated through 2010. The district-specific abstract is blank, so this is a city-aggregate date, not independently confirmed Bình Thạnh survey dating. The Bến Nghé example has revision date 2010-01-30, edition V2010, temporal extent 2010, and metadata stamp 2024-01-09; its description mentions database construction in 2014. Catalogue/metadata updates and retrieval in 2026 do not make the underlying cadastre current.

Any later permitted reconstruction must retain the 2010-era provenance and district-date uncertainty. A measured gap from rendered historical lines would be inferred evidence, likely Observed with method/date and uncertainty; provider-stated facts could be Declared. It would not become current Official Clear Width merely because the map publisher is official. A parcel gap also does not establish obstacle-free usable width.

## Requests and validation result

**9 direct HTTP requests total:** 3 robots checks, 3 catalogue searches, 1 GeoNetwork record, 1 city terms page, 1 WMS GetCapabilities. Six returned HTTP 200 and the three robots checks returned 404. All direct requests used the same identified User-Agent, `NgoNgach-WMSResearch/1.0`, with the research purpose and contact address. Separate discovery used one web-search tool call containing two queries; search infrastructure requests are not included in the direct HTTP count. No search-result pages were opened through that tool.

**Pilot map requests: 0/300.** GetMap images: 0. WMTS tiles: 0. Planning point queries: 0. ArcGIS FeatureServer requests: 0. No image sampling, including from pre-existing cached tiles, was performed after the gate decision.

- Matched validation cuts, n: **0**; matched ways, n: **0**.
- Per-cut MAE, signed bias and P90 absolute error: **N/A**.
- Per-way MAE, signed bias and P90 absolute error: **N/A**.
- Per-cut and per-way measurement records: none, because acquisition/vectorization did not run.
- The MAE ≤0.30 m criterion is **not evaluated**. These results are not 0.00 m error and do not indicate lack of geographic reference overlap.

The existing `parcels.measure` implementation was inspected offline. Any resumed pilot must use raw `gap_m`, not `width_m` (which subtracts the 1 m usable margin), and preserve its 5 m cut placement, local coordinate scales, perpendicular directions, corner rejection, opposing-parcel identity/component checks, minimum side distance and valid-gap limits. Boundary crossings alone would not establish identical semantics. New 5 m cuts lacking cached reference values must remain unvalidated unless recoverable from existing cached parcel geometry without network point queries.

## Decision and retained audit

**Do not proceed with the pilot or propose a citywide acquisition run on the present permission evidence.** This is a terms/permission no-go, not an empirical rejection of raster-derived widths. Resume only once the applicable Bình Thạnh dataset conditions and permission for identified, rate-limited automated map acquisition and derived research measurements are established, including any project-use financial condition. The conditional citywide request-count/rate/duration plan is not warranted because neither its permission nor accuracy prerequisite passed.

Original responses, HTTP metadata, URLs, retrieval times and SHA256 hashes are retained under `backend/cache/wms_vectorize_pilot/`. Its `audit.json` records all nine direct requests and null validation metrics; readable text extractions accompany terms/catalogue pages. Cached inputs under `backend/cache/portal_research/` and the previous official-bulk report were inspected without re-running their probes. Response hashes were recomputed and checked against the new audit metadata. Only this report and the isolated research cache were written by this task; existing working-tree changes were preserved.
