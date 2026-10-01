import json, math, sys, collections
fn, s,w,n,e = sys.argv[1], *map(float, sys.argv[2:6])
d=json.load(open(fn)); nodes={x['id']:(x['lat'],x['lon']) for x in d['elements'] if x['type']=='node'}
inside=lambda x: s<=nodes[x][0]<=n and w<=nodes[x][1]<=e
def hav(a,b):
    (la1,lo1),(la2,lo2)=nodes[a],nodes[b]; R=6371000; p1,p2=math.radians(la1),math.radians(la2)
    return 2*R*math.asin(math.sqrt(math.sin((p2-p1)/2)**2+math.cos(p1)*math.cos(p2)*math.sin(math.radians(lo2-lo1)/2)**2))
car={'motorway','trunk','primary','secondary','tertiary','unclassified','residential','living_street','service','road','track','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}
adj=collections.defaultdict(set); wayof={}
for x in d['elements']:
    if x['type']!='way' or x['tags'].get('highway') not in car: continue
    t=x['tags']
    if t.get('motorcar')=='no' or t.get('motor_vehicle')=='no' or t.get('access') in ('no','private'): continue  # car-legal network only
    ns=x['nodes']
    for a,b in zip(ns,ns[1:]): adj[a].add(b); adj[b].add(a); wayof[(a,b)]=wayof[(b,a)]=x
de=[x for x in adj if len(adj[x])==1 and inside(x)]
lens=[]; cls=collections.Counter()
for x in de:
    prev=None; cur=x; L=0; steps=0; first=None
    while True:
        nb=[y for y in adj[cur] if y!=prev]
        if len(adj[cur])>=3 or not nb or steps>5000: break
        nxt=nb[0]; 
        if first is None: first=wayof[(cur,nxt)]
        L+=hav(cur,nxt); prev,cur=cur,nxt; steps+=1
    lens.append(L)
    t=first['tags']; k=(t.get('highway'), t.get('motorcar','-'))
    if L>50: cls[k]+=1
print(f"car-legal network (excl. motorcar/motor_vehicle=no, access=no/private): dead-ends in bbox={len(de)}; branch >50 m: {sum(1 for l in lens if l>50)}; >100 m: {sum(1 for l in lens if l>100)}")
print("  >50 m dead-end branches by (highway, motorcar):", cls.most_common(6))
