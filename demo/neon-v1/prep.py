import json, math, heapq, random
random.seed(7)
R='/home/kvgkvg/Documents/mlai-car-access/'
d=json.load(open(R+'backend/cache/osm/demo_binhthanh.json'))['elements']
gaps=json.load(open(R+'data/processed/building_gaps_hcmc.json'))
LAT0,LON0=10.800,106.712
kx=111320*math.cos(math.radians(LAT0)); ky=110540
P=lambda lat,lon:((lon-LON0)*kx,-(lat-LAT0)*ky)
nodes={e['id']:P(e['lat'],e['lon']) for e in d if e['type']=='node'}
CLS={'trunk':0,'primary':0,'trunk_link':0,'primary_link':0,'secondary':1,'secondary_link':1,'tertiary':1,'tertiary_link':1,
     'residential':2,'living_street':2,'service':3,'footway':4,'steps':4,'pedestrian':4,'path':4}
ways=[];adj={}
def add(a,b,w,car,widx):
    adj.setdefault(a,[]).append((b,w,car,widx))
for w in d:
    if w['type']!='way':continue
    h=w.get('tags',{}).get('highway');
    if h not in CLS:continue
    c=CLS[h];g=gaps.get(str(w['id']))
    width=None
    if c>=2 and g: width=round(min(g['p25'],g['median'])*0.42,2)  # parcel gap -> rough clear width
    if c==3 and width is None and random.random()<.5: width=round(random.uniform(1.6,3.6),2)
    pts=[nodes[n] for n in w['nodes'] if n in nodes]
    if len(pts)<2:continue
    idx=len(ways)
    ways.append({'c':c,'w':width,'n':w.get('tags',{}).get('name',''),'p':[round(v,1) for p in pts for v in p]})
    car = c<=2 or (c==3 and width and width>=2.6)
    ow=w.get('tags',{}).get('oneway')=='yes'
    ns=[n for n in w['nodes'] if n in nodes]
    for a,b in zip(ns,ns[1:]):
        L=math.dist(nodes[a],nodes[b]); cost=L*(1 if c<=1 else 2.5 if c==2 else 4)
        add(a,b,cost,car,idx);add(b,a,cost,car,idx)
def dij(src,dst_pred,car,walk=False):
    dist={src:0};prev={};pq=[(0,src)]
    while pq:
        dd,u=heapq.heappop(pq)
        if dd>dist[u]:continue
        if dst_pred(u):
            path=[u]
            while u in prev:u=prev[u];path.append(u)
            return path[::-1],dd
        for v,w,c,_ in adj.get(u,[]):
            if car and not c:continue
            nd=dd+(math.dist(nodes[u],nodes[v]) if walk else w)
            if nd<dist.get(v,1e18):dist[v]=nd;prev[v]=u;heapq.heappush(pq,(nd,v))
    return None,None
# destination: node on a narrow alley near (300,100)
cands=[]
for wi,w in enumerate(ways):
    if w['c']==3 and w['w'] and w['w']<2.0:
        x,y=w['p'][-2],w['p'][-1]
        cands.append((math.hypot(x-250,y-150),x,y))
cands.sort()
nodeidx={v:k for k,v in nodes.items()}
best=None
for _,x,y in cands[:40]:
    dst=min((k for k in adj), key=lambda k:math.dist(nodes[k],(x,y)))
    # walk to nearest car-reachable node on secondary+ road
    major=set()
    for u in adj:
        for v,w,c,wi in adj[u]:
            if ways[wi]['c']<=1: major.add(u)
    wp,wl=dij(dst,lambda u:u in major,False,True)
    if wp and 260<wl<460: best=(dst,wp,wl);break
dst,wp,wl=best
stop=wp[-1]
# start: far major node at NW edge
far=max(major,key=lambda u:math.dist(nodes[u],nodes[stop]) if nodes[u][0]<-1200 else 0)
cp,cl=dij(far,lambda u:u==stop,True)
# naive "standard" route: shortest ignoring width (any car-ish way incl. narrow service) to dst
def naive():
    dist={far:0};prev={};pq=[(0,far)]
    while pq:
        dd,u=heapq.heappop(pq)
        if u==dst:break
        if dd>dist[u]:continue
        for v,w,c,wi in adj[u]:
            if ways[wi]['c']==4:continue
            nd=dd+math.dist(nodes[u],nodes[v])
            if nd<dist.get(v,1e18):dist[v]=nd;prev[v]=u;heapq.heappush(pq,(nd,v))
    p=[dst]
    while p[-1] in prev:p.append(prev[p[-1]])
    return p[::-1]
np_=naive()
blk=None
for i,(a,b) in enumerate(zip(np_,np_[1:])):
    for v,w,c,wi in adj[a]:
        if v==b and ways[wi]['c']>=2 and ways[wi]['w'] and ways[wi]['w']<2.28:
            if math.dist(nodes[a],nodes[dst])<700 and blk is None: blk=i


xs=lambda path:[round(v,1) for n in path for v in nodes[n]]
cams=json.load(open(R+'data/cameras/hcmc_cameras.json'))['cameras']
allcams=[[round(v) for v in P(c['lat'],c['lon'])] for c in cams]
fp=json.load(open(R+'data/flood/ird-hcmc/flood_points.geojson'))['features']
floods=[[round(v) for v in P(f['geometry']['coordinates'][1],f['geometry']['coordinates'][0])]+[f['properties'].get('Water_height_max_cm') or 20] for f in fp if f['geometry']]
tide=json.load(open(R+'data/flood/tide_forecast.json'))
out=dict(blk=blk,ways=ways,car=xs(cp),walk=xs(wp),naive=xs(np_),walkLen=round(wl),carLen=round(cl),cams=allcams,floods=floods,
  tide=[h['level_m'] for h in tide['highs']],dst=nodes[dst],stop=nodes[stop],start=nodes[far])
open('data.js','w').write('window.D='+json.dumps(out,ensure_ascii=False,separators=(',',':'))+';')
print(len(ways),'walk',wl,'car pts',len(cp),'naive',len(np_),'dst',nodes[dst],'stop',nodes[stop],'start',nodes[far])
print('widths',sum(1 for w in ways if w['w']), 'cams',len(allcams),'floods',len(floods))
