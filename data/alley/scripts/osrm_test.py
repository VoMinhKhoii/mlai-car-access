import json, random, subprocess, time, statistics, sys, math
random.seed(1)
def load(fn):
    d=json.load(open(fn)); nodes={e['id']:(e['lat'],e['lon']) for e in d['elements'] if e['type']=='node'}
    return d,nodes
out={}
for city,fn,(s,w,n,e) in [('HCMC','hcm_highways.json',(10.786,106.67585,10.804,106.69415)),('Hanoi','hn_highways.json',(20.996,105.8124,21.014,105.8316))]:
    d,nodes=load(fn)
    groups={'motorcar=no':[], 'motorcar=destination':[]}
    for x in d['elements']:
        if x['type']!='way' or x['tags'].get('highway')!='service': continue
        mc=x['tags'].get('motorcar')
        key='motorcar='+mc if mc in ('no','destination') else None
        if not key: continue
        ns=x['nodes']
        if len(ns)<3: continue
        mid=nodes[ns[len(ns)//2]]
        if s<=mid[0]<=n and w<=mid[1]<=e: groups[key].append((x['id'],mid))
    for key,items in groups.items():
        sample=random.sample(items, min(12,len(items)))
        dists=[]; onway=0
        for wid,(la,lo) in sample:
            r=subprocess.run(['curl','-s','-m','30','-A','hackathon-research/0.1',f'https://router.project-osrm.org/nearest/v1/driving/{lo},{la}?number=1'],capture_output=True,text=True).stdout
            try:
                j=json.loads(r); wp=j['waypoints'][0]; dists.append(wp['distance']); 
                if wp['distance']<1.0: onway+=1
            except Exception as ex: print('err',r[:100])
            time.sleep(1.1)
        dists.sort()
        print(f"{city} {key}: n={len(dists)} snapped-on-alley(<1m)={onway} median snap dist={statistics.median(dists):.1f} m  max={max(dists):.1f} m  all={[round(x,1) for x in dists]}", flush=True)
