"""Access Evidence → Width Range per way (Q10, Q11).

Every source becomes a bound on Clear Width with an Evidence Tier. Tiers are
combined strongest-first: the highest tier present sets the range, lower tiers
may only narrow it, and a conflict inside one tier is flagged for review.
"""
from __future__ import annotations

import csv
import json
import math
import re
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from functools import lru_cache

from . import flags, vehicles, footprints, declared_index, official_widths
from .config import DATA, STORE
from .osm import AreaGraph, Way, strip_accents

SYNTHETIC_DEMO_TIER = "Synthetic"
SYNTHETIC_DEMO_WIDTH_BASIS = "synthetic_demo_width"
TIERS = ["Measured", SYNTHETIC_DEMO_TIER, "Official", "Observed", "Declared", "Inferred"]
TIER_VI = {"Synthetic": "Synthetic demo", "Measured": "Measured", "Official": "Official",
           "Observed": "Observed", "Declared": "Declared", "Inferred": "Inferred"}
OPEN_HI = 40.0
WIDTH_BASES = frozenset({
    SYNTHETIC_DEMO_WIDTH_BASIS, "measured_clear_width", "observed_clear_width", "parcel_gap_estimate",
    "road_width_estimate", "declared_width", "inferred", "unknown",
})

LISTINGS_FILE = DATA / "processed" / "listings_evidence_binhthanh.json"
FIELD_FILE = DATA / "field" / "measurements.csv"
PARCEL_FILE = DATA / "official" / "parcel_gaps.csv"
GAPS_FILE = DATA / "processed" / "building_gaps_hcmc.json"
FIRE_FILE = DATA / "official" / "fire_access_4582.json"
FIRE_TRUCK_MIN = 3.5  # QCVN 06:2022/BXD clear width for a fire-truck road
# The building-to-building gap overstates Clear Width (steps, awnings, motorbikes): the upper bound adds the
# footprint error, the lower bound removes a typical encroachment from the narrower quarter of the samples.
GAP_FOOTPRINT_ERR = 0.8
GAP_ENCROACH = 1.2
from .reports import BLOCKAGE_FILE, CONFIRM_FILE  # noqa: E402  approved projections of reviewed reports


# English output adapter for descriptions supplied by cached/neighboring modules.
# Keep this block centralized for follow-up localization. Never translate proper
# street/alley names, user destination labels, model identifiers or source URLs.
ENGLISH_TEXT = {
 'Biển P.130 cấm dừng và đỗ xe': 'Sign P.130 prohibits stopping and parking',
 'Biển P.131a cấm đỗ xe': 'Sign P.131a prohibits parking',
 'Biển P.131b cấm đỗ xe ngày lẻ (hôm nay là ngày lẻ)': 'Sign P.131b prohibits odd-day parking (today is odd)',
 'Biển P.131c cấm đỗ xe ngày chẵn (hôm nay là ngày chẵn)': 'Sign P.131c prohibits even-day parking (today is '
                                                           'even)',
 'Đoạn đường được đánh dấu cấm dừng xe': 'This segment is marked no stopping',
 'Đoạn đường được đánh dấu cấm đỗ xe': 'This segment is marked no parking',
 'Dữ liệu biển báo OSM': 'OSM traffic-sign data',
 'Chưa xác định được ranh giới mép nút giao để kiểm tra khoảng cách 5 m': 'Junction boundary unknown; the 5 '
                                                                          'm setback is unverified',
 'Trong phạm vi 5 m tính từ mép đường giao nhau': 'Within 5 m of the intersecting road boundary',
 'Trên phần đường dành cho người đi bộ qua đường': 'On a pedestrian crossing',
 'Tại nơi dừng của xe buýt': 'At a bus stop',
 'Trên cầu, trong hầm đường bộ': 'On a bridge or inside a road tunnel',
 'Trên đường dẫn lên, xuống cầu vượt / nút giao': 'On an overpass or interchange ramp',
 'Đường trục chính tốc độ cao, không dừng đỗ tùy tiện': 'High-speed arterial; stopping and parking are '
                                                        'restricted',
 'Chưa có phép đo clear width đầy đủ để xác định số làn xe cơ giới': 'Complete clear-width measurements are '
                                                                     'missing; motor-vehicle lane count is '
                                                                     'unverified',
 'Danh sách 20 tuyến đường thu phí đỗ xe ô tô, TP.HCM (VETC)': 'HCMC list of 20 streets with paid car '
                                                               'parking (VETC)',
 'Chưa có dữ liệu biển báo đầy đủ tại vị trí này': 'Traffic-sign coverage is incomplete at this location',
 'Dữ liệu biển báo chưa đầy đủ': 'Traffic-sign data is incomplete',
 'Đường chính: chưa có dữ liệu biển cấm đỗ tại đoạn này': 'Main road: no parking-sign coverage for this '
                                                          'segment',
 'Phần đường chỉ đủ một làn xe cơ giới: không được đỗ': 'The roadway fits only one motor-vehicle lane: '
                                                        'parking is prohibited',
 'Không dừng, đỗ xe nơi phần đường chỉ đủ một làn xe cơ giới': 'Stopping and parking are prohibited where '
                                                               'the roadway fits only one motor-vehicle lane',
 'Bãi đỗ ngoài đường': 'Off-street parking',
 'Bãi đỗ xe': 'Parking lot',
 'Bãi đỗ có thanh toán điện tử VETC': 'Parking lot with VETC payment',
 'thanh toán VETC': 'VETC payment',
 'Báo ngập dương tính gần nhất đã hết hạn và chưa có quan sát khô mới hơn': 'The last positive flood report '
                                                                            'expired without a newer dry '
                                                                            'observation',
 'Không có dữ liệu triều hợp lệ tại thời điểm này': 'No valid tide data at this time',
 'Không có thời điểm để kiểm tra': 'No time available for a flood check',
 'Một hoặc nhiều thời điểm chưa có bằng chứng ngập đầy đủ': 'Flood evidence is incomplete at one or more '
                                                            'times',
 'Không có lịch sử ngập hoặc quan sát hiện thời cho đoạn đường': 'No flood history or current observations '
                                                                 'for this segment',
 'BĐ1': 'Alert 1',
 'BĐ2': 'Alert 2',
 'BĐ3': 'Alert 3',
 'OSM phân loại đường': 'OSM road class',
 'OSM số làn xe': 'OSM lane count',
 'Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)': 'Opposing cadastral parcels (HCMC Planning '
                                                           'Portal)',
 'Khoảng trống hình học giữa hai thửa đất': 'Cadastral parcel-gap estimate',
 'Tin rao Chợ Tốt (thu thập trực tiếp)': 'Chợ Tốt listings (collected)',
 'Tin rao Alonhadat (trường “Đường trước nhà”)': 'Alonhadat listings (frontage-road field)',
 'Cấm dừng': 'No stopping',
 'Đường nhánh không tên': 'Unnamed local road',
 'Đường chính không tên': 'Unnamed main road',
 'Hẻm không tên': 'Unnamed alley',
 'Lối đi bộ không tên': 'Unnamed footpath',
 'Trước cửa nhà': 'At the door'}
