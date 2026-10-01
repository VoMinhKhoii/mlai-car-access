"""Rank 2x2 km cells of central HCMC for the demo area.

Inputs: OSM alley-like ways (Overpass, `out tags center`), OSM parking,
IRD historical flood points. Output: printed ranking + grid_cells.json.
"""
import json, re, collections, math

LAT0, LAT1, LON0, LON1 = 10.70, 10.86, 106.60, 106.78
DLAT = 2.0 / 110.6
DLON = 2.0 / (111.32 * math.cos(math.radians(10.78)))

def cell_of(lat, lon):
    if not (LAT0 <= lat < LAT1 and LON0 <= lon < LON1):
        return None
    return (int((lat - LAT0) / DLAT), int((lon - LON0) / DLON))

cells = collections.defaultdict(lambda: collections.Counter())
names = collections.defaultdict(collections.Counter)
wards = collections.defaultdict(collections.Counter)

# Alleys
alleys = json.load(open('hcm_core_alleys.json'))['elements']
for w in alleys:
    c = w.get('center')
    if not c:
        continue
    k = cell_of(c['lat'], c['lon'])
    if k is None:
        continue
    t = w.get('tags', {})
    cells[k]['alleys'] += 1
    mc = t.get('motorcar') or t.get('motor_vehicle')
    if mc:
        cells[k]['car_tagged'] += 1
        if mc == 'no':
            cells[k]['car_no'] += 1
        else:
            cells[k]['car_ok'] += 1
    n = t.get('name', '')
    m = re.match(r'^(?:Hẻm|hẻm|HẺM|Kiệt)\s+[\d/]+\s+(.*)$', n)
    if m:
        names[k][m.group(1).strip()] += 1

# Parking (cars only)
P = '/private/tmp/claude-501/-Users-khoivo-Developer/2283b5f5-9ab5-48f6-be83-4d8a6fb67ff8/scratchpad/parking/hcm_parking.json'
for e in json.load(open(P))['elements']:
    if e.get('tags', {}).get('amenity') != 'parking':
        continue
    lat = e.get('lat') or e.get('center', {}).get('lat')
    lon = e.get('lon') or e.get('center', {}).get('lon')
    if lat is None:
        continue
    k = cell_of(lat, lon)
    if k is None:
        continue
    acc = e['tags'].get('access', '')
    if acc in ('private', 'no'):
        continue
    cells[k]['parking'] += 1

# Flood points
g = json.load(open('../flood/ird-hcmc/flood_points.geojson'))
for f in g['features']:
    p = f['properties']
    lon, lat = f['geometry']['coordinates'][:2]
    k = cell_of(lat, lon)
    if k is None:
        continue
    prec = (p.get('Spatial_precision') or '').strip().lower()
    prec = {'hugh': 'high', 'hgh': 'high'}.get(prec, prec)
    cells[k]['flood_all'] += 1
    if prec in ('high', 'medium'):
        cells[k]['flood_hm'] += 1
    cause = (p.get('Cause') or '').lower()
    if 'tide' in cause:
        cells[k]['flood_tide'] += 1
    if 'rain' in cause:
        cells[k]['flood_rain'] += 1
    if (p.get('Year') or 0) >= 2020:
        cells[k]['flood_recent'] += 1
    if p.get('Current_admin_unit'):
        wards[k][p['Current_admin_unit'].strip()] += 1

rows = []
for k, c in cells.items():
    if c['alleys'] < 200:
        continue
    share = c['car_tagged'] / c['alleys']
    center = (LAT0 + (k[0] + 0.5) * DLAT, LON0 + (k[1] + 0.5) * DLON)
    score = (min(c['flood_hm'], 15) / 15) * 0.4 + (min(c['alleys'], 1500) / 1500) * 0.25 \
        + share * 0.25 + (min(c['parking'], 10) / 10) * 0.10
    rows.append(dict(cell=k, center=[round(center[0], 5), round(center[1], 5)], score=round(score, 3),
                     alleys=c['alleys'], car_tag_share=round(share, 2), car_ok=c['car_ok'], car_no=c['car_no'],
                     parking=c['parking'], flood_all=c['flood_all'], flood_hm=c['flood_hm'],
                     flood_tide=c['flood_tide'], flood_rain=c['flood_rain'], flood_recent=c['flood_recent'],
                     top_alley_parents=[n for n, _ in names[k].most_common(4)],
                     flood_wards=[n for n, _ in wards[k].most_common(3)]))
rows.sort(key=lambda r: -r['score'])
json.dump(rows, open('grid_cells.json', 'w'), ensure_ascii=False, indent=1)
print(f"{'rank':>4} {'center':>20} {'score':>5} {'alleys':>6} {'car%':>5} {'ok/no':>7} {'park':>4} {'fl_all':>6} {'fl_hm':>5} {'tide':>4} {'rain':>4} {'>=2020':>6}  parents | wards")
for i, r in enumerate(rows[:15], 1):
    print(f"{i:>4} {str(r['center']):>20} {r['score']:>5} {r['alleys']:>6} {r['car_tag_share']*100:>4.0f}% {str(r['car_ok'])+'/'+str(r['car_no']):>7} {r['parking']:>4} {r['flood_all']:>6} {r['flood_hm']:>5} {r['flood_tide']:>4} {r['flood_rain']:>4} {r['flood_recent']:>6}  {', '.join(r['top_alley_parents'][:3])} | {', '.join(r['flood_wards'])}")
