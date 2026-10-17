"""Large-road route from A to B (D34): which way to drive, given traffic and water right now.

Goong gives one car route and no traffic. Alternatives come from routing via traffic cameras that lie
to either side of it (cameras sit on the arterials, so a camera is a good via point). Each route is
scored with its own camera readings (up to two frames about 13 seconds apart; a one-frame read cannot establish traffic movement) and
flood forecast along it (tide, rain and IRD history, as for alleys). The arrival plan still decides
the last stretch into the alley.
"""
from __future__ import annotations

import math
import re
import statistics
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from . import cameras, flags, hydro
from .config import CACHED_ONLY, GOONG_API_KEY, TRAFFIC_FACTOR, TRAFFIC_QUEUE_MIN
from .flood import DepthRange, flood_status, FloodProfile, FloodSnapshot, load_records, _street_key
from .osm import ALLEY_NAME, haversine, strip_accents
from .plan import _decode_polyline, _densify
from .vehicles import get_profile

VN_TZ = timezone(timedelta(hours=7))
LIVE_BEFORE_MIN, LIVE_AFTER_MIN = 15, 45   # cameras describe departures within this window of now
MAX_DETOUR = 1.6                           # an alternative may be at most this much longer than Goong's
SAME_ROUTE = 0.8                           # share of points within 40 m that makes two routes the same
CLUSTER_GAP_M = 400
COVER_M = 700                              # a camera speaks for this far along the route each way
CAMS_PER_CLUSTER = 3
RISKY_FLOOD_MIN = 5
ALLEY_MIN = 2
END_M = 400                                # alleys this close to either end are not the corridor's
STEP_NAME = re.compile(r"(?:vào|từ|trên)\s+(.+?)\s*$")


def _norm(name: str) -> str:
    s = re.sub(r"\s+\d+$", "", strip_accents(re.sub(r"\(.*?\)", "", name or ""))).strip()
    return re.sub(r"^(duong|nut giao|vong xoay)\s+", "", s)


def _fmt(t: datetime) -> str:
    return t.astimezone(VN_TZ).strftime("%H:%M")


# ---- routes ---------------------------------------------------------------------

def goong_route(origin, dest, via=None) -> dict | None:
    """Goong Direction v2 car route through an optional via point, with the street of every step."""
    if CACHED_ONLY:
        return None
    stops = ([f"{via['lat']},{via['lon']}"] if via else []) + [f"{dest[0]},{dest[1]}"]
    try:
        r = httpx.get("https://rsapi.goong.io/v2/direction",
                      params={"api_key": GOONG_API_KEY, "origin": f"{origin[0]},{origin[1]}",
                              "destination": ";".join(stops), "vehicle": "car"}, timeout=15).json()
        legs = r["routes"][0]["legs"]
        steps, coords = [], []
        for leg in legs:
            for s in leg["steps"]:
                pts = _decode_polyline(s["polyline"]["points"])
                m = STEP_NAME.search(re.sub(r"<[^>]+>", "", s.get("html_instructions", "")))
                steps.append({"name": m.group(1) if m else "", "coords": pts, "m": s["distance"]["value"]})
                coords += pts
        distance = sum(l["distance"]["value"] for l in legs)
        duration = sum(l["duration"]["value"] for l in legs)
        if len(coords) < 2 or not all(math.isfinite(v) for point in coords for v in point) \
                or not math.isfinite(distance) or not math.isfinite(duration) or distance < 0 or duration < 0:
            return None
        return {"geometry": coords, "steps": steps, "via": via,
                "distance_m": distance, "duration_s": duration}
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError, OverflowError):
        return None


def _samples(route: dict) -> list[tuple[float, float, float, str]]:
    """(lat, lon, metres along, street) every ~25 m."""
    out, along, prev = [], 0.0, None
    for s in route["steps"]:
        for lon, lat in _densify(s["coords"], 25.0) if len(s["coords"]) > 1 else s["coords"]:
            if prev:
                along += haversine(prev[0], prev[1], lat, lon)
            out.append((lat, lon, along, s["name"]))
            prev = (lat, lon)
    return out


