"""Resumable, $0 urban HCMC breadth crawl (no photos, listings, or AI calls).

Run: LISTINGS_TTL_H=48 nohup python3 -u pipelines/crawl_city.py > backend/cache/live/crawl_city.out 2>&1 &
Only this process writes city_parcels.json; it never writes live/parcels.json.
Small passes across cells avoid spending the entire night on the 3,000-way demo graph.
"""
from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import alonhadat, live, osm, parcels, portal_gate  # noqa: E402
from app.parcel_points import ParcelPoints  # noqa: E402
import city_scope
import osm_city_cache
import campus_priority
import crawl_scheduler
import crawl_ranked
from app.config import CACHE  # noqa: E402

DIR = CACHE / "live"
CITY = DIR / "city_parcels.json"
STATE = DIR / "crawl_city_state.json"
HUTECH = (10.8017, 106.7148)
VN = ZoneInfo("Asia/Ho_Chi_Minh")
STOP = threading.Event()
WRITE_LOCK = threading.RLock()
LOG = logging.getLogger("crawl_city")


def atomic_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


def cells() -> list[tuple[float, float]]:
    seen, out = set(), []
    for point in city_scope.schedule():
        p = point["lat"], point["lon"]
        key = osm.area_key(*p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def prebuild_running() -> bool:
    # Avoid matching our parent shell's command text or this script's filename.
    r = subprocess.run(["pgrep", "-f", r"[Pp]ython[^\n]*pipelines/prebuild_demo\.py"], capture_output=True)
    return r.returncode == 0


def graph_cells() -> list[tuple[float, float]]:
    out = cells()
    seen = {osm.area_key(*p) for p in out}
    for point in city_scope.schedule(.004):
        p = point["lat"], point["lon"]
        key = osm.area_key(*p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def candidates(g, lat, lon, cache, district_id=None):
    from shapely.geometry import Point
    district = next((d for d in city_scope.districts() if d["id"] == district_id), None) if district_id else None
    def in_district(w):
        if not district:
            return True
        la, lo = g.nodes[w.nodes[len(w.nodes) // 2]]
        return district["prepared"].covers(Point(lo, la))
    return sorted((w for w in g.ways.values() if w.drivable and w.kind != "main" and str(w.id) not in cache
                   and in_district(w)),
                  key=lambda w: (not w.is_alley, min(osm.haversine(lat, lon, *g.nodes[n]) for n in w.nodes)))


def warm_listings(state, save) -> None:
    """One district at a time, independently of the three cadastre workers."""
    try:
        districts = sorted(live._districts(), key=lambda d: osm.haversine(*HUTECH, d["lat"], d["lon"]))
    except Exception as exc:
        LOG.warning("listing districts error=%s", type(exc).__name__)
        return
    for d in districts:
        for source in ("s", "u", "alonhadat"):
            if STOP.is_set():
                return
            token = f"{d['id']}:{source}"
            if token in state["listings_done"]:
                continue
            try:
                if source == "alonhadat":
                    rows = alonhadat.pull_district(d["name"], DIR, {})
                else:
                    rows = live._pull(d["region"], d["id"], source, {"counts": {"fetched": 0}})
                with WRITE_LOCK:
                    state["listings_done"].append(token)
                save()
                LOG.info("listings district=%s source=%s ads=%d", d["name"], source, len(rows))
            except Exception as exc:
                state["listing_errors"] += 1
                LOG.warning("listings district=%s source=%s error=%s", d["name"], source, type(exc).__name__)


def warm_graphs(points) -> None:
    osm_city_cache.warm(points, STOP, LOG)



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop-at", default="2026-10-18T07:00:00+07:00")
    parser.add_argument("--schedule-status", help="one-shot schedule status file")
    parser.add_argument("--ranked", action="store_true", help="evidence queue, then 500 m campus set, then breadth; one targeted cut")
    parser.add_argument("--queue-base", default="http://127.0.0.1:8787")
    parser.add_argument("--skip-campus-priority", action="store_true", help="city-only maintenance; default interleaves 500 m deep campuses, rings and city")
    parser.add_argument("--portal-interval", type=float, default=180.0, help="minimum seconds between portal starts; learned spacing never decreases")
    parser.add_argument("--batch", type=int, default=12, help="ways per cell per pass, round-robin districts")
    parser.add_argument("--save-every", type=int, default=10)
    parser.add_argument("--cuts", type=int, choices=(1, 3), default=1,
                        help="one centre cut for breadth, or ends+middle; always deep=false")
    args = parser.parse_args()
    if args.ranked and args.portal_interval < 180:
        parser.error("ranked crawler spacing must be at least 180 seconds")
    if args.portal_interval < .5:
        parser.error("portal-interval must be at least 0.5 seconds")
    if args.batch < 1 or args.save_every < 1:
        parser.error("batch and save-every must be positive")
    deadline = datetime.fromisoformat(args.stop_at).timestamp()
    DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(DIR / "crawl_city.log"), logging.StreamHandler()])
    logging.getLogger("httpx").setLevel(logging.WARNING)
    lock = (DIR / "crawl_city.lock").open("a+")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Another crawl_city process owns the cache")
    if time.time() >= deadline:
        LOG.info("Stop time already passed; no requests made")
        return
    learning = portal_gate.configure_crawler(deadline, args.portal_interval)
    LOG.info("PORTAL_POLICY learning=%s lock_backoff_s=7200 cap_s=28800", learning)
    lock.seek(0)
    lock.truncate()
    lock.write(str(os.getpid()))
    lock.flush()
    cache = json.loads(CITY.read_text()) if CITY.exists() else {}
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    for key, default in (("cells_done", []), ("cells_visited", []), ("listings_done", []),
                         ("blocked", 0), ("errors", 0), ("listing_errors", 0)):
        state.setdefault(key, default)
    started, initial, last_report = time.time(), len(cache), 0
    point_cache = ParcelPoints(trust_env=False) if args.ranked else ParcelPoints()
    fractions = (.5,) if args.cuts == 1 else (.1, .5, .9)
    state["method"] = "point-spatial-cache-centre" if args.cuts == 1 else "point-spatial-cache-three-cuts"
    state["cuts_per_way"] = args.cuts
    state["run_started_at"] = datetime.now(VN).isoformat()
    state["run_initial_ways"] = initial
    state["round3_completed"] = {"inner": 0, "ring": 0, "city": 0}
    state["round3_completion_events"] = []
    state["portal_interval_requested_s"] = args.portal_interval
    state["scope"] = "17 urban districts (2021 boundaries; includes former Q2/Q9/Thu Duc)"
    state["districts_target"] = 17
    state.setdefault("districts_visited", [])
    state.setdefault("ways_meta", {})
    state.setdefault("cell_progress", {})
    # Recover labels/geometry for round-1 results using only already cached graphs.
    for prior_key in state["cells_visited"]:
        if prior_key == "demo":
            p = HUTECH
        else:
            try:
                p = tuple(map(float, prior_key.split("_")))
            except ValueError:
                continue
        graph = osm.cached_graph(*p)
        if graph:
            for w in graph.ways.values():
                if str(w.id) in cache and str(w.id) not in state["ways_meta"]:
                    state["ways_meta"][str(w.id)] = {"coords": [graph.nodes[n] for n in w.nodes],
                                                    "name": w.name, "alley": w.is_alley,
                                                    "cell": prior_key, "district": "round-1"}
            osm._GRAPHS.pop(prior_key, None)

    def save():
        with WRITE_LOCK:
            state.update({"updated_at": datetime.now(VN).isoformat(), "ways_measured": len(cache),
                          "ways_with_data": sum(bool(v and v.get("samples")) for v in cache.values()), "pid": os.getpid(),
                          "ways_deep_with_data": sum(bool(v and v.get("deep") and v.get("samples")) for v in cache.values()),
                          "alleys_with_data": sum(bool(v and v.get("samples")) and state["ways_meta"].get(k, {}).get("alley", False)
                                                  for k, v in cache.items()),
                          "stop_at": args.stop_at,
                          "run_elapsed_s": round(time.time() - started, 1),
                          "run_ways_added": len(cache) - initial,
                          "rate_ways_min": round((len(cache) - initial) * 60 / max(1, time.time() - started), 2),
                          "point_cache": dict(point_cache.stats),
                          "osm_cells_cached": len(list((CACHE / "osm").glob("area_*.json"))) + int(osm.DEMO_FILE.exists())})
            atomic_json(CITY, cache)
            atomic_json(STATE, state)

    def mark_schedule(reason):
        if not args.schedule_status:
            return
        path = Path(args.schedule_status)
        try:
            status = json.loads(path.read_text())
            if status.get("pid") == os.getpid():
                atomic_json(path, {**status, "state": reason, "updated_at": datetime.now(VN).isoformat()})
        except (OSError, ValueError):
            LOG.warning("Could not update schedule status")

    def stop(*_):
        STOP.set()
        state["stage"] = "paused_by_signal"
        save()
        mark_schedule("paused_by_signal")
        LOG.info("Stopped by signal; saved %d ways (in-flight ways will retry next run)", len(cache))
        portal_gate.release_crawler()
        logging.shutdown()
        os._exit(0)

    def deadline_stop():
        if not STOP.wait(max(0, deadline - time.time())):
            STOP.set()
            state["stage"] = "paused_window_end"
            save()
            mark_schedule("paused_window_end")
            LOG.info("Deadline %s reached; saved %d ways and exiting", args.stop_at, len(cache))
            # HTTP workers may be in a retry: do not let them prolong the overnight run.
            portal_gate.release_crawler()
            logging.shutdown()
            os._exit(0)

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    threading.Thread(target=deadline_stop, daemon=True).start()
    if args.ranked:
        state["portal_learning"] = learning
        try:
            crawl_ranked.run(state, cache, point_cache, STOP, save, LOG, args.queue_base)
        finally:
            portal_gate.release_crawler()
            point_cache.close()
            save()
        return
    while prebuild_running() and not STOP.is_set():
        LOG.info("Waiting for prebuild_demo to finish; no crawl requests made")
        STOP.wait(30)
    if STOP.is_set():
        save()
        return
    points = cells()
    schedule = {}
    for point in city_scope.schedule():
        schedule.setdefault(osm.area_key(point["lat"], point["lon"]), point)
    map_points = graph_cells()
    state["cells_target"] = len(points)
    state["osm_cells_target"] = len(map_points)
    files = list((CACHE / "osm").glob("area_*.json"))
    mean = sum(p.stat().st_size for p in files) / max(1, len(files))
    LOG.info("START pid=%d cells=%d map_keys=%d cached_ways=%d stop=%s projected_osm_MB=%.1f",
             os.getpid(), len(points), len(map_points), len(cache), args.stop_at, mean * len(map_points) / 1e6)
    if mean * len(map_points) > 2_000_000_000:
        LOG.warning("Projected OSM cache exceeds 2 GB")
    save()
    # Listings were warmed in round 1. This run spends its budget on map/parcel breadth.
    map_thread = threading.Thread(target=warm_graphs, args=(map_points,), daemon=True)
    if args.skip_campus_priority:
        inner, ring = set(), set()
        map_thread.start()
    else:
        inner, ring = campus_priority.run(state, cache, point_cache, STOP, save, LOG, WRITE_LOCK,
                                         after_prepare=map_thread.start)
    if not STOP.is_set():
        crawl_scheduler.run(state, cache, point_cache, inner, ring, points, schedule,
                            STOP, save, LOG, WRITE_LOCK, args.batch)
    save()
    portal_gate.release_crawler()
    point_cache.close()
    LOG.info("STOP ways=%d cells_done=%d blocked=%d errors=%d", len(cache), len(state["cells_done"]),
             state["blocked"], state["errors"])


if __name__ == "__main__":
    main()
