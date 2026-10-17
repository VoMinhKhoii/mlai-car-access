#!/usr/bin/env python3
"""Read-only, network-denied algorithm audit. Writes only docs/eval/audit-*.

  python3 pipelines/audit_algorithm.py --probes
  python3 pipelines/audit_algorithm.py --sweep --n 300 --seed 3317
  python3 pipelines/audit_algorithm.py --profile

Probes report observed defects, rather than asserting the defective result must
remain. Engine patches below are process-local fixture injection, never edits.
"""
from __future__ import annotations

import argparse
import cProfile
import hashlib
import io
import json
import math
import pstats
import random
import socket
import statistics
import sys
import time
import traceback
from itertools import combinations
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/eval"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "backend"))


def deny_network(*args, **kwargs):
    raise RuntimeError("Audit forbids all network access")


socket.socket.connect = deny_network
socket.socket.connect_ex = deny_network
socket.create_connection = deny_network

from app import evidence as ev, flags, flood, geometry, legality, live, osm, parcels, plan as engine, vehicles

engine.GOONG_API_KEY = ""  # no external approach/standard-route calls
osm._fetch_overpass = deny_network
parcels._parcel = deny_network
vehicles._TP_CACHE = OUT / "audit-three-point.json"  # prevent cache mutation outside audit artifacts
ARRIVE = datetime.fromisoformat("2026-10-17T12:00:00+07:00")
IDS = ["vinfast-vf-3", "toyota-vios", "toyota-fortuner", "kia-carnival", "ford-transit"]
SOURCE_FILES = [ROOT / "backend/app" / (x + ".py") for x in
                ("plan", "evidence", "vehicles", "parcels", "geometry", "osm", "flood", "legality", "live", "config", "parking_data")]


def hashes():
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in SOURCE_FILES}


def save(name, obj):
    OUT.mkdir(exist_ok=True, parents=True)
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str) + "\n")


def xy(x, y):
    return (10.8 + y / parcels.KY, 106.71 + x / parcels.KX)


def graph(points, ways, node_tags=None, source="audit-fixture"):
    els = [{"type": "node", "id": n, "lat": xy(x, y)[0], "lon": xy(x, y)[1],
            "tags": (node_tags or {}).get(n, {})} for n, (x, y) in points.items()]
    els += [{"type": "way", "id": wid, "nodes": nodes,
             "tags": {"highway": "residential", "name": f"Audit {wid}", **tags}}
            for wid, nodes, tags in ways]
    return osm.graph_from_elements(*xy(0, 0), els, source)


def wr(lo=4., hi=None, tier="Official"):
    return ev.WidthRange(lo, hi if hi is not None else lo + .3, tier)


def exit_search(g, fit=None, weighted=False):
    fit = fit or {wid: "fits" for wid in g.ways}
    rev = defaultdict(list)
    for n, edges in g.drive_adj.items():
        for ei, m in edges:
            rev[m].append((ei, n))
    src = {n: 0 for w in g.ways.values() if w.kind == "main" for n in w.nodes}
    res = engine.dijkstra(rev, src, lambda ei: fit[g.edges[ei].way_id] in ("fits", "tight"),
                          lambda ei: engine._cost(g.edges[ei].length,fit[g.edges[ei].way_id]) if weighted else g.edges[ei].length)
    return {True: res, False: res}


def candidate(g, wid, offset, kind="door"):
    edge = next(e for e in g.edges if e.way_id == wid)
    la, lo = engine._interp(g, edge.u, edge.v, offset, edge.length)
    return engine.Candidate(kind, la, lo, "Audit stop", wid, edge.idx, offset, walk_m=0)


def fixture_plan(g, dest, widths=None, fps=None, vid="toyota-vios", intent="pickup", **kw):
    widths = widths or {wid: wr(8.) for wid in g.ways}
    with patch.object(engine, "area", return_value=(g, widths, fps or {})), \
         patch.object(engine.parking_data, "lots_near", return_value=[]):
        return engine.plan(*dest, vid, intent, ARRIVE, 15 if intent == "pickup" else 120, **kw)


