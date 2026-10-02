"""Alley width from the HCMC cadastre (D32): the gap between the land parcels on either side of an alley.

The HCMC planning portal (thongtinquyhoach) answers a point with the land parcel there ("ranh" polygon, parcel
number). Cadastral parcels are surveyed, so unlike satellite footprints they resolve 2 m alleys. For an alley we
take two cross-sections (at 1/3 and 2/3 of its length): query a point a few metres to each side, get the two
parcels, and measure along the cross-section from the alley line to each parcel boundary.

The result is the legal right-of-way. Steps, ramps and stalls only narrow the built alley, so Evidence uses
[narrowest cut − 0.6 m, widest cut + 0.3 m] (≈ 0.3 m of steps or stalls per side). The endpoint is undocumented: few calls, low concurrency, cached per way, and the
build stops querying when the portal reports "blocked".
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor

import httpx
from shapely.geometry import LineString, Point, Polygon, shape

URL = "https://sqhkt-qlqh.tphcm.gov.vn/computing/930/api/v3.1/a-z/all"
HEADERS = {"User-Agent": "Mozilla/5.0 VaoDuoc-hackathon/0.3", "Referer": "https://thongtinquyhoach.hochiminhcity.gov.vn/"}
MAX_ALLEYS = 12
OFFSETS = (3.0, 5.0)        # metres to each side; the larger one is tried when the first lands in the alley
KX, KY = 109_400.0, 110_540.0  # metres per degree at ~10.8° N


class Blocked(Exception):
    pass


def _parcel(lat: float, lon: float) -> dict | None:
    r = httpx.post(URL, data={"Lat": f"{lat:.7f}", "Lon": f"{lon:.7f}"}, headers=HEADERS, timeout=30)
    r.raise_for_status()
    d = r.json()
    if d.get("blocked"):
        raise Blocked()
    info = json.loads(d["ThongTinChung"]) if isinstance(d.get("ThongTinChung"), str) else (d.get("ThongTinChung") or {})
    ranh = info.get("ranh")
    if not ranh:
        return None
    coords = json.loads(ranh) if isinstance(ranh, str) else ranh
    poly = shape({"type": "MultiPolygon", "coordinates": coords}) if isinstance(coords[0][0][0], list) else Polygon(coords[0])
    return {"id": info.get("mathuadat"), "poly": poly}


def _local(lon: float, lat: float, lat0: float, lon0: float) -> tuple[float, float]:
    return ((lon - lon0) * KX, (lat - lat0) * KY)


def _cross_section(p_ll, n_xy, lat0, lon0) -> float | None:
    """Width of one cross-section: query each side, then measure from the alley point to both parcels."""
    px, py = _local(p_ll[1], p_ll[0], lat0, lon0)
    for off in OFFSETS:
        sides = []
        for sgn in (1, -1):
            qx, qy = px + sgn * n_xy[0] * off, py + sgn * n_xy[1] * off
            sides.append(_parcel(lat0 + qy / KY, lon0 + qx / KX))
        if not all(sides) or sides[0]["id"] == sides[1]["id"]:
            continue
        polys = [Polygon([_local(x, y, lat0, lon0) for x, y in (g.exterior.coords)]) if g.geom_type == "Polygon"
                 else Polygon([_local(x, y, lat0, lon0) for x, y in max(g.geoms, key=lambda q: q.area).exterior.coords])
                 for g in (s["poly"] for s in sides)]
        alley_pt = Point(px, py)
        if any(pg.contains(alley_pt) for pg in polys):
            continue  # a parcel spans the alley line: the alley is not a separate strip here
        dist = []
        for sgn, pg in zip((1, -1), polys):
            ray = LineString([(px, py), (px + sgn * n_xy[0] * 15, py + sgn * n_xy[1] * 15)])
            hit = ray.intersection(pg.exterior)
            if hit.is_empty:
                break
            dist.append(alley_pt.distance(hit))
        if len(dist) == 2 and 1.0 <= sum(dist) <= 15.0:
            return round(sum(dist), 2)
    return None


def measure(way_coords: list[tuple[float, float]]) -> dict | None:
    """way_coords as (lat, lon). Two cross-sections; returns {"width_m": median, "samples": [...]} or None."""
    lat0, lon0 = way_coords[0]
    line = LineString([_local(lo, la, lat0, lon0) for la, lo in way_coords])
    if line.length < 16:
        return None
    samples = []
    for frac in (1 / 3, 2 / 3):
        d = line.length * frac
        p, a, b = line.interpolate(d), line.interpolate(max(0.0, d - 1)), line.interpolate(min(line.length, d + 1))
        dx, dy = b.x - a.x, b.y - a.y
        norm = math.hypot(dx, dy) or 1.0
        w = _cross_section((lat0 + p.y / KY, lon0 + p.x / KX), (-dy / norm, dx / norm), lat0, lon0)
        if w:
            samples.append(w)
    if not samples:
        return None
    return {"width_m": round(sorted(samples)[len(samples) // 2], 2), "samples": samples}


def measure_area(g, dest_lat: float, dest_lon: float, cache: dict, haversine) -> list[dict]:
    """Measure the alleys nearest the destination that are not cached yet (cache: way_id → result or None)."""
    alleys = []
    for w in g.ways.values():
        if w.kind == "main" or not w.drivable:
            continue
        d = min(haversine(dest_lat, dest_lon, *g.nodes[n]) for n in w.nodes)
        if d <= 400:
            alleys.append((d, w))
    alleys.sort(key=lambda x: x[0])
    todo = [w for _, w in alleys if str(w.id) not in cache][:MAX_ALLEYS]

    def one(w):
        try:
            return w.id, measure([g.nodes[n] for n in w.nodes])
        except Blocked:
            raise
        except Exception:
            return w.id, None

    with ThreadPoolExecutor(3) as pool:
        for wid, res in pool.map(one, todo):
            cache[str(wid)] = res
    return [{"way_id": int(k), **v} for k, v in cache.items() if v and any(int(k) == w.id for _, w in alleys)]
