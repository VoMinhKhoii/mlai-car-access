"""Live Area Build: evidence for the area around a destination is collected when it is planned.

Steps (streamed to the UI as they run, see build()):
  1. map       OSM street graph around the destination (Overpass, cached per area)
  2. listings  Chợ Tốt alley-house listings (sale + rent) of the 2 nearest HCMC districts, cached 12 h
  3. match     regex-v1 extraction, then alley-chain name matching to the OSM ways of this area
  4. photos    (flag ai_photo_evidence) Gemini reads listing photos of matched alleys; every reading
               waits in a review queue, and only a human approval makes it Observed evidence

Chợ Tốt has no geo search, so listings are pulled by district and kept only if they name a
street of this area. Coordinates are shifted ~90 m, so they are never used for matching.
"""
from __future__ import annotations

import hashlib
import re
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from . import ai, alonhadat, flags, news, parcels
from .config import CACHE, ROOT
from .evidence import STORE_EVIDENCE
from .osm import area_key, build_graph, haversine, strip_accents

sys.path.insert(0, str(ROOT / "pipelines"))
from common import norm_name  # noqa: E402
from extract_regex import Gazetteer, _chain_from, extract  # noqa: E402

VN_TZ = timezone(timedelta(hours=7))
API = "https://gateway.chotot.com/v1/public/ad-listing"
REGIONS = "https://gateway.chotot.com/v1/public/web-proxy-api/loadRegions"
HEADERS = {"User-Agent": "VaoDuoc-hackathon/0.2 (MLAI Hackathon 2026)"}
DIR = CACHE / "live"
TTL = timedelta(hours=12)
PAGE, PAGES = 50, 4          # per district and listing type
DISTRICTS = 2
CHAIN_MAX_M = 1000.0
HXH_FLAG = 2                 # pty_characteristics code for "Hẻm xe hơi"
MAX_PHOTOS = 12
PHOTOS_PER_LISTING = 2

# ---------- districts ----------

def _districts() -> list[dict]:
    """Every Chợ Tốt district of Ho Chi Minh City (region 13000) with its centroid."""
    path = DIR / "chotot_hcmc_districts_v2.json"
    if path.exists():
        return json.loads(path.read_text())
    regions = httpx.get(REGIONS, headers=HEADERS, timeout=20).json()["regionFollowId"]["entities"]["regions"]
    out = []
    for rid, region in regions.items():
        if rid != "13000":
            continue
        for aid, a in region.get("area", {}).items():
            try:
                lat, lon = (float(x) for x in a["geo"].split(","))
            except (KeyError, ValueError):
                continue
            out.append({"id": int(aid), "region": int(rid), "name": a["name"], "province": region["name"], "lat": lat, "lon": lon})
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False))
    return out


def nearest_districts(lat: float, lon: float, n: int = DISTRICTS) -> list[dict]:
    return sorted(_districts(), key=lambda d: haversine(lat, lon, d["lat"], d["lon"]))[:n]


# ---------- listings ----------

def _pull(region: int, area: int, st: str, job: dict) -> list[dict]:
    stamp = datetime.now(VN_TZ)
    path = DIR / "chotot" / f"{area}_{st}.json"
    if path.exists():
        cached = json.loads(path.read_text())
        if stamp - datetime.fromisoformat(cached["fetched_at"]) < TTL:
            job["cached"] = True
            return cached["ads"]
    ads = []
    for page in range(PAGES):
        params = {"region_v2": region, "area_v2": area, "cg": 1020, "house_type": 3, "st": st,
                  "limit": PAGE, "o": page * PAGE}
        r = httpx.get(API, params=params, headers=HEADERS, timeout=30)
        r.raise_for_status()
        batch = r.json().get("ads", [])
        ads += batch
        job["counts"]["fetched"] += len(batch)
        if len(batch) < PAGE:
            break
        time.sleep(0.8)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"fetched_at": stamp.isoformat(), "ads": ads}, ensure_ascii=False))
    return ads