def probes():
    rows = []

    def record(key, inp, actual, expected, triggered=True):
        rows.append(dict(id=key, input=inp, observed=actual, expected=expected, triggered=bool(triggered)))

    # A valid local choke point is deliberately discarded by D33's P20 rule.
    pc = {"way_id": 20, "samples": [1., 4., 4., 4., 4.],
          "cuts": [{"width_m": x, "gap_m": x + 1} for x in [1., 4., 4., 4., 4.]], "deep": True}
    with patch.object(ev.STORE_EVIDENCE, "live", {"audit": {"listings": [], "photos": [], "parcels": [pc]}}), \
         patch.object(ev.STORE_EVIDENCE, "by_way", {}):
        ev.STORE_EVIDENCE._load_live()
        b = ev.STORE_EVIDENCE.by_way[20][0]
    record("width-bottleneck", pc, {"range": [b.lo, b.hi], "vios_fit": engine.fit_class(wr(b.lo, b.hi), vehicles.get_profile(IDS[1]))},
           "Retain a valid 1 m bottleneck or mark unresolved; do not certify the entire way as fitting")
    bounds = [ev.Bound(.9, 1.1, "Measured", "tape narrow", "", "2026-10-17"),
              ev.Bound(4., 4.2, "Measured", "tape wide", "", "2026-09-01"),
              ev.Bound(4., 4.1, "Declared", "listing", "", "2026-01-01")]
    combined = ev._combine(bounds)
    record("tier-review", [b.to_json() for b in bounds], {"combined": combined[:4],
           "vios_fit": engine.fit_class(ev.WidthRange(*combined[:3], review=combined[3]), vehicles.get_profile(IDS[1]))},
           "A lower-tier listing must not resolve conflicting measurements into a confident fit")
    old, new = {"way_id": 20, "samples": [7.], "cuts": [], "deep": True, "queried_at": "2026-01-01"}, \
               {"samples": [2.], "cuts": [], "queried_at": "2026-10-17"}
    gg = graph({1:(0,0), 2:(100,0)}, [(20,[1,2],{})])
    with patch.object(live, "city_parcels", return_value={"20":new}):
        got = live._merge_city(gg, [old])[0]
    record("stale-deep", {"old":old,"fresh":new}, got, "Fresh contradictory cuts require reconciliation; deep is coverage, not recency")
    store = object.__new__(ev.EvidenceStore)
    store.by_way, store.by_name = {}, {}
    store._load_csv(ev.PARCEL_FILE, "Official", "audit CSV", None)
    record("legacy-margin", str(ev.PARCEL_FILE.relative_to(ROOT)), {k:[b.to_json() for b in v] for k,v in store.by_name.items()},
           "Raw CSV parcel gaps must use the same versioned 1 m conversion as live cuts")
    from shapely.geometry import box, Point
    road = box(-50,-2,22,2).union(box(18,-2,22,50))
    parts = list(box(-50,-50,50,50).difference(road).geoms)

    def lookup(la, lo):
        x,y = parcels._local(lo,la,*xy(0,0))
        for i,p in enumerate(parts):
            if p.covers(Point(x,y)):
                # Polygon API wants lon/lat.
                from shapely.ops import transform
                return {"id":i,"poly":transform(lambda xx,yy,z=None: (106.71+xx/parcels.KX,10.8+yy/parcels.KY),p)}
        return None

    cut = parcels.measure([xy(0,0),xy(20,0),xy(20,20)], fractions=[.5], parcel_lookup=lookup)
    record("corner-cut", "4 m L corridor, cut at its 90-degree vertex", cut,
           "The 4 m raw corridor should not become a 5.66 m raw gap at its bend")
    calls = []

    def partial(coords, step=None, max_cuts=2, **kw):
        calls.append(max_cuts)
        return {"samples":[3.],"cuts":[{"width_m":3.,"gap_m":4.}]}

    gg = graph({1:(0,0),2:(0,400),3:(0,800)}, [(20,[1,2],{}),(21,[2,3],{})])
    with patch.object(parcels,"path_into",return_value=[(20,[xy(0,0),xy(0,400)]),(21,[xy(0,400),xy(0,800)])]), \
         patch.object(parcels,"measure",side_effect=partial):
        parcels.measure_area(gg,*xy(0,800),{},osm.haversine)
    record("deep-budget", "Two 400 m ways, one successful cut on each", {"requested_cuts":calls,"total":sum(calls)},
           "60 attempted cuts total, independent of successful yield")

    p = vehicles.get_profile("toyota-vios")
    record("vehicle-door", "Toyota Vios width derivation", {"body":p.body_width,"mirror":p.mirror_width,
           "fits":p.fits_min,"tight":p.tight_min,"door":p.door_min,"D15_door":p.mirror_width+.9},
           "D15 specifies W including mirrors for door_min; implementation uses body width")
    confirm=OUT/"audit-confirmations.jsonl"
    confirm.write_text(json.dumps({"body_width":1.73,"mirror_width":1.98,"result":"in","vehicle_label":"Vios",
                                   "way_ids":[20],"date":"2026-10-17"})+"\n")
    store=object.__new__(ev.EvidenceStore);store.by_way={};store.by_name={}
    with patch.object(ev,"CONFIRM_FILE",confirm):store._load_confirmations()
    record("confirmation-mirror", "Vios got in: body 1.73 m, mirrors 1.98 m",store.by_way[20][0].to_json(),
           "Q10 specifies mirror-width lower bound (or capture a folded-mirror context), not body+.20")
    record("vehicle-water-units", {"wading_depth_mm":"0.2","powertrain":"ICE","gc_m":.15},
           vehicles._safe_water({"wading_depth_mm":"0.2","powertrain":"ICE"},.15),
           "Compare metres with metres; an invalid/sub-clearance 0.2 mm value must not enable the wading rule")
    v8 = vehicles.get_profile("vinfast-vf-8-the-all-new-2026")
    record("vehicle-provenance", "CSV marks VF 8 turning radius DERIVED; metadata", v8.to_json(),
           "Derived turning radius should be labelled estimated; class metadata must preserve uncertainty")
    record("turn-cache-version", "Length changes from 5.998 m to 12 m for the same Ford Transit profile id",
           {"cached_width":vehicles.three_point_width("ford-transit"),"new_body_diagonal_lower_bound":math.hypot(12.,2.068)+.6},
           "A spec change must invalidate id-only three_point.json; 9.09 m cannot turn a 12 m long rectangle")
    record("double-encroachment", "4.0 m parcel gap; 1.0 m usable deduction already includes parked motorbikes",
           {"usable":3.,"fortuner_fit":engine.fit_class(wr(3.,3.3),vehicles.get_profile("toyota-fortuner")),
            "fortuner_fits_threshold":vehicles.get_profile("toyota-fortuner").fits_min,
            "mirror_plus_side_clearance":vehicles.get_profile("toyota-fortuner").mirror_width+.6},
           "Document whether the same motorbike row is being deducted twice; calibrate one obstacle budget")

    points = {1:(-100,0),2:(0,0),3:(100,0),4:(0,100),5:(0,200),6:(100,100)}
    main=(10,[1,2,3],{"highway":"tertiary"})
    ways=[main,(20,[2,4,5],{}),(30,[4,6],{})]
    a = graph(points,ways)
    b = graph(points,[main,(20,[2,4],{}),(21,[4,5],{}),(30,[4,6],{})])
    outputs=[]
    for g in [a,b]:
        c=candidate(g,30,20)
        outputs.append(engine._way_out(c,g,{wid:wr(4) for wid in g.ways},{wid:"fits" for wid in g.ways},p,
                                      exit_search(g),{"side":"u"}))
    record("way-split", ways, outputs, "Identical physical T junction must have the same exit under an OSM way split")
    # A real forward loop exists, but the narrow car's shortest exit tree points
    # back over the arrival edge. The wide car penalizes that same edge as tight,
    # selecting the loop instead. Feasibility must not depend on that tree tie.
    g=graph({1:(-50,0),2:(0,0),3:(50,0),4:(0,200),5:(20,200),6:(20,0)},
            [(10,[1,2,3],{"highway":"tertiary"}),(20,[2,4],{}),(30,[4,5,6,2],{})])
    exits=[]
    for vid in ["vinfast-vf-3","kia-carnival"]:
        pp=vehicles.get_profile(vid); widths={10:wr(8),20:wr(3.4),30:wr(4.)}
        fits={wid:engine.fit_class(widths[wid],pp) for wid in g.ways}
        rev=defaultdict(list)
        for nn,es in g.drive_adj.items():
            for ei,mm in es:rev[mm].append((ei,nn))
        ex=engine.dijkstra(rev,{n:0 for n in [1,2,3]},lambda ei:True,
                           lambda ei:engine._cost(g.edges[ei].length,fits[g.edges[ei].way_id]))
        exits.append({"vehicle":vid,"fit":fits,"way_out":engine._way_out(candidate(g,20,100),g,widths,fits,pp,
                                                                 {True:ex,False:ex},{"side":"u"})})
    record("shortest-tree-exit", "200 m alley plus a 240 m fitting forward loop; stop halfway", exits,
           "Both cars have the same topological forward exit; search for an alternative instead of inspecting one predecessor")
    g=graph({1:(-100,0),2:(0,0),3:(100,0),4:(0,100)},[main,(20,[2,4],{"oneway":"yes"})])
    outputs=[]
    for width in [4.,9.]:
        c=candidate(g,20,20)
        outputs.append(engine._way_out(c,g,{10:wr(9),20:wr(width)},{10:"fits",20:"fits"},p,
                                      exit_search(g),{"side":"u"}))
    record("oneway-exit", "One-way u→v dead end, stop 20 m from u", outputs,
           "Neither reversing nor turning around may exit against the one-way direction")
    g=graph({1:(0,0),2:(0,200),3:(200,200)},[(10,[1,2],{}),(20,[2,3],{})])
    ff,_=engine.compute_fit(g,{10:wr(4.),20:wr(4.)},vehicles.get_profile("kia-carnival"))
    record("junction-turn", "Two 4 m alleys meeting at 90 degrees", {"fit":ff,"carnival_one_arc_need":vehicles.turn_in_width("kia-carnival",4.)},
           "Route transitions need vehicle swept-path feasibility; equal-width alleys currently skip the turn check")

    tagcases=[{"access":"private"},{"access":"private","motorcar":"destination"},
              {"motorcar":"no"},{"motor_vehicle":"no","motorcar":"yes"},
              {"vehicle":"no"},{"junction":"roundabout"},{"bridge":"yes","maxweight":"1"}]
    record("access-tags", tagcases, [{**t,"drivable":osm.Way(1,{"highway":"service",**t},[1,2]).drivable,
                                      "oneway_parsed":osm.Way(1,{"highway":"service",**t},[1,2]).oneway} for t in tagcases],
           "Honor tag specificity, vehicle=no, implicit roundabout direction, and per-vehicle bridge constraints")
    g=graph({1:(0,0),2:(0,50)},[(10,[1,2],{})],{2:{"barrier":"gate","access":"private"}})
    record("gate", "Untagged residential way through a private gate node", g.drive_adj,
           "Block the private gate node unless explicit access exists")
    record("private-walk", {"highway":"service","access":"private"},
           osm.Way(1,{"highway":"service","access":"private"},[1,2]).walkable,
           "Access restrictions must also apply to foot routing")
    # Endpoint-only snap invents a road across an arbitrary obstacle to a lot.
    g=graph({1:(0,0),2:(100,0)},[(10,[1,2],{"highway":"tertiary"})])
    c=engine.Candidate("lot",*xy(0,70),"lot across canal",None,entrance=1,data={"entrance_d":70})
    route=engine._route_in(c,g,{True:({1:0},{}),False:({1:0},{})})
    record("lot-connector", "Lot 70 m off a main-road node; no connecting way", route,
           "A public, fitting mapped entrance path is needed before certifying a lot connection")
    c=candidate(g,10,20)
    record("partial-route", "Final way excluded by search; source endpoint still in dist", engine._route_in(c,g,{True:({1:0},{}),False:({1:0},{})}),
           "Route in should recheck final partial edge; _evaluate rejects unfit street stops separately")
    g=graph({1:(0,0),2:(100,0),3:(200,0)},[(10,[1,2],{}),(20,[2,3],{})])
    dd,pr=engine.dijkstra(g.drive_adj,{1:0},lambda ei:True,
                          lambda ei:engine._cost(g.edges[ei].length,"tight" if g.edges[ei].way_id==10 else "fits"))
    got=engine._route_in(candidate(g,20,10),g,{True:(dd,pr),False:(dd,pr)})
    record("weighted-meters", "100 m tight approach plus 10 m of final edge",got,
           "Report about 110 physical metres, not about 140 penalty-weighted metres")

    g=graph({1:(0,0),2:(100,0)},[(10,[1,2],{})])
    c=candidate(g,10,80,"street")
    dest=xy(90,0)
    shape=engine._walk_geometry(g,c,{},*dest)
    drawn=sum(osm.haversine(a[1],a[0],b[1],b[0]) for a,b in zip(shape,shape[1:]))
    endpoint_distance=min(90+80,10+20)
    record("walk-edge", {"edge_m":100,"destination_offset":90,"stop_offset":80},
           {"reported_by_endpoint_rule_m":endpoint_distance,"drawn_m":drawn,"geometry":shape},
           "Distance and geometry must both follow the same 10 m sub-edge path")
    g=graph({1:(0,0),2:(50,0)},[(10,[1,2],{"highway":"motorway"})])
    try:
        fixture_plan(g,xy(10,0))
        error=None
    except Exception as ex:
        error=f"{type(ex).__name__}: {ex}"
    record("no-walk-crash", "Cached graph containing only a motorway", error,
           "Return insufficient walk coverage, not an AttributeError",error is not None)
    # Cache invalidation must include the graph revision, not just its source string.
    a=graph({1:(0,0),2:(100,0)},[(10,[1,2],{})],source="audit-cache-refresh")
    b=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})],source="audit-cache-refresh")
    with patch.object(engine,"build_graph",side_effect=[a,b]):
        _,wa,_=engine.area(*xy(0,0))
        _,wb,_=engine.area(*xy(0,0))
    record("graph-revision-cache", "Disk OSM refresh replaces way 10 with 20 under the same source", list(wb),
           "Width cache must contain new way 20",20 not in wb)

    record("moving-water", {"range":[.1,.3],"rain_driven":True,"safe_water_depth":.4},
           flood.flood_status(flood.DepthRange(.1,.3,["rain"],True,False),.4),
           "D14 says rain flood reaching 0.30 m is blocked for every vehicle")
    missing=ARRIVE.replace(year=2027)
    prof=flood.FloodProfile([flood.FloodRecord(10.8,106.71,"Audit",2020,"","tide",60,"high","")])
    record("missing-tide", missing.isoformat(), {"tide":flood.tide_level(missing),"depth":flood.depth_at(prof,missing,[]),
           "status":flood.worst_over(prof,[missing],[],.133)[0]}, "Missing forecast must be Unverified, not passable")
    rec=flood.FloodProfile([flood.FloodRecord(10.8,106.71,"Audit",2020,"","rain",60,"high","")])
    pulse=[{"start":(ARRIVE+timedelta(minutes=1)).isoformat(),"end":(ARRIVE+timedelta(minutes=14)).isoformat(),"mm_per_h":60}]
    record("rain-pulse", pulse, {"sampled":flood.worst_over(rec,[ARRIVE,ARRIVE+timedelta(minutes=15)],pulse,.133)[0],
           "inside":flood.worst_over(rec,[ARRIVE+timedelta(minutes=7)],pulse,.133)[0],
           "one_minute_after":flood.worst_over(rec,[ARRIVE+timedelta(minutes=15)],pulse,.133)[0]},
           "Dwell evaluation must include event boundaries and account for retained water")
    with patch.object(flood,"_extremes",return_value=[(ARRIVE,1.39),(ARRIVE+timedelta(minutes=7),1.65),(ARRIVE+timedelta(minutes=15),1.39)]):
        sampled=flood.worst_over(prof,[ARRIVE,ARRIVE+timedelta(minutes=15)],[],.133)[0]
        peak=flood.worst_over(prof,[ARRIVE+timedelta(minutes=7)],[],.133)[0]
    record("dwell-extrema", "Synthetic tide extremum at arrival+7 minutes between two sampled endpoints", {"sampled":sampled,"peak":peak},
           "Include published extrema inside the stay, not just an arrival-anchored 15-minute grid")
    overlap=[{"start":ARRIVE.isoformat(),"end":(ARRIVE+timedelta(hours=1)).isoformat(),"mm_per_h":10},
             {"start":ARRIVE.isoformat(),"end":(ARRIVE+timedelta(hours=1)).isoformat(),"mm_per_h":60}]
    record("rain-order", overlap, [flood.rain_rate(ARRIVE,overlap),flood.rain_rate(ARRIVE,overlap[::-1])],
           "Overlapping scenarios need a documented order-independent combination or validation")
    with patch.object(flood,"depth_at",side_effect=[flood.DepthRange(.01,.02,[],False,False),flood.DepthRange(.10,.12,[],False,False)]):
        ss,depth,tt=flood.worst_over(None,[ARRIVE,ARRIVE+timedelta(minutes=15)],[],.175)
    record("worst-depth", "Two passable depths: 1–2 cm then 10–12 cm",{"status":ss,"depth":depth.to_json(),"time":tt.isoformat()},
           "Worst depth/time should show the later 10–12 cm interval even when status ties")
    unknown=flood.depth_at(None,ARRIVE,[{**overlap[0],"mm_per_h":100}])
    record("rain-no-history", "100 mm/h on a street with no flood history", {"range":unknown.to_json(),"VF3_status":flood.flood_status(unknown,.175)},
           "No historical record cannot establish a universal safe upper bound of 10 cm")

    g=graph({1:(0,0),2:(100,0),3:(50,60)},[(10,[1,2],{"highway":"tertiary"})],{3:{"traffic_sign":"VN:P.130"}})
    stat,rules=legality.legality_on_street(g,g.ways[10],wr(8),*xy(50,0),math.inf,"park",ARRIVE)
    record("no-rule-permitted", "8 m tertiary street, no applicable sign/ordinance", {"status":stat,"rules":[r.to_json() for r in rules]},
           "No known prohibition with incomplete sign/curb coverage means Unverified, not an affirmative permission")
    # Sign 60 m down same way: no-stopping jurisdiction is not a 40 m circle.
    g=graph({1:(0,0),2:(200,0)},[(10,[1,2],{})],{1:{"traffic_sign":"VN:P.130"}})
    record("sign-extent", "P.130 at x=0; stop at x=60 on same uninterrupted way", [r.to_json() for r in legality._sign_rules(g,g.ways[10],*xy(60,0),"park",ARRIVE)],
           "Apply sign direction/side/extent until its terminating condition")
    g_off=graph({1:(0,0),2:(100,0),3:(50,20)},[(10,[1,2],{})],{3:{"traffic_sign":"VN:P.130"}})
    record("sign-unrelated", "P.130 20 m away, not on the candidate's way", [r.to_json() for r in legality._sign_rules(g_off,g_off.ways[10],*xy(50,0),"park",ARRIVE)],
           "Do not attach an unassociated sign to every nearby street")
    record("parking-tag-fee", {"parking:both:fee":"no"},
           [r.to_json() for r in legality._osm_parking_tags(osm.Way(1,{"highway":"residential","parking:both:fee":"no"},[1,2]),"park")],
           "Free parking is not prohibited parking; parse semantic restriction keys only")
    r1=legality._sign_rules(g,g.ways[10],*xy(20,0),"park",ARRIVE)
    g.node_tags[1]={"traffic_sign":"VN:P.131c"}
    r2=legality._sign_rules(g,g.ways[10],*xy(20,0),"park",ARRIVE.replace(hour=23))
    r3=legality._sign_rules(g,g.ways[10],*xy(20,0),"park",ARRIVE.replace(day=18,hour=1))
    record("legality-window", "Park 17 Oct 23:00–18 Oct 01:00 next to P.131c", {"at_arrival":[r.to_json() for r in r2],"at_departure":[r.to_json() for r in r3]},
           "Check legal validity across entire parked interval, not only arrival")
    record("junction-degree", "Physical T junction: parent way [1,2,3], branch [2,4]", 
           graph({1:(-50,0),2:(0,0),3:(50,0),4:(0,50)},[(10,[1,2,3],{}),(20,[2,4],{})]).drive_degree(2),
           "Physical branch degree is 3; distinct way count 2 misses the 5 m exclusion")
    g=graph({0:(-20,0),1:(0,0),2:(3,0),3:(20,0),4:(0,20)},
            [(10,[0,1],{"highway":"tertiary"}),(20,[1,2,3],{}),(30,[1,4],{})])
    rr=fixture_plan(g,xy(4,0))
    record("junction-shape-node", "Stop 4 m from a detected degree-three junction, behind a shape node at 3 m",
           rr["door"]["legality"],"A shape node must not hide the nearby 5 m junction exclusion")
    legalproxies=[]
    for tags in [{"covered":"yes"},{"highway":"trunk"}]:
        w=osm.Way(99,{"highway":"residential",**tags},[1,3])
        status,rules=legality.legality_on_street(g,w,wr(8),*xy(10,0),math.inf,"park",ARRIVE)
        legalproxies.append({"tags":tags,"status":status,"rules":[r.to_json() for r in rules]})
    record("legal-road-proxies", "covered=yes is not necessarily a tunnel; OSM trunk is not necessarily a statutory expressway",
           legalproxies,"Do not present road-class/covered proxies as established statutory prohibitions")
    save("audit-probes.json",{"source_sha256":hashes(),"cases":rows})
    print(f"PROBES: {len(rows)} observations saved to docs/eval/audit-probes.json",flush=True)
    return rows


