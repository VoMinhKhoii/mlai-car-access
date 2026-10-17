"""Six offline HTTP plans through FastAPI's real ASGI app (no AI/portal/Goong).

PYTHONPATH=backend:. python3 pipelines/verify_footprints.py
Uses already cached area graphs; fails instead of fetching a missing graph.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
from unittest.mock import patch

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT / "backend"))
from app import flags, live, osm, plan
from app.main import app


def main():
    flags.describe()
    flags._state.update(footprint_widths=True, parcel_widths=True, building_gaps=False)
    product=json.loads((ROOT / "backend/cache/live/footprint_widths.json").read_text())
    roads={str(r["id"]):r for r in json.loads((ROOT / "data/raw/buildings/roads.json").read_text())}
    snapshot=json.loads((ROOT / "data/raw/buildings/cadastral_snapshot.json").read_text())["ways"]
    cases=[{"district":"Q8","way_id":193729286},
           {"district":"Gò Vấp","way_id":327452981},
           {"district":"Tân Phú","way_id":373721652}]
    official=live.city_parcels()
    chosen=[]
    for wid,pc in sorted(official.items(),key=lambda kv: -len((kv[1] or {}).get("samples",[]))):
        if not pc or wid not in roads or wid not in product["ways"]:continue
        r=roads[wid];lon,lat=r["coords"][len(r["coords"])//2]
        if osm.area_key(lat,lon)=="demo":
            chosen.append({"district":"Bình Thạnh","way_id":int(wid)})
        if len(chosen)==3:break
    if len(chosen)!=3:raise RuntimeError("Need three real Official/footprint overlaps")
    cases+=chosen
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    points=[Point(c["lon"],c["lat"]) for cuts in snapshot.values() for c in cuts]
    tree=STRtree(points)
    summaries=[]
    with patch.object(plan,"GOONG_API_KEY",""), patch.object(osm,"_fetch_overpass",side_effect=RuntimeError("Offline verification: no network graph fetch")):
        client=TestClient(app)  # no lifespan context: do not start tide refresh
        for i,case in enumerate(cases):
            wid=str(case["way_id"]);r=roads[wid]
            # Interior arc-length midpoint avoids a junction belonging to another way.
            from shapely.geometry import LineString
            pt=LineString(r["coords"]).interpolate(.5,normalized=True)
            lat,lon=pt.y,pt.x
            key=osm.area_key(lat,lon)
            path=osm.DEMO_FILE if key=="demo" else ROOT / f"backend/cache/osm/area_{key}.json"
            assert path.exists(),path
            body={"lat":lat,"lon":lon,"label":r["tags"].get("name",""),"vehicle_id":"toyota-vios",
                  "intent":"pickup","arrive_at":"2026-10-17T10:00:00+07:00","dwell_min":15}
            response=client.post("/api/plan",json=body)
            assert response.status_code==200,response.text[:500]
            data=response.json()
            (ROOT / f"data/raw/buildings/verification_{i+1}.json").write_text(json.dumps(data,ensure_ascii=False))
            door=data["door"]
            assert door and str(door["way_id"])==wid,(wid,door and door.get("way_id"))
            wr=door["fit"]["width_range"]
            footprint=[b for b in wr["evidence"] if b["ai_feature"]=="footprint_widths"]
            assert footprint,(wid,"no footprint evidence")
            assert all(b["tier"]=="Inferred" for b in footprint)
            if i<3:
                assert wid not in snapshot
                assert not any(b["tier"]=="Official" for b in wr["evidence"])
                assert door["fit"]["class"]=="unknown",door["fit"]
            else:
                assert wr["top_tier"]=="Official",wr
                assert any(b["ai_feature"]=="footprint_widths" for b in wr["overruled"])
                flags._state["footprint_widths"]=False
                off=client.post("/api/plan",json=body).json()["door"]["fit"]["width_range"]
                flags._state["footprint_widths"]=True
                assert (wr["lo"],wr["hi"],wr["top_tier"])==(off["lo"],off["hi"],off["top_tier"])
            summary={**case,"name":r["tags"].get("name",""),"request":body,
                "http_status":response.status_code,"area_key":key,
                "nearest_snapshot_cadastral_cut_m":round(pt.distance(points[tree.nearest(pt)])*109400),
                "door_fit":door["fit"]["class"],"width_range":{"lo":wr["lo"],"hi":wr["hi"],"top_tier":wr["top_tier"]},
                "footprint_source":footprint[0]["source"],"footprint_overruled":i>=3,
                "verdict":data["verdict"],"official_unchanged_with_flag_off":i>=3}
            summaries.append(summary)
            print(json.dumps(summary,ensure_ascii=False),flush=True)
        c=client.get("/api/config")
        assert c.status_code==200
        coverage=c.json()["coverage"]
        assert coverage["ways_with_any_width"]>=len(product["ways"])
        assert sum(coverage["ways_by_strongest_width_tier"].values())==coverage["ways_with_any_width"]
        assert sum(coverage["alleys_by_strongest_width_tier"].values())==coverage["alleys_with_any_width"]
        flags._state["footprint_widths"]=False
        default_coverage=client.get("/api/config").json()["coverage"]
        assert not default_coverage["footprint_widths_enabled"]
        assert default_coverage["ways_with_any_width"]<=coverage["ways_with_any_width"]
        (ROOT / "docs/eval/footprint-coverage.json").write_text(json.dumps({"experiment_enabled":coverage,
            "footprint_flag_off":default_coverage},ensure_ascii=False,indent=2))
    report={"method":"FastAPI TestClient HTTP /api/plan + /api/config; real cached graphs and parcel merges; outgoing OSM blocked; Goong disabled; no lifespan background worker.",
            "flags":{"footprint_widths":True,"parcel_widths":True,"building_gaps":False},"plans":summaries}
    (ROOT / "docs/eval/footprint-verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":main()
