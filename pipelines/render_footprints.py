"""Render the footprint coverage hero, from actual job output; no network calls."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
import matplotlib.patheffects as pe
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
PALETTE = ["#ee8c83", "#f3ca79", "#69d8c3", "#93b9ff"]
NAMES = ["Hẻm xe máy", "Hẻm ba gác", "Hẻm xe hơi", "Ô tô tránh"]


def width_class(w):
    return 0 if w < 2 else 1 if w < 3 else 2 if w < 5 else 3


def main():
    data = json.loads((ROOT / "backend/cache/live/footprint_widths.json").read_text())
    roads = json.loads((ROOT / "data/raw/buildings/roads.json").read_text())
    stats, cal, estimates = data["stats"], data["calibration"], data["ways"]
    bg, classes, counts = [], [[] for _ in range(4)], Counter()
    for r in roads:
        wid = str(r["id"])
        if wid in estimates:
            klass = width_class(estimates[wid]["estimate_m"])
            classes[klass].append(r["coords"])
            counts[klass] += 1
        else:
            bg.append(r["coords"])
    plt.rcParams.update({"font.family":"DejaVu Sans", "text.color":"#edf2f7"})
    fig = plt.figure(figsize=(19.2,10.8),facecolor="#0b1620")
    ax = fig.add_axes([.025,.125,.69,.69],facecolor="#0b1620")
    scope=json.loads((ROOT / "data/official/hcmc_urban_districts_2021.geojson").read_text())
    polygons=[]
    labels=[]
    for f in scope["features"]:
        geom=shape(f["geometry"])
        polygons.extend([list(p.exterior.coords) for p in (geom.geoms if geom.geom_type=="MultiPolygon" else [geom])])
        p=geom.representative_point()
        name=f["properties"]["name"].replace("QUẬN ","Q.").replace("THÀNH PHỐ ","")
        labels.append((p.x,p.y,name))
    ax.add_collection(PolyCollection(polygons,facecolor="#10222e",edgecolor="#2c4350",linewidth=.5))
    ax.add_collection(LineCollection(bg,colors="#3c4d58",linewidths=.25,alpha=.6,rasterized=True))
    for k,lines in enumerate(classes):
        ax.add_collection(LineCollection(lines,colors=PALETTE[k],linewidths=1.45,alpha=.08,rasterized=True))
        ax.add_collection(LineCollection(lines,colors=PALETTE[k],linewidths=.48,alpha=.88,rasterized=True))
    for x,y,label in labels:
        if 106.555<x<106.875 and 10.69<y<10.89:
            text=ax.text(x,y,label,fontsize=7.8,color="#d3dde4",ha="center",va="center",zorder=10)
            text.set_path_effects([pe.withStroke(linewidth=3,foreground="#10222e")])
    ax.set_xlim(106.55,106.88);ax.set_ylim(10.68,10.90);ax.set_aspect(1/.982)
    ax.axis("off")
    # North arrow and geodesic scale in local metres.
    ax.annotate("N",xy=(106.564,10.875),xytext=(106.564,10.892),ha="center",fontsize=10,
                color="#90a6b5",arrowprops=dict(arrowstyle="<-",color="#90a6b5",lw=1.))
    x,y=106.56,10.687
    ax.plot([x,x+5000/109400],[y,y],color="#bdcbd4",lw=2)
    ax.text(x,y+.003,"5 km",fontsize=8,color="#bdcbd4")
    fig.text(.055,.935,"NGÕ NGÁCH",fontsize=14,weight="bold",color="#69d8c3")
    fig.text(.055,.877,"Bản đồ hẻm, nhìn từ mái nhà.",fontsize=32,weight="bold")
    fig.text(.055,.833,"TP.HCM  ·  Ước lượng từ mái nhà, hiệu chỉnh bằng địa chính",fontsize=13,color="#9eb1be")
    fig.text(.74,.767,f"{len(estimates):,}",fontsize=46,weight="bold",color="#69d8c3")
    fig.text(.742,.726,"đoạn có ước lượng thử nghiệm",fontsize=12,color="#d0dce5")
    fig.text(.742,.68,f"{stats['percent_with_footprint_width']:.1f}%",fontsize=26,weight="bold")
    fig.text(.825,.684,f"trong {stats['ways_total']:,} đường nhánh",fontsize=10.5,color="#9eb1be")
    fig.text(.742,.627,"PHÂN LỚP THEO ƯỚC LƯỢNG TRUNG TÂM",fontsize=9,weight="bold",color="#90a6b5")
    for k,label in enumerate(NAMES):
        yy=.577-k*.055
        fig.text(.742,yy,"━",fontsize=23,color=PALETTE[k],weight="bold")
        fig.text(.77,yy+.005,label,fontsize=12)
        fig.text(.952,yy+.005,f"{counts[k]:,}",fontsize=11,color=PALETTE[k],ha="right")
    fig.text(.742,.353,"CHƯA ĐẠT KIỂM CHỨNG · TẮT MẶC ĐỊNH",fontsize=9,weight="bold",color="#f3ca79")
    fig.text(.742,.31,f"{cal['matched_ways']} đoạn địa chính đối chiếu",fontsize=12)
    fig.text(.742,.272,f"±{cal['uncertainty_radius_m']:.1f} m",fontsize=24,color="#f3ca79",weight="bold")
    fig.text(.742,.236,"bán kính sai số thực nghiệm",fontsize=11,color="#9eb1be")
    fig.text(.742,.196,"Địa chính luôn được ưu tiên.",fontsize=12,color="#69d8c3")
    fig.text(.055,.104,"Màu là ước lượng, không xác nhận xe vào được. Khoảng bất định có thể cắt qua nhiều lớp.",fontsize=11,color="#c9d5de")
    fig.text(.055,.073,"Xám: chưa đủ hai phía nhà; không được coi là đường rộng. Chỉ phạm vi 10,68–10,90°N / 106,55–106,88°E.",fontsize=10,color="#90a6b5")
    fig.text(.055,.035,"© OpenStreetMap contributors · Overture Maps Foundation · Microsoft · Google Open Buildings  |  ODbL / CC BY 4.0  |  17.10.2026",fontsize=8.5,color="#718b9d")
    path=ROOT / "docs/eval/coverage-footprints.png"
    fig.savefig(path,dpi=200,facecolor=fig.get_facecolor())
    print(path)


if __name__=="__main__":main()
