"""Actual city cache coverage coloured by strongest source tier; offline PNG."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from shapely.geometry import shape
from app.evidence_queue import city_state, INVENTORY

COLORS = {'Measured':'#78ded1','Official':'#ffd27d','Observed':'#89b9f8','Declared':'#e6a6df','Inferred':'#b8ac8c',None:'#3a4954'}


def main():
    state = city_state()
    inv = json.loads(INVENTORY.read_text())
    cov = state['coverage']
    lines = defaultdict(list)
    for wid, r in state['ways'].items():
        lines[r['top_tier']].append(inv['ways'][wid]['coords'])
    plt.rcParams.update({'font.family':'DejaVu Sans','text.color':'#edf2f7'})
    fig = plt.figure(figsize=(19.2,10.8),facecolor='#0d1821')
    ax = fig.add_axes([.035,.14,.69,.65],facecolor='#0d1821')
    boundaries = ROOT/'data/official/hcmc_urban_districts_2021.geojson'
    if boundaries.exists():
        polys = []
        for f in json.loads(boundaries.read_text())['features']:
            geom = shape(f['geometry'])
            polys += [list(p.exterior.coords) for p in (geom.geoms if geom.geom_type=='MultiPolygon' else [geom])]
            p = geom.representative_point()
            ax.text(p.x,p.y,f['properties']['name'].replace('QUẬN ','Q.').replace('THÀNH PHỐ ',''),
                    fontsize=6,color='#a3b3c0',ha='center',alpha=.8,zorder=5)
        ax.add_collection(PolyCollection(polys,facecolor='#14242e',edgecolor='#344752',linewidth=.4))
    for tier in (None,'Inferred','Declared','Observed','Official','Measured'):
        if lines[tier]:
            ax.add_collection(LineCollection(lines[tier],colors=COLORS[tier],linewidths=.25 if tier is None else .65,
                                             alpha=.45 if tier is None else .9,rasterized=True))
    ax.set_xlim(106.505,106.945);ax.set_ylim(10.66,10.975);ax.set_aspect(1/.982);ax.axis('off')
    ax.plot([106.52,106.52+5000/109400],[10.675,10.675],color='#becbd3',lw=2)
    ax.text(106.52,10.68,'5 km',fontsize=8,color='#becbd3')
    fig.text(.055,.94,'NGÕ NGÁCH  /  EVIDENCE ENGINE',fontsize=13,weight='bold',color='#78ded1')
    fig.text(.055,.877,'Bằng chứng bề rộng, trên từng đoạn hẻm.',fontsize=30,weight='bold')
    fig.text(.055,.833,'TP.HCM · Màu theo nguồn mạnh nhất · Không bao gồm suy đoán theo loại đường OSM',fontsize=12,color='#a4b7c4')
    fig.text(.75,.76,f"{cov['evidence_ways_with_sources']:,}",fontsize=40,color='#78ded1',weight='bold')
    fig.text(.75,.72,f"/ {cov['evidence_non_main_ways']:,} đoạn đường nhánh có nguồn",fontsize=11,color='#b6c6d2')
    counts=cov['evidence_ways_by_strongest_tier']
    names={'Measured':'Đo thực tế','Official':'Chính thức','Observed':'Quan sát','Declared':'Tin rao / tự khai','Inferred':'Suy luận'}
    for i,tier in enumerate(names):
        y=.65-i*.06
        fig.text(.75,y,'━',fontsize=22,color=COLORS[tier])
        fig.text(.78,y+.005,names[tier],fontsize=12)
        fig.text(.96,y+.005,f"{counts[tier]:,}",fontsize=12,ha='right',color=COLORS[tier])
    fig.text(.75,.305,f"{cov['evidence_ways_unknown']:,} đoạn chưa có nguồn",fontsize=15,color='#a4b7c4',weight='bold')
    fig.text(.75,.26,f"{cov['evidence_declared_index_ways']:,} đoạn trong chỉ mục tin rao",fontsize=11,color='#e6a6df')
    fig.text(.75,.216,f"{cov['evidence_osm_routing_cells']:,} ô bản đồ đã lưu",fontsize=11,color='#a4b7c4')
    fig.text(.055,.104,'Bằng chứng ≠ xác nhận xe vào được. Tin rao mức Tự khai; địa chính và đo thực tế được ưu tiên.',fontsize=11,color='#cad6df')
    fig.text(.055,.071,'Phạm vi là hợp các ô OSM đã lưu ở vùng đô thị; không phủ toàn bộ địa giới TP.HCM. Xám: chưa có nguồn bề rộng.',fontsize=10,color='#a4b7c4')
    fig.text(.055,.035,'© OpenStreetMap contributors · ODbL  |  '+str(cov['evidence_declared_generated_at'])+'  |  Màu không biểu diễn chiều rộng',fontsize=8.5,color='#738c9e')
    out=ROOT/'docs/eval/coverage-evidence.png'
    fig.savefig(out,dpi=200,facecolor=fig.get_facecolor())
    (ROOT/'docs/eval/evidence-coverage.json').write_text(json.dumps(cov,ensure_ascii=False,indent=2))
    print(out)


if __name__=='__main__':
    main()
