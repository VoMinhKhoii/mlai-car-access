"""Deterministic cached-data input stress. No external HTTP, LLM or engine charges.

Run PYTHONPATH=backend python3 pipelines/stress_inputs.py --output tmp/input-stress/after.json.
Expected points are the OSM ways used to generate each request, never resolver output.
"""
from __future__ import annotations
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
import subprocess
import types
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app import agent, geocoding as geo
from app.osm import strip_accents, haversine

VEHICLES = [
    ('Merc GLC 200', 'class-m', 'outside'), ('Mercedes GLC 300', 'class-m', 'outside'),
    ('Mercedes C200', 'mercedes-benz-c-class', 'catalogue'), ('Mercedes E300', 'class-m', 'outside'),
    ('BMW X3', 'class-m', 'outside'), ('Kia Sorento', 'class-m', 'outside'),
    ('Honda CR-V', 'class-m', 'outside'), ('Honda City', 'honda-city', 'catalogue'),
    ('Hyundai Tucson', 'class-m', 'outside'), ('Ford Ranger', 'ford-ranger', 'catalogue'),
    *[(f'VinFast VF{i}', ('vinfast-vf-8-the-all-new-2026' if i == 8 else f'vinfast-vf-{i}'), 'catalogue') for i in (3, 5, 6, 7, 8, 9)],
    ('xe 7 chỗ', 'class-m', 'class'), ('bán tải', 'class-l', 'class'), ('16 chỗ', 'class-xl', 'class'),
]

def source_names(index_path=None):
    # Snapshot the real cached index: do not modify the live backend store.
    data = json.loads((index_path or ROOT / 'backend/store/osm_name_index.json').read_text())['names']
    return data