ENGLISH_PREFIXES = {
 'Chưa đủ bằng chứng hẻm rộng hơn ': 'Width unverified above ',
 'Điểm đỗ ô tô dưới lòng đường có thu phí (': 'Paid on-street car parking (',
 'Mưa ': 'Rain ',
 'Triều ': 'Tide ',
 'Báo ngập ': 'Flood report: ',
 'Tin rao Chợ Tốt': 'Chợ Tốt listings',
 'Tin rao Alonhadat': 'Alonhadat listings',
 'Khảo sát chưa có mặt cắt hợp lệ': 'Survey has no valid cuts',
 'Chưa đủ dữ liệu pháp lý: ': 'Stopping permission unverified: ',
 'Chưa đủ dữ liệu ngập: ': 'Flood evidence incomplete: '}
ENGLISH_FRAGMENTS = {' m (đủ hai làn xe)': ' m (two motor-vehicle lanes)',
 ' (ngày ': ' (date ',
 ' cm lúc ': ' cm at ',
 'dưới BĐ1': 'below Alert 1',
 'BĐ1': 'Alert 1',
 'BĐ2': 'Alert 2',
 'BĐ3': 'Alert 3',
 ', đo)': ', measured)',
 ', bản tin)': ', bulletin)',
 'mô hình ±': 'model ±',
 ' dành cho khách': ' for customers'}

@lru_cache(maxsize=8192)
def english_text(text: str) -> str:
    if text in ENGLISH_TEXT:
        return ENGLISH_TEXT[text]
    for before, after in ENGLISH_PREFIXES.items():
        if text.startswith(before):
            text = after + text[len(before):]
            for old, new in ENGLISH_FRAGMENTS.items():
                text = text.replace(old, new)
            return text
    return text


_DESCRIPTION_KEYS = frozenset({'text', 'detail', 'reason', 'basis', 'source', 'source_label',
    'headline', 'note', 'tier_vi', 'scope', 'unverified_reasons', 'fail_reasons',
    'drivers', 'unknown_reasons', 'alarm', 'safe_water_basis', 'assumptions'})
_GENERIC_NAMES = frozenset({'Đường nhánh không tên', 'Đường chính không tên', 'Hẻm không tên',
                           'Lối đi bộ không tên', 'Trước cửa nhà'})


def english_payload(value, key=None):
    """Translate descriptions; preserve legal citations and numerical/enum data."""
    if key == 'citation':
        return value
    if isinstance(value, dict):
        return {k: english_payload(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [english_payload(v, key) for v in value]
    if isinstance(value, str) and (key in _DESCRIPTION_KEYS or
            (key in ('name', 'way_name', 'label') and value in _GENERIC_NAMES)):
        return english_text(value)
    return value


def _empty_coverage(reason: str | None = None) -> dict:
    return {"cut_count": 0, "start_covered": False, "end_covered": False,
            "max_spacing_m": None, "truncated": False, "complete": False, "reason": reason}


@dataclass
class Bound:
    lo: float
    hi: float
    tier: str
    source: str
    detail: str
    observed_on: str = ""
    url: str = ""
    feature: str = ""
    width_basis: str | None = None
    uncertainty_m: float | None = None
    coverage: dict | None = None

    coverage_complete: bool = False
    coverage_m: float | None = None
    measurement_schema: str = ""
    estimate_m: float | None = None
    sample_count: int | None = None
    sample_cuts: list[dict] = field(default_factory=list, repr=False)
    sample_quality: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.width_basis is None:
            self.width_basis = {
                "Measured": "measured_clear_width",
                "Official": "parcel_gap_estimate",
                "Observed": "observed_clear_width",
                "Declared": "declared_width",
                "Inferred": "inferred",
            }.get(self.tier, "unknown")

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": None if self.hi >= OPEN_HI else round(self.hi, 2),
                "tier": self.tier, "tier_vi": TIER_VI[self.tier], "source": english_text(self.source),
                "detail": english_text(self.detail), "observed_on": self.observed_on, "url": self.url,
                "ai_feature": self.feature or None, "width_basis": self.width_basis,
                "uncertainty_m": self.uncertainty_m, "coverage": self.coverage,
                "coverage_complete": bool(self.coverage and self.coverage.get("complete")),
                "measurement_schema": self.measurement_schema, "estimate_m": self.estimate_m,
                "sample_count": self.sample_count, "sample_quality": self.sample_quality}


@dataclass
class WidthRange:
    lo: float
    hi: float
    top_tier: str | None
    evidence: list[Bound] = field(default_factory=list)
    review: bool = False
    overruled: list[Bound] = field(default_factory=list)
    way_out_claims: list[Bound] = field(default_factory=list)
    width_basis: str = "unknown"
    coverage: dict = field(default_factory=_empty_coverage)
    decisive_clearance: bool = False

    official_width_records: list[dict] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.lo == 0 and self.hi >= OPEN_HI:
            return 'Width unknown'
        if self.lo >= 6.0:
            return "Street"
        if self.hi - self.lo > 3.5 and self.hi < OPEN_HI:
            return "Width unknown"
        mid = (self.lo + min(self.hi, self.lo + 3.0)) / 2
        if mid < 2.0:
            return "Motorcycle alley"
        if mid < 3.0:
            return "Three-wheeler alley"
        if mid < 5.0:
            return "Car alley"
        return "Passing space"

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": None if self.hi >= OPEN_HI else round(self.hi, 2),
                "label": self.label, "top_tier": self.top_tier, "review": self.review,
                "evidence": [b.to_json() for b in self.evidence],
                "overruled": [b.to_json() for b in self.overruled],
                "way_out_claims": [b.to_json() for b in self.way_out_claims],
                "width_basis": self.width_basis, "coverage": self.coverage,
                "decisive_clearance": self.decisive_clearance,
                "sampled_estimate": self.sampled_estimate(),
                "official_width_records": self.official_width_records,
                "clear_width_caveat": ("Parcel geometry; usable = gap minus 1 m (minimum 0.5 m). "
                                       "Sampled estimate, not continuous clear width."
                                       if self.width_basis == "parcel_gap_estimate" else None)}

    def sampled_estimate(self) -> dict | None:
        """Diagnostic sampled bottleneck, separate from the whole-way bounds."""
        samples = [b for b in self.evidence if b.tier == self.top_tier and b not in self.overruled
                   and b.estimate_m is not None and math.isfinite(b.estimate_m)]
        if not samples:
            return None
        bound = min(samples, key=lambda b: b.estimate_m)
        error = bound.uncertainty_m or (.3 if bound.width_basis == 'parcel_gap_estimate' else 0)
        return {'value_m': round(bound.estimate_m, 2),
                'lo': round(max(0, bound.estimate_m-error), 2),
                'hi': round(bound.estimate_m+error, 2),
                'tier': bound.tier, 'source': english_text(bound.source), 'conflicted': self.review,
                'scope': 'sampled_bottleneck_only', 'guarantees_clearance': False}



