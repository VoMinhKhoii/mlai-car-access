# Research 03: Flood evidence (HCMC and Hanoi)

Collected 2026-09-28 by a research agent. Tags: [tested] called or downloaded; [documented]; [reported]; [unverified]. Data copied to `../../data/flood/`: the IRD set in `ird-hcmc/`, live-feed snapshots in `snapshots-2026-09-28/`.

## A. Historical: IRD/DataSuds HCMC database (doi:10.23708/8Y16HU)
- Published 2026-09-09. All 10 files download without login via `https://dataverse.ird.fr/api/access/datafile/{id}`. The licence is inconsistent: the API metadata says CC BY-NC 4.0, but the bundled ReadMe says CC-BY 4.0 [tested]. Metadata: https://dataverse.ird.fr/api/datasets/:persistentId/?persistentId=doi:10.23708/8Y16HU
- 425 points with 22 fields: date, location name/type, old district/ward plus post-2025 ward, depth min/max (cm), depth class, cause, impact, source, spatial precision, geocoding method and duration. The CRS is EPSG:9210, converted to WGS84 GeoJSON [tested].
- **By year:** 2002: 46; 2005–08: 57; 2010–13: 109; 2015–18: 56; 2019: 44; 2020: 11; 2022: 6; 2023: 28; 2024: 18; 2025: 43; 2026: 7. No records for 2003–04, 2009, 2014 or 2021. 362 records have a date (64 distinct days), with no time of day [tested].
- **By place:**
  - Old district: Bình Thạnh 76, D2 70, Thủ Đức 59, D8 30, D7 29, Bình Chánh 22, D1 21, Nhà Bè 18.
  - Current ward: An Khánh 56, Thạnh Mỹ Tây 34, Hiệp Bình 25, Phú Định 18, across 87 wards/communes [tested].
- **Cause and depth:** rain 198, tide 176, combined 51. Only 147 records (35%) give a depth: median 40 cm, 25 records above 50 cm. Depth class is "Unknown" for 257 [tested].
- **Spatial precision:** High (≤100 m) 78 (18%), Medium (100–500 m) 99 (23%), Low (>500 m) 248 (58%).
  - By geocoding: 341 street points (placed somewhere on the named street), 72 area points, 10 exact points.
  - About 80% of records name a street, but fewer than 20% are accurate to within 100 m.
  - 2023–26 has 96 records, 20 of them High precision [tested].
- **Recurrent streets** (5 or more years): Nguyễn Hữu Cảnh (10 years); Quốc Hương, Huỳnh Tấn Phát, Ung Văn Khiêm (7); Nguyễn Văn Hưởng, Thảo Điền, Kha Vạn Cân, Nguyễn Duy Trinh, Võ Văn Ngân (5).
- **Sources:** 92% newspapers. The source list is incomplete: the largest source (SRC_38) has no URL [tested].
- **Hanoi:** no comparable dataset on DataSuds or HDX [tested].

## B. Official lists and live feeds

### HCMC
- **Sở Xây dựng lists** [reported]. Both exist only as article text, not as a dataset.
  - 23 streets that flood 0.15–0.3 m when the tide exceeds the alarm level (Nov 2025): https://thanhnien.vn/danh-sach-23-tuyen-duong-bi-ngap-nuoc-do-trieu-cuong-o-tphcm-185251120195250754.htm
  - 34 "rốn ngập" (26 rain, 8 tide, June 2026). The article says a core problem is the lack of real-time data: https://vietnamnet.vn/so-xay-dung-tphcm-diem-danh-34-ron-ngap-2529419.html
