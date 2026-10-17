"""Small, mtime-cached public coverage summary; never reads credentials or calls AI."""
from __future__ import annotations

import json
import threading

from .config import CACHE
from . import flags, footprints
from .flood import tide_meta

_guard = threading.Lock()
_stamp, _summary = None, {}
_width_stamp, _width_summary = None, {}


def width_summary():
    """Unique ways by strongest *width evidence*, excluding OSM road-class priors.

    Cohort is the footprint job's bbox and drivable non-main road classes.
    Named/tagged alleys are reported separately from the broader road cohort.
    """
    global _width_stamp, _width_summary
    from .evidence import STORE_EVIDENCE, TIERS, _norm_alley, _osm_bounds
    from .osm import Way
    stamp, product = footprints.snapshot()
    if not product:
        return {"footprints_available": False}
    paths = [CACHE / "live/city_parcels.json", *sorted((CACHE / "live/areas").glob("*.json"))]
    def file_stamp(p):
        try:
            s = p.stat()
            return str(p), s.st_mtime_ns, s.st_size
        except OSError:
            return str(p), None
    key = (stamp, tuple(map(file_stamp, paths)), STORE_EVIDENCE.version,
           tuple((f["name"], f["enabled"]) for f in flags.describe()))
    if key == _width_stamp:
        return _width_summary
    by_tier = {t: set() for t in TIERS}
    cohort = product.get("cohort", {})
    alleys = {wid for wid, r in cohort.items() if r.get("is_alley")}
    for wid, r in cohort.items():
        w = Way(int(wid), r.get("tags", {}), [])
        external = STORE_EVIDENCE.by_way.get(w.id, []) + STORE_EVIDENCE.by_name.get(_norm_alley(w.name), [])
        for b in external + [b for b in _osm_bounds(w) if b.tier != "Inferred"]:
            if (not b.feature or flags.enabled(b.feature)) and b.feature != "footprint_widths":
                by_tier[b.tier].add(wid)
    if flags.enabled("footprint_widths"):
        by_tier["Inferred"].update(product["ways"])
    if flags.enabled("parcel_widths"):
        for p in paths:
            try:
                data = json.loads(p.read_text())
                rows = data.get("parcels", []) if p.parent.name == "areas" else [{"way_id": k, **v} for k, v in data.items() if isinstance(v, dict)]
                by_tier["Official"].update(str(r["way_id"]) for r in rows if r.get("samples") and str(r["way_id"]) in cohort)
            except (OSError, ValueError):
                continue
    assigned, strongest = set(), {}
    for tier in TIERS:
        strongest[tier] = by_tier[tier] - assigned
        assigned |= by_tier[tier]
    _width_summary = {"footprints_available": True,
        "width_scope_bbox_wsen": product.get("bbox_wsen"),
        "width_scope": "OSM drivable non-main roads; named/tagged alleys are a subset. Road-class priors excluded.",
        "non_main_drivable_ways_total": len(cohort), "ways_with_any_width": len(assigned),
        "ways_with_any_width_pct": round(100 * len(assigned) / max(1, len(cohort)), 2),
        "ways_by_strongest_width_tier": {t: len(ids) for t, ids in strongest.items()},
        "ways_with_width_by_tier": {t: len(ids) for t, ids in by_tier.items()},
        "alleys_total": len(alleys), "alleys_with_any_width": len(assigned & alleys),
        "alleys_with_any_width_pct": round(100 * len(assigned & alleys) / max(1, len(alleys)), 2),
        "alleys_by_strongest_width_tier": {t: len(ids & alleys) for t, ids in strongest.items()},
        "footprint_widths_enabled": flags.enabled("footprint_widths"),
        "footprint_stats": product.get("stats", {}),
        "footprint_calibration": product.get("calibration", {}),
        "footprint_release": product.get("dataset", {}).get("release"),
        "footprint_quality": product.get("calibration", {}).get("quality"),
        "footprint_generated_at": product.get("generated_at")}
    _width_stamp = key
    return _width_summary


def summary():
    global _stamp, _summary
    state_path = CACHE / "live/crawl_city_state.json"
    tide_status = CACHE / "flood/tide_refresh_status.json"
    paths = [state_path, tide_status]
    def stamp(path):
        try:
            s = path.stat()
            return s.st_mtime_ns, s.st_size
        except OSError:
            return None
    key = tuple(map(stamp, paths))
    with _guard:
        if key != _stamp:
            def read(path):
                try:
                    return json.loads(path.read_text())
                except (OSError, ValueError):
                    return {}
            state, refresh = map(read, paths)
            _summary = {"label": "Dữ liệu", "scope": state.get("scope", "TP.HCM"),
                        "ways_measured": state.get("ways_measured", 0),
                        "ways_with_cadastral_width": state.get("ways_with_data", 0),
                        "ways_deep_with_cadastral_width": state.get("ways_deep_with_data", 0),
                        "alleys_with_cadastral_width": state.get("alleys_with_data", 0),
                        "cells_visited": len(state.get("cells_visited", [])),
                        "cells_complete": len(state.get("cells_done", [])),
                        "cells_target": state.get("cells_target", 0),
                        "osm_cells_cached": state.get("osm_cells_cached", 0),
                        "osm_cells_target": state.get("osm_cells_target", 0),
                        "districts_visited": len(state.get("districts_visited", [])),
                        "districts_target": state.get("districts_target", 17),
                        "last_crawl_at": state.get("updated_at"),
                        "sampling": state.get("method", "shallow"),
                        "stage": state.get("stage", "city_breadth"),
                        "campuses": state.get("campuses", {}),
                        "all_results_deep": False, "tide_refresh_state": refresh.get("state", "pending"),
                        "tide_checked_at": refresh.get("checked_at"),
                        "note": "Bề rộng suy từ ranh thửa tại các mặt cắt đã lấy mẫu; thời gian cập nhật là lúc truy vấn, không phải ngày đo đạc địa chính."}
            _stamp = key
        # tide_meta is independently invalidated after an atomic bulletin update.
        return {**_summary, **width_summary(), "tide_bulletin_issued_at": tide_meta().get("issued_at")}
