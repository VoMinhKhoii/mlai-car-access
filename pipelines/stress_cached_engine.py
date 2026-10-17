#!/usr/bin/env python3
"""Seeded, network-denied stress test. Freeze first, then compare identical inputs.

python3 pipelines/stress_cached_engine.py freeze --n 600 --seed 171026
python3 pipelines/stress_cached_engine.py run --phase before --workers 6
python3 pipelines/stress_cached_engine.py run --phase after --workers 6
python3 pipelines/stress_cached_engine.py report
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
from itertools import combinations
import json
import math
import multiprocessing
from pathlib import Path
import random
import shutil
import socket
import statistics
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/eval'
FROZEN = ROOT / 'tmp/stress-frozen'
sys.path.insert(0, str(ROOT / 'backend'))
IDS = ['vinfast-vf-3', 'toyota-vios', 'class-m', 'toyota-fortuner', 'kia-carnival', 'ford-transit']
ARRIVE = datetime.fromisoformat('2026-10-17T09:31:00+07:00')


def denied(*args, **kwargs):
    raise RuntimeError('Stress test forbids ALL network access')


socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
from app import evidence as ev, live, osm, parcels, plan, vehicles, declared_index  # noqa: E402

plan.GOONG_API_KEY = ''
osm._fetch_overpass = parcels._parcel = live.build = denied


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'backend/app').glob('*.py'))}


def district_lookup():
    from shapely.geometry import shape, Point
    from shapely.prepared import prep
    shapes = [(f['properties']['name'], prep(shape(f['geometry']))) for f in json.loads(
        (ROOT/'data/official/hcmc_urban_districts_2021.geojson').read_text())['features']]
    centers = json.loads((ROOT/'backend/cache/live/chotot_hcmc_districts_v2.json').read_text())
    def lookup(la, lo):
        p = Point(lo, la)
        for name, poly in shapes:
            if poly.covers(p):
                return name, '2021 district polygon'
        c = min(centers, key=lambda c: osm.haversine(la,lo,c['lat'],c['lon']))
        return c['name'].upper(), 'nearest district centroid (outside polygon coverage)'
    return lookup


def freeze(n, seed):
    rng = random.Random(seed)
    lookup = district_lookup()
    cells = defaultdict(list)
    paths = sorted((ROOT/'backend/cache/osm').glob('area_*.json'))
    for path in paths:
        la,lo = map(float,path.stem.removeprefix('area_').split('_'))
        if osm.area_key(la,lo) != path.stem.removeprefix('area_'):
            continue  # these coordinates resolve to the larger demo cache
        cells[lookup(la,lo)[0]].append(path)
    cells[lookup(10.8,106.71)[0]].append(ROOT/'backend/cache/osm/demo_binhthanh.json')
    FROZEN.mkdir(parents=True,exist_ok=True)
    for name in ['city_parcels.json','declared_index.json']:
        shutil.copy2(ROOT/'backend/cache/live'/name,FROZEN/name)
    areas = {p.stem:json.loads(p.read_text()) for p in sorted((ROOT/'backend/cache/live/areas').glob('*.json'))}
    write(FROZEN/'areas.json',areas)
    for values in cells.values():
        rng.shuffle(values)
    districts = sorted(cells)
    points=[]
    kinds=['alley']*60+['street']*25+['block']*15
    # Shuffle independently per 100; district and sampling kind cannot alias.
    categories=(kinds*(math.ceil(n/100)))[:n];rng.shuffle(categories)
    used=Counter()
    def copy_cell(path):
        target=FROZEN/path.name
        if not target.exists():shutil.copy2(path,target)
        return json.loads(target.read_text())['elements']
    def cell_key(path):
        return 'demo' if path.name.startswith('demo') else path.stem.removeprefix('area_')
    for i,kind in enumerate(categories):
        requested_kind=kind
        district=districts[i%len(districts)]
        for attempt in range(len(cells[district])*2):
            if attempt>=len(cells[district]):kind='block'
            path=cells[district][used[district]%len(cells[district])];used[district]+=1
            key=cell_key(path)
            elements=copy_cell(path)
            nodes={e['id']:(e['lat'],e['lon']) for e in elements if e['type']=='node'}
            ways=[osm.Way(e['id'],e.get('tags',{}),[k for k in e.get('nodes',[]) if k in nodes])
                  for e in elements if e['type']=='way']
            eligible=[]
            for w in ways:
                if not plan._car_way_allowed(w):continue
                if kind=='alley' and not (w.is_alley or w.highway=='service'):continue
                if kind=='street' and (w.is_alley or w.highway not in ('residential','tertiary')):continue
                ns=[k for k in w.nodes if osm.area_key(*nodes[k])==key]
                if ns:eligible.append((w,ns))
            if kind=='block':
                if key=='demo':la,lo=rng.uniform(10.789,10.819),rng.uniform(106.686,106.731)
                else:
                    la0,lo0=map(float,key.split('_'));la,lo=la0+rng.uniform(-.00198,.00198),lo0+rng.uniform(-.00198,.00198)
                if osm.area_key(la,lo)!=key:continue
                # Random off-road interior point, not a claimed building entrance.
                if any(osm.haversine(la,lo,*p)<8 for p in nodes.values()):continue
                wid=None
            elif eligible:
                w,ns=rng.choice(eligible);la,lo=nodes[rng.choice(ns)];wid=w.id
            else:continue
            if lookup(la,lo)[0]!=district:continue
            points.append({'i':i,'key':key,'lat':la,'lon':lo,'district':district,
                'district_method':lookup(la,lo)[1],'sampling':kind,'requested_sampling':requested_kind,'sampled_way_id':wid,'cohort':'random'})
            break
        else:raise RuntimeError(f'No {kind} candidate in {district}')
        if i%100==0:print('FREEZE',i,flush=True)
    # Additional targeted probes are explicitly separate from random prevalence.
    supplemental=[(10.7889312,106.697545,'Ministop Trần Doãn Khanh')]
    records=[{'way_id':int(wid),**pc} for wid,pc in json.loads((FROZEN/'city_parcels.json').read_text()).items() if pc]
    records += [p for a in areas.values() for p in a.get('parcels',[])]
    records.sort(key=lambda p:min(p.get('samples') or [40]))
    seen=set()
    for pc in records:
        cuts=[c for c in pc.get('cuts',[]) if c.get('lat') and c.get('width_m') is not None]
        if not cuts:continue
        c=min(cuts,key=lambda c:c['width_m']);key=osm.area_key(c['lat'],c['lon'])
        identity=(pc.get('way_id'),key)
        if identity in seen:continue
        seen.add(identity)
        supplemental.append((c['lat'],c['lon'],f"Official narrow-cut probe {pc.get('way_id')}"))
        if len(supplemental)>=31:break
    for la,lo,label in supplemental:
        key=osm.area_key(la,lo);path=ROOT/'backend/cache/osm'/('demo_binhthanh.json' if key=='demo' else f'area_{key}.json')
        if not path.exists():continue
        copy_cell(path)
        points.append({'i':len(points),'key':key,'lat':la,'lon':lo,'district':lookup(la,lo)[0],
            'district_method':lookup(la,lo)[1],'sampling':'targeted','sampled_way_id':None,'cohort':'targeted','label':label})
    manifest={'seed':seed,'random_destinations':n,'all_cached_cells_in_pool':sum(map(len,cells.values())),
        'district_cell_pool':{d:len(v) for d,v in cells.items()},'points':points,
        'frozen_files_sha256':{p.name:sha(p) for p in sorted(FROZEN.glob('*.json'))},
        'sources_before':sources(),'district_note':'17 urban district polygons; outside coverage explicitly uses nearest-centroid strata.'}
    write(OUT/'stress-inputs.json',manifest)
    print('FROZEN',len(points),'destinations',Counter(p['district'] for p in points),flush=True)


def configure():
    city=json.loads((FROZEN/'city_parcels.json').read_text())
    areas=json.loads((FROZEN/'areas.json').read_text())
    live.city_parcels=lambda:city
    live.cached_area=lambda key,*args:areas.get(key)
    declared_index.PATH=FROZEN/'declared_index.json'
    def path_for(key):return FROZEN/('demo_binhthanh.json' if key=='demo' else f'area_{key}.json')
    osm._load_elements=lambda la,lo,key,*args,**kw:(json.loads(path_for(key).read_text())['elements'],f'cache:{key}')
    osm._graph_stamp=lambda key:(path_for(key).stat().st_mtime_ns,path_for(key).stat().st_size)
    vehicles._TP_CACHE=FROZEN/'unused-three-point.json'
    return areas


def cut_features(g,w,records):
    from shapely.geometry import LineString, Point
    coords=[g.nodes[n] for n in w.nodes]
    length=sum(osm.haversine(*a,*b) for a,b in zip(coords,coords[1:]))
    cuts=[c for pc in records for c in pc.get('cuts',[]) if c.get('width_m') is not None and c.get('valid',True)]
    c=min(cuts,key=lambda c:c['width_m']) if cuts else {}
    la,lo=c.get('lat'),c.get('lon')
    junctions=[n for n in w.nodes if len({z for _,z in g.walk_adj.get(n,[]) if plan._car_way_allowed(g.ways[g.edges[_].way_id])})>=3]
    distance=min((osm.haversine(la,lo,*g.nodes[n]) for n in junctions),default=None) if la is not None else None
    crossing=None;off_way=None
    if la is not None:
        ky,kx=110540,111320*math.cos(math.radians(la))
        line=LineString([((b-lo)*kx,(a-la)*ky) for a,b in coords]);off_way=line.distance(Point(0,0))
        if c.get('heading_deg') is not None and c.get('gap_m'):
            heading=math.radians(c['heading_deg']);half=c['gap_m']/2
            ray=LineString([(-math.sin(heading)*half, math.cos(heading)*half),(math.sin(heading)*half,-math.cos(heading)*half)])
            crossing=False
            for other in g.ways.values():
                if other.id==w.id or not plan._car_way_allowed(other):continue
                otherline=LineString([((g.nodes[n][1]-lo)*kx,(g.nodes[n][0]-la)*ky) for n in other.nodes])
                if ray.intersects(otherline):crossing=True;break
    return {'nearest_junction_m':round(distance,2) if distance is not None else None,
        'cut_length_m':c.get('gap_m'),'way_length_m':round(length,2),
        'cut_length_vs_way_length':round(c['gap_m']/length,4) if c.get('gap_m') and length else None,
        'number_of_cuts':len(cuts),'narrowest_cut_m':c.get('width_m'),'cut':c or None,
        'cut_crosses_another_way':crossing,'cut_off_centerline_m':round(off_way,2) if off_way is not None else None,
        'way_crosses_cell_boundary':len({osm.area_key(*p) for p in coords})>1,
        'survey_coverage': [pc.get('coverage',{}) for pc in records]}


def cluster(row):
    f=set(row['flags']);lim=row.get('limiting') or {}
    if 'crash' in f:return 'exception'
    if f & {'walk_over_cap','walk_geometry_mismatch','door_stop_inconsistent'}:return 'walk_or_contract'
    if 'vehicle_monotonicity' in f:return 'vehicle_monotonicity'
    if 'official_basis_without_sample' in f:return 'failed_survey_midpoint'
    if lim.get('nearest_junction_m') is not None and lim['nearest_junction_m']<5 and lim.get('narrowest_cut_m',40)<1:
        return 'junction_cut'
    if lim.get('cut_off_centerline_m',0) and lim['cut_off_centerline_m']>1.5:return 'misaligned_cut'
    if 'single_cut_confidence' in f:return 'single_cut_confidence'
    if row.get('legal_status') in ('Prohibited','Restricted'):return 'cited_stop_prohibition'
    if 'basis_not_sample' in f:return 'clamped_basis_provenance'
    if 'destination_sample_contradiction' in f:return 'different_route_bottleneck'
    if 'official_submetre' in f:return 'narrow_cut_requires_field_check'
    if 'street_sedan_no' in f:return 'street_prior_or_other_checks'
    return 'other'


def run_point(point):
    t0=time.perf_counter();la,lo=point['lat'],point['lon']
    # Isolated cold request per destination: no history-dependent accumulation of area evidence.
    ev.STORE_EVIDENCE.live={};live.apply(None,la,lo)
    g,wrs,_=plan.area(la,lo)
    pcs=live._merge_city(g,(live.cached_area(point['key']) or {}).get('parcels',[]))
    by_way=defaultdict(list)
    for pc in pcs:by_way[pc['way_id']].append(pc)
    trace={};geom_cache={};original=plan._estimate
    def capture(c,gg,ww,p,checks,failures):
        result=original(c,gg,ww,p,checks,failures)
        segments={}
        for ei,l in (checks['route_in'] or {}).get('_segments',[])+checks['way_out'].get('_segments',[]):
            segments[ei]=max(segments.get(ei,0),l)
        if c.edge_idx is not None:segments.setdefault(c.edge_idx,.01)
        vals=[(plan._width_estimate(ww[gg.edges[ei].way_id]),gg.edges[ei].way_id) for ei in segments]
        finite=[x for x in vals if x[0] is not None]
        value,wid=min(finite,key=lambda x:x[0]) if finite else (None,c.way_id)
        trace[(c.kind,c.edge_idx,c.offset)]={'limiting_way_id':wid,'basis_value_m':value,
            'route_way_ids':list(dict.fromkeys(gg.edges[ei].way_id for ei in segments)),
            'route_strict':(checks['route_in'] or {}).get('strict'), 'exit_strict':checks['way_out'].get('strict')}
        trace[(c.kind,round(c.lat,9),round(c.lon,9))]=trace[(c.kind,c.edge_idx,c.offset)]
        return result
    plan._estimate=capture
    rows=[];flags=[]
    for intent in ('park','pickup'):
        group=[]
        for vid in IDS:
            t=time.perf_counter();p=vehicles.get_profile(vid);trace.clear()
            row={**point,'id':f"{point['i']}:{intent}:{vid}",'vehicle_id':vid,'vehicle_size_class':p.size_class,
                'mirror_width_m':p.mirror_width,'tight_min_m':p.tight_min,'door_min_m':p.door_min,'intent':intent}
            try:
                result=plan.plan(la,lo,vid,intent,ARRIVE,120 if intent=='park' else 15)
                row.update(seconds=time.perf_counter()-t,verdict=result['verdict'],counts=result['counts'])
                def brief(stop):
                    if not stop:return None
                    trace_row=trace.get((stop['kind'],round(stop['lat'],9),round(stop['lon'],9)),{})
                    return {k:stop.get(k) for k in ['kind','way_id','name','lat','lon','ok','verified','tier','walk','estimate','fail_reasons','legality','way_out']}|{'fit_class':stop['fit']['class'],'trace':trace_row}
                row['door']=brief(result['door']);row['stops']=[brief(s) for s in result['stop_points']]
                checks=[]
                if row['door']:checks.append(('door',row['door']))
                if row['stops'] and (not row['door'] or row['stops'][0]['kind']!='door'):checks.append(('stop',row['stops'][0]))
                for scope,stop in checks:
                    fs=[];tr=stop['trace'];wid=tr.get('limiting_way_id') or stop['way_id'];w=g.ways.get(wid)
                    dw=g.ways.get(stop['way_id']);wr=wrs.get(wid);value=tr.get('basis_value_m')
                    est=stop['estimate'];negative=est['answer']=='no'
                    lanes=ev._num(dw.tags.get('lanes')) if dw else None
                    if dw and negative and p.mirror_width<=vehicles.get_profile('toyota-vios').mirror_width and (dw.highway in ('residential','tertiary','secondary','primary') or (lanes or 0)>=2):fs.append('street_sedan_no')
                    official=[b for b in (wr.evidence if wr else []) if b.tier in ('Measured','Official') and b not in wr.overruled]
                    samples=[b.estimate_m for b in official if b.estimate_m is not None]
                    if wr and wr.top_tier in ('Measured','Official') and value is not None:
                        if not samples and any(b.measurement_schema=='parcel-survey-unresolved-v2' for b in official) and 'địa chính / chính thức' in est['basis']:fs.append('official_basis_without_sample')
                        if samples and not any(abs(value-s)<.011 for s in samples) and not any(b.lo<=value<=b.hi and not b.estimate_m for b in official):fs.append('basis_not_sample')
                        if samples and min(samples)<1:fs.append('official_submetre')
                    own=[b.estimate_m for b in wrs[dw.id].evidence if b.tier in ('Measured','Official') and b.estimate_m is not None] if dw else []
                    if negative and own and min(own)>=max(p.tight_min,p.door_min):fs.append('destination_sample_contradiction')
                    if w and wid not in geom_cache:geom_cache[wid]=cut_features(g,w,by_way[wid])
                    geom=geom_cache.get(wid,{})
                    if negative and est['confidence'] in ('medium','high') and geom.get('number_of_cuts')==1 and samples and min(samples)<max(p.tight_min,p.door_min):fs.append('single_cut_confidence')
                    if fs:
                        item={**row,'scope':scope,'flags':fs,'answer':est['answer'],'confidence':est['confidence'],'basis':est['basis'],
                            'coverage_fraction':est.get('coverage',{}).get('sample_supported_fraction'),
                            'legal_status':stop['legality']['status'],'fail_reasons':stop['fail_reasons'],
                            'limiting':{'way_id':wid,'name':w.name if w else None,'highway':w.highway if w else None,
                                'tags':w.tags if w else {},'evidence_tiers':sorted({b.tier for b in wr.evidence}) if wr else [],
                                'basis_data_source':([est['limiting_width']['source']] if est.get('limiting_width') else
                                    [b.source for b in official] if official else [b.source for b in (wr.evidence if wr else [])]),
                                'basis_value_m':value,**geom}}
                        item.pop('stops',None);item.pop('door',None);item['cluster']=cluster(item);flags.append(item)
                invariant=[];cap=plan.WALK_CAP_M[intent]
                for stop in row['stops']:
                    coords=stop['walk'].get('geometry',[]);length=sum(osm.haversine(a[1],a[0],b[1],b[0]) for a,b in zip(coords,coords[1:]))
                    if length>cap+1e-5 or stop['walk']['meters']>cap:invariant.append('walk_over_cap')
                    if abs(length-stop['walk']['meters'])>1:invariant.append('walk_geometry_mismatch')
                    if not stop['ok'] or stop['fit_class'] in ('no','blocked') or stop['way_out']['mode']=='none' or stop['way_out'].get('reverse_m',0)>60:invariant.append('unsafe_offered_stop')
                if (result['verdict']['code']=='none') != (not row['stops']) and result['verdict']['estimate']['answer']!='unknown':invariant.append('door_stop_inconsistent')
                if row['stops'] and result['verdict']['estimate']!=row['stops'][0]['estimate']:invariant.append('door_stop_inconsistent')
                row['invariants']=list(set(invariant));group.append(row)
                if invariant:flags.append({**point,'id':row['id'],'vehicle_id':vid,'intent':intent,'flags':row['invariants'],'cluster':'walk_or_contract'})
            except Exception:
                row.update(seconds=time.perf_counter()-t,error=traceback.format_exc());flags.append({**row,'flags':['crash'],'cluster':'exception'})
            rows.append(row)
        for small,wide in combinations(group,2):
            # Catalogue order is monotone in the full geometry, with class-m
            # excluded when dimensions/radius cross an exact model profile.
            sp,wp=vehicles.get_profile(small['vehicle_id']),vehicles.get_profile(wide['vehicle_id'])
            if not (sp.mirror_width<=wp.mirror_width and sp.length<=wp.length and sp.turning_radius<=wp.turning_radius):continue
            quality=lambda row:(row['stops'][0]['tier'],row['stops'][0]['walk']['meters']) if row['stops'] else (3,math.inf)
            bad=quality(small)>quality(wide) or (small['door'] and wide['door'] and wide['door']['ok'] and not small['door']['ok'])
            if bad:flags.append({**point,'id':small['id'],'vehicle_id':small['vehicle_id'],'wider_vehicle':wide['vehicle_id'],'intent':intent,'flags':['vehicle_monotonicity'],'cluster':'vehicle_monotonicity','small_quality':quality(small),'wide_quality':quality(wide)})
    plan._estimate=original
    return {'point':point,'rows':rows,'flags':flags,'total_s':time.perf_counter()-t0}


def run(phase,workers):
    manifest=json.loads((OUT/'stress-inputs.json').read_text())
    configure()
    # Build the expensive manoeuvre envelopes once, then fork read-only copies.
    for vid in IDS:vehicles.three_point_width(vid)
    start=sources();t=time.perf_counter();completed=[]
    output=OUT/f'stress-{phase}.jsonl'
    with output.open('w') as fp,ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('fork')) as pool:
        fs={pool.submit(run_point,p):p for p in manifest['points']}
        for f in as_completed(fs):
            result=f.result();completed.append(result);fp.write(json.dumps(result,ensure_ascii=False,default=str)+'\n');fp.flush()
            if len(completed)%10==0:print(phase,len(completed),'/',len(fs),'elapsed',round(time.perf_counter()-t),'flags',sum(len(x['flags']) for x in completed),flush=True)
    rows=[r for result in completed for r in result['rows']];flags=[r for result in completed for r in result['flags']]
    summary={'phase':phase,'destinations':len(completed),'plans':len(rows),'workers':workers,'elapsed_s':time.perf_counter()-t,
        'flags':dict(Counter(k for r in flags for k in r['flags'])),'clusters':dict(Counter(r['cluster'] for r in flags)),
        'flagged_plan_count':len({r['id'] for r in flags}),'flagged_evaluations':len(flags),
        'verdict_answers':dict(Counter(r.get('verdict',{}).get('estimate',{}).get('answer','exception') for r in rows)),
        'source_sha256_start':start,'source_sha256_end':sources(),
        'latency_s':quantiles([r['seconds'] for r in rows])}
    write(OUT/f'stress-{phase}-summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)


def quantiles(xs):
    xs=sorted(xs)
    return {'p50':statistics.median(xs),'p95':xs[min(len(xs)-1,math.ceil(.95*len(xs))-1)],'max':max(xs)}


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['freeze','run','report'])
    parser.add_argument('--n',type=int,default=600);parser.add_argument('--seed',type=int,default=171026)
    parser.add_argument('--phase',choices=['before','after'],default='before');parser.add_argument('--workers',type=int,default=6)
    args=parser.parse_args()
    if args.action=='freeze':freeze(args.n,args.seed)
    elif args.action=='run':run(args.phase,args.workers)
    else:raise SystemExit('Use pipelines/stress_cached_report.py after both phases.')


if __name__=='__main__':main()