def _dedupe(ads: list[dict]) -> list[dict]:
    seen, out = set(), []
    for a in sorted(ads, key=lambda a: a.get("list_time", 0), reverse=True):
        key = hashlib.sha1((a.get("subject", "") + "\n" + a.get("body", "")).encode()).hexdigest()
        if key not in seen and a.get("ad_id") not in seen:
            seen.update((key, a.get("ad_id")))
            out.append(a)
    return out


def _match(g, by_name: dict[str, list], chain: list[str], lat, lon):
    """Deepest alley level of the chain that exists in this area, nearest same-named way."""
    for depth, level in enumerate(reversed(chain)):
        key = norm_name(level)
        # The chain is written "Hẻm …"; Hà Nội names alleys "Ngõ/Ngách", Huế and Đà Nẵng "Kiệt".
        cands = next((by_name[k] for k in (key, *(re.sub(r"^hem\b", alt, key) for alt in ("ngo", "ngach", "kiet")))
                      if k in by_name), [])
        if not cands:
            continue
        def dist(w):
            if lat is None:
                return 0.0
            return min(haversine(lat, lon, *g.nodes[n]) for n in w.nodes)
        best = min(cands, key=dist)
        if dist(best) <= CHAIN_MAX_M:
            return best, "alley_chain" if depth == 0 else "alley_chain_parent"
    return None, None


def _listings(g, ads: list[dict], job: dict) -> list[dict]:
    streets = {w.name for w in g.ways.values() if w.name and not w.is_alley}
    street_keys = {norm_name(s) for s in streets}
    gaz = Gazetteer(streets)
    by_name: dict[str, list] = {}
    for w in g.ways.values():
        if w.name:
            by_name.setdefault(norm_name(w.name), []).append(w)
    out = []
    for a in ads:
        street = a.get("street_name") or ""
        if norm_name(street) not in street_keys:
            continue
        job["counts"]["in_area"] += 1
        text = f"{a.get('subject', '')}\n{a.get('body', '')}\n{street}"
        ex = extract(text, street or None, gaz)
        chain = ex["alley_chain"]
        num = (a.get("street_number") or "").strip().strip("/")
        if not chain and "/" in num:  # structured house number "694/33" is an alley address
            chain = _chain_from(num, street.replace("Đường ", "", 1))
        access = ex["access_claim"] or ("xe_hoi" if HXH_FLAG in (a.get("pty_characteristics") or []) else None)
        way, method = _match(g, by_name, chain, a.get("latitude"), a.get("longitude"))
        if not way:
            continue
        aln = a.get("source") == "alonhadat"
        width, at_mouth = ex["width_m"], ex["width_at_mouth"]
        if aln and a.get("road_front_m"):  # structured "Đường trước nhà": the alley in front of this house
            width, at_mouth = a["road_front_m"], False
        out.append({
            "listing_id": a["ad_id"], "url": a["url"] if aln else f"https://www.nhatot.com/{a['list_id']}.htm",
            "posted_at": a.get("posted_at", "") if aln else
            (datetime.fromtimestamp(a["list_time"] / 1000, VN_TZ).isoformat(timespec="seconds") if a.get("list_time") else ""),
            "source": "Tin rao Alonhadat (trường “Đường trước nhà”)" if aln else "Tin rao Chợ Tốt (thu thập trực tiếp)",
            "title": a.get("subject", ""), "street": street, "alley_chain": chain,
            "osm_way_id": way.id, "osm_name": way.name, "match_method": method,
            "width_m": width, "width_at_mouth": at_mouth, "width_text": ex["width_text"],
            "access_claim": access, "through": ex["through"],
            "images": (a.get("images") or [])[:PHOTOS_PER_LISTING],
        })
    job["counts"]["matched"] = len(out)
    job["counts"]["alleys"] = len({x["osm_way_id"] for x in out})
    return out


# ---------- photos ----------

def _photo_path(key: str):
    return DIR / "photos" / f"{key}.json"


