"""Offline official alley-width/ROW import. Never calls the point planning portal or an LLM.

python3 pipelines/official_bulk.py build
Inputs are bounded public downloads in data/raw/official_bulk (see source manifest).
Historical road/base widths and planned ROW remain metadata, never Clear Width bounds.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'pipelines'))
from common import fold, norm_name
from listings_city import graph_for, atomic
from app.live import _match
from app.osm import haversine

RAW = ROOT / 'data/raw/official_bulk'
PRODUCT = ROOT / 'backend/cache/live/official_widths.json'
Q9_URL = 'https://congbao.hochiminhcity.gov.vn/cong-bao/van-ban/quyet-dinh/so/01-2009-qd-ubnd/ngay/16-02-2009/tai-ve/30822'
MAP_URL = 'https://maps.hcmgis.vn/statistic'


def clean(s):
    return re.sub(r'\s+', ' ', (s or '').replace('ð', 'đ').replace('Ð', 'Đ')).strip()


def numeric_range(s):
    s = clean(s).replace(',', '.')
    if not re.fullmatch(r'\d+(?:\.\d+)?(?:\s*[-÷–]\s*\d+(?:\.\d+)?)?', s):
        return None
    nums = [float(x) for x in re.findall(r'\d+(?:\.\d+)?', s)]
    if not all(0 < x <= 100 for x in nums):
        return None
    return [min(nums), max(nums)]


def parse_q9(path):
    import pdfplumber
    records, audit = [], []
    ward, cols, context_road = '', None, ''
    with pdfplumber.open(path) as pdf:
        for pi, page in enumerate(pdf.pages):
            text = clean(page.extract_text())
            m = re.search(r'LỘ GIỚI HẺM PHƯỜNG (.+?) \(Ban hành', text)
            if m:
                ward, context_road = m[1], ''
            for table in page.extract_tables():
                if clean(table[0][0]).upper() == 'STT':
                    head = [fold(clean(c)) for c in table[0]]
                    sub = [fold(clean(c)) for c in table[1]] if len(table)>1 else ['']*len(head)
                    def col(test):
                        return next((i for i,v in enumerate(head) if test(v)), None)
                    cols = {'name': col(lambda v:'ten moi' in v) or col(lambda v:'ten hem' in v or 'ten duong' in v),
                            'route': col(lambda v:'ly trinh' in v),
                            'length': col(lambda v:'dai chung' in v),
                            'base': col(lambda v:'rong' in v)}
                    forecast = [i for i,(v,w) in enumerate(zip(head,sub)) if 'du kien' in v or 'du kien' in w or w=='dk']
                    cols['planned'] = forecast[-1] if forecast else col(lambda v:'lo gioi' in v)
                    if any(v is None for v in cols.values()):
                        raise ValueError(f'Unrecognized official table layout on PDF page {pi+1}: {cols}')
                if not cols:
                    continue
                for ri, row in enumerate(table):
                    if not re.fullmatch(r'\d+', clean(row[0])):
                        # Full-width street section headings are authoritative context.
                        v = clean(row[0])
                        if fold(v).startswith('duong ') and all(c is None for c in row[1:]):
                            context_road = v
                        continue
                    cells = {k: clean(row[i]) for k,i in cols.items()}
                    base, planned = numeric_range(cells['base']), numeric_range(cells['planned'])
                    r = {'id': f'q9-2009-p{pi+1}-r{ri+1}', 'source_id':'q9_2009', 'pdf_page':pi+1,
                         'ordinal':int(row[0]), 'ward':ward, 'name':cells['name'], 'route':cells['route'],
                         'context_road':context_road, 'length_text':cells['length'],
                         'road_base_width_m':base, 'planned_right_of_way_m':planned,
                         'source_date':'2009-02-16', 'url':Q9_URL, 'table_cells':cells}
                    if not base and not planned:
                        audit.append({**r,'status':'unparsed_numeric_cells'})
                    else:
                        records.append(r)
    return records, audit


def source_chain_names(r):
    """Only explicit street context; never expand a child width onto a parent alley."""
    name = re.sub(r'(?i)^hẻm\s+số\s+', 'Hẻm ', clean(r['name']))
    # Structured names sometimes already say "Hẻm 4 đường Lò Lu".
    name = re.sub(r'(?i)\bđường số\s+', 'Đường ', name)
    names = []
    if re.search(r'(?i)hẻm\s+[\d\w/]+\s+(?:đường\s+)?[A-Za-zÀ-ỹĐđ]', name):
        names.append(name)
    number = re.match(r'(?i)^(?:hẻm\s+)?(\d+[A-Za-z]?(?:/[\dA-Za-z]+)*)\b', name)
    if not number:
        return names
    # A name can include a street in parentheses, e.g. "300 (Lê Văn Việt)".
    explicit = re.search(r'\(([^)]+)\)', name)
    start = re.split(r'\s+[-–]\s+', r['route'])[0].strip()
    start = re.sub(r'(?i)^đ\.?\s*(?=\w)', 'Đường ', start)
    start = re.sub(r'(?i)^đường số\s+', 'Đường ', start)
    roads = [explicit[1]] if explicit else [start, r.get('context_road','')]
    for road in roads:
        if road and not re.match(r'(?i)^(?:hẻm|nhà|cuối|rạch|ngã|cầu|khu|trường)\b', road):
            names.append(f'Hẻm {number[1]} {road}')
    return list(dict.fromkeys(names))


def match_q9(records, rows):
    # Global by-name uniqueness guards the coordinate-free legacy chain matcher.
    g, by_name = graph_for(rows)
    owners = defaultdict(set)
    for record in records:
        for name in source_chain_names(record):
            owners[norm_name(name)].add(record['ward'])
    out = []
    for r in records:
        found = {}
        candidates = source_chain_names(r)
        for name in candidates:
            if len(owners[norm_name(name)]) != 1:
                continue
            ways = by_name.get(norm_name(name), [])
            if not ways:
                continue
            # Numbered streets recur citywide: reject even distant duplicates.
            # Multiple splits of the same name are accepted only in one <=500 m cluster.
            pts = [g.nodes[w.nodes[len(w.nodes)//2]] for w in ways]
            if any(haversine(*pts[0],*p)>500 for p in pts[1:]):
                continue
            if not all(10.72<=y<=10.94 and 106.72<=x<=106.91 for y,x in pts):
                continue
            best, method = _match(g, by_name, [name], None, None)
            if best is None or method != 'alley_chain':
                continue
            for w in ways:
                if w.highway in ('motorway','trunk','primary','secondary','tertiary'):
                    continue
                found[w.id] = w.name
        out.append({**r,'candidate_names':candidates,'way_ids':sorted(found),
                    'osm_names':sorted(set(found.values())),
                    'match_method':'exact_chain_unique_cluster' if found else None,
                    'status':'matched' if found else 'unresolved_name_or_ambiguity'})
    return out


def metric_line(coords):
    from shapely.geometry import LineString
    # Fixed local equirectangular projection, scale error << matching tolerance in this tiny extent.
    return LineString([(x*111320*math.cos(math.radians(10.82)),y*111320) for x,y in coords])


def source_lines(feature):
    from shapely.geometry import MultiLineString
    geom = feature['geometry']
    cs = geom['coordinates'] if geom['type']=='MultiLineString' else [geom['coordinates']]
    return MultiLineString([metric_line(c) for c in cs if len(c)>1])


def line_match_stats(way_line, source):
    n = max(4, math.ceil(way_line.length/5))
    points = [way_line.interpolate(way_line.length*i/n) for i in range(n+1)]
    distances = [p.distance(source) for p in points]
    # Whole-way support only; no widening across source endpoints or parallel roads.
    fraction = sum(d<=3 for d in distances)/len(distances)
    near = way_line.intersection(source.buffer(3)).length / max(way_line.length, .01)
    from shapely.ops import nearest_points
    aligned = []
    for a, b in zip(points, points[1:]):
        sa, sb = nearest_points(a, source)[1], nearest_points(b, source)[1]
        dx, dy, sx, sy = b.x-a.x, b.y-a.y, sb.x-sa.x, sb.y-sa.y
        den = math.hypot(dx,dy)*math.hypot(sx,sy)
        angle = math.degrees(math.acos(min(1,abs((dx*sx+dy*sy)/den)))) if den > .01 else 90
        aligned.append(angle <= 20)
    return {'aligned_fraction':round(sum(aligned)/len(aligned),3), 'fraction_within_3m':round(fraction,3),'length_fraction_within_3m':round(near,3),
            'max_distance_m':round(max(distances),3),'mean_distance_m':round(sum(distances)/len(distances),3)}


def match_hcmgis(rows):
    from shapely.strtree import STRtree
    collection=json.loads((RAW/'maps_ht_lg_hem_pla_line.body').read_text())
    features=collection['features']
    if collection.get('totalFeatures') != len(features):
        raise ValueError('WFS response is incomplete; source review is required before import')
    source_geoms=[source_lines(f) for f in features]
    tree=STRtree(source_geoms)
    matches, audit = defaultdict(list), []
    for wid,r in rows.items():
        coords=r['coords']
        if not any(106.74<=x<=106.79 and 10.79<=y<=10.85 for x,y in coords):
            continue
        geom=metric_line(coords)
        if geom.length<15:
            continue
        eligible=[]
        for k in tree.query(geom.buffer(3)):
            stats=line_match_stats(geom,source_geoms[k])
            if stats['aligned_fraction']>=.8 and stats['fraction_within_3m']>=.9 and stats['length_fraction_within_3m']>=.9 and stats['max_distance_m']<=5:
                eligible.append((int(k),stats))
        if len(eligible)!=1:
            if eligible:audit.append({'way_id':int(wid),'status':'ambiguous_parallel_or_duplicate','candidates':[features[k]['id'] for k,_ in eligible]})
            continue
        k,stats=eligible[0];f=features[k];p=f['properties']
        width=numeric_range(str(p.get('chieurong','')))
        if not width:
            continue
        record={'id':f['id'],'source_id':'hcmgis_pla_2021','source_date':p.get('ngayphienban','')[:10],
                'name':p.get('duong',''),'road_base_width_m':None,'reported_road_width_m':width,
                'width_definition':'Source field chieurong; base/surface/clear-width meaning unverified',
                'planned_right_of_way_m':None,
                'url':MAP_URL,'reported_position_accuracy':p.get('giatridochinhxacmatphang'),
                'position_accuracy_unit':'not_verified_from_service_metadata',
                'match_method':'whole_way_geometry_90pct_3m','match':stats,
                'way_ids':[int(wid)],'osm_name':r['tags'].get('name',''),
                'status':'historical_width_definition_unverified'}
        matches[wid].append(record)
    matched_ids={r['id'] for rs in matches.values() for r in rs}
    return matches, {'features':len(features),'matched_features':len(matched_ids),'matched_ways':len(matches),
                     'unmatched_features':[f['id'] for f in features if f['id'] not in matched_ids],
                     'ambiguous_matches':audit, 'min_way_length_m':15, 'alignment_fraction_required':.8}


def cadastral_snapshot(output_path=None):
    result=defaultdict(dict);inputs=[];city_ids=set()
    paths=[ROOT/'backend/cache/live/city_parcels.json',*sorted((ROOT/'backend/cache/live/areas').glob('*.json'))]
    for path in paths:
        if not path.exists():continue
        raw=path.read_bytes();d=json.loads(raw)
        records=d.get('parcels',[]) if path.parent.name=='areas' else [{'way_id':k,**v} for k,v in d.items() if isinstance(v,dict)]
        inputs.append({'path':str(path.relative_to(ROOT)),'sha256':hashlib.sha256(raw).hexdigest()})
        for r in records:
            for c in r.get('cuts',[]):
                if not isinstance(c,dict) or c.get('valid',True) is False or not all(c.get(k) is not None for k in ['gap_m','lat','lon']):continue
                if path.name=='city_parcels.json':city_ids.add(str(r['way_id']))
                result[str(r['way_id'])][(round(c['lat'],7),round(c['lon'],7))]=c
    out={'generated_at':datetime.now(timezone.utc).isoformat(),'inputs':inputs,'city_way_ids':sorted(city_ids),
         'ways':{wid:list(cuts.values()) for wid,cuts in result.items()}}
    atomic(output_path or RAW/'cadastral_snapshot.json',out)
    return out


def validate(ways, snapshot):
    records=[]
    for wid,claims in ways.items():
        cuts=snapshot['ways'].get(str(wid),[])
        if not cuts:continue
        gap=min(c['gap_m'] for c in cuts)
        for c in claims:
            base=c.get('road_base_width_m') or c.get('reported_road_width_m');planned=c.get('planned_right_of_way_m')
            records.append({'way_id':int(wid),'source_id':c['source_id'],'record_id':c['id'],
                            'min_raw_parcel_gap_m':gap,'n_cuts':len(cuts),'road_base_width_m':base,
                            'planned_right_of_way_m':planned,
                            'base_minus_gap_m':(sum(base)/2-gap) if base else None,
                            'planned_ge_gap':planned[1]>=gap if planned else None})
    per={}
    for sid in ['q9_2009','hcmgis_pla_2021']:
        rs=[r for r in records if r['source_id']==sid];errors=sorted(abs(r['base_minus_gap_m']) for r in rs if r['base_minus_gap_m'] is not None)
        per[sid]={'overlapping_ways':len({r['way_id'] for r in rs}),'comparisons':len(rs),
                  'base_width_median_absolute_difference_m':errors[len(errors)//2] if errors else None,
                  'agreement':None,'reason':'No cadastral overlap; accuracy/ROW agreement cannot be estimated' if not rs else 'Different dates/semantics; descriptive comparison only'}
    return {'city_reference_ways':len(snapshot['city_way_ids']),'union_reference_ways':len(snapshot['ways']),
            'reference_cuts':sum(len(v) for v in snapshot['ways'].values()),'reference':'raw gap_m, no 1 m deduction',
            'per_source':per,'rows':records,'current_clear_width_new_ways':0}


def build():
    inv=json.loads((ROOT/'backend/cache/live/evidence_inventory.json').read_text())
    rows=inv['ways']
    q9,failures=parse_q9(RAW/'q9_2009_download.body')
    q9=match_q9(q9,rows)
    atomic(ROOT/'data/official/alley_widths_q9_2009.json',{'schema_version':1,'attribution':'Công báo Thành phố Hồ Chí Minh',
           'url':Q9_URL,'source_date':'2009-02-16','legal_status':'partly amended 2012-08-21; historical snapshot, not a current legal determination',
           'records':q9,'parse_failures':failures})
    ways,ma=match_hcmgis(rows)
    for r in q9:
        for wid in r['way_ids']:ways[str(wid)].append(r)
    snapshot=cadastral_snapshot();validation=validate(ways,snapshot)
    product={'schema_version':1,'generated_at':datetime.now(timezone.utc).isoformat(),
             'semantics':'official_historical_and_planned_metadata_only','inventory_generated_at':inv['generated_at'],
             'sources':{'q9_2009':{'title':'QĐ 01/2009/QĐ-UBND Quận 9; Công báo TP.HCM','date':'2009-02-16','url':Q9_URL,
                                 'reuse':'Gazette footer permits reuse with source attribution','attribution':'Công báo Thành phố Hồ Chí Minh'},
                        'hcmgis_pla_2021':{'title':'HCMGIS Maps / Phước Long A: Hiện trạng lộ giới hẻm (Line)','date':'2021-08-09','url':MAP_URL,
                                          'reuse':'WFS Fees/AccessConstraints NONE; explicit data licence not stated; permission needed for redistribution'}},
             'ways':dict(ways)}
    from geocode_unmatched import merge_official
    product = merge_official(product)
    atomic(PRODUCT,product)
    comparisons=[]
    for wid, claims in ways.items():
        old=[r for r in claims if r['source_id']=='q9_2009' and r.get('road_base_width_m')]
        recent=[r for r in claims if r['source_id']=='hcmgis_pla_2021' and r.get('reported_road_width_m')]
        for a in old:
            for b in recent:
                comparisons.append({'way_id':int(wid),'pdf_record_id':a['id'],'wfs_record_id':b['id'],
                                    'road_base_2009_m':a['road_base_width_m'],'road_width_2021_m':b['reported_road_width_m'],
                                    'absolute_difference_m':round(abs(sum(a['road_base_width_m'])/2-sum(b['reported_road_width_m'])/2),3)})
    import statistics
    cross={'note':'Different dates and width definitions; not cadastral validation or current accuracy',
           'unique_ways':len({r['way_id'] for r in comparisons}),'comparisons':len(comparisons),
           'median_absolute_difference_m':statistics.median([r['absolute_difference_m'] for r in comparisons]) if comparisons else None,
           'rows':comparisons}
    summary={'generated_at':product['generated_at'],'q9':{'parsed_records':len(q9),'wards':dict(Counter(r['ward'] for r in q9)),
             'matched_records':sum(bool(r['way_ids']) for r in q9),'matched_ways':len({wid for r in q9 for wid in r['way_ids']}),
             'parse_failures':len(failures),'unmatched_records':sum(not r['way_ids'] for r in q9)},
             'hcmgis':ma,'metadata_ways':len(ways),'named_or_tagged_alley_metadata_ways':sum(1 for wid in ways if rows[wid]['tags'].get('service')=='alley' or re.search(r'(?i)\b(hẻm|ngõ|ngách|kiệt)\b',rows[wid]['tags'].get('name',''))),
             'cadastral_validation':validation,'dated_official_cross_comparison':cross,'product':str(PRODUCT.relative_to(ROOT)),
             'scope':'Union of existing cached urban HCMC OSM; no citywide completeness claim'}
    atomic(ROOT/'docs/eval/official-bulk-validation.json',summary)
    atomic(RAW/'hcmgis_matches.json',dict(ways))
    print(json.dumps({k:v for k,v in summary.items() if k not in ['hcmgis','cadastral_validation','dated_official_cross_comparison']},ensure_ascii=False,indent=2))
    print('HCMGIS',ma['features'],ma['matched_features'],ma['matched_ways'],'CAD',validation['city_reference_ways'],validation['union_reference_ways'])


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['build'])
    parser.parse_args();build()