def quantiles(values):
    if not values:
        return {}
    v=sorted(values)
    return {"n":len(v),"min":v[0],"median":statistics.median(v),"p95":v[min(len(v)-1,int(.95*len(v)))],"max":v[-1]}


def cached_cells(seed):
    rng=random.Random(seed)
    paths={p.stem.removeprefix("area_"):p for p in (ROOT/"backend/cache/osm").glob("area_*.json")}
    selected=["demo"]
    for p in sorted((ROOT/"backend/cache/live/areas").glob("*.json")):
        if p.stem in paths and p.stem not in selected:
            selected.append(p.stem)
    city=json.loads(live.CITY_PARCELS.read_text())
    pcs=sorted({osm.area_key(c["lat"],c["lon"]) for pc in city.values() if pc for c in pc.get("cuts",[])})
    for key in rng.sample(pcs,len(pcs)):
        if key in paths and key not in selected:
            selected.append(key)
        if len(selected)>=15:
            break
    keys=[k for k in sorted(paths) if k not in selected and 10.68<=float(k.split("_")[0])<=10.90
          and 106.55<=float(k.split("_")[1])<=106.88 and osm.area_key(*map(float,k.split("_")))==k]
    selected+=rng.sample(keys,min(30-len(selected),len(keys)))
    return selected


