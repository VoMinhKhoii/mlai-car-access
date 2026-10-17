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
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import flags, vehicles
from .config import DATA, STORE
from .osm import AreaGraph, Way, strip_accents

SYNTHETIC_DEMO_TIER = "Synthetic"
SYNTHETIC_DEMO_WIDTH_BASIS = "synthetic_demo_width"
TIERS = ["Measured", SYNTHETIC_DEMO_TIER, "Official", "Observed", "Declared", "Inferred"]
TIER_VI = {"Synthetic": "Mock · giả lập", "Measured": "Đo thực tế", "Official": "Số liệu chính thức",
           "Observed": "Đã quan sát", "Declared": "Tin rao / tự khai", "Inferred": "Suy luận"}
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
                "tier": self.tier, "tier_vi": TIER_VI[self.tier], "source": self.source,
                "detail": self.detail, "observed_on": self.observed_on, "url": self.url,
                "ai_feature": self.feature or None, "width_basis": self.width_basis,
                "uncertainty_m": self.uncertainty_m, "coverage": self.coverage}


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

    @property
    def label(self) -> str:
        if self.lo >= 6.0:
            return "Đường phố"
        if self.hi - self.lo > 3.5 and self.hi < OPEN_HI:
            return "Chưa rõ bề rộng"
        mid = (self.lo + min(self.hi, self.lo + 3.0)) / 2
        if mid < 2.0:
            return "Hẻm xe máy"
        if mid < 3.0:
            return "Hẻm ba gác"
        if mid < 5.0:
            return "Hẻm xe hơi"
        return "Ô tô tránh"

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": None if self.hi >= OPEN_HI else round(self.hi, 2),
                "label": self.label, "top_tier": self.top_tier, "review": self.review,
                "evidence": [b.to_json() for b in self.evidence],
                "overruled": [b.to_json() for b in self.overruled],
                "way_out_claims": [b.to_json() for b in self.way_out_claims],
                "width_basis": self.width_basis, "coverage": self.coverage,
                "decisive_clearance": self.decisive_clearance}



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
        return "unknown", _empty_coverage("Không có bằng chứng bề rộng"), False
    if any(bound.tier == SYNTHETIC_DEMO_TIER for bound in bounds):
        basis = SYNTHETIC_DEMO_WIDTH_BASIS
    else:
        rank = {"measured_clear_width": 0, "observed_clear_width": 1, "parcel_gap_estimate": 2,
                "road_width_estimate": 3, "declared_width": 4, "inferred": 5, "unknown": 6}
        basis = max((bound.width_basis for bound in bounds), key=lambda value: rank.get(value, 6))
    coverages = [bound.coverage for bound in bounds if bound.coverage]
    missing_coverage = len(coverages) != len(bounds)
    if not coverages:
        coverage = _empty_coverage("Không có dữ liệu phủ theo chiều dài")
    else:
        complete = (not missing_coverage
                    and all(item.get("complete", False) for item in coverages)
                    and all((_num(item.get("cut_count")) or 0) > 0
                            and item.get("start_covered", False) and item.get("end_covered", False)
                            and not item.get("truncated", False)
                            and (_num(item.get("max_spacing_m")) or float("inf")) <= 5.1
                            for item in coverages))
        coverage = {
            "cut_count": sum(int(item.get("cut_count", 0)) for item in coverages),
            "start_covered": not missing_coverage and all(item.get("start_covered", False) for item in coverages),
            "end_covered": not missing_coverage and all(item.get("end_covered", False) for item in coverages),
            "max_spacing_m": max((item.get("max_spacing_m") or 0.0 for item in coverages), default=0.0) or None,
            "truncated": any(item.get("truncated", False) for item in coverages),
            "complete": complete,
            "reason": (next((item.get("reason") for item in coverages if item.get("reason")), None)
                       or ("Bằng chứng thiếu metadata phủ theo chiều dài" if missing_coverage else None)),
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
            out.append(Bound(2.75 * lanes, 3.75 * lanes + 2.5, "Inferred", "OSM số làn xe",
                             f"highway={w.highway}, lanes={t['lanes']}", url=osm_url))
        else:
            out.append(Bound(6.0, OPEN_HI, "Inferred", "OSM phân loại đường", f"highway={w.highway}", url=osm_url))
    elif w.highway == "service" and t.get("service") == "alley":
        out.append(Bound(1.5, 4.5, "Inferred", "OSM phân loại đường", "service=alley (1 ô tô hoặc 2 xe máy)", url=osm_url))
    elif w.highway in ("residential", "living_street", "unclassified", "road"):
        lo = 2.5 if w.is_alley else 3.5
        out.append(Bound(lo, 15.0, "Inferred", "OSM phân loại đường", f"highway={w.highway}", url=osm_url))
    elif w.highway == "service":
        out.append(Bound(2.0, 8.0, "Inferred", "OSM phân loại đường", f"highway=service {t.get('service', '')}".strip(), url=osm_url))
    elif w.kind == "foot":
        out.append(Bound(0.5, 2.5, "Inferred", "OSM phân loại đường", f"highway={w.highway}", url=osm_url))
    # Observed: explicit car tags (mostly Grab's mapping team in HCMC) and width tags.
    car = t.get("motorcar") or t.get("motor_vehicle")
    if car in ("yes", "destination", "permissive", "designated"):
        out.append(Bound(2.2, OPEN_HI, "Observed", "OSM: ô tô được vào", f"motorcar={car}",
                         url=osm_url, width_basis="unknown"))
    elif car == "no":
        out.append(Bound(0.5, 2.6, "Observed", "OSM: cấm/không vào được ô tô", "motorcar=no",
                         url=osm_url, width_basis="unknown"))
    for key, pad in (("width", 0.3), ("est_width", 0.5)):
        v = _num(t.get(key))
        if v and v > 0:
            out.append(Bound(max(0.5, v - pad), v + pad, "Observed", f"OSM {key}", f"{key}={t[key]}",
                             url=osm_url, width_basis="road_width_estimate", uncertainty_m=pad))
    mw = _num(t.get("maxwidth"))
    if mw and mw > 0:
        out.append(Bound(0.5, mw + 0.2, "Observed", "OSM biển hạn chế chiều rộng",
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
        self._load_csv(field_file, "Measured", "Nhóm đo bằng thước", pad=0.1)
        self._load_csv(PARCEL_FILE, "Inferred", "Khoảng cách thửa đất (cổng Thông tin quy hoạch TP.HCM)",
                       pad=None, width_basis="parcel_gap_estimate")
        self._load_confirmations()


    def _load_listings(self) -> None:
        # With live crawling on, listings come only from the on-demand area builds (live.py).
        if flags.enabled("live_crawl") or not LISTINGS_FILE.exists():
            return
        for it in json.loads(LISTINGS_FILE.read_text(encoding="utf-8")):
            self._add_listing(it, "Tin rao Chợ Tốt (trích xuất)")

    def add_areas(self, areas: list[dict]) -> None:
        """Evidence from server-built Live Area Builds (listings, listing photos, cadastral cuts)."""
        for area in areas:
            for it in area["listings"]:
                self._add_listing(it, it.get("source") or "Tin rao Chợ Tốt (thu thập trực tiếp)")
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
                raw_cuts, raw_samples = pc.get("cuts"), pc.get("samples")
                invalid = not isinstance(raw_cuts, list) or not isinstance(raw_samples, list)
                raw_cuts = raw_cuts if isinstance(raw_cuts, list) else []
                raw_samples = raw_samples if isinstance(raw_samples, list) else []
                invalid |= len(raw_samples) != len(raw_cuts)
                length = _num(pc.get("segment_length_m"))
                cuts = []
                for cut in raw_cuts:
                    if not isinstance(cut, dict):
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
                    cuts.append((cut, width, at_m))
                sample_values = [_num(value) for value in raw_samples]
                if any(value is None for value in sample_values):
                    invalid = True
                elif len(sample_values) == len(cuts) and any(
                        abs(value - item[1]) > 0.02 for value, item in zip(sample_values, cuts)):
                    invalid = True
                if not cuts:
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
                            "reason": None if complete else "Các mặt cắt chưa phủ đủ hai đầu và toàn bộ đoạn đường"}
                narrow, width = min(cuts, key=lambda item: item[1])[0], min(item[1] for item in cuts)
                how = f"đo {len(cuts)} mặt cắt" + (" mỗi ≤5 m" if pc.get("deep") else "")
                detail = (f"Khoảng trống thửa đất ước tính ({how}): hẹp nhất "
                          f"{width:.1f} m (thửa cách nhau {narrow['gap_m']:.1f} m)").replace(".", ",")
                self._add(Bound(width, width, "Inferred", "Khoảng trống hình học giữa hai thửa đất",
                                detail, url="https://thongtinquyhoach.hochiminhcity.gov.vn/",
                                feature="parcel_widths", width_basis="parcel_gap_estimate", coverage=coverage),
                          way_id)
                if invalid:
                    self.review_by_way.add(way_id)

    def _add_photo(self, ph: dict) -> None:
        w = _num(ph.get("width_m"))
        if w is None or w <= 0 or not ph.get("way_id") or ph.get("status") == "rejected":
            return
        common = dict(observed_on=ph.get("posted_at", "")[:10], url=ph.get("image_url", ""))
        ref = ph.get("reference") or "không rõ vật tham chiếu"
        if ph.get("status") == "approved":
            self._add(Bound(max(0.5, w - 0.3), w + 0.3, "Observed", "Ảnh tin rao (đã duyệt)",
                            f"Người duyệt xác nhận ≈{w:g} m ({ref})", width_basis="observed_clear_width",
                            uncertainty_m=0.3, **common), ph["way_id"])
        elif ph.get("gate") == "ACCEPT":
            self._add(Bound(max(0.5, w * 0.8), w * 1.2, "Inferred", "AI đọc ảnh tin rao",
                            f"AI ước lượng ≈{w:g} m từ ảnh ({ref}), chưa duyệt", feature="ai_photo_evidence",
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
                self._add(Bound(lo, OPEN_HI, "Declared", source + " – hẻm con",
                                "“hẻm xe hơi” ở hẻm con ⇒ hẻm cha cũng vào được xe",
                                observed_on=str(it.get("posted_at", ""))[:10], url=it.get("url", ""),
                                feature="ai_listings"), way_id)
            return
        common = dict(tier="Declared", source=source, observed_on=str(it.get("posted_at", ""))[:10],
                      url=it.get("url", ""), feature="ai_listings")
        w = _num(it.get("width_m"))
        if w:
            where = "đo ở đầu hẻm" if it.get("width_at_mouth") else "không rõ vị trí đo"
            self._add(Bound(0.5, w, detail=f"“hẻm {w:g} m” ({where})", **common), way_id)
        claim = it.get("access_claim")
        claims = {"xe_hoi": (2.2, OPEN_HI, "“hẻm xe hơi”"), "xe_hoi_tranh": (4.5, OPEN_HI, "“xe hơi tránh nhau”"),
                  "ba_gac": (0.5, 3.0, "“hẻm ba gác”"), "xe_may": (0.5, 2.2, "“hẻm xe máy”")}
        if claim in claims:
            lo, hi, d = claims[claim]
            self._add(Bound(lo, hi, detail=d, **common), way_id)
        if it.get("through") in ("thong", "cut"):
            d = "“hẻm thông”" if it["through"] == "thong" else "“hẻm cụt”"
            self.way_out_by_way.setdefault(int(way_id), []).append(Bound(0, OPEN_HI, detail=d, **common))

    def _load_fire_list(self) -> None:
        """QĐ 4582: alleys fire trucks cannot enter. Usually narrower than 3.5 m, but long dead ends, bends and low
        wires also put an alley on the list, so it is a Declared bound (a conflict with a listing asks for review)."""
        if not FIRE_FILE.exists():
            return
        doc = json.loads(FIRE_FILE.read_text(encoding="utf-8"))
        for it in doc["items"]:
            b = Bound(0.5, FIRE_TRUCK_MIN, "Declared", "QĐ 4582/QĐ-UBND TP.HCM (24/7/2026)",
                      f"Xe chữa cháy không vào được ({it['ward']}): thường do hẻm hẹp hơn 3,5 m",
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
            self._add(Bound(lo, max(lo, hi), "Inferred", "Khoảng cách giữa hai dãy nhà (ảnh vệ tinh)",
                            f"Nhà hai bên cách nhau ≈{g['median']:.1f} m (đo {g['n']} điểm; footprint Microsoft/Google/OSM qua Overture)",
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
                                "reason": None if complete else "Thiếu phủ đầy đủ hai đầu hoặc có mặt cắt thưa"}
                bound = Bound(lo, hi, tier, source, row.get("note") or f"{w:g} m",
                              observed_on=row.get("date", ""), url=row.get("photo_url", ""),
                              width_basis=basis, uncertainty_m=uncertainty, coverage=coverage)
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
                lo, hi, d = body + 0.2, OPEN_HI, f"Tài xế {label} xác nhận vào được"
            elif result == "tight":
                lo, hi, d = body + 0.1, mirror + 0.8, f"Tài xế {label} xác nhận vào được nhưng chật"
            else:
                lo, hi, d = 0.5, mirror + 0.2, f"Tài xế {label} không vào được"
            for way_id in way_ids:
                self._add(Bound(lo, hi, "Observed", "Xác nhận sau khi đến", d,
                                observed_on=observed, width_basis="unknown"), way_id)
            exit_labels = {
                "through": "đi thẳng ra",
                "turned": "quay đầu ra",
                "reversed": "lùi ra",
            }
            if result != "no" and exit_action in exit_labels:
                detail = f"Tài xế {label} xác nhận đã {exit_labels[exit_action]}"
                for way_id in way_out_ids:
                    self.way_out_by_way.setdefault(way_id, []).append(
                        Bound(0, OPEN_HI, "Observed", "Xác nhận sau khi đến", detail,
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


STORE_EVIDENCE = EvidenceStore()


def width_ranges(g: AreaGraph, evidence: EvidenceView | None = None) -> dict[int, WidthRange]:
    evidence = evidence or STORE_EVIDENCE.view()
    out = {}
    for way in g.ways.values():
        bounds = _osm_bounds(way) + evidence.bounds_for(way)
        lo, hi, top, review, overruled, active = _combine(bounds)
        review = review or way.id in evidence.review_by_way
        basis, coverage, decisive = _width_metadata(active, review)
        out[way.id] = WidthRange(
            lo, hi, top, bounds, review, overruled, evidence.way_out_for(way.id),
            basis, coverage, decisive,
        )
    return out


def blocked_ways_today() -> dict[int, dict]:
    """Temporary blockages approved for today (D17)."""
    out = {}
    if not BLOCKAGE_FILE.exists():
        return out
    today = date.today().isoformat()
    for line in BLOCKAGE_FILE.read_text(encoding="utf-8").splitlines():
        try:
            b = json.loads(line) if line.strip() else None
            if b and b.get("date") == today:
                out[int(b["way_id"])] = b
        except (ValueError, KeyError, TypeError):
            continue  # one malformed line must not stop every plan
    return out
