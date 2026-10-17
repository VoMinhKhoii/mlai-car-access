"""Arrival Plan engine: filter Stop Points by Hard Checks, then rank by walk (Q2, Q5–Q7, Q12, D15–D19)."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import flags, hydro, parking_data
from .config import (ALLEY_SPEED_MPS, FLOOD_TIMING_HORIZON_H, FLOOD_TIMING_STEP_MIN,
                     FLOOD_TRAVERSAL_MARGIN_MIN, GOONG_API_KEY, CACHED_ONLY, PICKUP_DWELL_MIN,
                     REVERSE_LIMIT_M, WALK_CAP_M, WALK_WADE_M)
from .evidence import (STORE_EVIDENCE, WidthRange, blocked_ways_today, english_payload,
                       english_text, width_ranges)
from .flood import (KNOWLEDGE_ORDER, STATUS_ORDER, FloodAssessment, FloodSnapshot, _street_key,
                    alarm_label, evidence_generation, flood_profiles, worst_over)
from .legality import ORDER as LEGAL_ORDER
from .legality import StopRule, legality_for_lot, legality_over_window, supports_legal_lane_count
from .osm import AreaGraph, area_key, build_graph, haversine
from .storage import LRU
from .vehicles import VehicleProfile, get_profile, three_point_width, turn_in_width

VN_TZ = timezone(timedelta(hours=7))
WALK_SPEED = 1.2  # m/s
WALK_CONNECTION_CAP_M = 35.0
WALK_SNAP_M = 5.0  # connector shorter than this is projection noise, not an unmapped gap
INF = float("inf")

# Bounded caches keyed by everything their content depends on: graph identity (area key + source), AI flags, the
# published evidence generation and the area build revision. An area overlay never leaks into another key.
_WR = LRU(32)
_FP = LRU(32)


def area(lat: float, lon: float, generations: tuple[str, str] | None = None, live_area: dict | None = None,
         synthetic_demo_file: Path | None = None):
    STORE_EVIDENCE.refresh_footprints()
    g = build_graph(lat, lon)
    key = (area_key(lat, lon), g.source, id(g), tuple(f["enabled"] for f in flags.describe()),
           synthetic_demo_file)
    from . import live
    city = live.city_parcels()
    if flags.enabled("parcel_widths") and live_area is None:
        # D57: dynamic area evidence expires; dated static portal geometry does
        # not. Use the validated server-cache loader, never arbitrary JSON.
        record = live._load_area(live.area_key(lat, lon))
        if record:
            try:
                observed = datetime.fromisoformat(record["collected_at"])
                dated = observed.tzinfo is not None and observed <= datetime.now(VN_TZ)
            except (KeyError, TypeError, ValueError):
                dated = False
            if dated and record.get("parcels"):
                live_area = {"key": record["key"],
                             "revision": f"{record['revision']}:static-parcels:{record['collected_at']}",
                             "collected_at": record["collected_at"], "parcels": record["parcels"],
                             "listings": [], "photos": [], "news": []}
    if flags.enabled("parcel_widths"):
        dated_parcels = [{**pc, "observed_on": pc.get("observed_on") or pc.get("queried_at")
                         or (live_area or {}).get("collected_at", "")}
                        for pc in (live_area or {}).get("parcels", []) if isinstance(pc, dict)]
        # Do not let an undated partial legacy scan mask a richer city deep
        # survey. Explicit newer survey timestamps still take precedence.
        dated_parcels = [pc for pc in dated_parcels if not (
            len((current := city.get(str(pc.get("way_id"))) or {}).get("cuts", []))
            > len(pc.get("cuts", []))
            and not (pc.get("queried_at") and current.get("queried_at")
                     and pc["queried_at"] > current["queried_at"]))]
        merged_parcels = live._merge_city(g, dated_parcels)
        if merged_parcels:
            live_area = {"listings": [], "photos": [], **(live_area or {}), "parcels": merged_parcels,
                         "revision": str((live_area or {}).get("revision", "")) + ":" + str(id(city))}
    view = STORE_EVIDENCE.view(live_area, synthetic_demo_file=synthetic_demo_file)
    wkey = key + (STORE_EVIDENCE.version, (live_area or {}).get("key"), (live_area or {}).get("revision"))
    wrs = _WR.get(wkey)
    if wrs is None:
        wrs = width_ranges(g, view)
        _WR.put(wkey, wrs)
    evidence_generations = generations or evidence_generation()
    fkey = key + evidence_generations[:1]
    fps = _FP.get(fkey)
    if fps is None:
        fps = flood_profiles(g)
        _FP.put(fkey, fps)
    return g, wrs, fps


def invalidate_evidence() -> None:
    _WR.clear()


# ---- per-vehicle fit ----------------------------------------------------------

def fit_class(wr: WidthRange, p: VehicleProfile) -> str:
    if wr.lo >= p.fits_min:
        result = "fits"
    elif wr.lo >= p.tight_min:
        result = "tight"
    elif wr.hi < p.tight_min:
        return "no"
    else:
        return "unknown"
    return result if wr.decisive_clearance else "unknown"

def compute_fit(g: AreaGraph, wrs: dict[int, WidthRange], p: VehicleProfile):
    fit, notes = {}, {}
    for wid, w in g.ways.items():
        fit[wid] = fit_class(wrs[wid], p) if w.drivable else "no"
    # D16: turning in from the parent street; failing it downgrades "fits" to "tight".
    for wid, w in g.ways.items():
        if fit[wid] != "fits" or w.kind == "main" or wrs[wid].lo >= 6:
            continue
        for n in (w.nodes[0], w.nodes[-1]):
            for pid in g.node_ways.get(n, ()):
                if pid == wid or not g.ways[pid].drivable:
                    continue
                if not wrs[pid].decisive_clearance:
                    fit[wid] = "unknown"
                    notes[wid] = "Complete clear-width measurements are missing at the turn"
                    break
                if wrs[pid].lo <= wrs[wid].lo:
                    continue
                street = min(round(wrs[pid].lo * 2) / 2, 12.0)
                need = turn_in_width(p.id, street)
                if wrs[wid].lo < need:
                    fit[wid] = "tight"
                    notes[wid] = f"Turning in from {g.ways[pid].name or 'main road'} may require multiple moves (one-turn entry needs width ≥ {need:.1f} m)"
    for wid, b in blocked_ways_today().items():
        if wid in fit:
            fit[wid] = "blocked"
            notes[wid] = f"Temporarily blocked today: {b.get('reason', 'obstruction')} ({b.get('source', 'driver report')})"
    return fit, notes


# ---- graph search ---------------------------------------------------------------

def _usable(fit: str, flood: str, strict: bool) -> bool:
    if fit in ("no", "blocked") or flood == "blocked":
        return False
    if strict and (fit == "unknown" or flood == "risky"):
        return False
    return True


def _cost(length: float, fit: str) -> float:
    return length * (1.3 if fit == "tight" else 1.15 if fit == "unknown" else 1.0)


def dijkstra(adj, sources: dict[int, float], edge_ok, edge_cost, limit=INF):
    dist = dict(sources)
    pred: dict[int, tuple[int, int]] = {}
    pq = [(d, n) for n, d in sources.items()]
    heapq.heapify(pq)
    while pq:
        d, n = heapq.heappop(pq)
        if d > dist.get(n, INF) or d > limit:
            continue
        for eidx, m in adj.get(n, ()):
            if not edge_ok(eidx):
                continue
            nd = d + edge_cost(eidx)
            if nd < dist.get(m, INF):
                dist[m] = nd
                pred[m] = (eidx, n)
                heapq.heappush(pq, (nd, m))
    return dist, pred


def _path_nodes(pred, node):
    out = [node]
    while node in pred:
        node = pred[node][1]
        out.append(node)
    return out  # node → source


def _coords(g: AreaGraph, nodes):
    return [[g.nodes[n][1], g.nodes[n][0]] for n in nodes]


def _interp(g: AreaGraph, u: int, v: int, s: float, length: float):
    (la, lo), (lb, lob) = g.nodes[u], g.nodes[v]
    f = 0 if length == 0 else s / length
    return la + (lb - la) * f, lo + (lob - lo) * f


def _project(g: AreaGraph, lat: float, lon: float, predicate, edges=None):
    """Nearest point on an edge whose way satisfies predicate → (edge, offset from u, distance).
    `edges` limits the search to a precomputed subset (default: the whole graph)."""
    best = (None, 0.0, INF)
    kx = math.cos(math.radians(lat)) * 111320
    ky = 110540
    for e in g.edges if edges is None else edges:
        if not predicate(g.ways[e.way_id]):
            continue
        (la, lo), (lb, lob) = g.nodes[e.u], g.nodes[e.v]
        ax, ay = (lo - lon) * kx, (la - lat) * ky
        bx, by = (lob - lon) * kx, (lb - lat) * ky
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / L2))
        px, py = ax + t * dx, ay + t * dy
        d = math.hypot(px, py)
        if d < best[2]:
            best = (e, t * e.length, d)
    return best


# ---- plan -------------------------------------------------------------------------

@dataclass
class Candidate:
    kind: str                 # door | street | lot
    lat: float
    lon: float
    name: str
    way_id: int | None
    edge_idx: int | None = None
    offset: float = 0.0       # from edge.u
    walk_m: float = INF
    walk_node: int | None = None
    walk_tail: float = 0.0
    lot: dict | None = None
    entrance: int | None = None
    data: dict = field(default_factory=dict)

@dataclass
class PlanContext:
    g: AreaGraph
    wrs: dict[int, WidthRange]
    fps: dict
    fit: dict[int, str]
    fit_notes: dict[int, str]
    paid: dict
    vehicle: VehicleProfile
    intent: str
    rain: list[dict]
    flood: FloodSnapshot
    candidates: list[Candidate]
    shared: object | None = None
    legality_cache: dict[tuple[int, date, date], tuple[str, list[StopRule]]] = field(default_factory=dict)
    flood_aggregate_cache: dict = field(default_factory=dict)



def plan(dest_lat: float, dest_lon: float, vehicle_id: str, intent: str, arrive_at: datetime | None,
         dwell_min: int | None, rain_scenario: list[dict] | None = None, dest_label: str = "",
         origin: tuple[float, float] | None = None, live_area: dict | None = None,
         synthetic_demo_scenario: str | None = None, synthetic_demo_file: Path | None = None) -> dict:
    # FloodSnapshot captures file generations, metadata, reports, and rain once for this request.
    vehicle = get_profile(vehicle_id)
    arrive = (arrive_at or datetime.now(VN_TZ)).astimezone(VN_TZ)
    dwell = dwell_min if dwell_min is not None else (PICKUP_DWELL_MIN if intent == "pickup" else 120)
    if dwell < 0:
        raise ValueError("Dwell duration must be nonnegative")
    depart = arrive + timedelta(minutes=dwell)
    rain = (list(rain_scenario) if rain_scenario is not None and len(rain_scenario) > 0 else
            (hydro.rain_spells(dest_lat, dest_lon) if flags.enabled("live_hydro") else []))
    flood_snapshot = FloodSnapshot(rain)
    cap = WALK_CAP_M[intent]

    g, wrs, fps = area(dest_lat, dest_lon, flood_snapshot.generations, live_area, synthetic_demo_file)
    fit, fit_notes = compute_fit(g, wrs, vehicle)
    paid = parking_data.paid_street_ways(g)
    main_nodes = {n for way in g.ways.values() if way.kind == "main" and way.drivable for n in way.nodes}
    rev_adj: dict[int, list[tuple[int, int]]] = {}
    for node, edges in g.drive_adj.items():
        for edge_idx, other in edges:
            rev_adj.setdefault(other, []).append((edge_idx, node))

    we, woff, wd = _project(g, dest_lat, dest_lon, lambda way: way.walkable)
    walk_connection_missing = we is None or wd > WALK_CONNECTION_CAP_M
    if walk_connection_missing:
        wdist, wpred = {}, {}
    else:
        walk_src = {we.u: wd + woff, we.v: wd + (we.length - woff)}
        wdist, wpred = dijkstra(g.walk_adj, walk_src, lambda edge: True,
                                lambda edge: g.edges[edge].length, limit=cap + 60)
    de, doff, ddist = _project(g, dest_lat, dest_lon, lambda way: way.drivable)
    # Only walk edges the walking search reached can give a finite walking distance: project onto those alone.
    reached_walk_edges = [e for e in g.edges if g.ways[e.way_id].walkable and (e.u in wdist or e.v in wdist)]

    def walk_access(lat: float, lon: float, road_edge=None, road_offset: float | None = None):
        if walk_connection_missing:
            return None
        if road_edge is not None and g.ways[road_edge.way_id].walkable:
            walk_edge, walk_offset, connector = road_edge, road_offset, 0.0
        else:
            walk_edge, walk_offset, connector = _project(g, lat, lon, lambda way: True, reached_walk_edges)
        if walk_edge is None or connector > WALK_CONNECTION_CAP_M:
            return None
        network_distance, _ = _walk_start(walk_edge, walk_offset, wdist, we, woff, wd)
        if not math.isfinite(network_distance):
            return None
        return {"walk_edge_idx": walk_edge.idx, "walk_offset": walk_offset,
                "walk_connector_m": connector, "walk_destination_connector_m": wd}, connector + network_distance

    candidates: list[Candidate] = []
    walk_connection_rejected = False
    walk_candidate_count = 0
    if not walk_connection_missing and de is not None and ddist <= WALK_CONNECTION_CAP_M:
        la, lo = _interp(g, de.u, de.v, doff, de.length)
        access = walk_access(la, lo, de, doff)
        if access is not None and access[1] <= cap:
            candidates.append(Candidate("door", la, lo, "At the door", de.way_id, de.idx, doff,
                                        walk_m=access[1], data=access[0]))
            walk_candidate_count += 1
        else:
            walk_connection_rejected = True
    for edge in g.edges:
        way = g.ways[edge.way_id]
        if not way.drivable:
            continue
        # Walking is never shorter than the straight line: an edge whose nearer end is farther than the walk cap
        # plus the edge's own length cannot hold a stop within the cap. This bound is exact, not a heuristic.
        near_end = min(haversine(dest_lat, dest_lon, *g.nodes[edge.u]), haversine(dest_lat, dest_lon, *g.nodes[edge.v]))
        if near_end - edge.length > cap:
            continue
        offsets = [edge.length / 2] if edge.length < 16 else [8.0, edge.length / 2, edge.length - 8.0]
        for offset in offsets:
            la, lo = _interp(g, edge.u, edge.v, offset, edge.length)
            access = walk_access(la, lo, edge if way.walkable else None,
                                 offset if way.walkable else None)
            if access is None:
                walk_connection_rejected = True
                continue
            walk_data, walk = access
            if walk > cap:
                continue
            candidates.append(Candidate("street", la, lo, g.display_name(way.id), way.id, edge.idx,
                                        offset, walk_m=walk, data=walk_data))
            walk_candidate_count += 1
    for lot in parking_data.lots_near(g, dest_lat, dest_lon, radius=cap + 150):
        entrance, entrance_d = g.nearest_node(lot["lat"], lot["lon"], lambda node: node in g.drive_adj)
        access = walk_access(lot["lat"], lot["lon"])
        if entrance is None or entrance_d > 80 or access is None:
            walk_connection_rejected = True
            continue
        walk_data, walk = access
        if walk <= cap:
            access_ways = sorted(wid for wid in g.node_ways.get(entrance, ()) if g.ways[wid].drivable)
            candidates.append(Candidate("lot", lot["lat"], lot["lon"], lot["name"], None, walk_m=walk,
                                        lot=lot, entrance=entrance,
                                        data={"entrance_d": entrance_d, "access_way_ids": access_ways,
                                              **walk_data}))
            walk_candidate_count += 1

    ctx = PlanContext(g, wrs, fps, fit, fit_notes, paid, vehicle, intent, rain, flood_snapshot, candidates)
    ctx.shared = _SharedRoutes(g, wrs)
    report_keys = {_street_key(report.get("street", "")) for report in flood_snapshot.reports}
    dynamic_flood_ways = set(fps)
    dynamic_flood_ways.update(
        way_id for way_id in g.ways
        if _street_key(g.display_name(way_id)) in report_keys)
    static_unknown_flood = FloodAssessment(
        "risky", None, "missing_history",
        "No flood history or current observations for this segment", None)

    class LazyFloodMap:
        """Resolve only ways reached by Dijkstra; share results for one temporal interval."""

        def __init__(self, times_key: tuple[datetime, ...]):
            self.times_key = times_key
            self.assessments: dict[int, FloodAssessment] = {}
            self.reads: set[int] | None = None

        def __getitem__(self, way_id: int) -> FloodAssessment:
            if way_id not in dynamic_flood_ways:
                return static_unknown_flood
            if self.reads is not None:
                self.reads.add(way_id)
            if way_id not in self.assessments:
                self.assessments[way_id] = worst_over(
                    fps.get(way_id), list(self.times_key), rain, vehicle.safe_water_depth,
                    g.display_name(way_id), flood_snapshot)
            return self.assessments[way_id]

    flood_maps: dict[tuple[datetime, ...], LazyFloodMap] = {}

    def flood_at(times) -> LazyFloodMap:
        times_key = tuple(sorted(set(times)))
        if times_key not in flood_maps:
            flood_maps[times_key] = LazyFloodMap(times_key)
        return flood_maps[times_key]

    # Exact time keys avoid repeated work within a window. Across timing ticks, a network
    # is also reusable when every way Dijkstra inspected has the same flood status: with
    # unchanged edge decisions and costs, the algorithm follows the identical search.
    search_cache: dict[tuple[str, tuple[datetime, ...] | None, bool], tuple[dict, dict]] = {}
    search_variants: dict[tuple[str, bool], list[tuple[tuple[tuple[int, str], ...],
                                                       tuple[dict, dict]]]] = {}
    network_dijkstra_calls = 0

    def search(direction, adj, times_key, strict):
        nonlocal network_dijkstra_calls
        key = (direction, times_key, strict)
        if key in search_cache:
            return search_cache[key]
        flood_map = flood_at(times_key) if times_key is not None else None
        if flood_map is not None:
            for signature, network in search_variants.get((direction, strict), ()):
                if all(flood_map[way_id].status == status for way_id, status in signature):
                    search_cache[key] = network
                    return network
            flood_map.reads = set()
        network = dijkstra(
            adj, {node: 0.0 for node in main_nodes},
            lambda edge: _usable(
                fit[g.edges[edge].way_id],
                flood_map[g.edges[edge].way_id].status if flood_map is not None else "passable",
                strict),
            lambda edge: _cost(g.edges[edge].length, fit[g.edges[edge].way_id]))
        network_dijkstra_calls += 1
        if flood_map is not None:
            signature = tuple(sorted(
                (way_id, flood_map.assessments[way_id].status) for way_id in flood_map.reads))
            flood_map.reads = None
            search_variants.setdefault((direction, strict), []).append((signature, network))
        search_cache[key] = network
        return network

    fit_arr = {strict: search("arrival-fit", g.drive_adj, None, strict) for strict in (True, False)}
    fit_ext = {strict: search("exit-fit", rev_adj, None, strict) for strict in (True, False)}
    route_cache: dict[tuple, dict | None] = {}
    exit_cache: dict[tuple, dict] = {}

    def route_for(idx, networks, times=None):
        key = (idx, id(networks[True]), id(networks[False]), tuple(times or ()))
        if key not in route_cache:
            route_cache[key] = _best_route(ctx.candidates[idx], ctx, networks, times)
        return route_cache[key]

    def exit_for(idx, networks, route, times=None):
        route_key = (route.get("strict"), route.get("side"), tuple(route.get("edge_ids", ())))
        key = (idx, id(networks[True]), id(networks[False]), route_key, tuple(times or ()))
        if key not in exit_cache:
            exit_cache[key] = _best_way_out(ctx.candidates[idx], ctx, networks, route, times)
        return exit_cache[key]

    fit_routes = {idx: route_for(idx, fit_arr) for idx in range(len(ctx.candidates))}
    fit_exits = {
        idx: exit_for(idx, fit_ext, fit_routes[idx]) if fit_routes[idx] is not None
        else _way_out(ctx.candidates[idx], g, wrs, fit, vehicle, fit_ext, None)
        for idx in range(len(ctx.candidates))
    }

    bucket_time_cache: dict[tuple[datetime, int, bool], tuple[datetime, ...]] = {}

    def bucket_times(anchor: datetime, metres: float, arriving: bool) -> tuple[datetime, ...]:
        duration_s = _traversal_duration(metres).total_seconds()
        bucket_s = FLOOD_TIMING_STEP_MIN * 60
        conservative_s = max(bucket_s, math.ceil(duration_s / bucket_s) * bucket_s)
        key = (anchor, conservative_s, arriving)
        if key not in bucket_time_cache:
            delta = timedelta(seconds=conservative_s)
            start, end = ((anchor - delta, anchor) if arriving else (anchor, anchor + delta))
            bucket_time_cache[key] = tuple(flood_snapshot.sample_times(start, end))
        return bucket_time_cache[key]

    def grouped_networks(direction, adj, states):
        by_times: dict[tuple[datetime, ...], dict[bool, tuple[dict, dict]]] = {}
        for times_key in set(states.values()):
            by_times[times_key] = {
                strict: search(direction, adj, times_key, strict) for strict in (True, False)
            }
        return {idx: by_times[times_key] for idx, times_key in states.items()}

    def candidate_networks(candidate_indices, window_arrive, window_depart):
        arr_states = {
            idx: bucket_times(window_arrive, fit_routes[idx]["meters"], True)
            for idx in candidate_indices if fit_routes[idx] is not None
        }
        arr_networks = {idx: fit_arr for idx in candidate_indices if idx not in arr_states}
        arr_routes = {idx: None for idx in candidate_indices}
        for _ in range(4):
            current = grouped_networks("arrival", g.drive_adj, arr_states)
            arr_networks.update(current)
            changed = False
            for idx, networks in current.items():
                route = route_for(idx, networks, arr_states[idx])
                arr_routes[idx] = route
                if route is None:
                    continue
                next_times = bucket_times(window_arrive, route["meters"], True)
                if next_times != arr_states[idx]:
                    arr_states[idx] = next_times
                    changed = True
            if not changed:
                break
        if arr_states:
            arr_networks.update(grouped_networks("arrival", g.drive_adj, arr_states))
            for idx in arr_states:
                arr_routes[idx] = route_for(idx, arr_networks[idx], arr_states[idx])

        exit_states = {}
        for idx in candidate_indices:
            route = arr_routes.get(idx)
            if route is None:
                continue
            initial_exit = exit_for(idx, fit_ext, route)
            if initial_exit["mode"] != "none":
                exit_states[idx] = bucket_times(
                    window_depart, _way_out_meters(initial_exit, g), False)
        ext_networks = {idx: fit_ext for idx in candidate_indices if idx not in exit_states}
        for _ in range(4):
            current = grouped_networks("exit", rev_adj, exit_states)
            ext_networks.update(current)
            changed = False
            for idx, networks in current.items():
                way_out = exit_for(idx, networks, arr_routes[idx], exit_states[idx])
                if way_out["mode"] == "none":
                    continue
                next_times = bucket_times(
                    window_depart, _way_out_meters(way_out, g), False)
                if next_times != exit_states[idx]:
                    exit_states[idx] = next_times
                    changed = True
            if not changed:
                break
        if exit_states:
            ext_networks.update(grouped_networks("exit", rev_adj, exit_states))

        return {
            idx: (arr_networks[idx], ext_networks[idx], fit_arr, fit_ext,
                  list(arr_states.get(idx, (window_arrive,))),
                  list(exit_states.get(idx, (window_depart,))))
            for idx in candidate_indices
        }

    def can_ever_qualify(idx: int) -> bool:
        candidate = ctx.candidates[idx]
        return _timing_static_eligible(
            candidate, fit, wrs, vehicle, fit_routes[idx], fit_exits[idx])

    timing_candidate_indices = [
        idx for idx in range(len(ctx.candidates)) if can_ever_qualify(idx)
    ]

    def dwell_times_for(window_arrive, window_depart):
        dwell_times = {window_arrive, window_depart}
        cursor = window_arrive
        while cursor < window_depart:
            dwell_times.add(cursor)
            cursor += timedelta(minutes=FLOOD_TIMING_STEP_MIN)
        dwell_times.update(flood_snapshot.sample_times(window_arrive, window_depart))
        return sorted(dwell_times)

    def evaluate_window(window_arrive, window_depart):
        stay_times = dwell_times_for(window_arrive, window_depart)
        passed, rejected, door_result = [], [], None
        candidate_indices = list(range(len(ctx.candidates)))
        networks_by_candidate = candidate_networks(
            candidate_indices, window_arrive, window_depart)
        for idx in candidate_indices:
            candidate = ctx.candidates[idx]
            result = _evaluate(
                candidate, ctx, window_arrive, window_depart, stay_times,
                *networks_by_candidate[idx])
            if candidate.kind == "door":
                door_result = result
            (passed if result["ok"] else rejected).append(result)
        return passed, rejected, door_result

    def qualifies_window(window_arrive, window_depart):
        stay_times = dwell_times_for(window_arrive, window_depart)
        networks_by_candidate = candidate_networks(
            timing_candidate_indices, window_arrive, window_depart)
        return any(
            _candidate_timing_qualified(
                ctx.candidates[idx], ctx, window_arrive, window_depart, stay_times,
                networks_by_candidate[idx][0], networks_by_candidate[idx][1],
                networks_by_candidate[idx][4], networks_by_candidate[idx][5])
            for idx in timing_candidate_indices)

    results, rejected, door_eval = evaluate_window(arrive, depart)
    results.sort(key=_stop_order)
    chosen = _choose(results)
    result_order = {
        id(result["_c"]): (0 if result["ok"] else 1, result["tier"], result["walk"]["meters"])
        for result in results + rejected
    }
    timing_candidate_indices.sort(
        key=lambda idx: result_order.get(id(ctx.candidates[idx]), (2, INF, INF)))
    for rank, result in enumerate(chosen, 1):
        result["rank"] = rank
        result["walk"]["geometry"] = _walk_geometry(
            g, result["_c"], wpred, wdist, we, woff, dest_lat, dest_lon)
        result["walk"]["wade"] = _walk_wade(g, fps, result["_c"], wpred, wdist, arrive, rain,
                                               flood_snapshot, vehicle.safe_water_depth, we, woff)

    failure_codes = sorted({code for result in rejected for code in result["failure_codes"]})

    no_stop_reason = ("missing_walk_connection"
                      if not chosen and walk_candidate_count == 0
                      and (walk_connection_missing or walk_connection_rejected) else None)
    verdict = _verdict(chosen, door_eval, intent, cap)
    decisive = chosen[0] if chosen else door_eval
    verdict["profile"] = decisive.get("profile", []) if decisive else []
    verdict["decided_by"] = decisive.get("estimate", {}).get("decided_by", "walk") if decisive else "walk"
    verdict["door_estimate"] = door_eval.get("estimate") if door_eval else None
    verdict["door_profile"] = door_eval.get("profile", []) if door_eval else []
    if no_stop_reason:
        verdict["detail"] = "No mapped walking connection to a stop within 35 m."
    if chosen:
        verdict["estimate"] = chosen[0].get("estimate")
    elif door_eval:
        verdict["estimate"] = door_eval.get("estimate")
    else:
        verdict['estimate'] = {
            'answer': 'unknown' if no_stop_reason else 'no', 'confidence': 'low',
            'basis': ('Insufficient walking connections or road network for an estimate' if no_stop_reason else
                      'No stop passed the checks in the cached road network')}
    timing = None
    flood_timing_needed = _needs_flood_timing(chosen, rejected)
    if flood_timing_needed:
        def qualifies(candidate_arrive, candidate_depart):
            return qualifies_window(candidate_arrive, candidate_depart)

        timing = _flood_timing(intent, arrive, depart, qualifies, failure_codes)
        if timing["leave_before_at"]:
            before_depart = datetime.fromisoformat(timing["leave_before_at"])
            before_arrive = arrive
            alt_passed, _, alt_door = evaluate_window(before_arrive, before_depart)
            alt_chosen = _choose(sorted(alt_passed, key=_stop_order))
            alt_verdict = _verdict(alt_chosen, alt_door, intent, cap)
            timing["if_leave_before"] = {"headline": alt_verdict["headline"], "code": alt_verdict["code"]}

    for result in results + rejected:
        result.pop("_c", None)

    std = _standard_route(g, de, doff, fit, wrs)
    if GOONG_API_KEY and std:
        start = origin or (std["geometry"][0][1], std["geometry"][0][0])
        goong = goong_standard_route(g, start, (dest_lat, dest_lon), fit, wrs, GOONG_API_KEY)
        if goong:
            std = goong
    if origin and GOONG_API_KEY:
        _add_trips(chosen, origin)
    synthetic_demo_data = synthetic_demo_file is not None
    displayed_demo_scenario = synthetic_demo_scenario if synthetic_demo_data else None

    return english_payload({
        "destination": {"lat": dest_lat, "lon": dest_lon, "label": dest_label},
        "vehicle": vehicle.to_json(), "intent": intent,
        "window": {"arrive": arrive.isoformat(), "depart": depart.isoformat(), "dwell_min": dwell,
                   "tide_arrive": _tide_json(arrive, flood_snapshot),
                   "tide_depart": _tide_json(depart, flood_snapshot), "rain": rain},
        "verdict": verdict, "timing": timing, "stop_points": chosen, "door": door_eval,
        "synthetic_demo_data": synthetic_demo_data,
        "synthetic_demo_scenario": displayed_demo_scenario,
        "no_stop_reason": no_stop_reason,
        "standard_route": std,
        "layers": _layers(g, wrs, fit, fit_notes, fps, dest_lat, dest_lon, arrive, depart,
                          rain, vehicle, flood_snapshot),
        "area_source": g.source,
        "counts": {"candidates": len(candidates), "passed": len(results), "rejected": len(rejected),
                   "dijkstra": network_dijkstra_calls + 1 + int(de is not None)},
    })


def _choose(results: list[dict]) -> list[dict]:
    chosen = []
    for result in results:
        same_way = result.get("way_id") and any(item.get("way_id") == result["way_id"] for item in chosen)
        if not same_way and all(haversine(result["lat"], result["lon"], item["lat"], item["lon"]) > 45
                                for item in chosen):
            chosen.append(result)
        if len(chosen) == 3:
            break
    return chosen


def _traversal_duration(metres: float) -> timedelta:
    seconds = 2 * max(0.0, metres) / ALLEY_SPEED_MPS + FLOOD_TRAVERSAL_MARGIN_MIN * 60
    return timedelta(seconds=seconds)


def _way_out_meters(way_out: dict, g: AreaGraph) -> float:
    return way_out.get("meters", sum(g.edges[idx].length for idx in way_out.get("edge_ids", ())))


def _timing_static_eligible(candidate: Candidate, fit: dict[int, str],
                            wrs: dict[int, WidthRange], vehicle: VehicleProfile,
                            route: dict | None, way_out: dict) -> bool:
    if route is None or not route["strict"] or way_out["mode"] == "none" or not way_out["strict"]:
        return False
    if candidate.kind == "lot":
        return True
    return fit[candidate.way_id] in ("fits", "tight") and wrs[candidate.way_id].lo >= vehicle.door_min


_FLOOD_FAILURE_CODES = frozenset(("flood_arrival", "flood_exit", "flood_stay"))


def _needs_flood_timing(chosen: list[dict], rejected: list[dict]) -> bool:
    """Offer alternate departure times only when flooding leaves no usable stop."""
    if chosen:
        return False
    return any(_FLOOD_FAILURE_CODES.intersection(result.get("failure_codes", ()))
               for result in rejected)


def _flood_timing(intent: str, arrive: datetime, depart: datetime, qualifies,
                  failure_codes: list[str]) -> dict:
    step = timedelta(minutes=FLOOD_TIMING_STEP_MIN)
    horizon = timedelta(hours=FLOOD_TIMING_HORIZON_H)

    if intent == "pickup":
        # Pickup: user controls arrival; return honest reason without sweep
        return {"leave_before_at": None, "or_after_at": None, "approximate": False,
                "reason": "Try another arrival time for pickup.",
                "failure_codes": failure_codes}

    # Park: sweep for earliest safe departure
    before = None
    t = depart - step
    lower = arrive + step
    while t >= lower:
        if qualifies(arrive, t):
            before = t
            break
        t -= step

    after = None
    t = depart + step
    while t <= depart + horizon:
        if qualifies(arrive, t):
            after = t
            break
        t += step

    reason = (None if before or after else
              "No departure time passed every check within 12 hours; flood evidence may be missing or stale.")
    return {"leave_before_at": before.isoformat() if before else None,
            "or_after_at": after.isoformat() if after else None,
            "reason": reason, "approximate": True, "failure_codes": failure_codes}


def _tide_json(t, snapshot: FloodSnapshot):
    tp = snapshot.tide_at(t)
    lvl = tp[0] if tp else None
    return {"level_m": None if lvl is None else round(lvl, 2), "alarm": alarm_label(lvl),
            "kind": tp[1] if tp else None}


def _assessment_json(assessment: FloodAssessment) -> dict:
    out = assessment.to_json()
    out["at"] = assessment.at.isoformat() if assessment.at else None
    out["source"] = assessment.source
    return out


def _aggregate_flood(ctx: PlanContext, way_ids: list[int], times: list[datetime],
                     interval_start: datetime, interval_end: datetime, approximate: bool = True) -> dict:
    ordered = list(dict.fromkeys(wid for wid in way_ids if wid in ctx.g.ways))
    times_key = tuple(sorted(set(times)))
    cache_key = (tuple(ordered), times_key, interval_start, interval_end, approximate)
    if cache_key in ctx.flood_aggregate_cache:
        return ctx.flood_aggregate_cache[cache_key]
    legs = []
    assessments = []
    for wid in ordered:
        assessment = worst_over(ctx.fps.get(wid), list(times_key), ctx.rain,
                                ctx.vehicle.safe_water_depth, ctx.g.display_name(wid), ctx.flood)
        assessments.append(assessment)
        leg = _assessment_json(assessment)
        leg.update({"way_id": wid, "name": ctx.g.display_name(wid)})
        legs.append(leg)
    if not assessments:
        aggregate = FloodAssessment("risky", None, "missing_history",
                                    "No connected route segments available for a flood check", None)
    else:
        decisive = max(assessments, key=lambda item: (
            STATUS_ORDER[item.status], item.depth.hi if item.depth else -1.0))
        unknown = max(assessments, key=lambda item: KNOWLEDGE_ORDER[item.knowledge])
        aggregate = (FloodAssessment(
            decisive.status, decisive.depth, unknown.knowledge,
            "Flood evidence is incomplete for one or more segments or times",
            None, None, None)
            if unknown.knowledge != "known" and unknown is not decisive else decisive)
    out = _assessment_json(aggregate)
    out["legs"] = legs
    out["interval"] = {"start": interval_start.isoformat(), "end": interval_end.isoformat(),
                       "approximate": approximate}
    ctx.flood_aggregate_cache[cache_key] = out
    return out


def _route_flood(ctx: PlanContext, route: dict, times: list[datetime]) -> dict:
    return _aggregate_flood(ctx, route.get("way_ids", []), times, times[0], times[-1])


def _public_route(route: dict) -> dict:
    return {key: value for key, value in route.items()
            if key not in ("strict", "edge_ids", "way_ids", "_segments")}


def _public_way_out_claims(route: dict, wrs: dict[int, WidthRange]) -> list[dict]:
    return [
        claim.to_json()
        for way_id in dict.fromkeys(route.get("way_ids", ()))
        for claim in wrs[way_id].way_out_claims
    ]


def _candidate_legality(c: Candidate, ctx: PlanContext, arrive: datetime,
                        depart: datetime) -> tuple[str, list[StopRule]]:
    # Cache by calendar window while sign rules are day-granular (P.131b/c parity).
    # If hour-scoped sign schedules are added, include their boundaries in this key.
    key = (id(c), arrive.date(), depart.date())
    if key not in ctx.legality_cache:
        if c.kind == "lot":
            legality = legality_for_lot(c.lot, ctx.intent)
        else:
            edge = ctx.g.edges[c.edge_idx]
            junction_distances = []
            for node, center_distance in (
                (edge.u, c.offset), (edge.v, edge.length - c.offset)
            ):
                if ctx.g.drive_degree(node) < 3:
                    continue
                crossing_ways = [
                    way_id for way_id in ctx.g.node_ways.get(node, ())
                    if way_id != c.way_id and ctx.g.ways[way_id].drivable
                ]
                if not crossing_ways or any(
                    not supports_legal_lane_count(ctx.wrs[way_id]) for way_id in crossing_ways
                ):
                    junction_distances.append(None)
                else:
                    boundary_buffer = max(ctx.wrs[way_id].hi for way_id in crossing_ways) / 2
                    junction_distances.append(center_distance - boundary_buffer)
            known_distances = [distance for distance in junction_distances if distance is not None]
            if known_distances and min(known_distances) < 5.0:
                dist_to_junction = min(known_distances)
            elif any(distance is None for distance in junction_distances):
                dist_to_junction = None
            else:
                dist_to_junction = min(known_distances, default=INF)
            legality = legality_over_window(
                ctx.g, ctx.g.ways[c.way_id], ctx.wrs[c.way_id], c.lat, c.lon,
                dist_to_junction, ctx.intent, arrive, depart, ctx.paid.get(c.way_id))
        ctx.legality_cache[key] = legality
    return ctx.legality_cache[key]


def _ways_flood_known_passable(ctx: PlanContext, way_ids: list[int],
                                times: list[datetime]) -> bool:
    ordered = dict.fromkeys(way_id for way_id in way_ids if way_id in ctx.g.ways)
    if not ordered:
        return False
    for way_id in ordered:
        assessment = worst_over(
            ctx.fps.get(way_id), times, ctx.rain, ctx.vehicle.safe_water_depth,
            ctx.g.display_name(way_id), ctx.flood)
        if assessment.status != "passable" or assessment.knowledge != "known":
            return False
    return True


def _candidate_timing_qualified(c: Candidate, ctx: PlanContext, arrive: datetime,
                                depart: datetime, stay_times: list[datetime],
                                arr, ext, arr_times, exit_times) -> bool:
    route = _route_in(c, ctx.g, arr)
    way_out = _way_out(c, ctx.g, ctx.wrs, ctx.fit, ctx.vehicle, ext, route)
    if not _timing_static_eligible(c, ctx.fit, ctx.wrs, ctx.vehicle, route, way_out):
        return False
    legality_status, _ = _candidate_legality(c, ctx, arrive, depart)
    if legality_status != "Permitted":
        return False
    stop_way_ids = ([c.way_id] if c.kind != "lot" else c.data.get("access_way_ids", []))
    return (
        _ways_flood_known_passable(ctx, route.get("way_ids", []), arr_times)
        and _ways_flood_known_passable(ctx, way_out.get("way_ids", []), exit_times)
        and _ways_flood_known_passable(ctx, stop_way_ids, stay_times)
    )


CONFIDENCE_VI = {"high": "high", "medium": "medium", "low": "low"}


def _width_hypothesis(wr):
    """Keep the point's actual source separate from whole-way verification.

    A failed Official survey is missing evidence, not a zero-width observation.
    Its fused interval may have a finite, weaker cap; taking that interval's
    midpoint invents a narrow Official measurement (D50).
    """
    if wr.review or wr.top_tier is None:
        return None
    from .evidence import TIERS
    unresolved = any(b.measurement_schema == 'parcel-survey-unresolved-v2' for b in wr.evidence)
    active = [b for b in wr.evidence if (b not in wr.overruled or (unresolved and
              b.tier == 'Inferred' and b.source in ('OSM road class', 'OSM lane count'))) and
              b.measurement_schema != 'parcel-survey-unresolved-v2']
    for tier in TIERS[TIERS.index(wr.top_tier):]:
        bounds = [b for b in active if b.tier == tier and (b.estimate_m is not None or b.lo > 0)]
        if not bounds:
            continue
        samples = [b for b in bounds if b.estimate_m is not None]
        if samples:
            b = min(samples, key=lambda b: b.estimate_m)
            value = b.estimate_m  # never relabel a weaker cap as this sample
        else:
            lo, hi = max(b.lo for b in bounds), min(b.hi for b in bounds)
            if lo > hi:
                return None
            b = min(bounds, key=lambda b: b.hi)
            value = (lo + min(hi, lo+3)) / 2
        return {'value_m': value, 'tier': tier, 'source': english_text(b.source), 'width_basis': b.width_basis,
                'observed_on': b.observed_on, 'source_url': b.url,
                'sampled': bool(samples), 'sample_count': b.sample_count,
                'sampled_range': wr.sampled_estimate() if samples else None,
                'bottleneck_support': b.sample_quality.get('bottleneck_support'),
                'isolated_low_outlier': b.sample_quality.get('isolated_low_outlier', False),
                'fallback_from_unresolved': tier != wr.top_tier or unresolved}
    # Diagnostic callers can supply an interval without individual bounds.
    if not wr.evidence and wr.lo > 0:
        return {'value_m': (wr.lo+min(wr.hi,wr.lo+3))/2, 'tier': wr.top_tier,
                'source': 'Width interval', 'width_basis': wr.width_basis, 'sampled': False, 'sample_count': None,
                'bottleneck_support': None, 'isolated_low_outlier': False,
                'fallback_from_unresolved': False}
    return None


def _width_estimate(wr):
    hypothesis = _width_hypothesis(wr)
    return hypothesis['value_m'] if hypothesis else None


def _estimate(c, g, wrs, p, checks, failures):
    """D50: useful hypothesis + ordinal evidence confidence; hard checks are unchanged."""
    route, wo = checks['route_in'], checks['way_out']
    segments = {}
    for ei, length in (route or {}).get('_segments', []) + wo.get('_segments', []):
        segments[ei] = max(segments.get(ei, 0), length)
    if c.way_id is not None and c.edge_idx is not None:
        segments[c.edge_idx] = max(segments.get(c.edge_idx, 0), .01)
    total = sum(segments.values())
    widths = [wrs[g.edges[ei].way_id] for ei in segments]
    hypotheses = [_width_hypothesis(wr) for wr in widths]
    values = [h['value_m'] if h else None for h in hypotheses]
    strong_m = quantitative_m = 0.0
    measured = all_sampled = 0
    all_sample_m = 0.0
    for (ei, length), wr in zip(segments.items(), widths):
        numeric = [b for b in wr.evidence if b.tier in ('Measured', 'Official', 'Observed')
                   and b not in wr.overruled and (b.estimate_m is not None or (b.hi < 40 and b.hi > 0 and
                        b.measurement_schema != 'parcel-survey-unresolved-v2'))]
        if numeric:
            measured += 1
            quantitative_m += length
        if numeric or any(b.estimate_m is not None and b.sample_count and b not in wr.overruled
                          for b in wr.evidence):
            all_sampled += 1
            all_sample_m += length
        if wr.top_tier in ('Measured', 'Official') and wr.lo > 0 and not wr.review and (
                not wr.evidence or any(b.tier == wr.top_tier and b.coverage_complete for b in wr.evidence)):
            strong_m += length
    coverage = {'sampled_segments': measured, 'total_segments': len(segments),
                'sample_supported_fraction': round(quantitative_m / total, 3) if total else 0,
                'complete_strong_fraction': round(strong_m / total, 3) if total else 0,
                'all_sampled_segments': all_sampled,
                'all_sample_supported_fraction': round(all_sample_m / total, 3) if total else 0,
                'scope': 'Arrival/exit segments with width samples; isolated samples do not establish continuous clearance'}
    # Passage uses tight_min; opening the door uses the separate stop threshold.
    stop_hypothesis = _width_hypothesis(wrs[c.way_id]) if c.way_id is not None else None
    stop_value = stop_hypothesis['value_m'] if stop_hypothesis else None
    if not widths or any(v is None for v in values):
        answer = 'unknown'
    elif min(values) >= p.fits_min and (stop_value is None or stop_value >= p.door_min):
        answer = 'fits'
    else:
        # A point below a threshold is a low-confidence negative, not a hard exclusion.
        answer = 'tight' if min(values) >= p.tight_min and (stop_value is None or stop_value >= p.door_min) else 'no'
    width_answer = answer
    if failures:
        answer = 'no'
    confidence = 'low'
    legal = checks['legality']
    flood = checks['flood']['stay']['status']
    if total and quantitative_m / total >= .5 and not any(w.review for w in widths):
        confidence = 'medium'
    threshold_clear = all(wr.lo >= p.fits_min for wr in widths) and (
        c.way_id is None or wrs[c.way_id].lo >= p.door_min)
    if (total and strong_m / total >= 1 - 1e-9 and threshold_clear and route and route.get('strict')
            and wo.get('strict') and flood == 'passable' and legal['status'] == 'Permitted'
            and not c.data.get('walk_path', {}).get('unverified', True)):
        confidence = 'high'
    if (answer == 'unknown' or wo['mode'] in ('unknown', 'none') or any(w.review for w in widths)
            or any(h and h['fallback_from_unresolved'] for h in hypotheses)):
        confidence = 'low'
    hard_legal = legal['status'] in ('Prohibited', 'Restricted')
    hard_width = any(not wr.review and any(
        b.tier in ('Measured', 'Official') and b.tier == wr.top_tier and b not in wr.overruled and
        ((b.feature != 'parcel_widths' and b.measurement_schema != 'legacy-raw-gap-converted-v2') or
         b.sample_quality.get('bottleneck_support', 0) >= 2) and
        b.hi < (p.door_min if g.edges[ei].way_id == c.way_id else p.tight_min)
        for b in wr.evidence) for ei, wr in zip(segments, widths))
    if hard_legal or hard_width or flood == 'blocked':
        answer, confidence = 'no', 'high'
    elif not route or failures:
        confidence = 'low'
        if width_answer in ("fits", "tight", "unknown") and (not route or wo['mode'] == 'none') and checks.get('fit', {}).get('class') not in ('no', 'blocked'):
            # A missing directed path in this cached graph does not measure a
            # narrow street. Keep the failed Hard Check, but say what is unknown.
            answer = 'unknown'
    # Every automatic cut that determines a negative needs corroboration, not
    # just the numerically smallest path value. In particular, a stop's door
    # threshold can fail while a different segment is the path bottleneck.
    if answer == 'no' and not (hard_legal or hard_width or flood == 'blocked'):
        limiting_hypotheses = [(h, p.tight_min) for h in hypotheses]
        limiting_hypotheses.append((stop_hypothesis, p.door_min))
        if any(h and h['value_m'] < need and (h['fallback_from_unresolved'] or
               h['isolated_low_outlier'] or (h['sample_count'] is not None and
               (h['bottleneck_support'] or 0) < 2)) for h, need in limiting_hypotheses):
            confidence = 'low'
    if c.kind == 'lot' and not failures:
        answer = 'unknown'  # no measured entrance / internal manoeuvre envelope
    tier_names = {'Measured':'measured', 'Official':'cadastral / official', 'Observed':'observed',
                  'Declared':'declared', 'Inferred':'inferred'}
    finite = [(v, wr, ei, h) for v, wr, ei, h in zip(values, widths, segments, hypotheses) if v is not None]
    limiting_json = None
    if finite:
        limiting_point = min(finite, key=lambda x: x[0])
        if stop_value is not None and stop_value < p.door_min and all(
                v is not None and v >= p.tight_min for v in values):
            # A stop's door threshold can decide a negative even when another
            # traversed segment has the numerically smallest width.
            limiting_point = next((item for item in finite if
                g.edges[item[2]].way_id == c.way_id), limiting_point)
        value, limiting, ei, hypothesis = limiting_point
        way = g.ways[g.edges[ei].way_id]
        limiting_json = {**hypothesis, 'way_id': way.id, 'way_name': way.name or english_text(g.display_name(way.id)),
                         'osm_url': f'https://www.openstreetmap.org/way/{way.id}'}
        basis = [f"{tier_names.get(hypothesis['tier'], 'source unknown')} ≈{value:.2f} m"
                 + f" ({way.name or english_text(g.display_name(way.id))}; OSM {way.id})"]
        if hypothesis['fallback_from_unresolved']:
            basis.append('survey has no valid samples; estimate uses a weaker source')
        if (answer == 'no' and not (hard_legal or hard_width or flood == 'blocked') and
                (hypothesis['fallback_from_unresolved'] or hypothesis['isolated_low_outlier'] or
                 (hypothesis['sample_count'] is not None and (hypothesis['bottleneck_support'] or 0) < 2))):
            confidence = 'low'
            basis.append('bottleneck lacks two consistent independent cuts')
        if stop_hypothesis and way.id != c.way_id:
            basis.append(f"at the door ≈{stop_value:.2f} m ({g.ways[c.way_id].name or english_text(g.display_name(c.way_id))})")
    else:
        basis = ['insufficient width evidence for an estimate']
    basis.append(f"{all_sampled}/{len(segments)} segments sampled ({coverage['all_sample_supported_fraction']:.0%} of route length with samples)")
    if strong_m < total:
        basis.append('incomplete route survey')
    if wo['mode'] == 'unknown' or wo.get('manoeuvre_status') == 'unknown':
        basis.append('exit / manoeuvres unverified')
    if flood in ('unknown', 'risky'):
        basis.append('flood conditions unknown' if flood == 'unknown' else 'possible flooding')
    if legal['status'] == 'Unverified':
        basis.append('stopping permission unverified')
    if hard_legal:
        basis.extend(english_text(r['text']) + ' (' + r['citation'] + ')' for r in legal['rules']
                     if r['status'] in ('Prohibited', 'Restricted'))
    elif failures:
        basis.append(english_text(failures[0]))
    decided_by = ('legal' if hard_legal else 'flood' if flood == 'blocked' or
                  any('flood' in str(f).lower() for f in failures) else
                  'width' if width_answer in ('no', 'unknown') or hard_width else
                  'way_out' if wo.get('mode') in ('none', 'unknown') else
                  'walk' if c.data.get('walk_path', {}).get('unverified', False) else 'width')
    return {'decided_by': decided_by, 'answer': answer, 'confidence': confidence, 'basis': ' · '.join(basis), 'coverage': coverage,
            'limiting_width': limiting_json, 'stop_width': stop_hypothesis}



def _evaluate(c: Candidate, ctx: PlanContext, arrive, depart, stay_times,
              arr, ext, fit_arr, fit_ext, arr_times, exit_times) -> dict:
    g, wrs, fit, fit_notes = ctx.g, ctx.wrs, ctx.fit, ctx.fit_notes
    p, intent = ctx.vehicle, ctx.intent
    checks, reasons_fail, unverified, failure_codes = {}, [], [], []
    tier_bump = 0
    way_id = c.way_id if c.kind != "lot" else None

    route = _best_route(c, ctx, arr, arr_times)
    fit_route = _best_route(c, ctx, fit_arr)
    if route is None:
        if fit_route is not None:
            failure_codes.append("flood_arrival")
            reasons_fail.append("Arrival route is flooded during entry")
            fit_route["flood"] = _route_flood(ctx, fit_route, arr_times)
            route_output = {"available": False, **_public_route(fit_route)}
        else:
            failure_codes.append("no_fit")
            reasons_fail.append("No arrival route fits the vehicle dimensions")
            route_output = {"available": False, "meters": None, "geometry": [], "flood": None}
    else:
        route["flood"] = _route_flood(ctx, route, arr_times)
        route_output = {"available": True, **_public_route(route)}
        if not route["strict"]:
            unverified.append("Arrival route includes unverified width or flood conditions")
    checks["route_in"] = route_output

    if way_id is not None:
        wr = wrs[way_id]
        fit_class_at_stop = fit[way_id]
        fitj = {"class": fit_class_at_stop, "width_range": wr.to_json(), "note": fit_notes.get(way_id),
                "needed": {"fits_min": round(p.fits_min, 2), "tight_min": round(p.tight_min, 2),
                           "door_min": round(p.door_min, 2)}}
        if fit_class_at_stop in ("no", "blocked"):
            failure_codes.append("no_fit")
            reasons_fail.append(fit_notes.get(way_id) or
                                f"{wr.label} {wr.lo:.1f}–{min(wr.hi, 40):.1f} m; vehicle needs ≥ {p.tight_min:.2f} m")
        elif fit_class_at_stop == "unknown":
            unverified.append(f"Width unverified ({wr.lo:.1f}–{min(wr.hi, 40):.1f} m; "
                              f"vehicle needs ≥ {p.tight_min:.2f} m)")
        if wr.hi < p.door_min:
            failure_codes.append("no_fit")
            reasons_fail.append(f"Insufficient door-opening space (needs {p.door_min:.2f} m)")
        elif wr.lo < p.door_min and fit_class_at_stop != "no":
            unverified.append(f"Door-opening space unverified (needs {p.door_min:.2f} m)")
        checks["fit"] = fitj
    else:
        checks["fit"] = {"class": "lot", "note": "Off-street parking"}

    way_out = _best_way_out(c, ctx, ext, route, exit_times)
    fit_way_out = _best_way_out(c, ctx, fit_ext, fit_route)
    if route is not None:
        # Only evaluate exit if entry succeeded; otherwise skip exit checks (route is None)
        if way_out["mode"] == "none":
            if fit_way_out["mode"] != "none":
                failure_codes.append("flood_exit")
                reasons_fail.append("Exit route is flooded during departure")
                fit_way_out["flood"] = _route_flood(ctx, fit_way_out, exit_times)
                way_out_output = {"available": False, **_public_route(fit_way_out),
                                  "route_verified": fit_way_out["strict"],
                                  "observed": _public_way_out_claims(fit_way_out, wrs)}
            else:
                failure_codes.append("dead_end")
                reasons_fail.append("No suitable exit (dead end or excessive reversing)")
                way_out_output = {"available": False, **_public_route(way_out), "flood": None,
                                  "route_verified": False, "observed": _public_way_out_claims(way_out, wrs)}
        else:
            way_out["flood"] = _route_flood(ctx, way_out, exit_times)
            way_out_output = {"available": True, **_public_route(way_out),
                              "route_verified": way_out["strict"],
                              "observed": _public_way_out_claims(way_out, wrs)}
            if not way_out["strict"]:
                unverified.append(way_out.get("text") or "Exit unverified")
            if way_out.get("tight_exit"):
                tier_bump = 1
    else:
        # Entry failed; don't evaluate exit
        way_out_output = {"available": False, "mode": "none", "text": way_out["text"], "meters": None,
                          "geometry": [], "flood": None, "route_verified": False, "observed": []}
    checks["way_out"] = way_out_output

    stop_way_ids = ([way_id] if way_id is not None else c.data.get("access_way_ids", []))
    stay = _aggregate_flood(ctx, stop_way_ids, stay_times, arrive, depart, approximate=False)
    if stay["status"] == "blocked":
        failure_codes.append("flood_stay")
        depth = stay["depth"]
        detail = (f"{depth['lo'] * 100:.0f}–{depth['hi'] * 100:.0f} cm"
                  if depth else "depth unknown")
        reasons_fail.append(f"Water at the stop: {detail}, exceeding the vehicle safe depth of "
                            f"{p.safe_water_depth * 100:.0f} cm")
    elif stay["status"] == "risky":
        depth = stay["depth"]
        unverified.append((f"Possible flooding {depth['lo'] * 100:.0f}–{depth['hi'] * 100:.0f} cm"
                           if depth else stay["reason"] or "Flood evidence incomplete"))
    flood = {"stay": stay}
    checks["flood"] = flood

    legality_status, rules = _candidate_legality(c, ctx, arrive, depart)
    checks["legality"] = {"status": legality_status, "rules": [english_payload(rule.to_json()) for rule in rules]}
    if legality_status == "Prohibited" or (intent == "park" and legality_status == "Restricted"):
        failure_codes.append("legality")
        reasons_fail.append("; ".join(english_text(rule.text) for rule in rules
                                      if rule.status in ("Prohibited", "Restricted")))
    elif legality_status == "Unverified":
        unverified.append("Stopping permission unverified: " +
                          "; ".join(english_text(rule.text) for rule in rules if rule.status == "Unverified"))

    stop_walk_connector = c.data.get("walk_connector_m", 0.0)
    destination_walk_connector = c.data.get("walk_destination_connector_m", 0.0)
    walk_connection_unverified = stop_walk_connector > WALK_SNAP_M or destination_walk_connector > WALK_SNAP_M
    if walk_connection_unverified:
        unverified.append("The nearest connector has no mapped OSM footpath; only the mapped walking portion is drawn")
    tier = 2 if (legality_status == "Restricted" or unverified) else tier_bump
    ok = not reasons_fail
    walk_min = c.walk_m / WALK_SPEED / 60
    walk_connection = {
        "stop_to_walk_m": round(stop_walk_connector, 1),
        "destination_to_walk_m": round(destination_walk_connector, 1),
        "mapped": not walk_connection_unverified,
        "reason": None if not walk_connection_unverified else
        "Connector distance is estimated; unmapped walking portions are not drawn",
    }
    # Public serialization deliberately removes edge IDs. Estimate from the
    # original selected routes, retaining partial-edge lengths and strictness.
    # A rejected door still has a diagnostic route: do not compare only its
    # stop-edge placeholder against another vehicle's complete feasible path.
    estimate_route = route or (ctx.shared.route(c) if ctx.shared else None)
    estimate_exit = way_out
    if route is None and ctx.shared and estimate_route:
        estimate_exit = ctx.shared.exit(c, estimate_route)
    estimate_checks = {**checks, "route_in": estimate_route, "way_out": estimate_exit}
    estimate = _estimate(c, g, wrs, p, estimate_checks, reasons_fail)
    # Confidence can never imply verification beyond the canonical hard checks.
    if not (ok and tier <= 1) and estimate["confidence"] == "high" and estimate["answer"] != "no":
        estimate["confidence"] = "medium"
    return {
        "estimate": estimate, "profile": _segment_profile(g, wrs, estimate_route),
        "decided_by": estimate["decided_by"],
        "ok": ok, "kind": c.kind, "name": c.name, "lat": c.lat, "lon": c.lon, "way_id": way_id,
        "tier": tier, "verified": ok and tier <= 1,
        "badges": _badges(checks, tier, legality_status),
        "walk": {"meters": round(c.walk_m), "minutes": max(1, round(walk_min)) if c.walk_m > 20 else 0,
                 "connection": walk_connection},
        "route_in": route_output, "fit": checks["fit"], "way_out": way_out_output,
        "flood": flood, "legality": checks["legality"], "failure_codes": list(dict.fromkeys(failure_codes)),
        "fail_reasons": reasons_fail, "unverified_reasons": unverified, "lot": c.lot, "_c": c,
    }


def _pred_edge_ids(pred, node: int) -> list[int]:
    edges = []
    while node in pred:
        edge_idx, node = pred[node]
        edges.append(edge_idx)
    return edges


def _route_in(c: Candidate, g: AreaGraph, arr) -> dict | None:
    for strict in (True, False):
        dist, pred = arr[strict]
        if c.kind == "lot":
            node = c.entrance
            if node in dist:
                nodes = _path_nodes(pred, node)[::-1]
                edge_ids = _pred_edge_ids(pred, node)[::-1]
                segments = [(idx, g.edges[idx].length) for idx in edge_ids]
                access_ways = list(c.data.get("access_way_ids", []))
                way_ids = [g.edges[idx].way_id for idx in edge_ids] + access_ways
                return {"strict": False, "meters": round(sum(length for _, length in segments) + c.data.get("entrance_d", 0)),
                        "_segments": segments,
                        "geometry": _coords(g, nodes), "flood": None,
                        "edge_ids": edge_ids, "way_ids": way_ids}
            continue
        edge = g.edges[c.edge_idx]
        way = g.ways[edge.way_id]
        opts = []
        if edge.u in dist and way.oneway >= 0:
            opts.append((dist[edge.u] + c.offset, edge.u, "u"))
        if edge.v in dist and way.oneway <= 0:
            opts.append((dist[edge.v] + edge.length - c.offset, edge.v, "v"))
        if opts:
            dmin, node, side = min(opts)
            nodes = _path_nodes(pred, node)[::-1]
            edge_ids = _pred_edge_ids(pred, node)[::-1] + [edge.idx]
            partial = c.offset if side == 'u' else edge.length-c.offset
            segments = [(idx, g.edges[idx].length) for idx in edge_ids[:-1]] + [(edge.idx, partial)]
            way_ids = [g.edges[idx].way_id for idx in edge_ids]
            return {"strict": strict, "meters": round(sum(length for _, length in segments)), "side": side,
                    "_segments": segments,
                    "geometry": _coords(g, nodes) + [[c.lon, c.lat]], "flood": None,
                    "edge_ids": edge_ids, "way_ids": way_ids}
    return None


def _way_out(c: Candidate, g: AreaGraph, wrs, fit, p: VehicleProfile, ext, route) -> dict:
    if route is None:
        return {"mode": "none", "text": "No arrival route; exit cannot be assessed", "strict": False,
                "turn_verified": False, "edge_ids": [], "way_ids": []}
    for strict in (True, False):
        dist, pred = ext[strict]
        if c.kind == "lot":
            node = c.entrance
            if node in dist:
                edge_ids = _pred_edge_ids(pred, node)
                access_ways = list(c.data.get("access_way_ids", []))
                way_ids = access_ways + [g.edges[idx].way_id for idx in edge_ids]
                return {"mode": "lot", "strict": False, "turn_verified": False, "reverse_m": 0,
                        "tight_exit": False,
                        "text": "Parking-lot entrance, manoeuvre space and exit geometry are unverified",
                        "geometry": _coords(g, _path_nodes(pred, node)),
                        "_segments": [(idx, g.edges[idx].length) for idx in edge_ids],
                        "edge_ids": edge_ids, "way_ids": way_ids}
            continue
        edge = g.edges[c.edge_idx]
        way = g.ways[edge.way_id]
        a, b = (edge.u, edge.v) if route.get("side") == "u" else (edge.v, edge.u)
        s_a = c.offset if route.get("side") == "u" else edge.length - c.offset
        forward_ok = (way.oneway == 0) or (way.oneway == 1 and a == edge.u) or (way.oneway == -1 and a == edge.v)
        if forward_ok and b in dist and pred.get(b, (None,))[0] != edge.idx:
            edge_ids = [edge.idx] + _pred_edge_ids(pred, b)
            return {"mode": "through", "strict": strict,
                    "reverse_m": 0, "tight_exit": False,
                    "text": "Continue to the main road in the permitted direction",
                    "geometry": [[c.lon, c.lat]] + _coords(g, _path_nodes(pred, b)),
                    "_segments": [(edge.idx, edge.length-s_a)] + [(idx, g.edges[idx].length) for idx in edge_ids[1:]],
                    "edge_ids": edge_ids, "way_ids": [g.edges[idx].way_id for idx in edge_ids]}
        if (way.oneway == 0 and wrs[way.id].decisive_clearance
                and wrs[way.id].lo >= three_point_width(p.id) and a in dist):
            edge_ids = [edge.idx] + _pred_edge_ids(pred, a)
            return {"mode": "turn_here", "strict": False, "turn_verified": False,
                    "reverse_m": 0, "tight_exit": False,
                    "text": "Width suggests a possible turnaround; swept manoeuvre space is unverified",
                    "geometry": [[c.lon, c.lat]] + _coords(g, _path_nodes(pred, a)),
                    "_segments": [(edge.idx, s_a)] + [(idx, g.edges[idx].length) for idx in edge_ids[1:]],
                    "edge_ids": edge_ids, "way_ids": [g.edges[idx].way_id for idx in edge_ids]}
        if way.oneway != 0 or a not in dist:
            continue
        path = _path_nodes(pred, a)
        reverse_m = s_a
        turn_at = None
        reversible = True
        for index, node in enumerate(path):
            usable = [
                (edge_idx, neighbor) for edge_idx, neighbor in g.drive_adj.get(node, ())
                if fit.get(g.edges[edge_idx].way_id) in ("fits", "tight")
            ]
            neighbors = {neighbor for _, neighbor in usable}
            has_main = any(g.ways[g.edges[edge_idx].way_id].kind == "main"
                           for edge_idx, _ in usable)
            if len(neighbors) >= 3 or (has_main and len(neighbors) >= 2 and index > 0):
                turn_at = index
                break
            if index + 1 < len(path):
                reverse_edge = g.edges[pred[node][0]]
                if g.ways[reverse_edge.way_id].oneway != 0:
                    reversible = False
                    break
                reverse_m += reverse_edge.length
        if turn_at is None and reversible:
            turn_at = len(path) - 1  # path ends at a main-network source node
        if not reversible or turn_at is None or reverse_m > 2 * REVERSE_LIMIT_M:
            continue
        tight = reverse_m > REVERSE_LIMIT_M
        text = (f"Reverse {reverse_m:.0f} m to a junction; turning space is unverified"
                if not tight else
                f"Must reverse {reverse_m:.0f} m (over the {REVERSE_LIMIT_M:.0f} m reverse limit); turning space is unverified")
        edge_ids = [edge.idx] + _pred_edge_ids(pred, a)
        return {"mode": "reverse", "strict": False, "turn_verified": False,
                "reverse_m": round(reverse_m), "tight_exit": tight,
                "text": text, "geometry": [[c.lon, c.lat]] + _coords(g, path),
                "_segments": [(edge.idx, s_a)] + [(idx, g.edges[idx].length) for idx in edge_ids[1:]],
                "edge_ids": edge_ids, "way_ids": [g.edges[idx].way_id for idx in edge_ids]}
    return {"mode": "none", "strict": False, "turn_verified": False,
            "text": "No suitable exit (dead end or excessive reversing)",
            "edge_ids": [], "way_ids": []}


def _badges(checks, tier, lstatus) -> list[str]:
    out = []
    fc = checks["fit"]["class"]
    out.append({"fits": "Fits", "tight": "Tight", "unknown": "Width unknown", "lot": "Parking lot"}.get(fc, fc))
    wo = checks["way_out"]
    way_out_label = {
        "through": "Through exit",
        "turn_here": "Turnaround unverified",
        "lot": "Parking-lot exit unverified",
    }.get(wo["mode"])
    if way_out_label is None:
        way_out_label = (f"Reverse {wo.get('reverse_m', 0)} m; turnaround unverified"
                         if wo["mode"] == "reverse" else "No exit")
    if wo["mode"] == "through" and not wo.get("route_verified", False):
        way_out_label = "Exit unverified"
    out.append(way_out_label)
    out.append({"passable": "No flooding predicted", "risky": "Possible flooding", "blocked": "Flooded"}[checks["flood"]["stay"]["status"]])
    if lstatus == "Unverified":
        codes = {rule["code"] for rule in checks["legality"]["rules"] if rule["status"] == "Unverified"}
        labels = (
            ("lane-unknown", "Lane count unknown"),
            ("junction-5m", "Junction boundary unknown"),
            ("no-rule", "Signs unverified"),
            ("main-road-signs", "Signs unverified"),
        )
        out.append(next((label for code, label in labels if code in codes), "Stopping permission unverified"))
    else:
        out.append({"Permitted": "Permitted", "Restricted": "Restricted by law", "Prohibited": "Prohibited"}[lstatus])
    return out


def _walk_start(edge, offset, wdist, dest_edge, dest_offset, dest_connector=0.0):
    """Distance and first graph node, or None for a direct path on one edge."""
    distance, node = min((wdist.get(edge.u, INF) + offset, edge.u),
                         (wdist.get(edge.v, INF) + edge.length - offset, edge.v))
    if dest_edge is not None and edge.idx == dest_edge.idx:
        direct = abs(offset - dest_offset) + dest_connector
        if direct <= distance:
            return direct, None
    return distance, node


def _walk_geometry(g, c: Candidate, wpred, wdist, dest_edge, dest_offset, dlat, dlon):
    if dest_edge is None or "walk_edge_idx" not in c.data:
        return []
    start_edge = g.edges[c.data["walk_edge_idx"]]
    start_offset = c.data["walk_offset"]
    distance, node = _walk_start(start_edge, start_offset, wdist, dest_edge, dest_offset,
                                 c.data.get("walk_destination_connector_m", 0.0))
    if not math.isfinite(distance):
        return []
    path_nodes = _path_nodes(wpred, node) if node is not None else []
    start_point = _interp(g, start_edge.u, start_edge.v, start_offset, start_edge.length)
    end_point = _interp(g, dest_edge.u, dest_edge.v, dest_offset, dest_edge.length)
    coords = [[start_point[1], start_point[0]]]
    coords.extend(_coords(g, path_nodes))
    coords.append([end_point[1], end_point[0]])
    if c.data.get("walk_connector_m", 0) <= WALK_SNAP_M:
        coords[0] = [c.lon, c.lat]
    if c.data.get("walk_destination_connector_m", 0) <= WALK_SNAP_M:
        coords[-1] = [dlon, dlat]
    return [point for index, point in enumerate(coords) if index == 0 or point != coords[index - 1]]


def _walk_wade(g: AreaGraph, fps, c: Candidate, wpred, wdist, arrive: datetime, rain: list[dict],
               snapshot: FloodSnapshot, safe_depth: float, dest_edge=None, dest_offset=0.0):
    worst = None
    if c.kind == "door" or "walk_edge_idx" not in c.data:
        return None
    edge = g.edges[c.data["walk_edge_idx"]]
    offset = c.data["walk_offset"]
    distance, node = _walk_start(edge, offset, wdist, dest_edge, dest_offset,
                                 c.data.get("walk_destination_connector_m", 0.0))
    if not math.isfinite(distance):
        return None
    # Include the partial edges at both ends; they need not occur in wpred.
    way_ids = {edge.way_id}
    if dest_edge is not None:
        way_ids.add(dest_edge.way_id)
    while node in wpred:
        edge_idx, node = wpred[node]
        way_ids.add(g.edges[edge_idx].way_id)
    for way_id in sorted(way_ids):
        assessment = snapshot.assess(fps.get(way_id), arrive, safe_depth, g.display_name(way_id))
        depth = assessment.depth
        if depth and depth.hi > WALK_WADE_M and (worst is None or depth.hi > worst["hi"]):
            worst = {"lo": round(depth.lo, 2), "hi": round(depth.hi, 2), "street": g.display_name(way_id),
                     "label": "Walk through floodwater"}
    return worst


def _verdict(chosen, door_eval, intent, cap) -> dict:
    if not chosen:
        return {"code": "none", "headline": f"No suitable stop within {cap:.0f} m walk — low confidence",
                "detail": "Try a different arrival time, stay duration or smaller vehicle."}
    best = chosen[0]
    estimate = best.get('estimate') or {'answer': 'unknown', 'confidence': 'low'}
    confidence = estimate['confidence']
    code = ('door' if best['kind'] == 'door' else 'nearby') if best['verified'] else 'unverified'
    if best['legality']['status'] == 'Restricted':
        return {'code': code, 'headline': f"Stopping prohibited at {best['name']} — {confidence} confidence",
                'detail': ' · '.join(english_text(r['text'])+' ('+r['citation']+')'
                                   for r in best['legality']['rules'] if r['status'] == 'Restricted')}
    if best['kind'] == 'door':
        action = {'fits': 'Can reach the door', 'tight': 'Tight access to the door',
                  'no': 'Door access unlikely', 'unknown': 'Door access unverified'}[estimate['answer']]
    else:
        verb = 'Park' if intent == 'park' else 'Stop for pickup/drop-off'
        action = f"{verb} {'at' if best['kind'] == 'lot' else 'on'} {best['name']}, {best['walk']['meters']} m walk"
        if estimate['answer'] == 'no':
            action = f"Access to {best['name']} may not fit the vehicle, {best['walk']['meters']} m walk"
    detail = english_text(best['way_out']['text'])
    if best.get('unverified_reasons'):
        detail += ' · ' + ' · '.join(english_text(r) for r in best['unverified_reasons'])
    return {'code': code, 'headline': f'{action} — {confidence} confidence', 'detail': detail}


def _decode_polyline(s: str) -> list[list[float]]:
    coords, idx, lat, lon = [], 0, 0, 0
    while idx < len(s):
        for which in (0, 1):
            shift = result = 0
            while True:
                b = ord(s[idx]) - 63
                idx += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            d = ~(result >> 1) if result & 1 else result >> 1
            if which == 0:
                lat += d
            else:
                lon += d
        coords.append([lon / 1e5, lat / 1e5])
    return coords


def goong_drive(origin, dest) -> dict | None:
    if CACHED_ONLY:
        return None
    """Goong Direction v2 car route: geometry [[lon, lat]…], distance (m) and duration (s)."""
    try:
        from .geocoding import goong_direction
        r = goong_direction({"origin": f"{origin[0]},{origin[1]}",
                             "destination": f"{dest[0]},{dest[1]}", "vehicle": "car"})
        leg = r["routes"][0]["legs"][0]
        coords = []
        for step in leg["steps"]:
            coords += _decode_polyline(step["polyline"]["points"])
        return {"geometry": coords, "distance_m": leg["distance"]["value"], "duration_s": leg["duration"]["value"]}
    except Exception:
        return None


def _add_trips(chosen: list[dict], origin) -> None:
    """Whole trip per Stop Point: Goong drives from the origin to where our last stretch starts."""
    from concurrent.futures import ThreadPoolExecutor

    def leg_for(sp):
        g_in = (sp.get("route_in") or {}).get("geometry") or []
        handoff = (g_in[0][1], g_in[0][0]) if g_in else (sp["lat"], sp["lon"])
        return goong_drive(origin, handoff)

    with ThreadPoolExecutor(3) as pool:
        legs = list(pool.map(leg_for, chosen))
    for sp, leg in zip(chosen, legs):
        if not leg:
            continue
        last = (sp.get("route_in") or {}).get("meters") or 0
        drive_s = leg["duration_s"] + last / ALLEY_SPEED_MPS
        sp["approach"] = {"geometry": leg["geometry"], "source": "Goong Direction v2 (car)"}
        sp["trip"] = {"drive_m": round(leg["distance_m"] + last), "drive_min": max(1, round(drive_s / 60)),
                      "walk_m": sp["walk"]["meters"], "walk_min": sp["walk"]["minutes"],
                      "total_min": max(1, round(drive_s / 60)) + sp["walk"]["minutes"]}


def goong_standard_route(g, origin, dest, fit, wrs, key: str) -> dict | None:
    """Goong's own car route, with the alleys it uses that don't (or may not) fit this vehicle."""
    leg = goong_drive(origin, dest)
    if not leg:
        return None
    coords = leg["geometry"]
    # Snap the route's points near the destination to ways; a way counts only if the route runs along it
    # (2+ points), not if it merely passes the mouth of a side alley at a junction.
    hits: dict[int, int] = {}
    order: list[int] = []
    for lon, lat in _densify(coords, 10.0):
        if haversine(lat, lon, dest[0], dest[1]) > 800:
            continue
        best, bd = None, 6.0
        for wid in _ways_near(g, lat, lon):
            w = g.ways[wid]
            d = min(haversine(lat, lon, *g.nodes[n]) for n in w.nodes)
            if d < bd:
                best, bd = wid, d
        if best:
            hits[best] = hits.get(best, 0) + 1
            if best not in order:
                order.append(best)
    bad = []
    for wid in order:
        if hits[wid] >= 2 and fit.get(wid) in ("no", "blocked", "unknown") and g.ways[wid].kind != "main":
            wr = wrs[wid]
            bad.append({"way_id": wid, "name": g.display_name(wid), "label": wr.label, "fit": fit[wid],
                        "lo": round(wr.lo, 2), "hi": None if wr.hi >= 40 else round(wr.hi, 2)})
    return {"geometry": coords, "unfit_ways": bad, "source": "goong",
            "distance_m": leg["distance_m"], "duration_s": leg["duration_s"],
            "note": "Goong car route: alley widths and flooding are not considered"}


def _densify(coords: list[list[float]], step_m: float) -> list[list[float]]:
    """Extra points every ~step_m along the polyline, so long straight segments are sampled too."""
    out = []
    for (lo1, la1), (lo2, la2) in zip(coords, coords[1:]):
        n = max(1, int(haversine(la1, lo1, la2, lo2) // step_m))
        out += [[lo1 + (lo2 - lo1) * i / n, la1 + (la2 - la1) * i / n] for i in range(n)]
    return out + coords[-1:]


_NEAR_CACHE: dict = {}


def _ways_near(g, lat, lon):
    key = (g.source, round(lat, 3), round(lon, 3))
    if key not in _NEAR_CACHE:
        _NEAR_CACHE[key] = [wid for wid, w in g.ways.items() if w.drivable and any(
            abs(g.nodes[n][0] - lat) < 0.0012 and abs(g.nodes[n][1] - lon) < 0.0012 for n in w.nodes)]
    return _NEAR_CACHE[key]


def _standard_route(g, de, doff, fit, wrs):
    """What an ordinary car map does: shortest drivable path to the door, ignoring width and water."""
    if de is None:
        return None
    main_nodes = {n for w in g.ways.values() if w.kind == "main" and w.drivable for n in w.nodes}
    dist, pred = dijkstra(g.drive_adj, {n: 0.0 for n in main_nodes}, lambda e: True, lambda e: g.edges[e].length)
    opts = [(dist[n] + (doff if n == de.u else de.length - doff), n) for n in (de.u, de.v) if n in dist]
    if not opts:
        return None
    _, n = min(opts)
    nodes = _path_nodes(pred, n)[::-1]
    bad = []
    for a, b in zip(nodes, nodes[1:]):
        eidx = pred[b][0]
        wid = g.edges[eidx].way_id
        if fit[wid] in ("no", "blocked", "unknown") and wid not in [x["way_id"] for x in bad]:
            wr = wrs[wid]
            bad.append({"way_id": wid, "name": g.display_name(wid), "label": wr.label, "fit": fit[wid],
                        "lo": round(wr.lo, 2), "hi": None if wr.hi >= 40 else round(wr.hi, 2)})
    return {"geometry": _coords(g, nodes), "unfit_ways": bad, "source": "osm",
            "note": "Standard map route: shortest car route without alley-width or flood checks"}


def _layers(g: AreaGraph, wrs, fit, fit_notes, fps, lat, lon, arrive, depart, rain, p,
            snapshot: FloodSnapshot):
    feats, flood_feats = [], []
    for wid, w in g.ways.items():
        if not w.drivable:
            continue
        la, lo = g.nodes[w.nodes[len(w.nodes) // 2]]
        if haversine(lat, lon, la, lo) > 750:
            continue
        wr = wrs[wid]
        coords = g.way_coords(wid)
        feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"way_id": wid, "name": g.display_name(wid), "kind": w.kind, "fit": fit[wid],
                                     "label": wr.label, "lo": round(wr.lo, 2),
                                     "hi": None if wr.hi >= 40 else round(wr.hi, 2),
                                     "top_tier": wr.top_tier, "review": wr.review, "note": fit_notes.get(wid)}})
        prof = fps.get(wid)
        da = snapshot.assess(prof, arrive, p.safe_water_depth, g.display_name(wid))
        dd = snapshot.assess(prof, depart, p.safe_water_depth, g.display_name(wid))
        if prof or da.depth or dd.depth or da.knowledge != "known" or dd.knowledge != "known":
            flood_feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                                "properties": {"way_id": wid, "name": g.display_name(wid),
                                               "records": len(prof.records) if prof else 0,
                                               "inferred_from": prof.inferred_from if prof else "",
                                               "arrive": da.depth.to_json() if da.depth else None,
                                               "depart": dd.depth.to_json() if dd.depth else None,
                                               "status_arrive": da.status,
                                               "status_depart": dd.status,
                                               "knowledge_arrive": da.knowledge,
                                               "knowledge_depart": dd.knowledge,
                                               "reason_arrive": da.reason,
                                               "reason_depart": dd.reason,
                                               "freshness_arrive": da.freshness,
                                               "freshness_depart": dd.freshness}})
    return {"fit": {"type": "FeatureCollection", "features": feats},
            "flood": {"type": "FeatureCollection", "features": flood_feats}}


def way_evidence(lat: float, lon: float, way_id: int, live_area: dict | None = None,
                 synthetic_demo_file: Path | None = None) -> dict:
    g, wrs, fps = area(lat, lon, live_area=live_area, synthetic_demo_file=synthetic_demo_file)
    w = g.ways[way_id]
    prof = fps.get(way_id)
    return {"way_id": way_id, "name": g.display_name(way_id), "tags": w.tags, "osm_url": f"https://www.openstreetmap.org/way/{way_id}",
            "width_range": wrs[way_id].to_json(),
            "flood_history": {"records": [r.to_json() for r in prof.records] if prof else [],
                              "inferred_from": prof.inferred_from if prof else ""}}

# Ordinal estimate order. Unknown is below a supported tight hypothesis and
# above an explicit negative; uncertainty is never treated as a clearance pass.
_ANSWER_ORDER = {'fits': 0, 'tight': 1, 'unknown': 2, 'no': 3}


def _stop_order(result):
    return (_ANSWER_ORDER[result['estimate']['answer']],
            {'high': 0, 'medium': 1, 'low': 2}[result['estimate']['confidence']],
            result['tier'], result['walk']['meters'])


def _segment_profile(g, wrs, route):
    """Ordered, physical arrival-edge lengths (including the partial door edge)."""
    profile, start = [], 0.0
    for ei, length in (route or {}).get('_segments', []):
        # A destination exactly at a junction can add a zero-length stop edge.
        # Its width remains in the stop estimate, but it is not driven distance.
        if round(length, 2) <= 0:
            continue
        wid = g.edges[ei].way_id
        wr = wrs[wid]
        h = _width_hypothesis(wr)
        profile.append({'way_id': wid, 'name': g.display_name(wid),
                        'length_m': round(length, 2), 'start_m': round(start, 2),
                        'width_lo': round(wr.lo, 2), 'width_hi': None if wr.hi >= 40 else round(wr.hi, 2),
                        'estimate_m': round(h['value_m'], 2) if h else None,
                        'width_basis': h.get('width_basis', wr.width_basis) if h else wr.width_basis,
                        'sample_count': h['sample_count'] if h else None,
                        'caveat': ('Sampled parcel gap minus 1 m (minimum 0.5 m); not continuous clear width'
                                   if (h or {}).get('width_basis', wr.width_basis) == 'parcel_gap_estimate' else None),
                        'tier': h['tier'] if h else wr.top_tier,
                        'source': h['source'] if h else None,
                        'observed_on': h.get('observed_on') if h else None,
                        'source_url': h.get('source_url') if h else None, 'sampled': bool(h and (h['sampled'] or any(
                            b.tier == h['tier'] and b.tier in ('Measured', 'Official', 'Observed')
                            and b not in wr.overruled and b.lo > 0 and b.hi < 40 for b in wr.evidence)))})
        start += length
    return profile


class _WithoutNode:
    """Read-only membership view; avoid copying the city tree per stop."""
    def __init__(self, values, excluded):
        self.values, self.excluded = values, excluded

    def __contains__(self, node):
        return node != self.excluded and node in self.values

    def __getitem__(self, node):
        if node not in self:
            raise KeyError(node)
        return self.values[node]


class _SharedRoutes:
    """Vehicle-independent widest estimated bottleneck, with distance tie-breaks.

    These are hypotheses, not clearance certificates. Unknown widths have zero
    capacity; a route containing them stays unknown. Directed access and today's
    closures are respected. One graph and two searches serve every vehicle.
    """
    def __init__(self, g, wrs):
        self.g, self.wrs = g, wrs
        self.values = {wid: _width_estimate(wr) for wid, wr in wrs.items()}
        self.blocked = set(blocked_ways_today())
        self.permissive = {wid: 'fits' for wid, way in g.ways.items() if way.drivable}
        self.main = {n for w in g.ways.values() if w.kind == 'main' and w.drivable for n in w.nodes}
        self.reverse = {}
        for n, edges in g.drive_adj.items():
            for ei, m in edges:
                self.reverse.setdefault(m, []).append((ei, n))
        self.arr = self._network(g.drive_adj)
        self.ext = self._network(self.reverse)
        self.routes, self.exits, self.exit_networks = {}, {}, {}

    def _network(self, adj):
        capacity = {n: INF for n in self.main}
        distance = {n: 0.0 for n in self.main}
        pred, queue = {}, [(-INF, 0.0, n) for n in sorted(self.main)]
        heapq.heapify(queue)
        while queue:
            neg, distance_n, n = heapq.heappop(queue)
            if (-neg, distance_n) != (capacity.get(n), distance.get(n)):
                continue
            for ei, m in adj.get(n, ()):
                edge = self.g.edges[ei]
                if edge.way_id in self.blocked:
                    continue
                cap = min(-neg, self.values[edge.way_id] or 0.0)
                dist = distance_n + edge.length
                if cap > capacity.get(m, -1) or (cap == capacity.get(m) and dist < distance.get(m, INF)):
                    capacity[m], distance[m], pred[m] = cap, dist, (ei, n)
                    heapq.heappush(queue, (-cap, dist, m))
        return capacity, distance, pred

    def route(self, c):
        key = (c.kind, c.edge_idx, c.offset, c.entrance)
        if key in self.routes:
            return self.routes[key]
        g = self.g
        cap, dist, pred = self.arr
        if c.kind == 'lot':
            out = _route_in(c, g, {True: ({}, {}), False: (dist, pred)})
        else:
            e, options = g.edges[c.edge_idx], []
            w = g.ways[e.way_id]
            if w.id not in self.blocked:
                for n, partial, side, allowed in ((e.u, c.offset, 'u', w.oneway >= 0),
                        (e.v, e.length-c.offset, 'v', w.oneway <= 0)):
                    if allowed and n in dist:
                        options.append((-min(cap[n], self.values[w.id] or 0), dist[n]+partial, n, partial, side))
            out = None
            if options:
                _, _, n, partial, side = min(options)
                ids = _pred_edge_ids(pred, n)[::-1] + [e.idx]
                segments = [(ei, g.edges[ei].length) for ei in ids[:-1]] + [(e.idx, partial)]
                out = {'strict': False, 'meters': round(sum(d for _, d in segments)), 'side': side,
                       '_segments': segments, 'edge_ids': ids, 'way_ids': [g.edges[ei].way_id for ei in ids],
                       'geometry': _coords(g, _path_nodes(pred, n)[::-1])+[[c.lon, c.lat]], 'flood': None}
        self.routes[key] = out
        return out

    def exit(self, c, route):
        if route is None:
            return {'mode': 'none', 'strict': False, 'text': 'No connected arrival route',
                    'edge_ids': [], 'way_ids': [], '_segments': []}
        key = (c.kind, c.edge_idx, c.offset, c.entrance, route.get('side'))
        if key in self.exits:
            return self.exits[key]
        g = self.g
        _, dist, pred = self.ext
        permissive = self.permissive
        out = _way_out(c, g, self.wrs, permissive, get_profile('class-xl'),
                       {True: ({}, {}), False: (dist, pred)}, route)
        # A shortest/widest exit tree may point back across the stop edge and
        # hide a forward loop. Search that loop explicitly, respecting direction.
        if c.kind != 'lot' and out['mode'] != 'through':
            e = g.edges[c.edge_idx]
            a, b = (e.u, e.v) if route.get('side') == 'u' else (e.v, e.u)
            w = g.ways[e.way_id]
            forward = w.oneway == 0 or (w.oneway == 1 and a == e.u) or (w.oneway == -1 and a == e.v)
            if forward:
                if (e.idx, b) not in self.exit_networks:
                    # Explore outward from the door and stop at the first main
                    # street. Rebuilding the entire city reverse tree for each
                    # stop edge is unnecessary and too slow for comparisons.
                    ds, ps, capacities = {b: 0.0}, {}, {b: INF}
                    queue = [(-INF, 0.0, b)]
                    target = None
                    while queue:
                        neg_capacity, distance, node = heapq.heappop(queue)
                        if distance != ds.get(node) or -neg_capacity != capacities.get(node):
                            continue
                        if node in self.main:
                            target = node
                            break
                        for ei, other in g.drive_adj.get(node, ()):
                            if ei == e.idx or g.edges[ei].way_id in self.blocked:
                                continue
                            capacity = min(-neg_capacity, self.values[g.edges[ei].way_id] or 0.0)
                            nd = distance+g.edges[ei].length
                            if capacity > capacities.get(other, -1) or (
                                    capacity == capacities.get(other) and nd < ds.get(other, INF)):
                                capacities[other], ds[other], ps[other] = capacity, nd, (ei, node)
                                heapq.heappush(queue, (-capacity, nd, other))
                    # Convert the forward tree to the route-in reverse-tree
                    # convention used below: b -> ... -> main street.
                    reverse_pred = {}
                    node = target
                    while node is not None and node in ps:
                        ei, parent = ps[node]
                        reverse_pred[parent] = (ei, node)
                        node = parent
                    self.exit_networks[e.idx, b] = ({b: ds[target]} if target is not None else {}, reverse_pred)
                ds, ps = self.exit_networks[e.idx, b]
                if b in ds:
                    partial = e.length-c.offset if a == e.u else c.offset
                    ids = [e.idx]+_pred_edge_ids(ps, b)
                    out = {'mode': 'through', 'strict': False, 'reverse_m': 0, 'tight_exit': False,
                           'text': 'Mapped through exit; width and manoeuvres require verification',
                           'geometry': [[c.lon, c.lat]]+_coords(g, _path_nodes(ps, b)),
                           '_segments': [(e.idx, partial)]+[(ei, g.edges[ei].length) for ei in ids[1:]],
                           'edge_ids': ids, 'way_ids': [g.edges[ei].way_id for ei in ids]}
        if c.kind != 'lot' and g.ways[c.way_id].oneway == 0:
            # A forward escape through a narrow shortcut must not hide the
            # wider reverse-to-junction option used by a larger vehicle.
            e = g.edges[c.edge_idx]
            b = e.v if route.get('side') == 'u' else e.u
            reverse_dist = _WithoutNode(dist, b)
            reverse = _way_out(c, g, self.wrs, permissive, get_profile('class-xl'),
                              {True: ({}, {}), False: (reverse_dist, pred)}, route)
            def quality(option):
                values = [self.values[wid] for wid in option.get('way_ids', [])]
                bottleneck = min(values) if values and all(v is not None for v in values) else 0.0
                return (option['mode'] == 'none', -bottleneck,
                        option['mode'] != 'through', _way_out_meters(option, g))
            out = min((out, reverse), key=quality)
        self.exits[key] = out
        return out


def _route_quality(route, ctx):
    if not route:
        return (4, 1, INF)
    vals = [ctx.shared.values[wid] for wid in route['way_ids']]
    value = min(vals) if vals and all(v is not None for v in vals) else None
    answer = ('unknown' if value is None else 'fits' if value >= ctx.vehicle.fits_min else
              'tight' if value >= ctx.vehicle.tight_min else 'no')
    sampled, total = 0.0, 0.0
    for ei, length in route.get('_segments', []):
        total += length
        wr = ctx.wrs[ctx.g.edges[ei].way_id]
        if any(b.tier in ('Measured', 'Official', 'Observed') and b not in wr.overruled
               and (b.estimate_m is not None or (0 < b.hi < 40 and
                    b.measurement_schema != 'parcel-survey-unresolved-v2')) for b in wr.evidence):
            sampled += length
    # Among equally good width hypotheses, prefer the sampled alternative over
    # an unsurveyed shortcut. Coverage describes this route, never a nearby way.
    return (_ANSWER_ORDER[answer], 0 if total and sampled/total >= .5 else 1,
            _way_out_meters(route, ctx.g))


def _checked_shared(route, ctx, times=None):
    if not route:
        return None
    strict = True
    for wid in route.get('way_ids', []):
        if not _usable(ctx.fit[wid], 'passable', False):
            return None
        strict = strict and ctx.fit[wid] in ('fits', 'tight')
        if times:
            flood = worst_over(ctx.fps.get(wid), times, ctx.rain, ctx.vehicle.safe_water_depth,
                               ctx.g.display_name(wid), ctx.flood)
            if flood.status == 'blocked':
                return None
            strict = strict and flood.status == 'passable'
    return {**route, 'strict': bool(strict and (route.get('mode', 'through') == 'through'))}


def _best_route(c, ctx, networks, times=None):
    original = _route_in(c, ctx.g, networks)
    if ctx.shared is None or c.kind == 'lot':
        return original
    common = _checked_shared(ctx.shared.route(c), ctx, times)
    def quality(incoming):
        outgoing = _checked_shared(ctx.shared.exit(c, incoming), ctx)
        if outgoing is None or outgoing['mode'] == 'none':
            return (4, 1, _way_out_meters(incoming, ctx.g))
        # Width feasibility is a complete arrival/exit decision. A cheap entry
        # facing an impossible exit must not hide the wider car's usable entry.
        traversed = incoming.get('_segments', [])+outgoing.get('_segments', [])
        scope = {}
        for ei, length in traversed:
            scope[ei] = max(scope.get(ei, 0), length)
        combined = {'way_ids': incoming['way_ids']+outgoing.get('way_ids', []),
                    '_segments': list(scope.items()), 'meters': sum(length for _, length in traversed)}
        return _route_quality(combined, ctx)
    return min((r for r in (original, common) if r is not None), key=quality, default=None)


def _best_way_out(c, ctx, networks, route, times=None):
    original = _way_out(c, ctx.g, ctx.wrs, ctx.fit, ctx.vehicle, networks, route)
    if ctx.shared is None or c.kind == 'lot' or route is None:
        return original
    common = _checked_shared(ctx.shared.exit(c, route), ctx, times)
    if common and common['mode'] != 'none':
        # Compare hypotheses before path length; all canonical width/flood
        # exclusions remain in _checked_shared. Reverse exits stay unverified.
        common['strict'] = common['strict'] and common['mode'] == 'through'
        original_quality = _route_quality(original if original.get('way_ids') else None, ctx)
        if original['mode'] == 'none' or _route_quality(common, ctx) < original_quality:
            return common
    return original


def compare_vehicles(lat: float, lon: float, intent: str, arrive_at: datetime | None,
                     dwell_min: int | None, rain: list[dict] | None, label: str,
                     vehicle_ids: list[str] | None = None, *, live_area: dict | None = None,
                     synthetic_demo_file: Path | None = None) -> dict:
    """Compare vehicle thresholds on ONE vehicle-independent route to the door.

    Choose the widest estimated bottleneck from the main-street network, breaking
    ties by distance. Unknown segments have zero capacity, never invented width.
    The route does not change with vehicle IDs or their ordering. Reuse the area,
    route searches and flood snapshot; do not run a separate arrival planner per
    vehicle. A comparison is an estimate, never an authorization to enter/park.
    """
    ids = list(dict.fromkeys(vehicle_ids if vehicle_ids is not None else
                            ['class-xs', 'class-s', 'class-m', 'class-l', 'class-xl']))
    profiles = [get_profile(vid) for vid in ids]
    arrive = (arrive_at or datetime.now(VN_TZ)).astimezone(VN_TZ)
    dwell = dwell_min if dwell_min is not None else (PICKUP_DWELL_MIN if intent == 'pickup' else 120)
    if dwell < 0:
        raise ValueError('Dwell duration must be nonnegative')
    depart = arrive + timedelta(minutes=dwell)
    rain = list(rain) if rain else (hydro.rain_spells(lat, lon) if flags.enabled('live_hydro') else [])
    snapshot = FloodSnapshot(rain)
    g, wrs, fps = area(lat, lon, snapshot.generations, live_area, synthetic_demo_file)
    shared = _SharedRoutes(g, wrs)
    edge, offset, connection = _project(g, lat, lon, lambda way: way.drivable)
    walk_edge, _, walk_connection = _project(g, lat, lon, lambda way: way.walkable)
    connected = edge is not None and connection <= WALK_CONNECTION_CAP_M
    mapped_walk = walk_edge is not None and walk_connection <= WALK_CONNECTION_CAP_M
    c = None
    if connected:
        la, lo = _interp(g, edge.u, edge.v, offset, edge.length)
        c = Candidate('door', la, lo, 'At the door', edge.way_id, edge.idx, offset,
                      walk_m=connection, data={'walk_path': {'unverified': not mapped_walk or connection > WALK_SNAP_M}})
    route = shared.route(c) if c else None
    way_out = shared.exit(c, route) if c else {'mode': 'none', 'strict': False, 'way_ids': [], '_segments': []}
    paid = parking_data.paid_street_ways(g)
    stay_times = snapshot.sample_times(arrive, depart)
    arrival_times = snapshot.sample_times(arrive-_traversal_duration((route or {}).get('meters', 0)), arrive)
    exit_times = snapshot.sample_times(depart, depart+_traversal_duration(_way_out_meters(way_out, g)))
    results = []
    for p in profiles:
        fit, notes = compute_fit(g, wrs, p)
        ctx = PlanContext(g, wrs, fps, fit, notes, paid, p, intent, rain, snapshot, [c] if c else [], shared=shared)
        if c is None:
            estimate = {'answer': 'unknown', 'confidence': 'low', 'decided_by': 'walk',
                        'basis': 'No mapped connection to the destination door', 'limiting_width': None}
            checks = {}
        else:
            incoming = {**route} if route else None
            outgoing = {**way_out}
            if incoming:
                checked_incoming = _checked_shared(incoming, ctx, arrival_times)
                incoming['strict'] = bool(checked_incoming and checked_incoming['strict'])
                incoming['flood'] = _route_flood(ctx, incoming, arrival_times)
            outgoing['strict'] = bool(outgoing.get('strict')) and all(
                fit[wid] in ('fits', 'tight') for wid in outgoing.get('way_ids', []))
            outgoing['flood'] = _route_flood(ctx, outgoing, exit_times)
            stay = _aggregate_flood(ctx, [c.way_id], stay_times, arrive, depart, approximate=False)
            status, rules = _candidate_legality(c, ctx, arrive, depart)
            checks = {'route_in': incoming, 'way_out': outgoing, 'fit': {'class': fit[c.way_id]},
                      'legality': {'status': status, 'rules': [english_payload(r.to_json()) for r in rules]},
                      'flood': {'stay': stay}}
            failures = []
            if outgoing['mode'] in ('none', 'unknown'):
                failures.append('No suitable exit; manoeuvres are unverified')
            flood_blocked = any(f and f['status'] == 'blocked' for f in
                                ((incoming or {}).get('flood'), outgoing['flood'], stay))
            if flood_blocked:
                failures.append('Flood blocks arrival, stay or departure')
            if not mapped_walk or connection > WALK_CAP_M[intent]:
                failures.append('Missing mapped walking connection')
            estimate = _estimate(c, g, wrs, p, checks, failures)
            if flood_blocked:
                estimate.update(answer='no', confidence='high', decided_by='flood')
            elif not mapped_walk:
                estimate.update(answer='unknown', confidence='low', decided_by='walk')
            # Shared hypotheses never certify manoeuvres, clearances or legality.
            if estimate['answer'] != 'no' and estimate['confidence'] == 'high' and not outgoing['strict']:
                estimate['confidence'] = 'medium'
        limiting = estimate.get('limiting_width')
        results.append({'vehicle_id': p.id, 'label': p.label, 'mirror_width': round(p.mirror_width, 3),
                        'needed_m': round(p.fits_min, 3),
                        'thresholds_m': {'fits': round(p.fits_min, 3), 'tight': round(p.tight_min, 3),
                                         'door': round(p.door_min, 3)},
                        'answer': estimate['answer'], 'confidence': estimate['confidence'],
                        'coverage': estimate.get('coverage'),
                        'limiting': ({'way_id': limiting['way_id'], 'name': limiting['way_name'],
                                     'width_lo': round(wrs[limiting['way_id']].lo, 2),
                                     'width_hi': None if wrs[limiting['way_id']].hi >= 40 else round(wrs[limiting['way_id']].hi, 2),
                                     'estimate_m': round(limiting['value_m'], 2), 'tier': limiting['tier'],
                                     'source': limiting['source'],
                                     'observed_on': limiting.get('observed_on'),
                                     'source_url': limiting.get('source_url'),
                                     'caveat': ('Sampled parcel gap minus 1 m (minimum 0.5 m); not continuous clear width'
                                                if limiting.get('width_basis', wrs[limiting['way_id']].width_basis) == 'parcel_gap_estimate' else None)} if limiting else None),
                        'decided_by': estimate['decided_by'], 'decisive_check': estimate['decided_by'],
                        'basis': estimate['basis'], 'checks': {**checks,
                            'route_in': _public_route(checks['route_in']) if checks.get('route_in') else None,
                            'way_out': _public_route(checks['way_out']) if checks.get('way_out') else None}})
    return english_payload({'destination': {'lat': lat, 'lon': lon, 'label': label}, 'intent': intent,
                            'window': {'arrive': arrive.isoformat(), 'depart': depart.isoformat(), 'dwell_min': dwell},
                            'route_choice': 'Widest estimated bottleneck from a main street; distance breaks ties. The same directed route is used for every vehicle.',
                            'route_in': _public_route(route) if route else None,
                            'profile': _segment_profile(g, wrs, route),
                            'exit_profile': _segment_profile(g, wrs, way_out),
                            'vehicles': results, 'area_source': g.source})