def pick_destinations(n,seed):
    rng=random.Random(seed)
    cells=cached_cells(seed)
    points=[]
    for i in range(n):
        key=cells[i%len(cells)]
        if key=="demo":
            # Still a reproducible random sample within the actual demo routing cell.
            la,lo=rng.uniform(10.792,10.810),rng.uniform(106.696,106.722)
        else:
            la0,lo0=map(float,key.split("_"))
            for _ in range(100):
                la,lo=la0+rng.uniform(-.00199,.00199),lo0+rng.uniform(-.00199,.00199)
                if osm.area_key(la,lo)==key: break
        assert osm.area_key(la,lo)==key,(key,la,lo,osm.area_key(la,lo))
        points.append({"i":i,"key":key,"lat":la,"lon":lo,"intent":"park" if i%2==0 else "pickup"})
    return points


def brief(r):
    return {"verdict":r["verdict"],"counts":r["counts"],
            "door":{k:r["door"].get(k) for k in ["ok","fit","way_out","fail_reasons","verified"]} if r["door"] else None,
            "stops":[{k:s[k] for k in ["kind","way_id","name","lat","lon","tier","verified","walk","fit","way_out","legality"]} for s in r["stop_points"]]}


def sweep(n,seed):
    points=pick_destinations(n,seed)
    results=[]
    failures=defaultdict(list)
    counts=Counter()
    timing=defaultdict(list)
    start_hash=hashes()
    t0=time.perf_counter()
    for c in points:
        t=time.perf_counter()
        live.area_status(c["lat"],c["lon"])  # cached_area + cached city cuts only; never live.build
        timing["cached_apply_s"].append(time.perf_counter()-t)
        g,wrs,fps=engine.area(c["lat"],c["lon"])
        sample={**c,"graph_ways":len(g.ways),"graph_edges":len(g.edges),"profiles":{}}
        fitmaps={}
        for vid in IDS:
            t=time.perf_counter()
            try:
                r=engine.plan(c["lat"],c["lon"],vid,c["intent"],ARRIVE,120 if c["intent"]=="park" else 15)
                elapsed=time.perf_counter()-t
                timing[vid].append(elapsed)
                sample["profiles"][vid]={"seconds":elapsed,**brief(r)}
                counts["plans_completed"]+=1
                fitmaps[vid]=engine.compute_fit(g,wrs,vehicles.get_profile(vid))[0]
                cap=engine.WALK_CAP_M[c["intent"]]
                sp=r["stop_points"]
                for s in sp:
                    for label,bad in [("stop_not_ok",not s["ok"]),("stop_fit_no",s["fit"]["class"] in ("no","blocked")),
                                      ("reported_walk_over_cap",s["walk"]["meters"]>cap),
                                      ("stop_exit_none",s["way_out"]["mode"]=="none"),
                                      ("stop_reverse_over_60",s["way_out"].get("reverse_m",0)>60)]:
                        if bad:
                            counts[label]+=1
                            if len(failures[label])<12: failures[label].append({**c,"vehicle":vid,"stop":brief(r)["stops"][s["rank"]-1]})
                    coords=s["walk"].get("geometry",[])
                    length=sum(osm.haversine(a[1],a[0],b[1],b[0]) for a,b in zip(coords,coords[1:]))
                    # The product deliberately draws only mapped walk edges. Estimated
                    # endpoint connectors are counted in metres but remain absent from the map.
                    connection = s["walk"].get("connection", {})
                    undrawn = sum(connection.get(k, 0) for k in ("stop_to_walk_m", "destination_to_walk_m")
                                  if connection.get(k, 0) > engine.WALK_SNAP_M)
                    if abs(length + undrawn - s["walk"]["meters"])>5:
                        counts["walk_geometry_mismatch"]+=1
                        if len(failures["walk_geometry_mismatch"])<12: failures["walk_geometry_mismatch"].append({**c,"vehicle":vid,"stop":s["name"],"reported_m":s["walk"]["meters"],"drawn_m":length,"undrawn_connector_m":undrawn})
                    if length>cap+1:
                        counts["walk_geometry_over_cap"]+=1
                    counts["stops_offered"]+=1
                code=r["verdict"]["code"]
                bad=(code=="none")!= (not sp)
                bad|=code=="door" and not(sp and sp[0]["kind"]=="door" and sp[0]["verified"])
                bad|=bool(sp) and code=="unverified" and sp[0]["verified"]
                if bad:
                    counts["verdict_inconsistent"]+=1
                    failures["verdict_inconsistent"].append({**c,"vehicle":vid,"result":brief(r)})
            except Exception as ex:
                counts["crashes"]+=1
                sample["profiles"][vid]={"error":f"{type(ex).__name__}: {ex}"}
                failures["crashes"].append({**c,"vehicle":vid,"trace":traceback.format_exc()})
        order={"no":0,"blocked":0,"unknown":1,"tight":2,"fits":3}
        for smaller,wider in combinations(IDS,2):
            aa,bb=sample["profiles"][smaller],sample["profiles"][wider]
            if "error" in aa or "error" in bb: continue
            counts["monotonic_plan_pairs"]+=1
            # A smaller car must retain every known-fitting way of the bigger car.
            for wid in fitmaps[smaller]:
                counts["monotonic_fit_pairs"]+=1
                if order[fitmaps[smaller][wid]]<order[fitmaps[wider][wid]]:
                    counts["fit_monotonicity"]+=1
                    if len(failures["fit_monotonicity"])<12: failures["fit_monotonicity"].append({**c,"smaller":smaller,"wider":wider,"way":wid})
            def quality(x):
                return (x["stops"][0]["tier"],x["stops"][0]["walk"]["meters"]) if x["stops"] else (3,math.inf)
            if quality(aa)>quality(bb):
                counts["plan_monotonicity"]+=1
                if len(failures["plan_monotonicity"])<20: failures["plan_monotonicity"].append({**c,"smaller":smaller,"wider":wider,"small_quality":quality(aa),"wide_quality":quality(bb),"small":aa,"wide":bb})
            if aa["door"] and bb["door"] and bb["door"]["ok"] and not aa["door"]["ok"]:
                counts["door_monotonicity"]+=1
                if len(failures["door_monotonicity"])<12: failures["door_monotonicity"].append({**c,"smaller":smaller,"wider":wider,"small":aa["door"],"wide":bb["door"]})
        results.append(sample)
        if (c["i"]+1)%10==0:
            print(f"SWEEP {c['i']+1}/{n}: {time.perf_counter()-t0:.1f}s; counts {dict(counts)}",flush=True)
            save("audit-sweep.json",{"n":n,"completed_destinations":len(results),"seed":seed,"arrive":ARRIVE.isoformat(),"vehicles":IDS,
                 "counts":dict(counts),"examples":dict(failures),"timing":{k:quantiles(v) for k,v in timing.items()},"results":results,
                 "source_sha256_start":start_hash,"source_sha256_end":hashes()})
    return results