- **Anti-flood centre map (https://chongngap.hochiminhcity.gov.vn/baongap/):** defines layers for rain and tide gauges, cameras, citizen/inspector reports with depth in cm, and "streets likely to flood". Its ArcGIS backend is dead: "licenses may be expired", services "not found" or "Token Required" [tested]. The centre was folded into Sở Xây dựng [reported]: https://thanhnien.vn/tphcm-chuyen-trung-tam-chong-ngap-cho-so-xay-dung-185799284.htm
- **UDI Maps** (drainage company app, since 2017) shows rain, tide, flood points, camera stills and citizen reports [reported]: https://udc.com.vn/ra-mat-ung-dung-truyen-tai-thong-tin-ngap-cho-tp-hcm. No public API found: the APK mirror was blocked and likely hostnames were dead [tested].
- **Planned sensors:** new sensors and AI cameras will feed an internal platform called "FEDS"; no public access mentioned [reported]: https://moitruong.net.vn/tp-hcm-dung-ai-va-sieu-cam-bien-duoi-nuoc-khoi-duong-pho-trong-nam-2026-91594.html
- **Traffic-camera stills are public:** `https://giaothong.hochiminhcity.gov.vn/render/ImageHandler.ashx?id=5d8cdb9f766c880017188968&t=<ms>` returned a live 800×450 JPEG of Hoàng Văn Thụ–Trần Huy Liệu at 11:27 [tested]. The camera list with coordinates was not extracted [unverified].

### Hanoi (Thoát nước Hà Nội; no login needed)
- `GET https://thoatnuochanoi.vn/ungngap/api/flood/getflood` returns 45 monitored flood points [tested]:
  - Points are street segments, including alleys ("Ngõ 211 Ngọc Lâm", "Ngõ 42, 58 Triều Khúc").
  - Each has lat/lng and an icon that encodes depth class; the legend runs 0 / 0.1 / 0.3 / 0.7 / 0.9 / >1 m.
  - All points showed dry on 2026-09-28; the web page polls every 10 s.
- `POST https://thoatnuochanoi.vn/map/api/getAllData` returns 62 rain gauges as class icons [tested].
- Numeric rainfall and 46 canal/river water levels exist only as one PNG per station (`/rain/images/{id}.png`, `/wt/images/{id}.png`; e.g. Tô Lịch shows "360"). Reading them needs OCR [tested].
- The HSDC Maps and iHanoi apps show depth in cm, rain and cameras [reported]: https://cellphones.com.vn/sforum/tra-cuu-diem-ngap-ung-tai-ha-noi
- Event lists [reported]:
  - 65 points on 2025-09-30 (typhoon Bualoi), published as screenshots: https://vietnamnet.vn/danh-sach-65-diem-ung-ngap-tren-dia-ban-ha-noi-2447657.html
  - 122 points on 2025-10-07: https://tapchinuoc.vn/tinh-hinh-ngap-ung-tai-ha-noi-nguyen-nhan-kinh-nghiem-quoc-te-va-dinh-huong-giai-phap-175251010105113761.htm

## C. Real-time drivers
- **Open-Meteo** (no key) works for both cities [tested].
  - Outside Europe and North America, `minutely_15` is just hourly data interpolated (docs); the response confirms it, with values repeating in blocks of four [tested/documented].
  - Past-24h model rain: HCMC 9.8 mm, Hanoi 0.6 mm.
  - The free tier is non-commercial only, 10k calls/day, data under CC BY 4.0 [documented].
- **vrain** (no key) [tested]:
  - `https://data.vrain.vn/public/current/all.json` lists 2,604 gauges nationwide (name, lat/lng, mm, rain class).
  - `/56.json` covers HCMC with 32 gauges, 8 in or near the urban core.
  - `/20.json` covers Hanoi with 25 gauges, only 2 in the core.
  - Totals run from 19:00 the previous day [reported]. Historical data needs a login [tested].
- **Radar:** 10-minute max-reflectivity PNGs, e.g. `http://hymetnet.gov.vn/dataout_web/NHB/20260928/NHB_202609280410_CMAX00.png` (Nhà Bè radar; timestamp in UTC) [tested].
  - Resolution is about 0.26 km per pixel; the image bounds are in the page's JS.
  - Hanoi is covered by the Phù Liễn and Việt Trì radars.
  - HCMC-specific coefficients for converting radar reflectivity to rain rate: IRD doi:10.23708/UT4REO [tested].
- **Tide:** Đài KTTV Nam Bộ publishes a daily 09:00 bulletin as a text PDF: https://kttvnb.vn/attachments/article/29144/HOCM_TBTC_20260928_0900.pdf [tested].
  - 2026-09-28: Nhà Bè 1.58 m (about alarm level 3), Phú An 1.55 m.
  - Forecast peak on 29–30/9 at 1.63–1.67 m, in the 06–08h and 17–19h windows; disaster risk level 2.
  - Phú An alarm levels (báo động 1/2/3) are 1.4/1.5/1.6 m, per QĐ 05/2020/QĐ-TTg [reported].
  - 2025 had 75 days at or above alarm level 1 [reported].
  - On 2026-09-27 the tide flooded Rạch Cùng and Phạm Thế Hiển streets [reported].
  - No numeric tide API found; the national disaster-monitoring site's (VNDMS) JS is obfuscated [tested].

## D. Crowd/news and problem validation
- VnExpress runs live reports with reader videos. On 2025-09-30 in Hanoi [reported]: https://vnexpress.net/giao-thong-ha-noi-hon-loan-gio-tan-tam-vi-mua-lon-4945604-tong-thuat.html
  - Cars were abandoned or floating at Liễu Giai–Phan Kế Bính.
  - Water was about 1 m deep at Liễu Giai–Đào Tấn.
  - More than 20 motorbikes stalled.
- Car flood covers (under 1M up to 30M VND) went viral in Sept 2025 [reported]: https://tuoitre.vn/do-chong-ngap-o-to-mua-mua-bao-gay-sot-mang-xa-hoi-loai-re-1-trieu-cao-cap-toi-30-trieu-dong-20250925152231359.htm
- **Not verified:** how Facebook, Zalo, Otofun, VOZ and TikTok are used for flood reports, and 2025 insurance-claim or thủy kích counts [unverified].

## E. Terrain [tested]
- Copernicus GLO-30 and FABDEM were both obtained.
- At HCMC flood points, FABDEM's median is 3.4 m versus 5.8 m for Copernicus, whose surface model includes buildings and trees.
- Flood points against 3,000 random points (AUC for "lower ground = flooded"): 0.55 overall, 0.64 for tide floods, 0.48 for rain floods, which is chance.
- In Hanoi, flood points are not lower than random points.
- So global 30 m DEMs are weak for tide flooding and useless for rain flooding at street level. FABDEM's licence is non-commercial [unverified]. No local LiDAR found [unverified].

## Agent's conclusion
HCMC has the deeper street-level evidence: the only historical geodatabase, a tide you can forecast with official daily numbers, public cameras, radar and gauges. But its official live flood map is down. Hanoi has the only official machine-readable live feed at street/alley level, but no historical geodatabase, and its floods are rain-driven and harder to forecast.

## Agent's implications
- **A defensible HCMC "evidence now" layer** could combine five inputs:
  - Prior: IRD points, recurrent streets and the 23/34 official hotspots, split by cause and keeping the precision field.
  - Tide: the daily PDF flags tide-prone streets during peak windows, by alarm level 1/2/3.
  - Rain now: vrain gauges plus Nhà Bè radar, with Open-Meteo for the next few hours.
  - Cameras: stills near hotspots scored by a vision model.
  - User confirmations.
- Label each item as timestamped evidence with its source, not as a prediction.
- **Hanoi equivalent:** poll the 45-point feed, OCR the gauge images, and add radar.
- Measured depths are sparse, so wading logic needs depth classes or ranges rather than exact values.
- **Licences:** IRD and FABDEM are non-commercial, and Open-Meteo's free tier is non-commercial. The government endpoints state no terms.
- The HCMC tide peaks on 29–30/9 give a live window to validate against.

## Open questions for the team/organizers
1. Does the organizer data include Vmap/VETC probe traces, user flood reports, or Tasco Insurance flood/hydrolock claims by location?
2. Can the organizers broker access to the HCMC drainage company's or Sở Xây dựng's sensors, or to numeric depths from Hanoi's HSDC system?
3. Is scraping unauthenticated government endpoints acceptable for the demo?
4. Does the demo count as "commercial" under the non-commercial licences?
5. Does Tasco hold a local DEM or LiDAR?
