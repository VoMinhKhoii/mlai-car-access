import ssl,certifi
ssl._create_default_https_context=lambda:ssl.create_default_context(cafile=certifi.where())
import json,time,urllib.request,urllib.error,subprocess,datetime,sys,concurrent.futures
from pathlib import Path
ROOT=Path(__file__).resolve().parent
LOCAL='http://127.0.0.1:8787'; PUBLIC='https://concerts-message-concerns-performer.trycloudflare.com'
phase=sys.argv[1] if len(sys.argv)>1 else 'before'
log=ROOT/(phase+'.jsonl')
def req(base,path='/mcp',body=None,headers=None,method=None):
 h={'Content-Type':'application/json','Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'};h.update(headers or {})
 t=time.time()
 try:
  with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(body,ensure_ascii=False).encode() if body is not None else None,headers=h,method=method),timeout=65) as r: status=r.status; raw=r.read(); hs=dict(r.headers)
 except urllib.error.HTTPError as e: status=e.code;raw=e.read();hs=dict(e.headers)
 except Exception as e:return {'exception':str(e),'seconds':time.time()-t}
 try: data=json.loads(raw)
 except: data=raw.decode(errors='replace')
 return {'status':status,'bytes':len(raw),'seconds':round(time.time()-t,3),'headers':hs,'body':data}
def record(name,args,r):
 with log.open('a') as f:f.write(json.dumps({'time':datetime.datetime.now().isoformat(),'name':name,'args':args,**r},ensure_ascii=False)+'\n')
 print(name, r.get('status'), r.get('bytes'),flush=True)
def rpc(method,params=None,base=LOCAL,pace=True,headers=None):
 if pace:time.sleep(1.15)
 b={'jsonrpc':'2.0','id':1,'method':method}
 if params is not None:b['params']=params
 r=req(base,body=b,headers=headers);record(method,{'base':base,'request':b,'headers':headers},r);return r
def call(name,args,base=LOCAL):return rpc('tools/call',{'name':name,'arguments':args},base)
record('baseline',{}, {'pids':subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN'),'config':req(LOCAL,'/api/config')})
for base in [LOCAL,PUBLIC]:
 for v in ['2025-06-18','2025-11-25']:rpc('initialize',{'protocolVersion':v,'capabilities':{},'clientInfo':{'name':'qa-real-client','version':'1'}},base)
 for m,p in [('tools/list',None),('ping',None),('bad/method',None),('tools/call',{'name':'missing','arguments':{}}),('tools/call',{'name':'plan_arrival','arguments':{}})]:rpc(m,p,base)
 record('GET /mcp',{'base':base},req(base,method='GET'))
 rpc('ping',base=base,headers={'Origin':'https://evil.example'})
places={}
queries=['Hẻm 441/14 Điện Biên Phủ','Hẻm 429 Điện Biên Phủ','137/41/18 Trần Đình Xu','HUTECH','Hẻm 479 Điện Biên Phủ','Hẻm 220/9 Xô Viết Nghệ Tĩnh','Hẻm 246 Xô Viết Nghệ Tĩnh','Hẻm 356 Xô Viết Nghệ Tĩnh']
for q in queries:
 r=call('find_place',{'query':q});d=r.get('body',{}).get('result',{}).get('structuredContent',{});places[q]=d
(ROOT/(phase+'-places.json')).write_text(json.dumps(places,ensure_ascii=False,indent=2))
call('list_vehicles',{});call('tide_levels',{'start':'2026-10-17T00:00:00+07:00','hours':24})
for q in [queries[i] for i in [0,1,4,5,6,7]]:
 d=places[q]
 if not d.get('results') or d.get('requires_clarification'):continue
 p=d['results'][0]
 for vehicle in ['vinfast-vf-3','toyota-vios','toyota-fortuner','class-xl']:
  for intent in ['park','pickup']:
   a={k:p[k] for k in ['lat','lon','label']};a.update(vehicle_id=vehicle,intent=intent,arrive_at='2026-10-17T14:00:00+07:00',dwell_min=120)
   r=call('plan_arrival',a)
   api=req(LOCAL,'/api/plan',a);record('api/plan',a,api)
   call('find_nearby_stops',a)
   sc=r.get('body',{}).get('result',{}).get('structuredContent',{})
   (ROOT/'latest-plan.json').write_text(json.dumps(sc,ensure_ascii=False,indent=2))
   way=sc.get('door',{}).get('way_id') or sc.get('destination',{}).get('way_id')
   if way:call('check_alley_fit',{k:a[k] for k in ['lat','lon','vehicle_id']}|{'way_id':way})
# aliases use canonical inputs, including a real resolved plan
aliases=[('tim_dia_diem',{'query':queries[0]}),('danh_sach_xe',{}),('muc_trieu',{'start':'2026-10-17T00:00:00+07:00','hours':24})]
for n,a in aliases:call(n,a)
# Deliberate local-only burst, after ordinary checks; no forged IPs.
time.sleep(61)
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
 out=list(ex.map(lambda i:req(LOCAL,body={'jsonrpc':'2.0','id':i,'method':'ping'}),range(65)))
record('rate-limit-burst',{}, {'responses':out})
time.sleep(61);rpc('ping')
print('DONE',flush=True)