def profile():
    cells=[("demo",10.79924,106.71239),("campus",10.840,106.808),("city",10.744,106.760)]
    out={}
    for name,la,lo in cells:
        t=time.perf_counter();live.area_status(la,lo);apply_s=time.perf_counter()-t
        times=[]
        for _ in range(5):
            t=time.perf_counter();r=engine.plan(la,lo,"toyota-vios","park",ARRIVE,120);times.append(time.perf_counter()-t)
        pr=cProfile.Profile();pr.enable();engine.plan(la,lo,"toyota-vios","park",ARRIVE,120);pr.disable()
        stream=io.StringIO();pstats.Stats(pr,stream=stream).strip_dirs().sort_stats("cumulative").print_stats(45)
        (OUT/f"audit-profile-{name}.txt").write_text(stream.getvalue())
        g,_,_=engine.area(la,lo)
        out[name]={"lat":la,"lon":lo,"cached_apply_s":apply_s,"plan_s":quantiles(times),"candidates":r["counts"],"ways":len(g.ways),"edges":len(g.edges)}
    save("audit-performance.json",out)
    print("PROFILE saved",flush=True)


def diagnose():
    live.area_status(10.79924,106.71239)
    g,wrs,fps=engine.area(10.79924,106.71239)
    out=[]
    for vid in [IDS[0],IDS[2]]:
        p=vehicles.get_profile(vid);fit,_=engine.compute_fit(g,wrs,p)
        e,off,_=engine._project(g,10.79924,106.71239,lambda w:w.drivable)
        arrsrc={n:0 for w in g.ways.values() if w.kind=="main" and w.drivable for n in w.nodes}
        dist,pred=engine.dijkstra(g.drive_adj,arrsrc,lambda ei:fit[g.edges[ei].way_id] in ("fits","tight"),lambda ei:engine._cost(g.edges[ei].length,fit[g.edges[ei].way_id]))
        ext=exit_search(g,fit,weighted=True)
        c=candidate(g,e.way_id,off)
        # candidate() selects the first edge; rebuild with the actual projected edge.
        c=engine.Candidate("door",*engine._interp(g,e.u,e.v,off,e.length),"220/9",e.way_id,e.idx,off,walk_m=0)
        route=engine._route_in(c,g,{True:(dist,pred),False:(dist,pred)})
        wo=engine._way_out(c,g,wrs,fit,p,ext,route)
        a=e.u if route and route["side"]=="u" else e.v
        path=engine._path_nodes(ext[True][1],a)
        nodes=[]
        reverse_m=off if route and route["side"]=="u" else e.length-off
        first_physical=None
        first_way_count=None
        for i,n in enumerate(path):
            incident=g.node_ways.get(n,set())
            usable_neighbors={m for ei,m in g.walk_adj.get(n,[]) if fit.get(g.edges[ei].way_id) in ("fits","tight")}
            usable_ways={wid for wid in incident if fit.get(wid) in ("fits","tight")}
            if first_physical is None and len(usable_neighbors)>=3:
                first_physical={"node":n,"reverse_m":reverse_m}
            if first_way_count is None and (len(usable_ways)>=3 or (any(g.ways[wid].kind=="main" for wid in usable_ways) and i>0)):
                first_way_count={"node":n,"reverse_m":reverse_m}
            nodes.append({"node":n,"latlon":g.nodes[n],"distinct_ways":len(incident),"reverse_so_far_m":reverse_m,
                          "physical_neighbors":len({m for _,m in g.walk_adj.get(n,[])}),
                          "ways":[{"id":wid,"name":g.ways[wid].name,"kind":g.ways[wid].kind,"fit":fit[wid],"width":[wrs[wid].lo,wrs[wid].hi]} for wid in sorted(incident)]})
            if i+1<len(path):reverse_m+=g.edges[ext[True][1][n][0]].length
        forward=e.v if route and route["side"]=="u" else e.u
        forward_dist,_=engine.dijkstra(g.drive_adj,{forward:0},lambda ei:ei!=e.idx and fit[g.edges[ei].way_id] in ("fits","tight"),lambda ei:g.edges[ei].length)
        main={n for w in g.ways.values() if w.kind=="main" for n in w.nodes}
        alt=min((forward_dist[n] for n in main if n in forward_dist),default=None)
        out.append({"vehicle":vid,"three_point":vehicles.three_point_width(vid),"door_width":wrs[e.way_id].to_json(),"route":route,"exit":wo,
                    "first_physical_junction":first_physical,"first_engine_turn_node":first_way_count,
                    "forward_path_without_candidate_edge_m":alt,"backtrack_nodes":nodes})
    save("audit-220-diagnosis.json",out)
    print("DIAGNOSIS saved",flush=True)


