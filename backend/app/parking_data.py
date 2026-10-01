"""Parking candidates (D18): OSM car parks, VETC lots and VETC-paid roadside streets."""
from __future__ import annotations

import json
from functools import lru_cache

from .config import DATA
from .osm import AreaGraph, haversine, strip_accents, MOTORBIKE_ONLY

VETC_LOTS = DATA / "processed" / "vetc_lots_hcmc.geojson"
VETC_STREETS = DATA / "processed" / "vetc_street_parking_hcmc.geojson"


@lru_cache(maxsize=1)
def _vetc_lots() -> list[dict]:
    if not VETC_LOTS.exists():
        return []
    out = []
    for f in json.loads(VETC_LOTS.read_text(encoding="utf-8")).get("features", []):
        p = f.get("properties", {})
        if not f.get("geometry") or p.get("vehicle") == "motorbike":
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        out.append({"id": f"vetc:{p.get('name')}", "lat": lat, "lon": lon, "name": p.get("name") or "Bãi đỗ VETC",
                    "address": p.get("address", ""), "source": "VETC",
                    "source_label": "Danh sách bãi đỗ thanh toán điện tử VETC 2026", "source_url": p.get("source_url", ""),
                    "live_spaces": None})
    return out


@lru_cache(maxsize=1)
def _vetc_streets() -> list[dict]:
    if not VETC_STREETS.exists():
        return []
    return [f for f in json.loads(VETC_STREETS.read_text(encoding="utf-8")).get("features", []) if f.get("geometry")]


def lots_near(g: AreaGraph, lat: float, lon: float, radius: float) -> list[dict]:
    out = []
    for lot in g.parking:
        t = lot["tags"]
        if t.get("amenity") != "parking" or t.get("access") in ("private", "no"):
            continue
        if t.get("motorcar") == "no" or MOTORBIKE_ONLY.search(t.get("name", "")):
            continue  # motorbike parking
        if haversine(lat, lon, lot["lat"], lot["lon"]) > radius:
            continue
        kind = {"underground": "Hầm đỗ ô tô", "multi-storey": "Bãi đỗ ô tô nhiều tầng"}.get(t.get("parking", ""), "Bãi đỗ ô tô")
        out.append({"id": f"osm:{lot['id']}", "lat": lot["lat"], "lon": lot["lon"],
                    "name": t.get("name") or kind, "access": t.get("access", ""),
                    "fee": t.get("fee"), "capacity": t.get("capacity"), "source": "OSM",
                    "source_label": "OpenStreetMap amenity=parking", "live_spaces": None})
    for lot in _vetc_lots():
        if haversine(lat, lon, lot["lat"], lot["lon"]) <= radius:
            out.append(dict(lot))
    return out


_PAID: dict[str, dict[int, dict]] = {}


def paid_street_ways(g: AreaGraph) -> dict[int, dict]:
    """Ways that lie on a VETC-paid roadside parking street (name match + within 25 m of the published line)."""
    if g.source in _PAID:
        return _PAID[g.source]
    out = {}
    for f in _vetc_streets():
        props = f.get("properties", {})
        key = strip_accents(props.get("street", "")).replace("duong ", "")
        coords = f["geometry"]["coordinates"]
        lines = coords if f["geometry"]["type"] == "MultiLineString" else [coords]
        pts = [pt for line in lines for pt in line]
        for w in g.ways.values():
            if not w.drivable or not key or key not in strip_accents(w.name):
                continue
            la, lo = g.nodes[w.nodes[len(w.nodes) // 2]]
            if any(haversine(la, lo, p[1], p[0]) < 25 for p in pts[:: max(1, len(pts) // 60)]):
                out[w.id] = props
    _PAID[g.source] = out
    return out
