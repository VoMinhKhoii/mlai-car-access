"""PIPELINE 4b: alley width from the gap between building footprints (D31).

For every small road in urban HCMC (OSM residential / living_street / service / unclassified), sample points
every 6 m (skipping 8 m at each end, where junctions open up), cast a ray perpendicular to the road on each
side, and measure the distance to the first building footprint (Overture: Microsoft ML + Google Open
Buildings + OSM). Where both sides hit a building within 12 m, the sum is the building-to-building gap.

The gap is an UPPER bound on Clear Width: steps, awnings, parked motorbikes and stalls only narrow it.
Per way we keep the median and 25th percentile of the gaps and the share of samples with walls on both
sides; ways with fewer than 3 such samples are dropped.

Inputs:  data/raw/overture/hcmc_buildings.parquet (pipelines/overture_buildings.py), OSM via Overpass
Output:  data/processed/building_gaps_hcmc.json  {way_id: {"median": m, "p25": m, "n": samples, "walled": share}}

Run:  python3 pipelines/building_gaps.py
"""
from __future__ import annotations

import json
import math
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import httpx
from shapely import wkb
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
BUILDINGS = ROOT / "data" / "raw" / "overture" / "hcmc_buildings.parquet"
ROADS_CACHE = ROOT / "data" / "raw" / "overture" / "hcmc_small_roads.json"
OUT = ROOT / "data" / "processed" / "building_gaps_hcmc.json"
BBOX = (10.68, 106.56, 10.90, 106.84)  # s, w, n, e (same as the building extract)
TILES = 8                              # Overpass tiles per side (smaller tiles avoid 504s)
STEP, END_SKIP, RAY = 6.0, 8.0, 12.0
MIN_SAMPLES = 3
LAT0 = (BBOX[0] + BBOX[2]) / 2
KX, KY = 111_320 * math.cos(math.radians(LAT0)), 110_540  # metres per degree
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
            "https://overpass.kumi.systems/api/interpreter"]


def xy(lon: float, lat: float) -> tuple[float, float]:
    return ((lon - BBOX[1]) * KX, (lat - BBOX[0]) * KY)


def fetch_roads() -> list[dict]:
    if ROADS_CACHE.exists():
        return json.loads(ROADS_CACHE.read_text())
    s, w, n, e = BBOX
    ds, dw = (n - s) / TILES, (e - w) / TILES
    tiles = [(s + i * ds, w + j * dw, s + (i + 1) * ds, w + (j + 1) * dw) for i in range(TILES) for j in range(TILES)]

    tile_dir = ROADS_CACHE.parent / "road_tiles"
    tile_dir.mkdir(parents=True, exist_ok=True)

    def one(t):
        path = tile_dir / ("_".join(f"{v:.4f}" for v in t) + ".json")
        if path.exists():
            return json.loads(path.read_text())
        q = (f'[out:json][timeout:180];way["highway"~"^(residential|living_street|service|unclassified)$"]'
             f'({t[0]},{t[1]},{t[2]},{t[3]});out tags geom;')
        last = None
        for attempt in range(4):
            for ep in OVERPASS:
                try:
                    r = httpx.post(ep, data={"data": q}, headers={"User-Agent": "VaoDuoc/0.3 (minhkhoitdn@gmail.com)"},
                                   timeout=240)
                    r.raise_for_status()
                    els = r.json()["elements"]
                    path.write_text(json.dumps(els))
                    return els
                except Exception as exc:  # next mirror, then retry the round
                    last = exc
            time.sleep(10 * (attempt + 1))
        raise RuntimeError(last)

    ways: dict[int, dict] = {}
    with ThreadPoolExecutor(2) as pool:
        for els in pool.map(one, tiles):
            for el in els:
                if el["type"] == "way" and len(el.get("geometry", [])) >= 2:
                    ways[el["id"]] = {"id": el["id"], "tags": el.get("tags", {}),
                                      "coords": [[p["lon"], p["lat"]] for p in el["geometry"]]}
    out = list(ways.values())
    ROADS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    ROADS_CACHE.write_text(json.dumps(out))
    return out


def load_buildings():
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    rows = con.execute(f"SELECT ST_AsWKB(geometry) FROM read_parquet('{BUILDINGS}')").fetchall()
    polys = []
    for (g,) in rows:
        geom = wkb.loads(bytes(g))
        if geom.is_empty:
            continue
        coords = geom.exterior.coords if geom.geom_type == "Polygon" else max(geom.geoms, key=lambda p: p.area).exterior.coords
        polys.append(LineString([xy(x, y) for x, y in coords]))  # boundaries: rays stop at the first wall
    return polys


def gaps_for(line: LineString, tree: STRtree, walls: list) -> list[float]:
    out = []
    length = line.length
    d = END_SKIP
    while d <= length - END_SKIP:
        p = line.interpolate(d)
        a, b = line.interpolate(max(0.0, d - 1.0)), line.interpolate(min(length, d + 1.0))
        dx, dy = b.x - a.x, b.y - a.y
        norm = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / norm, dx / norm
        sides = []
        for sgn in (1, -1):
            ray = LineString([(p.x, p.y), (p.x + sgn * nx * RAY, p.y + sgn * ny * RAY)])
            best = None
            for i in tree.query(ray):
                hit = ray.intersection(walls[i])
                if hit.is_empty:
                    continue
                dist = p.distance(hit)
                best = dist if best is None else min(best, dist)
            sides.append(best)
        if all(s is not None for s in sides) and sum(sides) > 0.8:
            out.append(sides[0] + sides[1])
        d += STEP
    return out


def main() -> None:
    t = time.time()
    roads = fetch_roads()
    print(f"{len(roads)} small roads ({time.time() - t:.0f}s)")
    walls = load_buildings()
    tree = STRtree(walls)
    print(f"{len(walls)} building outlines indexed ({time.time() - t:.0f}s)")
    result = {}
    for k, w in enumerate(roads):
        line = LineString([xy(x, y) for x, y in w["coords"]])
        if line.length < 2 * END_SKIP + STEP:
            continue
        gaps = gaps_for(line, tree, walls)
        samples = int((line.length - 2 * END_SKIP) // STEP) + 1
        if len(gaps) < MIN_SAMPLES:
            continue
        gaps.sort()
        result[str(w["id"])] = {"median": round(statistics.median(gaps), 2), "p25": round(gaps[len(gaps) // 4], 2),
                                "n": len(gaps), "walled": round(len(gaps) / samples, 2)}
        if k % 20000 == 0:
            print(f"  {k}/{len(roads)} roads, {len(result)} measured ({time.time() - t:.0f}s)")
    OUT.write_text(json.dumps(result, separators=(",", ":")))
    print(f"{len(result)} ways measured -> {OUT} ({OUT.stat().st_size // 1024} KB, {time.time() - t:.0f}s)")


if __name__ == "__main__":
    main()