def explain():
    sweep=json.loads((OUT/"audit-sweep.json").read_text())
    examples=sweep["examples"].get("plan_monotonicity",[])
    done=set();out=[]
    for c in examples:
        key=(c["i"],c["smaller"],c["wider"])
        if key in done:continue
        done.add(key)
        live.area_status(c["lat"],c["lon"])
        captured={}
        original=engine._evaluate
        for vid in [c["smaller"],c["wider"]]:
            rows=[]
            def evaluate(*args,**kwargs):
                r=original(*args,**kwargs)
                rows.append({k:v for k,v in r.items() if k!="_c"})
                return r
            with patch.object(engine,"_evaluate",side_effect=evaluate):
                r=engine.plan(c["lat"],c["lon"],vid,c["intent"],ARRIVE,120 if c["intent"]=="park" else 15)
            captured[vid]={"result":brief(r),"candidates":rows}
        target=captured[c["wider"]]["result"]["stops"][0]
        nearest={}
        for vid,x in captured.items():
            best=min(x["candidates"],key=lambda s:osm.haversine(target["lat"],target["lon"],s["lat"],s["lon"]))
            nearest[vid]=best
        out.append({k:c[k] for k in ["i","lat","lon","intent","smaller","wider"]}|{"same_stop_comparison":nearest})
    save("audit-monotonic-explanations.json",out)
    print("MONOTONIC EXPLANATIONS saved",flush=True)


