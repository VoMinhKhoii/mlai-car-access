from pathlib import Path
import json,collections
root=Path(__file__).parent;rows=[json.loads(l) for l in (root/'before.jsonl').read_text().splitlines()]
counts=collections.Counter();fitgroups=collections.defaultdict(dict);textset=set();bad=[];rank={'no':0,'tight':1,'fits':2}
for r in rows:
 p=r.get('args',{}).get('request',{}).get('params',{});a=p.get('arguments',{});n=p.get('name');body=r.get('body',{});s=body.get('result',{}) if isinstance(body,dict) else {}
 if n in ['plan_arrival','find_nearby_stops','check_alley_fit'] and 'vehicle_id' in a:
  counts[n]+=1;sc=s.get('structuredContent',{});e=sc.get('estimate',sc.get('verdict',{}).get('estimate',{}))
  if not e.get('answer') or not e.get('confidence'):bad.append({'name':n,'args':a,'estimate':e})
  if n=='check_alley_fit':fitgroups[a['way_id']][a['vehicle_id']]=e['answer']
 for c in s.get('content',[]):textset.add(c.get('text',''))
fitinv=[]
for way,vs in fitgroups.items():
 order=['vinfast-vf-3','toyota-vios','toyota-fortuner','class-xl']
 for a,b in zip(order,order[1:]):
  if a in vs and b in vs and rank.get(vs[a],-1)<rank.get(vs[b],-1):fitinv.append({'way':way,'smaller':a,'bigger':b,'answers':vs})
(root/'tool-quality.json').write_text(json.dumps({'counts':dict(counts),'missing_estimate_confidence':bad,'alley_fit_answers':dict(fitgroups),'alley_fit_inversions':fitinv,'english_text_summaries':sorted(textset)},ensure_ascii=False,indent=2))
print(dict(counts),'missing',bad,'direct-fit inversions',fitinv)
