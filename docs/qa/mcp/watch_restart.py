import subprocess,time,datetime,json,urllib.request
from pathlib import Path
root=Path(__file__).parent
baseline='15333'; observed=False
while datetime.datetime.now().strftime('%H:%M:%S') < '13:20:00':
 pid=subprocess.getoutput('lsof -tiTCP:8787 -sTCP:LISTEN').strip()
 try:
  d=json.load(urllib.request.urlopen('http://localhost:8787/api/config',timeout=5));state={k:v for k,v in d.items() if 'start' in k or 'uptime' in k}
 except Exception as e:state={'error':str(e)}
 with (root/'restart-watch.jsonl').open('a') as f:f.write(json.dumps({'time':datetime.datetime.now().isoformat(),'pid':pid,'start_fields':state})+'\n')
 if pid and pid!=baseline and not observed:
  observed=True
  with (root/'after-progress.log').open('w') as f:subprocess.run(['python3',str(root/'core_checks.py'),'after'],stdout=f,stderr=subprocess.STDOUT)
 time.sleep(20)
with (root/'restart-watch.jsonl').open('a') as f:f.write(json.dumps({'finished':datetime.datetime.now().isoformat(),'restart_observed':observed})+'\n')