def seams():
    rng=random.Random(3317)
    paths={p.stem.removeprefix("area_"):p for p in (ROOT/"backend/cache/osm").glob("area_*.json")}
    pairs=[]
    keys=list(paths);rng.shuffle(keys)
    for key in keys:
        la,lo=map(float,key.split("_"));east=f"{la:.3f}_{lo+.004:.3f}"
        if east not in paths or osm.area_key(la,lo)!=key or osm.area_key(la,lo+.004)!=east:continue
        if not (10.70<la<10.88 and 106.58<lo<106.80):continue
        pair=[]
        for lon in [lo+.002-.00001,lo+.002+.00001]:
            live.area_status(la,lon)
            g,wrs,_=engine.area(la,lon)
            r=engine.plan(la,lon,"toyota-vios","pickup",ARRIVE,15)
            e,off,d=engine._project(g,la,lon,lambda w:w.drivable)
            pair.append({"key":osm.area_key(la,lon),"lat":la,"lon":lon,"door_way":e.way_id if e else None,
                         "ways":len(g.ways),"edges":len(g.edges),"result":brief(r)})
        pairs.append(pair)
        if len(pairs)>=12:break
    save("audit-seams.json",{"pairs":pairs,"note":"2.18 m east/west perturbation across a 0.004 degree cell boundary; differences are diagnostic, not ground truth."})
    print("SEAMS saved",flush=True)


