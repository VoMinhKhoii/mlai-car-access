"""Live Area Build: server-owned evidence for the area around a destination.

An operator schedules a build; the backend runs it in a bounded background pool and publishes the result as a
versioned area record. Plans read that record from the server: the browser never sends evidence back.

Steps of a build:
  1. map       OSM street graph around the destination (Overpass, cached per area)
  2. parcels   (flag parcel_widths) cadastral parcel-gap estimates, deep scan on the legal ingress/egress paths
  3. listings  Chợ Tốt + Alonhadat alley-house listings of the 2 nearest districts, cached 12 h
  4. match     regex-v1 extraction, then alley-chain name matching to the OSM ways of this area
  5. news      street news (reference only, not Width Evidence)
  6. photos    (flag ai_photo_evidence) the model reads listing photos; only an operator approval makes a reading
               Observed evidence

Limits: one build per area at a time, MAX_RUNNING builds in parallel, MAX_QUEUED waiting, BUILD_DEADLINE_S per
build. Only a build that finished every step is published; a failed or timed-out build leaves the previous record.
Chợ Tốt has no geo search, so listings are pulled by district and kept only if they name a street of this area.
"""
from __future__ import annotations

import hashlib
import os
import fcntl
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from . import ai, alonhadat, flags, news, parcels
from .config import CACHE, ROOT, STORE
from .deadline import Expired, timeout
from .osm import area_key, build_graph, haversine, strip_accents
from .storage import LRU, CorruptState, read_json, write_json

sys.path.insert(0, str(ROOT / "pipelines"))
from common import norm_name  # noqa: E402
from extract_regex import Gazetteer, _chain_from, extract  # noqa: E402

VN_TZ = timezone(timedelta(hours=7))
API = "https://gateway.chotot.com/v1/public/ad-listing"
REGIONS = "https://gateway.chotot.com/v1/public/web-proxy-api/loadRegions"
HEADERS = {"User-Agent": "VaoDuoc-hackathon/0.2 (MLAI Hackathon 2026)"}
DIR = CACHE / "live"
AREAS_DIR = DIR / "areas"
PHOTO_REVIEWS = STORE / "photo_reviews.json"
TTL = timedelta(hours=12)    # listing cache and area record lifetime
SCHEMA_VERSION = 1
PAGE, PAGES = 50, 4          # per district and listing type
DISTRICTS = 2
CHAIN_MAX_M = 1000.0
HXH_FLAG = 2                 # pty_characteristics code for "Hẻm xe hơi"
MAX_PHOTOS = 12              # model calls per build
PHOTOS_PER_LISTING = 2
MAX_RUNNING, MAX_QUEUED = 2, 4
BUILD_DEADLINE_S = 300.0
PARCEL_BUDGET_S = 150.0      # the parcel step's share; the rest of the build still has time after a slow portal
JOB_KEEP_S = 600             # a finished job stays visible to pollers this long
KEY_RE = re.compile(r"^(demo|\d{1,2}\.\d{3}_\d{3}\.\d{3})$")


