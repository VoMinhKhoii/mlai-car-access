"""Arrival Plan engine: filter Stop Points by Hard Checks, then rank by walk (Q2, Q5–Q7, Q12, D15–D19)."""
from __future__ import annotations

import heapq
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import flags, parking_data
from .config import GOONG_API_KEY, PICKUP_DWELL_MIN, REVERSE_LIMIT_M, WALK_CAP_M, WALK_WADE_M
from .evidence import STORE_EVIDENCE, WidthRange, blocked_ways_today, width_ranges
from .flood import (FloodProfile, FloodRecord, alarm_label, depth_at, flood_profiles, flood_status, tide_level,
                    worst_over)
from .legality import ORDER as LEGAL_ORDER
from .legality import legality_for_lot, legality_on_street
from .osm import AreaGraph, build_graph, haversine
from .vehicles import VehicleProfile, get_profile, three_point_width, turn_in_width

VN_TZ = timezone(timedelta(hours=7))
WALK_SPEED = 1.2  # m/s
INF = float("inf")

_WR: dict = {}
_FP: dict = {}


def area(lat: float, lon: float):
    g = build_graph(lat, lon)
    key = (g.source, tuple(f["enabled"] for f in flags.describe()))
    wkey = key + (STORE_EVIDENCE.version,)
    if wkey not in _WR:
        _WR[wkey] = width_ranges(g)
    if key not in _FP:
        _FP[key] = flood_profiles(g)
    return g, _WR[wkey], _FP[key]


def invalidate_evidence() -> None:
    _WR.clear()


# ---- per-vehicle fit ----------------------------------------------------------

def fit_class(wr: WidthRange, p: VehicleProfile) -> str:
    if wr.lo >= p.fits_min:
        return "fits"
    if wr.lo >= p.tight_min:
        return "tight"
    if wr.hi < p.tight_min:
        return "no"
    return "unknown"


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
                if pid == wid or not g.ways[pid].drivable or wrs[pid].lo <= wrs[wid].lo:
                    continue
                street = min(round(wrs[pid].lo * 2) / 2, 12.0)
                need = turn_in_width(p.id, street)
                if wrs[wid].lo < need:
                    fit[wid] = "tight"
                    notes[wid] = f"Rẽ vào từ {g.ways[pid].name or 'đường chính'} cần đánh lái nhiều lần (rẽ một lần cần hẻm ≥ {need:.1f} m)"
    for wid, b in blocked_ways_today().items():
        if wid in fit:
            fit[wid] = "blocked"
            notes[wid] = f"Tạm thời bị chặn hôm nay: {b.get('reason', 'vật cản')} ({b.get('source', 'tài xế báo')})"
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


def _project(g: AreaGraph, lat: float, lon: float, predicate):
    """Nearest point on an edge whose way satisfies predicate → (edge, offset from u, distance)."""
    best = (None, 0.0, INF)
    kx = math.cos(math.radians(lat)) * 111320
    ky = 110540
    for e in g.edges:
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


def _fmt_t(t: datetime) -> str:
    return t.astimezone(VN_TZ).strftime("%H:%M")


