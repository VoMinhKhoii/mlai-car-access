"""PIPELINE 1: VETC parking lots and VETC-paid roadside parking streets for HCMC.

Inputs (downloaded and cached under data/raw/vetc/):
  - VETC lot lists (PDF), south + north
  - VETC news article listing the 20 HCMC roadside streets with cashless VETC payment
Outputs:
  - data/processed/vetc_lots_hcmc.geojson          (Point per HCMC lot row)
  - data/processed/vetc_street_parking_hcmc.geojson (LineString per merged OSM street part)

Run:  pipelines/.venv/bin/python pipelines/vetc_parking.py
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass

import pdfplumber
from shapely.geometry import LineString, mapping
from shapely.ops import linemerge

from common import PROCESSED, RAW, fold, http_get, norm_name, overpass, write_json
from geocode import get_geocoder

PDF_BASE = "https://vetc.com.vn/upload_images/files/"
PDFS = {
    "mien_nam": PDF_BASE + "Tong%20hop%20bai%20do%202026%20-%20MIEN%20NAM.pdf",
    "mien_bac": PDF_BASE + "Tong%20hop%20bai%20do%202026%20-%20MIEN%20BAC.pdf",
}
ARTICLE_URL = ("https://vetc.com.vn/vetc-trien-khai-he-thong-20-bai-gui-xe-khong-tien-mat-dau-tien-"
               "tai-thanh-pho-ho-chi-minh-n257.html")

# Search windows (south, west, north, east) keyed by the district text printed in the PDF.
# Old (pre-2025) district names are used in the PDF but no longer exist as OSM boundaries,
# so they are turned into bounded viewboxes instead of query text.
AREAS = {
    "central": (10.745, 106.650, 10.800, 106.715),   # Q1 / Q3 / Q5 / Q10
    "quận 2": (10.750, 106.700, 10.820, 106.800),
    "quận 7": (10.690, 106.680, 10.760, 106.760),
    "quận 8": (10.690, 106.580, 10.760, 106.700),
    "quận 12": (10.820, 106.600, 10.890, 106.720),
    "bình thạnh": (10.785, 106.680, 10.840, 106.740),
}
CENTRAL_DISTRICTS = ("quận 1", "quận 3", "quận 5", "quận 10")
# Approximate pre-2025 district extents for the 20 roadside streets. Used to keep only the part of a
# street name inside the district the article names (e.g. "Thủ Khoa Huân" also exists in Tân Hòa).
DISTRICT_BOXES = {
    "Quận 1": (10.755, 106.683, 10.795, 106.712),
    "Quận 5": (10.745, 106.650, 10.765, 106.686),
    "Quận 10": (10.757, 106.655, 10.782, 106.681),
}

# The 20 roadside streets exactly as the VETC article lists them (district from the article),
# each tied to the south-PDF row that carries its segment note. osm_names = OSM `name` values to fetch.
STREETS_20 = [
    # (article name, district, pdf STT, OSM names)
    ("Cao Bá Quát", "Quận 1", 16, ["Cao Bá Quát"]),
    ("Đông Du", "Quận 1", 15, ["Đông Du"]),
    ("Lê Lai", "Quận 1", 6, ["Lê Lai"]),
    ("Trương Định", "Quận 1", 9, ["Trương Định"]),
    ("Phan Chu Trinh", "Quận 1", 10, ["Phan Chu Trinh"]),
    ("Phan Bội Châu", "Quận 1", 11, ["Phan Bội Châu"]),
    ("Thủ Khoa Huân", "Quận 1", 17, ["Thủ Khoa Huân"]),
    ("Hai Bà Trưng", "Quận 1", 7, ["Hai Bà Trưng"]),
    ("Nguyễn Cư Trinh", "Quận 1", 8, ["Nguyễn Cư Trinh"]),
    ("Huyền Trân Công Chúa", "Quận 1", 12, ["Huyền Trân Công Chúa"]),
    ("Ngô Đức Kế", "Quận 1", 14, ["Ngô Đức Kế"]),
    ("Hồ Huấn Nghiệp", "Quận 1", 13, ["Hồ Huấn Nghiệp"]),
    ("An Dương Vương", "Quận 5", 19, ["An Dương Vương"]),
    ("Tản Đà", "Quận 5", 21, ["Tản Đà"]),
    ("Phạm Hữu Chí", "Quận 5", 18, ["Phạm Hữu Chí"]),
    ("Lê Hồng Phong", "Quận 10", 20, ["Lê Hồng Phong"]),
    ("Cao Thắng", "Quận 10", 25, ["Cao Thắng"]),
    ("Hẻm 781 Lê Hồng Phong & Hẻm 16 Trần Thiện Chánh", "Quận 10", 22,
     ["Hẻm 781 Lê Hồng Phong", "Hẻm 16 Trần Thiện Chánh"]),
    ("Hẻm 51 Thành Thái", "Quận 10", 23, ["Hẻm 51 Thành Thái"]),
    ("Hẻm 283-285 Cách Mạng Tháng Tám", "Quận 10", 24,
     ["Hẻm 283 Cách Mạng Tháng Tám", "Hẻm 285 Cách Mạng Tháng Tám",
      "Hẻm 283 Cách Mạng Tháng 8", "Hẻm 285 Cách Mạng Tháng 8"]),   # OSM spells it "Tháng 8"
]
FEE_NOTE = ("Thu phí sử dụng tạm thời lòng đường để đỗ ô tô (TNXP quản lý); trả qua VETC bằng quét QR "
            "hoặc tự động trừ tài khoản giao thông. Nguồn không công bố mức phí.")

# Extra free-text queries for lots whose PDF name/address is not a geocodable string.
# `expect` = folded regex that must appear in the result label; `max_conf` caps the confidence when the
# match is only the parent complex (OSM has "Thủ Thiêm Lakeview 3", not VETC's sub-buildings 3.1 / 3.2).
LOT_HINTS = {
    "Điểm gửi xe Lake View 3.2": (["Lakeview 3.2", "Thủ Thiêm Lakeview 3"], r"lakeview 3\b", 0.7),
    "Điểm gửi xe Lake View 3.1": (["Lakeview 3.1", "Thủ Thiêm Lakeview 3"], r"lakeview 3\b", 0.7),
    "Bãi xe thông minh Lô 41": (["Bãi xe Lô 41", "Lô 41"], "41", 0.9),
    "Điểm xe máy kín Tasco Tân Cảng": (["Tasco Tân Cảng", "220 Nguyễn Hữu Cảnh", "Nguyễn Hữu Cảnh"],
                                       "nguyen huu canh|tasco", 0.9),
    "Bitexco": (["Bitexco Financial Tower"], "bitexco", 0.9),
    "Kho Bãi ô tô Savico": (["Savico"], "savico", 0.9),
    "Kho Bãi xe máy Savico": (["Savico"], "savico", 0.9),
    "Trạm thu phí Chợ Bình Điền": (["Chợ Bình Điền"], "binh dien", 0.9),
}
POI_CATEGORIES = ("building", "amenity", "tourism", "shop", "office", "landuse", "man_made", "leisure")


@dataclass
class LotRow:
    stt: int
    operator: str
    name: str
    address: str
    lot_type_vi: str
    vehicle_vi: str
    province: str
    district: str
    deployed_on: str
    source_url: str


def download(key: str) -> str:
    path = RAW / "vetc" / f"vetc_lots_{key}.pdf"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        r = http_get(PDFS[key])
        if not r.content.startswith(b"%PDF"):
            raise RuntimeError(f"{PDFS[key]} did not return a PDF")
        path.write_bytes(r.content)
    return str(path)


def clean(cell) -> str:
    return re.sub(r"\s+", " ", (cell or "").replace("\n", " ")).strip()


def parse_pdf(key: str) -> list[LotRow]:
    rows = []
    with pdfplumber.open(download(key)) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                for r in table:
                    if not r or not clean(r[0]).isdigit():
                        continue
                    r = [clean(c) for c in r] + [""] * 9
                    rows.append(LotRow(int(r[0]), r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], PDFS[key]))
    return rows


def vehicle_of(v: str) -> str:
    f = fold(v)
    car, moto = ("o to" in f or "oto" in f), "xe may" in f
    return "both" if car and moto else "car" if car else "motorbike" if moto else "unknown"


def lot_type_of(t: str) -> str:
    f = fold(t)
    if "toa nha" in f:
        return "closed_building"
    return "closed" if "kin" in f else "open" if "mo" in f else "unknown"


def area_for(row: LotRow) -> tuple[float, float, float, float]:
    d = fold(row.district)
    for key, box in AREAS.items():
        if fold(key) in d and key != "central":
            return box
    if any(fold(c) in d for c in CENTRAL_DISTRICTS):
        return AREAS["central"]
    return (10.70, 106.60, 10.86, 106.78)


# ---------- street geometry (Overpass) ----------

def fetch_street_geometries() -> dict[str, list[dict]]:
    """Return {osm name: [way, ...]} for all 20-street names inside the central window."""
    names = sorted({n for *_, osm in STREETS_20 for n in osm})
    s, w, n, e = AREAS["central"]
    by_name: dict[str, list[dict]] = {}
    # main query (cached); the "Tháng 8" spellings go in a second query that may fail when mirrors are down
    for group in ([x for x in names if "Tháng 8" not in x], [x for x in names if "Tháng 8" in x]):
        rx = "|".join(re.escape(x) for x in group)
        q = f'[out:json][timeout:120];way["highway"]["name"~"^(Đường )?({rx})$"]({s},{w},{n},{e});out tags geom;'
        try:
            data = overpass(q, "vetc_streets")
        except Exception as exc:  # noqa: BLE001 - Overpass mirrors time out often; keep what we have
            print(f"  ! Overpass failed for {group}: {exc!r}")
            continue
        for el in data["elements"]:
            by_name.setdefault(norm_name(el["tags"]["name"]), []).append(el)
    return by_name


def _mid_in(way: dict, box) -> bool:
    p = way["geometry"][len(way["geometry"]) // 2]
    return box[0] <= p["lat"] <= box[2] and box[1] <= p["lon"] <= box[3]


def merged_lines(ways: list[dict]) -> list[LineString]:
    lines = [LineString([(p["lon"], p["lat"]) for p in w["geometry"]]) for w in ways if len(w["geometry"]) > 1]
    merged = linemerge(lines)
    return list(merged.geoms) if hasattr(merged, "geoms") else [merged]


def street_features(rows_by_stt: dict[int, LotRow], by_name) -> tuple[list[dict], dict[int, tuple]]:
    feats, midpoints = [], {}
    for street, district, stt, osm_names in STREETS_20:
        row = rows_by_stt.get(stt)
        seg = row.address if row else None
        m = re.search(r"(\d+(?:[.,]\d+)?)\s*(km|m)\b", seg or "")
        length_m = (float(m.group(1).replace(",", ".")) * (1000 if m.group(2) == "km" else 1)) if m else None
        found_any = False
        box = DISTRICT_BOXES[district]
        for osm_name in osm_names:
            ways = [w for w in by_name.get(norm_name(osm_name), []) if _mid_in(w, box)]
            if not ways:
                continue
            found_any = True
            lines = merged_lines(ways)
            longest = max(lines, key=lambda g: g.length)
            midpoints.setdefault(stt, longest.interpolate(0.5, normalized=True).coords[0])
            for i, line in enumerate(lines):
                feats.append({
                    "type": "Feature",
                    "geometry": mapping(line),
                    "properties": {
                        "street": street,
                        "osm_name": osm_name,
                        "district_published": district,
                        "segment_note": seg,
                        "published_length_m": length_m,
                        "fee_note": FEE_NOTE,
                        "source_url": ARTICLE_URL,
                        "segment_source_url": PDFS["mien_nam"] if row else None,
                        "osm_way_ids": sorted(w["id"] for w in ways if len(w["geometry"]) > 1),
                        "part": i,
                        "geometry_note": ("Toàn bộ đoạn tuyến theo OSM trong phạm vi quận (ước lượng); VETC chỉ "
                                          "công bố chiều dài đoạn thu phí, không công bố vị trí đoạn."),
                    },
                })
        if not found_any:
            print(f"  ! street {street!r}: no geometry")
    return feats, midpoints


# ---------- lot geocoding ----------

def label_head(label: str) -> str:
    return fold(label.split(",")[0])


def geocode_lot(geocoder, row: LotRow, street_midpoint, district_box=None) -> dict:
    box = district_box or area_for(row)
    roadside = "TNXP" in row.operator
    max_conf = 0.9
    if roadside:
        street = re.sub(r"^Đường\s+", "", re.split(r"\s+-\s*|\s-", row.address)[0]).strip()
        street = street.replace("Hai Ba Trưng", "Hai Bà Trưng")
        queries, expect = [street], fold(street.split(" và ")[0])
    else:
        hint = next((v for k, v in LOT_HINTS.items() if k in row.name or k in row.address), None)
        queries, expect, max_conf = hint if hint else ([row.address or row.name], fold(row.address or row.name), 0.9)
    for q in queries:
        for cand in geocoder.geocode(q, viewbox=box):
            head = label_head(cand.label)
            if not re.search(expect, head) and not re.search(expect, fold(cand.label)[:80]):
                continue
            category = cand.kind.split("/")[0]
            if category in POI_CATEGORIES and not roadside:
                conf, level = max_conf, "poi"
            elif category == "highway" and cand.kind.split("/")[1] == "bus_stop":
                conf, level = 0.6, "nearby_poi"
            else:
                conf, level = 0.5, "street"
            return {"lat": cand.lat, "lon": cand.lon, "geocoder": geocoder.name, "geocode_confidence": conf,
                    "geocode_level": level, "geocode_query": q, "geocode_label": cand.label}
    if street_midpoint:
        lon, lat = street_midpoint
        return {"lat": lat, "lon": lon, "geocoder": "osm-overpass-street-midpoint", "geocode_confidence": 0.4,
                "geocode_level": "street", "geocode_query": queries[0], "geocode_label": None}
    return {"lat": None, "lon": None, "geocoder": geocoder.name, "geocode_confidence": 0.0,
            "geocode_level": "not_found", "geocode_query": " | ".join(queries), "geocode_label": None}


def main() -> None:
    south = parse_pdf("mien_nam")
    north = parse_pdf("mien_bac")
    print(f"south PDF rows: {len(south)}; north PDF rows: {len(north)}")
    hcmc = [r for r in south + north if "hồ chí minh" in r.province.lower()]
    print(f"HCMC rows: {len(hcmc)} (north list HCMC rows: {sum(r in north for r in hcmc)})")

    by_name = fetch_street_geometries()
    rows_by_stt = {r.stt: r for r in south}
    street_feats, midpoints = street_features(rows_by_stt, by_name)

    geocoder = get_geocoder()
    lot_feats = []
    article_district = {stt: district for _, district, stt, _ in STREETS_20}
    for r in hcmc:
        in_south = r.source_url == PDFS["mien_nam"]
        dbox = DISTRICT_BOXES[article_district[r.stt]] if in_south and r.stt in article_district else None
        g = geocode_lot(geocoder, r, midpoints.get(r.stt) if in_south else None, dbox)
        print(f"  {r.stt:>2} {r.name or r.address:<45} -> {g['geocoder']:<30} {g['geocode_level']}")
        lot_feats.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [g["lon"], g["lat"]]} if g["lat"] is not None else None,
            "properties": {
                "name": r.name or r.address,
                "address": r.address,
                "vehicle": vehicle_of(r.vehicle_vi),
                "lot_type": lot_type_of(r.lot_type_vi),
                "lot_type_published": r.lot_type_vi,
                "roadside": "TNXP" in r.operator,
                "operator": r.operator,
                "district_published": r.district,
                "deployed_on": r.deployed_on or None,
                "pdf_row": r.stt,
                "source_url": r.source_url,
                **{k: g[k] for k in ("geocoder", "geocode_confidence", "geocode_level", "geocode_query",
                                     "geocode_label")},
            },
        })

    write_json(PROCESSED / "vetc_lots_hcmc.geojson", {"type": "FeatureCollection", "features": lot_feats})
    write_json(PROCESSED / "vetc_street_parking_hcmc.geojson",
               {"type": "FeatureCollection", "features": street_feats})
    located = sum(f["geometry"] is not None for f in lot_feats)
    streets_hit = len({f["properties"]["street"] for f in street_feats})
    print(f"lots: {len(lot_feats)} HCMC rows, {located} located; streets: {streets_hit}/20 with geometry, "
          f"{len(street_feats)} LineString features")


if __name__ == "__main__":
    sys.exit(main())
