"""Render a snapshot of urban HCMC crawl coverage for the pitch deck.

Run `python3 pipelines/render_coverage.py`. Requires matplotlib; makes no network
or AI calls. Grey context roads come from the existing OSM extract; coloured ways
come from atomic city results and recorded graph geometry. No-data != too narrow.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection, PolyCollection
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Ellipse
from shapely.geometry import shape

ROOT = Path(__file__).resolve().parents[1]
VN = ZoneInfo("Asia/Ho_Chi_Minh")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="docs/eval/coverage-hcmc-round2")
    args = parser.parse_args()
    output = ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    state = json.loads((ROOT / "backend/cache/live/crawl_city_state.json").read_text())
    results = json.loads((ROOT / "backend/cache/live/city_parcels.json").read_text())
    meta = dict(state.get("ways_meta", {}))
    scope = json.loads((ROOT / "data/official/hcmc_urban_districts_2021.geojson").read_text())
    context = ROOT / "data/raw/overture/hcmc_small_roads.json"
    roads = json.loads(context.read_text()) if context.exists() else []
    background = []
    for way in roads:
        coords = way.get("coords", [])
        if len(coords) < 2:
            continue
        background.append(coords)
        wid = str(way["id"])
        if wid in results and wid not in meta:
            meta[wid] = {"coords": [[lat, lon] for lon, lat in coords], "name": way.get("tags", {}).get("name", "")}
    green, amber, locations = [], [], []
    for wid, value in results.items():
        coords = meta.get(wid, {}).get("coords", [])
        if len(coords) >= 2:
            line = [[lon, lat] for lat, lon in coords]
            (green if value else amber).append(line)
            locations.append(line[len(line) // 2])

    plt.rcParams.update({"font.family": "DejaVu Sans", "text.color": "#193942", "axes.labelcolor": "#47636a"})
    fig = plt.figure(figsize=(16, 10), facecolor="#f6f8f7")
    ax = fig.add_axes([.045, .12, .65, .75])
    ax.set_facecolor("#f6f8f7")
    polygons = []
    labels = []
    for feature in scope["features"]:
        poly = shape(feature["geometry"])
        polygons.extend([list(p.exterior.coords) for p in (poly.geoms if poly.geom_type == "MultiPolygon" else [poly])])
        rp = poly.representative_point()
        name = feature["properties"]["name"].replace("QUẬN ", "Q. ").replace("THÀNH PHỐ ", "")
        labels.append((rp.x, rp.y, name))
    ax.add_collection(PolyCollection(polygons, facecolor="#edf1ef", edgecolor="#b5c4bf", linewidth=.7))
    ax.add_collection(LineCollection(background, colors="#c8d0cc", linewidths=.25, alpha=.55, rasterized=True))
    ax.add_collection(LineCollection(amber, colors="#dc8d3a", linewidths=1.3, alpha=.8))
    ax.add_collection(LineCollection(green, colors="#00896f", linewidths=1.8, alpha=.95))
    campus_file = ROOT / "docs/eval/hutech-campuses.json"
    campuses = json.loads(campus_file.read_text())["campuses"] if campus_file.exists() else []
    inner_radius = state.get("campus_inner_radius_m", 2000)
    for campus in campuses:
        if inner_radius < 2000:
            ax.add_patch(Ellipse((campus["lon"], campus["lat"]), 2 * inner_radius / 109400, 2 * inner_radius / 110540,
                                 facecolor="#477aaf", edgecolor="#245985", linewidth=1.0, alpha=.18))
        ax.add_patch(Ellipse((campus["lon"], campus["lat"]), 4000 / 109400, 4000 / 110540,
                             facecolor="none", edgecolor="#477aaf", linewidth=.85, alpha=.55, linestyle="--"))
        ax.scatter([campus["lon"]], [campus["lat"]], marker="o", s=16, color="#245985", zorder=5)
    for lon, lat, label in labels:
        ax.text(lon, lat, label, ha="center", fontsize=7.5, color="#526b68",
                bbox=dict(facecolor="#f6f8f7", edgecolor="none", alpha=.8, pad=1.5))
    ax.set_xlim(106.545, 106.895)
    ax.set_ylim(10.68, 10.915)
    ax.set_aspect(1 / .982)
    ax.tick_params(labelsize=8, colors="#6b817d", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_xlabel("Kinh độ", fontsize=9)
    ax.set_ylabel("Vĩ độ", fontsize=9)
    # A scale bar in the local longitude projection.
    x, y, length = 106.56, 10.695, 5000 / 109400
    ax.plot([x, x + length], [y, y], color="#294b48", linewidth=2)
    ax.text(x + length / 2, y + .003, "5 km", fontsize=8, ha="center")

    fig.text(.06, .944, "DỮ LIỆU HẺM TP.HCM", fontsize=24, weight="bold")
    fig.text(.06, .908, "Phạm vi đô thị · tiến độ thu thập địa chính thực tế", fontsize=12, color="#5b7470")
    measured = len(results)
    with_data = sum(bool(v) for v in results.values())
    side_x = .742
    fig.text(side_x, .83, f"{with_data:,}", fontsize=38, weight="bold", color="#00896f")
    fig.text(side_x, .795, "đoạn đường có bề rộng địa chính", fontsize=11)
    fig.text(side_x, .737, f"{measured:,} đã lấy mẫu", fontsize=17, weight="bold")
    fig.text(side_x, .704, f"{measured - with_data:,} chưa có mặt cắt hợp lệ", fontsize=11, color="#a46b2d")
    fig.text(side_x, .645, f"{len(state.get('cells_visited', []))} / {state.get('cells_target', 0)} ô đã tiếp cận", fontsize=14, weight="bold")
    fig.text(side_x, .612, f"{state.get('osm_cells_cached', 0):,} ô OSM đã lưu", fontsize=11)
    fig.text(side_x, .581, f"{len(campuses)} cơ sở HUTECH · quét 5 m trong {inner_radius:g} m", fontsize=10, color="#245985")
    for yy, color, text in ((.551, "#00896f", "Có bề rộng địa chính"), (.514, "#dc8d3a", "Đã hỏi, chưa có số liệu"),
                            (.477, "#c8d0cc", "OSM tham chiếu / chưa lấy mẫu")):
        fig.text(side_x, yy, "━", color=color, fontsize=18, weight="bold")
        fig.text(side_x + .025, yy + .002, text, fontsize=10)

    fig.text(side_x, .442, "◌  Vòng 2 km: lấy mẫu diện rộng" if inner_radius < 2000 else "◌  Vòng ưu tiên HUTECH (2 km)", fontsize=10, color="#245985")
    if locations:
        inset = fig.add_axes([.742, .19, .215, .20])
        inset.set_facecolor("#edf1ef")
        xs, ys = zip(*locations)
        inset.hexbin(xs, ys, gridsize=22, mincnt=1,
                     cmap=LinearSegmentedColormap.from_list("coverage", ["#d1e9de", "#00785e"]), linewidths=.2)
        inset.set_title("Mật độ các đoạn đã lấy mẫu", fontsize=9, loc="left")
        inset.tick_params(labelsize=7, length=0)
        for spine in inset.spines.values():
            spine.set_visible(False)
    stamp = state.get("updated_at", datetime.now(VN).isoformat())
    fig.text(.06, .064, f"Ảnh chụp tiến độ: {stamp}  ·  Mỗi kết quả là mẫu mặt cắt, không xác nhận toàn bộ chiều dài hẻm.", fontsize=9, color="#526b68")
    fig.text(.06, .041, "Nguồn: cổng Thông tin quy hoạch TP.HCM; © OpenStreetMap contributors (ODbL); ranh quận/huyện TNMT 2021.", fontsize=8, color="#708580")
    png = output.with_suffix(".png")
    fig.savefig(png, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    summary = {"generated_at": datetime.now(VN).isoformat(), "crawl_updated_at": stamp,
               "ways_measured": measured, "ways_with_data": with_data,
               "ways_drawn": len(green) + len(amber), "with_data_drawn": len(green),
               "cells_visited": len(state.get("cells_visited", [])),
               "osm_cells_cached": state.get("osm_cells_cached", 0),
               "png": str(png.relative_to(ROOT))}
    output.with_suffix(".json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    encoded = base64.b64encode(png.read_bytes()).decode()
    html = '<!doctype html><html lang="vi"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Dữ liệu hẻm TP.HCM</title><style>body{margin:0;background:#f6f8f7}img{display:block;width:100%;height:auto}</style><img alt="Bản đồ tiến độ thu thập bề rộng hẻm tại TP.HCM" src="data:image/png;base64,' + encoded + '"></html>'
    output.with_suffix(".html").write_text(html)
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
