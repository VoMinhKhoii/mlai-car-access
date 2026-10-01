"""Vehicle Profiles: exact Vehicle Models from the spec table, and worst-case Size Classes.

Rules: Q3 (inputs), Q4 (Size Class = worst case per limit), D14 (Safe Water Depth),
D15/D16 (widths needed to pass, open a door, turn in, turn around).
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from . import geometry
from .config import (CACHE, DATA, DOOR_OPEN_M, PARKED_MOTORBIKE_ROW_M, SIDE_CLEARANCE_M,
                     TIGHT_MARGIN_M)

CSV_PATH = DATA / "vehicles" / "vn_car_profiles.csv"
MIRROR_ALLOWANCE_M = 0.25  # added to body width when mirror width isn't published

SIZE_CLASSES = {
    "XS": ("Xe cỡ nhỏ", ["VinFast VF 3", "Kia Morning", "Hyundai Grand i10"]),
    "S": ("Sedan & crossover cỡ B/C", ["Toyota Vios", "Honda City", "Hyundai Accent", "Mazda Mazda3",
                                       "VinFast VF 5", "VinFast VF 6", "Toyota Yaris Cross", "Hyundai Creta",
                                       "Kia Seltos", "Mitsubishi Xforce", "Toyota Corolla Cross",
                                       "Mitsubishi Xpander", "Mazda CX-5"]),
    "M": ("SUV/MPV 7 chỗ & sedan cỡ D", ["Toyota Camry", "Mercedes-Benz C-Class", "VinFast VF 7", "VinFast VF 8",
                                         "VinFast Limo Green", "Ford Territory", "Toyota Innova Cross",
                                         "Toyota Fortuner", "Hyundai Santa Fe", "Ford Everest"]),
    "L": ("Xe lớn, bán tải, tải nhẹ", ["VinFast VF 9", "Kia Carnival", "Ford Ranger", "Hyundai New Porter H150",
                                        "Isuzu QKR"]),
    "XL": ("Xe khách 16 chỗ, van", ["Ford Transit", "Hyundai Solati"]),
}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


@dataclass
class VehicleProfile:
    id: str
    label: str
    kind: str                 # "model" | "class"
    size_class: str
    powertrain: str
    body_width: float
    mirror_width: float
    mirror_estimated: bool
    length: float
    wheelbase: float
    turning_radius: float
    turning_radius_estimated: bool
    track: float | None
    ground_clearance: float
    safe_water_depth: float
    safe_water_basis: str
    members: list[str] = field(default_factory=list)
    source_url: str = ""

    # D15
    @property
    def fits_min(self) -> float:
        return self.mirror_width + 2 * SIDE_CLEARANCE_M + PARKED_MOTORBIKE_ROW_M

    @property
    def tight_min(self) -> float:
        return self.mirror_width + TIGHT_MARGIN_M

    @property
    def door_min(self) -> float:
        return self.body_width + SIDE_CLEARANCE_M + DOOR_OPEN_M

    def to_json(self) -> dict:
        return {
            "id": self.id, "label": self.label, "kind": self.kind, "size_class": self.size_class,
            "powertrain": self.powertrain, "body_width": self.body_width, "mirror_width": round(self.mirror_width, 3),
            "mirror_estimated": self.mirror_estimated, "length": self.length,
            "turning_radius": self.turning_radius, "turning_radius_estimated": self.turning_radius_estimated,
            "ground_clearance": self.ground_clearance, "safe_water_depth": round(self.safe_water_depth, 3),
            "safe_water_basis": self.safe_water_basis, "members": self.members,
            "fits_min": round(self.fits_min, 2), "tight_min": round(self.tight_min, 2),
            "three_point_width": round(three_point_width(self.id), 2), "source_url": self.source_url,
        }


def _safe_water(row: dict, gc: float) -> tuple[float, str]:
    wading = _num(row.get("wading_depth_mm"))
    if "EV" in row.get("powertrain", "") and "HEV" not in row.get("powertrain", ""):
        return gc, "Nhà sản xuất (VinFast): nước không vượt khoảng sáng gầm"
    if wading and wading > gc + 1e-6:
        return 0.5 * wading / 1000, f"50% độ lội nước công bố ({int(wading)} mm, nước tĩnh, 7 km/h)"
    return min(gc, 0.25), "Toyota VN: không lội quá 25 cm; giới hạn bởi khoảng sáng gầm"


def _class_of(name: str) -> str:
    for cls, (_, members) in SIZE_CLASSES.items():
        if any(name.startswith(m) or m.startswith(name) for m in members):
            return cls
    return "M"


@lru_cache(maxsize=1)
def _load_models() -> dict[str, VehicleProfile]:
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))
    models: dict[str, VehicleProfile] = {}
    pending_r = []
    for row in rows:
        name = f"{row['brand']} {row['model']}".replace("(hatchback)", "").replace("(sedan)", "").strip()
        name = re.sub(r"\s*\(.*?\)\s*$", "", name).strip() if "VF 8" not in name else name
        W = _num(row["width_mm"]) / 1000
        mw = _num(row.get("width_with_mirrors_mm"))
        gc = (_num(row.get("ground_clearance_mm")) or 150) / 1000
        safe, basis = _safe_water(row, gc)
        R = _num(row.get("min_turning_radius_m"))
        T = _num(row.get("track_front_mm"))
        p = VehicleProfile(
            id=_slug(name), label=name, kind="model", size_class=_class_of(name),
            powertrain=row.get("powertrain", ""), body_width=W,
            mirror_width=(mw / 1000) if mw else W + MIRROR_ALLOWANCE_M, mirror_estimated=not mw,
            length=_num(row["length_mm"]) / 1000, wheelbase=_num(row["wheelbase_mm"]) / 1000,
            turning_radius=R or 0.0, turning_radius_estimated=R is None, track=(T / 1000) if T else None,
            ground_clearance=gc, safe_water_depth=safe, safe_water_basis=basis, source_url=row.get("source_url", ""),
        )
        models[p.id] = p
        if R is None:
            pending_r.append(p)
    # Missing turning radius: use the worst radius in the model's Size Class (conservative).
    for p in pending_r:
        peers = [m.turning_radius for m in models.values() if m.size_class == p.size_class and m.turning_radius]
        p.turning_radius = max(peers) if peers else 6.0
    return models


@lru_cache(maxsize=1)
def _load_classes() -> dict[str, VehicleProfile]:
    models = _load_models()
    out = {}
    for cls, (label, _) in SIZE_CLASSES.items():
        members = [m for m in models.values() if m.size_class == cls]
        widest = max(members, key=lambda m: m.mirror_width)
        longest = max(members, key=lambda m: m.length)
        lowest = min(members, key=lambda m: m.safe_water_depth)
        out[f"class-{cls.lower()}"] = VehicleProfile(
            id=f"class-{cls.lower()}", label=f"{cls} · {label}", kind="class", size_class=cls,
            powertrain="mixed", body_width=max(m.body_width for m in members),
            mirror_width=widest.mirror_width, mirror_estimated=widest.mirror_estimated,
            length=longest.length, wheelbase=longest.wheelbase,
            turning_radius=max(m.turning_radius for m in members), turning_radius_estimated=False,
            track=None, ground_clearance=min(m.ground_clearance for m in members),
            safe_water_depth=lowest.safe_water_depth,
            safe_water_basis=f"Thấp nhất trong nhóm ({lowest.label}): {lowest.safe_water_basis}",
            members=[m.label for m in members],
        )
    return out


def all_profiles() -> dict[str, VehicleProfile]:
    return {**_load_classes(), **_load_models()}


def get_profile(pid: str) -> VehicleProfile:
    profiles = all_profiles()
    if pid not in profiles:
        raise KeyError(pid)
    return profiles[pid]


def _members(pid: str) -> list[VehicleProfile]:
    p = get_profile(pid)
    if p.kind == "model":
        return [p]
    return [m for m in _load_models().values() if m.size_class == p.size_class]


@lru_cache(maxsize=4096)
def turn_in_width(pid: str, street_width: float) -> float:
    """Narrowest alley a vehicle can turn into in one forward arc from a street (D16)."""
    worst = 0.0
    for m in _members(pid):
        kw = dict(T=m.track)
        worst = max(worst, geometry.min_alley_for_turn_in(m.body_width, m.length, m.wheelbase,
                                                          m.turning_radius, street_width,
                                                          c=SIDE_CLEARANCE_M, **kw))
    return worst


_TP_CACHE = CACHE / "three_point.json"
_tp: dict[str, float] = json.loads(_TP_CACHE.read_text()) if _TP_CACHE.exists() else {}


def three_point_width(pid: str) -> float:
    """Narrowest space for a 3-point turn (D16); the simulation is slow, so results are cached on disk."""
    if pid not in _tp:
        worst = 0.0
        for m in _members(pid):
            w, _ = geometry.min_width_for_moves(m.body_width, m.length, m.wheelbase, m.turning_radius, 3,
                                                c=SIDE_CLEARANCE_M, T=m.track)
            worst = max(worst, w)
        _tp[pid] = worst
        _TP_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _TP_CACHE.write_text(json.dumps(_tp, indent=1))
    return _tp[pid]