def _photos(key: str, rows: list[dict], job: dict) -> list[dict]:
    path = _photo_path(key)
    done = {p["image_url"]: p for p in json.loads(path.read_text())} if path.exists() else {}
    done = {u: p for u, p in done.items() if p.get("gate") != "ERROR"}  # failed readings are retried
    todo = []
    for r in rows:
        if r["match_method"] != "alley_chain":
            continue
        for url in r["images"]:
            if url not in done and len(todo) < MAX_PHOTOS:
                todo.append((r, url))
    job["counts"]["photos_total"] = len(todo)

    def read(item):
        r, url = item
        rec = {"id": hashlib.sha1(url.encode()).hexdigest()[:12], "image_url": url, "way_id": r["osm_way_id"],
               "alley": r["osm_name"], "listing_url": r["url"], "posted_at": r["posted_at"], "status": "pending"}
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=20)
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            out = ai.read_listing_photo(resp.content, mime if mime.startswith("image/") else "image/jpeg")
            rec.update({k: out.get(k) for k in ("shows_alley", "view", "alley_width_m", "reference",
                                                 "cars_visible", "confidence", "notes", "gate", "model")})
            rec["width_m"] = out.get("alley_width_m")
        except Exception as exc:  # one bad photo must not stop the build
            rec.update({"gate": "ERROR", "notes": str(exc)[:200]})
        job["counts"]["photos_read"] += 1
        return rec

    with ThreadPoolExecutor(4) as pool:
        for rec in pool.map(read, todo):
            done[rec["image_url"]] = rec
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=1))
    return list(done.values())


def review_photo(key: str, photo_id: str, approve: bool) -> None:
    """Remember a reviewer's decision in the area's photo cache (best effort; the browser also keeps it)."""
    path = _photo_path(key)
    if not path.exists():
        return
    photos = json.loads(path.read_text())
    for p in photos:
        if p["id"] == photo_id:
            p["status"] = "approved" if approve else "rejected"
            p["reviewed_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
    path.write_text(json.dumps(photos, ensure_ascii=False, indent=1))


def apply(area: dict | None, lat: float, lon: float) -> str:
    """Load a build result the browser sent back, so any server instance can plan with it."""
    key = area_key(lat, lon)
    if area and area.get("key") == key:
        STORE_EVIDENCE.set_live(key, area.get("listings") or [], area.get("photos") or [], area.get("parcels") or [])
    return key


# ---------- build (streamed) ----------

def _step(job: dict, name: str, state: str, detail: str = "") -> None:
    job["steps"][name] = {"state": state, "detail": detail}


def _run(job: dict, lat: float, lon: float) -> None:
    key = job["key"]
    try:
        _step(job, "map", "running")
        g = build_graph(lat, lon)
        origin = {"demo-cache": "bản tải sẵn", "cache": "cache"}.get(g.source.split(":")[0], "Overpass trực tiếp")
        _step(job, "map", "done", f"{len(g.ways)} đoạn đường OSM ({origin})")

        if flags.enabled("parcel_widths"):
            _step(job, "parcels", "running")
            cache_path = DIR / "parcels.json"
            cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
            try:
                deep = flags.enabled("parcel_deep_scan")
                job["parcels"] = parcels.measure_area(g, lat, lon, cache, haversine, deep=deep)
                detail = (f"{len(job['parcels'])} đường có ước tính khoảng trống từ hình học thửa đất"
                          + ("; lối vào/ra lấy mẫu sâu mỗi 5 m trong giới hạn" if deep else ""))
            except parcels.Blocked:
                detail = "Cổng quy hoạch tạm chặn truy vấn; thử lại sau"
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps(cache))
            _step(job, "parcels", "done", detail)
        else:
            _step(job, "parcels", "skipped", "Đã tắt")

        _step(job, "listings", "running")
        ds = nearest_districts(lat, lon)
        ads = []
        for d in ds:
            for st in ("s", "u"):
                ads += _pull(d["region"], d["id"], st, job)
        n_chotot = len(ads)
        aln_counts: dict = {}
        for d in ds:
            try:
                ads += alonhadat.pull_district(d["name"], DIR, aln_counts)
            except Exception:  # a second source failing must not stop the build
                pass
        n_aln = len(ads) - n_chotot
        ads = _dedupe(ads)
        job["counts"]["unique"] = len(ads)
        _step(job, "listings", "done", f"{n_chotot} tin Chợ Tốt + {n_aln} tin Alonhadat ở {', '.join(d['name'] for d in ds)}")

        _step(job, "match", "running")
        rows = _listings(g, ads, job)
        job["listings"] = rows
        c = job["counts"]
        _step(job, "match", "done", f"{c['in_area']} tin trong khu vực → {c['matched']} tin khớp {c['alleys']} hẻm")

        _step(job, "news", "running")
        streets = _streets_near(g, lat, lon)
        job["news"] = news.news_for(streets)
        _step(job, "news", "done", f"{len(job['news'])} tin về {', '.join(streets[:3])}" if streets else "không có tên đường gần")

        if flags.enabled("ai_photo_evidence") and ai.provider():
            _step(job, "photos", "running")
            job["photos"] = _photos(key, rows, job)
            useful = [p for p in job["photos"] if p.get("width_m")]
            _step(job, "photos", "done", f"{len(job['photos'])} ảnh đã đọc, {len(useful)} ảnh có bề rộng (chờ duyệt)")
        else:
            _step(job, "photos", "skipped", "Bật “AI đọc ảnh tài xế gửi” để đọc ảnh tin rao")
        job["state"] = "done"
    except Exception as exc:
        job["state"], job["error"] = "error", str(exc)[:300]
    job["finished_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")