def _nearest(pts, lat, lon):
    best = (math.inf, None)
    for p in pts:
        if abs(p[0] - lat) < 0.002 and abs(p[1] - lon) < 0.002:
            d = haversine(lat, lon, p[0], p[1])
            if d < best[0]:
                best = (d, p)
    return best


def _overlap(a, b) -> float:
    hits = sum(1 for p in a[::4] if _nearest(b, p[0], p[1])[0] <= 40)
    return hits / max(1, len(a[::4]))


def _via_candidates(origin, dest, base_pts, k_per_side: int = 2) -> list[dict]:
    """Cameras off to each side of Goong's route, in the middle of the trip, as via points."""
    od = haversine(*origin, *dest)
    kx = math.cos(math.radians(origin[0])) * 111320
    ux, uy = (dest[1] - origin[1]) * kx, (dest[0] - origin[0]) * 110540
    sides: dict[int, list] = {1: [], -1: []}
    for c in cameras.registry()["cameras"]:
        do, dd = haversine(*origin, c["lat"], c["lon"]), haversine(*dest, c["lat"], c["lon"])
        if do + dd > 1.4 * od or not 0.2 <= do / (do + dd) <= 0.8:
            continue
        off = _nearest(base_pts, c["lat"], c["lon"])[0]
        if off < 800:
            continue
        cx, cy = (c["lon"] - origin[1]) * kx, (c["lat"] - origin[0]) * 110540
        side = 1 if ux * cy - uy * cx > 0 else -1
        sides[side].append((off, c))
    out = []
    for lst in sides.values():
        lst.sort(key=lambda x: x[0])
        picked = []
        for off, c in lst:  # nearest corridor, then one clearly further out
            if all(haversine(c["lat"], c["lon"], p["lat"], p["lon"]) > 1500 for p in picked):
                picked.append(c)
            if len(picked) == k_per_side:
                break
        out += picked
    return out


def _route_cams(pts) -> list[list[dict]]:
    """Cameras that watch this route, grouped into clusters along it."""
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    s, n, w, e = min(lats) - 0.002, max(lats) + 0.002, min(lons) - 0.002, max(lons) + 0.002
    hits = []
    for c in cameras.registry()["cameras"]:
        if not (s <= c["lat"] <= n and w <= c["lon"] <= e):
            continue
        d, p = _nearest(pts, c["lat"], c["lon"])
        if p is None or d > 70:
            continue
        here = {_norm(q[3]) for q in pts if abs(q[2] - p[2]) <= 300 and q[3]}
        names = cameras.street_names(c)
        if d <= 25 or any(a and b and (a in b or b in a) for a in names for b in here):
            hits.append((p[2], d, c))
    hits.sort(key=lambda h: h[0])
    clusters: list[list] = []
    for h in hits:
        if clusters and h[0] - clusters[-1][-1][0] <= CLUSTER_GAP_M:
            clusters[-1].append(h)
        else:
            clusters.append([h])
    return [[{**c, "along_m": round(a)} for a, _, c in sorted(cl, key=lambda h: h[1])[:CAMS_PER_CLUSTER]]
            for cl in clusters]


