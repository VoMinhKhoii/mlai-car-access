"""Access Evidence → Width Range per way (Q10, Q11).

Every source becomes a bound on Clear Width with an Evidence Tier. Tiers are
combined strongest-first: the highest tier present sets the range, lower tiers
may only narrow it, and a conflict inside one tier is flagged for review.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field, replace
from datetime import date

from . import flags, footprints, declared_index
from .config import DATA, STORE
from .osm import AreaGraph, Way, strip_accents, haversine

TIERS = ["Measured", "Official", "Observed", "Declared", "Inferred"]
TIER_VI = {"Measured": "Đo thực tế", "Official": "Số liệu chính thức", "Observed": "Đã quan sát",
           "Declared": "Tin rao / tự khai", "Inferred": "Suy luận"}
OPEN_HI = 40.0

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
CONFIRM_FILE = STORE / "confirmations.jsonl"
BLOCKAGE_FILE = STORE / "blockages.jsonl"


@dataclass
class Bound:
    lo: float
    hi: float
    tier: str
    source: str
    detail: str
    observed_on: str = ""
    url: str = ""
    feature: str = ""  # AI feature flag that produced this bound, if any
    coverage_complete: bool = True
    coverage_m: float | None = None
    measurement_schema: str = ""
    estimate_m: float | None = None  # sampled bottleneck, never a whole-way lower guarantee

    def to_json(self) -> dict:
        return {"lo": round(self.lo, 2), "hi": None if self.hi >= OPEN_HI else round(self.hi, 2),
                "tier": self.tier, "tier_vi": TIER_VI[self.tier], "source": self.source,
                "detail": self.detail, "observed_on": self.observed_on, "url": self.url,
                "ai_feature": self.feature or None, "coverage_complete": self.coverage_complete,
                "coverage_m": self.coverage_m, "measurement_schema": self.measurement_schema,
                "estimate_m": self.estimate_m}


@dataclass
class WidthRange:
    lo: float
    hi: float
    top_tier: str | None
    evidence: list[Bound] = field(default_factory=list)
    review: bool = False
    overruled: list[Bound] = field(default_factory=list)
    way_out_claims: list[Bound] = field(default_factory=list)
    official_width_records: list[dict] = field(default_factory=list)  # BEGIN official bulk metadata hook

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
                "official_width_records": self.official_width_records}  # END official bulk metadata hook


def _combine(bounds: list[Bound]) -> tuple[float, float, str | None, bool, list[Bound]]:
    if not bounds:
        return 0.5, OPEN_HI, None, False, []
    review = False
    overruled: list[Bound] = []
    current: tuple[float, float] | None = None
    top = None
    decisive_conflict = False
    incomplete = False
    for tier in TIERS:
        tb = [b for b in bounds if b.tier == tier]
        if not tb:
            continue
        lo, hi = max(b.lo for b in tb), min(b.hi for b in tb)
        conflict = lo > hi
        if conflict:
            lo, hi = min(b.lo for b in tb), max(b.hi for b in tb)
        if current is None:
            current, top = (lo, hi), tier
            decisive_conflict = conflict
            review = conflict
            incomplete = any(not b.coverage_complete for b in tb)
            continue
        if decisive_conflict or conflict:
            # Weak evidence cannot choose between contradictory stronger surveys.
            overruled.extend(tb)
            continue
        cand = (max(current[0], lo), min(current[1], hi))
        if incomplete:
            cand = (current[0], cand[1])
        if cand[0] <= cand[1]:
            current = cand
        else:
            overruled.extend(tb)
    return current[0], current[1], top, review, overruled


def _num(v):
    try:
        return float(str(v).replace(",", "."))
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
        out.append(Bound(2.2, OPEN_HI, "Observed", "OSM: ô tô được vào", f"motorcar={car}", url=osm_url))
    elif car == "no":
        out.append(Bound(0.5, 2.6, "Observed", "OSM: cấm/không vào được ô tô", "motorcar=no", url=osm_url))
    for key, pad in (("width", 0.3), ("est_width", 0.5)):
        v = _num(t.get(key))
        if v:
            out.append(Bound(max(0.5, v - pad), v + pad, "Observed", f"OSM {key}", f"{key}={t[key]}", url=osm_url))
    mw = _num(t.get("maxwidth"))
    if mw:
        out.append(Bound(0.5, mw + 0.2, "Observed", "OSM biển hạn chế chiều rộng", f"maxwidth={t['maxwidth']}", url=osm_url))
    return out


def _norm_alley(name: str) -> str:
    s = strip_accents(name)
    s = re.sub(r"\b(duong|d\.|pho)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


class EvidenceStore:
    """External evidence keyed by OSM way id or by normalised alley name."""

    def __init__(self) -> None:
        self.by_way: dict[int, list[Bound]] = {}
        self.by_name: dict[str, list[Bound]] = {}
        self.way_out_by_way: dict[int, list[Bound]] = {}
        self.live: dict[str, dict] = {}
        self.version = 0
        self._footprint_stamp = None
        self._declared_stamp = None  # city listing index (independent of live area builds)
        self.reload()

    def _add(self, bound: Bound, way_id=None, name=None) -> None:
        if way_id:
            self.by_way.setdefault(int(way_id), []).append(bound)
        elif name:
            self.by_name.setdefault(_norm_alley(name), []).append(bound)

    def reload(self) -> None:
        self.version += 1
        self.by_way.clear(), self.by_name.clear(), self.way_out_by_way.clear()
        self._load_listings()
        self._load_live()
        self._load_gaps()
        self._load_footprints()
        self._load_fire_list()
        # BEGIN field kit CSV adapter (method tiers + sample coverage)
        from . import field_evidence
        field_evidence.load_into(self)
        # END field kit CSV adapter
        self._load_csv(PARCEL_FILE, "Official", "Khoảng cách thửa đất (cổng quy hoạch TP.HCM)", pad=None)
        self._load_confirmations()
        # BEGIN moderated crowd evidence (after all Official bounds)
        from . import crowd
        crowd.load_into(self)
        # END moderated crowd evidence
        declared_index.load_into(self)  # BEGIN city-wide Declared index hook
        # BEGIN reviewed street-level imagery hook (isolated from live builds)
        from . import imagery_evidence
        imagery_evidence.load_into(self)
        # END reviewed street-level imagery hook

    def _load_listings(self) -> None:
        # With live crawling on, listings come only from the on-demand area builds (live.py).
        if flags.enabled("live_crawl") or not LISTINGS_FILE.exists():
            return
        for it in json.loads(LISTINGS_FILE.read_text(encoding="utf-8")):
            self._add_listing(it, "Tin rao Chợ Tốt (trích xuất)")

    def set_live(self, key: str, listings: list[dict], photos: list[dict], parcels: list[dict] | None = None) -> None:
        area = {"listings": listings, "photos": photos, "parcels": parcels or []}
        if self.live.get(key) == area:
            return  # unchanged: keep the cached width ranges
        self.live[key] = area
        self.reload()

    def _load_live(self) -> None:
        for area in self.live.values():
            for it in area["listings"]:
                self._add_listing(it, it.get("source") or "Tin rao Chợ Tốt (thu thập trực tiếp)")
            for ph in area["photos"]:
                self._add_photo(ph)
            for pc in area.get("parcels", []):
                # Spatial bottleneck fusion (D36). Quantiles describe samples;
                # they cannot remove a credible constriction or certify an unseen span.
                cuts = [c for c in pc.get("cuts", []) if c.get("valid", True) and
                        c.get("width_m") is not None]
                ws = (sorted(c["width_m"] for c in cuts) if pc.get("cuts") else sorted(pc.get("samples", [])))
                if not ws:
                    # A failed survey remains a coverage gap. Dropping it would
                    # let a weaker class/listing prior certify the unseen way.
                    self._add(Bound(0.0, OPEN_HI, "Official", "Khảo sát thửa đất chưa có mặt cắt hợp lệ",
                                    "Không có mặt cắt đối diện hợp lệ; chưa xác minh bề rộng toàn đoạn",
                                    observed_on=str(pc.get("queried_at", ""))[:10], feature="parcel_widths",
                                    coverage_complete=False, measurement_schema="parcel-survey-unresolved-v2"), pc["way_id"])
                    continue
                coverage = pc.get("coverage", {})
                complete = coverage.get("complete") is True and coverage.get("all_valid") is True
                lo = max(0.0, ws[0] - 0.3) if complete else 0.0
                hi = ws[0] + 0.3
                narrow = min(cuts, key=lambda c: c["width_m"]) if cuts else {"width_m": ws[0], "gap_m": ws[0] + 1}
                how = (f"đo {len(ws)} mặt cắt, cách nhau 5 m" if pc.get("deep") else f"đo {len(ws)} mặt cắt")
                detail = (f"Khoảng cách hai thửa đất đối diện trừ 1 m ({how}): hẹp nhất "
                          f"{narrow['width_m']:.1f} m (thửa cách nhau {narrow['gap_m']:.1f} m); "
                          f"p20 {ws[len(ws)//5]:.1f} m, p80 {ws[min(len(ws)-1, len(ws)*4//5)]:.1f} m; "
                          "bất định ±0,3 m; chưa xác minh toàn bộ đoạn nếu thiếu phạm vi khảo sát").replace(".", ",")
                self._add(Bound(lo, hi, "Official", "Thửa đất hai bên hẻm (cổng Thông tin quy hoạch TP.HCM)", detail,
                                observed_on=str(pc.get("queried_at", ""))[:10],
                                url="https://thongtinquyhoach.hochiminhcity.gov.vn/", feature="parcel_widths",
                                coverage_complete=complete, coverage_m=coverage.get("length_m"),
                                measurement_schema="parcel-usable-v2", estimate_m=ws[0]), pc["way_id"])

    def _add_photo(self, ph: dict) -> None:
        w = _num(ph.get("width_m"))
        if not w or not ph.get("way_id") or ph.get("status") == "rejected":
            return
        common = dict(observed_on=ph.get("posted_at", "")[:10], url=ph.get("image_url", ""))
        ref = ph.get("reference") or "không rõ vật tham chiếu"
        if ph.get("status") == "approved":
            self._add(Bound(max(0.5, w - 0.3), w + 0.3, "Observed", "Ảnh tin rao (đã duyệt)",
                            f"Người duyệt xác nhận ≈{w:g} m ({ref})", **common), ph["way_id"])
        elif ph.get("gate") == "ACCEPT":
            self._add(Bound(max(0.5, w * 0.8), w * 1.2, "Inferred", "AI đọc ảnh tin rao",
                            f"AI ước lượng ≈{w:g} m từ ảnh ({ref}), chưa duyệt", feature="ai_photo_evidence",
                            **common), ph["way_id"])

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
            self._add(Bound(0.5, w, detail=f"“hẻm {w:g} m” ({where})", estimate_m=w, **common), way_id)
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
                      f"Xe chữa cháy không vào được ({it['ward']}): thường do hẻm hẹp hơn 3,5 m"
                      + (f"; {it['provenance']}" if it.get('provenance') else ''),
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

    def refresh_footprints(self) -> None:
        """Call before consulting the plan width cache's EvidenceStore version."""
        # BEGIN field kit cross-process refresh (before plan width cache)
        from . import field_evidence
        field_evidence.refresh(self)
        # END field kit cross-process refresh
        declared_index.refresh(self)  # reload BEFORE the existing plan width-cache version check
        # BEGIN official bulk metadata refresh hook
        from . import official_widths
        official_widths.refresh(self)
        # END official bulk metadata refresh hook
        # BEGIN reviewed street-level imagery refresh hook
        from . import imagery_evidence
        imagery_evidence.refresh(self)
        # END reviewed street-level imagery refresh hook
        stamp, _ = footprints.snapshot()
        if stamp != self._footprint_stamp:
            self.reload()

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
            source = (f"Khoảng cách giữa các tòa nhà (ảnh vệ tinh, Overture; "
                      f"sai số ±{error:.1f} m so với địa chính)")
            detail = (f"{r['source']}; Overture {release}. {r['samples']}/{r['attempted']} mặt cắt hai phía, "
                      f"cách 10 m; khoảng nhà p10 {r['gap_p10_m']:.1f} m, trung vị {r['gap_median_m']:.1f} m. "
                      f"Hiệu chỉnh theo {calibration.get('matched_ways', 0)} đoạn địa chính; "
                      "trừ 1 m giả định lấn chiếm, thêm ±0,5 m bất định vật cản. "
                      "Suy luận từ mái nhà; không xác nhận lối đi thông thoáng. Địa chính được ưu tiên.")
            self._add(Bound(lo, hi, "Inferred", source, detail,
                            observed_on=data.get("generated_at", "")[:10],
                            url="https://docs.overturemaps.org/guides/buildings/", feature="footprint_widths"), wid)

    def _load_csv(self, path, tier: str, source: str, pad: float | None) -> None:
        if not path.exists():
            return
        for row in csv.DictReader(open(path, encoding="utf-8")):
            w = _num(row.get("width_m"))
            if not w:
                continue
            lo, hi = (w - pad, w + pad) if pad is not None else (0.5, w)
            b = Bound(max(0.5, lo), hi, tier, source, row.get("note") or f"{w:g} m",
                      observed_on=row.get("date", ""), url=row.get("photo_url", ""))
            if path == PARCEL_FILE:
                b = replace(b, lo=0.0, hi=max(0.0, w-1.0)+0.3, coverage_complete=False,
                            estimate_m=max(0.0, w-1.0),
                            measurement_schema="legacy-raw-gap-converted-v2",
                            detail=b.detail+f"; khoảng thửa gốc {w:g} m; trừ 1 m = {max(0,w-1):g} m, bất định ±0,3 m; chưa rõ phạm vi")
            self._add(b, row.get("osm_way_id") or None, row.get("alley_name") or None)

    def _load_confirmations(self) -> None:
        if not CONFIRM_FILE.exists():
            return
        for line in CONFIRM_FILE.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            body, mirror = c["body_width"], c["mirror_width"]
            if c["result"] == "in":
                lo, hi, d = (body if c.get("mirrors_folded") else mirror), OPEN_HI, f"Tài xế {c['vehicle_label']} xác nhận vào được"
            elif c["result"] == "tight":
                lo, hi, d = body + 0.1, mirror + 0.8, f"Tài xế {c['vehicle_label']} xác nhận vào được nhưng chật"
            else:
                lo, hi, d = 0.5, mirror + 0.2, f"Tài xế {c['vehicle_label']} không vào được"
            for way_id in c["way_ids"]:
                self._add(Bound(lo, hi, "Observed", "Xác nhận sau khi đến", d, observed_on=c["date"]), way_id)

    def bounds_for(self, w: Way) -> list[Bound]:
        out = list(self.by_way.get(w.id, []))
        if w.name:
            out += self.by_name.get(_norm_alley(w.name), [])
        return [b for b in out if not b.feature or flags.enabled(b.feature)]

    def way_out_for(self, way_id: int) -> list[Bound]:
        return [b for b in self.way_out_by_way.get(way_id, []) if not b.feature or flags.enabled(b.feature)]