def _status(job: dict) -> dict:
    return {k: v for k, v in job.items() if k not in ("listings", "photos", "news", "parcels")}


def _streets_near(g, lat: float, lon: float, n: int = 4) -> list[str]:
    """Named streets (and named alleys) closest to the destination, nearest first."""
    best: dict[str, tuple[float, str]] = {}
    for w in g.ways.values():
        if not w.name or not w.drivable:
            continue
        d = min(haversine(lat, lon, *g.nodes[x]) for x in w.nodes[:: max(1, len(w.nodes) // 6)])
        if d < 450:
            # Papers name streets, not alleys: "Hẻm 356 Xô Viết Nghệ Tĩnh" → "Xô Viết Nghệ Tĩnh".
            name = re.sub(r"^(hẻm|kiệt|ngõ|ngách)\s+[\w/]+\s+", "", w.name, flags=re.I)
            name = re.sub(r"^(Đường|đường)\s+", "", name).strip()
            if len(name) < 5 or re.match(r"^(số|đường số|nội bộ|nhánh)\b", name, re.I) or re.search(r"\d|nội bộ", name, re.I):
                continue
            key = strip_accents(name)
            if key not in best or d < best[key][0]:
                best[key] = (d, name)
    return [v[1] for v in sorted(best.values())][:n]


def build(lat: float, lon: float):
    """Run one area build inside the request and yield its status as it changes (NDJSON lines).

    The last line carries the result ({"area": {key, listings, photos}}); the browser keeps it and
    sends it back with each plan, so this works on stateless serverless instances.
    """
    key = area_key(lat, lon)
    job = {"key": key, "state": "running", "started_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
           "steps": {s: {"state": "pending", "detail": ""} for s in ("map", "parcels", "listings", "match", "news", "photos")},
           "counts": {"fetched": 0, "unique": 0, "in_area": 0, "matched": 0, "alleys": 0,
                      "photos_total": 0, "photos_read": 0},
           "listings": [], "photos": [], "news": [], "parcels": [], "error": None}
    if not flags.enabled("live_crawl"):
        yield json.dumps({"status": {"key": key, "state": "off"}}) + "\n"
        return
    t = threading.Thread(target=_run, args=(job, lat, lon), daemon=True)
    t.start()
    last = None
    while t.is_alive():
        snap = json.dumps({"status": _status(job)}, ensure_ascii=False)
        if snap != last:
            yield snap + "\n"
            last = snap
        t.join(0.7)
    area = {"key": key, "listings": job["listings"], "photos": job["photos"], "news": job["news"], "parcels": job["parcels"]}
    yield json.dumps({"status": _status(job), "area": area}, ensure_ascii=False) + "\n"