def _combine(bounds: list[Bound]) -> tuple[float, float, str | None, bool, list[Bound], list[Bound]]:
    if not bounds:
        return 0.5, OPEN_HI, None, False, [], []
    suppressed = [bound for bound in bounds if bound.tier == SYNTHETIC_DEMO_TIER] \
        if any(bound.tier == "Measured" for bound in bounds) else []
    if suppressed:
        bounds = [bound for bound in bounds if bound.tier != SYNTHETIC_DEMO_TIER]
    review = False
    overruled = list(suppressed)
    current: tuple[float, float] | None = None
    top = None
    active: list[Bound] = []
    for tier in TIERS:
        tb = [bound for bound in bounds if bound.tier == tier]
        if not tb:
            continue
        lo, hi = max(bound.lo for bound in tb), min(bound.hi for bound in tb)
        if lo > hi:  # conflict inside one tier: flag it and keep the safe (wider) range
            review = True
            lo, hi = min(bound.lo for bound in tb), max(bound.hi for bound in tb)
        if current is None:
            current, top = (lo, hi), tier
            active = list(tb)
            continue
        cand = (max(current[0], lo), min(current[1], hi))
        if cand[0] <= cand[1]:
            if cand != current:
                current = cand
                active.extend(tb)
        else:
            review = True  # a lower tier conflicts with the range set by stronger evidence
            overruled.extend(tb)
    assert current is not None
    return current[0], current[1], top, review, overruled, active


def _width_metadata(bounds: list[Bound], review: bool) -> tuple[str, dict, bool]:
    if not bounds:
        return "unknown", _empty_coverage("No width evidence"), False
    if any(bound.tier == SYNTHETIC_DEMO_TIER for bound in bounds):
        basis = SYNTHETIC_DEMO_WIDTH_BASIS
    else:
        rank = {"measured_clear_width": 0, "observed_clear_width": 1, "parcel_gap_estimate": 2,
                "road_width_estimate": 3, "declared_width": 4, "inferred": 5, "unknown": 6}
        basis = max((bound.width_basis for bound in bounds), key=lambda value: rank.get(value, 6))
    coverages = [bound.coverage for bound in bounds if bound.coverage]
    missing_coverage = len(coverages) != len(bounds)
    if not coverages:
        coverage = _empty_coverage("Longitudinal coverage is unavailable")
    else:
        complete = (not missing_coverage
                    and all(item.get("complete", False) for item in coverages)
                    and all((_num(item.get("cut_count")) or 0) > 0
                            and item.get("start_covered", False) and item.get("end_covered", False)
                            and not item.get("truncated", False)
                            and (_num(item.get("max_spacing_m")) or float("inf")) <= 5.1
                            for item in coverages)
                    and all(bound.width_basis != 'parcel_gap_estimate' or
                            bound.sample_quality.get('geometry_checked', False) for bound in bounds))
        coverage = {
            "cut_count": sum(int(item.get("cut_count", 0)) for item in coverages),
            "start_covered": not missing_coverage and all(item.get("start_covered", False) for item in coverages),
            "end_covered": not missing_coverage and all(item.get("end_covered", False) for item in coverages),
            "max_spacing_m": max((item.get("max_spacing_m") or 0.0 for item in coverages), default=0.0) or None,
            "truncated": any(item.get("truncated", False) for item in coverages),
            "complete": complete,
            "reason": (next((item.get("reason") for item in coverages if item.get("reason")), None)
                       or ("Evidence lacks longitudinal coverage metadata" if missing_coverage else None)),
        }
    decisive_basis = all(
        bound.width_basis in ("measured_clear_width", "observed_clear_width")
        or (bound.tier == SYNTHETIC_DEMO_TIER and bound.width_basis == SYNTHETIC_DEMO_WIDTH_BASIS)
        for bound in bounds
    )
    decisive_uncertainty = all(bound.uncertainty_m is not None
                               and math.isfinite(bound.uncertainty_m)
                               and bound.uncertainty_m >= 0 for bound in bounds)
    decisive_clearance = (
        not review and decisive_basis and decisive_uncertainty and coverage["complete"]
        and coverage["start_covered"] and coverage["end_covered"] and not coverage["truncated"]
    )
    return basis, coverage, decisive_clearance


