"""Flood evidence → Depth Range per way over a Dwell Window (Q12, Q13, D14).

History (IRD 2002–2026) says *which* streets flood when the tide or rain reaches a
level; the tide and rain (measured, then forecast: hydro.py, D35) say *whether* that happens during the stay.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from functools import lru_cache

from . import flags, hydro
from .config import DATA, FLOOD_REPORT_VALID_H, MOVING_WATER_BLOCK_M
from .config import STORE as ROOT_STORE
from .osm import AreaGraph, haversine, strip_accents

IRD_FILE = DATA / "flood" / "ird-hcmc" / "flood_points.geojson"
TIDE_FILE = DATA / "flood" / "tide_forecast.json"
IRD_URL = "https://doi.org/10.23708/8Y16HU"

_FILE_GENERATIONS: dict[str, tuple[int, int, str]] = {}


def _file_generation(path) -> str:
    """Content generation with a cheap stat fast path; changed inputs invalidate process caches."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return "missing"
    key = str(path)
    cached = _FILE_GENERATIONS.get(key)
    marker = (stat.st_mtime_ns, stat.st_size)
    if cached and cached[:2] == marker:
        return cached[2]
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    _FILE_GENERATIONS[key] = (*marker, digest)
    return digest


def evidence_generation() -> tuple[str, str]:
    """Generation of the historical and tide inputs used by cached profiles."""
    return _file_generation(IRD_FILE), _file_generation(TIDE_FILE)


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


def load_records() -> list[FloodRecord]:
    return list(_load_records(_file_generation(IRD_FILE)))


