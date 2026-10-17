"""Fetch fresh Overpass supercells once; materialize ordinary 1.2 km routing caches.

A .036° square with a 1.4 km halo replaces up to 81 overlapping requests.
The halo includes every way that can intersect a routing circle. All nodes of
selected ways are retained, including nodes beyond that circle, like `out; >;`.
"""
from __future__ import annotations

import json
import logging
import math
import os
import threading
import time
from pathlib import Path

import httpx
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

from app import osm
from app.config import AREA_RADIUS_M, CACHE, OVERPASS_ENDPOINTS

SIZE = .036
HALO = .014
DIRECTORY = CACHE / "osm" / "city_batches"
TTL = 86400
_lock = threading.Lock()
LOG = logging.getLogger("crawl_city")


def batch_key(lat, lon):
    return math.floor(lat / SIZE), math.floor(lon / SIZE)


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data, separators=(",", ":")))
    os.replace(tmp, path)


def fetch_batch(key, stop):
    path = DIRECTORY / f"{key[0]}_{key[1]}.json"
    if path.exists() and time.time() - path.stat().st_mtime < TTL:
        return json.loads(path.read_text())
    s, w = key[0] * SIZE - HALO, key[1] * SIZE - HALO
    n, e = (key[0] + 1) * SIZE + HALO, (key[1] + 1) * SIZE + HALO
    bbox = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    q = f'''[out:json][timeout:50];(
      way["highway"]({bbox});
      node["highway"~"^(crossing|bus_stop|traffic_signals|stop)$"]({bbox});
      node["traffic_sign"]({bbox});
      nwr["amenity"~"^(parking|parking_entrance)$"]({bbox});
    );out body;>;out skel qt;'''
    errors = []
    with _lock:  # one Overpass request across graph-warmup and measurement threads
        if path.exists() and time.time() - path.stat().st_mtime < TTL:
            return json.loads(path.read_text())
        for attempt in range(3):
            for endpoint in OVERPASS_ENDPOINTS:
                if stop.is_set():
                    raise InterruptedError()
                try:
                    from urllib.parse import urlparse
                    host = urlparse(endpoint).hostname
                    started = time.monotonic()
                    LOG.info("OSM_FETCH batch=%s host=%s attempt=%d", key, host, attempt + 1)
                    r = httpx.post(endpoint, data={"data": q},
                                   headers={"User-Agent": "VaoDuoc/0.3 (MLAI Hackathon 2026; minhkhoitdn@gmail.com)"}, timeout=65)
                    r.raise_for_status()
                    data = r.json()
                    if "remark" in data or not data.get("elements"):
                        raise RuntimeError("Incomplete Overpass response")
                    data["_cache"] = {"fetched_at": time.time(), "bbox": [s, w, n, e], "batch": list(key)}
                    atomic(path, data)
                    LOG.info("OSM_FETCHED batch=%s host=%s elements=%d elapsed_s=%.1f", key, host,
                             len(data["elements"]), time.monotonic() - started)
                    stop.wait(3)
                    return data
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    errors.append(type(exc).__name__)
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    LOG.warning("OSM_FETCH_FAILED batch=%s host=%s status=%s error=%s", key, host, status, type(exc).__name__)
                    if stop.wait(min(120, 10 * (attempt + 1))):
                        raise InterruptedError()
        raise RuntimeError(f"Overpass batch unavailable: {errors}")


class Batch:
    def __init__(self, data):
        self.data = data
        # Overpass can return a node twice (tagged body followed by skeleton).
        self.nodes = {}
        self.ways = []
        self.others = []
        for el in data["elements"]:
            if el["type"] == "node":
                previous = self.nodes.get(el["id"], {})
                self.nodes[el["id"]] = {**previous, **el}
            elif el["type"] == "way":
                self.ways.append(el)
            else:
                self.others.append(el)
        geometries, ways = [], []
        for way in self.ways:
            coords = [(self.nodes[n]["lon"], self.nodes[n]["lat"]) for n in way.get("nodes", []) if n in self.nodes]
            if len(coords) >= 2:
                geometries.append(LineString(coords))
                ways.append(way)
        self.ways = ways
        self.tree = STRtree(geometries)

    def area(self, lat, lon):
        radius = AREA_RADIUS_M + 35  # cover the rounding of area_key centres
        chosen, ids = [], set()
        for idx in self.tree.query(box(lon - radius / 109400, lat - radius / 110540,
                                       lon + radius / 109400, lat + radius / 110540)):
            way = self.ways[int(idx)]
            coords = [((self.nodes[n]["lon"] - lon) * 109400, (self.nodes[n]["lat"] - lat) * 110540)
                      for n in way.get("nodes", []) if n in self.nodes]
            if len(coords) >= 2:
                xs, ys = zip(*coords)
                if min(xs) > radius or max(xs) < -radius or min(ys) > radius or max(ys) < -radius:
                    continue
                if LineString(coords).distance(Point(0, 0)) <= radius:
                    chosen.append(way)
                    ids.update(way.get("nodes", []))
        for nid, node in self.nodes.items():
            if node.get("tags") and osm.haversine(lat, lon, node["lat"], node["lon"]) <= radius:
                ids.add(nid)
        elements = [self.nodes[n] for n in ids if n in self.nodes] + chosen
        # Keep relation membership where a selected way/node participates (parking relations).
        wids = {w["id"] for w in chosen}
        elements += [r for r in self.others if any(m.get("ref") in (wids if m.get("type") == "way" else ids)
                                                  for m in r.get("members", []))]
        return {"elements": elements, "osm3s": self.data.get("osm3s", {}),
                "_cache": {**self.data.get("_cache", {}), "center": [lat, lon], "radius_m": radius}}


