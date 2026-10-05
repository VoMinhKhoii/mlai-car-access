"""Street graph around a destination, built from OpenStreetMap via Overpass.

The Bình Thạnh demo strip is prefetched (cache/osm/demo_binhthanh.json) so the
demo runs offline; any other HCMC address is fetched on demand and cached.
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import httpx

from .config import AREA_RADIUS_M, CACHE, OVERPASS_ENDPOINTS

DEMO_FILE = CACHE / "osm" / "demo_binhthanh.json"
DEMO_BBOX = (10.785, 106.690, 10.815, 106.727)  # s, w, n, e

MAIN = {"motorway", "trunk", "primary", "secondary", "tertiary", "motorway_link",
        "trunk_link", "primary_link", "secondary_link", "tertiary_link"}
DRIVABLE = MAIN | {"unclassified", "residential", "living_street", "service", "road"}
FOOT_ONLY = {"footway", "pedestrian", "path", "steps", "cycleway", "corridor", "track"}
NOT_WALKABLE = {"motorway", "motorway_link", "trunk", "trunk_link", "construction", "proposed"}

# OSM often tags motorbike-parking lanes as plain driveways; the name is the only signal ("Đường vô bãi xe 2 bánh").
MOTORBIKE_ONLY = re.compile(r"(xe\s*(2|hai)\s*bánh|xe\s*máy|bãi\s*xe\s*máy|motorbike|motorcycle)", re.IGNORECASE)
ALLEY_NAME = re.compile(r"^\s*(hẻm|hem|kiệt|kiet|ngõ|ngo|ngách|ngach)\b", re.IGNORECASE)


@lru_cache(maxsize=65536)
def strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower().strip()


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass
class Way:
    id: int
    tags: dict
    nodes: list[int]

    @property
    def highway(self) -> str:
        return self.tags.get("highway", "")

    @property
    def name(self) -> str:
        return self.tags.get("name", "")

    @property
    def is_alley(self) -> bool:
        return self.tags.get("service") == "alley" or bool(ALLEY_NAME.match(self.name))

    @property
    def kind(self) -> str:
        if self.highway in MAIN:
            return "main"
        if self.highway in FOOT_ONLY:
            return "foot"
        if self.is_alley:
            return "alley"
        if self.highway in ("residential", "living_street", "unclassified", "road"):
            return "residential"
        if self.highway == "service":
            return "service"
        return "other"

    @property
    def drivable(self) -> bool:
        if self.highway not in DRIVABLE:
            return False
        if self.tags.get("access") in ("private", "no") and self.tags.get("motorcar") not in ("yes", "destination"):
            return False
        if self.tags.get("motorcar") == "no" or self.tags.get("motor_vehicle") == "no":
            return False
        if MOTORBIKE_ONLY.search(self.name) and self.tags.get("motorcar") not in ("yes", "destination"):
            return False
        return self.tags.get("area") != "yes"

    @property
    def walkable(self) -> bool:
        return self.highway not in NOT_WALKABLE and self.tags.get("foot") != "no" and self.tags.get("area") != "yes"

    @property
    def oneway(self) -> int:
        v = self.tags.get("oneway", "")
        if v in ("yes", "true", "1"):
            return 1
        if v == "-1":
            return -1
        return 0


@dataclass
class Edge:
    idx: int
    way_id: int
    u: int
    v: int
    length: float


@dataclass
class AreaGraph:
    center: tuple[float, float]
    nodes: dict[int, tuple[float, float]] = field(default_factory=dict)
    node_tags: dict[int, dict] = field(default_factory=dict)
    ways: dict[int, Way] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    drive_adj: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    walk_adj: dict[int, list[tuple[int, int]]] = field(default_factory=dict)
    node_ways: dict[int, set[int]] = field(default_factory=dict)
    parking: list[dict] = field(default_factory=list)
    source: str = ""

    def latlon(self, n: int) -> tuple[float, float]:
        return self.nodes[n]

    def drive_degree(self, n: int) -> int:
        return len({w for w in self.node_ways.get(n, ()) if self.ways[w].drivable})

    def edge_coords(self, e: Edge, forward: bool = True) -> list[list[float]]:
        a, b = (e.u, e.v) if forward else (e.v, e.u)
        (la, lo), (lb, lob) = self.nodes[a], self.nodes[b]
        return [[lo, la], [lob, lb]]

    def way_coords(self, way_id: int) -> list[list[float]]:
        return [[self.nodes[n][1], self.nodes[n][0]] for n in self.ways[way_id].nodes if n in self.nodes]

    def display_name(self, way_id: int) -> str:
        w = self.ways[way_id]
        if w.name:
            return w.name
        for n in (w.nodes[0], w.nodes[-1]):
            for other in self.node_ways.get(n, ()):
                if other != way_id and self.ways[other].name:
                    return f"Nhánh cạnh {self.ways[other].name}"
        return "Đường nhánh không tên"

    def nearest_node(self, lat: float, lon: float, predicate=None) -> tuple[int | None, float]:
        best, best_d = None, float("inf")
        for n, (la, lo) in self.nodes.items():
            if predicate and not predicate(n):
                continue
            d = haversine(lat, lon, la, lo)
            if d < best_d:
                best, best_d = n, d
        return best, best_d


def _inside(lat: float, lon: float, bbox, margin_deg: float = 0.0) -> bool:
    s, w, n, e = bbox
    return s + margin_deg <= lat <= n - margin_deg and w + margin_deg <= lon <= e - margin_deg


def _fetch_overpass(lat: float, lon: float, radius: float) -> dict:
    r = int(radius)
    q = f"""[out:json][timeout:120];
