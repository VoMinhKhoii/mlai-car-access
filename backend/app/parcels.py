"""Alley width from the HCMC cadastre (D32): the gap between the land parcels on either side of an alley.

The HCMC planning portal (thongtinquyhoach) answers a point with the land parcel there ("ranh" polygon, parcel
number). Cadastral parcels are surveyed, so unlike satellite footprints they resolve 2 m alleys. For an alley we
take two cross-sections (at 1/3 and 2/3 of its length): query a point a few metres to each side, get the two
parcels, and measure along the cross-section from the alley line to each parcel boundary.

How a cut is computed: the portal returns each parcel's boundary polygon (not just its area). At a point on the
alley we draw the line across it, ask for the parcel 3 m (then 5 m) to the left and to the right, and measure along
that line from the alley centreline to each parcel boundary; left + right = the parcel gap.

The gap is the legal right-of-way; steps, ramps, stalls and parked motorbikes narrow the built alley, so the
usable width of a cut is gap − 1.0 m (USABLE_MARGIN). Nearby roads get 2 cuts; the path from the main road to the
destination gets a cut every 5 m (DEEP_STEP), so its narrowest point is found wherever it is.
The endpoint is undocumented: low concurrency, cached, and the build stops when the portal reports "blocked".
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from concurrent.futures import ThreadPoolExecutor

import httpx
from shapely.geometry import LineString, Point, Polygon, shape
from shapely.ops import transform

URL = "https://sqhkt-qlqh.tphcm.gov.vn/computing/930/api/v3.1/a-z/all"
HEADERS = {"User-Agent": "Mozilla/5.0 VaoDuoc-hackathon/0.3", "Referer": "https://thongtinquyhoach.hochiminhcity.gov.vn/"}
MAX_ALLEYS = 6
USABLE_MARGIN = 1.0   # m subtracted from every parcel gap
DEEP_STEP = 5.0       # m between cuts on the path into the destination
DEEP_MAX_CUTS = 60    # 300 m of alley
OFFSETS = (1.5, 3.0, 5.0)   # metres to each side: closest first, so a narrow alley hits the facing parcel
MIN_SIDE = 0.3              # a side closer than this means the map line sits on a parcel edge: reject the cut
KX, KY = 109_400.0, 110_540.0  # metres per degree at ~10.8° N


class Blocked(Exception):
    pass


class Unavailable(Exception):
    """A transport failure is retryable, not a measured no-data result."""


def _parcel(lat: float, lon: float, client=None) -> dict | None:
    from . import portal_gate

    for attempt in range(2):  # the portal is slow at times: one retry, then give up on this point
        try:
            with portal_gate.slot():
                r = (client.post if client else httpx.post)(URL, data={"Lat": f"{lat:.7f}", "Lon": f"{lon:.7f}"}, headers=HEADERS, timeout=20)
            locked = r.status_code in (403, 429) or "temporarily locked" in r.text.lower()
            portal_gate.event("response", status=r.status_code, locked=locked)
            if locked:
                portal_gate.backoff()
                raise Blocked()
            r.raise_for_status()
            break
        except httpx.HTTPError as exc:
            portal_gate.event("transport_error", error=type(exc).__name__)
            if attempt:
                raise Unavailable(type(exc).__name__) from exc
    try:
        d = r.json()
    except ValueError as exc:
        raise Unavailable("Invalid portal JSON") from exc
    if d == []:
        return None
    if not isinstance(d, dict):
        raise Unavailable("Unexpected portal response")
    if d.get("blocked"):
        portal_gate.event("blocked_json")
        portal_gate.backoff()
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


def _cross_section(p_ll, n_xy, lat0, lon0, parcel_lookup=None) -> float | None:
    """Width of one cross-section: query each side, then measure from the alley point to both parcels."""
    px, py = _local(p_ll[1], p_ll[0], lat0, lon0)
    for off in OFFSETS:
        sides = []
        for sgn in (1, -1):
            qx, qy = px + sgn * n_xy[0] * off, py + sgn * n_xy[1] * off
            side = (parcel_lookup or _parcel)(lat0 + qy / KY, lon0 + qx / KX)
            if side is None:
                break  # no opposite parcel can make this offset valid; keep later offsets
            sides.append(side)
        if len(sides) != 2 or not all(sides) or sides[0]["id"] == sides[1]["id"]:
            continue
        polys = []
        for sgn, side in zip((1, -1), sides):
            pg = transform(lambda x, y, z=None: ((x-lon0)*KX, (y-lat0)*KY), side["poly"])
            query = Point(px + sgn*n_xy[0]*off, py + sgn*n_xy[1]*off)
            parts = [pg] if pg.geom_type == "Polygon" else list(pg.geoms)
            component = next((part for part in parts if part.covers(query)), None)
            if component is None:
                break
            polys.append(component)
        if len(polys) != 2:
            continue
        alley_pt = Point(px, py)
        if any(pg.contains(alley_pt) for pg in polys):
            continue  # a parcel spans the alley line: the alley is not a separate strip here
        dist = []
        for sgn, pg in zip((1, -1), polys):
            ray = LineString([(px, py), (px + sgn * n_xy[0] * 15, py + sgn * n_xy[1] * 15)])
            hit = ray.intersection(pg.boundary)
            if hit.is_empty:
                break
            dist.append(alley_pt.distance(hit))
        if len(dist) == 2 and min(dist) >= MIN_SIDE and 1.0 <= sum(dist) <= 15.0:
            return round(sum(dist), 2)
    return None


def _cut_at(line: LineString, d: float, lat0: float, lon0: float, parcel_lookup=None) -> dict | None:
    # A bisector across a corner measures the diagonal of the corridor (W2).
    # Reject nearby non-collinear vertices before querying any parcels.
    coords, along = list(line.coords), 0.0
    for i in range(1, len(coords)-1):
        a0, vertex, b0 = coords[i-1], coords[i], coords[i+1]
        along += math.dist(a0, vertex)
        ax, ay = vertex[0]-a0[0], vertex[1]-a0[1]
        bx, by = b0[0]-vertex[0], b0[1]-vertex[1]
        denom = math.hypot(ax, ay)*math.hypot(bx, by)
        if denom and abs(d-along) < 5 and (ax*bx+ay*by)/denom < math.cos(math.radians(15)):
            return None
    p, a, b = line.interpolate(d), line.interpolate(max(0.0, d - 1)), line.interpolate(min(line.length, d + 1))
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy) or 1.0
    lat, lon = lat0 + p.y / KY, lon0 + p.x / KX
    try:
        gap = _cross_section((lat, lon), (-dy / norm, dx / norm), lat0, lon0, parcel_lookup)
    except (Blocked, Unavailable):
        raise
    except Exception:  # one bad cut must not lose the others
        gap = None
    if not gap:
        return None
    return {"lat": round(lat, 7), "lon": round(lon, 7), "at_m": round(d, 1), "gap_m": gap,
            "width_m": round(max(0.0, gap - USABLE_MARGIN), 2), "valid": True,
            "heading_deg": round(math.degrees(math.atan2(dy, dx)), 2),
            "schema": "parcel-usable-v2", "usable_margin_m": USABLE_MARGIN}


def measure(way_coords: list[tuple[float, float]], step: float | None = None, max_cuts: int = 2,
            *, fractions=None, parcel_lookup=None) -> dict | None:
    """way_coords as (lat, lon). Cuts at 1/3 and 2/3 of the line, or every `step` metres (up to max_cuts).
    Returns {"samples": [usable widths], "cuts": [{lat, lon, at_m, gap_m, width_m}]} or None."""
    lat0, lon0 = way_coords[0]
    line = LineString([_local(lo, la, lat0, lon0) for la, lo in way_coords])
    if line.length < (6 if step or fractions is not None else 16):
        return None
    if step:
        at = [min(line.length - 1, step / 2 + i * step) for i in range(max_cuts) if step / 2 + i * step < line.length]
    else:
        at = [line.length * f for f in (fractions if fractions is not None else (1 / 3, 2 / 3))]
    if not at:
        return None
    with ThreadPoolExecutor(3 if step else 1) as pool:
        cuts = [c for c in pool.map(lambda d: _cut_at(line, d, lat0, lon0, parcel_lookup), at) if c]
    return {"samples": [c["width_m"] for c in cuts], "cuts": cuts,
            "schema": "parcel-usable-v2", "attempted": len(at),
            "attempts": [{"at_m": round(d, 1), "valid": any(abs(c['at_m']-d) <= .1 for c in cuts),
                          "reason": None if any(abs(c['at_m']-d) <= .1 for c in cuts)
                          else "geometry_invalid_or_no_opposing_frontage"} for d in at],
            "coverage": {"length_m": round(line.length, 2), "sampled_from_m": min(at), "sampled_to_m": max(at),
                         "all_valid": len(cuts) == len(at), "complete": False}}


def path_into(g, dest_lat: float, dest_lon: float) -> list[tuple[int, list[tuple[float, float]]]]:
    """Shortest drivable path from the nearest main road to the destination's door point, split per way:
    [(way_id, [(lat, lon), …]), …] from the main road inwards. Main-road stretches are left out."""
    from .plan import _interp, _path_nodes, _project, dijkstra  # local: plan imports the evidence store

    e, off, _ = _project(g, dest_lat, dest_lon, lambda w: w.drivable)
    if e is None:
        return []
    main = {n for w in g.ways.values() if w.kind == "main" and w.drivable for n in w.nodes}
    rev: dict[int, list] = {}
    for a, lst in g.drive_adj.items():
        for eidx, b in lst:
            rev.setdefault(b, []).append((eidx, a))
    dist, pred = dijkstra(g.drive_adj, {n: 0.0 for n in main}, lambda x: True, lambda x: g.edges[x].length)
    ends = [(dist[n] + (off if n == e.u else e.length - off), n) for n in (e.u, e.v) if n in dist]
    if not ends:
        return []
    _, last = min(ends)
    nodes = _path_nodes(pred, last)[::-1]  # main road → door edge end
    door = _interp(g, e.u, e.v, off, e.length)
    pieces: list[tuple[int, list]] = []
    for a, b in zip(nodes, nodes[1:]):
        wid = g.edges[pred[b][0]].way_id
        if g.ways[wid].kind == "main":
            continue
        if pieces and pieces[-1][0] == wid:
            pieces[-1][1].append(g.nodes[b])
        else:
            pieces.append((wid, [g.nodes[a], g.nodes[b]]))
    if g.ways[e.way_id].kind != "main":
        if pieces and pieces[-1][0] == e.way_id:
            pieces[-1][1].append(door)
        else:
            pieces.append((e.way_id, [g.nodes[last], door]))
    return pieces


@lru_cache(maxsize=1)
def point_cache():
    from .parcel_points import ParcelPoints
    return ParcelPoints()


def measure_area(g, dest_lat: float, dest_lon: float, cache: dict, haversine, city_cache: dict | None = None,
                 parcel_lookup=None) -> list[dict]:
    """Deep scan of the path into the destination (a cut every 5 m), plus 2 cuts on the nearest other roads.
    cache: key → result or None (keys "deep:<lat>,<lon>:<way>" and "<way>")."""
    # Breadth samples never replace the destination-specific 5 m scan. On a portal
    # failure live._merge_city still keeps those shallow samples, honestly labelled.
    city_cache = city_cache or {}
    out: dict[int, dict] = {}
    budget = DEEP_MAX_CUTS
    neighbors = {}
    for edge in g.edges:
        if g.ways[edge.way_id].drivable:
            neighbors.setdefault(edge.u, set()).add(edge.v)
            neighbors.setdefault(edge.v, set()).add(edge.u)
    junctions = [g.nodes[n] for n, arms in neighbors.items() if len(arms) >= 3]

    def validate_frontage(res):
        if not res:
            return res
        cuts = []
        for cut in res.get('cuts', []):
            cut = dict(cut)
            if 'lat' in cut and 'lon' in cut and any(haversine(cut['lat'],cut['lon'],*p) < 5 for p in junctions):
                cut.update(valid=False, reason='junction_frontage_unvalidated')
            cuts.append(cut)
        coverage = dict(res.get('coverage', {}))
        coverage['all_valid'] = bool(cuts) and all(c.get('valid', True) for c in cuts)
        return {**res, 'cuts': cuts, 'samples': [c['width_m'] for c in cuts if c.get('valid', True)], 'coverage': coverage}
    path = path_into(g, dest_lat, dest_lon)
    path_ids = {wid for wid, _ in path}
    warm_path = bool(path) and all(str(wid) in city_cache for wid, _ in path)
    for wid, coords in path:
        key = f"deep:{dest_lat:.5f},{dest_lon:.5f}:{wid}"
        path_length = sum(math.hypot((b[1]-a[1])*KX,(b[0]-a[0])*KY) for a,b in zip(coords,coords[1:]))
        attempted = min(budget, max(0, math.ceil((path_length-DEEP_STEP/2)/DEEP_STEP)))
        # A city-level `deep` boolean does not prove this destination's coverage.
        if key not in cache and budget > 0:
            res = measure(coords, step=DEEP_STEP, max_cuts=attempted, parcel_lookup=parcel_lookup)
            cache[key] = validate_frontage(res)
        budget -= attempted
        res = cache.get(key)
        if res:
            out[wid] = {"way_id": wid, **res, "deep": True}
        elif city_cache.get(str(wid)):
            out[wid] = {"way_id": wid, **city_cache[str(wid)], "deep": False}

    near = []
    for w in g.ways.values():
        if w.kind == "main" or not w.drivable or w.id in out or w.id in path_ids:
            continue
        d = min(haversine(dest_lat, dest_lon, *g.nodes[n]) for n in w.nodes)
        if d <= 400:
            near.append((d, w))
    near.sort(key=lambda x: x[0])
    todo = [w for _, w in near if str(w.id) not in cache and str(w.id) not in city_cache][:MAX_ALLEYS]
    if warm_path:
        todo = []  # city-covered route: use saved nearby widths; uncovered branches remain unknown

    def one(w):
        try:
            return w.id, validate_frontage(measure([g.nodes[n] for n in w.nodes], parcel_lookup=parcel_lookup))
        except (Blocked, Unavailable):
            raise
        except Exception:
            return w.id, None

    with ThreadPoolExecutor(3) as pool:
        for wid, res in pool.map(one, todo):
            cache[str(wid)] = res
    for _, w in near:
        res = cache.get(str(w.id)) or city_cache.get(str(w.id))
        if res and "cuts" in res:
            out[w.id] = {"way_id": w.id, **res, "deep": bool(res.get("deep"))}
    return list(out.values())
