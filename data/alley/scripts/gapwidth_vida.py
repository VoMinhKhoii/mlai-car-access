import json, math, sys, collections, statistics
import duckdb, pyproj
from shapely import wkb, STRtree
from shapely.geometry import LineString, Point
from shapely.ops import transform
tag, hwfile, s,w,n,e = sys.argv[1], sys.argv[2], *map(float, sys.argv[3:7])
utm = pyproj.Transformer.from_crs(4326, 32648, always_xy=True).transform
con=duckdb.connect(); con.execute("LOAD spatial;")
rows=con.execute(f"select ST_AsWKB(geometry), bf_source from 'vida_{tag}.parquet'").fetchall()
geoms=[]; src=[]
for g,ds in rows:
    geoms.append(transform(utm, wkb.loads(bytes(g)))); src.append(ds)
tree=STRtree(geoms)
d=json.load(open(hwfile))
nodes={x['id']:(x['lon'],x['lat']) for x in d['elements'] if x['type']=='node'}
import re
rx=re.compile(r'^(Hẻm|Ngõ|Ngách|Kiệt)\b')
minor={'service','residential','living_street','footway','path','pedestrian','steps','track','unclassified'}
res=[]; inside_pts=0; tot_pts=0
for x in d['elements']:
    if x['type']!='way': continue
    t=x['tags']
    if t.get('highway') not in minor: continue
    if not (t.get('service')=='alley' or rx.match(t.get('name',''))): continue
    pts=[nodes[i] for i in x['nodes']]
    if not all(s<=la<=n and w<=lo<=e for lo,la in pts): continue
    line=transform(utm, LineString(pts))
    if line.length<10: continue
    widths=[]
    k=2.5
    while k < line.length-2.5:
        p=line.interpolate(k); p2=line.interpolate(min(k+1,line.length)); p0=line.interpolate(max(k-1,0))
        dx,dy=p2.x-p0.x,p2.y-p0.y; L=math.hypot(dx,dy) or 1; nx,ny=-dy/L,dx/L
        tot_pts+=1
        if any(geoms[i].contains(p) for i in tree.query(p)): inside_pts+=1; k+=5; continue
        dists=[]
        for sg in (1,-1):
            ray=LineString([(p.x,p.y),(p.x+sg*nx*15,p.y+sg*ny*15)])
            best=None
            for i in tree.query(ray):
                inter=geoms[i].intersection(ray)
                if not inter.is_empty:
                    dd=p.distance(inter)
                    best=dd if best is None else min(best,dd)
            dists.append(best)
        if None not in dists: widths.append(dists[0]+dists[1])
        k+=5
    if widths:
        res.append((t.get('motorcar') or ('mv:'+t['motor_vehicle'] if 'motor_vehicle' in t else '(none)'), statistics.median(widths), t.get('name'), t.get('highway'), t.get('width'), line.length, x['id']))
print(f"[{tag}] alleys with >=1 two-sided gap measurement: {len(res)}; sample points {tot_pts}, of which inside a footprint: {inside_pts} ({100*inside_pts/max(tot_pts,1):.1f}%)")
by=collections.defaultdict(list)
for r in res: by[r[0]].append(r[1])
for k,v in sorted(by.items(), key=lambda z:-len(z[1])):
    v.sort(); q=lambda p: v[min(len(v)-1,int(p*len(v)))]
    print(f"  motorcar={k:16s} n={len(v):4d} gap-width median={q(.5):.1f} m  p25={q(.25):.1f}  p75={q(.75):.1f}  share<3m={sum(1 for z in v if z<3)/len(v):.0%}")
json.dump(res, open(f'gap_{tag}.json','w'), ensure_ascii=False)