def generate(names):
    seen, groups = set(), defaultdict(list)
    for p in sorted(names, key=lambda p: p['label']):
        norm = strip_accents(p['label'])
        if norm in seen: continue
        seen.add(norm)
        chain = re.search(r'\b(\d+[a-z]?(?:/\d+[a-z]?)*)\b', norm)
        if norm.startswith('hem ') and chain:
            groups[min(4, chain[1].count('/') + 1)].append(p)
    cases = []
    variants = ['exact', 'bare', 'ascii', 'ward-old', 'ward-new', 'ngo', 'kiet', 'ngach', 'english', 'typo']
    for depth in range(1, 5):
        # Include alphanumeric chains explicitly as well as a spread of city ways.
        pool = groups[depth]
        chosen = pool[::max(1, len(pool)//6)][:6]
        alpha = next((p for p in pool if re.search(r'/\d+[a-z]', p['norm'])), None)
        if alpha: chosen[-1] = alpha
        for p in chosen:
            for variant in variants:
                q = p['label']
                if variant == 'bare': q = re.sub(r'^Hẻm\s+', '', q, flags=re.I)
                elif variant == 'ascii': q = strip_accents(q)
                elif variant == 'ward-old': q += ', Phường 1, Quận 1, Hồ Chí Minh'
                elif variant == 'ward-new': q += ', phường Cầu Ông Lãnh, TP Hồ Chí Minh'
                elif variant in ('ngo', 'kiet', 'ngach', 'english'):
                    q = re.sub(r'^Hẻm', {'ngo':'ngõ','kiet':'kiệt','ngach':'ngách','english':'alley'}[variant], q)
                elif variant == 'typo':
                    # One character omission in a street token; chain is never changed.
                    words = q.split(); i = next((i for i,w in enumerate(words[2:],2) if len(w)>3),None)
                    if i is not None: words[i] = words[i][:-1]
                    q = ' '.join(words)
                cases.append({'kind':'resolver', 'pattern':variant, 'depth':depth, 'diacritics':variant!='ascii',
                              'query':q, 'expected':{k:p[k] for k in ('label','lat','lon','way_id')}})
    # Parent-alley approximation from genuine cached chains: trailing house is generated.
    for depth in (1,2,3):
        for p in groups[depth][:5]:
            q = re.sub(r'(\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*)',r'\1/18',p['label'],count=1)
            cases.append({'kind':'resolver','pattern':'house-parent','depth':depth+1,'diacritics':True,
                          'query':q,'expected':{k:p[k] for k in ('label','lat','lon','way_id')}})
    base = next(p for p in names if p['label']=='Hẻm 113/4 Võ Duy Ninh')
    addresses = [base, groups[2][3], groups[3][3]]
    for i,(vehicle,vid,catalogue) in enumerate(VEHICLES):
        for style in ('to', 'address-first', 'pickup', 'timed'):
            p=addresses[i%len(addresses)]
            msg = {'to':f'Tôi lái {vehicle} đến {p["label"]}',
                   'address-first':f'{p["label"]}, Hồ Chí Minh, Vietnam - {vehicle}',
                   'pickup':f'{vehicle} đón khách tại {p["label"]}, dừng 10 phút',
                   'timed':f'{vehicle} tới {p["label"]} lúc 7h tối nay, đỗ 2 giờ'}[style]
            cases.append({'kind':'driver','pattern':style,'depth':p['label'].count('/')+1,'diacritics':True,
                          'catalogue':catalogue,'message':msg,'expected_vehicle':vid,
                          'expected_query':p['label'], 'expected_intent':'pickup' if style=='pickup' else 'park',
                          'expected_hour':19 if style=='timed' else None})
    for p in [p for p in names if p['precision']=='street'][:8]:
        cases.append({'kind':'resolver','pattern':'street-only','depth':0,'diacritics':True,'query':p['label'],
                      'expected':{k:p[k] for k in ('label','lat','lon','way_id')}})
    for vehicle in ('xe máy','motorbike','Honda Wave'):
        cases.append({'kind':'decline','pattern':'motorbike','depth':0,'diacritics':True,'message':f'{vehicle} đến {base["label"]}'})
    for label in ('Cong ty CP Vuong Pham','Vương Phạm'):
        cases.append({'kind':'poi','pattern':'wrong-match','depth':0,'diacritics':label=='Vương Phạm','query':label})
    for vehicle,vid,_ in VEHICLES:
        cases.append({'kind':'followup','pattern':'followup','depth':2,'diacritics':True,
                      'message':f'Còn {vehicle} thì sao?','expected_vehicle':vid})
    for p in [p for p in names if p['precision']=='place'][:10]:
        cases.append({'kind':'resolver','pattern':'poi-name','depth':0,'diacritics':True,'query':p['label'],
                      'expected':{k:p[k] for k in ('label','lat','lon','way_id')}})
    for vehicle in ('VinFast VF4', 'Lamborghini Huracan', 'xe 4 chỗ'):
        cases.append({'kind':'unknown','pattern':'unknown-vehicle','depth':0,'diacritics':True,'message':f'{vehicle} đến {base["label"]}'})
    for i,(vehicle,vid,catalogue) in enumerate(VEHICLES):
        p=addresses[i%len(addresses)]
        cases.append({'kind':'journey','pattern':'plan-policy','depth':p['label'].count('/')+1,'diacritics':True,
                      'catalogue':catalogue,'message':f'{p["label"]} - {vehicle}',
                      'expected_vehicle':vid,'expected':{k:p[k] for k in ('label','lat','lon','way_id')}})
    return cases


def query_core(text):
    core=strip_accents(str(text)).split(',',1)[0]
    core=re.sub(r'^(?:hem|ngo|kiet|ngach|alley|lane)\s+', '', core)
    return re.sub(r'\bduong\s+', '', core).strip()


def run(cases, names):
    rows=[]
    previous={'lat':10.792106,'lon':106.716661,'label':'Hẻm 113/4 Võ Duy Ninh','vehicle_id':'toyota-vios',
              'arrive_at':'2026-10-17T08:00:00+07:00','dwell_min':120,'intent':'park'}
    history=[{'role':'user','parts':[{'functionResponse':{'name':'lap_ke_hoach','response':{'request':previous}}}]}]
    with tempfile.TemporaryDirectory() as d, patch.object(geo,'DB',Path(d)/'geo.sqlite'), \
         patch.object(geo,'_curated',[]), \
         patch.object(geo,'initialize_name_index',return_value=names), patch.object(geo,'goong',return_value={}), \
         patch.object(geo,'nominatim',return_value=[]), patch.object(agent,'_nominatim',return_value=[]), \
         patch.object(geo.httpx,'get',side_effect=AssertionError('Stress must never call HTTP')):
        for c in cases:
            ok,detail=False,''
            try:
                if c['kind']=='resolver':
                    p=c['expected']; r=geo.resolve_place(c['query'],(p['lat'],p['lon']))
                    good=[x for x in r['results'] if strip_accents(x['label'])==strip_accents(p['label']) and haversine(x['lat'],x['lon'],p['lat'],p['lon'])<150]
                    ok=bool(good) and not r.get('requires_clarification')
                    detail={'results':[{k:x.get(k) for k in ('label','way_id')} for x in r['results']], 'clarify':r.get('requires_clarification')}
                elif c['kind']=='poi':
                    ctx={'center':{'lat':10.761,'lon':106.69},'zoom':17,'candidates':[
                        {'name':'Trường Đại học Sư phạm TP.HCM, An Dương Vương','lat':10.76,'lon':106.68,'layer':'poi'},
                        {'name':'Cong Ty Cp Vuong Pham','lat':10.761,'lon':106.69,'layer':'poi'}]}
                    r=agent.resolve_place(c['query'],map_context=ctx)
                    ok=len(r['results'])==1 and 'Vuong Pham' in r['results'][0]['label']
                    detail=r
                elif c['kind']=='journey':
                    p=c['expected'];calls=[]
                    def execute(name,args,*rest):
                        calls.append((name,args))
                        if name=='tim_dia_diem':return agent.resolve_place(args['query'],(p['lat'],p['lon'])),None
                        if name=='lap_ke_hoach':return {'request':args,'verdict':{'headline':'Ước tính vào chật.',
                            'estimate':{'answer':'tight','confidence':'low','basis':'OSM fixture, only testing tool policy'}},'stop_points':[]},args
                        raise AssertionError(name)
                    with patch.object(agent,'execute',side_effect=execute):
                        events=list(agent.fallback_events(agent.AgentRequest(message=c['message']),[]))
                    plans=[a for n,a in calls if n=='lap_ke_hoach']
                    answer=next((e['text'] for e in events if e['type']=='answer'),'')
                    ok=len(plans)==1 and plans[0].get('vehicle_id')==c['expected_vehicle'] and query_core(plans[0].get('label'))==query_core(p['label']) and 'confidence' in answer.lower()
                    detail={'tools':[n for n,_ in calls],'plan':plans[0] if plans else None,'answer':answer}
                else:
                    req=agent.AgentRequest(message=c['message'],contents=history if c['kind']=='followup' else [])
                    args,question=agent.driver_request(req)
                    if c['kind']=='unknown':ok=args is None and bool(question)
                    elif c['kind']=='decline': ok=args is None and bool(question) and any(w in strip_accents(question) for w in ('car','motorcycle','o to','xe may','motorbike'))
                    else:
                        ok=bool(args) and args.get('vehicle_id')==c['expected_vehicle']
                        if c['kind']=='driver':
                            ok=ok and query_core(args.get('query', ''))==query_core(c['expected_query']) and args.get('intent')==c['expected_intent']
                            if c.get('expected_hour'): ok=ok and agent.datetime.fromisoformat(args['arrive_at']).hour==c['expected_hour']
                        elif args: ok=ok and args.get('lat')==previous['lat'] and args.get('dwell_min')==120
                    detail={'args':args,'question':question}
            except Exception as exc: detail={'error':type(exc).__name__+': '+str(exc)}
            rows.append({**c,'pass':bool(ok),'actual':detail})
    groups={}
    for dimension in ('kind','pattern','depth','diacritics','catalogue'):
        g=defaultdict(Counter)
        for r in rows:
            key=str(r.get(dimension,'n/a'));g[key]['total']+=1;g[key]['passed']+=int(r['pass'])
        groups[dimension]=dict(g)
    return {'total':len(rows),'passed':sum(r['pass'] for r in rows),'groups':groups,'cases':rows,'network_calls':0,'models':'deterministic'}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--corpus',type=Path);parser.add_argument('--baseline-ref');parser.add_argument('--index', type=Path);parser.add_argument('--pattern')
    a=parser.parse_args();names=source_names(a.index);cases=generate(names)
    if a.pattern:cases=[c for c in cases if c['pattern']==a.pattern]
    if a.baseline_ref:
        # Load original owned modules in memory. Never check out, edit or restart
        # another agent's workspace/server to obtain a comparable baseline.
        import app
        for name in ('geocoding','agent'):
            source=subprocess.check_output(['git','show',f'{a.baseline_ref}:backend/app/{name}.py'],cwd=ROOT,text=True)
            module=types.ModuleType('app.'+name);module.__package__='app';module.__file__=str(ROOT/'backend/app'/f'{name}.py')
            sys.modules['app.'+name]=module;setattr(app,name,module);exec(compile(source,module.__file__,'exec'),module.__dict__)
            if name=='geocoding':geo=module
            else:agent=module
    if a.corpus:a.corpus.write_text(json.dumps(cases,ensure_ascii=False,indent=2))
    report=run(cases,names);a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({k:report[k] for k in ('total','passed','groups','network_calls')},ensure_ascii=False))