def _num(v):
    try:
        value = float(str(v).replace(",", "."))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _osm_bounds(w: Way) -> list[Bound]:
    t, out = w.tags, []
    osm_url = f"https://www.openstreetmap.org/way/{w.id}"
    # Inferred: road class (OSM Vietnam guide: residential fits ≥2 cars; service=alley "one car or two scooters").
    if w.kind == "main":
        lanes = _num(t.get("lanes"))
        if lanes:
            out.append(Bound(2.75 * lanes, 3.75 * lanes + 2.5, "Inferred", "OSM lane count",
                             f"highway={w.highway}, lanes={t['lanes']}", url=osm_url))
        else:
            out.append(Bound(6.0, OPEN_HI, "Inferred", "OSM road class", f"highway={w.highway}", url=osm_url))
    elif w.highway == "service" and t.get("service") == "alley":
        out.append(Bound(1.5, 4.5, "Inferred", "OSM road class", "service=alley (one car or two motorcycles)", url=osm_url))
    elif w.highway in ("residential", "living_street", "unclassified", "road"):
        lo = 2.5 if w.is_alley else 3.5
        out.append(Bound(lo, 15.0, "Inferred", "OSM road class", f"highway={w.highway}", url=osm_url))
    elif w.highway == "service":
        out.append(Bound(2.0, 8.0, "Inferred", "OSM road class", f"highway=service {t.get('service', '')}".strip(), url=osm_url))
    elif w.kind == "foot":
        out.append(Bound(0.5, 2.5, "Inferred", "OSM road class", f"highway={w.highway}", url=osm_url))
    # Observed: explicit car tags (mostly Grab's mapping team in HCMC) and width tags.
    car = t.get("motorcar") or t.get("motor_vehicle")
    if car in ("yes", "destination", "permissive", "designated"):
        out.append(Bound(2.2, OPEN_HI, "Observed", "OSM: motorcars permitted", f"motorcar={car}",
                         url=osm_url, width_basis="unknown"))
    elif car == "no":
        out.append(Bound(0.5, 2.6, "Observed", "OSM: motorcars prohibited or inaccessible", "motorcar=no",
                         url=osm_url, width_basis="unknown"))
    for key, pad in (("width", 0.3), ("est_width", 0.5)):
        v = _num(t.get(key))
        if v and v > 0:
            out.append(Bound(max(0.5, v - pad), v + pad, "Observed", f"OSM {key}", f"{key}={t[key]}",
                             url=osm_url, width_basis="road_width_estimate", uncertainty_m=pad))
    mw = _num(t.get("maxwidth"))
    if mw and mw > 0:
        out.append(Bound(0.5, mw + 0.2, "Observed", "OSM signed maximum width",
                         f"maxwidth={t['maxwidth']}", url=osm_url, width_basis="declared_width"))
    return out


