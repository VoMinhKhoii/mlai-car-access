import math, json, sys, io, subprocess, os
from PIL import Image, ImageDraw
import duckdb
from shapely import wkb
tag, hwfile, lat, lon, z = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), int(sys.argv[5])
def deg2num(lat, lon, z):
    n=2**z; x=(lon+180)/360*n; y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n; return x,y
cx,cy=deg2num(lat,lon,z); x0,y0=int(cx)-1,int(cy)-1
img=Image.new('RGB',(768,768))
for dx in range(3):
    for dy in range(3):
        fn=f'tile_{z}_{x0+dx}_{y0+dy}.jpg'
        if not os.path.exists(fn):
            subprocess.run(['curl','-s','-m','30','-A','Mozilla/5.0','-o',fn,f'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y0+dy}/{x0+dx}'])
        img.paste(Image.open(fn).convert('RGB'),(dx*256,dy*256))
raw=img.copy()
def px(lo,la):
    x,y=deg2num(la,lo,z); return ((x-x0)*256,(y-y0)*256)
dr=ImageDraw.Draw(img)
con=duckdb.connect(); con.execute("LOAD spatial;")
col={'Google Open Buildings':(255,0,0),'Microsoft ML Buildings':(0,160,255),'OpenStreetMap':(255,255,0)}
for g,ds in con.execute(f"select ST_AsWKB(geometry), sources[1].dataset from 'ov_{tag}.parquet'").fetchall():
    geom=wkb.loads(bytes(g))
    polys=[geom] if geom.geom_type=='Polygon' else list(geom.geoms)
    for p in polys:
        pts=[px(*c) for c in p.exterior.coords]
        if all(-50<a<818 and -50<b<818 for a,b in pts): dr.line(pts+[pts[0]],fill=col.get(ds,(255,255,255)),width=1)
d=json.load(open(hwfile)); nodes={x['id']:(x['lon'],x['lat']) for x in d['elements'] if x['type']=='node'}
for x in d['elements']:
    if x['type']!='way': continue
    t=x['tags']; mc=t.get('motorcar')
    c=(0,255,0) if mc in ('destination','yes') else ((255,0,255) if mc=='no' or t.get('motor_vehicle')=='no' else (255,255,255))
    pts=[px(*nodes[i]) for i in x['nodes'] if i in nodes]
    if len(pts)>1: dr.line(pts,fill=c,width=2)
mpp=156543.03*math.cos(math.radians(lat))/2**z
print('m/px',round(mpp,3))
img.save(f'render_{tag}_{z}.png'); raw.save(f'raw_{tag}_{z}.png')
