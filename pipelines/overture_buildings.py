"""PIPELINE 4a: building footprints for urban HCMC from Overture Maps (Microsoft ML + Google Open Buildings + OSM).

One-off extract: Overture's global building theme is read over HTTP with DuckDB and filtered to the HCMC
urban bbox; only id, source and the footprint (WKB) are kept.
Output: data/raw/overture/hcmc_buildings.parquet (gitignored; the derived alley gaps are what ships).

Run:  python3 pipelines/overture_buildings.py [--release 2026-09-23.1]
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "raw" / "overture" / "hcmc_buildings.parquet"
# Urban HCMC (old districts 1–12, Bình Thạnh, Phú Nhuận, Gò Vấp, Tân Bình, Tân Phú, Bình Tân, inner Thủ Đức).
BBOX = (106.56, 10.68, 106.84, 10.90)  # w, s, e, n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="2026-09-23.1")
    a = ap.parse_args()
    w, s, e, n = BBOX
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial; SET s3_region='us-west-2';")
    t = time.time()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    con.execute(f"""
        COPY (
          SELECT id, sources[1].dataset AS source, geometry
          FROM read_parquet('s3://overturemaps-us-west-2/release/{a.release}/theme=buildings/type=building/*',
                            hive_partitioning=1)
          WHERE bbox.xmin >= {w} AND bbox.xmax <= {e} AND bbox.ymin >= {s} AND bbox.ymax <= {n}
        ) TO '{OUT}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    rows = con.execute(f"SELECT source, count(*) FROM '{OUT}' GROUP BY 1 ORDER BY 2 DESC").fetchall()
    print(f"{sum(r[1] for r in rows)} buildings in {time.time() - t:.0f}s -> {OUT}")
    for src, cnt in rows:
        print(f"  {src}: {cnt}")


if __name__ == "__main__":
    main()
