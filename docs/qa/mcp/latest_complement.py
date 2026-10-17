from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
while 'DONE' not in (ROOT/'after-matrix-progress.log').read_text():
 if datetime.datetime.now().strftime('%H:%M:%S')>'13:19:30':sys.exit()
 time.sleep(5)
record('baseline',{}, {'pids':subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN')})
rows=[json.loads(l) for l in (ROOT/'after.jsonl').read_text().splitlines()];seen=set()
for r in rows:
 p=r.get('args',{}).get('request',{}).get('params',{});a=p.get('arguments',{})
 if p.get('name')!='plan_arrival' or not a.get('label'):continue
 key=(a['label'],a['vehicle_id'],a['intent'])
 if key in seen:continue
 seen.add(key)
 if subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN').strip()!='42127':print('PID CHANGED',flush=True);sys.exit()
 if datetime.datetime.now().strftime('%H:%M:%S')>'13:19:45':print('DEADLINE',flush=True);sys.exit()
 result=call('plan_arrival',a);record('api/plan',a,req(LOCAL,'/api/plan',a));call('find_nearby_stops',a)
 old=[json.loads(l) for l in (ROOT/'before.jsonl').read_text().splitlines()]
 for x in old:
  pp=x.get('args',{}).get('request',{}).get('params',{})
  if pp.get('name')=='plan_arrival' and pp.get('arguments')==a:
   way=x.get('body',{}).get('result',{}).get('structuredContent',{}).get('door',{}).get('way_id')
   if way:call('check_alley_fit',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':way})
   break
print('DONE',flush=True)
