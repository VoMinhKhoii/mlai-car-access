from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
# Continue the same post-restart matrix without repeating already-tested combinations.
while True:
 rp=ROOT/'after-rate.jsonl'
 if rp.exists() and any(json.loads(l).get('name')=='ping' for l in rp.read_text().splitlines()):break
 time.sleep(5)
rows=[json.loads(l) for l in (ROOT/'after.jsonl').read_text().splitlines()]
seen=set()
for r in rows:
 p=r.get('args',{}).get('request',{}).get('params',{});a=p.get('arguments',{})
 if p.get('name')=='plan_arrival' and a.get('label'):seen.add((a['label'],a['vehicle_id'],a['intent']))
places=json.loads((ROOT/'before-places.json').read_text())
for query,pd in places.items():
 if not any(x in query for x in ['441/14','429','479','220/9','246','356']):continue
 p=pd['results'][0]
 for vehicle in ['vinfast-vf-3','toyota-vios','toyota-fortuner','class-xl']:
  for intent in ['park','pickup']:
   if (p['label'],vehicle,intent) in seen:continue
   if datetime.datetime.now().strftime('%H:%M:%S')>'13:19:45':print('DEADLINE',flush=True);sys.exit()
   a={k:p[k] for k in ['lat','lon','label']}|dict(vehicle_id=vehicle,intent=intent,arrive_at='2026-10-17T14:00:00+07:00',dwell_min=120)
   r=call('plan_arrival',a);record('api/plan',a,req(LOCAL,'/api/plan',a));call('find_nearby_stops',a)
   # Use the already-resolved pre-restart door way when the compact plan is an error.
   old=[json.loads(l) for l in (ROOT/'before.jsonl').read_text().splitlines()]
   way=None
   for x in old:
    pp=x.get('args',{}).get('request',{}).get('params',{})
    if pp.get('name')=='plan_arrival' and pp.get('arguments')==a:
     way=x.get('body',{}).get('result',{}).get('structuredContent',{}).get('door',{}).get('way_id');break
   if way:call('check_alley_fit',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':way})
print('DONE',flush=True)
