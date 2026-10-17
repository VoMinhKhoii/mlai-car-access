"""Urban HCMC schedule: 17 districts in 2021, including former Q2/Q9/Thủ Đức.

District population density and locally available OSM alley density determine priority.
Round-robin districts so a large dense district cannot monopolize the first night.
The dated administrative source is scheduling data, never cadastral evidence.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from shapely.geometry import Point, box, shape
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parents[1]
SCOPE = ROOT / "data/official/hcmc_urban_districts_2021.geojson"


@lru_cache(maxsize=1)
def districts():
    out = []
    for f in json.loads(SCOPE.read_text())["features"]:
        p, poly = f["properties"], shape(f["geometry"])
        out.append({**p, "poly": poly, "prepared": prep(poly),
                    "density": p["population_2021"] / p["area_km2"]})
    return sorted(out, key=lambda d: -d["density"])


@lru_cache(maxsize=1)
def alley_density():
    """An existing extract ranks cells; fresh Overpass remains the source of graph data."""
    counts = Counter()
    path = ROOT / "data/raw/overture/hcmc_small_roads.json"
    if path.exists():
        for w in json.loads(path.read_text()):
            tags, coords = w.get("tags", {}), w.get("coords", [])
            if coords and (tags.get("service") == "alley" or tags.get("name", "").lower().startswith(("hẻm", "hem"))):
                lon, lat = coords[len(coords) // 2]
                counts[(round(lat / .012), round(lon / .012))] += 1
    return counts


def schedule(step=.012):
    """Include boundary-straddling cells. Ordering never depends on the demo address."""
    import math
    density, queues, seen = alley_density(), [], set()
    for d in districts():
        w, s, e, n = d["poly"].bounds
        points = []
        for i in range(math.floor(s / step), math.ceil(n / step) + 1):
            for j in range(math.floor(w / step), math.ceil(e / step) + 1):
                lat, lon = round(i * step, 4), round(j * step, 4)
                if d["prepared"].intersects(box(lon - step / 2, lat - step / 2,
                                                lon + step / 2, lat + step / 2)):
                    points.append({"lat": lat, "lon": lon, "district": d["name"], "district_id": d["id"],
                                   "population_density_2021": round(d["density"]),
                                   "alley_density_prior": density[(round(lat / .012), round(lon / .012))]})
        points.sort(key=lambda p: (-p["alley_density_prior"], p["lat"], p["lon"]))
        queues.append(points)
    out = []
    for i in range(max(map(len, queues))):
        for queue in queues:
            if i < len(queue):
                p = queue[i]
                key = (p["lat"], p["lon"])
                if key not in seen:
                    seen.add(key)
                    out.append(p)
    return out


def contains(lat, lon):
    return any(d["prepared"].covers(Point(lon, lat)) for d in districts())
