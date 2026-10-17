"""Flood evidence → Depth Range per way over a Dwell Window (Q12, Q13, D14).

History (IRD 2002–2026) says *which* streets flood when the tide or rain reaches a
level; the tide forecast and rain scenario say *whether* that happens during the stay.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache, wraps
from contextvars import ContextVar

from . import flags
from .config import DATA, MOVING_WATER_BLOCK_M
from .config import STORE as ROOT_STORE
from .osm import AreaGraph, haversine, strip_accents

IRD_FILE = DATA / "flood" / "ird-hcmc" / "flood_points.geojson"
TIDE_FILE = DATA / "flood" / "tide_forecast.json"
IRD_URL = "https://doi.org/10.23708/8Y16HU"


def _street_key(name: str) -> str:
    s = strip_accents(name or "")
    for p in ("duong ", "d. ", "pho "):
        if s.startswith(p):
            s = s[len(p):]
    return s.split(" - ")[0].split("(")[0].strip()


@dataclass
class FloodRecord:
    lat: float
    lon: float
    street: str
    year: int | None
    date: str
    cause: str
    depth_max_cm: float | None
    precision: str
    source: str

    def to_json(self) -> dict:
        return {"street": self.street, "year": self.year, "date": self.date, "cause": self.cause,
                "depth_max_cm": self.depth_max_cm, "precision": self.precision, "source": self.source,
                "dataset": "IRD – Historical database of urban flooding in HCMC 2002–2026", "url": IRD_URL}


@lru_cache(maxsize=1)
def load_records() -> list[FloodRecord]:
    g = json.loads(IRD_FILE.read_text(encoding="utf-8"))
    out = []
    for f in g["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        prec = (p.get("Spatial_precision") or "").strip().lower()
        prec = {"hugh": "high", "hgh": "high"}.get(prec, prec)
        cause = (p.get("Cause") or "").strip().lower()
        cause = "tide" if "tide" in cause else "rain" if "rain" in cause else "combined" if cause else "unknown"
        out.append(FloodRecord(lat, lon, (p.get("Location_name") or "").strip(), p.get("Year"),
                               str(p.get("Date") or ""), cause, p.get("Water_height_max_cm"), prec,
                               (p.get("Source_type") or "").strip()))
    return out


@dataclass
class FloodProfile:
    records: list[FloodRecord] = field(default_factory=list)
    inferred_from: str = ""  # set when the profile is borrowed from an adjoining flooded street

    def count(self, *causes) -> int:
        return sum(1 for r in self.records if r.cause in causes)

    def depth_pct(self, q: float, *causes) -> float | None:
        if not flags.enabled("ai_flood_prior"):
            return None  # without the learned prior, only the official fixed ranges apply
        ds = sorted(r.depth_max_cm for r in self.records if r.depth_max_cm and (not causes or r.cause in causes))
        if not ds:
            return None
        return ds[min(len(ds) - 1, int(q * len(ds)))] / 100


def flood_profiles(g: AreaGraph) -> dict[int, FloodProfile]:
    recs = [r for r in load_records()
            if haversine(g.center[0], g.center[1], r.lat, r.lon) < 3000]
    profiles: dict[int, FloodProfile] = {}
    for w in g.ways.values():
        if not w.drivable and not w.walkable:
            continue
        key = _street_key(w.name)
        pts = [g.nodes[n] for n in w.nodes[:: max(1, len(w.nodes) // 8)]] + [g.nodes[w.nodes[-1]]]
        hits = []
        for r in recs:
            d = min(haversine(r.lat, r.lon, la, lo) for la, lo in pts)
            same_street = key and key == _street_key(r.street)
            if (r.precision == "high" and d <= 50) or (r.precision == "medium" and d <= 120 and (same_street or d <= 40)) \
                    or (same_street and d <= 700):
                hits.append(r)
        if hits:
            profiles[w.id] = FloodProfile(hits)
    # Alleys that open onto a flooded street share its water near the mouth (inferred, part of the prior).
    if not flags.enabled("ai_flood_prior"):
        return profiles
    flooded_nodes = {n: wid for wid in profiles for n in g.ways[wid].nodes}
    for w in g.ways.values():
        if w.id in profiles or w.kind not in ("alley", "residential", "service"):
            continue
        for n in w.nodes:
            wid = flooded_nodes.get(n)
            if wid:
                parent = g.ways[wid]
                profiles[w.id] = FloodProfile(profiles[wid].records,
                                              inferred_from=parent.name or f"way {wid}")
                break
    return profiles


_REQUEST = ContextVar('engine_flood_request', default=None)


def request_cache(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        if _REQUEST.get() is not None:
            return function(*args, **kwargs)
        token = _REQUEST.set({})
        try:
            return function(*args, **kwargs)
        finally:
            _REQUEST.reset(token)
    return wrapped


def _memo_depth(function):
    @wraps(function)
    def wrapped(p,t,rain_scenario,name=''):
        cache=_REQUEST.get()
        if cache is None:
            return function(p,t,rain_scenario,name)
        key=('depth',id(p),t,tuple((s['start'],s['end'],s['mm_per_h']) for s in rain_scenario),name)
        if key not in cache:
            cache[key]=function(p,t,rain_scenario,name)
        return cache[key]
    return wrapped


# ---- tide -----------------------------------------------------------------------

@lru_cache(maxsize=1)
def tide_meta() -> dict:
    return json.loads(TIDE_FILE.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _extremes() -> list[tuple[datetime, float]]:
    meta = tide_meta()
    highs = [(datetime.fromisoformat(h["t"]), h["level_m"]) for h in meta["highs"]]
    if meta.get("lows"):
        # Official unequal lows and a missing high (ct) must not become invented -1.9 m troughs.
        return sorted(highs + [(datetime.fromisoformat(h["t"]), h["level_m"]) for h in meta["lows"]])
    out = []
    for (t1, l1), (t2, _) in zip(highs, highs[1:]):
        out.append((t1, l1))
        out.append((t1 + (t2 - t1) / 2, meta["low_level_m"]))
    out.append(highs[-1])
    return out


def tide_level(t: datetime) -> float | None:
    ex = _extremes()
    if t.tzinfo is None:
        t = t.replace(tzinfo=ex[0][0].tzinfo)
    for (t1, l1), (t2, l2) in zip(ex, ex[1:]):
        if t1 <= t <= t2:
            f = (t - t1) / (t2 - t1)
            return l1 + (l2 - l1) * (1 - math.cos(math.pi * f)) / 2
    return None


def tide_series(start: datetime, hours: int = 48, step_min: int = 15) -> list[dict]:
    out, t = [], start
    while t <= start + timedelta(hours=hours):
        lvl = tide_level(t)
        if lvl is not None:
            out.append({"t": t.isoformat(), "level_m": round(lvl, 3)})
        t += timedelta(minutes=step_min)
    return out


def alarm_label(level: float | None) -> str | None:
    if level is None:
        return None
    a = tide_meta()["alarm_levels_m"]
    if level >= a["BD3"]:
        return "BĐ3"
    if level >= a["BD2"]:
        return "BĐ2"
    if level >= a["BD1"]:
        return "BĐ1"
    return None


# ---- depth ----------------------------------------------------------------------

@dataclass
class DepthRange:
    lo: float
    hi: float
    drivers: list[str]
    rain_driven: bool
    inferred: bool
    known: bool = True
    unknown_reasons: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2) if self.known else None,
                "hi": round(self.hi, 2) if self.known else None, "drivers": self.drivers,
                "rain_driven": self.rain_driven, "inferred": self.inferred,
                "known": self.known, "unknown_reasons": self.unknown_reasons}


def rain_rate(t: datetime, scenario: list[dict]) -> float:
    rates = [0.0]
    for s in scenario or []:
        a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
        if a.tzinfo is None and t.tzinfo is not None:
            a, b = a.replace(tzinfo=t.tzinfo), b.replace(tzinfo=t.tzinfo)
        if a <= t <= b:
            rates.append(max(0.0, float(s["mm_per_h"])))
    return max(rates)


RAIN_RETENTION_MIN = 60  # explicit conservative scenario assumption; not a calibrated recession model


def _retained_rain(t, scenario):
    rates = [rain_rate(t, scenario)]
    for s in scenario or []:
        end = datetime.fromisoformat(s['end'])
        if end.tzinfo is None:
            end = end.replace(tzinfo=t.tzinfo)
        if end < t <= end + timedelta(minutes=RAIN_RETENTION_MIN):
            rates.append(max(0.0, float(s['mm_per_h'])))
    return max(rates)


def evaluation_times(start, end, rain):
    """All discontinuities and tide extrema, plus a bounded grid for diagnostics."""
    if end < start:
        raise ValueError('Dwell end precedes arrival')
    out = {start, end}
    out.update(t for t, _ in _extremes() if start <= t <= end)
    for s in rain or []:
        a, b = datetime.fromisoformat(s['start']), datetime.fromisoformat(s['end'])
        if a.tzinfo is None:
            a, b = a.replace(tzinfo=start.tzinfo), b.replace(tzinfo=start.tzinfo)
        if b < a or float(s['mm_per_h']) < 0:
            raise ValueError('Invalid rain interval')
        for t in (a, b, b+timedelta(minutes=RAIN_RETENTION_MIN)):
            for candidate in (t-timedelta(microseconds=1),t,t+timedelta(microseconds=1)):
                if start <= candidate <= end:
                    out.add(candidate)
    return sorted(out)


LIVE_FILE = ROOT_STORE / "live_flood_reports.jsonl"
_FEATURE_OF_SOURCE = {"photo": "ai_photo_evidence", "camera": "ai_camera_flood"}


def _read_live_reports() -> list[dict]:
    """Accepted flood-now reports from the AI features, each honouring its own flag."""
    if not LIVE_FILE.exists():
        return []
    out = []
    for line in LIVE_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if flags.enabled(_FEATURE_OF_SOURCE.get(r.get("source"), "ai_text_rules")) and r.get("observed_at"):
            out.append(r)
    return out


def live_reports():
    cache=_REQUEST.get()
    if cache is None:
        return _read_live_reports()
    if 'live_reports' not in cache:
        cache['live_reports']=_read_live_reports()
    return cache['live_reports']


def _live_bound(name: str, t: datetime):
    key = _street_key(name)
    if not key:
        return None
    best = None
    for r in live_reports():
        if _street_key(r.get("street", "")) != key or r.get("depth_cm") is None:
            continue
        seen = datetime.fromisoformat(r["observed_at"])
        if seen.tzinfo is None and t.tzinfo is not None:
            seen = seen.replace(tzinfo=t.tzinfo)
        if abs((t - seen).total_seconds()) <= 2 * 3600:
            d = float(r["depth_cm"]) / 100
            if best is None or d > best[0]:
                best = (d, r)
    return best


@_memo_depth
def depth_at(p: FloodProfile | None, t: datetime, rain_scenario: list[dict], name: str = "") -> DepthRange | None:
    level = tide_level(t)
    rain = _retained_rain(t, rain_scenario)
    lo = hi = 0.0
    drivers: list[str] = []
    rain_driven = False
    unknown = []
    if p is None or not p.records:
        unknown.append("Chưa có hồ sơ đáp ứng ngập của đoạn đường")
    if p and p.count("tide", "combined") and level is None:
        unknown.append("Ngoài thời hạn dự báo triều")
    live = _live_bound(name, t) if name else None
    if live:
        d, r = live
        lo, hi = max(lo, max(0.0, d - 0.05)), max(hi, d + 0.05)
        drivers.append(f"Báo ngập {d * 100:.0f} cm lúc {r['observed_at'][11:16]} ({r.get('source', 'văn bản')})")
    if p and p.count("tide", "combined") and level is not None and level >= tide_meta()["alarm_levels_m"]["BD1"]:
        a = tide_meta()["alarm_levels_m"]
        if level >= a["BD3"]:
            tlo, thi = 0.15, max(0.30, p.depth_pct(0.75, "tide", "combined") or 0)
        elif level >= a["BD2"]:
            tlo, thi = 0.05, 0.20
        else:
            tlo, thi = 0.0, 0.10
        lo, hi = max(lo, tlo), max(hi, thi)
        drivers.append(f"Triều {level:.2f} m ({alarm_label(level)})")
    if rain >= 10:
        if p and p.count("rain", "combined"):
            if rain >= 60:
                rlo, rhi = 0.20, max(0.50, p.depth_pct(1.0, "rain", "combined") or 0)
            elif rain >= 30:
                rlo, rhi = 0.10, max(0.30, p.depth_pct(0.5, "rain", "combined") or 0)
            else:
                rlo, rhi = 0.0, 0.15
            if any(d.startswith("Triều ") for d in drivers):
                rlo, rhi = rlo + 0.1, rhi + 0.1
            lo, hi = max(lo, rlo), max(hi, rhi)
            rain_driven = True
            drivers.append(f"Mưa {rain:g} mm/h")
        elif rain >= 60:
            rain_driven = True
            unknown.append("Chưa biết độ sâu ứng với mưa lớn tại đoạn này")
            drivers.append(f"Mưa {rain:g} mm/h (chưa có ghi nhận ngập ở đoạn này)")
    if rain > rain_rate(t, rain_scenario):
        drivers.append("Giả định nước mưa lưu lại 60 phút; chưa hiệu chuẩn thời gian rút")
    return DepthRange(lo, hi, drivers, rain_driven, bool(p and p.inferred_from), not unknown, unknown)


STATUS_ORDER = {"passable": 0, "unknown": 1, "risky": 2, "blocked": 3}


def flood_status(d: DepthRange | None, safe_depth: float) -> str:
    if d is None:
        return "unknown"
    if d.rain_driven and d.hi >= MOVING_WATER_BLOCK_M:
        return "blocked"
    if d.lo >= safe_depth:
        return "blocked"
    if not d.known:
        return "unknown"
    if d.hi >= safe_depth or (d.rain_driven and d.hi >= MOVING_WATER_BLOCK_M):
        return "risky"
    return "passable"


def worst_over(p: FloodProfile | None, times: list[datetime], rain: list[dict], safe: float, name: str = ""):
    """Worst Flood Status over a set of times, with the depth that caused it."""
    worst, worst_d, worst_t = "passable", None, None
    if not times:
        return "unknown", None, None
    times = sorted(set(times) | set(evaluation_times(min(times), max(times), rain)))
    for t in times:
        d = depth_at(p, t, rain, name)
        s = flood_status(d, safe)
        if (STATUS_ORDER[s], d.hi if d else -1) > (STATUS_ORDER[worst], worst_d.hi if worst_d else -1):
            worst, worst_d, worst_t = s, d, t
    return worst, worst_d, worst_t
