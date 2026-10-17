import sys,json
from pathlib import Path
sys.path.insert(0,'.')
from pipelines import audit_algorithm as a
from app import osm
points=json.loads(Path('docs/eval/engine-final/frozen-inputs.json').read_text())['points']
a.OUT=Path('docs/eval/estimate-sweep');a.OUT.mkdir(exist_ok=True)
a.pick_destinations=lambda n,seed:points[:n]
original=a.engine.area
frozen={}
def area(lat,lon):
 key=osm.area_key(lat,lon)
 if key not in frozen:frozen[key]=original(lat,lon)
 return frozen[key]
a.engine.area=area
results=a.sweep(300,3317)
data=json.loads((a.OUT/'audit-sweep.json').read_text())
summary={k:v for k,v in data.items() if k not in ('results','examples')}
summary['examples']=data['examples']
(a.OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2))
print('FINAL',json.dumps(data['counts']),flush=True)
