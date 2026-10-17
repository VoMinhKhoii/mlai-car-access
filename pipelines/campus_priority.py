"""Full 5 m scans within 2 km of Goong-resolved HUTECH centres, before city breadth.

All drivable ways explicitly named/tagged as alleys are included. Other non-main
roads retain the city breadth policy; they cannot delay completion of known alleys.
Overlapping campus circles share work. Deep no-data completion is recorded apart
from successful widths so resuming never confuses shallow coverage with a deep scan.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from shapely.geometry import LineString, Point

from app import ai, live, osm, parcels, portal_gate
from app.config import CACHE
import osm_city_cache

ROOT = Path(__file__).resolve().parents[1]
CAMPUSES = ROOT / "docs/eval/hutech-campuses.json"
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def now():
    return datetime.now(VN).isoformat()


def within(coords, lat, lon, radius=2000):
    if len(coords) < 2:
        return False
    line = LineString([((lo - lon) * parcels.KX, (la - lat) * parcels.KY) for la, lo in coords])
    return line.distance(Point(0, 0)) <= radius


def cut_count(coords):
    lat, lon = coords[0]
    length = LineString([parcels._local(lo, la, lat, lon) for la, lo in coords]).length
    return max(0, math.ceil((length - parcels.DEEP_STEP / 2) / parcels.DEEP_STEP)) if length >= 6 else 0


def full_measure(coords, lookup):
    lat, lon = coords[0]
    line = LineString([parcels._local(lo, la, lat, lon) for la, lo in coords])
    # Unlike a destination path's 60-cut budget, a full campus way has no 300 m cap.
    limit = max(1, math.ceil(line.length / parcels.DEEP_STEP))
    result = parcels.measure(coords, step=parcels.DEEP_STEP, max_cuts=limit, parcel_lookup=lookup)
    attempted = sum(1 for i in range(limit) if parcels.DEEP_STEP / 2 + i * parcels.DEEP_STEP < line.length) if line.length >= 6 else 0
    return result, attempted


def prepare(state, stop, save, log, guard):
    points = json.loads(CAMPUSES.read_text())["campuses"]
    state.setdefault("campuses", {})
    state.setdefault("campus_targets", {})
    state.setdefault("campus_deep_done", {})
    state.setdefault("campus_retry_after", {})
    state["stage"] = "campus_maps"
    targets, metadata = {}, state["ways_meta"]
    for campus in points:
        if stop.is_set():
            return points, targets
        ident, lat, lon = campus["id"], campus["lat"], campus["lon"]
        with guard:
            current = state["campuses"].setdefault(ident, {})
            current.update({"label": campus["label"], "lat": lat, "lon": lon, "radius_m": 2000,
                            "geocoder": campus["geocoder"], "resolved_at": campus["resolved_at"]})
            current.setdefault("started_at", now())
        log.info("CAMPUS_COORD id=%s lat=%.9f lon=%.9f radius_m=2000 source=Goong-app", ident, lat, lon)
        save()
        s, n = lat - 2000 / parcels.KY, lat + 2000 / parcels.KY
        w, e = lon - 2000 / parcels.KX, lon + 2000 / parcels.KX
        keys = [(i, j) for i in range(math.floor(s / osm_city_cache.SIZE), math.floor(n / osm_city_cache.SIZE) + 1)
                for j in range(math.floor(w / osm_city_cache.SIZE), math.floor(e / osm_city_cache.SIZE) + 1)]
        elements = {}
        for key in keys:
            while not stop.is_set():
                try:
                    data = osm_city_cache.fetch_batch(key, stop)
                    for el in data["elements"]:
                        token = el["type"], el["id"]
                        elements[token] = {**elements.get(token, {}), **el}
                    break
                except Exception as exc:
                    log.warning("CAMPUS_MAP id=%s batch=%s error=%s backoff_s=60", ident, key, type(exc).__name__)
                    stop.wait(60)
        if stop.is_set():
            return points, targets
        graph = osm.graph_from_elements(lat, lon, list(elements.values()), "campus-fresh-overpass")
        ids, new_meta = [], {}
        non_main = 0
        for way in graph.ways.values():
            if not way.drivable or way.kind == "main":
                continue
            coords = [graph.nodes[n] for n in way.nodes]
            if within(coords, lat, lon):
                non_main += 1
                if not way.is_alley:
                    continue
                wid = str(way.id)
                ids.append(wid)
                new_meta[wid] = {"coords": coords, "name": way.name, "alley": way.is_alley,
                                 "cell": osm.area_key(lat, lon), "district": "HUTECH-priority"}
        osm_city_cache.ensure(lat, lon, stop, force_fresh=True)
        with guard:
            metadata.update(new_meta)
            targets[ident] = set(ids)
            state["campus_targets"][ident] = sorted(ids, key=int)
            current["ways_target"] = len(ids)
            current["drivable_non_main_candidates"] = non_main
            current["alleys_target"] = len(ids)
            current["cuts_target"] = sum(cut_count(metadata[wid]["coords"]) for wid in ids)
            current["map_ready_at"] = now()
            save()
        log.info("CAMPUS_TARGET id=%s drivable_non_main=%d tagged_alleys=%d cuts=%d", ident,
                 non_main, len(ids), current["cuts_target"])
        # Warm every routing key in the campus circle from the fetched batches.
        for i in range(math.floor(s / .004), math.ceil(n / .004) + 1):
            for j in range(math.floor(w / .004), math.ceil(e / .004) + 1):
                la, lo = round(i * .004, 4), round(j * .004, 4)
                if osm.haversine(lat, lon, la, lo) <= 2250 and not stop.is_set():
                    osm_city_cache.ensure(la, lo, stop, force_fresh=True)
        del graph, elements
    return points, targets


def update_counts(state, cache, targets):
    done, meta = state["campus_deep_done"], state["ways_meta"]
    for ident, ids in targets.items():
        info = state["campuses"][ident]
        deep = ids & done.keys()
        info.update({"ways_deep_completed": len(deep),
                     "ways_with_cadastral_width": sum(bool(cache.get(wid)) for wid in ids),
                     "ways_deep_with_width": sum(done[wid]["with_data"] for wid in deep),
                     "alleys_with_cadastral_width": sum(bool(cache.get(wid)) and meta[wid]["alley"] for wid in ids),
                     "alleys_deep_completed": sum(meta[wid]["alley"] for wid in deep),
                     "attempted_cuts": sum(done[wid]["attempted_cuts"] for wid in deep),
                     "updated_at": now()})
        if ids and len(deep) == len(ids) and not info.get("finished_at"):
            info["finished_at"] = now()
            info["elapsed_s"] = round((datetime.fromisoformat(info["finished_at"]) - datetime.fromisoformat(info["started_at"])).total_seconds(), 1)


def offline_pass(queue, state, cache, lookup, targets, stop, save, log, guard):
    """Use a cooldown for useful work without making a single portal request.

    Missing even one lookup aborts that way; unknown points are never extrapolated
    or cached as no-data. Complete cached scans have the same 5 m geometry.
    """
    def cached_only(lat, lon):
        hit, result = lookup.lookup(lat, lon)
        if not hit:
            raise parcels.Unavailable("Polygon not cached")
        return result
    completed = []
    for wid in list(queue):
        if stop.is_set():
            break
        try:
            result, cuts = full_measure(state["ways_meta"][wid]["coords"], cached_only)
        except parcels.Unavailable:
            continue
        except Exception as exc:
            log.warning("CAMPUS_OFFLINE error=%s; keeping remaining ways for retry", type(exc).__name__)
            break
        with guard:
            if result:
                cache[wid] = {**result, "deep": True, "sample_strategy": "campus-full-5m",
                              "queried_at": now(), "attempted_cuts": cuts}
            elif wid not in cache:
                cache[wid] = None
            state["campus_deep_done"][wid] = {"finished_at": now(), "attempted_cuts": cuts,
                                               "with_data": bool(result), "offline": True}
            completed.append(wid)
    with guard:
        for wid in completed:
            queue.remove(wid)
        state["campus_offline_checked_at"] = now()
        state["campus_offline_request_stamp"] = lookup.stats["requests"]
        update_counts(state, cache, targets)
        save()
    log.info("CAMPUS_OFFLINE completed=%d portal_requests=0", len(completed))


def prebuild(points, state, stop, save, log, guard):
    # This process may use only the explicitly free Gemini keys; no paid provider fallback.
    for key in ("PROD_GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    original = ai._call

    def free_call(*args, **kwargs):
        provider = ai.provider()
        if not provider or provider[0] != "gemini" or not ai.gemini_keys():
            raise ai.NoModel("No free Gemini key configured")
        try:
            return original(*args, **kwargs)
        except Exception as exc:
            # HTTP exception strings may contain URL query credentials. Persist class names only.
            raise RuntimeError(type(exc).__name__) from None

    ai._call = free_call
    try:
        for campus in points:
            if stop.is_set():
                return
            ident, lat, lon = campus["id"], campus["lat"], campus["lon"]
            while not state["campuses"].get(ident, {}).get("map_ready_at") and not stop.wait(1):
                pass
            if stop.is_set():
                return
            info = state["campuses"][ident]
            if info.get("build", {}).get("state") == "done":
                continue
            with guard:
                info["build"] = {"state": "running", "started_at": now()}
                save()
            started = time.monotonic()
            try:
                area = live.run_sync(lat, lon) or {}
                status = {"state": "done" if area else "error"}
                with guard:
                    info["build"] = {**info["build"], "state": status.get("state"), "finished_at": now(),
                                      "elapsed_s": round(time.monotonic() - started, 1), "key": area.get("key"),
                                      "listings": len(area.get("listings", [])), "news": len(area.get("news", [])),
                                      "parcels": len(area.get("parcels", [])), "photos": len(area.get("photos", [])),
                                      "error": bool(status.get("error"))}
                log.info("CAMPUS_BUILD id=%s state=%s elapsed_s=%.1f listings=%d news=%d", ident,
                         status.get("state"), time.monotonic() - started, len(area.get("listings", [])), len(area.get("news", [])))
            except Exception as exc:
                with guard:
                    info["build"] = {**info["build"], "state": "error", "error": type(exc).__name__, "finished_at": now()}
                log.warning("CAMPUS_BUILD id=%s error=%s", ident, type(exc).__name__)
            save()
    finally:
        ai._call = original


def classify(state, targets, points):
    """A way touching any 500 m circle is deep; remaining campus ways are breadth."""
    inner, rings = {}, {}
    meta = state["ways_meta"]
    for point in points:
        ident = point["id"]
        ids = targets[ident]
        inner[ident] = {wid for wid in ids if within(meta[wid]["coords"], point["lat"], point["lon"], 500)}
        rings[ident] = ids - inner[ident]
    deep = set().union(*inner.values())
    ring = set().union(*rings.values()) - deep
    state["campus_inner_targets"] = {key: sorted(ids, key=int) for key, ids in inner.items()}
    state["campus_ring_targets"] = {key: sorted(ids, key=int) for key, ids in rings.items()}
    state["campus_deep_ways_target"] = len(deep)
    state["campus_deep_cuts_target"] = sum(cut_count(meta[wid]["coords"]) for wid in deep)
    state["campus_ring_ways_target"] = len(ring)
    state["campus_inner_radius_m"] = 500
    state["campus_outer_radius_m"] = 2000
    state["campus_priority_policy"] = "interleaved-500m-deep-2km-ring-city-breadth"
    for ident, info in state["campuses"].items():
        info.update({"inner_radius_m": 500, "inner_alleys_target": len(inner[ident]),
                     "inner_cuts_target": sum(cut_count(meta[wid]["coords"]) for wid in inner[ident]),
                     "ring_alleys_target": len(rings[ident])})
        info.pop("finished_at", None)
        info.pop("elapsed_s", None)
    return deep, ring


def run(state, cache, lookup, stop, save, log, guard, after_prepare=None):
    points, targets = prepare(state, stop, save, log, guard)
    if stop.is_set():
        return set(), set()
    deep, ring = classify(state, targets, points)
    state["stage"] = "interleaved_inner_ring_city"
    state["round3_started_at"] = now()
    save()
    if after_prepare:
        after_prepare()
    log.info("ROUND3_TARGET inner_alleys=%d inner_cuts=%d ring_alleys=%d", len(deep),
             state["campus_deep_cuts_target"], len(ring))
    return deep, ring
