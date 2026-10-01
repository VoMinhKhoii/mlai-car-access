import json, math, sys, re, collections
fn, s,w,n,e = sys.argv[1], *map(float, sys.argv[2:6])
d = json.load(open(fn))
nodes = {el['id']:(el['lat'],el['lon']) for el in d['elements'] if el['type']=='node'}
ways = [el for el in d['elements'] if el['type']=='way']
inside=lambda x: s<=nodes[x][0]<=n and w<=nodes[x][1]<=e
def hav(a,b):
    (la1,lo1),(la2,lo2)=nodes[a],nodes[b]; R=6371000
    p1,p2=math.radians(la1),math.radians(la2); dp=p2-p1; dl=math.radians(lo2-lo1)
    return 2*R*math.asin(math.sqrt(math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2))
def inlen(wy): return sum(hav(a,b) for a,b in zip(wy['nodes'],wy['nodes'][1:]) if inside(a) or inside(b))
inner=[wy for wy in ways if any(inside(x) for x in wy['nodes'])]
rx=re.compile(r'^(Hẻm|Ngõ|Ngách|Kiệt)\b', re.I)
minor={'service','residential','living_street','footway','path','pedestrian','steps','track','unclassified'}
alley=[wy for wy in inner if wy['tags'].get('highway') in minor and (wy['tags'].get('service')=='alley' or rx.match(wy['tags'].get('name','')))]
L=sum(inlen(x) for x in alley)
print(f"alley-like ways: {len(alley)}  length {L/1000:.1f} km")
def has(wy):
    t=wy['tags']
    return {'motorcar':'motorcar' in t,'motor_vehicle':'motor_vehicle' in t,'width/maxwidth':('width' in t or 'maxwidth' in t or 'est_width' in t),'access':'access' in t}
for k in ['motorcar','motor_vehicle','width/maxwidth','access']:
    sub=[x for x in alley if has(x)[k]]
    print(f"  with {k:15s}: {len(sub):4d} ways ({100*len(sub)/len(alley):4.1f}%), {sum(inlen(x) for x in sub)/1000:5.1f} km ({100*sum(inlen(x) for x in sub)/L:4.1f}% of length)")
anysig=[x for x in alley if any(has(x).values())]
print(f"  ANY car signal: {len(anysig)} ways ({100*len(anysig)/len(alley):.1f}%), {100*sum(inlen(x) for x in anysig)/L:.1f}% of length")
# value distribution by length
vals=collections.Counter()
for x in alley:
    t=x['tags']; v=t.get('motorcar') or ('mv:'+t['motor_vehicle'] if 'motor_vehicle' in t else None) or '(none)'
    vals[v]+=inlen(x)
print("  car-access value by km:", {k:round(v/1000,1) for k,v in vals.most_common()})
# footway subtype
fw=collections.Counter(x['tags'].get('footway','(none)') for x in inner if x['tags'].get('highway')=='footway')
print("  footway subtags:",fw.most_common(5))
unnamed_service=[x for x in inner if x['tags'].get('highway')=='service' and 'name' not in x['tags']]
print("  unnamed service ways:",len(unnamed_service), collections.Counter(x['tags'].get('service','(none)') for x in unnamed_service).most_common(5))