def _forecast_flood(pts, route, depart, rain, safe, snapshot: FloodSnapshot) -> list[dict]:
    """Flood forecast along the route from IRD history, tide and rain (same model as for alleys)."""
    lats, lons = [p[0] for p in pts], [p[1] for p in pts]
    s, n, w, e = min(lats) - 0.007, max(lats) + 0.007, min(lons) - 0.007, max(lons) + 0.007
    groups: dict[str, list] = {}
    for record in load_records():
        if not (s <= record.lat <= n and w <= record.lon <= e):
            continue
        distance, point = _nearest_far(pts, record.lat, record.lon)
        if point is None:
            continue
        same = _street_key(record.street) and _street_key(record.street) == _street_key(point[3])
        if (record.precision == "high" and distance <= 50) or \
                (record.precision == "medium" and distance <= 120 and (same or distance <= 40)) or \
                (same and distance <= 700):
            groups.setdefault(point[3] or record.street, []).append((point[2], record))
    out = []
    total = max(1.0, pts[-1][2])
    for street, hits in groups.items():
        along = min(a for a, _ in hits)
        t = depart + timedelta(seconds=route["duration_s"] * along / total)
        assessment = snapshot.assess(FloodProfile([record for _, record in hits]), t, safe, street)
        item = assessment.to_json()
        item.update({"street": street, "at": t.isoformat(), "along_m": round(along),
                     "records": len(hits)})
        out.append(item)
    return sorted(out, key=lambda x: x["along_m"])


def _nearest_far(pts, lat, lon):
    best = (math.inf, None)
    for p in pts[::2]:
        if abs(p[0] - lat) < 0.007 and abs(p[1] - lon) < 0.007:
            d = haversine(lat, lon, p[0], p[1])
            if d < best[0]:
                best = (d, p)
    return best


def _label(route) -> str:
    by: dict[str, float] = {}
    for s in route["steps"][1:-1]:
        if s["name"]:
            by[s["name"]] = by.get(s["name"], 0) + s["m"]
    top = sorted(by.items(), key=lambda x: -x[1])[:3]
    order = [s["name"] for s in route["steps"] if s["name"] in dict(top)]
    return "via " + ", ".join(dict.fromkeys(order)) if order else "direct route"


# ---- scoring --------------------------------------------------------------------

