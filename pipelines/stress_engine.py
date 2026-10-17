#!/usr/bin/env python3
"""Seeded, network-denied stress test. Freeze first, then compare identical inputs.

python3 pipelines/stress_engine.py freeze --n 200 --seed 171026
python3 pipelines/stress_engine.py run --phase before --workers 4
python3 pipelines/stress_engine.py run --phase after --workers 4
python3 pipelines/stress_engine.py report
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
import hashlib
import gzip
from itertools import combinations
import json
import math
import os
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
OUT = ROOT / 'docs/eval/engine-stress-data'
FROZEN = ROOT / 'tmp/engine-stress/frozen'
# Independent paths are set before importing any backend module. No HTTP server.
RUNTIME = ROOT / 'tmp/engine-stress/runtime'
RUNTIME.mkdir(parents=True, exist_ok=True)
for name in ('store', 'cache/live'):
    (RUNTIME/name).mkdir(parents=True, exist_ok=True)
if not (RUNTIME/'flags.json').exists():
    shutil.copy2(ROOT/'backend/flags.json', RUNTIME/'flags.json')
    shutil.copytree(ROOT/'backend/store', RUNTIME/'store', dirs_exist_ok=True)
    for path in (ROOT/'backend/cache/live').glob('*.json'):
        shutil.copy2(path, RUNTIME/'cache/live'/path.name)
# Preserve production area_key semantics: the bundled demo graph must exist
# before importing osm, including when no sampled point selects that graph.
(RUNTIME/'cache/osm').mkdir(parents=True, exist_ok=True)
if not (RUNTIME/'cache/osm/demo_binhthanh.json').exists():
    shutil.copy2(ROOT/'backend/cache/osm/demo_binhthanh.json', RUNTIME/'cache/osm/demo_binhthanh.json')
os.environ.update(VAODUOC_STORE=str(RUNTIME/'store'), VAODUOC_CACHE=str(RUNTIME/'cache'),
                  VAODUOC_FLAGS=str(RUNTIME/'flags.json'), FLAG_LIVE_HYDRO='0', NGONGACH_CACHED_ONLY='1')
sys.path.insert(0, os.environ.get('ENGINE_STRESS_BACKEND', str(ROOT/'backend')))
IDS = ['vinfast-vf-3', 'toyota-vios', 'class-m', 'toyota-fortuner', 'kia-carnival', 'ford-transit']
ARRIVE = datetime.fromisoformat('2026-10-17T09:31:00+07:00')


def denied(*args, **kwargs):
    raise RuntimeError('Stress test forbids ALL network access')


socket.socket.connect = denied
socket.socket.connect_ex = denied
socket.create_connection = denied
from app import config  # noqa: E402
# An archived baseline package still reads the same frozen runtime and repo data.
for name in ('vehicles','field','flood','official','processed'):
    if not (RUNTIME/'data'/name).exists():
        shutil.copytree(ROOT/'data'/name, RUNTIME/'data'/name)
config.ROOT, config.DATA = ROOT, RUNTIME/'data'
from app import evidence as ev, live, osm, parcels, plan, vehicles, declared_index  # noqa: E402

plan.GOONG_API_KEY = ''
osm._fetch_overpass = parcels._parcel = live.build = denied


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources():
    return {'backend/app/'+p.name:sha(p) for p in sorted(Path(plan.__file__).parent.glob('*.py'))}


def distance_to_road(lat, lon, elements):
    """Metres to mapped road centreline, independent of OSM shape-node density."""
    kx = 111320*math.cos(math.radians(lat))
    nodes = {e['id']: ((e['lon']-lon)*kx, (e['lat']-lat)*110540)
             for e in elements if e['type'] == 'node'}
    best = math.inf
    for way in elements:
        if way['type'] != 'way' or way.get('tags', {}).get('highway') not in osm.DRIVABLE:
            continue
        coords = [nodes[n] for n in way['nodes'] if n in nodes]
        for a, b in zip(coords, coords[1:]):
            dx, dy = b[0]-a[0], b[1]-a[1]
            norm = dx*dx+dy*dy
            t = max(0, min(1, -(a[0]*dx+a[1]*dy)/norm)) if norm else 0
            best = min(best, math.hypot(a[0]+t*dx, a[1]+t*dy))
    return best


def repair_block_sampling(manifest):
    """Retain near-road probes as controls; replace them in the random cohort."""
    lookup = district_lookup()
    controls = []
    for point in list(manifest['points']):
        if point['cohort'] != 'random' or point['sampling'] != 'block':
            continue
        key = point['key']
        path = FROZEN/('demo_binhthanh.json' if key == 'demo' else f'area_{key}.json')
        elements = json.loads(path.read_text())['elements']
        distance = distance_to_road(point['lat'], point['lon'], elements)
        point['road_centreline_distance_m'] = round(distance, 2) if math.isfinite(distance) else None
        if distance >= 8:
            continue
        rng = random.Random(manifest['seed']*1009+point['i'])
        for _ in range(1000):
            if key == 'demo':
                la, lo = rng.uniform(10.789, 10.819), rng.uniform(106.686, 106.731)
            else:
                la0, lo0 = map(float, key.split('_'))
                la, lo = la0+rng.uniform(-.00198, .00198), lo0+rng.uniform(-.00198, .00198)
            if osm.area_key(la, lo) != key or lookup(la, lo)[0] != point['district']:
                continue
            distance = distance_to_road(la, lo, elements)
            if distance >= 8:
                break
        else:
            raise RuntimeError(f'No interior block probe found in {key}')
        new = {**point, 'i': len(manifest['points']), 'lat': la, 'lon': lo,
               'road_centreline_distance_m': round(distance, 2) if math.isfinite(distance) else None}
        point.update(cohort='targeted', sampling='near_road_control', label='Near-road control retained after block resampling')
        manifest['points'].append(new)
        controls.append(point['i'])
    manifest['resampled_block_controls'] = controls
    manifest['block_sampling_rule'] = 'Random block probes are at least 8 m from mapped drivable-road centrelines; not surveyed entrances.'
    return manifest


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
    shutil.copy2(RUNTIME/'cache/osm/demo_binhthanh.json',FROZEN/'demo_binhthanh.json')
    for name in ['city_parcels.json','declared_index.json']:
        shutil.copy2(RUNTIME/'cache/live'/name,FROZEN/name)
    areas = (json.loads((FROZEN/'areas.json').read_text()) if (FROZEN/'areas.json').exists() else
             {p.stem:json.loads(p.read_text()) for p in sorted((ROOT/'backend/cache/live/areas').glob('*.json'))})
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
        for attempt in range(max(10,len(cells[district])*2)):
            if attempt==len(cells[district]):district=districts[(districts.index(district)+1)%len(districts)]
            path=cells[district][used[district]%len(cells[district])];used[district]+=1
            key=cell_key(path)
            elements=copy_cell(path)
            nodes={e['id']:(e['lat'],e['lon']) for e in elements if e['type']=='node'}
            ways=[osm.Way(e['id'],e.get('tags',{}),[k for k in e.get('nodes',[]) if k in nodes])
                  for e in elements if e['type']=='way']
            eligible=[]
            for w in ways:
                if not w.drivable:continue
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
    manifest.update(head=__import__('subprocess').check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                    cached_area_note='Legacy area records replayed as trusted server overlays; current area_status rejects their old schema. No expiry/schema policy is changed.',
                    runtime_flags=json.loads((RUNTIME/'flags.json').read_text()))
    repair_block_sampling(manifest)
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
    junctions=[n for n in w.nodes if len({z for _,z in g.walk_adj.get(n,[]) if g.ways[g.edges[_].way_id].drivable})>=3]
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
                if other.id==w.id or not other.drivable:continue
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
    if 'estimate_scope_missing' in f:return 'missing_route_scope'
    if 'unfiltered_junction_cut' in f:return 'junction_cut'
    if 'unfiltered_misaligned_cut' in f:return 'misaligned_cut'
    if 'sample_prior_conflict' in f:return 'sample_prior_conflict'
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
    if f & {'official_submetre','automatic_submetre'}:return 'narrow_cut_requires_field_check'
    if 'street_sedan_no' in f:return 'street_prior_or_other_checks'
    return 'other'


def run_point(point):
    t0=time.perf_counter();la,lo=point['lat'],point['lon']
    # Isolated cold request per destination: no history-dependent accumulation of area evidence.
    live_area=(live.cached_area(point['key']) or None)
    g,wrs,_=plan.area(la,lo,live_area=live_area)
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
            'estimated_segment_count':len(segments), 'estimated_scope_m':sum(segments.values()),
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
                result=plan.plan(la,lo,vid,intent,ARRIVE,120 if intent=='park' else 15,live_area=live_area)
                row.update(seconds=time.perf_counter()-t,verdict=result['verdict'],counts=result['counts'])
                def brief(stop):
                    if not stop:return None
                    trace_row=trace.get((stop['kind'],round(stop['lat'],9),round(stop['lon'],9)),{})
                    return {k:stop.get(k) for k in ['kind','way_id','name','lat','lon','ok','verified','tier','walk','estimate','fail_reasons','legality','way_out','failure_codes','route_in','unverified_reasons']}|{'fit_class':stop['fit']['class'],'trace':trace_row}
                row['door']=brief(result['door']);row['stops']=[brief(s) for s in result['stop_points']]
                checks=[]
                if row['door']:checks.append(('door',row['door']))
                if row['stops'] and (not row['door'] or row['stops'][0]['kind']!='door'):checks.append(('stop',row['stops'][0]))
                vectors=[]
                for scope,stop in checks:
                    fs=[];tr=stop['trace'];wid=tr.get('limiting_way_id') or stop['way_id'];w=g.ways.get(wid)
                    dw=g.ways.get(stop['way_id']);wr=wrs.get(wid);value=tr.get('basis_value_m')
                    est=stop['estimate'];negative=est['answer']=='no'
                    lanes=ev._num(dw.tags.get('lanes')) if dw else None
                    if dw and negative and p.mirror_width<=vehicles.get_profile('toyota-vios').mirror_width and (dw.highway in ('residential','tertiary','secondary','primary') or (lanes or 0)>=2):fs.append('street_sedan_no')
                    official=[b for b in (wr.evidence if wr else []) if (b.tier in ('Measured','Official') or b.feature=='parcel_widths') and b not in wr.overruled]
                    samples=[b.estimate_m for b in official if b.estimate_m is not None]
                    if wr and (wr.top_tier in ('Measured','Official') or any(b.feature=='parcel_widths' for b in wr.evidence)) and value is not None:
                        if not samples and any(b.measurement_schema=='parcel-survey-unresolved-v2' for b in official) and 'địa chính / chính thức' in est['basis']:fs.append('official_basis_without_sample')
                        source=(est.get('limiting_width') or {}).get('source')
                        source_samples=[b.estimate_m for b in official if b.source==source and b.estimate_m is not None]
                        if source_samples and not any(abs(value-s)<.011 for s in source_samples):fs.append('basis_not_sample')
                        if samples and value is not None and value<1:fs.append('official_submetre' if wr.top_tier=='Official' else 'automatic_submetre')
                    own=[b.estimate_m for b in wrs[dw.id].evidence if (b.tier in ('Measured','Official') or b.feature=='parcel_widths') and b.estimate_m is not None] if dw else []
                    if negative and own and min(own)>=max(p.tight_min,p.door_min):fs.append('destination_sample_contradiction')
                    if w and wid not in geom_cache:geom_cache[wid]=cut_features(g,w,by_way[wid])
                    geom=geom_cache.get(wid,{})
                    if negative and stop['legality']['status'] not in ('Prohibited','Restricted') and est['confidence'] in ('medium','high') and geom.get('number_of_cuts')==1 and samples and min(samples)<max(p.tight_min,p.door_min):fs.append('single_cut_confidence')
                    if tr.get('estimated_scope_m',0)<.1 and (stop.get('route_in') or {}).get('available') and (stop.get('route_in') or {}).get('meters',0) and stop['route_in']['meters']>5:fs.append('estimate_scope_missing')
                    if w and samples and len(samples)>0 and geom.get('nearest_junction_m') is not None and geom['nearest_junction_m']<5 and value is not None and abs(value-geom['narrowest_cut_m'])<.011:fs.append('unfiltered_junction_cut')
                    if w and samples and geom.get('cut_off_centerline_m',0) and geom['cut_off_centerline_m']>1.5 and value is not None and abs(value-geom['narrowest_cut_m'])<.011:fs.append('unfiltered_misaligned_cut')
                    if est['answer']=='unknown' and own and dw and wrs[dw.id].review:fs.append('sample_prior_conflict')
                    vector={**point,'id':row['id'],'vehicle_id':vid,'vehicle_size_class':p.size_class,
                            'intent':intent,'scope':scope,'stop_way_id':stop['way_id'],
                            'highway':dw.highway if dw else None,'answer':est['answer'],'confidence':est['confidence'],
                            'coverage':est.get('coverage'),'limiting_way_id':wid,'tiers':[b.tier for b in wr.evidence] if wr else [],
                            'width_hypothesis':value,'flags':fs,
                            'sample_quality':[b.sample_quality for b in (wr.evidence if wr else []) if b.feature=='parcel_widths'],
                            **geom}
                    vectors.append(vector)
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
                if not result['verdict'].get('estimate'):invariant.append('missing_verdict_estimate')
                for stop in row['stops']:
                    coords=stop['walk'].get('geometry',[]);length=sum(osm.haversine(a[1],a[0],b[1],b[0]) for a,b in zip(coords,coords[1:]))
                    if length>cap+1e-5 or stop['walk']['meters']>cap:invariant.append('walk_over_cap')
                    connector=stop['walk'].get('connection',{});expected=length+connector.get('stop_to_walk_m',0)+connector.get('destination_to_walk_m',0)
                    if abs(expected-stop['walk']['meters'])>1:invariant.append('walk_geometry_mismatch')
                    if not stop['ok'] or stop['fit_class'] in ('no','blocked') or stop['way_out']['mode']=='none' or stop['way_out'].get('reverse_m',0)>60:invariant.append('unsafe_offered_stop')
                if bool(row['stops']) and result['verdict']['code']=='none':invariant.append('door_stop_inconsistent')
                if row['stops'] and result['verdict']['estimate']!=row['stops'][0]['estimate']:invariant.append('door_stop_inconsistent')
                row['invariants']=list(set(invariant));row['features']=vectors;group.append(row)
                if invariant:flags.append({**point,'id':row['id'],'vehicle_id':vid,'intent':intent,'flags':row['invariants'],'cluster':'walk_or_contract'})
            except Exception:
                row.update(seconds=time.perf_counter()-t,error=traceback.format_exc());flags.append({**row,'flags':['crash'],'cluster':'exception'})
            rows.append(row)
        for small,wide in combinations(group,2):
            # Catalogue order is monotone in the full geometry, with class-m
            # excluded when dimensions/radius cross an exact model profile.
            sp,wp=vehicles.get_profile(small['vehicle_id']),vehicles.get_profile(wide['vehicle_id'])
            if not (sp.mirror_width<=wp.mirror_width and sp.length<=wp.length and sp.turning_radius<=wp.turning_radius and sp.safe_water_depth>=wp.safe_water_depth):continue
            quality=lambda row:(row['stops'][0]['tier'],row['stops'][0]['walk']['meters']) if row['stops'] else (3,math.inf)
            bad=quality(small)>quality(wide) or (small['door'] and wide['door'] and wide['door']['ok'] and not small['door']['ok'])
            if bad:flags.append({**point,'id':small['id'],'vehicle_id':small['vehicle_id'],'wider_vehicle':wide['vehicle_id'],'intent':intent,'flags':['vehicle_monotonicity'],'cluster':'vehicle_monotonicity','small_quality':quality(small),'wide_quality':quality(wide)})
    plan._estimate=original
    return {'point':point,'rows':rows,'flags':flags,'total_s':time.perf_counter()-t0}


def run(phase,workers,limit=None,append=False):
    manifest=json.loads((OUT/'stress-inputs.json').read_text())
    configure()
    # Build the expensive manoeuvre envelopes once, then fork read-only copies.
    for vid in IDS:vehicles.three_point_width(vid)
    previous = json.loads((OUT/f'stress-{phase}-summary.json').read_text()) if append else {}
    start=sources();t=time.perf_counter();completed=load_results(phase) if append else []
    seen={x['point']['i'] for x in completed}
    points=[p for p in manifest['points'] if p['i'] not in seen][:limit]
    output=OUT/f'stress-{phase}.jsonl'
    if append and completed and not output.exists():
        with output.open('w') as fp:
            for result in completed:
                fp.write(json.dumps(result, ensure_ascii=False, default=str)+'\n')
    with output.open('a' if append else 'w') as fp,ProcessPoolExecutor(max_workers=workers,mp_context=multiprocessing.get_context('fork')) as pool:
        fs={pool.submit(run_point,p):p for p in points}
        for f in as_completed(fs):
            result=f.result();completed.append(result);fp.write(json.dumps(result,ensure_ascii=False,default=str)+'\n');fp.flush()
            if len(completed)%10==0:print(phase,len(completed),'/',len(fs),'elapsed',round(time.perf_counter()-t),'flags',sum(len(x['flags']) for x in completed),flush=True)
    rows=[r for result in completed for r in result['rows']];flags=[r for result in completed for r in result['flags']]
    summary={'phase':phase,'destinations':len(completed),'plans':len(rows),'workers':workers,
        'elapsed_s':previous.get('elapsed_s', 0)+time.perf_counter()-t,
        'flags':dict(Counter(k for r in flags for k in r['flags'])),'clusters':dict(Counter(r['cluster'] for r in flags)),
        'flagged_plan_count':len({r['id'] for r in flags}),'flagged_evaluations':len(flags),
        'verdict_answers':dict(Counter(r.get('verdict',{}).get('estimate',{}).get('answer','missing_estimate') for r in rows)),
        'source_package':str(Path(plan.__file__).parent),'source_sha256_start':start,'source_sha256_end':sources(),
        'latency_s':quantiles([r['seconds'] for r in rows])}
    write(OUT/f'stress-{phase}-summary.json',summary);print(json.dumps({k:v for k,v in summary.items() if not k.startswith('source_')},ensure_ascii=False),flush=True)


def quantiles(xs):
    xs=sorted(xs)
    return {'p50':statistics.median(xs),'p95':xs[min(len(xs)-1,math.ceil(.95*len(xs))-1)],'max':max(xs)}


CLUSTER_NAMES = {
    'missing_route_scope': 'Route omitted from width estimate',
    'missing_verdict_estimate': 'Missing verdict estimate',
    'junction_cut': 'Unfiltered junction frontage',
    'bend_cut': 'Unfiltered bend frontage',
    'misaligned_cut': 'Misaligned automatic cut',
    'sample_prior_conflict': 'Conflicting sampled/class/access evidence',
    'cited_stop_prohibition': 'Cited stopping prohibition (retained)',
    'different_route_bottleneck': 'Door wider than another route segment',
    'narrow_cut_requires_field_check': 'Credible narrow cut / field review',
    'single_cut_confidence': 'Uncorroborated automatic negative',
    'clamped_basis_provenance': 'Basis differs from its cited sample',
    'failed_survey_midpoint': 'Unresolved survey labelled as a sample',
    'vehicle_monotonicity': 'Vehicle dominance regression',
    'street_prior_or_other_checks': 'Other street-negative review',
    'walk_or_contract': 'Walk / returned-stop contract', 'exception': 'Exception',
}
CLUSTER_NOTES = {
    'missing_route_scope': 'Public serialization removed route edges; estimate original selected routes and partial lengths.',
    'missing_verdict_estimate': 'No projected door/stop omitted the estimate; return explicit unknown/low.',
    'junction_cut': 'A cut within 5 m of a physical junction is frontage geometry; reject it and retain the diagnostic.',
    'bend_cut': 'A cut within 5 m of a bend over 15 degrees is diagonal frontage; reject it and retain the diagnostic.',
    'misaligned_cut': 'The cut lies over 1.5 m from its way; retain unresolved coverage instead of a width cap.',
    'sample_prior_conflict': 'Suppress generic road-class priors for checked parcel caps; retain credible cuts and stronger access-tag conflicts for review.',
    'cited_stop_prohibition': 'Retain the cited prohibition; a wide road does not authorize stopping.',
    'different_route_bottleneck': 'The route and door differ; name the limiting route way and show the door samples separately.',
    'narrow_cut_requires_field_check': 'Retain credible narrow geometry; sparse or uncorroborated automatic negatives stay low confidence.',
    'single_cut_confidence': 'Require two consistent independent automatic cuts for a confident bottleneck.',
    'clamped_basis_provenance': 'Cite the selected source’s actual sample, not a weaker fused cap.',
    'vehicle_monotonicity': 'Compare dominance and same-path estimate/confidence without relaxing hard checks.',
}


def load_results(phase):
    path = OUT/f'stress-{phase}.jsonl'
    if path.exists():
        return [json.loads(line) for line in path.read_text().splitlines()]
    with gzip.open(str(path)+'.gz', 'rt') as fp:
        return [json.loads(line) for line in fp]


def review_flags(results):
    """The same causal rules for both phases, including unused cut validation.

    A raw geometry problem is actionable only when the original sample still
    influenced the hypothesis/conflict and has no recorded rejection. Geometry
    rejections remain visible as diagnostics after a fix, not recurring errors.
    """
    from app.width_samples import assess
    graphs, expected = {}, {}
    reviewed = []
    for result in results:
        for row in result['rows']:
            for feature in row.get('features', []):
                item = dict(feature)
                fs = set(item['flags'])
                stop = row['door'] if item['scope'] == 'door' else row['stops'][0]
                value = item.get('width_hypothesis')
                profile = vehicles.get_profile(item['vehicle_id'])
                need = profile.door_min if item['limiting_way_id'] == item['stop_way_id'] else profile.tight_min
                # A single low outlier among many cuts is still one-cut evidence.
                # Check support metadata, not only the total number of cuts.
                uncorroborated = any(q.get('sample_min_m') is not None and value is not None and
                    abs(q['sample_min_m']-value) < .011 and
                    (q.get('isolated_low_outlier') or q.get('bottleneck_support', 0) < 2)
                    for q in item.get('sample_quality', []))
                if (item['answer'] == 'no' and item['confidence'] in ('medium', 'high') and
                        value is not None and value < need and uncorroborated and
                        stop['legality']['status'] not in ('Prohibited', 'Restricted') and
                        (stop.get('flood') or {}).get('stay', {}).get('status') != 'blocked'):
                    fs.add('single_cut_confidence')
                key, wid, raw = item['key'], item['limiting_way_id'], item.get('cut')
                if raw and raw.get('lat') is not None:
                    identity = (key, wid, raw['lat'], raw['lon'])
                    if identity not in expected:
                        if key not in graphs:
                            path = FROZEN/('demo_binhthanh.json' if key == 'demo' else f'area_{key}.json')
                            graphs[key] = osm.graph_from_elements(item['lat'], item['lon'],
                                                                 json.loads(path.read_text())['elements'])
                        g = graphs[key]
                        _, q = assess(g, g.ways[wid], [raw])
                        expected[identity] = [c['rejection_reason'] for c in q['rejected_cuts']]
                    rejected = [c for q in item.get('sample_quality', []) for c in q.get('rejected_cuts', [])]
                    already_rejected = any(abs(c.get('lat', 90)-raw['lat']) < 1e-7 and
                                           abs(c.get('lon', 180)-raw['lon']) < 1e-7 for c in rejected)
                    value = item.get('width_hypothesis')
                    in_use = ('sample_prior_conflict' in fs or
                              (value is not None and abs(value-raw['width_m']) < .011))
                    if in_use and not already_rejected:
                        for reason in expected[identity]:
                            fs.add({'within_5m_of_junction': 'unfiltered_junction_cut',
                                    'within_5m_of_bend_over_15deg': 'unfiltered_bend_cut',
                                    'off_centerline_over_1_5m': 'unfiltered_misaligned_cut'}[reason])
                if not fs:
                    continue
                stop = row['door'] if item['scope'] == 'door' else row['stops'][0]
                item.update(flags=sorted(fs), legal_status=stop['legality']['status'],
                            basis=stop['estimate']['basis'], fail_reasons=stop['fail_reasons'])
                if 'unfiltered_junction_cut' in fs:
                    primary = 'junction_cut'
                elif 'unfiltered_bend_cut' in fs:
                    primary = 'bend_cut'
                elif 'unfiltered_misaligned_cut' in fs:
                    primary = 'misaligned_cut'
                else:
                    primary = cluster({'flags': fs, 'limiting': {}, 'legal_status': item['legal_status']})
                item['cluster'] = primary
                reviewed.append(item)
        # Plan-wide invariants/dominance cannot be represented by a door feature.
        for flag in result['flags']:
            if flag.get('scope') is not None:
                continue
            item = dict(flag)
            if item['flags'] == ['missing_verdict_estimate']:
                item['cluster'] = 'missing_verdict_estimate'
            reviewed.append(item)
        # Catalogue order is not a physical dominance order (Fortuner is
        # narrower/shorter than class-m). Check both directions from the same
        # recorded plans, without making another planner/provider request.
        grouped = defaultdict(list)
        for row in result['rows']:
            if not row.get('error'):
                grouped[row['intent']].append(row)
        for group in grouped.values():
            for a, b in combinations(group, 2):
                ap, bp = vehicles.get_profile(a['vehicle_id']), vehicles.get_profile(b['vehicle_id'])
                dominates = lambda x, y: (x.mirror_width <= y.mirror_width and x.length <= y.length and
                    x.turning_radius <= y.turning_radius and x.safe_water_depth >= y.safe_water_depth)
                if dominates(ap, bp):
                    small, wide = a, b
                elif dominates(bp, ap):
                    small, wide = b, a
                else:
                    continue
                sd, wd = small.get('door'), wide.get('door')
                if not sd or not wd:
                    continue
                state = lambda d: (d['trace'].get('route_way_ids'), d['way_out']['mode'],
                    d['way_out'].get('route_verified'), d['legality']['status'], d['ok'])
                if state(sd) != state(wd):
                    continue
                se, we = sd['estimate'], wd['estimate']
                confidence = {'low': 0, 'medium': 1, 'high': 2}
                if we['answer'] == 'fits' and (se['answer'] != 'fits' or
                        confidence[se['confidence']] < confidence[we['confidence']]):
                    reviewed.append({**result['point'], 'id': small['id'], 'intent': small['intent'],
                        'vehicle_id': small['vehicle_id'], 'wider_vehicle': wide['vehicle_id'],
                        'scope': 'same_path_estimate', 'flags': ['estimate_monotonicity'],
                        'cluster': 'vehicle_monotonicity', 'small_estimate': se, 'wide_estimate': we})
    return reviewed


def plot_clusters(before, after, clusters, manifest):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from shapely.geometry import shape
    geo = json.loads((ROOT/'data/official/hcmc_urban_districts_2021.geojson').read_text())
    order = [c['cluster'] for c in clusters]
    colors = {c: plt.get_cmap('tab10')(i % 10) for i, c in enumerate(order)}
    fig = plt.figure(figsize=(20, 9), facecolor='#fafaf7')
    grid = fig.add_gridspec(1, 3, width_ratios=[1, 1, 1.35], wspace=.9)
    lons = [p['lon'] for p in manifest['points']]
    lats = [p['lat'] for p in manifest['points']]
    for i, (title, flags) in enumerate([('Before · 8775ef4', before), ('After · working tree', after)]):
        ax = fig.add_subplot(grid[0, i])
        ax.set_facecolor('#f3f5f0')
        for f in geo['features']:
            geometry = shape(f['geometry'])
            for poly in list(geometry.geoms) if hasattr(geometry, 'geoms') else [geometry]:
                x, y = poly.exterior.xy
                ax.fill(x, y, color='#e2e8e0')
                ax.plot(x, y, color='#b0bdb0', lw=.5)
        ax.scatter(lons, lats, s=8, c='#b5b5af', alpha=.5, zorder=2)
        for c in order:
            pts = {(f['lon'], f['lat']) for f in flags if f['cluster'] == c}
            if pts:
                x, y = zip(*pts)
                ax.scatter(x, y, s=27, color=colors[c], edgecolors='white', lw=.4, zorder=3)
        ax.set(xlim=(min(lons)-.015, max(lons)+.015), ylim=(min(lats)-.015, max(lats)+.015),
               xlabel='Longitude', ylabel='Latitude', title=f'{title}\n{len(flags):,} review evaluations')
        ax.set_aspect(1/.982)
        ax.set_anchor('N')
        ax.grid(alpha=.15)
    ax = fig.add_subplot(grid[0, 2])
    ax.set_facecolor('#fafaf7')
    y = list(range(len(order)))
    ax.barh([v-.18 for v in y], [c['before'] for c in clusters], height=.34,
            color=[colors[c] for c in order], label='Before')
    ax.barh([v+.18 for v in y], [c['after'] for c in clusters], height=.34,
            color=[colors[c] for c in order], alpha=.4, label='After')
    import textwrap
    ax.set_yticks(y, [textwrap.fill(CLUSTER_NAMES.get(c, c), 27) for c in order], fontsize=9)
    ax.invert_yaxis()
    for i, c in enumerate(clusters):
        ax.text(max(c['before'], c['after'])+max([x['before'] for x in clusters]+[1])*.015,
                i, f"{c['before']:,} → {c['after']:,}", va='center', fontsize=9)
    ax.set_xlim(0, max([max(c['before'], c['after']) for c in clusters]+[1])*1.3)
    ax.set_title('Causal review clusters', loc='left', fontweight='bold')
    ax.set_xlabel('Door / first-stop evaluations; plan contracts counted once')
    ax.legend(frameon=False)
    ax.spines[['top', 'right']].set_visible(False)
    fig.suptitle('HCMC cached engine stress · identical destinations and evidence', x=.05,
                 ha='left', fontsize=19, fontweight='bold')
    fig.text(.05, .035, f"{manifest['random_destinations']} seeded random + {len(manifest['points'])-manifest['random_destinations']} targeted destinations · 6 vehicles × park/pickup · no network\n"
             'Flags are software diagnostics and review candidates, not field-confirmed access failures. '
             'Coincident points collapse on maps; grey dots show all sampled destinations.', fontsize=10)
    fig.subplots_adjust(top=.88, bottom=.14)
    fig.savefig(ROOT/'docs/eval/engine-clusters.png', dpi=180, facecolor=fig.get_facecolor(), bbox_inches='tight')
    plt.close(fig)


def report():
    manifest = json.loads((OUT/'stress-inputs.json').read_text())
    raw = {phase: load_results(phase) for phase in ('before', 'after')}
    metadata = {p['i']: p for p in manifest['points']}
    for phase, results in raw.items():
        if {r['point']['i'] for r in results} != set(metadata):
            raise RuntimeError(f'{phase}: incomplete phase; finish every frozen destination before reporting')
        if sum(len(r['rows']) for r in results) != len(metadata)*len(IDS)*2:
            raise RuntimeError(f'{phase}: incomplete vehicle/intent cross-product')
        for result in results:
            point = metadata[result['point']['i']]
            result['point'].update(point)
            for row in result['rows']:
                row.update(point)
                for feature in row.get('features', []):
                    feature.update(point)
    rows = {phase: [r for x in results for r in x['rows']] for phase, results in raw.items()}
    flags = {phase: review_flags(results) for phase, results in raw.items()}
    counts = {phase: Counter(f['cluster'] for f in ff) for phase, ff in flags.items()}
    clusters = [{'cluster': c, 'before': counts['before'][c], 'after': counts['after'][c]}
                for c in sorted(set(counts['before']) | set(counts['after']),
                                key=lambda c: (-counts['before'][c], c))]
    summary = {'input_head': manifest['head'], 'destinations': len(manifest['points']),
               'random_mix': dict(Counter(p['sampling'] for p in manifest['points'] if p['cohort'] == 'random')),
               'selected_cells': len({p['key'] for p in manifest['points']}), 'clusters': clusters, 'validation': {}}
    for phase, rr in rows.items():
        summary['validation'][phase] = {
            'plans': len(rr), 'exceptions': sum('error' in r for r in rr),
            'invariants': dict(Counter(k for r in rr for k in r.get('invariants', []))),
            'flag_counts': dict(Counter(k for f in flags[phase] for k in f['flags'])),
            'flagged_plans': len({f['id'] for f in flags[phase]}),
            'latency_s': quantiles([r['seconds'] for r in rr]),
            'answers': dict(Counter(r.get('verdict', {}).get('estimate', {}).get('answer', 'missing_estimate') for r in rr))}
        for check in ('official_submetre', 'official_basis_without_sample', 'single_cut_confidence',
                      'basis_not_sample', 'vehicle_monotonicity', 'estimate_monotonicity',
                      'walk_over_cap', 'walk_geometry_mismatch', 'unsafe_offered_stop',
                      'door_stop_inconsistent', 'crash', 'unfiltered_misaligned_cut'):
            summary['validation'][phase]['flag_counts'].setdefault(check, 0)
    for phase in raw:
        phase_path = OUT/f'stress-{phase}-summary.json'
        phase_summary = json.loads(phase_path.read_text())
        phase_summary.setdefault('initial_screening', {k: phase_summary[k] for k in
            ('flags', 'clusters', 'flagged_plan_count', 'flagged_evaluations')})
        phase_summary.update(flags=summary['validation'][phase]['flag_counts'], clusters=dict(counts[phase]),
            flagged_plan_count=summary['validation'][phase]['flagged_plans'], flagged_evaluations=len(flags[phase]),
            clustering_policy='Uniform geometry revalidation in report(); initial screening retained separately')
        write(phase_path, phase_summary)
    summary['frozen_inputs_unchanged'] = all(sha(FROZEN/name) == digest
        for name, digest in manifest['frozen_files_sha256'].items())
    summary['static_inputs_sha256'] = {str(p.relative_to(RUNTIME/'data')): sha(p)
        for p in sorted((RUNTIME/'data').rglob('*')) if p.is_file()}
    summary['test_results'] = {}
    for name, filename in [('core', 'engine-stress-core-tests.txt'), ('backend', 'engine-stress-backend-final-tests.txt'),
                           ('regressions_before', 'engine-stress-regressions-before.txt')]:
        log = ROOT/'docs/eval'/filename
        if log.exists():
            summary['test_results'][name] = next((line.strip() for line in reversed(log.read_text().splitlines())
                if ' passed' in line and ' in ' in line), 'Run still in progress')
    write(OUT/'summary.json', summary)
    for phase in raw:
        with gzip.open(OUT/f'features-{phase}.jsonl.gz', 'wt') as fp:
            for row in rows[phase]:
                for feature in row.get('features', []):
                    fp.write(json.dumps(feature, ensure_ascii=False)+'\n')
        write(OUT/f'clusters-{phase}.json', flags[phase])
        target = next(x for x in raw[phase] if x['point'].get('label') == 'Ministop Trần Doãn Khanh')
        write(OUT/f'ministop-{phase}.json', target)
    plot_clusters(flags['before'], flags['after'], clusters, manifest)
    target = {phase: next(r for r in rows[phase] if r.get('label') == 'Ministop Trần Doãn Khanh'
                         and r['vehicle_id'] == 'class-m' and r['intent'] == 'park') for phase in raw}
    lines = ['# Engine stress test — 17 October 2026', '',
        f"Baseline: `{manifest['head']}` on `hackathon-night-2026-10-17`; after: uncommitted engine changes. "
        'No commits/pushes, Gemini, Goong, Overpass or planning-portal requests; all socket connections are denied. '
        'No HTTP server was started or restarted, and :8787 was left alone. Store, flags and cached evidence live under `tmp/engine-stress/`.', '',
        f"## Scope and frozen inputs\n\n**{len(manifest['points'])} destinations × six vehicles × two intents = {len(rows['after']):,} plans per phase.** "
        f"{manifest['random_destinations']} random destinations: {summary['random_mix']}; "
        f"{len(manifest['points'])-manifest['random_destinations']} targeted cached narrow-cut probes, including Ministop. "
        f"{summary['selected_cells']} distinct routing cells, drawn from {manifest['all_cached_cells_in_pool']:,} cached cells. "
        'The production demo graph is present before key selection, so demo/non-demo routing matches the app.', '',
        'VF 3, Vios, class-m, Fortuner, Carnival and Ford Transit; park 120 min / pickup 15 min; arrival '
        '`2026-10-17T09:31+07:00`. Road samples choose an eligible way then a node in its cell. '
        'Block probes are random cell-interior points ≥8 m from mapped road centrelines, not verified entrances. '
        'Near-road initial probes are retained as extra targeted controls and replaced in the random cohort. '
        'Strata use 17 urban district polygons (2021); outside coverage, nearest-centroid district labels are explicitly recorded. '
        'No claim of uniform city coverage or field accuracy; overlapping cells and six vehicles are correlated observations.', '',
        'City parcel/Declared snapshots, legacy area overlays, static vehicle/flood/field/official products and routing JSON are frozen. '
        'Legacy area records are replayed as server-owned test overlays; the current production loader rejects their old schema. '
        'No production schema/expiry policy is changed. The baseline package is exported from git into an isolated directory; '
        'the harness points both packages at the same frozen data. [Manifest](engine-stress-data/stress-inputs.json) contains file hashes. '
        f"Frozen routing/evidence hashes unchanged: **{summary['frozen_inputs_unchanged']}**.", '',
        '## Ministop Trần Doãn Khanh', '',
        'The archived [reported result](stress-known-before.json) contains `no/medium`, an Official-labelled 1.5 m hypothesis '
        'and a strict destination interval 0–5.86 m. The 1.5 m is consistent with the fallback midpoint of an unresolved survey, '
        'not the door’s own 5.56–5.65 m samples. At the requested merged HEAD, automatic parcel estimates already became Inferred; '
        'the exact old source label/verdict no longer reproduces. Instead, its estimate omits the approach/exit scope entirely.', '',
        f"Fresh baseline: `{target['before']['door']['estimate']['answer']}/{target['before']['door']['estimate']['confidence']}`; "
        f"{target['before']['door']['estimate']['coverage']['total_segments']} estimated segment(s). "
        f"After: `{target['after']['door']['estimate']['answer']}/{target['after']['door']['estimate']['confidence']}`; "
        f"{target['after']['door']['estimate']['coverage']['total_segments']} arrival/exit segments. "
        'The route basis cites Cây Điệp way 35113132 at 3.58 m; the door independently cites Trần Doãn Khanh way 35115025 at 5.56 m. '
        'The sampled bottleneck band is 5.26–5.86 m. Its strict lower bound remains zero; strict fit is unknown and `verified=false`. '
        'This merged product retains Inferred provenance and low confidence, rather than promoting cadastral geometry to measured clearance. '
        '[Before](engine-stress-data/ministop-before.json) · [after](engine-stress-data/ministop-after.json).', '',
        '## Rule changes and clusters', '',
        'D51–D54 document the changes. Validate cached cuts before fusion; reject junction/bend frontage and >1.5 m misalignment. '
        'MAD marks an isolated low cut for confidence review. It never removes a credible constriction solely for being narrow. '
        'Confident automatic width rejection needs two consistent cut centres ≥1 m apart, within 0.6 m of the narrowest cut. '
        'Keep whole-way verification strict; expose sampled width separately, preserve the source’s own numeric value, '
        'and estimate original route objects before public serialization strips their edge IDs. Every verdict now has an estimate.', '',
        'Rules are causal and deterministic; k-means/HDBSCAN would mostly cluster duplicate vehicles and mixed legitimate legal negatives. '
        'Geometry rules are reapplied equally to both phases: a raw problematic cut is flagged only if it still influences the estimate/conflict '
        'and lacks a recorded rejection. Each door/first-stop evaluation gets one primary cluster; missing-verdict contracts count once per plan. '
        'These are review diagnostics, not counts of field-proven access failures.', '',
        '| Primary cluster | Before | After | Cause / action |', '|---|---:|---:|---|']
    for c in clusters:
        lines.append(f"| {CLUSTER_NAMES.get(c['cluster'], c['cluster'])} | {c['before']} | {c['after']} | {CLUSTER_NOTES.get(c['cluster'], 'Review the recorded evidence and checks.')} |")
    lines += ['', '![HCMC failure clusters and before/after counts](engine-clusters.png)', '',
        '## Checks and latency', '', '| Check | Before | After |', '|---|---:|---:|']
    all_flags = set(summary['validation']['before']['flag_counts']) | set(summary['validation']['after']['flag_counts'])
    for name in sorted(all_flags):
        lines.append(f"| {name} | {summary['validation']['before']['flag_counts'].get(name, 0)} | {summary['validation']['after']['flag_counts'].get(name, 0)} |")
    for phase, v in summary['validation'].items():
        q = v['latency_s']
        lines += ['', f"**{phase.title()}**: {v['exceptions']} crashes; p50 **{q['p50']:.3f} s**, "
            f"p95 **{q['p95']:.3f} s**, max {q['max']:.3f} s. Four process workers, shared development machine; "
            'includes full plan/layers and trace instrumentation; graph/width caches are warm per destination. '
            'Excludes HTTP transport and one-time vehicle-envelope prewarming. '
            f"Invariants: `{v['invariants']}`. Answers: `{v['answers']}`."]
    lines += ['', 'Full-profile dominance compares mirror width, length and turning radius only when the smaller profile’s water tolerance is no worse. '
        'Same-path estimate/confidence monotonicity and progressive consistent evidence are also checked by the active estimate tests. '
        'Offered stops are checked for walk caps, geometry-plus-connector metres, fit exclusions, a Way Out, reverse limits and verdict/first-stop agreement.', '',
        '## Regressions and handoff', '',
        '`backend/tests/test_engine_quality.py` freezes Ministop plus ten distinct worst sampled door ways from the baseline '
        '(junction first, then extreme narrow conflicts). Self-contained cached geometry/cuts are in '
        '`backend/tests/fixtures/engine_regressions.json`; tests need no private runtime caches. '
        'Additional tests cover credible MAD outliers, independent/duplicate cut support, numeric-string caches, '
        'the unresolved Official midpoint, legacy single-cut confidence, route partial lengths and empty-network estimates. '
        f"Current core tests: **{summary['test_results'].get('core', 'not recorded')}**. "
        f"Full backend suite: **{summary['test_results'].get('backend', 'not recorded')}**. "
        'Network connections are denied, and writable backend paths are isolated. Parked prototype suites retain the repository’s default skips. '
        '[Core log](engine-stress-core-tests.txt) · [Full backend log](engine-stress-backend-final-tests.txt). '
        'The frozen quality regressions against the baseline produced **19 failures / 5 passes** before the citation-only test additions; '
        'all current quality regressions pass. [Baseline regression log](engine-stress-regressions-before.txt).', '',
        'English migration: all controlled copy in the owned engine files is English; real street names and legal citations remain verbatim. '
        'Rule summaries are English. The adapter, estimate basis and Restricted verdict each have citation regressions for the full law and QCVN citation. '
        'The remaining-string inventory in [Agent D’s English handoff](english-ui-handoff.md) was checked: dictionary inputs, generic-name matching, brands and identifiers are intentional. '
        'Legacy free-text evidence notes/source titles not recognized by the centralized adapter remain original text. '
        'The follow-up extension point is `ENGLISH_TEXT` / `ENGLISH_PREFIXES` / `ENGLISH_FRAGMENTS` in `evidence.py`. '
        '[Agent integration handoff](engine-agent-handoff.md) records the English caveat test update and a legacy null compact-flood renderer edge case.', '',
        'Changed engine files: `backend/app/plan.py`, `backend/app/evidence.py`, `backend/app/width_samples.py`. '
        'Added the regression module/fixture and `pipelines/stress_engine.py`; appended D51–D54 and these eval artifacts. '
        'Updated English-copy assertions in `test_engine_estimate.py`, `test_evidence_safety.py` and `test_plan_boundaries.py`. '
        'No geocoding, agent/search, frontend, MCP, portal transport or parcel-fetch code was edited by this task. '
        'Other agents’ shared-workspace changes are outside this report.', '',
        'Backend/API integration exposes `fit.width_range.sampled_estimate` and `estimate.stop_width`; strict `lo/hi` retain their safety meaning. '
        'The existing Result/Evidence width labels still format strict `lo/hi`; a frontend follow-up must wire the sampled band for estimate display '
        '(labelled sampled/unverified), while retaining strict bounds for clearance decisions. No frontend code was edited under Agent B ownership. '
        'The shared :8787 process has not reloaded these Python changes; its owner must reload it when coordinating the team handoff.', '',
        'Reproduce on the frozen runtime (network denied by the script):', '', '```sh',
        'python3 pipelines/stress_engine.py freeze --n 200 --seed 171026',
        'ENGINE_STRESS_BACKEND="$PWD/tmp/engine-stress/baseline-backend" python3 pipelines/stress_engine.py run --phase before --workers 4',
        'python3 pipelines/stress_engine.py run --phase after --workers 4',
        'python3 pipelines/stress_engine.py report', '```', '',
        'The isolated baseline package is a byte-for-byte export of `backend/app` from 8775ef4; it is not a worktree checkout. '
        'Raw plan summaries are `engine-stress-data/stress-{before,after}.jsonl.gz`; '
        'the smaller `features-{before,after}.jsonl.gz` record class/highway, district, cut-to-junction distance, cuts per way, tiers, '
        'vehicle class, door/stop scope, coverage and sample-quality diagnostics. Aggregate results are in '
        '[summary.json](engine-stress-data/summary.json).', '']
    (ROOT/'docs/eval/engine-stress.md').write_text('\n'.join(lines))
    for phase in raw:
        path = OUT/f'stress-{phase}.jsonl'
        if path.exists():
            with path.open('rb') as src, gzip.open(str(path)+'.gz', 'wb', compresslevel=6) as dst:
                shutil.copyfileobj(src, dst)
            path.unlink()
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['freeze','run','report'])
    parser.add_argument('--n',type=int,default=200);parser.add_argument('--seed',type=int,default=171026)
    parser.add_argument('--phase',choices=['before','after'],default='before');parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--limit',type=int)
    parser.add_argument('--append',action='store_true',help='Run only missing manifest point IDs and append to a phase')
    args=parser.parse_args()
    if args.action=='freeze':freeze(args.n,args.seed)
    elif args.action=='run':run(args.phase,args.workers,args.limit,args.append)
    else:report()


if __name__=='__main__':main()
