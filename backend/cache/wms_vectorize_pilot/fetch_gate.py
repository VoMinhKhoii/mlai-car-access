"""Metadata/terms requests only; no maps, feature queries, credentials or retries."""
import hashlib,json,time
from pathlib import Path
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
import httpx
ROOT=Path(__file__).resolve().parent
UA='NgoNgach-WMSResearch/1.0 (HCMC alley parcel-gap pilot; terms audit only; contact pkhoa1331@gmail.com)'
client=httpx.Client(headers={'User-Agent':UA},timeout=30,follow_redirects=False,trust_env=False)
last=0
robots={}
def request(url,label):
 global last
 meta_file=ROOT/(label+'.meta.json');body_file=ROOT/(label+'.body')
 if meta_file.exists():return json.loads(meta_file.read_text()),body_file.read_bytes()
 latest=max((p.stat().st_mtime for p in ROOT.glob('*.meta.json')),default=0)
 time.sleep(max(0,2-(time.monotonic()-last),2-(time.time()-latest)));last=time.monotonic()
 meta={'url':url,'retrieved_at':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),'user_agent':UA}
 try:
  r=client.get(url);body=r.content
  meta.update(status=r.status_code,headers=dict(r.headers),bytes=len(body),sha256=hashlib.sha256(body).hexdigest())
 except httpx.HTTPError as e:body=b'';meta.update(status='transport_error',error=str(e))
 body_file.write_bytes(body);meta_file.write_text(json.dumps(meta,indent=2))
 print(label,meta['status'],meta.get('bytes'),flush=True)
 return meta,body

def get(url,label):
 p=urlparse(url)
 if p.scheme!='https' or p.hostname not in {'geoportal-stnmt.tphcm.gov.vn','geodata-stnmt.tphcm.gov.vn','opendata.hochiminhcity.gov.vn'}:raise ValueError('Unreviewed host')
 origin=p.scheme+'://'+p.netloc
 if origin not in robots:
  m,b=request(origin+'/robots.txt',p.hostname+'_robots')
  rp=RobotFileParser()
  if m['status'] in (404,410):rp.parse([])
  elif m['status']==200 and 'html' not in m.get('headers',{}).get('content-type',''):rp.parse(b.decode(errors='replace').splitlines())
  else:raise RuntimeError('Robots unavailable/refused: '+str(m))
  robots[origin]=rp
 rp=robots[origin]
 if not rp.can_fetch(UA,url):raise RuntimeError('Robots disallows '+url)
 delay=rp.crawl_delay(UA) or rp.crawl_delay('*') or 0
 if delay:time.sleep(delay)
 m,b=request(url,label)
 if m['status'] in (401,403,429):raise RuntimeError('Stop after refusal '+str(m['status']))
 return m,b
if __name__=='__main__':
 import sys
 get(sys.argv[1],sys.argv[2])