class Busy(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


def _left(job: dict, limit: float) -> float:
    """HTTP timeout for the next call of this build; Expired once the build deadline has passed."""
    return timeout(job.get("deadline"), limit)


# ---------- districts ----------

def _districts(deadline: float | None = None) -> list[dict]:
    """Every Chợ Tốt district of Ho Chi Minh City (region 13000) with its centroid."""
    path = DIR / "chotot_hcmc_districts_v2.json"
    if path.exists():
        return json.loads(path.read_text())
    regions = httpx.get(REGIONS, headers=HEADERS, timeout=timeout(deadline, 20)).json()["regionFollowId"]["entities"]["regions"]
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


def nearest_districts(lat: float, lon: float, n: int = DISTRICTS, deadline: float | None = None) -> list[dict]:
    return sorted(_districts(deadline), key=lambda d: haversine(lat, lon, d["lat"], d["lon"]))[:n]


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
        r = httpx.get(API, params=params, headers=HEADERS, timeout=_left(job, 30))
        r.raise_for_status()
        batch = r.json().get("ads", [])
        ads += batch
        job["counts"]["fetched"] += len(batch)
        if len(batch) < PAGE:
            break
        time.sleep(0.8)
    write_json(path, {"fetched_at": stamp.isoformat(), "ads": ads})
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
    """Model readings of listing photos (raw, cached). Review status lives in PHOTO_REVIEWS, not here."""
    path = _photo_path(key)
    done = {p["image_url"]: p for p in read_json(path, [])}
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
               "alley": r["osm_name"], "listing_url": r["url"], "posted_at": r["posted_at"]}
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=_left(job, 20))
            mime = resp.headers.get("content-type", "image/jpeg").split(";")[0]
            out = ai.read_listing_photo(resp.content, mime if mime.startswith("image/") else "image/jpeg",
                                        deadline=job["deadline"])
            rec.update({k: out.get(k) for k in ("shows_alley", "view", "alley_width_m", "reference",
                                                 "cars_visible", "confidence", "notes", "gate", "model")})
            rec["width_m"] = out.get("alley_width_m")
        except Expired:
            rec.update({"gate": "ERROR", "notes": "hết thời hạn thu thập"})
        except Exception as exc:  # one bad photo must not stop the build
            rec.update({"gate": "ERROR", "notes": str(exc)[:200]})
        job["counts"]["photos_read"] += 1
        return rec

    with ThreadPoolExecutor(4) as pool:
        for rec in pool.map(read, todo):
            done[rec["image_url"]] = rec
    write_json(path, list(done.values()), indent=1)
    return list(done.values())


_review_lock = threading.Lock()


def _photo_reviews() -> dict:
    try:
        return read_json(PHOTO_REVIEWS, {})
    except CorruptState:
        return {}  # unreadable reviews: every photo stays pending, never auto-approved


def review_photo(photo_id: str, approve: bool, reviewer: str) -> dict:
    """An operator's decision on one listing-photo reading. Idempotent; the newest decision wins."""
    with _review_lock:
        reviews = read_json(PHOTO_REVIEWS, {})
        rec = {"status": "approved" if approve else "rejected", "reviewer": reviewer,
               "reviewed_at": datetime.now(VN_TZ).isoformat(timespec="seconds")}
        reviews[photo_id] = rec
        write_json(PHOTO_REVIEWS, reviews, indent=1)
    _plan_cache.clear()
    return rec


CITY_PARCELS = DIR / "city_parcels.json"
_city_stamp = None
_city_cache: dict = {}
_city_lock = threading.Lock()


def city_parcels() -> dict:
    """Crawler-owned shallow results, reloaded only after an atomic replacement."""
    global _city_stamp, _city_cache
    with _city_lock:
        try:
            st = CITY_PARCELS.stat()
            stamp = (st.st_mtime_ns, st.st_size)
        except FileNotFoundError:
            _city_stamp, _city_cache = None, {}
            return _city_cache
        if stamp != _city_stamp:
            data = json.loads(CITY_PARCELS.read_text())
            _city_cache, _city_stamp = data, stamp
        return _city_cache


def _merge_city(g, measured: list[dict]) -> list[dict]:
    city = city_parcels()
    by_way = {wid: {"way_id": wid, **city[str(wid)], "deep": bool(city[str(wid)].get("deep"))}
              for wid in g.ways if city.get(str(wid))}
    for p in measured:
        current = by_way.get(p["way_id"], {})
        if current.get("sample_strategy") == "campus-full-5m" and p.get("queried_at", "") <= current.get("queried_at", ""):
            continue  # an older partial destination scan must not mask the fresh full-way scan
        seen, existing = p.get("queried_at", ""), current.get("queried_at", "")
        if seen and existing and seen != existing:
            if seen > existing:
                by_way[p["way_id"]] = p
            continue
        if p.get("deep") or not by_way.get(p["way_id"], {}).get("deep"):
            by_way[p["way_id"]] = p
    return list(by_way.values())


