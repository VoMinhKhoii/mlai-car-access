"""Parcel geometry supplies a gap estimate, not a physical clear-width measurement.

The HCMC planning portal returns cadastral parcel boundary polygons. A cross-section measures the gap from the
road centreline to each opposing parcel boundary; the usable-gap estimate subtracts USABLE_MARGIN but cannot
account for steps, ramps, stalls or parked vehicles. Its official provenance does not make the usable estimate
Official-tier or decisive clearance evidence.

Deep scans sample full OSM ways on legal ingress and egress paths, including endpoints and approximately every
DEEP_STEP metres, with a shared DEEP_MAX_CUTS budget. Sparse or truncated coverage stays diagnostic-only. Even
complete cuts do not prove that every obstruction between them is absent.
"""
from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor

import httpx
from shapely.geometry import LineString, Point, Polygon, shape

URL = "https://sqhkt-qlqh.tphcm.gov.vn/computing/930/api/v3.1/a-z/all"
HEADERS = {"User-Agent": "Mozilla/5.0 VaoDuoc-hackathon/0.3", "Referer": "https://thongtinquyhoach.hochiminhcity.gov.vn/"}
MAX_ALLEYS = 6
USABLE_MARGIN = 1.0   # m subtracted from every parcel gap
DEEP_STEP = 5.0       # m maximum intended spacing between deep-scan cuts
DEEP_MAX_CUTS = 60    # shared cap across full ways on ingress and egress paths
OFFSETS = (1.5, 3.0, 5.0)   # metres to each side: closest first, so a narrow alley hits the facing parcel
MIN_SIDE = 0.3              # a side closer than this means the map line sits on a parcel edge: reject the cut
KX, KY = 109_400.0, 110_540.0  # metres per degree at ~10.8° N


class Blocked(Exception):
    pass


def _parcel(lat: float, lon: float) -> dict | None:
    for attempt in range(2):  # the portal is slow at times: one retry, then give up on this point
        try:
            r = httpx.post(URL, data={"Lat": f"{lat:.7f}", "Lon": f"{lon:.7f}"}, headers=HEADERS, timeout=20)
            r.raise_for_status()
            break
        except httpx.HTTPError:
            if attempt:
                return None
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
        if len(dist) == 2 and min(dist) >= MIN_SIDE and 1.0 <= sum(dist) <= 15.0:
            return round(sum(dist), 2)
    return None


def _cut_at(line: LineString, d: float, lat0: float, lon0: float) -> dict | None:
    p, a, b = line.interpolate(d), line.interpolate(max(0.0, d - 1)), line.interpolate(min(line.length, d + 1))
    dx, dy = b.x - a.x, b.y - a.y
    norm = math.hypot(dx, dy) or 1.0
    lat, lon = lat0 + p.y / KY, lon0 + p.x / KX
    try:
        gap = _cross_section((lat, lon), (-dy / norm, dx / norm), lat0, lon0)
    except Blocked:
        raise
    except Exception:  # one bad cut must not lose the others
        gap = None
    if not gap:
        return None
    return {"lat": round(lat, 7), "lon": round(lon, 7), "at_m": round(d, 1), "gap_m": gap,
            "width_m": round(max(0.5, gap - USABLE_MARGIN), 2)}


def measure(way_coords: list[tuple[float, float]], step: float | None = None, max_cuts: int = 2) -> dict | None:
    """Return sampled usable-width estimates plus segment coverage diagnostics."""
    if len(way_coords) < 2 or max_cuts <= 0:
        return None
    lat0, lon0 = way_coords[0]
    line = LineString([_local(lo, la, lat0, lon0) for la, lo in way_coords])
    if not math.isfinite(line.length) or line.length < (6 if step else 16):
        return None
    if step and step > 0:
        segment_count = max(1, math.ceil(line.length / step))
        requested_count = segment_count + 1
        truncated = requested_count > max_cuts
        if truncated and max_cuts >= 2:
            targets = [line.length * round(i * segment_count / (max_cuts - 1)) / segment_count
                       for i in range(max_cuts)]
        elif truncated:
            targets = [line.length / 2]
        else:
            targets = [line.length * i / segment_count for i in range(requested_count)]
    else:
        targets = [line.length / 3, 2 * line.length / 3]
        truncated = False
    with ThreadPoolExecutor(min(3, len(targets))) as pool:
        cuts = [cut for cut in pool.map(lambda distance: _cut_at(line, distance, lat0, lon0), targets) if cut]
    if not cuts:
        return None
    positions = sorted(cut["at_m"] for cut in cuts)
    return {
        "samples": [cut["width_m"] for cut in cuts],
        "cuts": cuts,
        "segment_length_m": round(line.length, 1),
        "truncated": truncated,
        "max_spacing_m": round(max((b - a for a, b in zip(positions, positions[1:])), default=0.0), 1),
    }


