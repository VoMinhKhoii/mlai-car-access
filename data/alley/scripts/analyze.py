import json, math, sys, re, collections
fn, s,w,n,e = sys.argv[1], *map(float, sys.argv[2:6])
d = json.load(open(fn))
nodes = {el['id']:(el['lat'],el['lon']) for el in d['elements'] if el['type']=='node'}
ways = [el for el in d['elements'] if el['type']=='way']
def inside(nid):
    lat,lon = nodes[nid]; return s<=lat<=n and w<=lon<=e
def hav(a,b):
    (la1,lo1),(la2,lo2)=nodes[a],nodes[b]
    R=6371000; p1,p2=math.radians(la1),math.radians(la2)
    dp=p2-p1; dl=math.radians(lo2-lo1)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*R*math.asin(math.sqrt(x))
inner=[wy for wy in ways if any(inside(x) for x in wy['nodes'])]
print(f"ways total(outer)={len(ways)} inner={len(inner)}")
# length inside (segments with >=1 endpoint inside)
def inlen(wy):
    L=0
    for a,b in zip(wy['nodes'],wy['nodes'][1:]):
        if inside(a) or inside(b): L+=hav(a,b)
    return L
cnt=collections.Counter(); ln=collections.Counter()
for wy in inner:
    h=wy['tags'].get('highway'); cnt[h]+=1; ln[h]+=inlen(wy)
print("\n== highway type: ways / km (inner bbox) ==")
for h,c in cnt.most_common(): print(f"{h:16s} {c:5d} {ln[h]/1000:7.2f} km")
print(f"TOTAL {sum(cnt.values())} ways, {sum(ln.values())/1000:.1f} km")
keys=['name','width','est_width','maxwidth','maxwidth:physical','motorcar','motor_vehicle','motorcycle','vehicle','access','oneway','noexit','surface','lanes','service','maxweight','smoothness','lit','sidewalk','layer','tunnel','covered']
focus={'residential','service','living_street','unclassified','footway','path','track','pedestrian','steps','tertiary','secondary','primary'}
print("\n== tag presence among inner ways (all highway types) ==")
for k in keys:
    c=sum(1 for wy in inner if k in wy['tags'])
    vals=collections.Counter(wy['tags'][k] for wy in inner if k in wy['tags'])
    top=', '.join(f'{v}:{c2}' for v,c2 in vals.most_common(6)) if k!='name' else ''
    print(f"{k:18s} {c:5d} ({100*c/len(inner):5.1f}%)  {top}")
print("\n== tag presence by type for alley-candidate types (residential/service/living_street/footway/path/unclassified) ==")
for h in ['residential','service','living_street','unclassified','footway','path','pedestrian','track']:
    ws=[wy for wy in inner if wy['tags'].get('highway')==h]
    if not ws: continue
    row=[f"{k}={sum(1 for wy in ws if k in wy['tags'])}" for k in ['name','width','est_width','maxwidth','motorcar','motor_vehicle','access','oneway','noexit','surface','lanes']]
    print(h, len(ws), ' '.join(row))
# names
print("\n== name patterns ==")
pat=collections.Counter(); samples=collections.defaultdict(list)
for wy in inner:
    nm=wy['tags'].get('name')
    if not nm: pat['<no name>']+=1; continue
    first=nm.split()[0]
    key = first if first.lower() in ('hẻm','ngõ','ngách','kiệt','hẽm','hem','ngo','đường','phố','hẻm') else ('contains /' if '/' in nm else 'other')
    if '/' in nm and key not in ('contains /',): key=key+' (+/)'
    pat[key]+=1
    if len(samples[key])<8: samples[key].append(nm+' ['+wy['tags'].get('highway')+']')
for k,v in pat.most_common(): print(f"{k:20s} {v}  e.g. {samples.get(k,[])[:6]}")
# degree / dead ends
car={'motorway','trunk','primary','secondary','tertiary','unclassified','residential','living_street','service','road','track','motorway_link','trunk_link','primary_link','secondary_link','tertiary_link'}
def deadends(types):
    adj=collections.defaultdict(set); nway=collections.defaultdict(set)
    for wy in ways:
        if types and wy['tags'].get('highway') not in types: continue
        ns=wy['nodes']
        for a,b in zip(ns,ns[1:]):
            adj[a].add(b); adj[b].add(a)
        for x in ns: nway[x].add(wy['id'])
    de=[x for x in adj if len(adj[x])==1 and inside(x)]
    return adj,de
wmap={wy['id']:wy for wy in ways}
for label,types in [('car-candidate network',car),('all highway',None)]:
    adj,de=deadends(types)
    print(f"\n== dead-end (degree-1) nodes inside inner bbox, {label}: {len(de)}")
    # branch length from dead end to first junction (deg>=3)
    lens=[]
    for x in de:
        prev=None; cur=x; L=0; steps=0
        while True:
            nb=[y for y in adj[cur] if y!=prev]
            if len(adj[cur])>=3 or not nb or steps>5000: break
            nxt=nb[0]; L+=hav(cur,nxt); prev,cur=cur,nxt; steps+=1
        lens.append(L)
    if lens:
        lens.sort(); q=lambda p: lens[min(len(lens)-1,int(p*len(lens)))]
        print(f"   dead-end branch length m: median={q(.5):.0f} p25={q(.25):.0f} p75={q(.75):.0f} p90={q(.9):.0f} max={lens[-1]:.0f}; >50m: {sum(1 for l in lens if l>50)}, >100m: {sum(1 for l in lens if l>100)}")
