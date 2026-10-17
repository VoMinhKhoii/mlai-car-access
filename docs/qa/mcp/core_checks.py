from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
record('baseline',{}, {'pids':subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN'),'config':req(LOCAL,'/api/config')})
for base in [LOCAL,PUBLIC]:
 for v in ['2025-06-18','2025-11-25']:rpc('initialize',{'protocolVersion':v,'capabilities':{},'clientInfo':{'name':'qa-core','version':'1'}},base)
 rpc('tools/list',base=base);rpc('ping',base=base)
 for m,p in [('bad/method',None),('tools/call',{'name':'missing','arguments':{}}),('tools/call',{'name':'plan_arrival','arguments':{}})]:rpc(m,p,base)
 record('GET /mcp',{'base':base},req(base,method='GET'));rpc('ping',base=base,headers={'Origin':'https://evil.example'})
for name,a in [('find_place',{'query':'HUTECH'}),('list_vehicles',{}),('tide_levels',{'start':'2026-10-17T00:00:00+07:00','hours':24})]:call(name,a)
p=json.loads((ROOT/'before-places.json').read_text())['Hẻm 441/14 Điện Biên Phủ']['results'][0]
a={k:p[k] for k in ['lat','lon','label']}|dict(vehicle_id='toyota-fortuner',intent='park',arrive_at='2026-10-17T14:00:00+07:00',dwell_min=120)
for name,args in [('plan_arrival',a),('find_nearby_stops',a),('check_alley_fit',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':610082013}),('lap_ke_hoach',a),('tim_cho_do_gan',a),('kiem_tra_xe_vao_hem',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':610082013})]:call(name,args)
call('plan_arrival',a,PUBLIC)
record('api/plan',a,req(LOCAL,'/api/plan',a))
# Post-restart regression: every requested alley, all three arrival tools for Fortuner;
# and the exact smaller/larger candidate-selection failure at 429.
if phase=='after':
 places=json.loads((ROOT/'before-places.json').read_text())
 for query,pd in places.items():
  if not any(x in query for x in ['441/14','429','479','220/9','246','356']):continue
  p=pd['results'][0]
  for vehicle in (['toyota-fortuner','class-xl'] if '429' in query else ['toyota-fortuner']):
   for intent in (['park','pickup'] if '429' in query else ['park']):
    args={k:p[k] for k in ['lat','lon','label']}|dict(vehicle_id=vehicle,intent=intent,arrive_at='2026-10-17T14:00:00+07:00',dwell_min=120)
    result=call('plan_arrival',args)
    record('api/plan',args,req(LOCAL,'/api/plan',args));call('find_nearby_stops',args)
    way=result.get('body',{}).get('result',{}).get('structuredContent',{}).get('door',{}).get('way_id')
    if way:call('check_alley_fit',{k:args[k] for k in ['lat','lon','vehicle_id']}|{'way_id':way})
