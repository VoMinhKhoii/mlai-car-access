#!/usr/bin/env python3
"""Seeded real-cache search + fallback-agent HTTP stress test. No outbound providers.

python3 pipelines/e2e_stress.py generate --n 480 --seed 171026
python3 pipelines/e2e_stress.py run --stage before --workers 4
python3 pipelines/e2e_stress.py report
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import re
import sqlite3
import statistics
import subprocess
import sys
import time
import unicodedata
import urllib.request
import urllib.parse

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/eval'
BASE = 'http://127.0.0.1:8793'
def norm(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s.lower().replace('đ','d').replace('ð','d')) if unicodedata.category(c) != 'Mn')
def write(p, obj): p.write_text(json.dumps(obj, ensure_ascii=False, indent=2))
def hashes():
    return {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ['backend/app/agent.py','backend/app/geocoding.py','backend/app/vehicles.py','backend/app/plan.py','backend/app/evidence.py']}
def gate():
    stat = subprocess.check_output(['git','diff','--stat','--','backend/app/geocoding.py','backend/app/agent.py'], cwd=ROOT, text=True)
    fingerprint = hashlib.sha256((stat + json.dumps({k:v for k,v in hashes().items() if k.endswith(('agent.py','geocoding.py'))},sort_keys=True)).encode()).hexdigest()
    p=OUT/'e2e-concurrency-gate.json'; now=time.time()
    old=json.loads(p.read_text()) if p.exists() else {}
    start=old.get('stable_since',now) if old.get('fingerprint')==fingerprint else now
    proof=[str(p.relative_to(ROOT)) for p in (OUT).glob('mapsearch-*.png')]
    state={'observed_at':datetime.now(timezone.utc).isoformat(),'stable_since':start,'stable_seconds':now-start,'fingerprint':fingerprint,'diff_stat':stat,'mapsearch_pngs':proof,'ready':now-start>=600 and bool(proof)}
    write(p,state)
    with (OUT/'e2e-concurrency-observations.jsonl').open('a') as f:f.write(json.dumps(state)+'\n')
    print(json.dumps(state,ensure_ascii=False))
    return state

VEHICLES=[('Merc GLC 200','class-m',False),('Mercedes GLC 300','class-m',False),('Mercedes C 200','mercedes-benz-c-class',True),('Mercedes E 200','class-m',False),('BMW X3','class-m',False),('Kia Sorento','class-m',False),('Kia Carnival','kia-carnival',True),('Honda CR-V','class-m',False),('Honda City','honda-city',True),('Hyundai Tucson','class-m',False),('Ford Ranger','ford-ranger',True),('VinFast VF 3','vinfast-vf-3',True),('VF4',None,False),('VinFast VF 5','vinfast-vf-5',True),('VF6','vinfast-vf-6',True),('VF7','vinfast-vf-7',True),('VF8','vinfast-vf-8',True),('VF9','vinfast-vf-9',True),('xe 7 chỗ','class-m',True),('bán tải','class-l',True),('xe 16 chỗ','class-xl',True),('xe máy',None,False),('motorbike',None,False),('Toyota Vios','toyota-vios',True)]
ALLEY=re.compile(r'^(?:hem|ngo|kiet|ngach)\s+(\d+[a-z]?(?:/\d+[a-z]?)*)\s+(.+)$')

def generate(n,seed):
    rng=random.Random(seed)
    from shapely.geometry import Point, shape
    from shapely.prepared import prep
    districts=[(f['properties']['name'],prep(shape(f['geometry']))) for f in json.loads((ROOT/'data/official/hcmc_urban_districts_2021.geojson').read_text())['features']]
    def district(p):
        point=Point(p['lon'],p['lat'])
        return next((name for name,poly in districts if poly.covers(point)),None)
    names=json.loads((ROOT/'backend/store/osm_name_index.json').read_text())['names']
    # Merge same-name way segments into an independent identity oracle.
    byname=defaultdict(list)
    for p in names:byname[norm(p['label'])].append(p)
    alleys=[p for p in names if ALLEY.match(norm(p['label'])) and len(ALLEY.match(norm(p['label']))[2])>=5]
    unique=list({norm(p['label']):p for p in alleys}.values())
    rng.shuffle(unique)
    official=json.loads((ROOT/'data/official/fire_access_4582.json').read_text())['items']
    official_matches=[(r,byname[norm(r['name'])][0]) for r in official if norm(r['name']) in byname]
    listings=[]
    with sqlite3.connect(ROOT/'data/raw/listings_city/listings.sqlite') as db:
        for (raw,) in db.execute('SELECT payload FROM ads'):
            row=json.loads(raw); street=norm(row.get('street_name',''));street=re.sub(r'^duong\s+','',street)
            if not street:continue
            # Listing-derived addresses are accepted only when their real chain/street
            # also identifies an indexed alley; advertising dimensions are not truth.
            text=norm(row.get('body','')+' '+row.get('subject',''))
            chains=re.findall(r'(?<!\d)\d+[a-z]?(?:/\d+[a-z]?){1,3}',text)
            for chain in chains:
                key='hem '+chain+' '+street
                if key in byname:
                    listings.append((row,byname[key][0]));break
    rng.shuffle(official_matches);rng.shuffle(listings)
    rows=[]
    for i in range(n):
        provenance='osm_index'; suffix='';era='none'
        if i%8==0 and official_matches:
            src,p=official_matches[(i//8)%len(official_matches)]; provenance='qd4582';suffix=', '+src['ward']+', TP.HCM';era='post2025'
        elif i%8==1 and listings:
            src,p=listings[(i//8)%len(listings)];provenance='listing_address';suffix=', TP.HCM'
        else:p=unique[i%len(unique)]
        m=ALLEY.match(norm(p['label']));chain,street=m.groups()
        # Keep the exact real alley name, append synthetic house subdivisions.
        raw=re.match(r'^\S+\s+\S+\s+(.+)$',p['label'])[1]
        depth=1+i%4
        parts=chain.split('/')
        while len(parts)<depth:parts.append(str(rng.randint(1,49))+('A' if i%11==0 else ''))
        target='/'.join(parts);prefix=['','hẻm ','ngõ ','kiệt ','ngách ','alley '][i%6]
        address=prefix+target+' '+raw
        if not suffix and i%3==0 and district(p):suffix=', '+district(p)+', Hồ Chí Minh';era='historical'
        address+=suffix
        variant='accented'
        if i%5==0:address=norm(address);variant='no_diacritics'
        elif i%17==0:
            address=address.replace(raw,raw[:-1] if len(raw)>6 else raw);variant='typo'
        # Oracle: longest mapped chain prefix, independently of resolver code.
        longest=max((j for j in range(1,len(parts)+1) if 'hem '+'/'.join(parts[:j])+' '+street in byname),default=len(chain.split('/')))
        key='hem '+'/'.join(parts[:longest])+' '+street
        truths=byname.get(key,[p]);truth=truths[0]
        car,vid,incat=VEHICLES[i%len(VEHICLES)]
        intent='pickup' if i%3==1 else 'park';hour=8 if i%2 else 19;dwell=10 if intent=='pickup' else 120
        template=i%5
        if template==0:message=f'{address} - {car}'
        elif template==1:message=f'Tôi lái {car} tới {address}, đón khách sáng mai 8h, dừng 10 phút.'
        elif template==2:message=f'{car} đỗ xe tại {address}, tối nay 19h trong 2 tiếng.'
        elif template==3:message=f'Can my {car} park at {address} tomorrow at 8am for 120 minutes?'
        else:message=f'Đi {car} đến {address}, đỗ 2 tiếng lúc 19h.'
        if template!=1:intent='park';dwell=120
        if car=='VF8':vid='vinfast-vf-8-the-all-new-2026'
        rows.append({'id':f'random-{i:03}','query':message,'search_query':address,'truth':{'label':truth['label'],'way_ids':[q['way_id'] for q in truths],'lat':truth['lat'],'lon':truth['lon'],'precision':'alley','fallback':target!='/'.join(parts[:longest])},'expect':{'vehicle_id':vid,'decline':car in ('xe máy','motorbike'),'unknown_vehicle':car=='VF4','intent':intent,'dwell_min':dwell,'hour':8 if template in (1,3) else 19 if template else None,'tomorrow':template in (1,3)},'features':{'pattern':['address_first','pickup','park','english','drive'][template],'chain_depth':len(parts),'diacritics':variant,'ward_era':era,'catalogue':incat,'vehicle':car,'provenance':provenance}})
    # Required reproduction is deliberately not assigned an invented OSM way ID.
    # Exact source absence is measured, rather than blessing another 137 branch.
    rows.insert(0,{'id':'user-repro','query':'137/41/18 Trần Đình Xu, Cầu Ông Lãnh, Hồ Chí Minh, Vietnam - Merc GLC 200','search_query':'137/41/18 Trần Đình Xu, Cầu Ông Lãnh, Hồ Chí Minh, Vietnam','truth':{'label':'Hẻm 137/41 Trần Đình Xu','way_ids':[],'lat':10.761,'lon':106.690,'precision':'alley','fallback':True},'expect':{'vehicle_id':'class-m','intent':'park'},'features':{'pattern':'address_first','chain_depth':3,'diacritics':'accented','ward_era':'post2025','catalogue':False,'vehicle':'Merc GLC 200','provenance':'user_repro'}})
    for j,(address,kind) in enumerate([('Chợ Bến Thành','poi'),('HUTECH','ambiguous'),('Trần Đình Xu','street'),('Tô Ngọc Vân','street'),('Highlands','ambiguous'),('12/3 Cao Thắng','unknown_branch')]):
        match=byname.get(norm(address),[])
        rows.append({'id':f'supplement-{j}','query':f'Tôi lái Honda City tới {address}, đỗ 2 tiếng lúc 19h.','search_query':address,'truth':{'label':address,'way_ids':[p['way_id'] for p in match],'lat':match[0]['lat'] if match else 10.7769,'lon':match[0]['lon'] if match else 106.7009,'precision':kind},'expect':{'vehicle_id':'honda-city','clarify':kind in ('ambiguous','unknown_branch')},'features':{'pattern':kind,'chain_depth':0,'diacritics':'accented','ward_era':'none','catalogue':True,'vehicle':'Honda City','provenance':'supplement'}})
    # Follow-ups have authentic structured tool history from their parent's HTTP run.
    for i,msg in enumerate(['Đổi sang VF3 thì sao?','Đổi sang sáng mai lúc 8h nhé','Còn chỗ nào gần hơn?','Nếu mưa 45 mm/h thì sao?']):
        parent=next(r for r in rows if r['expect'].get('vehicle_id')=='honda-city' and r['id'].startswith('random'))
        rows.append({**parent,'id':f'follow-{i}','query':msg,'parent':parent['id'],'expect':{**parent['expect'],'vehicle_id':'vinfast-vf-3' if i==0 else 'honda-city'},'features':{**parent['features'],'pattern':'followup'}})
    write(OUT/'e2e-inputs.json',{'seed':seed,'generated_at':datetime.now(timezone.utc).isoformat(),'source_counts':{'index':len(names),'alleys':len(unique),'matched_listings':len(listings),'matched_qd4582':len(official_matches)},'source_hashes':hashes(),'cases':rows})
    print('generated',len(rows),'cases',Counter(r['features']['provenance'] for r in rows))

def request(path,body=None):
    data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None
    req=urllib.request.Request(BASE+path,data=data,headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=240) as r:return r.read().decode()
def truth_match(p,truth):
    if truth['way_ids'] and p.get('way_id') in truth['way_ids']:return True
    return norm(p.get('label','')).split(',')[0]==norm(truth['label']).split(',')[0]
def assess(case,search,events):
    failures=[];expect=case['expect'];truth=case['truth']
    geo=next((e.get('result',{}) for e in reversed(events) if e.get('name')=='tim_dia_diem' and e['type']=='tool_result'),{})
    calls=[e for e in events if e['type']=='tool_call'];plans=[e for e in calls if e['name']=='lap_ke_hoach']
    answer=next((e.get('text','') for e in events if e['type']=='answer'),'')
    special=truth['precision'] in ('poi','street','ambiguous','unknown_branch')
    sm=any(truth_match(p,truth) for p in search.get('results',[]))
    gm=bool(geo.get('results') and truth_match(geo['results'][0],truth))
    if not special and not sm:failures.append('search_wrong_or_missing_alley')
    if expect.get('decline'):
        if plans or not re.search(r'xe may|motorbike|xe hai banh|o to',norm(answer)):failures.append('motorbike_not_declined')
    elif expect.get('unknown_vehicle'):
        if plans:failures.append('invented_vehicle')
    elif expect.get('clarify'):
        if plans:failures.append('ambiguous_planned')
    else:
        if not case.get('parent') and not geo:failures.append('destination_not_parsed')
        elif not special and not case.get('parent') and not gm:failures.append('agent_wrong_or_missing_alley')
        if not plans:failures.append('missing_plan')
        elif plans[-1]['args'].get('vehicle_id')!=expect.get('vehicle_id'):failures.append('vehicle_mapping')
        if plans and not case.get('parent'):
            args=plans[-1]['args']
            for field in ('intent','dwell_min'):
                if field in expect and args.get(field)!=expect[field]:failures.append('args_'+field)
            if expect.get('hour') is not None:
                try:
                    dt=datetime.fromisoformat(args['arrive_at'])
                    if dt.hour!=expect['hour']:failures.append('arrival_time')
                    day=datetime.now(dt.tzinfo).date()
                    if (dt.date()-day).days!=int(expect.get('tomorrow',False)):failures.append('arrival_day')
                except (ValueError,KeyError):failures.append('arrival_time')
        if plans and not any(e['type']=='ui' for e in events):failures.append('plan_error')
        if plans and not case.get('parent') and not special and not gm:failures.append('wrong_place_plan')
        if plans and not case['features']['catalogue'] and not re.search(r'chua co|nhom|thay the|tuong duong',norm(answer)):failures.append('missing_vehicle_note')
        if plans and truth.get('fallback') and not re.search(r'chua.*so nha|hem.*chua|hem cha|nhanh.*chua|tren hem',norm(answer)):failures.append('missing_precision_note')
    if any(e['type']=='error' for e in events):failures.append('runtime_error')
    if not answer:failures.append('missing_answer')
    cls=('decline' if expect.get('decline') and not plans else 'wrong_place' if 'wrong_place_plan' in failures else 'plan' if any(e['type']=='ui' for e in events) else 'refusal' if not answer else 'clarify')
    # One primary cluster per case; secondary labels are retained for analysis.
    priority=['runtime_error','plan_error','search_wrong_or_missing_alley','destination_not_parsed','agent_wrong_or_missing_alley','vehicle_mapping','missing_plan','motorbike_not_declined','missing_vehicle_note','missing_precision_note','ambiguous_planned','invented_vehicle','missing_answer','args_intent','args_dwell_min','arrival_time','arrival_day']
    cluster=next((f for f in priority if f in failures),'pass')
    return {'passed':not failures,'failures':failures,'cluster':cluster,'search_match':sm,'agent_match':gm,'resolved':geo.get('results',[]),'vehicle_mapping':plans[-1]['args'].get('vehicle_id') if plans else None,'tool_sequence':[e['name'] for e in calls],'plan_ran':any(e['type']=='ui' for e in events),'answer_class':cls,'answer':answer,'feature_vector':{**case['features'],'resolver_source':(geo.get('results') or [{}])[0].get('source'),'failed_step':cluster}}
def run(stage,workers,limit):
    fixture=json.loads((OUT/'e2e-inputs.json').read_text());cases=fixture['cases'][:limit] if limit else fixture['cases']
    history={};rows=[];started=time.time();source=hashes()
    output=OUT/f'e2e-{stage}.jsonl'
    def one(case):
        begin=time.monotonic();err=None;events=[];search={}
        try:
            st=time.monotonic();search=json.loads(request('/api/search?'+urllib.parse.urlencode({'q':case['search_query']})));sl=time.monotonic()-st
            at=time.monotonic();raw=request('/api/agent',{'message':case['query'],'contents':history.get(case.get('parent'),[])});events=[json.loads(l) for l in raw.splitlines() if l.strip()];al=time.monotonic()-at
        except Exception as exc:err=str(exc);sl=al=None;events.append({'type':'error','text':err})
        result=assess(case,search,events)
        done=next((e for e in events if e['type']=='done'),{})
        row={'id':case['id'],'latency_s':round(time.monotonic()-begin,3),'search_latency_s':sl,'agent_latency_s':al,'search':search,**result,'events':[e for e in events if e['type']!='done'],'http_error':err}
        return row,done.get('contents',[])
    with output.open('w') as f:
        for batch in ([c for c in cases if not c.get('parent')],[c for c in cases if c.get('parent')]):
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures={pool.submit(one,c):c for c in batch}
                for future in as_completed(futures):
                    row,h=future.result();rows.append(row);history[row['id']]=h;f.write(json.dumps(row,ensure_ascii=False)+'\n');f.flush()
                    if len(rows)%20==0 or row['id']=='user-repro':print(stage,len(rows),'/',len(cases),row['id'],row['cluster'],row['latency_s'],flush=True)
    summary={'stage':stage,'count':len(rows),'passed':sum(r['passed'] for r in rows),'plans':sum(r['plan_ran'] for r in rows),'clusters':dict(Counter(r['cluster'] for r in rows)),'latency_p50_s':statistics.median(r['latency_s'] for r in rows),'latency_p90_s':sorted(r['latency_s'] for r in rows)[int(len(rows)*.9)],'duration_s':time.time()-started,'source_hashes_start':source,'source_hashes_end':hashes(),'mode':'deterministic fallback, real cached geocoder and engine, HTTP 8793'}
    write(OUT/f'e2e-{stage}-summary.json',summary);print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['generate','run','gate']);p.add_argument('--n',type=int,default=480);p.add_argument('--seed',type=int,default=171026);p.add_argument('--stage',default='before');p.add_argument('--workers',type=int,default=4);p.add_argument('--limit',type=int);a=p.parse_args()
    if a.command=='generate':generate(a.n,a.seed)
    elif a.command=='run':run(a.stage,a.workers,a.limit)
    else:gate()