STORE_EVIDENCE = EvidenceStore()


def width_ranges(g: AreaGraph) -> dict[int, WidthRange]:
    STORE_EVIDENCE.refresh_footprints()
    out = {}
    for w in g.ways.values():
        bounds = _osm_bounds(w) + STORE_EVIDENCE.bounds_for(w)
        footprint_bounds = [b for b in bounds if b.feature == "footprint_widths"]
        ignored = []
        active, city_ignored, city_review = declared_index.prepare(w.id, bounds)
        if footprint_bounds:
            if any(b.tier in ("Measured", "Official") for b in bounds):
                # A roof model never alters surveyed widths, even when overlapping.
                ignored = footprint_bounds
                active = [b for b in active if b not in footprint_bounds]
            else:
                # Road-class guesses must not truncate calibrated uncertainty.
                active = [b for b in active if not (b.tier == "Inferred" and
                          b.source in ("OSM phân loại đường", "OSM số làn xe"))]
        # Even a complete destination-prefix scan is not a complete OSM way survey.
        scoped = []
        for b in active:
            if b.feature == "parcel_widths" and b.coverage_complete:
                length = sum(haversine(*g.nodes[a], *g.nodes[z]) for a, z in zip(w.nodes, w.nodes[1:]))
                if b.coverage_m is None or b.coverage_m + 1 < length:
                    b = replace(b, lo=0.0, coverage_complete=False)
            scoped.append(b)
        active = scoped
        lo, hi, top, review, overruled = _combine(active)
        overruled += ignored + city_ignored  # END city-wide Declared index hook
        review = review or city_review
        wr = WidthRange(lo, hi, top, bounds, review, overruled, STORE_EVIDENCE.way_out_for(w.id))
        # BEGIN official bulk metadata hook (never enters _combine)
        from . import official_widths
        wr.official_width_records = official_widths.for_way(w.id)
        # END official bulk metadata hook
        out[w.id] = wr
    # BEGIN crowd disagreement metadata (fusion remains unchanged)
    from . import crowd
    crowd.mark_review(out)
    # END crowd disagreement metadata
    return out


def blocked_ways_today() -> dict[int, dict]:
    """Temporary Blockages reported today (D17); they expire at the end of the day."""
    if not BLOCKAGE_FILE.exists():
        return {}
    today = date.today().isoformat()
    out = {}
    for line in BLOCKAGE_FILE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            b = json.loads(line)
            if b.get("date") in (today, "demo"):
                out[int(b["way_id"])] = b
    return out
