"""PIPELINE 5: HCMC Decision 4582/QĐ-UBND (24/7/2026) → alleys fire trucks cannot enter → Official width evidence.

Phụ lục 2 of the decision lists, ward by ward, the roads and alleys that do not meet fire-fighting access
(QCVN 06:2022/BXD: a fire-truck road needs ≥ 3.5 m clear width). A listed alley is therefore taken as narrower
than 3.5 m. The annex is published as text converted from PDF (words broken by stray spaces, numbering that
restarts at 1 for every ward, ward names at page breaks), so parsing is sequence-based.

Steps
  1. fetch    luatvietnam.vn page with the full annex (cached in data/raw/qd4582.html)
  2. parse    items "N <Hẻm|Đường|…> name" with N = previous + 1, or 1 for a new ward; ward = last ward heading
  3. locate   ward centre via Goong geocoding (cached)
  4. match    to OSM small roads by space- and accent-insensitive name; among same-named ways, the one nearest
              the ward centre (≤ 4 km)
Output: data/official/fire_access_4582.json  [{ward, name, way_ids, dist_m}] (+ unmatched count)

Run:  python3 pipelines/fire_access_4582.py
"""
from __future__ import annotations

import html
import json
import math
import re
import unicodedata
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
URL = ("https://luatvietnam.vn/dat-dai/quyet-dinh-4582-qd-ubnd-tp-hcm-2026-cong-bo-danh-sach-khu-vuc-khong-dam-bao"
       "-ha-tang-giao-thong-nguon-nuoc-chua-chay-442277-d2.html")
RAW = ROOT / "data" / "raw" / "qd4582.html"
ROADS = ROOT / "data" / "raw" / "overture" / "hcmc_small_roads.json"
WARDS = ROOT / "data" / "raw" / "qd4582_wards.json"
OUT = ROOT / "data" / "official" / "fire_access_4582.json"
MAX_DIST = 3000.0
KIND = r"(?:Hẻm|Hẽm|Đường|Kiệt|Ngõ|Tuyến|Nhánh|Lối|Khu|Hẻ m|Đư ờng)"
WARD = re.compile(r"\b(Phường|Xã|Đặc khu)\s+((?:[A-ZĐÂĂÊÔƠƯÁÀẢÃẠ0-9][^\s]*\s?){1,4}?)(?=\s+(?:Phường|Xã|STT|\(|\d|$))")


def env(key: str) -> str:
    for line in (ROOT / ".env.local").read_text().splitlines():
        if line.startswith(key + "="):
            return line.split("=", 1)[1].split("#")[0].strip().strip('"')
    return ""


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s.replace("đ", "d").replace("Đ", "D"))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def key(name: str) -> str:
    """Space-, accent- and 'Đường'-insensitive key: 'Hẻm 745/136 Đường Quang Trung' → 'hem745/136quangtrung'."""
    k = re.sub(r"\s+", "", fold(name))
    k = re.sub(r"^(hem|kiet|ngo)([0-9]+[a-z]?(?:/[0-9]+[a-z]?)*)(duong|d\.)", r"\1\2", k)
    return re.sub(r"^duong", "", k)


def haversine(a, b) -> float:
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def parse(text: str) -> list[dict]:
    """Walk the numbered items; a reset to 1 starts the next ward."""
    start = text.find("PHỤ LỤC 2")
    body = text[start:] if start >= 0 else text
    items, ward, prev = [], None, 0
    pending_ward = None
    # candidate boundaries: a number followed by a road keyword
    marks = list(re.finditer(rf"(?:(?<=\s)|^)(\d{{1,4}})\s+(?={KIND})", body))
    for i, m in enumerate(marks):
        n = int(m.group(1))
        seg_end = marks[i + 1].start() if i + 1 < len(marks) else len(body)
        segment = body[m.end():seg_end]
        heads = [f"{w.group(1)} {w.group(2).strip()}" for w in WARD.finditer(body[(marks[i - 1].end() if i else 0):m.start()])]
        if heads:
            pending_ward = heads[-1]
        if n == prev + 1 or (n == 1 and prev > 0) or (prev == 0 and n == 1):
            if n == 1:
                ward = pending_ward or ward
            name = re.split(r"\s+(?:STT|Phường|Xã|Đặc khu|PHỤ LỤC|\(Đính)", segment)[0].strip(" ,.;")
            items.append({"ward": ward, "name": re.sub(r"\s+", " ", name)})
            prev = n
        elif items:  # not a boundary: the number belongs to the previous name (e.g. "An Thạnh 4 6")
            items[-1]["name"] += f" {n} " + re.split(r"\s+(?:STT|Phường|Xã|Đặc khu)", segment)[0].strip()
    return items


