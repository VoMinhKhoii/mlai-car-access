"""Read-only city evidence state + persistent demand-weighted measurement queue.

No cadastral/OSM/LLM network calls. The usage database stores only way ids and
aggregate counts; no coordinates, destinations, account ids or vehicle history.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
import threading

from . import declared_index, flags
from .config import CACHE, STORE

INVENTORY = CACHE / "live/evidence_inventory.json"
USAGE = STORE / "evidence_usage.sqlite"
_lock = threading.RLock()
_state_key, _state = None, {}
THRESHOLDS = {"vf3": 1.95, "sedan": 2.18, "suv": 2.31}


def stamp(path):
    try:
        s = path.stat()
        return str(path), s.st_mtime_ns, s.st_size
    except OSError:
        return str(path), None, None


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def db(path=None):
    path = path or USAGE
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("CREATE TABLE IF NOT EXISTS usage (way_id INTEGER PRIMARY KEY, requests INTEGER NOT NULL, last_seen TEXT NOT NULL)")
    return con


def record_way_ids(ids, path=None):
    """At most one count per way per successful Arrival Plan."""
    clean = sorted({int(x) for x in ids if isinstance(x, int) and not isinstance(x, bool) and x > 0})
    if not clean:
        return
    con = db(path)
    try:
        with con:
            con.executemany("INSERT INTO usage VALUES (?,1,?) ON CONFLICT(way_id) DO UPDATE SET requests=requests+1,last_seen=excluded.last_seen",
                            [(wid, datetime.now(timezone.utc).isoformat(timespec="seconds")) for wid in clean])
    finally:
        con.close()


def usage(path=None):
    path = path or USAGE
    if not path.exists():
        return {}
    con = db(path)
    try:
        return {wid: {"plan_requests": count, "last_requested_at": last} for wid, count, last in con.execute("SELECT * FROM usage")}
    finally:
        con.close()


def touched_way_ids(result):
    """Explicit stop/door ids plus route segments lying on returned OSM geometry.

    A map layer's mere presence is NOT demand. Route matching requires a positive
    length overlap, so crossing/nearby ways do not get spurious demand counts.
    """
    ids, routes = set(), []

    def walk(value):
        if isinstance(value, dict):
            wid = value.get("way_id")
            if isinstance(wid, int) and wid > 0:
                ids.add(wid)
            for k, v in value.items():
                if k in ("route_in", "standard_route", "way_out") and isinstance(v, dict) and len(v.get("geometry") or []) >= 2:
                    routes.append(v["geometry"])
                if k != "layers":
                    walk(v)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk({k: result.get(k) for k in ("door", "stop_points", "standard_route")})
    if routes:
        from shapely.geometry import LineString
        from shapely.ops import unary_union
        # Coordinates in the route and layer share the OSM centreline. A tiny
        # 1 cm buffer handles floating point interpolation, not shifted geometry.
        lines = [LineString([(x * 109400, y * 110574) for x, y in cs]) for cs in routes]
        route = unary_union(lines).buffer(.01)
        for f in result.get("layers", {}).get("fit", {}).get("features", []):
            coords = f.get("geometry", {}).get("coordinates", [])
            if len(coords) < 2:
                continue
            line = LineString([(x * 109400, y * 110574) for x, y in coords])
            if line.length < .05:
                continue
            if line.intersection(route).length >= min(2., line.length * .5):
                wid = f.get("properties", {}).get("way_id")
                if isinstance(wid, int) and wid > 0:
                    ids.add(wid)
    return ids


def city_state():
    """Cached actual per-way ranges and source tier counts; no road-prior coverage credit."""
    global _state_key, _state
    from .evidence import EvidenceStore, STORE_EVIDENCE, TIERS, _osm_bounds, _combine
    from .osm import Way, DRIVABLE, FOOT_ONLY
    from . import footprints
    from . import imagery_evidence
    paths = [INVENTORY, declared_index.PATH, CACHE / "live/city_parcels.json",
             CACHE / "live/footprint_widths.json", CACHE / "live/parcels.json",
             *sorted((CACHE / "live/areas").glob("*.json"))]
    key = (tuple(map(stamp, paths)), STORE_EVIDENCE.version,
           imagery_evidence.active_stamp(),  # pending batch writes do not invalidate the live queue
           tuple((f['name'], f['enabled']) for f in flags.describe()))
    with _lock:
        if key == _state_key:
            return _state
        inv = read(INVENTORY)
        if not inv:
            return {"available": False, "ways": {}, "coverage": {"evidence_engine_available": False}}
        store = EvidenceStore()
        cad = {str(wid): {"way_id": int(wid), **r} for wid, r in read(CACHE / "live/city_parcels.json").items() if isinstance(r, dict) and r.get("samples")}
        listings, photos = [], []
        for path in paths[5:]:
            area = read(path)
            listings.extend(area.get("listings", []))
            photos.extend(area.get("photos", []))
            for r in area.get("parcels", []):
                wid = str(r['way_id'])
                if r.get("samples") and (wid not in cad or r.get("deep")):
                    cad[wid] = r
        from . import live
        reviews = live._photo_reviews()
        photos = [{**p, "status": reviews.get(p.get("id"), {}).get("status", "pending")} for p in photos]
        store = store.view({"listings": listings, "photos": photos, "parcels": list(cad.values())})
        tiers = {t: set() for t in TIERS}
        strongest = {t: set() for t in TIERS}
        alley_ids, drivable_ids, states = set(), set(), {}
        for wid, row in inv["ways"].items():
            w = Way(int(wid), row["tags"], [])
            if w.kind == "main" or w.highway not in DRIVABLE | FOOT_ONLY:
                continue
            if w.is_alley:
                alley_ids.add(wid)
            if w.drivable:
                drivable_ids.add(wid)
            bounds = _osm_bounds(w) + store.bounds_for(w)
            active, ignored, review = declared_index.prepare(w.id, bounds)
            fp = [b for b in active if b.feature == "footprint_widths"]
            if fp:
                if any(b.tier in ("Measured", "Official") for b in active):
                    active = [b for b in active if b not in fp]
                else:
                    active = [b for b in active if not (b.tier == "Inferred" and b.source in ("OSM phân loại đường", "OSM số làn xe"))]
            lo, hi, top, conflict, _, _ = _combine(active)
            # Coverage credits sourced bounds, never generic road/lanes priors.
            source_bounds = [b for b in bounds if b.source not in ("OSM phân loại đường", "OSM số làn xe")]
            present = {b.tier for b in source_bounds}
            for tier in present:
                tiers[tier].add(wid)
            source_top = next((t for t in TIERS if t in present), None)
            if source_top:
                strongest[source_top].add(wid)
            coords = row["coords"]
            x, y = coords[len(coords)//2]
            states[wid] = {"way_id": w.id, "name": w.name, "lat": y, "lon": x, "lo": lo, "hi": hi,
                           "top_tier": source_top, "range_top_tier": top, "review": review or conflict,
                           "is_alley": w.is_alley, "drivable": w.drivable}
        covered = set().union(*tiers.values())
        _, product = declared_index.snapshot()
        cov = {"evidence_engine_available": True, "evidence_generated_at": inv.get("generated_at"),
               "evidence_scope": inv.get("scope"), "evidence_osm_routing_cells": inv.get("routing_cells"),
               "evidence_non_main_ways": len(states), "evidence_drivable_non_main_ways": len(drivable_ids),
               "evidence_named_tagged_alleys": len(alley_ids), "evidence_ways_with_sources": len(covered),
               "evidence_ways_unknown": len(states)-len(covered),
               "evidence_ways_by_strongest_tier": {t:len(v) for t,v in strongest.items()},
               "evidence_ways_by_tier": {t:len(v) for t,v in tiers.items()},
               "evidence_alleys_by_strongest_tier": {t:len(v & alley_ids) for t,v in strongest.items()},
               "evidence_drivable_ways_by_strongest_tier": {t:len(v & drivable_ids) for t,v in strongest.items()},
               "evidence_declared_index_ways": len(product.get("ways", {})),
               "evidence_declared_generated_at": product.get("generated_at"),
               "evidence_note": "Strongest source tier, not resolved vehicle access. Generic road-class/lanes priors excluded. Cache union is not full administrative-city coverage."}
        _state_key, _state = key, {"available": True, "ways": states, "coverage": cov}
        return _state


def rank(row, demand):
    crossed = [name for name, threshold in THRESHOLDS.items() if row['lo'] < threshold <= row['hi']]
    scarcity = {"Synthetic": .05, "Measured": .05, "Official": .15, "Observed": .7, "Declared": 1., "Inferred": 1.3, None: 1.5}[row["top_tier"]]
    score = (1 + math.log2(1 + demand)) * (1 + len(crossed)) * scarcity
    if row.get("review"):
        score *= 1.5
    return round(score, 6), crossed


def queue(limit=100, bbox=None, min_score=0):
    state = city_state()
    counts = usage()
    candidates = []
    for row in state.get("ways", {}).values():
        if bbox and not (bbox[0] <= row['lon'] <= bbox[2] and bbox[1] <= row['lat'] <= bbox[3]):
            continue
        demand = counts.get(row['way_id'], {}).get('plan_requests', 0)
        score, crossed = rank(row, demand)
        if score < min_score:
            continue
        candidates.append({**row, "hi": None if row['hi'] >= 40 else row['hi'], "score": score,
                           "thresholds_straddled": crossed, "plan_requests": demand,
                           "last_requested_at": counts.get(row['way_id'], {}).get('last_requested_at'),
                           "recommended_action": "measure_or_review" if row.get('review') else "measure_clear_width"})
    candidates.sort(key=lambda r:(-r['score'], -r['plan_requests'], not r['is_alley'], r['way_id']))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "available": state.get('available', False),
            "eligible_ways": len(candidates), "items": candidates[:limit], "thresholds_m": THRESHOLDS,
            "score_formula": "(1+log2(1+plan_requests)) × (1+thresholds_straddled) × tier_scarcity × (1.5 if review else 1)",
            "tier_scarcity": {"Synthetic": .05, "Measured": .05, "Official": .15, "Observed": .7, "Declared": 1., "Inferred": 1.3, "unknown": 1.5},
            "demand_scope": "Successful /api/plan responses: door/stops, explicit ways and overlapping returned route geometry; counted once per request. No destinations retained.",
            "coverage": state.get('coverage', {})}