def plan(dest_lat: float, dest_lon: float, vehicle_id: str, intent: str, arrive_at: datetime | None,
         dwell_min: int | None, rain_scenario: list[dict] | None = None, dest_label: str = "",
         _nested: bool = False, origin: tuple[float, float] | None = None) -> dict:
    p = get_profile(vehicle_id)
    arrive = (arrive_at or datetime.now(VN_TZ)).astimezone(VN_TZ)
    dwell = dwell_min if dwell_min else (PICKUP_DWELL_MIN if intent == "pickup" else 120)
    depart = arrive + timedelta(minutes=dwell)
    stay_times = [arrive + timedelta(minutes=m) for m in range(0, dwell + 1, 15)] + [depart]
    rain = rain_scenario or []
    cap = WALK_CAP_M[intent]

    g, wrs, fps = area(dest_lat, dest_lon)
    fit, fit_notes = compute_fit(g, wrs, p)
    paid = parking_data.paid_street_ways(g)

    def flood_at(times):
        return {wid: worst_over(fps.get(wid), times, rain, p.safe_water_depth, g.ways[wid].name) for wid in g.ways}

    fl_arr, fl_dep, fl_stay = flood_at([arrive]), flood_at([depart]), None
    main_nodes = {n for w in g.ways.values() if w.kind == "main" and w.drivable for n in w.nodes}
    rev_adj: dict[int, list[tuple[int, int]]] = {}
    for a, lst in g.drive_adj.items():
        for eidx, b in lst:
            rev_adj.setdefault(b, []).append((eidx, a))

    def way_of(eidx):
        return g.edges[eidx].way_id

    def search(adj, flood_map, strict):
        return dijkstra(adj, {n: 0.0 for n in main_nodes},
                        lambda e: _usable(fit[way_of(e)], flood_map[way_of(e)][0], strict),
                        lambda e: _cost(g.edges[e].length, fit[way_of(e)]))

    arr = {True: search(g.drive_adj, fl_arr, True), False: search(g.drive_adj, fl_arr, False)}
    ext = {True: search(rev_adj, fl_dep, True), False: search(rev_adj, fl_dep, False)}

    # Walk from the destination door outward.
    we, woff, wd = _project(g, dest_lat, dest_lon, lambda w: w.walkable)
    walk_src = {we.u: wd + woff, we.v: wd + (we.length - woff)}
    wdist, wpred = dijkstra(g.walk_adj, walk_src, lambda e: True, lambda e: g.edges[e].length, limit=cap + 60)
    de, doff, ddist = _project(g, dest_lat, dest_lon, lambda w: w.drivable)

    # ---- candidates
    cands: list[Candidate] = []
    if de is not None and ddist <= 35:
        la, lo = _interp(g, de.u, de.v, doff, de.length)
        cands.append(Candidate("door", la, lo, "Trước cửa nhà" , de.way_id, de.idx, doff,
                               walk_m=ddist))
    for e in g.edges:
        w = g.ways[e.way_id]
        if not w.drivable or min(wdist.get(e.u, INF), wdist.get(e.v, INF)) > cap + 20:
            continue
        offs = [e.length / 2] if e.length < 16 else [8.0, e.length / 2, e.length - 8.0]
        for s in offs:
            walk = min(wdist.get(e.u, INF) + s, wdist.get(e.v, INF) + e.length - s)
            if walk > cap:
                continue
            la, lo = _interp(g, e.u, e.v, s, e.length)
            cands.append(Candidate("street", la, lo, g.display_name(w.id), w.id, e.idx, s, walk_m=walk))
    for lot in parking_data.lots_near(g, dest_lat, dest_lon, radius=cap + 150):
        ent, ent_d = g.nearest_node(lot["lat"], lot["lon"], lambda n: n in g.drive_adj)
        wn, wnd = g.nearest_node(lot["lat"], lot["lon"], lambda n: n in wdist)
        if ent is None or ent_d > 80 or wn is None:
            continue
        walk = wdist[wn] + wnd
        if walk <= cap:
            cands.append(Candidate("lot", lot["lat"], lot["lon"], lot["name"], None, walk_m=walk, lot=lot,
                                   entrance=ent, data={"entrance_d": ent_d}))

    # ---- evaluate each candidate
    results, rejected = [], []
    door_eval = None
    for c in cands:
        r = _evaluate(c, g, wrs, fps, fit, fit_notes, paid, p, intent, arrive, depart, stay_times, rain,
                      arr, ext, fl_arr, fl_dep)
        if c.kind == "door":
            door_eval = r
        (results if r["ok"] else rejected).append(r)

    results.sort(key=lambda r: (r["tier"], r["walk"]["meters"]))
    chosen = []
    for r in results:
        same_way = r.get("way_id") and any(c.get("way_id") == r["way_id"] for c in chosen)
        if not same_way and all(haversine(r["lat"], r["lon"], c["lat"], c["lon"]) > 45 for c in chosen):
            chosen.append(r)
        if len(chosen) == 3:
            break
    for i, r in enumerate(chosen, 1):
        r["rank"] = i
        r["walk"]["geometry"] = _walk_geometry(g, r["_c"], wpred, dest_lat, dest_lon)
        r["walk"]["wade"] = _walk_wade(g, fps, r["_c"], wpred, arrive, rain)
    for r in results + rejected:
        r.pop("_c", None)

    std = _standard_route(g, de, doff, fit, wrs)
    if GOONG_API_KEY and std and not _nested:
        start = origin or (std["geometry"][0][1], std["geometry"][0][0])
        goong = goong_standard_route(g, start, (dest_lat, dest_lon), fit, wrs, GOONG_API_KEY)
        if goong:
            std = goong
    if origin and GOONG_API_KEY and not _nested:
        _add_trips(chosen, origin)

    verdict = _verdict(chosen, door_eval, intent, cap)
    timing = None
    exit_trouble = (not chosen or (door_eval and not door_eval["ok"])) and any(
        "lúc rời đi" in x for r in rejected for x in r["fail_reasons"])
    if exit_trouble and not _nested:
        timing = _flood_timing(p, arrive, depart, rain)
        if timing and timing.get("leave_before"):
            dwell_ok = int((timing["_before"] - arrive).total_seconds() // 60)
            alt = plan(dest_lat, dest_lon, vehicle_id, intent, arrive, dwell_ok, rain, dest_label, _nested=True)
            timing["if_leave_before"] = {"headline": alt["verdict"]["headline"], "code": alt["verdict"]["code"]}
        if timing:
            timing.pop("_before", None)
            parts = []
            if timing.get("leave_before"):
                parts.append(f"rời trước {timing['leave_before']}")
            if timing.get("or_after"):
                parts.append(f"hoặc ở lại tới sau {timing['or_after']}")
            verdict["timing"] = (f"Triều lên làm ngập đường ra lúc {_fmt_t(depart)}. Để xe này ra được: "
                                 + " ".join(parts) + ".")

    return {
        "destination": {"lat": dest_lat, "lon": dest_lon, "label": dest_label},
        "vehicle": p.to_json(),
        "intent": intent,
        "window": {"arrive": arrive.isoformat(), "depart": depart.isoformat(), "dwell_min": dwell,
                   "tide_arrive": _tide_json(arrive), "tide_depart": _tide_json(depart), "rain": rain},
        "verdict": verdict,
        "timing": timing,
        "stop_points": chosen,
        "door": door_eval,
        "standard_route": std,
        "layers": _layers(g, wrs, fit, fit_notes, fps, dest_lat, dest_lon, arrive, depart, rain, p),
        "area_source": g.source,
        "counts": {"candidates": len(cands), "passed": len(results), "rejected": len(rejected)},
    }


def _flood_timing(p: VehicleProfile, arrive, depart, rain) -> dict | None:
    """Latest departure before, or earliest after, the flood that traps this vehicle on tide-prone streets."""
    probe = FloodProfile([FloodRecord(0, 0, "", None, "", "tide", None, "high", "")])

    def ok(t):
        return flood_status(depth_at(probe, t, rain), p.safe_water_depth) == "passable"

    if ok(depart):
        return None
    before, t = None, depart
    while t - timedelta(minutes=15) >= arrive + timedelta(minutes=15):
        t -= timedelta(minutes=15)
        if ok(t):
            before = t
            break
    after, t = None, depart
    for _ in range(48):
        t += timedelta(minutes=15)
        if ok(t):
            after = t
            break
    if not before and not after:
        return None
    return {"leave_before": _fmt_t(before) if before else None, "_before": before,
            "or_after": _fmt_t(after) if after else None}


def _tide_json(t):
    lvl = tide_level(t)
    return {"level_m": None if lvl is None else round(lvl, 2), "alarm": alarm_label(lvl)}


def _evaluate(c, g, wrs, fps, fit, fit_notes, paid, p, intent, arrive, depart, stay_times, rain,
              arr, ext, fl_arr, fl_dep) -> dict:
    checks, reasons_fail, unverified = {}, [], []
    tier_bump = 0
    way_id = c.way_id if c.kind != "lot" else None

    # 1. Route in (on the Fit Network, flood at arrival).
    route = _route_in(c, g, arr)
    if route is None:
        reasons_fail.append("Không có đường vào phù hợp với xe (hẻm hẹp hoặc ngập lúc đến)")
    elif not route["strict"]:
        unverified.append("Đường vào đi qua đoạn chưa đủ bằng chứng (bề rộng hoặc ngập)")
    checks["route_in"] = route

    # 2. Fit at the stop itself + door opening (street stops only).
    if way_id is not None:
        wr = wrs[way_id]
        fc = fit[way_id]
        fitj = {"class": fc, "width_range": wr.to_json(), "note": fit_notes.get(way_id),
                "needed": {"fits_min": round(p.fits_min, 2), "tight_min": round(p.tight_min, 2),
                           "door_min": round(p.door_min, 2)}}
        if fc in ("no", "blocked"):
            reasons_fail.append(fit_notes.get(way_id) or
                                f"{wr.label} {wr.lo:.1f}–{min(wr.hi, 40):.1f} m, xe cần ≥ {p.tight_min:.2f} m")
        elif fc == "unknown":
            unverified.append(f"Chưa đủ bằng chứng bề rộng ({wr.lo:.1f}–{min(wr.hi, 40):.1f} m; xe cần ≥ {p.tight_min:.2f} m)")
        elif fc == "tight":
            tier_bump = max(tier_bump, 0)
        if wr.hi < p.door_min:
            reasons_fail.append(f"Không đủ chỗ mở cửa xe (cần {p.door_min:.2f} m)")
        elif wr.lo < p.door_min and fc != "no":
            unverified.append(f"Chưa chắc đủ chỗ mở cửa xe (cần {p.door_min:.2f} m)")
        checks["fit"] = fitj
    else:
        checks["fit"] = {"class": "lot", "note": "Bãi đỗ ngoài đường"}

    # 3. Way Out (at departure).
    wo = _way_out(c, g, wrs, fit, p, ext, route)
    checks["way_out"] = wo
    if wo["mode"] == "none":
        reasons_fail.append(wo["text"])
    elif not wo["strict"]:
        unverified.append("Đường ra lúc rời đi chưa đủ bằng chứng")
    if wo.get("tight_exit"):
        tier_bump = 1

    # 4. Flood at the stop over the whole Dwell Window.
    prof = fps.get(way_id) if way_id is not None else (fps.get(g.edges[g.drive_adj[c.entrance][0][0]].way_id)
                                                        if c.entrance in g.drive_adj else None)
    st, d, t = worst_over(prof, stay_times, rain, p.safe_water_depth, g.ways[way_id].name if way_id else "")
    flood = {"stay": {"status": st, "depth": d.to_json() if d else None, "at": _fmt_t(t) if t else None},
             "arrival_route": route["flood"] if route else None, "exit_route": wo.get("flood")}
    if st == "blocked":
        reasons_fail.append(f"Điểm dừng ngập {d.lo * 100:.0f}–{d.hi * 100:.0f} cm lúc {_fmt_t(t)} "
                            f"({', '.join(d.drivers)}), quá mức an toàn {p.safe_water_depth * 100:.0f} cm của xe")
    elif st == "risky":
        unverified.append(f"Có thể ngập {d.lo * 100:.0f}–{d.hi * 100:.0f} cm lúc {_fmt_t(t)}")
    checks["flood"] = flood

    # 5. Stop Legality.
    if c.kind == "lot":
        lstatus, rules = legality_for_lot(c.lot, intent)
    else:
        e = g.edges[c.edge_idx]
        dj = min(c.offset if g.drive_degree(e.u) >= 3 else INF,
                 e.length - c.offset if g.drive_degree(e.v) >= 3 else INF)
        lstatus, rules = legality_on_street(g, g.ways[way_id], wrs[way_id], c.lat, c.lon, dj, intent, arrive,
                                            paid.get(way_id))
    checks["legality"] = {"status": lstatus, "rules": [r.to_json() for r in rules]}
    if lstatus == "Prohibited" or (intent == "park" and lstatus == "Restricted"):
        reasons_fail.append("; ".join(r.text for r in rules if r.status in ("Prohibited", "Restricted")))
    elif lstatus == "Unverified":
        unverified.append("Chưa đủ dữ liệu pháp lý: " + "; ".join(r.text for r in rules if r.status == "Unverified"))

    # Ranking tiers (Q6, Q7): verified → verified with a tight exit → Restricted or Unverified.
    tier = 2 if (lstatus == "Restricted" or unverified) else tier_bump
    ok = not reasons_fail
    walk_min = c.walk_m / WALK_SPEED / 60
    return {
        "ok": ok, "kind": c.kind, "name": c.name, "lat": c.lat, "lon": c.lon, "way_id": way_id,
        "tier": tier, "verified": ok and tier <= 1,
        "badges": _badges(checks, tier, lstatus),
        "walk": {"meters": round(c.walk_m), "minutes": max(1, round(walk_min)) if c.walk_m > 20 else 0},
        "route_in": route and {k: v for k, v in route.items() if k != "strict"},
        "fit": checks["fit"], "way_out": {k: v for k, v in wo.items() if k != "strict"},
        "flood": flood, "legality": checks["legality"],
        "fail_reasons": reasons_fail, "unverified_reasons": unverified, "lot": c.lot, "_c": c,
    }


def _route_in(c: Candidate, g: AreaGraph, arr) -> dict | None:
    for strict in (True, False):
        dist, pred = arr[strict]
        if c.kind == "lot":
            n = c.entrance
            if n in dist:
                nodes = _path_nodes(pred, n)[::-1]
                return {"strict": strict, "meters": round(dist[n] + c.data.get("entrance_d", 0)),
                        "geometry": _coords(g, nodes) + [[c.lon, c.lat]], "flood": None}
            continue
        e = g.edges[c.edge_idx]
        w = g.ways[e.way_id]
        opts = []
        if e.u in dist and w.oneway >= 0:
            opts.append((dist[e.u] + c.offset, e.u, "u"))
        if e.v in dist and w.oneway <= 0:
            opts.append((dist[e.v] + e.length - c.offset, e.v, "v"))
        if opts:
            dmin, n, side = min(opts)
            nodes = _path_nodes(pred, n)[::-1]
            return {"strict": strict, "meters": round(dmin), "side": side,
                    "geometry": _coords(g, nodes) + [[c.lon, c.lat]], "flood": None}
    return None


def _way_out(c: Candidate, g: AreaGraph, wrs, fit, p: VehicleProfile, ext, route) -> dict:
    if route is None:
        return {"mode": "none", "text": "Không vào được nên không xét đường ra", "strict": False}
    for strict in (True, False):
        dist, pred = ext[strict]
        if c.kind == "lot":
            n = c.entrance
            if n in dist:
                return {"mode": "lot", "strict": strict, "reverse_m": 0, "tight_exit": False,
                        "text": "Quay đầu trong bãi rồi ra theo đường vào",
                        "geometry": [[c.lon, c.lat]] + _coords(g, _path_nodes(pred, n))}
            continue
        e = g.edges[c.edge_idx]
        w = g.ways[e.way_id]
        a, b = (e.u, e.v) if route["side"] == "u" else (e.v, e.u)
        s_a = c.offset if route["side"] == "u" else e.length - c.offset
        forward_ok = (w.oneway == 0) or (w.oneway == 1 and a == e.u) or (w.oneway == -1 and a == e.v)
        if wrs[w.id].lo >= three_point_width(p.id) and a in dist:
            return {"mode": "turn_here", "strict": strict, "reverse_m": 0, "tight_exit": False,
                    "text": f"Quay đầu tại chỗ (đường rộng ≥ {wrs[w.id].lo:.1f} m)",
                    "geometry": [[c.lon, c.lat]] + _coords(g, _path_nodes(pred, a))}
        if forward_ok and b in dist and pred.get(b, (None,))[0] != e.idx:
            return {"mode": "through", "strict": strict, "reverse_m": 0, "tight_exit": False,
                    "text": "Đi thẳng ra đường lớn, không phải lùi",
                    "geometry": [[c.lon, c.lat]] + _coords(g, _path_nodes(pred, b))}
        if a in dist:
            path = _path_nodes(pred, a)
            rev = s_a
            turn_at = None
            for i, n in enumerate(path):
                usable = [wid for wid in g.node_ways.get(n, ()) if fit.get(wid) in ("fits", "tight")]
                if len(usable) >= 3 or (usable and any(g.ways[x].kind == "main" for x in usable) and i > 0):
                    turn_at = i
                    break
                if i + 1 < len(path):
                    rev += g.edges[pred[n][0]].length
            if turn_at is None:
                turn_at = len(path) - 1
            if rev > 2 * REVERSE_LIMIT_M:  # nobody reverses a car this far in an alley: not a way out (D29)
                continue
            tight = rev > REVERSE_LIMIT_M
            txt = (f"Lùi {rev:.0f} m rồi quay đầu tại ngã ba" if not tight
                   else f"Phải lùi {rev:.0f} m (quá giới hạn {REVERSE_LIMIT_M:.0f} m) mới quay đầu được")
            return {"mode": "reverse", "strict": strict, "reverse_m": round(rev), "tight_exit": tight,
                    "text": txt, "geometry": [[c.lon, c.lat]] + _coords(g, path)}
    return {"mode": "none", "strict": False,
            "text": "Không có đường ra phù hợp lúc rời đi (hẻm cụt hoặc ngập lúc về)"}


def _badges(checks, tier, lstatus) -> list[str]:
    out = []
    fc = checks["fit"]["class"]
    out.append({"fits": "Vừa xe", "tight": "Chật", "unknown": "Chưa rõ bề rộng", "lot": "Bãi đỗ"}.get(fc, fc))
    wo = checks["way_out"]
    out.append({"through": "Đi thẳng ra", "turn_here": "Quay đầu tại chỗ", "lot": "Quay đầu trong bãi",
                "reverse": f"Lùi {wo.get('reverse_m', 0)} m"}.get(wo["mode"], "Không có đường ra"))
    out.append({"passable": "Không ngập", "risky": "Có thể ngập", "blocked": "Ngập"}[checks["flood"]["stay"]["status"]])
    if lstatus == "Unverified":
        codes = {r["code"] for r in checks["legality"]["rules"] if r["status"] == "Unverified"}
        out.append("Chưa rõ đủ 2 làn xe" if "lane-unknown" in codes else "Chưa rõ biển báo")
    else:
        out.append({"Permitted": "Được phép", "Restricted": "Hạn chế theo luật", "Prohibited": "Cấm"}[lstatus])
    return out


def _walk_geometry(g, c: Candidate, wpred, dlat, dlon):
    if c.kind == "door":
        return [[c.lon, c.lat], [dlon, dlat]]
    if c.kind == "lot":
        n, _ = g.nearest_node(c.lat, c.lon, lambda x: x in wpred)
        return [[c.lon, c.lat]] + (_coords(g, _path_nodes(wpred, n)) if n else []) + [[dlon, dlat]]
    e = g.edges[c.edge_idx]
    best = min((e.u, e.v), key=lambda n: (0 if n in wpred else 1, 0))
    return [[c.lon, c.lat]] + _coords(g, _path_nodes(wpred, best)) + [[dlon, dlat]]


def _walk_wade(g, fps, c: Candidate, wpred, arrive, rain):
    worst = None
    if c.kind == "door":
        return None
    start = g.nearest_node(c.lat, c.lon, lambda x: x in wpred)[0] if c.kind == "lot" else g.edges[c.edge_idx].u
    node = start
    while node in wpred:
        eidx, node = wpred[node]
        d = depth_at(fps.get(g.edges[eidx].way_id), arrive, rain, g.ways[g.edges[eidx].way_id].name)
        if d and d.hi > WALK_WADE_M and (worst is None or d.hi > worst["hi"]):
            worst = {"lo": round(d.lo, 2), "hi": round(d.hi, 2), "street": g.ways[g.edges[eidx].way_id].name,
                     "label": "Lội nước"}
    return worst


def _verdict(chosen, door_eval, intent, cap) -> dict:
    if not chosen:
        return {"code": "none", "headline": f"Không có điểm dừng phù hợp trong {cap:.0f} m đi bộ",
                "detail": "Thử đổi giờ đến, thời gian ở lại hoặc chọn xe nhỏ hơn."}
    best = chosen[0]
    verb = "đỗ" if intent == "park" else "dừng đón/trả"
    if best["kind"] == "door" and best["verified"]:
        return {"code": "door", "headline": "Xe vào tận cửa được", "detail": best["way_out"]["text"]}
    if not best["verified"]:
        head = ("Chỉ có điểm dừng hạn chế theo luật" if best["legality"]["status"] == "Restricted"
                else "Chưa đủ bằng chứng để khẳng định")
        return {"code": "unverified", "headline": head,
                "detail": f"Gợi ý: {verb} tại {best['name']}, đi bộ {best['walk']['meters']} m"}
    return {"code": "nearby", "headline": f"{verb.capitalize()} tại {best['name']}, đi bộ {best['walk']['meters']} m"
                                          f" (~{best['walk']['minutes']} phút)",
            "detail": "Xe không nên vào tận cửa" if door_eval and not door_eval["ok"] else ""}


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
    """Goong Direction v2 car route: geometry [[lon, lat]…], distance (m) and duration (s)."""
    import httpx
    try:
        r = httpx.get("https://rsapi.goong.io/v2/direction",
                      params={"api_key": GOONG_API_KEY, "origin": f"{origin[0]},{origin[1]}",
                              "destination": f"{dest[0]},{dest[1]}", "vehicle": "car"}, timeout=15).json()
        leg = r["routes"][0]["legs"][0]
        coords = []
        for step in leg["steps"]:
            coords += _decode_polyline(step["polyline"]["points"])
        return {"geometry": coords, "distance_m": leg["distance"]["value"], "duration_s": leg["duration"]["value"]}
    except Exception:
        return None


ALLEY_SPEED = 15 / 3.6  # m/s for the last stretch inside alleys


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
        drive_s = leg["duration_s"] + last / ALLEY_SPEED
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
    return {"geometry": coords, "unfit_ways": bad, "source": "Goong Direction v2 (car)",
            "distance_m": leg["distance_m"], "duration_s": leg["duration_s"],
            "note": "Tuyến ô tô của Goong: không tính bề rộng hẻm và ngập"}


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
    return {"geometry": _coords(g, nodes), "unfit_ways": bad,
            "note": "Tuyến bản đồ thông thường: đường ngắn nhất cho ô tô, không tính bề rộng hẻm và ngập"}


def _layers(g, wrs, fit, fit_notes, fps, lat, lon, arrive, depart, rain, p):
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
                      "properties": {"way_id": wid, "name": w.name, "kind": w.kind, "fit": fit[wid],
                                     "label": wr.label, "lo": round(wr.lo, 2),
                                     "hi": None if wr.hi >= 40 else round(wr.hi, 2),
                                     "top_tier": wr.top_tier, "review": wr.review, "note": fit_notes.get(wid)}})
        prof = fps.get(wid)
        da, dd = depth_at(prof, arrive, rain, w.name), depth_at(prof, depart, rain, w.name)
        if prof or da or dd:
            flood_feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                                "properties": {"way_id": wid, "name": w.name, "records": len(prof.records) if prof else 0,
                                               "inferred_from": prof.inferred_from if prof else "",
                                               "arrive": da.to_json() if da else None,
                                               "depart": dd.to_json() if dd else None,
                                               "status_arrive": flood_status(da, p.safe_water_depth),
                                               "status_depart": flood_status(dd, p.safe_water_depth)}})
    return {"fit": {"type": "FeatureCollection", "features": feats},
            "flood": {"type": "FeatureCollection", "features": flood_feats}}


def way_evidence(lat: float, lon: float, way_id: int) -> dict:
    g, wrs, fps = area(lat, lon)
    w = g.ways[way_id]
    prof = fps.get(way_id)
    return {"way_id": way_id, "name": g.display_name(way_id), "tags": w.tags, "osm_url": f"https://www.openstreetmap.org/way/{way_id}",
            "width_range": wrs[way_id].to_json(),
            "flood_history": {"records": [r.to_json() for r in prof.records] if prof else [],
                              "inferred_from": prof.inferred_from if prof else ""}}