@lru_cache(maxsize=4)
def _load_records(generation: str) -> tuple[FloodRecord, ...]:
    del generation
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
    return tuple(out)


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
    record_keys = [_street_key(record.street) for record in recs]
    by_street: dict[str, list[int]] = {}
    spatial: dict[tuple[int, int], list[int]] = {}
    cell_size = 0.001  # ~111 m latitude and ~108 m longitude in HCMC
    for idx, record in enumerate(recs):
        if record_keys[idx]:
            by_street.setdefault(record_keys[idx], []).append(idx)
        cell = (math.floor(record.lat / cell_size), math.floor(record.lon / cell_size))
        spatial.setdefault(cell, []).append(idx)

    profiles: dict[int, FloodProfile] = {}
    for w in g.ways.values():
        if not w.drivable and not w.walkable:
            continue
        key = _street_key(w.name)
        pts = [g.nodes[n] for n in w.nodes[:: max(1, len(w.nodes) // 8)]]
        if pts[-1] != g.nodes[w.nodes[-1]]:
            pts.append(g.nodes[w.nodes[-1]])
        candidates = set(by_street.get(key, ())) if key else set()
        for lat, lon in pts:
            row, col = math.floor(lat / cell_size), math.floor(lon / cell_size)
            for dy in range(-2, 3):
                for dx in range(-2, 3):
                    candidates.update(spatial.get((row + dy, col + dx), ()))
        hits = []
        for idx in candidates:
            record = recs[idx]
            d = min(haversine(record.lat, record.lon, lat, lon) for lat, lon in pts)
            same_street = bool(key and key == record_keys[idx])
            if ((record.precision == "high" and d <= 50)
                    or (record.precision == "medium" and d <= 120 and (same_street or d <= 40))
                    or (same_street and d <= 700)):
                hits.append(record)
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


# ---- tide -----------------------------------------------------------------------

def tide_meta() -> dict:
    """Return current tide metadata, invalidating when the source file changes."""
    return _tide_meta(_file_generation(TIDE_FILE))


@lru_cache(maxsize=4)
def _tide_meta(generation: str) -> dict:
    del generation
    return json.loads(TIDE_FILE.read_text(encoding="utf-8"))


def _extremes() -> list[tuple[datetime, float]]:
    return list(_cached_extremes(_file_generation(TIDE_FILE)))


@lru_cache(maxsize=4)
def _cached_extremes(generation: str) -> tuple[tuple[datetime, float], ...]:
    meta = _tide_meta(generation)
    highs = [(datetime.fromisoformat(h["t"]), h["level_m"]) for h in meta["highs"]]
    if meta.get("lows"):
        return tuple(sorted(highs + [(datetime.fromisoformat(h["t"]), h["level_m"]) for h in meta["lows"]]))
    out = []
    for (t1, l1), (t2, _) in zip(highs, highs[1:]):
        out.append((t1, l1))
        out.append((t1 + (t2 - t1) / 2, meta["low_level_m"]))
    if highs:
        out.append(highs[-1])
    return tuple(out)


def _bulletin_level_from(t: datetime, extremes: tuple[tuple[datetime, float], ...]) -> float | None:
    if not extremes:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=extremes[0][0].tzinfo)
    for (t1, l1), (t2, l2) in zip(extremes, extremes[1:]):
        if t1 <= t <= t2:
            f = (t - t1) / (t2 - t1)
            return l1 + (l2 - l1) * (1 - math.cos(math.pi * f)) / 2
    return None


def _select_tide(t, live, bulletin, metadata):
    if live is None:
        return (bulletin, "bulletin") if bulletin is not None else None
    if live[1] == "measured" or bulletin is None:
        return live
    # A refreshed official forecast supersedes a model fetched before that bulletin.
    issued = metadata.get("issued_at")
    model_fetched = hydro._cache.get("marine", (0, None))[0]
    if issued and model_fetched and datetime.fromisoformat(issued).timestamp() > model_fetched:
        return bulletin, "bulletin"
    return live


def tide_point(t: datetime) -> tuple[float, str] | None:
    """Phú An level at t and how it is known: measured, model, or shipped bulletin."""
    live = hydro.tide_point(t) if flags.enabled("live_hydro") else None
    return _select_tide(t, live, _bulletin_level(t), tide_meta())


def tide_level(t: datetime) -> float | None:
    tp = tide_point(t)
    return tp[0] if tp else None


def _bulletin_level(t: datetime) -> float | None:
    return _bulletin_level_from(t, tuple(_extremes()))


def tide_series(start: datetime, hours: int = 48, step_min: int = 15) -> list[dict]:
    out, t = [], start
    while t <= start + timedelta(hours=hours):
        tp = tide_point(t)
        if tp is not None:
            out.append({"t": t.isoformat(), "level_m": round(tp[0], 3), "kind": tp[1]})
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

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": round(self.hi, 2), "drivers": self.drivers,
                "rain_driven": self.rain_driven, "inferred": self.inferred}


def rain_rate(t: datetime, scenario: list[dict]) -> float:
    rate = 0.0  # spells overlap once measured hours drain: the wettest one counts
    for s in scenario or []:
        a, b = datetime.fromisoformat(s["start"]), datetime.fromisoformat(s["end"])
        if a.tzinfo is None and t.tzinfo is not None:
            a, b = a.replace(tzinfo=t.tzinfo), b.replace(tzinfo=t.tzinfo)
        if a <= t <= b:
            rate = max(rate, float(s["mm_per_h"]))
    return rate


def _tide_depth(level: float, p: FloodProfile, metadata: dict | None = None) -> tuple[float, float] | None:
    a = (metadata or tide_meta())["alarm_levels_m"]
    if level >= a["BD3"]:
        return 0.15, max(0.30, p.depth_pct(0.75, "tide", "combined") or 0)
    if level >= a["BD2"]:
        return 0.05, 0.20
    if level >= a["BD1"]:
        return 0.0, 0.10
    return None


LIVE_FILE = ROOT_STORE / "live_flood_reports.jsonl"
_FEATURE_OF_SOURCE = {"photo": "ai_photo_evidence", "camera": "ai_camera_flood"}
STATUS_ORDER = {"passable": 0, "risky": 1, "blocked": 2}
KNOWLEDGE_ORDER = {"known": 0, "missing_history": 1, "missing_rain": 2, "missing_tide": 2,
                   "stale_positive_observation": 3}


def _usable_report(r) -> dict | None:
    """A report the snapshot can always read: ISO `observed_at` and a finite `depth_cm` (or none).

    One malformed approved report must never take down every plan, so it is skipped instead.
    """
    if not isinstance(r, dict) or not isinstance(r.get("observed_at"), str):
        return None
    try:
        datetime.fromisoformat(r["observed_at"])
        depth = r.get("depth_cm")
        if depth is not None:
            depth = float(depth)
            if not math.isfinite(depth):
                return None
    except (TypeError, ValueError):
        return None
    return {**r, "depth_cm": depth}


def live_reports() -> list[dict]:
    """Accepted observations. A request snapshots this list before evaluating any times."""
    if not LIVE_FILE.exists():
        return []
    out = []
    for line in LIVE_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = _usable_report(json.loads(line))
        except ValueError:
            r = None  # a torn line from an interrupted append
        if r is None:
            continue
        if flags.enabled(_FEATURE_OF_SOURCE.get(r.get("source"), "ai_text_rules")) and r.get("observed_at"):
            out.append(r)
    return out


@dataclass
class FloodAssessment:
    status: str
    depth: DepthRange | None
    knowledge: str
    reason: str | None
    freshness: dict | None
    at: datetime | None = None
    source: str | None = None

    def to_json(self) -> dict:
        return {"status": self.status, "depth": self.depth.to_json() if self.depth else None,
                "knowledge": self.knowledge, "reason": self.reason, "freshness": self.freshness}


def _as_time(value: str, like: datetime) -> datetime:
    t = datetime.fromisoformat(value)
    if t.tzinfo is None and like.tzinfo is not None:
        t = t.replace(tzinfo=like.tzinfo)
    return t


class FloodSnapshot:
    """Request-scoped immutable evidence plus memoized assessments for all timing probes."""

    def __init__(self, rain_scenario: list[dict] | None = None, reports: list[dict] | None = None,
                 rain_known_until: datetime | None = None):
        self.rain = tuple(dict(s) for s in (rain_scenario or []))
        # None: the rain scenario is authoritative for every time. Otherwise rain is only known
        # up to this instant (end of live gauge/forecast coverage); later times are missing_rain.
        self.rain_known_until = rain_known_until
        self.reports = tuple(r for r in (_usable_report(r) for r in (live_reports() if reports is None else reports))
                             if r is not None)
        self.generations = evidence_generation()
        self.tide_metadata = _tide_meta(self.generations[1])
        self.tide_extremes = _cached_extremes(self.generations[1])
        self._tides: dict[datetime, tuple[float, str] | None] = {}
        self._depths: dict[tuple[object, datetime, str, float], FloodAssessment] = {}
        # Index reports by normalized street key to avoid repeated accent-stripping scans
        self._reports_by_street: dict[str, list[dict]] = {}
        for report in self.reports:
            key = _street_key(report.get("street", ""))
            if key:
                if key not in self._reports_by_street:
                    self._reports_by_street[key] = []
                self._reports_by_street[key].append(report)

    def tide_at(self, t: datetime) -> tuple[float, str] | None:
        if t not in self._tides:
            live = hydro.tide_point(t) if flags.enabled("live_hydro") else None
            self._tides[t] = _select_tide(t, live, _bulletin_level_from(t, self.tide_extremes), self.tide_metadata)
        return self._tides[t]

    def latest_observation(self, name: str, t: datetime) -> tuple[dict, datetime] | None:
        key = _street_key(name)
        latest = None
        if not key:
            return None
        for report in self._reports_by_street.get(key, []):
            if report.get("depth_cm") is None:
                continue
            seen = _as_time(report["observed_at"], t)
            if seen > t:  # future observations are never an oracle for an earlier request.
                continue
            if latest is None or seen > latest[1]:
                latest = report, seen
        return latest

    def latest_valid_observation(self, name: str, t: datetime) -> tuple[dict, datetime] | None:
        """Return the latest observation that is still valid at time t."""
        key = _street_key(name)
        latest_valid = None
        if not key:
            return None
        for report in self._reports_by_street.get(key, []):
            if report.get("depth_cm") is None:
                continue
            seen = _as_time(report["observed_at"], t)
            if seen > t:  # future observations are never an oracle for an earlier request.
                continue
            valid_until = seen + timedelta(hours=FLOOD_REPORT_VALID_H)
            if t <= valid_until:  # still valid at t
                if latest_valid is None or seen > latest_valid[1]:
                    latest_valid = report, seen
        return latest_valid

    def last_positive_observation(self, name: str, t: datetime) -> tuple[dict, datetime] | None:
        """Return the last positive (flooded) observation, regardless of expiry, if no valid dry newer than it."""
        key = _street_key(name)
        last_positive = None
        last_valid = self.latest_valid_observation(name, t)
        if not key:
            return None
        for report in self._reports_by_street.get(key, []):
            if report.get("depth_cm") is None:
                continue
            seen = _as_time(report["observed_at"], t)
            if seen > t:
                continue
            depth = float(report["depth_cm"]) / 100
            if depth > 0:  # positive observation
                if last_positive is None or seen > last_positive[1]:
                    last_positive = report, seen
        # Only return the last positive if there is no newer valid observation
        if last_positive and last_valid and last_valid[1] > last_positive[1]:
            return None  # a newer valid observation exists, so stale positive is cleared
        return last_positive

    def sample_times(self, start: datetime, end: datetime) -> list[datetime]:
        if end < start:
            start, end = end, start
        points = {start, end}
        for t, _ in self.tide_extremes:
            if t.tzinfo is None and start.tzinfo is not None:
                t = t.replace(tzinfo=start.tzinfo)
            if start <= t <= end:
                points.add(t)
        for report in self.reports:
            if not report.get("observed_at"):
                continue
            seen = _as_time(report["observed_at"], start)
            expires = seen + timedelta(hours=FLOOD_REPORT_VALID_H)
            if start <= seen <= end:
                points.add(seen)
            if start <= expires <= end:
                points.add(expires)
        for spell in self.rain:
            try:
                spell_start = _as_time(spell.get("start"), start)
                spell_end = _as_time(spell.get("end"), start)
                if start <= spell_start <= end:
                    points.add(spell_start)
                if start <= spell_end <= end:
                    points.add(spell_end)
            except (ValueError, TypeError, KeyError):
                pass  # skip malformed rain spells
        return sorted(points)

    def assess(self, p: FloodProfile | None, t: datetime, safe_depth: float, name: str = "") -> FloodAssessment:
        profile_key = None
        if p is not None:
            profile_key = (
                p.inferred_from,
                tuple((record.lat, record.lon, record.street, record.year, record.date,
                       record.cause, record.depth_max_cm, record.precision, record.source)
                      for record in p.records))
        key = (profile_key, t, _street_key(name), safe_depth)
        if key not in self._depths:
            self._depths[key] = _assess_at(p, t, list(self.rain), safe_depth, name, self)
        return self._depths[key]


def flood_status(d: DepthRange | None, safe_depth: float) -> str:
    if d is None:
        return "passable"
    if d.rain_driven and d.lo >= MOVING_WATER_BLOCK_M:
        return "blocked"
    if d.lo >= safe_depth:
        return "blocked"
    if d.hi >= safe_depth or (d.rain_driven and d.hi >= MOVING_WATER_BLOCK_M):
        return "risky"
    return "passable"


def _assess_at(p: FloodProfile | None, t: datetime, rain_scenario: list[dict], safe_depth: float,
               name: str, snapshot: FloodSnapshot) -> FloodAssessment:
    tp = snapshot.tide_at(t)
    rain = rain_rate(t, rain_scenario)
    lo = hi = 0.0
    drivers: list[str] = []
    rain_driven = False
    freshness = None
    source = None

    observation = snapshot.latest_observation(name, t)
    stale_positive = False
    fresh_dry = False
    if observation:
        report, seen = observation
        valid_until = seen + timedelta(hours=FLOOD_REPORT_VALID_H)
        depth = float(report["depth_cm"]) / 100
        if t <= valid_until:
            source = report.get("source", "text")
            freshness = {"observed_at": seen.isoformat(), "valid_until": valid_until.isoformat(),
                         "source": source}
            if depth > 0:
                lo, hi = max(lo, depth), max(hi, depth + 0.05)
                drivers.append(f"Báo ngập {depth * 100:.0f} cm lúc {seen.strftime('%H:%M')} ({source})")
            else:
                fresh_dry = True

    # An expired dry report is not evidence that an older positive report has cleared.
    # Only a newer still-valid observation clears last_positive_observation().
    stale = snapshot.last_positive_observation(name, t)
    if stale:
        stale_report, stale_seen = stale
        stale_until = stale_seen + timedelta(hours=FLOOD_REPORT_VALID_H)
        if t > stale_until:
            stale_positive = True
            source = stale_report.get("source", "text")
            freshness = {"observed_at": stale_seen.isoformat(),
                         "valid_until": stale_until.isoformat(), "source": source}

    tide_needed = bool(p and p.count("tide", "combined"))
    if tide_needed and tp is not None:
        level, kind = tp
        err = hydro.TIDE_MODEL_ERR_M if kind == "model" else 0.0
        high = _tide_depth(level + err, p, snapshot.tide_metadata)
        low = _tide_depth(level - err, p, snapshot.tide_metadata)
        if high:
            lo, hi = max(lo, low[0] if low else 0.0), max(hi, high[1])
            how = {"measured": "đo", "model": f"mô hình ±{err * 100:.0f} cm", "bulletin": "bản tin"}[kind]
            drivers.append(f"Triều {level:.2f} m ({alarm_label(level) or 'dưới BĐ1'}, {how})")
        if freshness is None:
            freshness = {"source": kind}
            source = kind
    if rain >= 10 and p and p.count("rain", "combined"):
        if rain >= 60:
            rlo, rhi = 0.20, max(0.50, p.depth_pct(1.0, "rain", "combined") or 0)
        elif rain >= 30:
            rlo, rhi = 0.10, max(0.30, p.depth_pct(0.5, "rain", "combined") or 0)
        else:
            rlo, rhi = 0.0, 0.15
        if drivers:
            rlo, rhi = rlo + 0.1, rhi + 0.1
        lo, hi = max(lo, rlo), max(hi, rhi)
        rain_driven = True
        drivers.append(f"Mưa {rain:g} mm/h")
        source = source or "rain"

    depth = DepthRange(lo, hi, drivers, rain_driven, bool(p and p.inferred_from)) if hi > 0 else None
    status = flood_status(depth, safe_depth)
    if stale_positive:
        knowledge = "stale_positive_observation"
        reason = "Báo ngập dương tính gần nhất đã hết hạn và chưa có quan sát khô mới hơn"
    elif tide_needed and tp is None:
        knowledge = "missing_tide"
        reason = "Không có dữ liệu triều hợp lệ tại thời điểm này"
    elif (p and p.count("rain", "combined") and snapshot.rain_known_until is not None
          and t > snapshot.rain_known_until):
        knowledge = "missing_rain"
        reason = "Không có dữ liệu mưa (đo hoặc dự báo) tại thời điểm này"
    elif p is None and not fresh_dry and depth is None:
        knowledge = "missing_history"
        reason = "Không có lịch sử ngập hoặc quan sát hiện thời cho đoạn đường"
    else:
        knowledge = "known"
        reason = None
    if knowledge != "known" and status == "passable":
        status = "risky"
    return FloodAssessment(status, depth, knowledge, reason, freshness, t, source)


def depth_at(p: FloodProfile | None, t: datetime, rain_scenario: list[dict], name: str = "",
             safe_depth: float = float("inf"), snapshot: FloodSnapshot | None = None) -> FloodAssessment:
    """Assess one way at one time. Missing evidence is explicit and never represented as zero depth."""
    snap = snapshot or FloodSnapshot(rain_scenario)
    return snap.assess(p, t, safe_depth, name)


def worst_over(p: FloodProfile | None, times: list[datetime], rain: list[dict], safe: float, name: str = "",
               snapshot: FloodSnapshot | None = None) -> FloodAssessment:
    """Worst assessment without attributing one sample's uncertainty to another sample."""
    snap = snapshot or FloodSnapshot(rain)
    assessments = [snap.assess(p, t, safe, name) for t in sorted(set(times))]
    if not assessments:
        return FloodAssessment("risky", None, "missing_history", "Không có thời điểm để kiểm tra", None)
    decisive = max(assessments, key=lambda a: (STATUS_ORDER[a.status],
                                               a.depth.hi if a.depth else -1.0))
    unknown = max(assessments, key=lambda a: KNOWLEDGE_ORDER[a.knowledge])
    if unknown.knowledge != "known" and unknown is not decisive:
        return FloodAssessment(
            decisive.status, decisive.depth, unknown.knowledge,
            "Một hoặc nhiều thời điểm chưa có bằng chứng ngập đầy đủ",
            None, None, None)
    return decisive