def ward_centres(wards: list[str]) -> dict[str, list[float]]:
    cache = json.loads(WARDS.read_text()) if WARDS.exists() else {}
    k = env("GOONG_API_KEY")
    for w in wards:
        if w in cache or not k:
            continue
        try:
            r = httpx.get("https://rsapi.goong.io/geocode", params={"address": f"{w}, Hồ Chí Minh", "api_key": k}, timeout=15).json()
            loc = r["results"][0]["geometry"]["location"]
            cache[w] = [loc["lat"], loc["lng"]]
        except Exception:
            cache[w] = None
    WARDS.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
    return cache


def main() -> None:
    if not RAW.exists():
        r = httpx.get(URL, headers={"User-Agent": "Mozilla/5.0 Chrome/128"}, timeout=60, follow_redirects=True)
        RAW.parent.mkdir(parents=True, exist_ok=True)
        RAW.write_text(r.text, encoding="utf-8")
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", RAW.read_text(encoding="utf-8"))))
    items = parse(text)
    wards = sorted({i["ward"] for i in items if i["ward"]})
    print(f"{len(items)} items in {len(wards)} wards")

    centres = ward_centres(wards)
    by_key: dict[str, list[dict]] = {}
    for w in json.loads(ROADS.read_text()):
        nm = w["tags"].get("name")
        if nm:
            c = w["coords"][len(w["coords"]) // 2]
            by_key.setdefault(key(nm), []).append({"id": w["id"], "lat": c[1], "lon": c[0]})

    out, unmatched, no_ward = [], 0, 0
    for it in items:
        cands = by_key.get(key(it["name"]), [])
        centre = centres.get(it["ward"]) if it["ward"] else None
        if not cands:
            unmatched += 1
            continue
        if centre:
            near = [(haversine(centre, (c["lat"], c["lon"])), c) for c in cands]
            # Short generic names ("Đường C1", "Đường số 5") repeat across the city: demand a closer match.
            generic = "/" not in it["name"] and len(key(it["name"])) < 12
            near = [x for x in near if x[0] <= (1500.0 if generic else MAX_DIST)]
            if not near:
                unmatched += 1
                continue
            dmin = min(d for d, _ in near)
            ids = sorted({c["id"] for d, c in near if d <= dmin + 300})  # one alley is often split into several ways
            out.append({**it, "way_ids": ids, "dist_m": round(dmin)})
        elif len({(round(c["lat"], 2), round(c["lon"], 2)) for c in cands}) == 1:  # unambiguous without a ward
            no_ward += 1
            out.append({**it, "way_ids": sorted({c["id"] for c in cands}), "dist_m": None})
        else:
            unmatched += 1
    OUT.write_text(json.dumps({"source": "QĐ 4582/QĐ-UBND TP.HCM ngày 24/7/2026, Phụ lục 2", "url": URL,
                               "rule": "QCVN 06:2022/BXD: đường cho xe chữa cháy rộng thông thủy ≥ 3,5 m",
                               "items": out, "parsed": len(items), "unmatched": unmatched}, ensure_ascii=False, indent=1))
    ways = {w for o in out for w in o["way_ids"]}
    print(f"matched {len(out)} items → {len(ways)} OSM ways ({no_ward} without ward); unmatched {unmatched} -> {OUT}")


if __name__ == "__main__":
    main()