def path_into(g, dest_lat: float, dest_lon: float) -> list[tuple[int, list[tuple[float, float]]]]:
    """Shortest drivable path from the nearest main road to the destination's door point, split per way:
    [(way_id, [(lat, lon), …]), …] from the main road inwards. Main-road stretches are left out."""
    from .plan import _interp, _path_nodes, _project, dijkstra  # local: plan imports the evidence store

    e, off, _ = _project(g, dest_lat, dest_lon, lambda w: w.drivable)
    if e is None:
        return []
    main = {n for w in g.ways.values() if w.kind == "main" and w.drivable for n in w.nodes}
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

def path_out(g, dest_lat: float, dest_lon: float) -> list[tuple[int, list[tuple[float, float]]]]:
    """Shortest legal directed route from the destination point to a main road, split by OSM way."""
    from .plan import _interp, _path_nodes, _project, dijkstra

    edge, offset, _ = _project(g, dest_lat, dest_lon, lambda way: way.drivable)
    if edge is None:
        return []
    way = g.ways[edge.way_id]
    sources = {}
    if way.oneway >= 0:
        sources[edge.v] = edge.length - offset
    if way.oneway <= 0:
        sources[edge.u] = offset
    main_nodes = {node for road in g.ways.values() if road.kind == "main" and road.drivable
                  for node in road.nodes}
    dist, pred = dijkstra(g.drive_adj, sources, lambda _: True, lambda idx: g.edges[idx].length)
    targets = [(dist[node], node) for node in main_nodes if node in dist]
    if not targets:
        return []
    _, main_node = min(targets)
    nodes = _path_nodes(pred, main_node)[::-1]
    destination = _interp(g, edge.u, edge.v, offset, edge.length)
    pieces: list[tuple[int, list[tuple[float, float]]]] = []
    for a, b in zip(nodes, nodes[1:]):
        way_id = g.edges[pred[b][0]].way_id
        if g.ways[way_id].kind == "main":
            continue
        if pieces and pieces[-1][0] == way_id:
            pieces[-1][1].append(g.nodes[b])
        else:
            pieces.append((way_id, [g.nodes[a], g.nodes[b]]))
    if way.kind != "main":
        if pieces and pieces[0][0] == edge.way_id:
            pieces[0][1].insert(0, destination)
        else:
            pieces.insert(0, (edge.way_id, [destination, g.nodes[nodes[0]]]))
    return pieces


def measure_area(g, dest_lat: float, dest_lon: float, cache: dict, haversine, deep: bool = True) -> list[dict]:
    """Scan full ways on legal ingress and egress paths, then shallow-scan nearby roads."""
    out: dict[int, dict] = {}
    budget = DEEP_MAX_CUTS
    paths = path_into(g, dest_lat, dest_lon) + path_out(g, dest_lat, dest_lon) if deep else []
    route_way_ids = list(dict.fromkeys(way_id for way_id, _ in paths))
    for way_id in route_way_ids:
        key = f"deep-v2:{dest_lat:.5f},{dest_lon:.5f}:{way_id}"
        if key not in cache and budget > 0:
            way = g.ways[way_id]
            coords = [g.nodes[node] for node in way.nodes]
            cache[key] = measure(coords, step=DEEP_STEP, max_cuts=budget)
        result = cache.get(key)
        if result:
            budget = max(0, budget - len(result.get("cuts", [])))
            out[way_id] = {"way_id": way_id, **result, "deep": True}

    near = []
    for way in g.ways.values():
        if way.kind == "main" or not way.drivable or way.id in out:
            continue
        distance = min(haversine(dest_lat, dest_lon, *g.nodes[node]) for node in way.nodes)
        if distance <= 400:
            near.append((distance, way))
    near.sort(key=lambda item: item[0])
    todo = [way for _, way in near if f"width-v2:{way.id}" not in cache][:MAX_ALLEYS]

    def one(way):
        try:
            return way.id, measure([g.nodes[node] for node in way.nodes])
        except Blocked:
            raise
        except Exception:
            return way.id, None

    with ThreadPoolExecutor(3) as pool:
        for way_id, result in pool.map(one, todo):
            cache[f"width-v2:{way_id}"] = result
    for _, way in near:
        result = cache.get(f"width-v2:{way.id}")
        if result and "cuts" in result:
            out[way.id] = {"way_id": way.id, **result, "deep": False}
    return list(out.values())


