"""City-wide, resumable Declared evidence. No planning-portal requests.

python3 pipelines/listings_city.py fetch --max-pages 100
python3 pipelines/listings_city.py build [--llm-budget 0]
python3 pipelines/listings_city.py run --loop --interval-hours 12

Raw pages, checkpoints and content-hash LLM results are private under data/raw/.
Only compact, sourced bounds and non-personal street geometry are published.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "pipelines"))
import httpx
from common import USER_AGENT, fold, norm_name
from extract_regex import Gazetteer, _chain_from, extract
from app.config import CACHE, DATA, HCMC_BBOX
from app.osm import AreaGraph, Way, DRIVABLE, FOOT_ONLY, MAIN, haversine

RAW = DATA / "raw/listings_city"
OUT = CACHE / "live/declared_index.json"
INVENTORY = CACHE / "live/evidence_inventory.json"
API = "https://gateway.chotot.com/v1/public/ad-listing"
REGIONS = "https://gateway.chotot.com/v1/public/web-proxy-api/loadRegions"
HEADERS = {"User-Agent": USER_AGENT}
OPEN = 40.0


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def atomic(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def read(path, default=None):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {} if default is None else default


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class PoliteHTTP:
    """One sequential request stream; persist host-wide Retry-After across runs."""
    def __init__(self, delay=1.5):
        self.delay = max(1.5, delay)
        self.last = 0.0
        self.state_path = RAW / "http_state.json"
        self.state = read(self.state_path)
        self.calls = Counter()
        self.robots = {}
        self.client = httpx.Client(headers=HEADERS, follow_redirects=True, timeout=30)

    def get(self, url, **kwargs):
        host = urlparse(url).netloc
        if self.state.get(host, {}).get("retry_at", 0) > time.time():
            raise RuntimeError("source_in_persisted_cooldown")
        time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
        self.last = time.monotonic()
        self.calls[host] += 1
        r = self.client.get(url, **kwargs)
        if r.status_code in (403, 429, 500, 502, 503, 504):
            from email.utils import parsedate_to_datetime
            retry = r.headers.get("retry-after", "")
            try:
                seconds = float(retry)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(retry).timestamp() - time.time()
                except (TypeError, ValueError):
                    seconds = 900
            failures = self.state.get(host, {}).get("failures", 0) + 1
            self.state[host] = {"retry_at": time.time() + max(seconds, min(86400, 900 * 2 ** min(failures - 1, 6))),
                                "failures": failures, "status": r.status_code}
            atomic(self.state_path, self.state)
            raise RuntimeError(f"source_backoff_http_{r.status_code}")
        r.raise_for_status()
        return r


def districts(http=None):
    path = CACHE / "live/chotot_hcmc_districts_v2.json"
    if path.exists():
        return read(path, [])
    data = http.get(REGIONS).json()["regionFollowId"]["entities"]["regions"]["13000"]
    return [{"id": int(aid), "region": 13000, "name": a["name"]} for aid, a in data["area"].items()]


def sanitize(a, source="chotot"):
    keys = ("ad_id", "list_id", "subject", "body", "street_name", "street_number", "latitude", "longitude",
            "pty_characteristics", "list_time", "posted_at", "url", "road_front_m", "kind")
    out = {k: a[k] for k in keys if k in a}
    seller = a.get("account_id") or a.get("account_oid")
    out["seller_hash"] = a.get("seller_hash") or (digest(str(seller))[:20] if seller else None)
    out["source"] = source
    return out


def archive_ads(ads):
    """Append immutable sanitized listing revisions; later refreshes never erase evidence."""
    RAW.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RAW / 'listings.sqlite', timeout=10)
    try:
        con.execute('CREATE TABLE IF NOT EXISTS ads (hash TEXT PRIMARY KEY, payload TEXT NOT NULL)')
        with con:
            con.executemany('INSERT OR IGNORE INTO ads VALUES (?,?)', [
                (digest(a['source'] + ':' + str(a.get('ad_id')) + ':' + a.get('subject', '') + '\n' + a.get('body', '')),
                 json.dumps(a, ensure_ascii=False)) for a in ads])
        return [json.loads(row[0]) for row in con.execute('SELECT payload FROM ads ORDER BY rowid')]
    finally:
        con.close()


def fetch(max_pages=100, ttl_hours=12, delay=1.5, alonhadat=True):
    http = PoliteHTTP(delay)
    report = {"started_at": now(), "partitions": [], "errors": []}
    ds = districts(http)
    # Round-robin pages: every district/type gets breadth before deep pagination.
    jobs = [(d, st) for d in ds for st in ("s", "u")]
    stopped = set()
    for page in range(max_pages):
        for d, st in jobs:
            part = f"{d['id']}_{st}"
            if part in stopped:
                continue
            path = RAW / "chotot" / f"{part}_{page:04}.json"
            cached = read(path)
            if cached and time.time() - cached.get("fetched_unix", 0) < ttl_hours * 3600:
                batch = cached.get("ads", [])
            else:
                try:
                    r = http.get(API, params={"region_v2": d["region"], "area_v2": d["id"], "cg": 1020,
                                             "house_type": 3, "st": st, "limit": 50, "o": page * 50})
                    doc = r.json()
                    if not isinstance(doc.get("ads"), list):
                        raise ValueError("missing_ads")
                    batch = doc["ads"]
                    # An API can cap offsets by repeating the first page. Stop on zero new ids.
                    batch = [sanitize(a) for a in batch]
                    atomic(path, {"fetched_at": now(), "fetched_unix": time.time(), "district": d["name"],
                                  "district_id": d["id"], "listing_type": st, "page": page, "ads": batch})
                    archive_ads([{**a, 'district_id': d['id'], 'listing_type': st, 'fetched_at': now()} for a in batch])
                    print(json.dumps({"district": d["name"], "type": st, "page": page, "ads": len(batch)}), flush=True)
                except Exception as exc:
                    # Never stringify HTTP exceptions: request URLs might carry credentials in other clients.
                    reason = str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__
                    report["errors"].append({"partition": part, "page": page, "reason": reason})
                    stopped.add(part)
                    continue
            previous = {a.get("ad_id") for p in (RAW / "chotot").glob(f"{part}_*.json")
                        if int(p.stem.rsplit("_", 1)[1]) < page for a in read(p).get("ads", [])}
            fresh = {a.get("ad_id") for a in batch} - previous
            report["partitions"].append({"partition": part, "page": page, "ads": len(batch), "new_ids": len(fresh)})
            if len(batch) < 50 or not fresh:
                stopped.add(part)
        atomic(RAW / "fetch_report.json", {**report, "updated_at": now(), "http_calls": dict(http.calls)})
        if len(stopped) == len(jobs):
            break
    if alonhadat:
        fetch_alonhadat(http, ds, max_pages, ttl_hours, report)
    report.update(finished_at=now(), http_calls=dict(http.calls))
    atomic(RAW / "fetch_report.json", report)
    atomic(RAW / 'fetch_runs' / f"{report['started_at'].replace(':','-')}_{os.getpid()}.json", report)
    http.client.close()
    return report


def fetch_alonhadat(http, ds, max_pages, ttl_hours, report):
    """Robots-authorized pages only; any blocking response stops this host."""
    base = "https://alonhadat.com.vn"
    try:
        robots = RobotFileParser()
        robots.parse(http.get(base + "/robots.txt").text.splitlines())
        idx = read(CACHE / "live/alonhadat_hcmc_districts.json")
        if not idx:
            url = base + "/can-ban-nha-dat/ho-chi-minh"
            if not robots.can_fetch(USER_AGENT, url):
                report["alonhadat"] = {"status": "robots_disallowed"}
                return
            text = http.get(url).text
            idx = {m.group(2): [int(m.group(1)), m.group(2)] for m in re.finditer(
                r"/nha-dat/can-ban/nha-dat/ho-chi-minh/(\d+)/([a-z0-9-]+)\.html", text)}
        from app.alonhadat import _text
        crawl_delay = robots.crawl_delay(USER_AGENT) or robots.crawl_delay('*')
        if crawl_delay:
            http.delay = max(http.delay, crawl_delay)
        for d in ds:
            slug = re.sub(r"[^a-z0-9]+", "-", fold(d["name"])).strip("-")
            if slug not in idx:
                continue
            aid, slug = idx[slug]
            for mode in ("can-ban", "cho-thue"):
                seen = set()
                for page in range(1, max_pages + 1):
                    suffix = "" if page == 1 else f"/trang--{page}"
                    url = f"{base}/nha-dat/{mode}/nha-trong-hem/ho-chi-minh/{aid}/{slug}{suffix}.html"
                    if not robots.can_fetch(USER_AGENT, url):
                        break
                    pagepath = RAW / "alonhadat_pages" / f"{aid}_{mode}_{page}.json"
                    cached = read(pagepath)
                    if cached and time.time() - cached.get("fetched_unix", 0) < ttl_hours * 3600:
                        urls = cached["urls"]
                    else:
                        text = http.get(url).text
                        urls = list(dict.fromkeys(base + u for u in re.findall(r"href=['\"](/[a-z0-9-]+-\d{6,}\.html)['\"]", text)))
                        atomic(pagepath, {"urls": urls, "fetched_unix": time.time()})
                    fresh = set(urls) - seen
                    if not fresh:
                        break
                    seen.update(urls)
                    for detail in sorted(fresh):
                        path = RAW / "alonhadat" / f"{digest(detail)}.json"
                        if path.exists() and time.time() - path.stat().st_mtime < ttl_hours * 3600:
                            continue
                        if not robots.can_fetch(USER_AGENT, detail):
                            continue
                        t = http.get(detail).text
                        cells = [_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", t, re.S)]
                        table = dict(zip(cells[::2], cells[1::2]))
                        def field(pattern):
                            m = re.search(pattern, t, re.S)
                            return _text(m.group(1)) if m else ""
                        street = field(r"itemprop=['\"]streetAddress['\"]>(.*?)</span>")
                        num = re.match(r"^\s*([\d]+[A-Za-z]?(?:/[\dA-Za-z]+)*)\s*,?\s*(.*)$", street)
                        road = re.match(r"([\d.,]+)\s*m", table.get("Đường trước nhà", ""))
                        ad = {"ad_id": "aln" + digest(detail)[:16], "url": detail,
                              "subject": field(r"<h1[^>]*>(.*?)</h1>"),
                              "body": field(r"itemprop=['\"]description['\"]>(.*?)</p>"),
                              "street_name": num.group(2) if num else street,
                              "street_number": num.group(1) if num else "", "kind": table.get("Loại BDS", ""),
                              "road_front_m": float(road.group(1).replace(",", ".")) if road else None,
                              "posted_at": field(r"itemprop=['\"]datePosted['\"] datetime=['\"]([\d-]+)['\"]"),
                              "source": "alonhadat", "district_id": d["id"], "listing_type": mode}
                        atomic(path, ad)
                        archive_ads([ad])
        report["alonhadat"] = {"status": "finished"}
    except Exception as exc:
        report["alonhadat"] = {"status": "unavailable", "reason": str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__}


def inventory(force=False):
    """Read ALL cached routing cells; no OSM or cadastral network calls."""
    paths = sorted((CACHE / "osm").glob("area_*.json")) + sorted((CACHE / "osm/city_batches").glob("*.json"))
    demo = CACHE / "osm/demo_binhthanh.json"
    if demo.exists():
        paths.append(demo)
    fingerprint = digest(json.dumps([(p.name, p.stat().st_mtime_ns, p.stat().st_size) for p in paths]))
    old = read(INVENTORY)
    if not force and old.get("fingerprint") == fingerprint:
        return old
    rows = {}
    s, west, n, east = HCMC_BBOX
    for p in paths:
        data = read(p)
        elements = data.get("elements", [])
        nodes = {e["id"]: (e["lat"], e["lon"]) for e in elements if e["type"] == "node" and "lat" in e}
        for el in elements:
            if el["type"] != "way" or not el.get("tags", {}).get("highway"):
                continue
            coords = [[nodes[k][1], nodes[k][0]] for k in el.get("nodes", []) if k in nodes]
            if len(coords) < 2 or not any(s <= y <= n and west <= x <= east for x, y in coords):
                continue
            wid = str(el["id"])
            if wid in rows and len(rows[wid]["coords"]) >= len(coords):
                continue
            rows[wid] = {"id": el["id"], "tags": el["tags"], "coords": coords,
                         "osm_timestamp": el.get("timestamp", "")}
    result = {"schema_version": 1, "generated_at": now(), "fingerprint": fingerprint,
              "routing_cells": sum(p.name.startswith("area_") for p in paths), "cache_files": len(paths),
              "scope": "Union of cached HCMC routing cells; not full administrative-city coverage", "ways": rows}
    atomic(INVENTORY, result)
    return result


def graph_for(rows):
    g = AreaGraph((10.8, 106.7))
    node_id = 0
    by_name = defaultdict(list)
    for r in rows.values():
        ids = []
        for x, y in r["coords"]:
            node_id += 1
            g.nodes[node_id] = (y, x)
            ids.append(node_id)
        w = Way(r["id"], r["tags"], ids)
        g.ways[w.id] = w
        if w.name:
            by_name[norm_name(w.name)].append(w)
    return g, by_name


def all_ads():
    rows = {}
    for directory in (CACHE / "live/chotot", RAW / "chotot"):
        for path in sorted(directory.glob("*.json")):
            doc = read(path)
            for a in doc.get("ads", []):
                a = sanitize(a)
                a["district_id"] = doc.get("district_id") or int(path.stem.split("_")[0])
                a["listing_type"] = doc.get("listing_type") or path.stem.split("_")[1]
                a["fetched_at"] = doc.get("fetched_at", "")
                rows[("chotot", str(a.get("ad_id")))] = a
    for path in sorted((CACHE / "live/alonhadat").glob("*.json")):
        doc = read(path)
        for a in doc.get("ads", []):
            a = {**sanitize(a, "alonhadat"), "fetched_at": doc.get("fetched_at", "")}
            rows[("alonhadat", str(a.get("ad_id")))] = a
    for path in sorted((RAW / "alonhadat").glob("*.json")):
        a = read(path)
        rows[("alonhadat", str(a.get("ad_id")))] = a
    archived = archive_ads(list(rows.values()))
    raw_count = len({(a['source'], str(a.get('ad_id'))) for a in archived})
    # Remove exact cross-source reposts regardless of ad id.
    seen, unique = set(), []
    for a in sorted(archived, key=lambda a: str(a.get("list_time", "")), reverse=True):
        key = digest(fold(a.get("subject", "") + "\n" + a.get("body", "")))
        if key not in seen:
            unique.append(a)
            seen.add(key)
    return unique, raw_count


class FreeExtractor:
    """Hard lifetime call cap, atomic reservations and cached successes AND errors.

    No app.ai/provider fallback: only GEMINI_API_KEY* environment names qualify.
    The paid key's VALUE is excluded even if aliased under a free-key name.
    """
    def __init__(self, budget=0):
        self.remaining = min(1500, max(0, budget))
        self.calls = self.accepted = 0
        self.keys = list(dict.fromkeys(v for k, v in sorted(os.environ.items())
                    if re.fullmatch(r"GEMINI_API_KEY(?:_.*|\d*)", k) and v and v != os.environ.get("PROD_GEMINI_API_KEY")))
        self.model = os.environ.get("EVIDENCE_FREE_MODEL", "gemini-2.5-flash")
        RAW.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(RAW / "llm_cache.sqlite")
        self.db.execute("CREATE TABLE IF NOT EXISTS results (hash TEXT PRIMARY KEY, result TEXT, reserved_at TEXT)")
        self.db.commit()

    def extract(self, text, baseline):
        prompt = ('Extract ONLY explicit own-alley access claims. Nearby alleys and distance are NOT width. '
                  'Do not infer a street address. JSON: {"width_m":number|null,"access_claim":'
                  '"xe_hoi"|"xe_hoi_tranh"|"ba_gac"|"xe_may"|null,"width_quote":string,'
                  '"access_quote":string,"own_alley":boolean}. Exact verbatim quotes required. Listing:\n' + text[:14000])
        key = digest(self.model + "\nquote-gate-v1\n" + prompt)
        hit = self.db.execute("SELECT result FROM results WHERE hash=?", (key,)).fetchone()
        if hit:
            return json.loads(hit[0]) if hit[0] else {"gate": "REVIEW", "reason": "interrupted_reservation"}
        if not self.remaining or not self.keys:
            return {"gate": "REVIEW", "reason": "no_free_call"}
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT COUNT(*) FROM results").fetchone()[0] >= 1500:
                return {"gate": "REVIEW", "reason": "lifetime_cap"}
            try:
                self.db.execute("INSERT INTO results VALUES (?,NULL,?)", (key, now()))
            except sqlite3.IntegrityError:
                return {"gate": "REVIEW", "reason": "already_reserved"}
        self.remaining -= 1
        self.calls += 1
        try:
            # Key is a header, never a query parameter or log value.
            r = httpx.post(f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent",
                           headers={"x-goog-api-key": self.keys[0]},
                           json={"contents": [{"parts": [{"text": prompt}]}],
                                 "generationConfig": {"temperature": 0, "responseMimeType": "application/json"}}, timeout=40)
            if r.status_code in (400, 401, 403, 404, 429):
                self.remaining = 0  # honor quota/configuration failure, never rotate keys to bypass it
            r.raise_for_status()
            result = json.loads(r.json()["candidates"][0]["content"]["parts"][0]["text"])
            valid = result.get("own_alley") is True
            for field, quote in (("width_m", "width_quote"), ("access_claim", "access_quote")):
                v = result.get(field)
                if v is not None:
                    q = result.get(quote)
                    valid &= isinstance(q, str) and bool(q.strip()) and q in text
                    # A quote must itself pass the deterministic extractor.
                    qex = extract(q or "")
                    valid &= qex.get(field) == v
                    if baseline.get(field) is not None:
                        valid &= baseline[field] == v
            w = result.get("width_m")
            valid &= w is None or (isinstance(w, (int, float)) and not isinstance(w, bool) and math.isfinite(w) and 1 <= w <= 15)
            valid &= result.get("access_claim") in (None, "xe_hoi", "xe_hoi_tranh", "ba_gac", "xe_may")
            result["gate"] = "ACCEPT" if valid and (w or result.get("access_claim")) else "REVIEW"
        except Exception as exc:
            result = {"gate": "REVIEW", "reason": type(exc).__name__}
            status = getattr(getattr(exc, 'response', None), 'status_code', None)
            if status is not None:
                result['http_status'] = status
        with self.db:
            self.db.execute("UPDATE results SET result=? WHERE hash=?", (json.dumps(result), key))
        time.sleep(4)
        self.accepted += result.get("gate") == "ACCEPT"
        return result


def listing_bounds(ex, method):
    claim = ex.get("access_claim")
    access = {"xe_hoi": (2.2, OPEN), "xe_hoi_tranh": (4.5, OPEN), "ba_gac": (.5, 3.), "xe_may": (.5, 2.2)}
    if method == "alley_chain_parent":
        return (access[claim], False) if claim in ("xe_hoi", "xe_hoi_tranh") else (None, False)
    bounds = []
    if ex.get("width_m") is not None:
        bounds.append((.5, ex["width_m"]))
    if claim in access:
        bounds.append(access[claim])
    if not bounds:
        return None, False
    lo, hi = max(b[0] for b in bounds), min(b[1] for b in bounds)
    conflict = lo > hi
    return ((min(b[0] for b in bounds), max(b[1] for b in bounds)) if conflict else (lo, hi)), conflict


def aggregate(records):
    out = {}
    by_way = defaultdict(list)
    for r in records:
        by_way[str(r["way_id"])].append(r)
    for wid, rs in by_way.items():
        # Count a seller/property once per way; preserve every independent claim for a safe hull.
        # Join shared seller, property address OR identical content. This avoids
        # counting the same house advertised by two brokers as corroboration.
        parent = list(range(len(rs)))
        def root(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i
        seen = {}
        for i, r in enumerate(rs):
            for key in r.get('independence_keys', [r['independence_key']]):
                if key in seen:
                    parent[root(i)] = root(seen[key])
                seen[key] = i
        representatives = {root(i): r for i, r in enumerate(rs)}
        independent = set(representatives)
        bounds = [r["bounds"] for r in rs]
        signatures = {(r.get("access_claim"), r.get("width_m")) for r in rs}
        votes = Counter((r.get("access_claim"), r.get("width_m")) for r in representatives.values())
        dates = sorted(r["posted_at"] for r in rs if r.get("posted_at"))
        # Numeric widths disagree if their quoted maxima differ; do not tighten to the smallest advertisement.
        review = len(signatures) > 1 or any(r["review"] for r in rs)
        out[wid] = {"lo": min(b[0] for b in bounds), "hi": max(b[1] for b in bounds),
                    "n_listings": len(rs), "independent_listings": len(independent),
                    "independence": "shared seller, exact property address or exact text joins listings; not verified ownership",
                    "agreement": round(max(votes.values()) / len(independent), 3), "review": review,
                    "first_posted": dates[0] if dates else "", "last_posted": dates[-1] if dates else "",
                    "sources": dict(Counter(r["source"] for r in rs)),
                    "claims": [{k: r[k] for k in ("listing_id", "url", "posted_at", "source", "width_m", "access_claim", "method", "bounds", "extractor")} for r in rs],
                    "name": rs[0]["name"]}
    return out


def cadastral():
    city = read(CACHE / "live/city_parcels.json")
    out = {str(k): v for k, v in city.items() if isinstance(v, dict) and v.get("samples")}
    for path in sorted((CACHE / "live/areas").glob("*.json")):
        for p in read(path).get("parcels", []):
            wid = str(p["way_id"])
            if p.get("samples") and (wid not in out or p.get("deep")):
                out[wid] = p
    return out


def width_class(w):
    return "xe_may" if w < 2 else "ba_gac" if w < 3 else "xe_hoi" if w < 5 else "xe_hoi_tranh"


def validation(records, cad):
    confusion = defaultdict(Counter)
    errors, overlaps, rows = [], [], []
    for r in records:
        pc = cad.get(str(r["way_id"]))
        if not pc:
            continue
        gaps = sorted(c["gap_m"] for c in pc.get("cuts", []) if c.get("gap_m") is not None)
        if not gaps:
            continue
        gap = gaps[len(gaps) // 5] if len(gaps) >= 5 else gaps[0]
        pred = r.get("access_claim") or (width_class(r["width_m"]) if r.get("width_m") else None)
        if pred:
            confusion[pred][width_class(gap)] += 1
        if r.get("width_m"):
            errors.append(r["width_m"] - gap)
        ws = sorted(pc["samples"])
        lo = ws[len(ws)//5] if len(ws) >= 5 else ws[0]
        hi = (ws[len(ws)*4//5] if len(ws) >= 5 else ws[-1]) + .3
        overlap = max(lo, r["bounds"][0]) <= min(hi, r["bounds"][1])
        overlaps.append(overlap)
        rows.append({"way_id": r["way_id"], "listing_id": r.get("listing_id"), "claim": pred,
                     "parcel_gap_m": gap, "parcel_gap_class": width_class(gap), "interval_overlap": overlap,
                     "method": r.get("method")})
    matrix = {k: dict(v) for k, v in confusion.items()}
    total = sum(sum(v.values()) for v in confusion.values())
    exact = sum(v.get(k, 0) for k, v in confusion.items())
    return {"matched_records": len(rows), "matched_ways": len({r['way_id'] for r in rows}),
            "label_vs_parcel_gap_confusion": matrix, "label_class_records": total,
            "label_class_exact_pct": round(100*exact/total, 2) if total else None,
            "interval_overlap_pct": round(100*sum(overlaps)/len(overlaps), 2) if overlaps else None,
            "numeric_claims": len(errors), "numeric_mean_error_m": round(sum(errors)/len(errors), 3) if errors else None,
            "numeric_mae_m": round(sum(map(abs, errors))/len(errors), 3) if errors else None,
            "caveat": "Convenience overlap, geographically concentrated; parcel gaps are legal space, not measured Clear Width. Claim-level matrix includes parent claims separately identified in rows.",
            "rows": rows}


def fire_audit(inv, cad):
    """Reparse the ENTIRE annex; publish every unmatched item and reason, never force a false match."""
    from fire_access_4582 import parse, key, RAW as FIRE_RAW, WARDS
    existing = read(DATA / "official/fire_access_4582.json")
    if not FIRE_RAW.exists():
        return {}, {"status": "raw_annex_missing"}
    text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", FIRE_RAW.read_text())))
    items = parse(text)
    centres = read(WARDS)
    by_key = defaultdict(list)
    for wid, r in inv["ways"].items():
        if r["tags"].get("name"):
            by_key[key(r["tags"]["name"])].append(r)
    supplemental, audited, matched_ids = {}, [], set()
    old_ids = {str(w) for it in existing.get("items", []) for w in it["way_ids"]}
    for idx, it in enumerate(items):
        cands = by_key.get(key(it["name"]), [])
        centre = centres.get(it["ward"])
        reason = "no_named_osm_match"
        selected = []
        if cands and centre:
            generic = "/" not in it["name"] and len(key(it["name"])) < 12
            near = [(haversine(*centre, r["coords"][len(r['coords'])//2][1], r["coords"][len(r['coords'])//2][0]), r) for r in cands]
            near = [(d, r) for d, r in near if d <= (1500 if generic else 3000)]
            if near:
                dmin = min(d for d, _ in near)
                selected = [r for d, r in near if d <= dmin + 300]
            else:
                reason = "outside_ward_distance_gate"
        elif cands:
            clusters = {(round(r["coords"][len(r['coords'])//2][1], 2), round(r["coords"][len(r['coords'])//2][0], 2)) for r in cands}
            if len(clusters) == 1:
                selected = cands
            else:
                reason = "ambiguous_without_ward_centre"
        ids = sorted({str(r['id']) for r in selected})
        matched_ids.update(ids)
        audited.append({"item": idx, **it, "way_ids": ids, "status": "matched" if ids else reason})
        for wid in ids:
            if wid not in old_ids:
                supplemental[wid] = {"lo": .5, "hi": 3.5, "tier": "Declared", "source": "QĐ 4582/QĐ-UBND (kiểm tra toàn bộ phụ lục)",
                    "detail": "Xe chữa cháy không vào được; có thể do khúc cua, dây thấp hoặc ngõ cụt, không chỉ bề rộng.",
                    "observed_on": "2026-07-24", "url": existing.get("url", "")}
    records = [{"way_id": int(wid), "bounds": [.5, 3.5], "width_m": None, "access_claim": None} for wid in matched_ids]
    audit = {"parsed_items": len(items), "matched_items": sum(bool(i['way_ids']) for i in audited),
             "matched_ways": len(matched_ids), "existing_ways": len(old_ids), "new_ways": len(supplemental),
             "unmatched_items": sum(not i['way_ids'] for i in audited), "unmatched_reasons": dict(Counter(i['status'] for i in audited if not i['way_ids'])),
             "validation": validation(records, cad), "items": audited,
             "caveat": "No-access is not a width measurement; keep existing conservative Declared semantics, never promote to Official."}
    atomic(RAW / "fire_audit.json", audit)
    return supplemental, {k: v for k, v in audit.items() if k != "items"}


def build(llm_budget=0, force_inventory=False):
    started = time.monotonic()
    inv = inventory(force_inventory)
    g, by_name = graph_for(inv["ways"])
    # Reuse the established deepest-chain matcher with its 1 km disambiguation gate.
    from app.live import _match
    gaz = Gazetteer({w.name for w in g.ways.values() if w.name and not w.is_alley})
    ads, raw_count = all_ads()
    llm = FreeExtractor(llm_budget)
    records, reviews = [], []
    counts = Counter()
    districts_seen = defaultdict(Counter)
    for a in ads:
        street = a.get("street_name") or ""
        text = f"{a.get('subject', '')}\n{a.get('body', '')}\n{street}"
        ex = extract(text, street or None, gaz)
        flags = a.get("pty_characteristics") or []
        if not ex["access_claim"] and (2 in flags or "2" in flags):
            ex["access_claim"] = "xe_hoi"
        if a.get("source") == "alonhadat" and a.get("road_front_m") and ("hem" in fold(a.get("kind", "")) or "/" in a.get("street_number", "")):
            w = a["road_front_m"]
            if isinstance(w, (float, int)) and 1 <= w <= 15:
                ex["width_m"] = w
        ambiguous = len(ex["width_mentions_m"]) > 1 or (len(set(ex["access_claims_all"]) - {"xe_hoi", "xe_hoi_tranh"}) > 0 and "xe_hoi" in ex["access_claims_all"])
        extractor = "regex-v1"
        if ambiguous:
            counts["ambiguous"] += 1
            result = llm.extract(text, ex)
            reviews.append({"listing_id": str(a.get("ad_id")), "result": result, "content_hash": digest(text)})
            if result.get("gate") == "ACCEPT":
                ex.update({k: result.get(k) for k in ("width_m", "access_claim")})
                extractor = "free-gemini-quote-gate-v1"
            else:
                counts["review_excluded"] += 1
                continue
        if ex.get("width_m") is None and not ex.get("access_claim"):
            continue
        counts["usable_claim"] += 1
        districts_seen[str(a.get("district_id", "unknown"))]["usable_claim"] += 1
        chain = ex["alley_chain"]
        num = str(a.get("street_number") or "").strip().strip("/")
        if not chain and "/" in num and street:
            chain = _chain_from(num, re.sub(r"^Đường\s+", "", street))
        lat, lon = a.get("latitude"), a.get("longitude")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not math.isfinite(lat + lon):
            lat = lon = None
        # With no coordinate, require city-wide uniqueness. Existing matcher otherwise picks its first candidate.
        if lat is None:
            candidates = next((by_name[norm_name(c)] for c in reversed(chain) if norm_name(c) in by_name), [])
            if len(candidates) != 1:
                counts["ambiguous_location"] += 1
                continue
        way, method = _match(g, by_name, chain, lat, lon)
        if not way or not way.is_alley:
            continue
        bound, conflict = listing_bounds(ex, method)
        if bound is None:
            counts["parent_nonpropagating"] += 1
            continue
        posted = a.get("posted_at", "")
        if a.get("list_time"):
            posted = datetime.fromtimestamp(a['list_time']/1000, timezone.utc).isoformat(timespec="seconds")
        property_key = norm_name(chain[-1]) if num.count("/") >= 1 and chain else None
        identity = a.get("seller_hash") or property_key or digest(fold(text))
        independence_keys = ['content:' + digest(fold(text)), 'ad:' + a['source'] + ':' + str(a.get('ad_id'))]
        if a.get('seller_hash'):
            independence_keys.append('seller:' + a['seller_hash'])
        if property_key:
            independence_keys.append('property:' + property_key)
        records.append({"way_id": way.id, "name": way.name, "listing_id": str(a.get("ad_id")),
                        "url": a.get("url") or f"https://www.nhatot.com/{a.get('list_id')}.htm",
                        "source": a["source"], "posted_at": str(posted)[:10], "fetched_at": a.get("fetched_at", ""),
                        "independence_key": digest(str(identity))[:20], "independence_keys": independence_keys,
                        "bounds": list(bound), "method": method,
                        "width_m": ex["width_m"] if method == "alley_chain" else None,
                        "access_claim": ex["access_claim"], "review": conflict, "extractor": extractor})
        counts[method] += 1
        districts_seen[str(a.get("district_id", "unknown"))]["matched"] += 1
    product = aggregate(records)
    cad = cadastral()
    fire, fire_report = fire_audit(inv, cad)
    tag_report = osm_audit(inv, cad)
    report = {"generated_at": now(), "runtime_s": round(time.monotonic()-started, 2),
              "source_districts": len(districts()), "district_listing_type_partitions": len(list((CACHE / 'live/chotot').glob('*.json'))),
              "fetched_unique_ad_ids": raw_count, "deduplicated_listings": len(ads),
              "usable_claim_pct": round(100*counts['usable_claim']/max(1,len(ads)), 2),
              "counts": dict(counts), "ways_covered": len(product), "districts": dict(districts_seen),
              "all_districts": [{"id": d['id'], "name": d['name'],
                                 "deduplicated_listings": sum(a.get('district_id') == d['id'] for a in ads),
                                 **dict(districts_seen.get(str(d['id']), {}))} for d in districts()],
              "by_source": {src: {"listings": sum(a['source']==src for a in ads),
                                  "matched_records": sum(r['source']==src for r in records),
                                  "ways": len({r['way_id'] for r in records if r['source']==src}),
                                  "validation": validation([r for r in records if r['source']==src], cad)} for src in ('chotot','alonhadat')},
              "validation": validation(records, cad), "exact_chain_validation": validation([r for r in records if r['method']=='alley_chain'], cad),
              "free_llm_calls_this_build": llm.calls, "free_llm_accepted_this_build": llm.accepted,
              "free_llm_calls_lifetime": llm.db.execute('SELECT COUNT(*) FROM results').fetchone()[0],
              "paid_calls": 0, "portal_calls": 0, "fire_access": fire_report, "osm_tags": tag_report,
              "mapillary": {"status": "skipped_no_account_client_token", "ways": 0, "validation": None,
                            "registration_flow": "Account + registered application required; no configured token; no account creation performed",
                            "source_url": "https://github.com/mapillary/mapillary-js#installation-and-usage"}}
    atomic(RAW / "matched_records.json", records)
    atomic(RAW / "reviews.json", reviews)
    from geocode_unmatched import merge_declared
    atomic(OUT, merge_declared({"schema_version": 1, "tier": "Declared", "generated_at": now(), "ways": product,
                 "fire_supplemental": fire, "stats": {k:v for k,v in report.items() if k not in ('validation','exact_chain_validation','by_source','fire_access','osm_tags')}}))
    atomic(ROOT / "docs/eval/evidence-city.json", report)
    print(json.dumps({k:report[k] for k in ('runtime_s','fetched_unique_ad_ids','deduplicated_listings','usable_claim_pct','ways_covered','counts','free_llm_calls_this_build')}, ensure_ascii=False))
    return report


def osm_audit(inv, cad):
    """Audit width/est_width/maxwidth independently; lanes is only a road-class prior."""
    from app.evidence import _osm_bounds
    result = {}
    for tag in ('width', 'est_width', 'maxwidth', 'lanes'):
        rs, tagged = [], 0
        for wid, r in inv['ways'].items():
            w = Way(int(wid), r['tags'], [])
            if w.kind == 'main' or w.highway not in DRIVABLE | FOOT_ONLY or tag not in w.tags:
                continue
            tagged += 1
            for b in _osm_bounds(w):
                if b.source in ('OSM '+tag, 'OSM biển hạn chế chiều rộng') and (tag != 'maxwidth' or b.source == 'OSM biển hạn chế chiều rộng'):
                    if tag != 'maxwidth' and b.source != 'OSM '+tag:
                        continue
                    rs.append({'way_id':w.id,'bounds':[b.lo,b.hi], 'width_m':float(w.tags[tag]) if tag in ('width','est_width') else None,
                               'access_claim':None})
        result[tag] = {'tagged_non_main_ways':tagged,'usable_existing_bounds':len(rs),'validation':validation(rs,cad),
                       'decision':'existing Observed semantics retained; no precision promotion' if tag != 'lanes' else 'not integrated as Clear Width: lane count alone is insufficient'}
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('fetch','build','run'))
    p.add_argument('--max-pages',type=int,default=100)
    p.add_argument('--ttl-hours',type=float,default=12)
    p.add_argument('--delay',type=float,default=1.5)
    p.add_argument('--llm-budget',type=int,default=0)
    p.add_argument('--force-inventory',action='store_true')
    p.add_argument('--loop',action='store_true')
    p.add_argument('--interval-hours',type=float,default=12)
    p.add_argument('--no-alonhadat',action='store_true')
    args = p.parse_args()
    # Only this pipeline's process lock; never touches the cadastral crawler lease.
    import fcntl
    RAW.mkdir(parents=True,exist_ok=True)
    with (RAW/'engine.lock').open('a+') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another listings evidence engine is active')
        import signal
        import threading
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        lock.seek(0)
        lock.truncate()
        lock.write(str(os.getpid()))
        lock.flush()
        status_path = CACHE/'live/evidence_engine_status.json'
        status = {'pid':os.getpid(),'started_at':now(),'loop':args.loop,'command':args.command,
                  'free_llm_budget_per_cycle':min(1500,max(0,args.llm_budget)), 'paid_calls':0,'portal_calls':0}
        try:
            while not stop.is_set():
                status.update(state='running',cycle_started_at=now())
                atomic(status_path,status)
                try:
                    if args.command in ('fetch','run'):
                        fetch(args.max_pages,args.ttl_hours,args.delay,not args.no_alonhadat)
                    if args.command in ('build','run'):
                        build(args.llm_budget,args.force_inventory)
                    status.update(last_success_at=now(),last_error=None)
                except Exception as exc:
                    status['last_error']=type(exc).__name__
                    if not args.loop:
                        raise
                if not args.loop:
                    break
                interval = max(60,args.interval_hours*3600)
                status.update(state='sleeping',next_run_at=datetime.fromtimestamp(time.time()+interval,timezone.utc).isoformat(timespec='seconds'))
                atomic(status_path,status)
                stop.wait(interval)
        finally:
            status.update(state='stopped',stopped_at=now())
            atomic(status_path,status)


if __name__ == '__main__':
    main()
