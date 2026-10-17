import subprocess,os,json
from pathlib import Path
root=Path(__file__).resolve().parent
repo=root.parents[2]
env=os.environ.copy();env['npm_config_cache']=str(root/'npm-cache')
base=['npx','-y','@modelcontextprotocol/inspector','--cli']
args=['--method','tools/call','--tool-name','plan_arrival','--tool-arg','lat=10.802092539999743','--tool-arg','lon=106.71365960299639','--tool-arg','label=Hẻm 441/14 Điện Biên Phủ','--tool-arg','vehicle_id=toyota-fortuner','--tool-arg','arrive_at=2026-10-17T14:00:00+07:00','--tool-arg','dwell_min=120','--tool-arg','intent=park']
results=[]
for mode,target in [('public',['https://concerts-message-concerns-performer.trycloudflare.com/mcp','--transport','http']),('stdio',['-e','VAODUOC_API=http://127.0.0.1:8787','python3',str(repo/'mcp/vaoduoc_mcp.py')])]:
 for method,suffix in [('list',['--method','tools/list']),('plan',args)]:
  name=f'inspector-after-{mode}-{method}'
  with (root/(name+'.log')).open('w') as f:
   try:r=subprocess.run(base+target+suffix,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=120);results.append({'test':name,'exit_code':r.returncode})
   except subprocess.TimeoutExpired:results.append({'test':name,'timeout':True})
  (root/'inspector-after-status.json').write_text(json.dumps(results,indent=2))