_last_key, _last_batch = None, None
_batch_guard = threading.Lock()


def ensure(lat, lon, stop, force_fresh=False):
    global _last_key, _last_batch
    key = osm.area_key(lat, lon)
    if key == "demo":
        # The shared demo stays intact; fresh urban batches still cover its surrounding cells.
        return
    path = CACHE / "osm" / f"area_{key}.json"
    if path.exists() and (not force_fresh or time.time() - path.stat().st_mtime < TTL):
        return
    # Every alias of a key must receive a circle around its canonical centre.
    clat, clon = map(float, key.split("_"))
    bk = batch_key(clat, clon)
    with _batch_guard:
        if _last_key != bk:
            _last_batch = Batch(fetch_batch(bk, stop))
            _last_key = bk
        atomic(path, _last_batch.area(clat, clon))


def warm(points, stop, log):
    groups = {}
    for lat, lon in points:
        groups.setdefault(batch_key(lat, lon), []).append((lat, lon))
    for key, locations in groups.items():
        if stop.is_set():
            return
        try:
            for lat, lon in locations:
                if stop.is_set():
                    return
                ensure(lat, lon, stop, force_fresh=True)
            log.info("OSM_BATCH key=%s keys=%d cached", key, len(locations))
        except Exception as exc:
            log.warning("OSM_BATCH key=%s error=%s; retry on next run", key, type(exc).__name__)


def refresh_demo(stop, log):
    """Refresh the shared wide demo graph from fresh batches, preserving preset IDs."""
    if osm.DEMO_FILE.exists():
        old = json.loads(osm.DEMO_FILE.read_text())
        if old.get("_cache", {}).get("kind") == "fresh-demo-bbox" and time.time() - old["_cache"]["fetched_at"] < TTL:
            return
    s, w, n, e = osm.DEMO_BBOX
    merged, timestamps = {}, []
    for i in range(math.floor(s / SIZE), math.floor(n / SIZE) + 1):
        for j in range(math.floor(w / SIZE), math.floor(e / SIZE) + 1):
            data = fetch_batch((i, j), stop)
            timestamps.append(data.get("_cache", {}).get("fetched_at", time.time()))
            for el in data["elements"]:
                token = el["type"], el["id"]
                merged[token] = {**merged.get(token, {}), **el}
    batch = Batch({"elements": list(merged.values())})
    extent, ids, chosen = box(w, s, e, n), set(), []
    for index in batch.tree.query(extent, predicate="intersects"):
        way = batch.ways[int(index)]
        chosen.append(way)
        ids.update(way.get("nodes", []))
    for nid, node in batch.nodes.items():
        if node.get("tags") and extent.covers(Point(node["lon"], node["lat"])):
            ids.add(nid)
    required = {32584409, 544982029, 136507381, 193085696, 192512291}
    if not required <= {w["id"] for w in chosen}:
        log.warning("DEMO_REFRESH skipped: a preset way is absent from fresh OSM")
        return
    fresh = {"elements": [batch.nodes[n] for n in ids if n in batch.nodes] + chosen,
             "_cache": {"kind": "fresh-demo-bbox", "fetched_at": min(timestamps), "bbox": [s, w, n, e]},
             "osm3s": {"copyright": "© OpenStreetMap contributors, ODbL"}}
    atomic(osm.DEMO_FILE, fresh)
    osm._GRAPHS.pop("demo", None)
    log.info("DEMO_REFRESH ways=%d nodes=%d", len(chosen), len(ids))