def _atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    with tmp.open("w") as f:
        json.dump(value, f, ensure_ascii=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def _save_parcel_cache(path, cache, original=None):
    with path.with_suffix(".lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        current = json.loads(path.read_text()) if path.exists() else {}
        changes = cache if original is None else {k: v for k, v in cache.items() if k not in original or original[k] != v}
        current.update(changes)
        _atomic_json(path, current)


# ---------- area records (server-owned) ----------

_areas = LRU(32)
_area_lock = threading.Lock()
_plan_cache = LRU(32)  # area record merged with the current photo reviews, per area revision


def _area_path(key: str):
    if not KEY_RE.match(key):
        raise ValueError(f"invalid area key {key!r}")
    return AREAS_DIR / f"{key}.json"


def _load_area(key: str) -> dict | None:
    rec = _areas.get(key)
    if rec is not None:
        return rec
    try:
        rec = read_json(_area_path(key), None)
    except CorruptState:
        return None
    if rec and rec.get("schema_version") == SCHEMA_VERSION and rec.get("key") == key:
        _areas.put(key, rec)
        return rec
    return None


def _union_rows(previous, current, identity):
    rows = {identity(row): row for row in previous}
    rows.update({identity(row): row for row in current})
    return list(rows.values())


def _publish(job: dict) -> dict:
    key = job["key"]
    with _area_lock:
        prev = _load_area(key)
        now = datetime.now(VN_TZ)
        rec = {"schema_version": SCHEMA_VERSION, "key": key, "revision": (prev or {}).get("revision", 0) + 1,
               "collected_at": now.isoformat(timespec="seconds"), "expires_at": (now + TTL).isoformat(timespec="seconds"),
               "complete": job["complete"], "steps": job["steps"], "counts": job["counts"],
               "listings": _union_rows((prev or {}).get("listings", []), job["listings"], lambda r: r.get("url") or str(r.get("listing_id"))),
               "photos": _union_rows((prev or {}).get("photos", []), job["photos"], lambda r: r.get("id") or r.get("image_url")),
               "news": _union_rows((prev or {}).get("news", []), job["news"], lambda r: (r.get("street"), r.get("url"))),
               "parcels": _union_rows((prev or {}).get("parcels", []), job["parcels"], lambda r: r["way_id"])}
        write_json(_area_path(key), rec)
        _areas.put(key, rec)
    return rec


def area_status(lat: float, lon: float) -> tuple[dict | None, dict]:
    """The usable area record for a destination (or None) and a public status: fresh, partial, stale, missing."""
    key = area_key(lat, lon)
    rec = _load_area(key)
    job = _jobs.get(key)
    building = bool(job and job["state"] in ("queued", "running"))
    if not rec:
        return None, {"key": key, "state": "missing", "revision": None, "collected_at": None, "expires_at": None,
                      "building": building, "reason": "Chưa thu thập dữ liệu trực tiếp cho khu vực này"}
    status = {"key": key, "revision": rec["revision"], "collected_at": rec["collected_at"],
              "expires_at": rec["expires_at"], "building": building}
    if datetime.fromisoformat(rec["expires_at"]) <= datetime.now(VN_TZ):
        return None, {**status, "state": "stale", "reason": "Dữ liệu khu vực đã quá hạn 12 giờ nên không được dùng"}
    if not rec.get("complete"):
        status.update(state="partial", reason="Lần thu thập gần nhất thiếu một bước (xem chi tiết bước)")
    else:
        status.update(state="fresh", reason=None)
    reviews = _photo_reviews()
    rkey = (key, rec["revision"], json.dumps(reviews, sort_keys=True))
    merged = _plan_cache.get(rkey)
    if merged is None:
        photos = [{**p, "status": reviews.get(p["id"], {}).get("status", "pending")} for p in rec["photos"]]
        merged = {**rec, "photos": photos, "revision": f"{rec['revision']}:{hashlib.sha1(rkey[2].encode()).hexdigest()[:8]}"}
        _plan_cache.put(rkey, merged)
    return merged, status


def public_area(rec: dict | None) -> dict | None:
    """What the browser may see of an area record (for display only; it is never sent back)."""
    if not rec:
        return None
    return {"key": rec["key"], "revision": rec["revision"], "news": rec.get("news", []),
            "photos": [{k: p.get(k) for k in ("id", "image_url", "way_id", "alley", "listing_url", "posted_at",
                                              "status", "view", "width_m", "reference", "confidence", "notes",
                                              "gate", "shows_alley")} for p in rec.get("photos", [])]}


# ---------- build jobs ----------

STEPS = ("map", "parcels", "listings", "match", "news", "photos")
_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()
_pool = ThreadPoolExecutor(MAX_RUNNING, thread_name_prefix="area-build")


def _step(job: dict, name: str, state: str, detail: str = "") -> None:
    job["steps"][name] = {"state": state, "detail": detail}


def _run(job: dict, lat: float, lon: float) -> None:
    key = job["key"]
    job["state"] = "running"
    job["started_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
    job["deadline"] = time.monotonic() + BUILD_DEADLINE_S
    try:
        _step(job, "map", "running")
        g = build_graph(lat, lon, deadline=job["deadline"])
        origin = {"demo-cache": "bản tải sẵn", "cache": "cache"}.get(g.source.split(":")[0], "Overpass trực tiếp")
        _step(job, "map", "done", f"{len(g.ways)} đoạn đường OSM ({origin})")

        if flags.enabled("parcel_widths"):
            _step(job, "parcels", "running")
            cache_path = DIR / "parcels.json"
            try:
                cache = read_json(cache_path, {})
            except CorruptState:
                cache = {}
            original_cache = cache.copy()
            # The planning portal can be very slow: parcels get their own share of the deadline, so a slow portal
            # leaves a partial record (unmeasured ways stay unknown) instead of losing listings and news too.
            parcel_deadline = min(job["deadline"], time.monotonic() + PARCEL_BUDGET_S)
            try:
                deep = flags.enabled("parcel_deep_scan")
                job["parcels"] = parcels.measure_area(g, lat, lon, cache, haversine, deep=deep,
                                                      deadline=parcel_deadline, city_cache=city_parcels())
                _step(job, "parcels", "done",
                      f"{len(job['parcels'])} đường có ước tính khoảng trống từ hình học thửa đất"
                      + ("; lối vào/ra lấy mẫu sâu mỗi 5 m trong giới hạn" if deep else ""))
            except parcels.DeadlineExceeded as exc:
                _save_parcel_cache(cache_path, cache, original_cache)
                if time.monotonic() >= job["deadline"] - 0.5:
                    raise Expired("hết thời hạn 300 giây khi đo thửa đất")
                job["parcels"], job["complete"] = getattr(exc, "partial", []), False
                _step(job, "parcels", "error",
                      f"Cổng quy hoạch chậm: dừng đo sau {PARCEL_BUDGET_S:.0f} giây, đã đo {len(job['parcels'])} "
                      "đường; các đường chưa đo vẫn là chưa rõ")
            except (parcels.Blocked, parcels.Unavailable):
                job["complete"] = False
                _step(job, "parcels", "error", "Cổng quy hoạch tạm chặn truy vấn; thử lại sau")
            _save_parcel_cache(cache_path, cache, original_cache)
        else:
            _step(job, "parcels", "skipped", "Đã tắt")

        job["parcels"] = _merge_city(g, job["parcels"])

        _step(job, "listings", "running")
        ds = nearest_districts(lat, lon, deadline=job["deadline"])
        ads = []
        for d in ds:
            for st in ("s", "u"):
                ads += _pull(d["region"], d["id"], st, job)
        n_chotot = len(ads)
        aln_counts: dict = {}
        for d in ds:
            _left(job, 1)
            try:
                ads += alonhadat.pull_district(d["name"], DIR, aln_counts, job["deadline"])
            except Expired:
                raise
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

        _left(job, 1)
        _step(job, "news", "running")
        streets = _streets_near(g, lat, lon)
        job["news"] = news.news_for(streets, job["deadline"])
        _step(job, "news", "done", f"{len(job['news'])} tin về {', '.join(streets[:3])}" if streets else "không có tên đường gần")

        if flags.enabled("ai_photo_evidence") and ai.provider():
            _step(job, "photos", "running")
            job["photos"] = _photos(key, rows, job)
            useful = [p for p in job["photos"] if p.get("width_m")]
            _step(job, "photos", "done", f"{len(job['photos'])} ảnh đã đọc, {len(useful)} ảnh có bề rộng (chờ duyệt)")
        else:
            _step(job, "photos", "skipped", "Bật “AI đọc ảnh tài xế gửi” để đọc ảnh tin rao")
        _left(job, 1)
        rec = _publish(job)
        job["state"], job["revision"] = "done", rec["revision"]
    except Expired as exc:
        job["state"], job["error"] = "error", f"hết thời hạn {BUILD_DEADLINE_S:.0f} giây ({exc})"
    except Exception as exc:
        job["state"], job["error"] = "error", str(exc)[:300]
    job["finished_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
    job["_finished"] = time.monotonic()
    for step in job["steps"].values():  # steps a failed build never reached are not "pending" forever
        if job["state"] == "error" and step["state"] in ("pending", "running"):
            step["state"] = "skipped"


def _prune() -> None:
    now = time.monotonic()
    for k in [k for k, j in _jobs.items() if j.get("_finished") and now - j["_finished"] > JOB_KEEP_S]:
        del _jobs[k]


def schedule(lat: float, lon: float) -> dict:
    """Start (or join) the build for this area. Raises Busy when the bounded pool is full."""
    key = area_key(lat, lon)
    with _jobs_lock:
        _prune()
        job = _jobs.get(key)
        if job and job["state"] in ("queued", "running"):
            return public_job(job)  # single flight: a second request joins the running build
        active = [j for j in _jobs.values() if j["state"] in ("queued", "running")]
        if len(active) >= MAX_RUNNING + MAX_QUEUED:
            raise Busy(retry_after=30)
        job = {"key": key, "state": "queued", "queued_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
               "started_at": None, "finished_at": None, "error": None, "revision": None, "complete": True,
               "steps": {s: {"state": "pending", "detail": ""} for s in STEPS},
               "counts": {"fetched": 0, "unique": 0, "in_area": 0, "matched": 0, "alleys": 0,
                          "photos_total": 0, "photos_read": 0},
               "listings": [], "photos": [], "news": [], "parcels": []}
        _jobs[key] = job
        _pool.submit(_run, job, lat, lon)
        return public_job(job)


def job_status(key: str) -> dict | None:
    job = _jobs.get(key)
    return public_job(job) if job else None


def public_job(job: dict) -> dict:
    return {k: v for k, v in job.items()
            if k not in ("listings", "photos", "news", "parcels", "deadline") and not k.startswith("_")}


def run_sync(lat: float, lon: float) -> dict | None:
    """Build an area in the calling thread and return the published record (offline pipelines only)."""
    key = area_key(lat, lon)
    job = {"key": key, "state": "queued", "error": None, "revision": None, "complete": True,
           "steps": {s: {"state": "pending", "detail": ""} for s in STEPS},
           "counts": {"fetched": 0, "unique": 0, "in_area": 0, "matched": 0, "alleys": 0,
                      "photos_total": 0, "photos_read": 0},
           "listings": [], "photos": [], "news": [], "parcels": []}
    _run(job, lat, lon)
    return _load_area(key) if job["state"] == "done" else None


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
