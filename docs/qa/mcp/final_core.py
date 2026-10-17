from pathlib import Path
exec((Path(__file__).parent/'run_checks.py').read_text().split("record('baseline'")[0])
record('baseline',{}, {'pids':subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN'),'config':req(LOCAL,'/api/config')})
rpc('tools/list',base=PUBLIC)
for label,lat,lon in [('Hẻm 441/53 Điện Biên Phủ',10.8027513,106.7128822),('Hẻm 429 Điện Biên Phủ',10.802498,106.713094)]:
 for vehicle in ['vinfast-vf-3','toyota-fortuner']:
  a=dict(label=label,lat=lat,lon=lon,vehicle_id=vehicle,intent='park',arrive_at='2026-10-17T14:00:00+07:00',dwell_min=120)
  r=call('plan_arrival',a,PUBLIC);record('api/plan',a,req(PUBLIC,'/api/plan',a))
  s=r.get('body',{}).get('result',{}).get('structuredContent',{});way=s.get('door',{}).get('way_id')
  if way:call('check_alley_fit',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':way},PUBLIC)
  else:record('check_alley_fit skipped',a,{'reason':'No resolved door way_id in plan','plan':s})
  call('find_nearby_stops',a,PUBLIC)
print('DONE',flush=True)
