"""VOI-first single-cut crawler; local planning never contacts the parcel portal.

The API queue order is authoritative. Cached raw footprint stations and previous
parcel cuts only choose where to inspect; inferred hints never become evidence.
"""
from __future__ import annotations
import argparse
from collections import deque
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import time

import httpx
from shapely.geometry import LineString
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from app import evidence_queue, osm, parcels, portal_gate
from app.config import CACHE

ROOT=Path(__file__).resolve().parents[1]
POLICY='voi-single-cut-v4'


def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return {}


def queue_snapshot(base='http://127.0.0.1:8787'):
    from urllib.parse import urlsplit
    if urlsplit(base).hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('Queue API must be local')
    try:
        response=httpx.get(base.rstrip('/')+'/api/evidence/queue',params={'limit':1000},timeout=60,trust_env=False)
        response.raise_for_status();data=response.json();source='GET /api/evidence/queue?limit=1000'
    except (httpx.HTTPError,ValueError):
        data=evidence_queue.queue(limit=1000);source='same in-process evidence_queue.queue (local API unavailable)'
    if not data.get('available') or not isinstance(data.get('items'),list):
        raise RuntimeError('Evidence queue unavailable; no unranked portal fallback')
    return data,source


class GeometryProbe(parcels.Unavailable):pass


class CutPlanner:
    def __init__(self, inventory=None, city=None, hints=None):
        self.inventory=inventory if inventory is not None else read(evidence_queue.INVENTORY)
        self.ways=self.inventory.get('ways',{})
        self.city=city if city is not None else read(CACHE/'live/city_parcels.json')
        self.hints=hints if hints is not None else self.load_hints()
        self.junction_cache={}

    def load_hints(self):
        # Only an advisory index; use the latest cached raw footprint run.
        directories=sorted((ROOT/'data/raw/buildings').glob('tiles_*'),key=lambda p:p.stat().st_mtime,reverse=True)
        hints={}
        if not directories:return hints
        for path in sorted(directories[0].glob('*.json')):
            for wid,row in read(path).get('ways',{}).items():
                candidates=[cut for cut in row.get('samples',[]) if cut.get('status')=='ok'
                            and isinstance(cut.get('gap_m'),(int,float)) and math.isfinite(cut['gap_m'])]
                if candidates:hints[wid]=sorted(candidates,key=lambda cut:cut['gap_m'])
        return hints

    def junctions(self, lat, lon):
        key=osm.area_key(lat,lon)
        if key not in self.junction_cache:
            graph=osm.cached_graph(lat,lon)
            if graph is None:return None
            neighbors={}
            for edge in graph.edges:
                if graph.ways[edge.way_id].drivable:
                    neighbors.setdefault(edge.u,set()).add(edge.v)
                    neighbors.setdefault(edge.v,set()).add(edge.u)
            self.junction_cache[key]=[graph.nodes[n] for n,arms in neighbors.items() if len(arms)>=3]
            osm._GRAPHS.pop(key,None)
        return self.junction_cache[key]

    def eligible(self,line,at,lat,lon):
        p=line.interpolate(at);la,lo=lat+p.y/parcels.KY,lon+p.x/parcels.KX
        junctions=self.junctions(la,lo)
        if junctions is None:return False,'missing_cached_graph'
        if any(osm.haversine(la,lo,*j)<5 for j in junctions):return False,'junction_frontage_unvalidated'
        def probe(*args):raise GeometryProbe()
        try:parcels._cut_at(line,at,lat,lon,probe)
        except GeometryProbe:return True,None
        return False,'corner_or_degenerate_cut'

    def select(self,item):
        wid=str(item['way_id']);row=self.ways.get(wid)
        plan={**item,'phase':item.get('phase','queue'),'policy':POLICY}
        if row is None:return {**plan,'status':'skip','reason':'missing_inventory_geometry'}
        way=osm.Way(int(wid),row['tags'],[])
        if not way.drivable or way.kind=='main':return {**plan,'status':'skip','reason':'not_drivable_non_main'}
        coords=[(la,lo) for lo,la in row['coords']]
        if len(coords)<2:return {**plan,'status':'skip','reason':'degenerate_way'}
        lat,lon=coords[0];line=LineString([parcels._local(lo,la,lat,lon) for la,lo in coords])
        if line.length<6:return {**plan,'status':'skip','reason':'way_shorter_than_6m'}
        candidates=[]
        prior=self.city.get(wid) or {}
        for cut in prior.get('cuts',[]):
            if not cut.get('valid',True) or not isinstance(cut.get('width_m'),(int,float)):continue
            if 'lat' in cut and 'lon' in cut:
                from shapely.geometry import Point
                p=Point(*parcels._local(cut['lon'],cut['lat'],lat,lon))
                if p.distance(line)>2:continue
                at=line.project(p)
            else:at=cut.get('at_m')
            if isinstance(at,(int,float)):
                candidates.append((cut['width_m'],at,'narrowest_cached_parcel_cut'))
        for cut in self.hints.get(wid,[]):
            candidates.append((max(0,cut['gap_m']-parcels.USABLE_MARGIN),cut['at_m'],'narrowest_cached_footprint_station'))
        # Lowest suspected clearance first. Hints are never used as a measured width.
        candidates.sort(key=lambda candidate:(candidate[0],candidate[1]))
        along=0;interiors=[]
        for a,b in zip(line.coords,line.coords[1:]):
            length=math.dist(a,b)
            interiors.append((length,along+length/2));along+=length
        candidates.extend((None,at,'longest_straight_interior_no_located_width_hint') for _,at in sorted(interiors,reverse=True))
        candidates.append((None,line.length/2,'geometric_interior_fallback_no_located_width_hint'))
        rejected=[];seen=set()
        for suspected,at,reason in candidates:
            if not 1<=at<=line.length-1 or round(at,2) in seen:continue
            seen.add(round(at,2));valid,why=self.eligible(line,at,lat,lon)
            if not valid:
                rejected.append(why);continue
            point=line.interpolate(at)
            return {**plan,'status':'ready','at_m':round(at,3),'fraction':at/line.length,
                    'cut_lat':lat+point.y/parcels.KY,'cut_lon':lon+point.x/parcels.KX,
                    'cut_reason':reason,'suspected_width_hint_m':suspected,'length_m':round(line.length,2),
                    'thresholds_m':{key:evidence_queue.THRESHOLDS[key] for key in item.get('thresholds_straddled',[])},
                    'rejected_candidates':rejected}
        return {**plan,'status':'skip','reason':'no_valid_cached_geometry_station','rejected_candidates':rejected}

    def coords(self,wid):return [(la,lo) for lo,la in self.ways[str(wid)]['coords']]