def _norm_alley(name: str) -> str:
    s = strip_accents(name)
    s = re.sub(r"\b(duong|d\.|pho)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class EvidenceIndex:
    """Evidence bounds keyed by OSM way id or by normalised alley name. Built once, then only read."""

    def __init__(self, exclude_measured_way_ids=frozenset(), exclude_measured_names=frozenset()) -> None:
        self.by_way: dict[int, list[Bound]] = {}
        self.by_name: dict[str, list[Bound]] = {}
        self.way_out_by_way: dict[int, list[Bound]] = {}
        self.review_by_way: set[int] = set()
        self._exclude_measured_way_ids = exclude_measured_way_ids
        self._exclude_measured_names = exclude_measured_names

    def _add(self, bound: Bound, way_id=None, name=None) -> None:
        if bound.width_basis not in WIDTH_BASES:
            bound.width_basis = "unknown"
        if way_id:
            self.by_way.setdefault(int(way_id), []).append(bound)
        elif name:
            self.by_name.setdefault(_norm_alley(name), []).append(bound)

    def load_static(self, field_file: Path) -> None:
        self._load_listings()
        self._load_gaps()
        self._load_fire_list()
        self._load_csv(field_file, "Measured", "Field measurement team", pad=0.1)
        self._load_csv(PARCEL_FILE, "Inferred", "Cadastral parcel gap (HCMC Planning Portal)",
                       pad=None, width_basis="parcel_gap_estimate")
        self._load_confirmations()
        if flags.enabled("footprint_widths"):
            self._load_footprints()
        declared_index.load_into(self)
        from . import imagery_evidence
        imagery_evidence.load_into(self)


    def _load_footprints(self) -> None:
        self._footprint_stamp, data = footprints.snapshot()
        if not data:
            return
        calibration = data.get("calibration", {})
        error = calibration.get("uncertainty_radius_m", 0)
        release = data.get("dataset", {}).get("release", "")
        for wid, r in data["ways"].items():
            lo, hi = r.get("lo"), r.get("hi")
            if not isinstance(lo, (float, int)) or not isinstance(hi, (float, int)) or not .5 <= lo <= hi < OPEN_HI:
                continue
            source = (f"Building gaps (Overture imagery; "
                      f"error ±{error:.1f} m against cadastral gaps)")
            detail = (f"{r['source']}; Overture {release}. {r['samples']}/{r['attempted']} opposing cuts "
                      f"at 10 m intervals; building-gap p10 {r['gap_p10_m']:.1f} m, median {r['gap_median_m']:.1f} m. "
                      f"Calibrated against {calibration.get('matched_ways', 0)} cadastral ways; "
                      "assumes 1 m encroachment and ±0.5 m obstacle uncertainty. "
                      "Roof-based inference does not establish clear passage; cadastral evidence takes precedence.")
            self._add(Bound(lo, hi, "Inferred", source, detail,
                            observed_on=data.get("generated_at", "")[:10],
                            url="https://docs.overturemaps.org/guides/buildings/", feature="footprint_widths"), wid)

    def _load_listings(self) -> None:
        # With live crawling on, listings come only from the on-demand area builds (live.py).
        if flags.enabled("live_crawl") or not LISTINGS_FILE.exists():
            return
        for it in json.loads(LISTINGS_FILE.read_text(encoding="utf-8")):
            self._add_listing(it, "Chợ Tốt listings (extracted)")

    def add_areas(self, areas: list[dict]) -> None:
        """Evidence from server-built Live Area Builds (listings, listing photos, cadastral cuts)."""
        for area in areas:
            for it in area["listings"]:
                self._add_listing(it, it.get("source") or "Chợ Tốt listings (collected)")
            for ph in area["photos"]:
                self._add_photo(ph)
            for pc in area.get("parcels", []):
                if not isinstance(pc, dict):
                    continue
                way_id = pc.get("way_id")
                if way_id is None:
                    continue
                try:
                    way_id = int(way_id)
                except (TypeError, ValueError):
                    continue
                observed = str(pc.get("observed_on") or pc.get("queried_at")
                               or area.get("collected_at") or "")
                source_url = pc.get("source_url") or "https://thongtinquyhoach.hochiminhcity.gov.vn/"
                raw_cuts, raw_samples = pc.get("cuts"), pc.get("samples")
                invalid = not isinstance(raw_cuts, list) or not isinstance(raw_samples, list)
                raw_cuts = raw_cuts if isinstance(raw_cuts, list) else []
                raw_samples = raw_samples if isinstance(raw_samples, list) else []
                invalid |= len(raw_samples) != len(raw_cuts)
                length = _num(pc.get("segment_length_m"))
                cuts = []
                for cut in raw_cuts:
                    if not isinstance(cut, dict) or cut.get("valid") is False:
                        invalid = True
                        continue
                    width, gap = _num(cut.get("width_m")), _num(cut.get("gap_m"))
                    at_m = _num(cut.get("at_m"))
                    if at_m is None:
                        invalid = True
                    if (width is None or gap is None or width <= 0 or gap <= 0 or width > gap
                            or (at_m is not None and (at_m < 0 or (length is not None and at_m > length + 0.5)))):
                        invalid = True
                        continue
                    # Cache schemas can contain numeric strings. Normalize
                    # once before geometry/statistical checks; a malformed
                    # supplied location must not become an unlocated sample.
                    lat, lon = _num(cut.get('lat')), _num(cut.get('lon'))
                    if ((cut.get('lat') is not None or cut.get('lon') is not None)
                            and (lat is None or lon is None)):
                        invalid = True
                        continue
                    cuts.append(({**cut, 'observed_on': cut.get('observed_on') or cut.get('queried_at') or observed,
                                  'source': cut.get('source') or 'Cadastral parcel-gap estimate',
                                  'source_url': cut.get('source_url') or source_url,
                                  'width_m': width, 'gap_m': gap, 'at_m': at_m,
                                  'lat': lat, 'lon': lon}, width, at_m))
                sample_values = [_num(value) for value in raw_samples]
                if any(value is None for value in sample_values):
                    invalid = True
                elif len(sample_values) == len(cuts) and any(
                        abs(value - item[1]) > 0.02 for value, item in zip(sample_values, cuts)):
                    invalid = True
                if not cuts:
                    self._add(Bound(0, OPEN_HI, 'Inferred', 'Cadastral parcel-gap estimate',
                                    'Survey has no valid cuts; whole-way width is unverified',
                                    feature='parcel_widths', width_basis='parcel_gap_estimate',
                                    measurement_schema='parcel-survey-unresolved-v2', sample_count=0,
                                    coverage=_empty_coverage('Survey has no valid cuts')), way_id)
                    if invalid:
                        self.review_by_way.add(way_id)
                    continue
                positions = sorted(item[2] for item in cuts if item[2] is not None)
                start = bool(positions and positions[0] <= 0.5)
                end = bool(length is not None and length > 0 and positions
                           and length - positions[-1] <= 0.5)
                spacing = max((b - a for a, b in zip(positions, positions[1:])), default=None)
                truncated = str(pc.get("truncated", "")).lower() in ("1", "true", "yes")
                complete = bool(length is not None and length > 0 and len(positions) == len(cuts)
                                and start and end and spacing is not None and spacing <= 5.1 and not truncated)
                coverage = {"cut_count": len(cuts), "start_covered": start, "end_covered": end,
                            "max_spacing_m": round(spacing, 1) if spacing is not None else None,
                            "truncated": truncated, "complete": complete,
                            "reason": None if complete else "Cuts do not cover both endpoints and the whole way"}
                narrow, width = min(cuts, key=lambda item: item[1])[0], min(item[1] for item in cuts)
                how = f"sampled {len(cuts)} cuts" + (" at ≤5 m intervals" if pc.get("deep") else "")
                detail = (f"Estimated cadastral gap ({how}): narrowest "
                          f"{width:.1f} m (parcel gap {narrow['gap_m']:.1f} m)")
                self._add(Bound(width, width, "Official", "Cadastral parcel-gap estimate",
                                detail, observed_on=observed, url=source_url,
                                feature="parcel_widths", width_basis="parcel_gap_estimate", coverage=coverage,
                                estimate_m=width, sample_count=len(cuts), sample_cuts=[item[0] for item in cuts],
                                measurement_schema="parcel-usable-v2"),
                          way_id)
                if invalid:
                    self.review_by_way.add(way_id)

    def _add_photo(self, ph: dict) -> None:
        w = _num(ph.get("width_m"))
        if w is None or w <= 0 or not ph.get("way_id") or ph.get("status") == "rejected":
            return
        common = dict(observed_on=ph.get("posted_at", "")[:10], url=ph.get("image_url", ""))
        ref = ph.get("reference") or "reference object unknown"
        if ph.get("status") == "approved":
            self._add(Bound(max(0.5, w - 0.3), w + 0.3, "Observed", "Listing photo (reviewed)",
                            f"Reviewer confirmed ≈{w:g} m ({ref})", width_basis="observed_clear_width",
                            uncertainty_m=0.3, **common), ph["way_id"])
        elif ph.get("gate") == "ACCEPT":
            self._add(Bound(max(0.5, w * 0.8), w * 1.2, "Inferred", "AI listing-photo estimate",
                            f"AI estimate ≈{w:g} m from a photo ({ref}), not reviewed", feature="ai_photo_evidence",
                            width_basis="inferred", **common), ph["way_id"])

    def _add_listing(self, it: dict, source: str) -> None:
        way_id = it.get("osm_way_id")
        method = it.get("match_method")
        # Chợ Tốt shifts coordinates ~90 m, so only alley-name matches are trusted.
        # A claim about a sub-alley ("…/34") only proves its parent admits the same car (a lower bound).
        if not way_id or method not in ("alley_chain", "alley_chain_parent"):
            return
        if method == "alley_chain_parent":
            claim = it.get("access_claim")
            if claim in ("xe_hoi", "xe_hoi_tranh"):
                lo = 4.5 if claim == "xe_hoi_tranh" else 2.2
                self._add(Bound(lo, OPEN_HI, "Declared", source + " – child alley",
                                "“car-accessible” child alley implies access through its parent",
                                observed_on=str(it.get("posted_at", ""))[:10], url=it.get("url", ""),
                                feature="ai_listings"), way_id)
            return
        common = dict(tier="Declared", source=source, observed_on=str(it.get("posted_at", ""))[:10],
                      url=it.get("url", ""), feature="ai_listings")
        w = _num(it.get("width_m"))
        if w:
            where = "measured at the alley entrance" if it.get("width_at_mouth") else "measurement location unknown"
            self._add(Bound(0.5, w, detail=f"“alley {w:g} m” ({where})", estimate_m=w, **common), way_id)
        claim = it.get("access_claim")
        claims = {"xe_hoi": (2.2, OPEN_HI, "“car-accessible alley”"), "xe_hoi_tranh": (4.5, OPEN_HI, "“cars can pass”"),
                  "ba_gac": (0.5, 3.0, "“three-wheeler alley”"), "xe_may": (0.5, 2.2, "“motorcycle alley”")}
        if claim in claims:
            lo, hi, d = claims[claim]
            self._add(Bound(lo, hi, detail=d, **common), way_id)
        if it.get("through") in ("thong", "cut"):
            d = "“through alley”" if it["through"] == "thong" else "“dead-end alley”"
            self.way_out_by_way.setdefault(int(way_id), []).append(Bound(0, OPEN_HI, detail=d, **common))

    def _load_fire_list(self) -> None:
        """QĐ 4582: alleys fire trucks cannot enter. Usually narrower than 3.5 m, but long dead ends, bends and low
        wires also put an alley on the list, so it is a Declared bound (a conflict with a listing asks for review)."""
        if not FIRE_FILE.exists():
            return
        doc = json.loads(FIRE_FILE.read_text(encoding="utf-8"))
        for it in doc["items"]:
            b = Bound(0.5, FIRE_TRUCK_MIN, "Declared", "HCMC Decision 4582/QĐ-UBND (24 July 2026)",
                      f"Fire-truck access unavailable ({it['ward']}): often associated with width below 3.5 m"
                      + (f"; {it['provenance']}" if it.get("provenance") else ""),
                      observed_on="2026-07-24", url=doc["url"])
            for wid in it["way_ids"]:
                self._add(b, wid)

    def _load_gaps(self) -> None:
        if not GAPS_FILE.exists():
            return
        for wid, g in json.loads(GAPS_FILE.read_text()).items():
            if g["walled"] < 0.4:  # mostly open on one side: the gap says little
                continue
            lo, hi = max(0.5, g["p25"] - GAP_ENCROACH), g["median"] + GAP_FOOTPRINT_ERR
            self._add(Bound(lo, max(lo, hi), "Inferred", "Building-row gap (satellite imagery)",
                            f"Opposing buildings are ≈{g['median']:.1f} m apart ({g['n']} samples; Microsoft/Google/OSM footprints via Overture)",
                            observed_on="2026-09", url="https://overturemaps.org", feature="building_gaps"), int(wid))

    def _load_csv(self, path, tier: str, source: str, pad: float | None,
                  width_basis: str | None = None) -> None:
        if not path.exists():
            return
        with open(path, encoding="utf-8") as f:
            for row in csv.DictReader(f):
                raw_way_id = row.get("osm_way_id") or None
                try:
                    way_id = int(raw_way_id) if raw_way_id else None
                except (TypeError, ValueError):
                    way_id = None
                name = row.get("alley_name") or None
                if tier == "Measured" and (
                    way_id in self._exclude_measured_way_ids
                    or (name is not None and _norm_alley(name) in self._exclude_measured_names)
                ):
                    continue
                w = _num(row.get("width_m"))
                if w is None or w <= 0:
                    continue
                uncertainty = _num(row.get("uncertainty_m"))
                if uncertainty is None:
                    lo, hi = (w - pad, w + pad) if pad is not None else (0.5, w)
                elif uncertainty < 0:
                    continue
                else:
                    lo, hi = w - uncertainty, w + uncertainty
                lo, hi = max(0.5, lo), max(0.5, hi)
                basis = row.get("width_basis") or width_basis or {
                    "Measured": "measured_clear_width",
                    "Official": "parcel_gap_estimate",
                    "Observed": "observed_clear_width",
                    "Declared": "declared_width",
                    "Inferred": "inferred",
                }.get(tier, "unknown")
                if basis not in WIDTH_BASES:
                    basis = "unknown"
                if (basis == SYNTHETIC_DEMO_WIDTH_BASIS) != (tier == SYNTHETIC_DEMO_TIER):
                    continue
                coverage = None
                coverage_keys = ("cut_count", "start_covered", "end_covered", "max_spacing_m", "truncated", "complete")
                if any(row.get(key) not in (None, "") for key in coverage_keys):
                    count_value = _num(row.get("cut_count"))
                    cut_count = (int(count_value) if count_value is not None and count_value >= 0
                                 and count_value.is_integer() else 0)
                    max_spacing = _num(row.get("max_spacing_m"))
                    start = str(row.get("start_covered", "")).lower() in ("1", "true", "yes")
                    end = str(row.get("end_covered", "")).lower() in ("1", "true", "yes")
                    truncated = str(row.get("truncated", "")).lower() in ("1", "true", "yes")
                    complete = (str(row.get("complete", "")).lower() in ("1", "true", "yes")
                                and cut_count > 0 and start and end and max_spacing is not None
                                and max_spacing <= 5.1 and not truncated)
                    coverage = {"cut_count": int(cut_count), "start_covered": start, "end_covered": end,
                                "max_spacing_m": max_spacing, "truncated": truncated, "complete": complete,
                                "reason": None if complete else "Endpoint coverage is incomplete or cuts are too sparse"}
                bound = Bound(lo, hi, tier, source, row.get("note") or f"{w:g} m",
                              observed_on=row.get("date", ""), url=row.get("photo_url", ""),
                              width_basis=basis, uncertainty_m=uncertainty, coverage=coverage)
                if path == PARCEL_FILE:
                    bound = replace(bound, lo=0.0, hi=max(0.0, w-1.0)+0.3,
                                    estimate_m=max(0.0, w-1.0), coverage_complete=False,
                                    sample_count=1, sample_quality={'bottleneck_support': 0,
                                                                  'geometry_checked': False},
                                    measurement_schema="legacy-raw-gap-converted-v2")
                self._add(bound, way_id, name)

    def _load_confirmations(self) -> None:
        if not CONFIRM_FILE.exists():
            return
        for line in CONFIRM_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                c = json.loads(line)
                vehicle_id = c.get("vehicle_id")
                body = vehicles.min_body_width(vehicle_id) if vehicle_id else float(c["body_width"])
                mirror, label = float(c["mirror_width"]), c["vehicle_label"]
                result, way_ids, observed = c["result"], [int(w) for w in c["way_ids"]], c["date"]
                way_out_ids = [int(w) for w in c.get("way_out_ids", [])]
                exit_action = c.get("exit", "unknown")
            except (ValueError, KeyError, TypeError):
                continue  # one malformed line must not stop every plan
            if result == "in":
                lo, hi, d = body + 0.2, OPEN_HI, f"Driver {label} confirmed access"
            elif result == "tight":
                lo, hi, d = body + 0.1, mirror + 0.8, f"Driver {label} confirmed tight access"
            else:
                lo, hi, d = 0.5, mirror + 0.2, f"Driver {label} could not enter"
            for way_id in way_ids:
                self._add(Bound(lo, hi, "Observed", "Arrival confirmation", d,
                                observed_on=observed, width_basis="unknown"), way_id)
            exit_labels = {
                "through": "through exit",
                "turned": "turn around and exit",
                "reversed": "reverse out",
            }
            if result != "no" and exit_action in exit_labels:
                detail = f"Driver {label} confirmed: {exit_labels[exit_action]}"
                for way_id in way_out_ids:
                    self.way_out_by_way.setdefault(way_id, []).append(
                        Bound(0, OPEN_HI, "Observed", "Arrival confirmation", detail,
                              observed_on=observed, width_basis="unknown")
                    )

    def bounds_for(self, w: Way) -> list[Bound]:
        out = list(self.by_way.get(w.id, []))
        if w.name:
            out += self.by_name.get(_norm_alley(w.name), [])
        return [b for b in out if not b.feature or flags.enabled(b.feature)]

    def way_out_for(self, way_id: int) -> list[Bound]:
        return [b for b in self.way_out_by_way.get(way_id, []) if not b.feature or flags.enabled(b.feature)]


class EvidenceView:
    """What one request reasons from: the base snapshot plus, optionally, one area's build overlay."""

    def __init__(self, base: EvidenceIndex, overlay: EvidenceIndex | None = None) -> None:
        self.base, self.overlay = base, overlay
        self.review_by_way = base.review_by_way | (overlay.review_by_way if overlay else set())

    def bounds_for(self, w: Way) -> list[Bound]:
        return self.base.bounds_for(w) + (self.overlay.bounds_for(w) if self.overlay else [])

    def way_out_for(self, way_id: int) -> list[Bound]:
        return self.base.way_out_for(way_id) + (self.overlay.way_out_for(way_id) if self.overlay else [])


class EvidenceStore:
    """Owner of the static evidence snapshot.

    reload() builds a complete new index off to the side and then publishes it with one reference swap, so a
    request that already holds `snapshot` keeps reasoning from a consistent index and never sees a half-cleared
    one. Area builds never mutate the snapshot; they become a per-request overlay (see `view`).
    """

    def __init__(self, *, _exclude_measured_way_ids=frozenset(),
                 _exclude_measured_names=frozenset(), _field_file: Path = FIELD_FILE) -> None:
        self._exclude_measured_way_ids = frozenset(int(value) for value in _exclude_measured_way_ids)
        self._exclude_measured_names = frozenset(
            normalized for value in _exclude_measured_names if (normalized := _norm_alley(value))
        )
        self._field_file = _field_file
        self.version = 0
        self.snapshot = EvidenceIndex()
        self.reload()

    @classmethod
    def evaluation_snapshot(cls, *, exclude_measured_way_ids=(), exclude_normalized_names=(),
                            field_file: Path = FIELD_FILE) -> EvidenceStore:
        """Create an isolated evidence index with held-out measured rows removed before indexing."""
        return cls(_exclude_measured_way_ids=exclude_measured_way_ids,
                   _exclude_measured_names=exclude_normalized_names, _field_file=field_file)

    def reload(self) -> None:
        index = EvidenceIndex(self._exclude_measured_way_ids, self._exclude_measured_names)
        index.load_static(self._field_file)
        self.snapshot = index
        self._imagery_stamp = getattr(index, "_imagery_stamp", None)
        self._declared_stamp = getattr(index, "_declared_stamp", None)
        self._product_stamps = self._stamps()
        self.version += 1

    @staticmethod
    def _stamps():
        from . import imagery_evidence
        def stamp(p):
            try:
                st = p.stat()
                return st.st_mtime_ns, st.st_size
            except FileNotFoundError:
                return None
        return (footprints.snapshot()[0], declared_index.snapshot()[0],
                official_widths.snapshot()[0], imagery_evidence.active_stamp(),
                stamp(FIELD_FILE), stamp(CONFIRM_FILE))

    def refresh_footprints(self):
        if self._stamps() != self._product_stamps:
            self.reload()

    def bounds_for(self, way):
        return self.snapshot.bounds_for(way)

    def _add(self, bound, way_id=None, name=None):
        self.snapshot._add(bound, way_id, name)
        self.version += 1

    @property
    def by_way(self) -> dict[int, list[Bound]]:
        return self.snapshot.by_way

    @property
    def by_name(self) -> dict[str, list[Bound]]:
        return self.snapshot.by_name

    def view(self, area: dict | None = None, *,
             synthetic_demo_file: Path | None = None) -> EvidenceView:
        overlay = None
        if area or synthetic_demo_file:
            overlay = EvidenceIndex()
            if area:
                overlay.add_areas([area])
            if synthetic_demo_file:
                overlay._load_csv(
                    synthetic_demo_file, SYNTHETIC_DEMO_TIER, "Synthetic demo fixture",
                    pad=0.1, width_basis=SYNTHETIC_DEMO_WIDTH_BASIS,
                )
        return EvidenceView(self.snapshot, overlay)


def _validate_parcel_bound(g, w, b):
    if b.feature != 'parcel_widths' or not b.sample_cuts:
        return b
    from .width_samples import assess
    cuts, quality = assess(g, w, b.sample_cuts)
    if not cuts:
        return replace(b, lo=0, hi=OPEN_HI, estimate_m=None, coverage_complete=False,
                       measurement_schema='parcel-survey-unresolved-v2', sample_count=0,
                       coverage=_empty_coverage('No geometry-valid cuts remain'),
                       sample_quality=quality,
                       detail='Cached cut geometry is invalid; whole-way width remains unverified')
    # Unlocated legacy values remain conservative constraints. They cannot be
    # geometry-filtered, and MAD alone must not erase their narrowest cut.
    if not quality['geometry_checked']:
        return replace(b, sample_quality=quality)
    narrow = min(c['width_m'] for c in cuts)
    # Even an endpoint-complete parcel survey is not a continuous physical
    # clearance guarantee. Preserve sample coverage, never install a floor.
    coverage = dict(b.coverage or _empty_coverage())
    if quality['rejected_cuts']:
        coverage.update(cut_count=len(cuts), complete=False, start_covered=False, end_covered=False,
                        reason='Geometry-invalid cuts rejected; whole-way coverage is incomplete')
    return replace(b, lo=0, hi=narrow+.3, uncertainty_m=.3,
                   estimate_m=narrow, coverage_complete=False, sample_count=len(cuts),
                   coverage=coverage,
                   sample_quality=quality,
                   detail=(f"Narrowest valid sample {narrow:.2f} m; retained {len(cuts)}/{len(b.sample_cuts)} cuts; "
                           f"{quality['bottleneck_support']} cuts corroborate the bottleneck. "
                           'Planning-portal parcel gap minus 1 m (minimum 0.5 m), ±0.3 m allowance; '
                           'sampled estimate, not continuous clear width.'))


STORE_EVIDENCE = EvidenceStore()


def width_ranges(g: AreaGraph, evidence: EvidenceView | None = None) -> dict[int, WidthRange]:
    STORE_EVIDENCE.refresh_footprints()
    evidence = evidence or STORE_EVIDENCE.view()
    out = {}
    for way in g.ways.values():
        bounds = _osm_bounds(way) + [_validate_parcel_bound(g, way, b) for b in evidence.bounds_for(way)]
        candidates, city_ignored, city_review = declared_index.prepare(way.id, bounds)
        # A road-class prior cannot contradict a geometry-checked parcel cap or
        # manufacture a positive floor for an incomplete sampled survey. The
        # Official identifies the portal geometry's provenance, not physical clearance.
        parcel_ignored = []
        if any(b.feature == 'parcel_widths' and
               (b.sample_quality.get('geometry_checked') or b.measurement_schema == 'parcel-survey-unresolved-v2')
               for b in candidates):
            parcel_ignored = [b for b in candidates if b.tier == 'Inferred' and
                             b.source in ('OSM road class', 'OSM lane count')]
            candidates = [b for b in candidates if b not in parcel_ignored]
        footprint_bounds = [b for b in candidates if b.feature == "footprint_widths"]
        ignored = []
        if footprint_bounds:
            if any(b.tier in ("Measured", "Official") for b in candidates):
                ignored = footprint_bounds
                candidates = [b for b in candidates if b not in footprint_bounds]
            else:
                candidates = [b for b in candidates if not (b.tier == "Inferred" and
                    b.source in ("OSM road class", "OSM lane count"))]
        lo, hi, top, review, overruled, active = _combine(candidates)
        review = review or city_review
        overruled += ignored + city_ignored + parcel_ignored
        review = review or way.id in evidence.review_by_way
        basis, coverage, decisive = _width_metadata(active, review)
        out[way.id] = WidthRange(
            lo, hi, top, bounds, review, overruled, evidence.way_out_for(way.id),
            basis, coverage, decisive, official_widths.for_way(way.id),
        )
    return out


def blocked_ways_today() -> dict[int, dict]:
    """Temporary blockages approved for today (D17)."""
    out = {}
    if not BLOCKAGE_FILE.exists():
        return out
    today = datetime.now(timezone(timedelta(hours=7))).date().isoformat()
    for line in BLOCKAGE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            b = json.loads(line) if line.strip() else None
            if b and b.get("date") == today:
                out[int(b["way_id"])] = b
        except (ValueError, KeyError, TypeError):
            continue  # one malformed line must not stop every plan
    return out
