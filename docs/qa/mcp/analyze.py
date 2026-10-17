import json,collections
from pathlib import Path
root=Path(__file__).parent
summary={}
for file in root.glob('*.jsonl'):
 if file.name.startswith(('codex','restart')):continue
 try:rows=[json.loads(l) for l in file.read_text().splitlines()]
 except:continue
 tools=[r for r in rows if r.get('name')=='tools/call']
 plans=[r for r in tools if r['args']['request']['params']['name']=='plan_arrival']
 errors=[{'name':r['args']['request']['params']['name'],'args':r['args']['request']['params']['arguments'],'status':r.get('status'),'body':r.get('body'),'exception':r.get('exception')} for r in tools if r.get('status')!=200 or r.get('body',{}).get('error') or r.get('body',{}).get('result',{}).get('isError')]
 pairs=[];missing=[];monos=collections.defaultdict(dict)
 for r in plans:
  a=r['args']['request']['params']['arguments']
  if 'label' not in a:continue
  sc=r.get('body',{}).get('result',{}).get('structuredContent',{});v=sc.get('verdict',{});est=v.get('estimate',{})
  apis=[x for x in rows if x.get('name')=='api/plan' and x.get('args')==a]
  if apis:
   av=apis[0].get('body',{}).get('verdict',{});pairs.append({'args':a,'headline_equal':v.get('headline')==av.get('headline'),'estimate_answer_equal':est.get('answer')==av.get('estimate',{}).get('answer'),'mcp_headline':v.get('headline'),'api_headline':av.get('headline')})
  citations=[]
  def walk(d):
   if isinstance(d,dict):
    for k,value in d.items():
     if k=='citation':citations.append(value)
     walk(value)
   elif isinstance(d,list):
    for x in d:walk(x)
  walk(sc)
  if not est.get('answer') or not est.get('confidence') or not citations:missing.append({'args':a,'estimate':est,'citation_count':len(citations)})
  monos[(a['label'],a['intent'])][a['vehicle_id']]={'answer':est.get('answer'),'code':v.get('code'),'headline':v.get('headline'),'door_answer':sc.get('door',{}).get('estimate',{}).get('answer')}
 rank={'no':0,'unlikely':0,'tight':1,'fits':2,'yes':2}
 inversions=[]
 for (label,intent),vals in monos.items():
  vs=['vinfast-vf-3','toyota-vios','toyota-fortuner','class-xl']
  for a,b in zip(vs,vs[1:]):
   if a in vals and b in vals:
    for key in ['answer','door_answer']:
     if vals[a][key] in rank and vals[b][key] in rank and rank[vals[a][key]]<rank[vals[b][key]]:inversions.append({'label':label,'intent':intent,'field':key,'smaller':{a:vals[a]},'bigger':{b:vals[b]}})
 burst=[r for r in rows if r.get('name')=='rate-limit-burst']
 summary[file.name]={'records':len(rows),'tool_calls':len(tools),'plans':len(plans),'errors':errors,'max_tool_bytes':max([r.get('bytes',0) for r in tools] or [0]),'missing_estimate_confidence_citations':missing,'api_pairs':pairs,'monotonicity':[{ 'label':k[0],'intent':k[1],'vehicles':v} for k,v in monos.items()],'inversions':inversions,'rate_limit':dict(collections.Counter(str(r.get('status')) for r in burst[0]['responses'])) if burst else None}
(root/'analysis.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
for name,s in summary.items():print(name,{k:v for k,v in s.items() if k not in ['api_pairs','monotonicity']},'pair_mismatches',sum(not (p['headline_equal'] and p['estimate_answer_equal']) for p in s['api_pairs']))