def ordered_items(snapshot,inner,inventory,completed=()):
    """Exact queue order, then campus membership, then unseen urban inventory."""
    seen=set(map(str,completed));out=[]
    for row in snapshot['items']:
        wid=str(row['way_id'])
        if wid not in seen:
            out.append({**row,'phase':'queue'});seen.add(wid)
    for wid in sorted(map(str,inner),key=int):
        if wid not in seen and wid in inventory:
            out.append({'way_id':int(wid),'phase':'campus-inner','score':None,'thresholds_straddled':[]});seen.add(wid)
    for wid,row in inventory.items():
        way=osm.Way(int(wid),row['tags'],[])
        if wid not in seen and way.drivable and way.kind!='main':
            out.append({'way_id':int(wid),'phase':'breadth','score':None,'thresholds_straddled':[]});seen.add(wid)
    return out


def merge_result(previous,result,plan):
    previous=previous or {};cuts=[dict(c) for c in previous.get('cuts',[])]
    for cut in result.get('cuts',[]):
        cuts=[c for c in cuts if not (abs(c.get('at_m',-100)-cut['at_m'])<.2 and
                  abs(c.get('lat',-100)-cut['lat'])<.00002 and abs(c.get('lon',-100)-cut['lon'])<.00002)]
        cuts.append(cut)
    return {**result,'cuts':cuts,'samples':[c['width_m'] for c in cuts if c.get('valid',True) and c.get('width_m') is not None],
            'deep':False,'prior_scan_deep':previous.get('deep',False),'sample_strategy':POLICY,
            'selected_cut':{key:plan.get(key) for key in ('at_m','cut_reason','score','thresholds_straddled')},
            'queried_at':datetime.now().astimezone().isoformat(),
            'coverage':{**result.get('coverage',{}),'complete':False,'all_valid':bool(cuts) and all(c.get('valid',True) for c in cuts)}}