def corridor(origin: tuple[float, float], dest: tuple[float, float], vehicle_id: str,
             depart_at: datetime | None = None, rain: list[dict] | None = None,
             schedule_cameras: bool = False) -> dict:
    """Route choice from the flood forecast and whatever camera readings are cached now; never waits on cameras.

    With schedule_cameras (operator only), the unread cameras most relevant to the routes are queued as one bounded
    background job (`camera_job`); the client polls it and asks again once it is ready."""
    if not GOONG_API_KEY:
        return {"available": False, "reason": "GOONG_API_KEY is required for main-road routes"}
    p = get_profile(vehicle_id)
    now = datetime.now(VN_TZ)
    depart = (depart_at or now).astimezone(VN_TZ)
    lead = (depart - now).total_seconds() / 60
    use_cams = flags.enabled("ai_camera_flood") and -LIVE_BEFORE_MIN <= lead <= LIVE_AFTER_MIN

    base = goong_route(origin, dest)
    if not base:
        return {"available": False, "reason": "Goong returned no routes"}
    base_pts = _samples(base)
    with ThreadPoolExecutor(4) as pool:
        alts = [r for r in pool.map(lambda v: goong_route(origin, dest, v),
                                    _via_candidates(origin, dest, base_pts)) if r]
    routes = [(base, base_pts)]
    for r in alts:
        if r["distance_m"] > MAX_DETOUR * base["distance_m"]:
            continue
        pts = _samples(r)
        if any(_overlap(pts, q) >= SAME_ROUTE and _overlap(q, pts) >= SAME_ROUTE for _, q in routes):
            continue
        routes.append((r, pts))

    clusters = [_route_cams(pts) for _, pts in routes]
    cam_ids = [c["id"] for cls in clusters for cl in cls for c in cl]
    readings = cameras.cached(cam_ids) if use_cams else {}
    camera_job = None
    if use_cams and cam_ids:
        chosen, dropped = _camera_subset(clusters, readings)
        if chosen and schedule_cameras:
            try:
                job = cameras.schedule(chosen)
                camera_job = {"id": job["id"], "state": job["state"], "dropped": dropped}
            except cameras.Busy as exc:
                camera_job = {"id": None, "state": "busy", "retry_after": exc.retry_after, "dropped": dropped,
                              "reason": "Camera reading queue is full"}
        camera_job = camera_job or {"id": None, "state": "not_scheduled", "dropped": dropped,
                                    "reason": None if not chosen else "Operator sign-in required for new camera readings"}
        camera_job.update(cameras_requested=len(set(cam_ids) - set(readings)),
                          cameras_scheduled=len(chosen) if camera_job["id"] else 0)
        scheduled = set(chosen) if camera_job["id"] else set()
    else:
        scheduled = set()

    seen = [_observe(cls, readings, p, scheduled) for cls in clusters]
    factors = {h["name"]: TRAFFIC_FACTOR[h["traffic"]] for hs in seen for h in hs if h["traffic"]}
    typical = statistics.median(factors.values()) if factors else 1.0
    request_rain = rain if rain is not None else []
    flood_snapshot = FloodSnapshot(request_rain)
    out = [_score(i, r, pts, hs, typical, p, depart, request_rain, flood_snapshot)
           for i, ((r, pts), hs) in enumerate(zip(routes, seen))]
    ok = [x for x in out if x["status"] != "blocked"] or out
    best = min(ok, key=lambda x: (x["status"] == "blocked", x["eta_min"], x["distance_m"]))
    best["chosen"] = True
    summary = _summary(best, out[0], out)
    if use_cams and best["status"] != "blocked" and best["traffic_unknown"] > 0:
        count = best["traffic_unknown"]
        summary += f" {count} segments lack camera traffic confirmation; ETA cannot rule out congestion there."
    return {"available": True, "depart_at": depart.isoformat(timespec="minutes"), "checked_at": now.isoformat(timespec="seconds"),
            "live": use_cams, "live_note": None if use_cams else _why_not_live(lead),
            "vehicle": {"id": p.id, "label": p.label, "safe_water_depth": p.safe_water_depth},
            "routes": out, "summary": summary, "typical_factor": round(typical, 2),
            "cameras_read": sum(1 for x in readings.values() if x.get("state") == "ok"),
            "cameras_offline": sum(1 for x in readings.values() if x.get("state") == "offline"),
            "camera_job": camera_job,
            "source": {"cameras": cameras.PORTAL_URL, "routes": "Goong Direction v2 (car)"}}


def _camera_subset(clusters, readings) -> tuple[list[str], list[dict]]:
    """At most MAX_JOB_CAMERAS unread cameras: first the Goong route's clusters, one camera each (the nearest that
    the portal does not mark as offline), then the alternatives'. Every other unread camera is dropped, with why."""
    chosen: list[str] = []
    for cls in clusters:
        for cl in cls:
            if any(c["id"] in readings for c in cl):
                continue  # this stretch already has a fresh reading
            usable = [c for c in cl if c.get("status") != "NOT_IMAGE" and c["id"] not in chosen]
            if usable and len(chosen) < cameras.MAX_JOB_CAMERAS:
                chosen.append(usable[0]["id"])
    dropped = []
    for cls in clusters:
        for cl in cls:
            for c in cl:
                if c["id"] in readings or c["id"] in chosen or c["id"] in {d["id"] for d in dropped}:
                    continue
                why = ("camera is offline" if c.get("status") == "NOT_IMAGE"
                       else "another camera already covers this segment in this reading" if any(x["id"] in chosen for x in cl)
                       else f"exceeds the limit of {cameras.MAX_JOB_CAMERAS} cameras per reading")
                dropped.append({"id": c["id"], "name": c["name"], "reason": why})
    return chosen, dropped


def _why_not_live(lead: float) -> str:
    if not flags.enabled("ai_camera_flood"):
        return "AI camera reading is disabled: using flood forecasts only (tides, rain, history)."
    when = "is in the past" if lead < 0 else f"is in {lead / 60:.0f} hours" if lead < 24 * 60 else f"is in {lead / 1440:.0f} days"
    return f"Departure {when}: cameras show current conditions only, so routes use flood forecasts (tides, rain, history)."