(
  way["highway"](around:{r},{lat},{lon});
  node["highway"~"^(crossing|bus_stop|traffic_signals|stop)$"](around:{r},{lat},{lon});
  node["traffic_sign"](around:{r},{lat},{lon});
  nwr["amenity"~"^(parking|parking_entrance)$"](around:{r},{lat},{lon});
);
out body;
>;
out skel qt;"""
    # No Accept header: overpass-api.de answers 406 to "Accept: application/json".
    headers = {"User-Agent": "VaoDuoc/0.3 (MLAI Hackathon 2026; minhkhoitdn@gmail.com)"}

    def ask(ep: str) -> dict:
        resp = httpx.post(ep, data={"data": q}, headers=headers, timeout=150)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("elements"):
            raise RuntimeError(f"{ep}: empty answer")
        return data

    errors = []
    for attempt in range(3):  # all mirrors at once; if every one fails (504s are common), wait and try again
        pool = ThreadPoolExecutor(len(OVERPASS_ENDPOINTS))
        futures = [pool.submit(ask, ep) for ep in OVERPASS_ENDPOINTS]
        try:
            for fut in as_completed(futures):
                try:
                    return fut.result()
                except Exception as exc:  # wait for the next mirror
                    errors.append(str(exc)[:120])
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"Overpass unavailable: {errors}")


def area_key(lat: float, lon: float) -> str:
    """One street graph (and one live evidence build) per key."""
    if DEMO_FILE.exists() and _inside(lat, lon, DEMO_BBOX, margin_deg=0.004):
        return "demo"
    return f"{round(lat / 0.004) * 0.004:.3f}_{round(lon / 0.004) * 0.004:.3f}"


_fetch_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def load_elements(lat: float, lon: float) -> tuple[list[dict], str]:
    key = area_key(lat, lon)
    with _locks_guard:
        lock = _fetch_locks.setdefault(key, threading.Lock())
    with lock:  # the plan request and the live build must not download the same area twice
        return _load_elements(lat, lon, key)


def _load_elements(lat: float, lon: float, key: str) -> tuple[list[dict], str]:
    if key == "demo":
        return json.loads(DEMO_FILE.read_text())["elements"], "demo-cache"
    path = CACHE / "osm" / f"area_{key}.json"
    if path.exists():
        return json.loads(path.read_text())["elements"], f"cache:{key}"
    data = _fetch_overpass(lat, lon, AREA_RADIUS_M)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data["elements"], f"overpass:{key}"


_GRAPHS: dict[str, AreaGraph] = {}


def cached_graph(lat: float, lon: float) -> AreaGraph | None:
    """The area graph only if it is already on disk or in memory (never downloads; used while typing)."""
    key = area_key(lat, lon)
    if key in _GRAPHS:
        return _GRAPHS[key]
    if key == "demo" or (CACHE / "osm" / f"area_{key}.json").exists():
        return build_graph(lat, lon)
    return None


def build_graph(lat: float, lon: float) -> AreaGraph:
    key = area_key(lat, lon)
    if key in _GRAPHS:
        return _GRAPHS[key]
    elements, source = load_elements(lat, lon)
    g = AreaGraph(center=(lat, lon), source=source)
    raw_ways = []
    for el in elements:
        if el["type"] == "node":
            g.nodes[el["id"]] = (el["lat"], el["lon"])
            if el.get("tags"):
                g.node_tags[el["id"]] = el["tags"]
        elif el["type"] == "way":
            raw_ways.append(el)
    for el in raw_ways:
        tags = el.get("tags", {})
        if tags.get("amenity") in ("parking", "parking_entrance") and "highway" not in tags:
            pts = [g.nodes[n] for n in el.get("nodes", []) if n in g.nodes]
            if pts:
                g.parking.append({"id": f"w{el['id']}", "lat": sum(p[0] for p in pts) / len(pts),
                                  "lon": sum(p[1] for p in pts) / len(pts), "tags": tags})
            continue
        if "highway" not in tags:
            continue
        w = Way(el["id"], tags, [n for n in el.get("nodes", []) if n in g.nodes])
        if len(w.nodes) < 2:
            continue
        g.ways[w.id] = w
    for nid, tags in g.node_tags.items():
        if tags.get("amenity") in ("parking", "parking_entrance"):
            la, lo = g.nodes[nid]
            g.parking.append({"id": f"n{nid}", "lat": la, "lon": lo, "tags": tags})

    for w in g.ways.values():
        for a, b in zip(w.nodes, w.nodes[1:]):
            (la, lo), (lb, lob) = g.nodes[a], g.nodes[b]
            e = Edge(len(g.edges), w.id, a, b, haversine(la, lo, lb, lob))
            g.edges.append(e)
            g.node_ways.setdefault(a, set()).add(w.id)
            g.node_ways.setdefault(b, set()).add(w.id)
            if w.drivable:
                if w.oneway >= 0:
                    g.drive_adj.setdefault(a, []).append((e.idx, b))
                if w.oneway <= 0:
                    g.drive_adj.setdefault(b, []).append((e.idx, a))
            if w.walkable:
                g.walk_adj.setdefault(a, []).append((e.idx, b))
                g.walk_adj.setdefault(b, []).append((e.idx, a))
    _GRAPHS[key] = g
    return g
