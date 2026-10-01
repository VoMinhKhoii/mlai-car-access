import json, re, collections, sys
BOXES = {
 "A Bình Thạnh (ĐBP/XVNT/Nguyễn Hữu Cảnh)": (10.790, 10.810, 106.695, 106.722),
 "B Q1 south + Q4 (Cô Giang/Đoàn Văn Bơ)": (10.752, 10.772, 106.690, 106.712),
 "C Phú Nhuận/Tân Định (sample)": (10.786, 10.804, 106.676, 106.694),
}
alleys = json.load(open('hcm_core_alleys.json'))['elements']
P = '/private/tmp/claude-501/-Users-khoivo-Developer/2283b5f5-9ab5-48f6-be83-4d8a6fb67ff8/scratchpad/parking/hcm_parking.json'
parking = [e for e in json.load(open(P))['elements'] if e.get('tags', {}).get('amenity') == 'parking']
flood = json.load(open('../flood/ird-hcmc/flood_points.geojson'))['features']
inb = lambda b, lat, lon: b[0] <= lat < b[1] and b[2] <= lon < b[3]
for name, b in BOXES.items():
    al = [w for w in alleys if w.get('center') and inb(b, w['center']['lat'], w['center']['lon'])]
    tagged = [w for w in al if (w['tags'].get('motorcar') or w['tags'].get('motor_vehicle'))]
    no = [w for w in tagged if (w['tags'].get('motorcar') or w['tags'].get('motor_vehicle')) == 'no']
    pk = [e for e in parking if inb(b, e.get('lat') or e.get('center', {}).get('lat', 0), e.get('lon') or e.get('center', {}).get('lon', 0)) and e['tags'].get('access') not in ('private', 'no')]
    fl = [f for f in flood if inb(b, f['geometry']['coordinates'][1], f['geometry']['coordinates'][0])]
    prec = collections.Counter((f['properties'].get('Spatial_precision') or '').strip().lower().replace('hugh','high').replace('hgh','high') for f in fl)
    cause = collections.Counter((f['properties'].get('Cause') or '').strip() for f in fl)
    locs = collections.Counter((f['properties'].get('Location_name') or '').strip() for f in fl)
    depth = [f['properties'].get('Water_height_max_cm') for f in fl if f['properties'].get('Water_height_max_cm')]
    print(f"\n== {name}  bbox={b}")
    print(f"  alleys {len(al)}, car-tagged {len(tagged)} ({len(tagged)/max(len(al),1):.0%}), motorcar=no {len(no)}")
    print(f"  public car parking (OSM) {len(pk)}")
    print(f"  IRD flood records {len(fl)}; precision {dict(prec)}; cause {dict(cause)}")
    print(f"  depth max cm (n={len(depth)}): {sorted(depth)}")
    print(f"  top flood locations: {locs.most_common(6)}")