def _observe(cls, readings, p, scheduled: set[str] = frozenset()) -> list[dict]:
    """What the cameras of each cluster see: worst confident traffic level and deepest water."""
    out = []
    for cl in cls:
        reads = [readings[c["id"]] for c in cl if c["id"] in readings]
        good = [x for x in reads if x.get("state") == "ok" and x.get("confidence", 0) >= 0.5]
        # Traffic: the lower median of the group, so one camera catching a passing queue does not rate a junction
        # that its neighbours see moving; a real jam shows on most of them. Water: the deepest (safety).
        levels = sorted(cameras.TRAFFIC.index(x["traffic"]) for x in good if x.get("traffic") in cameras.TRAFFIC)
        traffic = cameras.TRAFFIC[levels[(len(levels) - 1) // 2]] if levels else None
        depth = max((x["depth_cm"] for x in good if x.get("depth_cm")), default=0)
        fstat = flood_status(DepthRange(max(0.0, depth / 100 - 0.05), depth / 100 + 0.05, [], False, False),
                             p.safe_water_depth) if depth else None
        # Name the group after the camera that set its rating (deepest water, else one at the group's level).
        reads.sort(key=lambda x: (x in good, x.get("depth_cm") or 0, x.get("traffic") == traffic), reverse=True)
        shown = reads[0] if reads else None
        out.append({"cameras": [cameras.public(x) for x in reads] or
                    [{"id": c["id"], "name": c["name"], "lat": c["lat"], "lon": c["lon"],
                      "image_url": f"/api/cameras/{c['id']}.jpg", "state": "not_read"} for c in cl],
                    "name": (shown or cl[0])["name"], "lat": (shown or cl[0])["lat"], "lon": (shown or cl[0])["lon"],
                    "along_m": cl[0]["along_m"], "traffic": traffic, "traffic_vi": cameras.TRAFFIC_VI.get(traffic), "delay_min": 0,
                    "depth_cm": depth or None, "flood_status": fstat,
                    # read: a fresh reading exists; scheduled: in the running job; unknown: not read this time.
                    "coverage": "read" if reads else "scheduled" if any(c["id"] in scheduled for c in cl) else "unknown",
                    "at": shown and (shown.get("image_time") or shown.get("at") or "")[11:16]})
    return out


def _score(i, r, pts, hotspots, typical, p, depart, rain, snapshot: FloodSnapshot) -> dict:
    reasons: list[tuple[float, str]] = []  # (weight in minutes, text), in route order
    risky, blocked = 0, False
    length, base_min = max(1.0, pts[-1][2]), r["duration_s"] / 60
    seen = [h for h in hotspots if h["traffic"]]
    covered = 0.0
    for k, h in enumerate(seen):  # the stretch each camera speaks for, split halfway with its neighbours
        a = h["along_m"]
        lo = max(0.0, a - COVER_M, (seen[k - 1]["along_m"] + a) / 2 if k else -1)
        hi = min(length, a + COVER_M, (a + seen[k + 1]["along_m"]) / 2 if k + 1 < len(seen) else math.inf)
        covered += max(0.0, hi - lo)
        d = base_min * max(0.0, hi - lo) / length * (TRAFFIC_FACTOR[h["traffic"]] - 1) \
            + TRAFFIC_QUEUE_MIN.get(h["traffic"], 0)
        h["delay_min"] = round(d)
        if h["traffic"] in ("un_u", "ket_cung"):
            reasons.append((d, f"Camera {h['name']} at {h['at']}: {h['traffic_vi'].lower()} (+{d:.0f} min)"))
    rest = base_min * max(0.0, length - covered) / length * (typical - 1)
    delay = sum(h["delay_min"] for h in seen) + rest
    if rest >= 1:
        reasons.append((rest, f"Segments without cameras: general multiplier ×{typical:.1f} (+{rest:.0f} min)"))
    for h in hotspots:
        if h["flood_status"] == "blocked":
            blocked = True
            reasons.append((999, f"Camera {h['name']} at {h['at']}: flooding ~{h['depth_cm']} cm, exceeds vehicle limit "
                                 f"{p.safe_water_depth * 100:.0f} cm"))
        elif h["flood_status"] == "risky":
            risky += 1
            reasons.append((RISKY_FLOOD_MIN, f"Camera {h['name']} at {h['at']}: flooding ~{h['depth_cm']} cm"))
    forecast = _forecast_flood(pts, r, depart, rain, p.safe_water_depth, snapshot)
    for f in forecast:
        depth = f["depth"]
        if f["status"] == "blocked":
            blocked = True
            detail = (f"{depth['lo'] * 100:.0f}–{depth['hi'] * 100:.0f} cm"
                      if depth else "unknown depth")
            reasons.append((999, f"Forecast flooding {detail} at {f['street']} at {_fmt(datetime.fromisoformat(f['at']))}: "
                                 "exceeds the vehicle limit"))
        elif f["status"] == "risky":
            risky += 1
            detail = (f"{depth['lo'] * 100:.0f}–{depth['hi'] * 100:.0f} cm"
                      if depth else f"insufficient data ({f['reason']})")
            reasons.append((RISKY_FLOOD_MIN, f"Forecast {detail} at {f['street']} at "
                                             f"{_fmt(datetime.fromisoformat(f['at']))}"))
    alleys, at = [], 0.0
    for s in r["steps"]:  # alleys at either end are the arrival plan's (or the start's) business
        if s["name"] and ALLEY_NAME.match(s["name"]) and END_M < at < r["distance_m"] - END_M and s["name"] not in alleys:
            alleys.append(s["name"])
        at += s["m"]
    for a in alleys:
        reasons.append((ALLEY_MIN, f"Via {a}: width not checked for this vehicle"))
    eta = base_min + delay + RISKY_FLOOD_MIN * risky + ALLEY_MIN * len(alleys)
    status = "blocked" if blocked else "risky" if risky else "ok"
    return {"id": i, "label": _label(r), "via": r["via"] and {"name": r["via"]["name"], "lat": r["via"]["lat"],
                                                              "lon": r["via"]["lon"]},
            "is_goong": i == 0, "geometry": r["geometry"], "distance_m": r["distance_m"],
            "base_min": round(base_min), "delay_min": round(delay), "eta_min": round(eta), "status": status,
            "hotspots": hotspots, "flood_forecast": forecast, "alleys": alleys,
            "traffic_unknown": sum(1 for h in hotspots if h["traffic"] is None),
            "reasons": [t for _, t in reasons], "top_reason": max(reasons)[1] if reasons else None,
            "cameras_on_route": sum(len(h["cameras"]) for h in hotspots), "chosen": False}


def _summary(best: dict, goong: dict, routes: list[dict]) -> str:
    if best["status"] == "blocked":
        return "All routes have flooding above the vehicle limit. Consider changing departure time."
    if best is goong:
        others = [x for x in routes if x is not best]
        gap = min((x["eta_min"] for x in others), default=best["eta_min"]) - best["eta_min"]
        tail = f" Other routes are at least {gap} min slower." if gap > 0 else \
            " Another route is equally fast." if others else ""
        return f"Take the Goong suggestion ({best['label']}), about {best['eta_min']} min.{tail}"
    why = goong["top_reason"] or "this route is faster"
    gain = goong["eta_min"] - best["eta_min"]
    lead = f"about {gain} min faster than the Goong suggestion" if gain > 0 else "avoids adverse conditions on the Goong route"
    if goong["status"] == "blocked":
        lead = "the Goong suggestion is flooded"
    return f"Recommended: {best['label']} (~{best['eta_min']} min), {lead}. Reason: {why}."