def run(state,cache,lookup,stop,save,log,queue_base='http://127.0.0.1:8787'):
    planner=CutPlanner(city=cache)
    done=state.setdefault('ranked_done',{})
    inner=set().union(*(set(ids) for ids in state.get('campus_inner_targets',{}).values()))
    state.update(stage='ranked_voi',method=POLICY)
    pending=deque();refreshed=0
    while not stop.is_set():
        if not pending or time.time()-refreshed>=1800:
            try:snapshot,source=queue_snapshot(queue_base)
            except Exception as exc:
                log.warning('RANKED_QUEUE unavailable=%s; no portal work',type(exc).__name__);stop.wait(60);continue
            recent={wid for wid,row in done.items() if time.time()-row.get('at',0)<86400}
            pending=deque(ordered_items(snapshot,inner,planner.ways,recent));refreshed=time.time()
            state['ranked_queue']={'source':source,'generated_at':snapshot['generated_at'],
                'first20':[row['way_id'] for row in snapshot['items'][:20]],'pending':len(pending)}
            log.info('RANKED_QUEUE source=%s first20=%s',source,state['ranked_queue']['first20']);save()
        if not pending:stop.wait(60);continue
        portal_gate.observe_api_backoff()
        until=portal_gate.cooldown_until()
        if until>time.time():
            state['cooldown_until']=datetime.fromtimestamp(until).astimezone().isoformat();save()
            stop.wait(min(30,until-time.time()));continue
        item=pending.popleft();wid=str(item['way_id']);plan=planner.select(item)
        state['ranked_current']=plan
        if plan['status']=='ready':
            row=planner.ways[wid];way=osm.Way(int(wid),row['tags'],[])
            state.setdefault('ways_meta',{}).setdefault(wid,{'coords':planner.coords(wid),'name':way.name,
                'alley':way.is_alley,'cell':osm.area_key(plan['cut_lat'],plan['cut_lon']),
                'district':'evidence-queue','inventory_generated_at':planner.inventory.get('generated_at')})
        save()
        if plan['status']!='ready':
            done[wid]={'at':time.time(),'status':'skipped_geometry','reason':plan['reason']}
            log.info('RANKED_SKIP way=%s reason=%s',wid,plan['reason']);save();continue
        log.info('RANKED_CUT phase=%s way=%s score=%s at_m=%.3f reason=%s thresholds=%s',
                 plan['phase'],wid,plan.get('score'),plan['at_m'],plan['cut_reason'],plan.get('thresholds_straddled'))
        try:
            result=parcels.measure(planner.coords(wid),fractions=(plan['fraction'],),parcel_lookup=lookup)
            if result is not None:
                cache[wid]=merge_result(cache.get(wid),result,plan)
            done[wid]={'at':time.time(),'status':'measured' if result and result.get('samples') else 'no_valid_frontage',
                       'selected_at_m':plan['at_m'],'phase':plan['phase']}
            log.info('RANKED_DONE way=%s status=%s',wid,done[wid]['status'])
        except parcels.Blocked:
            state['blocked']+=1;pending.appendleft(item)
            log.warning('RANKED_LOCK way=%s spacing_s=%.1f recovery_until=%.0f',wid,
                        portal_gate.request_interval(),portal_gate.cooldown_until())
        except Exception as exc:
            state['errors']+=1;pending.appendleft(item)
            log.warning('RANKED_RETRY way=%s error=%s',wid,type(exc).__name__);stop.wait(60)
        save()


def dry_plan(base,output):
    snapshot,source=queue_snapshot(base);planner=CutPlanner()
    state=read(CACHE/'live/crawl_city_state.json')
    inner=set().union(*(set(ids) for ids in state.get('campus_inner_targets',{}).values()))
    items=ordered_items(snapshot,inner,planner.ways)
    plans=[planner.select(row) for row in items[:20]]
    expected=[row['way_id'] for row in snapshot['items'][:20]];actual=[row['way_id'] for row in plans]
    result={'generated_at':datetime.now().astimezone().isoformat(),'source':source,'queue_generated_at':snapshot['generated_at'],
        'first20_equal':expected==actual,'api_first20':expected,'planned_first20':actual,'plans':plans,
        'phase_order':['queue','campus-inner-500m','breadth'],'portal_requests':0,
        'learning':portal_gate.learned_spacing(180)}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps({key:result[key] for key in ('first20_equal','api_first20','portal_requests','learning')}))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--queue-base',default='http://127.0.0.1:8787')
    parser.add_argument('--plan-output',type=Path,default=ROOT/'docs/eval/crawler-round4-plan.json');args=parser.parse_args()
    dry_plan(args.queue_base,args.plan_output)