def route_checks():
    data=json.loads((OUT/"audit-sweep.json").read_text())
    selected={}
    for c in data["results"]:selected.setdefault(c["key"],c)
    counts=Counter();examples=[]
    for c in selected.values():
        live.area_status(c["lat"],c["lon"])
        g,wrs,_=engine.area(c["lat"],c["lon"])
        coord_nodes={(lo,la):n for n,(la,lo) in g.nodes.items()}
        by_pair=defaultdict(list)
        for e in g.edges:
            by_pair[(e.u,e.v)].append(e);by_pair[(e.v,e.u)].append(e)
        for vid in IDS:
            r=engine.plan(c["lat"],c["lon"],vid,c["intent"],ARRIVE,120 if c["intent"]=="park" else 15)
            fit,_=engine.compute_fit(g,wrs,vehicles.get_profile(vid));counts["plans"]+=1
            for s in r["stop_points"]:
                counts["routes"]+=1
                coords=(s["route_in"] or {}).get("geometry",[])
                for aa,bb in zip(coords,coords[1:]):
                    a,b=coord_nodes.get(tuple(aa)),coord_nodes.get(tuple(bb))
                    if a is not None and b is not None and (a,b) in by_pair:
                        es=by_pair[(a,b)];counts["full_steps"]+=1
                        if not any(fit[e.way_id] not in ("no","blocked") for e in es):
                            counts["unfit_steps"]+=1;examples.append({"i":c["i"],"vehicle":vid,"step":[a,b]})
                        if not any((e.idx,b) in g.drive_adj.get(a,[]) for e in es):counts["oneway_violations"]+=1
                    elif s["kind"]=="lot":counts["unmapped_lot_links"]+=1
                    else:
                        counts["partial_steps"]+=1
                        if fit[s["way_id"]] in ("no","blocked"):counts["unfit_partial_steps"]+=1
    save("audit-route-checks.json",{"counts":dict(counts),"examples":examples,"note":"30 destinations × 5 vehicles; returned entry paths, not exit paths or an external origin approach."})
    print("ROUTE CHECKS saved",flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--probes",action="store_true");ap.add_argument("--sweep",action="store_true")
    ap.add_argument("--profile",action="store_true");ap.add_argument("--diagnose",action="store_true")
    ap.add_argument("--explain",action="store_true");ap.add_argument("--seams",action="store_true")
    ap.add_argument("--case",help="Run probes and print this observation id")
    ap.add_argument("--routes",action="store_true")
    ap.add_argument("--n",type=int,default=300);ap.add_argument("--seed",type=int,default=3317)
    a=ap.parse_args();OUT.mkdir(exist_ok=True)
    if not any([a.probes,a.sweep,a.profile,a.diagnose,a.explain,a.seams,a.routes]):a.probes=True
    if a.probes or a.case:
        observations=probes()
        if a.case:
            matches=[r for r in observations if r["id"]==a.case]
            if not matches:raise SystemExit("Unknown case id: "+a.case)
            print(json.dumps(matches[0],ensure_ascii=False,indent=2,default=str))
    if a.diagnose:diagnose()
    if a.profile:profile()
    if a.sweep:sweep(a.n,a.seed)
    if a.explain:explain()
    if a.seams:seams()
    if a.routes:route_checks()


if __name__=="__main__":main()
