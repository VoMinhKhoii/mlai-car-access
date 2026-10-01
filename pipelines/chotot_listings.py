"""PIPELINE 2: Chợ Tốt alley-house listings -> Declared access Evidence matched to OSM alley ways.

Steps
  1. fetch   public ad-listing API (house_type=3 "Nhà ngõ, hẻm"), small pages, 1.5 s apart, cap 1,500;
             raw pages cached in data/raw/chotot/ (re-runs reuse them unless --refresh)
  2. extract regex-v1 (extract_regex.py) over subject + body
  3. match   to OSM alley ways from Overpass: alley-chain name first, else nearest alley on the listed
             street within 120 m of the (shifted) listing coordinate
Output: data/processed/listings_evidence_binhthanh.json

Run:  pipelines/.venv/bin/python pipelines/chotot_listings.py [--refresh] [--cap 1500]
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import json
import re
import time

from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

from common import (DEMO_BBOX, PROCESSED, RAW, LocalProj, bbox_str, buffer_bbox, http_get, in_bbox,
                    norm_name, overpass, write_json)
from extract_regex import EXTRACTOR, Gazetteer, extract

API = "https://gateway.chotot.com/v1/public/ad-listing"
# (label, area_v2, ad type)  s = for sale, u = for rent. Pulled in this order until the cap.
PULLS = [
    ("binh_thanh_sale", 13109, "s"),
    ("binh_thanh_rent", 13109, "u"),
    ("phu_nhuan_sale", 13111, "s"),
    ("quan_1_sale", 13096, "s"),
]
PAGE = 20
SLEEP_S = 1.5
NEAREST_MAX_M = 120.0
CHAIN_MAX_M = 1000.0      # a same-named alley farther than this is taken to be a different alley
HXH_FLAG = 2              # pty_characteristics code for "Hẻm xe hơi"
ALLEY_NAME = re.compile(r"^(Hẻm|hẻm|HẺM|Kiệt|Ngõ)\b")


# ---------- 1. fetch ----------

def fetch(cap: int, refresh: bool) -> list[dict]:
    out_dir = RAW / "chotot"
    out_dir.mkdir(parents=True, exist_ok=True)
    ads: list[dict] = []
    for label, area, st in PULLS:
        offset, total = 0, None
        while len(ads) < cap and (total is None or offset < total):
            path = out_dir / f"{label}_o{offset:04d}.json"
            if path.exists() and not refresh:
                page = json.loads(path.read_text())
            else:
                params = {"region_v2": 13000, "area_v2": area, "cg": 1020, "house_type": 3, "st": st,
                          "limit": PAGE, "o": offset}
                page = http_get(API, params=params).json()
                path.write_text(json.dumps(page, ensure_ascii=False))
                time.sleep(SLEEP_S)
            total = page.get("total", 0)
            batch = page.get("ads", [])
            if not batch:
                break
            for a in batch:
                a["_pull"] = label
            ads.extend(batch[: cap - len(ads)])
            offset += PAGE
        print(f"  {label}: total {total}, have {len(ads)} so far")
    return ads


def dedupe(ads: list[dict]) -> list[dict]:
    """Drop exact re-posts (same subject+body); keep the newest. Also drop repeated ad_ids across pulls."""
    texts, ids, uniq = set(), set(), []
    for a in sorted(ads, key=lambda a: a.get("list_time", 0), reverse=True):
        key = hashlib.sha1((a.get("subject", "") + "\n" + a.get("body", "")).encode()).hexdigest()
        if key not in texts and a["ad_id"] not in ids:
            texts.add(key)
            ids.add(a["ad_id"])
            uniq.append(a)
    return uniq


# ---------- 3. OSM ----------

class AlleyIndex:
    def __init__(self, ways: list[dict]):
        lat0 = sum(DEMO_BBOX[::2]) / 2
        lon0 = sum(DEMO_BBOX[1::2]) / 2
        self.proj = LocalProj(lat0, lon0)
        self.ways, geoms = [], []
        self.by_name: dict[str, list[int]] = {}
        for w in ways:
            if len(w.get("geometry", [])) < 2:
                continue
            geoms.append(LineString([self.proj.xy(p["lat"], p["lon"]) for p in w["geometry"]]))
            i = len(self.ways)
            self.ways.append(w)
            name = w["tags"].get("name")
            if name:
                self.by_name.setdefault(norm_name(name), []).append(i)
        self.geoms = geoms
        self.tree = STRtree(geoms)

    def dist(self, i: int, pt: Point) -> float:
        return self.geoms[i].distance(pt)

    def point(self, lat, lon) -> Point:
        return Point(self.proj.xy(lat, lon))


def fetch_osm(extent) -> tuple[list[dict], list[str]]:
    s, w, n, e = extent
    bb = f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"
    q = (f'[out:json][timeout:240];('
         f'way["highway"]["name"]({bb});'
         f'way["highway"="service"]["service"="alley"]({bb});'
         f'way["highway"="living_street"]({bb});'
         f');out tags geom;')
    data = overpass(q, "alleys_" + bbox_str(extent).replace(",", "_"))
    ways = [el for el in data["elements"] if el["type"] == "way"]
    alleys = [w for w in ways if ALLEY_NAME.match(w["tags"].get("name", ""))
              or w["tags"].get("service") == "alley" or w["tags"].get("highway") == "living_street"]
    street_names = sorted({w["tags"]["name"] for w in ways if "name" in w["tags"] and not ALLEY_NAME.match(w["tags"]["name"])})
    print(f"  OSM: {len(ways)} ways, {len(alleys)} alley-like, {len(street_names)} street names")
    return alleys, street_names


def match(idx: AlleyIndex, lat, lon, chain: list[str], street: str | None, extent):
    if lat is None or lon is None or not in_bbox(lat, lon, extent):
        return None, None, "outside_osm_extent"
    pt = idx.point(lat, lon)
    for depth, level in enumerate(reversed(chain)):
        cands = idx.by_name.get(norm_name(level), [])
        if cands:
            best = min(cands, key=lambda i: idx.dist(i, pt))
            d = idx.dist(best, pt)
            if d <= CHAIN_MAX_M:
                return idx.ways[best], d, "alley_chain" if depth == 0 else "alley_chain_parent"
    skey = norm_name(street or "")
    if skey:
        near = [int(i) for i in idx.tree.query(pt.buffer(NEAREST_MAX_M))]
        on_street = [i for i in near
                     if norm_name(idx.ways[i]["tags"].get("name", "")).endswith(" " + skey)
                     and idx.dist(i, pt) <= NEAREST_MAX_M]
        if on_street:
            best = min(on_street, key=lambda i: idx.dist(i, pt))
            return idx.ways[best], idx.dist(best, pt), "nearest_on_street"
    return None, None, "unmatched"


# ---------- main ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=1500)
    ap.add_argument("--refresh", action="store_true", help="re-download listing pages")
    args = ap.parse_args()

    print("1. fetch")
    raw = fetch(args.cap, args.refresh)
    ads = dedupe(raw)
    print(f"  pulled {len(raw)}, unique {len(ads)}")

    located = [a for a in ads if a.get("latitude") and a.get("longitude")]
    lats = [a["latitude"] for a in located] + [DEMO_BBOX[0], DEMO_BBOX[2]]
    lons = [a["longitude"] for a in located] + [DEMO_BBOX[1], DEMO_BBOX[3]]
    # OSM extent = demo bbox ∪ listings' bbox (inside HCMC), buffered 300 m
    extent = buffer_bbox((max(min(lats), 10.70), max(min(lons), 106.60), min(max(lats), 10.86),
                          min(max(lons), 106.78)), 300)
    print(f"3. OSM extent {bbox_str(extent)}")
    alleys, street_names = fetch_osm(extent)
    idx = AlleyIndex(alleys)
    gaz = Gazetteer(street_names + [a.get("street_name", "") for a in ads if a.get("street_name")])

    print("2. extract + 3. match")
    # Chợ Tốt coordinates are street/ward-level and shared by many listings; a proximity match from a
    # shared coordinate only says "some alley on this street", so the count is exported with each row.
    coord_count = collections.Counter((a.get("latitude"), a.get("longitude")) for a in ads)
    out = []
    for a in ads:
        # street_name sometimes carries the alley address itself ("332/4A Phan Văn Trị"), so it is scanned too
        text = f"{a.get('subject', '')}\n{a.get('body', '')}\n{a.get('street_name', '')}"
        street = a.get("street_name") or None
        ex = extract(text, street, gaz)
        hxh_flag = HXH_FLAG in (a.get("pty_characteristics") or [])
        access, access_src = ex["access_claim"], "text" if ex["access_claim"] else None
        if access is None and hxh_flag:
            access, access_src = "xe_hoi", "chotot_flag"
        lat, lon = a.get("latitude"), a.get("longitude")
        way, dist, method = match(idx, lat, lon, ex["alley_chain"], street, extent)
        out.append({
            "listing_id": a["ad_id"],
            "url": f"https://www.nhatot.com/{a['list_id']}.htm",
            "posted_at": dt.datetime.fromtimestamp(a["list_time"] / 1000, dt.timezone.utc).isoformat(timespec="seconds")
            if a.get("list_time") else None,
            "title": a.get("subject"),
            "street": street,
            "ward": a.get("ward_name_v3") or a.get("ward_name"),
            "ward_old": a.get("ward_name"),
            "district_old": a.get("area_name"),
            "listing_type": {"s": "sale", "u": "rent"}.get(a.get("type"), a.get("type")),
            "lat": lat,
            "lon": lon,
            "coord_shared_by": coord_count[(lat, lon)] if lat else None,
            "alley_chain": ex["alley_chain"],
            "alley_chain_source": ex["alley_chain_source"],
            "osm_way_id": way["id"] if way else None,
            "osm_name": way["tags"].get("name") if way else None,
            "osm_motorcar": way["tags"].get("motorcar") if way else None,
            "match_method": method,
            "match_distance_m": round(dist, 1) if dist is not None else None,
            "width_m": ex["width_m"],
            "width_at_mouth": ex["width_at_mouth"],
            "width_text": ex["width_text"],
            "width_mentions_m": ex["width_mentions_m"],
            "access_claim": access,
            "access_source": access_src,
            "chotot_hxh_flag": hxh_flag,
            "car_to_door": ex["car_to_door"],
            "through": ex["through"],
            "extractor": EXTRACTOR,
            "evidence_tier": "Declared",
        })
    write_json(PROCESSED / "listings_evidence_binhthanh.json", out)

    in_demo = [r for r in out if r["lat"] and in_bbox(r["lat"], r["lon"], buffer_bbox(DEMO_BBOX, 300))]
    def count(rows, pred):
        return sum(1 for r in rows if pred(r))
    for name, rows in (("all", out), ("demo bbox+300m", in_demo)):
        print(f"  [{name}] listings {len(rows)} | width {count(rows, lambda r: r['width_m'])}"
              f" | access(text) {count(rows, lambda r: r['access_source'] == 'text')}"
              f" | through {count(rows, lambda r: r['through'])} | chain {count(rows, lambda r: r['alley_chain'])}"
              f" | matched {count(rows, lambda r: r['osm_way_id'])}"
              f" (chain {count(rows, lambda r: r['match_method'].startswith('alley_chain'))},"
              f" nearest {count(rows, lambda r: r['match_method'] == 'nearest_on_street')},"
              f" of which unique-coord {count(rows, lambda r: r['match_method'] == 'nearest_on_street' and r['coord_shared_by'] == 1)})")


if __name__ == "__main__":
    main()
