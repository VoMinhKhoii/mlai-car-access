"""Open-data footprint widths. Never contacts the cadastral portal or an AI API.

python3 pipelines/footprints_city.py fetch|roads|measure|calibrate|all [--workers 6]
Large inputs and per-cut diagnostics stay under gitignored data/raw/buildings.
Dependencies: duckdb, shapely>=2, numpy (matplotlib for the separate renderer).
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time

import duckdb
import numpy as np
import shapely
from shapely.geometry import LineString, Point, box
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/buildings"
OUT = ROOT / "backend/cache/live/footprint_widths.json"
RELEASE = "2026-09-23.1"
BBOX = (106.55, 10.68, 106.88, 10.90)  # west, south, east, north
# Extra 30 m halo means rays at the study boundary have complete building data.
HALO = .0003
KX, KY = 111_320 * math.cos(math.radians(10.79)), 110_540
STEP, RAY = 10., 15.


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")))
    os.replace(tmp, path)


def xy(lon, lat):
    return (lon - BBOX[0]) * KX, (lat - BBOX[1]) * KY


def fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    path = RAW / "hcmc_buildings.parquet"
    if path.exists() and (RAW / "manifest.json").exists():
        return
    started = time.monotonic()
    c = duckdb.connect()
    c.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    c.execute("SET s3_region='us-west-2'; SET threads=8;")
    w, s, e, n = BBOX
    uri = f"s3://overturemaps-us-west-2/release/{RELEASE}/theme=buildings/type=building/*"
    tmp = path.with_suffix(".tmp.parquet")
    c.execute(f"""COPY (SELECT id, sources[1].dataset AS source, ST_AsWKB(geometry) AS geometry
        FROM read_parquet('{uri}', hive_partitioning=1)
        WHERE bbox.xmin <= {e+HALO} AND bbox.xmax >= {w-HALO}
        AND bbox.ymin <= {n+HALO} AND bbox.ymax >= {s-HALO})
        TO '{tmp}' (FORMAT PARQUET, COMPRESSION ZSTD)""")
    os.replace(tmp, path)
    sources = dict(c.execute(f"SELECT source,count(*) FROM '{path}' GROUP BY 1").fetchall())
    atomic(RAW / "manifest.json", {"dataset": "Overture Maps buildings", "release": RELEASE,
        "uri": uri, "bbox_wsen": BBOX, "halo_degrees": HALO,
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
        "license": "ODbL-1.0 (Overture buildings theme)",
        "upstream_licenses": {"OpenStreetMap": "ODbL-1.0", "Microsoft ML Buildings": "ODbL-1.0",
                              "Google Open Buildings": "CC-BY-4.0"},
        "attribution": "© OpenStreetMap contributors, Overture Maps Foundation; Microsoft; Google Open Buildings",
        "license_url": "https://docs.overturemaps.org/attribution/#buildings",
        "sources": sources, "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "download_seconds": round(time.monotonic()-started, 1)})
    print("BUILDINGS", sources, flush=True)


def roads():
    """Reuse the complete older extract plus crawler-owned batches (read only).

    Query only uncovered bbox strips; sequential Overpass, no mirror racing.
    Road ways include full OSM node IDs, enabling offline plan verification.
    """
    RAW.mkdir(parents=True, exist_ok=True)
    by_id, origins = {}, []
    old = ROOT / "data/raw/overture/hcmc_small_roads.json"
    if old.exists():
        by_id.update({r["id"]: r for r in json.loads(old.read_text())})
        origins.append({"path": str(old.relative_to(ROOT)), "mtime": old.stat().st_mtime,
                        "bbox_wsen": [106.56, 10.68, 106.84, 10.90]})
    for p in sorted((ROOT / "backend/cache/osm/city_batches").glob("*.json")):
        try:
            d = json.loads(p.read_text())
            nodes = {r["id"]: [r["lon"], r["lat"]] for r in d["elements"] if r["type"] == "node"}
            for r in d["elements"]:
                if r["type"] == "way" and r.get("tags", {}).get("highway"):
                    coords = [nodes[i] for i in r.get("nodes", []) if i in nodes]
                    if len(coords) >= 2:
                        by_id[r["id"]] = {"id": r["id"], "tags": r["tags"], "coords": coords,
                                            "nodes": r.get("nodes", [])}
            origins.append({"path": str(p.relative_to(ROOT)), "mtime": p.stat().st_mtime,
                            "cache": d.get("_cache")})
        except (OSError, ValueError, KeyError):
            continue
    # Existing extract covers the central rectangle; these four strips close its
    # west/east gaps, with modest overlap. Results belong only to this pipeline.
    import httpx
    strips = [(10.68,106.55,10.79,106.561), (10.79,106.55,10.90,106.561),
              (10.68,106.839,10.79,106.88), (10.79,106.839,10.90,106.88)]
    if not old.exists():
        strips += [(10.68,106.56,10.79,106.84), (10.79,106.56,10.90,106.84)]
    for i, bounds in enumerate(strips):
        p = RAW / f"roads_strip_{i}.json"
        if p.exists():
            d = json.loads(p.read_text())
        else:
            q = '[out:json][timeout:120];way["highway"~"^(residential|living_street|service|unclassified|road)$"](' + ','.join(map(str,bounds)) + ');out tags geom;'
            for endpoint in ["https://overpass.kumi.systems/api/interpreter", "https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
                             "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]:
                try:
                    with httpx.Client(timeout=240, headers={"User-Agent":"NgoNgach-open-widths/1.0 (hackathon; minhkhoitdn@gmail.com)"}) as client:
                        client.headers.pop("accept", None)
                        r = client.post(endpoint, data={"data":q}) if "kumi" in endpoint else client.get(endpoint, params={"data":q})
                    r.raise_for_status(); d = r.json()
                    if "remark" in d or not d.get("elements"):
                        raise ValueError("incomplete Overpass response")
                    d["fetched_at"] = datetime.now(timezone.utc).isoformat()
                    atomic(p,d)
                    time.sleep(3)
                    break
                except (httpx.HTTPError, ValueError) as exc:
                    print("OVERPASS", endpoint, str(exc)[:180], flush=True)
            else:
                raise RuntimeError(f"Could not fetch strip {bounds}; incomplete coverage, refusing to publish")
        for r in d["elements"]:
            if r["type"] == "way" and len(r.get("geometry", [])) >= 2:
                by_id[r["id"]] = {"id":r["id"], "tags":r.get("tags", {}), "nodes":r.get("nodes", []),
                                    "coords":[[v["lon"],v["lat"]] for v in r["geometry"]]}
        origins.append({"path":str(p.relative_to(ROOT)), "bbox_swen":bounds,
                        "fetched_at":d.get("fetched_at") or datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),
                        "osm_timestamp":d.get("osm3s",{}).get("timestamp_osm_base")})
    # Study cohort: all drivable non-main classes. Same car/access rules as app.osm.
    import sys
    sys.path.insert(0,str(ROOT / "backend"))
    from app.osm import Way, MAIN
    study = box(*BBOX)
    selected = []
    for r in by_id.values():
        way = Way(r["id"],r["tags"],[])
        if way.drivable and way.highway not in MAIN and study.intersects(LineString(r["coords"])):
            r["is_alley"] = way.is_alley
            selected.append(r)
    atomic(RAW / "roads.json", selected)
    atomic(RAW / "roads_manifest.json", {"sources":origins,"count":len(selected),"bbox_wsen":BBOX,
        "license":"ODbL-1.0", "attribution":"© OpenStreetMap contributors",
        "note":"Mixed cache dates; not a fresh city-wide OSM snapshot. Only bbox extension strips fetched today."})
    print("ROADS",len(selected), flush=True)


def section(line, d, tree, polys, sources):
    p = line.interpolate(d)
    a,b = line.interpolate(max(0,d-1)),line.interpolate(min(line.length,d+1))
    dx,dy = b.x-a.x,b.y-a.y
    norm = math.hypot(dx,dy)
    if norm < 1e-8:
        return {"status":"degenerate"}
    nx,ny = -dy/norm,dx/norm
    # A roof spanning the centreline is a failed observation, never a wide gap.
    if any(polys[i].covers(p) for i in tree.query(p)):
        return {"status":"inside_building"}
    hits=[]
    for sign in (-1,1):
        ray=LineString([(p.x,p.y),(p.x+sign*nx*RAY,p.y+sign*ny*RAY)])
        nearest=None
        for i in tree.query(ray):
            hit=ray.intersection(polys[i])
            if not hit.is_empty:
                dist=p.distance(hit)
                if nearest is None or dist < nearest[0]:
                    nearest=(dist,int(i))
        hits.append(nearest)
    if any(h is None for h in hits):
        return {"status":"open_side"}
    if hits[0][1] == hits[1][1] or min(h[0] for h in hits) < .3:
        return {"status":"misaligned"}
    return {"status":"ok", "gap_m":round(sum(h[0] for h in hits),3),
            "sources":" + ".join(sorted(set(sources[h[1]] for h in hits)))}


def measure_tile(job):
    key, ways, cal_cuts, signature = job
    path = RAW / f"tiles_{signature}" / f"{key}.json"
    if path.exists():
        return json.loads(path.read_text())
    c=duckdb.connect(); c.execute("SET threads=1; LOAD spatial;")
    # Tile selection uses *whole way bounds* plus a ray halo, not just its midpoint.
    coords=np.asarray([p for w in ways for p in w["coords"]])
    lo=coords.min(axis=0)-HALO;hi=coords.max(axis=0)+HALO
    rows=c.execute(f"""SELECT source, geometry FROM '{RAW / 'hcmc_buildings.parquet'}'
        WHERE ST_Intersects(ST_GeomFromWKB(geometry),ST_MakeEnvelope({lo[0]},{lo[1]},{hi[0]},{hi[1]}))""").fetchall()
    c.close()
    geoms=shapely.from_wkb([bytes(r[1]) for r in rows])
    # Keep multipolygons, holes and full polygon interiors. Vectorised projection.
    geoms=shapely.transform(geoms,lambda a: (a-np.array(BBOX[:2]))*np.array([KX,KY]))
    valid=shapely.is_valid(geoms)
    if not valid.all():
        geoms[~valid]=shapely.make_valid(geoms[~valid])
    src=[r[0] or "unknown" for r in rows]
    tree=STRtree(geoms)
    results, matched = {}, []
    for w in ways:
        line=LineString([xy(*v) for v in w["coords"]])
        if line.length < 1:
            results[str(w["id"])]=dict(attempted=0,valid=0,status_counts={"degenerate_way":1},samples=[],is_alley=w["is_alley"])
            continue
        # Skip junction flares; short ways still receive a midpoint observation.
        ds=list(np.arange(5.,line.length-5.+1e-8,STEP)) if line.length >= 10 else [line.length/2]
        if not ds: ds=[line.length/2]
        cuts=[]
        for d in ds:
            p=line.interpolate(d)
            if not (0<=p.x<=(BBOX[2]-BBOX[0])*KX and 0<=p.y<=(BBOX[3]-BBOX[1])*KY):
                continue
            cuts.append({"at_m":round(float(d),2),**section(line,float(d),tree,geoms,src)})
        good=[v["gap_m"] for v in cuts if v["status"]=="ok"]
        r={"attempted":len(cuts),"valid":len(good),"status_counts":dict(Counter(v["status"] for v in cuts)),
           "samples":cuts,"is_alley":w["is_alley"]}
        if good:
            r.update(p10=round(float(np.quantile(good,.1)),3),p20=round(float(np.quantile(good,.2)),3),
                     median=round(float(np.median(good)),3),
                     source=Counter(v["sources"] for v in cuts if v["status"]=="ok").most_common(1)[0][0])
        results[str(w["id"])]=r
        for cut in cal_cuts.get(str(w["id"]),[]):
            # Match the exact cadastral location rather than comparing unrelated way medians.
            point=Point(*xy(cut["lon"],cut["lat"]))
            d=line.project(point)
            if point.distance(line)>2:
                continue
            obs=section(line,d,tree,geoms,src)
            if obs["status"]=="ok":
                matched.append({"way_id":w["id"],"lat":cut["lat"],"lon":cut["lon"],
                    "official_gap_m":cut["gap_m"],"footprint_gap_m":obs["gap_m"],"source":obs["sources"]})
    result={"ways":results,"matched_cuts":matched}
    atomic(path,result)
    return result


def cadastral_snapshot():
    """Read only, deduplicate identical cuts; capture inputs so evaluation is reproducible."""
    existing = RAW / "cadastral_snapshot.json"
    if existing.exists():
        return json.loads(existing.read_text())["ways"]
    merged=defaultdict(dict)
    paths=[ROOT / "backend/cache/live/city_parcels.json",*sorted((ROOT / "backend/cache/live/areas").glob("*.json"))]
    provenance=[]
    for p in paths:
        if not p.exists():continue
        content=p.read_bytes(); data=json.loads(content)
        rows=data.get("parcels",[]) if p.parent.name=="areas" else [{"way_id":k,**v} for k,v in data.items() if isinstance(v,dict)]
        provenance.append({"path":str(p.relative_to(ROOT)),"sha256":hashlib.sha256(content).hexdigest()})
        for r in rows:
            for cut in r.get("cuts",[]):
                if all(k in cut for k in ("lat","lon","gap_m")):
                    merged[str(r["way_id"])][(round(cut["lat"],7),round(cut["lon"],7))]=cut
    out={k:list(v.values()) for k,v in merged.items()}
    atomic(RAW / "cadastral_snapshot.json",{"inputs":provenance,"ways":out})
    return out


def measure(workers):
    started=time.monotonic()
    ways=json.loads((RAW / "roads.json").read_text())
    cuts=cadastral_snapshot()
    signature=hashlib.sha256(("v2:" + str(STEP) + str(RAY) + ":" +
        json.loads((RAW / "manifest.json").read_text())["sha256"] + ":" +
        hashlib.sha256((RAW / "roads.json").read_bytes()).hexdigest() + ":" +
        hashlib.sha256((RAW / "cadastral_snapshot.json").read_bytes()).hexdigest()).encode()).hexdigest()[:12]
    tiles=defaultdict(list)
    for w in ways:
        lon,lat=w["coords"][len(w["coords"])//2]
        tiles[f"{int((lon-BBOX[0])/.04)}_{int((lat-BBOX[1])/.04)}"].append(w)
    results,matched={},[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i,r in enumerate(pool.map(measure_tile,[(k,v,cuts,signature) for k,v in sorted(tiles.items())])):
            results.update(r["ways"]);matched.extend(r["matched_cuts"])
            print(f"TILES {i+1}/{len(tiles)} ways={len(results)} matches={len(matched)} elapsed={time.monotonic()-started:.0f}s",flush=True)
    atomic(RAW / "measurements.json",results)
    atomic(RAW / "matched_cuts.json",matched)
    atomic(RAW / "runtime.json",{"measurement_seconds":round(time.monotonic()-started,1),"workers":workers,
        "step_m":STEP,"ray_m":RAY,"tiles":len(tiles),"sampled_at":datetime.now(timezone.utc).isoformat(),
        "input_signature":signature,"software":{"duckdb":duckdb.__version__,"shapely":shapely.__version__,"numpy":np.__version__}})


def metrics(errors):
    a=np.asarray(errors)
    if len(a)==0:return {"n":0}
    return {"n":len(a),"bias_m":round(float(np.mean(a)),3),"median_signed_m":round(float(np.median(a)),3),
            "median_absolute_m":round(float(np.median(abs(a))),3),"mae_m":round(float(np.mean(abs(a))),3),
            "p90_absolute_m":round(float(np.quantile(abs(a),.9)),3)}


def calibrate():
    measured=json.loads((RAW / "measurements.json").read_text())
    matches=json.loads((RAW / "matched_cuts.json").read_text())
    # Weight ways equally: deep-scanned ways must not dominate the calibration.
    per_way=defaultdict(list)
    for r in matches:per_way[str(r["way_id"])].append(r)
    pairs=[]
    for wid,rows in per_way.items():
        pairs.append({"way_id":wid,"source":Counter(r["source"] for r in rows).most_common(1)[0][0],
            "error":float(np.median([r["footprint_gap_m"]-r["official_gap_m"] for r in rows])),
            "footprint_gap":float(np.median([r["footprint_gap_m"] for r in rows])),
            "official_gap":float(np.median([r["official_gap_m"] for r in rows]))})
    # Deterministic way-disjoint 60/20/20 fit, residual calibration, test.
    split=lambda wid:int(hashlib.sha256(str(wid).encode()).hexdigest()[:8],16)%10
    fit=[r for r in pairs if split(r["way_id"])<6]
    cal=[r for r in pairs if 6<=split(r["way_id"])<8]
    test=[r for r in pairs if split(r["way_id"])>=8]
    if min(len(fit),len(cal),len(test))<10:
        raise RuntimeError("Too few independent matched ways for honest calibration")
    bias=float(np.median([r["error"] for r in fit]))
    # 90% split-conformal absolute residual radius; finite sample rank, no interpolation.
    residual=sorted(abs(r["error"]-bias) for r in cal)
    radius=max(1.,residual[min(len(residual)-1,math.ceil((len(residual)+1)*.9)-1)])
    by_source={s:metrics([r["error"] for r in pairs if r["source"]==s]) for s in sorted({r["source"] for r in pairs})}
    accepted={k:v for k,v in measured.items() if v["valid"]>=3 and v["valid"]/max(1,v["attempted"])>=.4}
    # Way bottleneck residuals independently widen the band: a median-only calibration
    # must not pretend it validates a p10 bottleneck estimate.
    official=json.loads((RAW / "cadastral_snapshot.json").read_text())["ways"]
    bottleneck=[]
    for r in cal:
        wid=r["way_id"]
        if wid in accepted:
            target=float(np.quantile([v["gap_m"] for v in official[wid]],.2))
            bottleneck.append(abs(accepted[wid]["p10"]-bias-target))
    if bottleneck:
        radius=max(radius,sorted(bottleneck)[min(len(bottleneck)-1,math.ceil((len(bottleneck)+1)*.9)-1)])
    calibration={"matched_cuts":len(matches),"matched_ways":len(pairs),"raw_way_error":metrics([r["error"] for r in pairs]),
        "raw_cut_error":metrics([r["footprint_gap_m"]-r["official_gap_m"] for r in matches]),
        "by_source":by_source,"fit_ways":len(fit),"calibration_ways":len(cal),"test_ways":len(test),
        "bias_correction_m":round(bias,3),"uncertainty_radius_m":round(radius,3),
        "test_corrected_error":metrics([r["error"]-bias for r in test]),
        "test_interval_coverage":round(sum(abs(r["error"]-bias)<=radius for r in test)/len(test),3),
        "bottleneck_calibration_ways":len(bottleneck),
        "split":"sha256(OSM way id) mod 10: 0–5 fit, 6–7 residual calibration, 8–9 test",
        "limitations":"Convenience sample concentrated near cadastral scans; way-disjoint holdout is not geographic validation. Roofprints do not observe clear width or obstacles. Radius calibrated against parcel gaps, not tape measurements."}
    baseline=float(np.median([r["official_gap"] for r in fit]))
    calibration["test_constant_baseline_error"]=metrics([baseline-r["official_gap"] for r in test])
    calibration["test_gap_pearson_r"]=round(float(np.corrcoef([r["footprint_gap"] for r in test],[r["official_gap"] for r in test])[0,1]),3)
    calibration["quality"]="exploratory_not_vehicle_decisive"
    calibration["cadastral_snapshot_ways"]=len(official)
    calibration["cadastral_snapshot_cuts"]=sum(map(len,official.values()))
    result={}
    for wid,r in accepted.items():
        # Same 1 m encroachment assumption as cadastral usable widths. Additional
        # 0.5 m on each side explicitly allows uncalibrated obstacle variability.
        estimate=max(.5,r["p10"]-bias-1.)
        lo=max(.5,estimate-radius-.5)
        hi=max(lo,max(.5,r["median"]-bias-1.)+radius+.5)
        result[wid]={"lo":round(lo,2),"hi":round(min(39.9,hi),2),"estimate_m":round(estimate,2),
            "gap_p10_m":r["p10"],"gap_median_m":r["median"],"samples":r["valid"],
            "attempted":r["attempted"],"source":r["source"],"is_alley":r["is_alley"]}
    states=Counter()
    for r in measured.values():states.update(r["status_counts"])
    manifest=json.loads((RAW / "manifest.json").read_text())
    stats={"ways_total":len(measured),"ways_with_footprint_width":len(result),
        "ways_with_any_two_sided_sample":sum(r["valid"]>0 for r in measured.values()),
        "percent_with_footprint_width":round(100*len(result)/max(1,len(measured)),2),
        "named_or_tagged_alleys_total":sum(r["is_alley"] for r in measured.values()),
        "named_or_tagged_alleys_with_footprint_width":sum(r["is_alley"] for r in result.values()),
        "sample_states":dict(states)}
    atomic(OUT,{"schema_version":1,"generated_at":datetime.now(timezone.utc).isoformat(),"tier":"Inferred",
        "bbox_wsen":BBOX,"dataset":manifest,"calibration":calibration,"stats":stats,
        "runtime":json.loads((RAW / "runtime.json").read_text()),"ways":result,
        "cohort":{str(r["id"]):{"is_alley":r["is_alley"],"tags":r["tags"]}
                  for r in json.loads((RAW / "roads.json").read_text()) if str(r["id"]) in measured}})
    report={"dataset":manifest,"stats":stats,"calibration":calibration,
        "roads":json.loads((RAW / "roads_manifest.json").read_text()),
        "calibration_inputs":json.loads((RAW / "cadastral_snapshot.json").read_text())["inputs"],
        "runtime":json.loads((RAW / "runtime.json").read_text())}
    atomic(ROOT / "docs/eval/footprint-calibration.json",report)
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)


if __name__=="__main__":
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("stage",choices=["fetch","roads","measure","calibrate","all"])
    ap.add_argument("--workers",type=int,default=min(6,os.cpu_count() or 1))
    args=ap.parse_args()
    for name,fn in [("fetch",fetch),("roads",roads),("measure",lambda:measure(args.workers)),("calibrate",calibrate)]:
        if args.stage in (name,"all"):fn()
