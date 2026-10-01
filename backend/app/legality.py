"""Stop Legality from traffic law, road signs and local ordinances (Q6, Q7).

We show the law, never advice: every Stop Rule carries its citation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .config import TWO_LANE_MIN_M
from .evidence import WidthRange
from .osm import AreaGraph, Way, haversine

LAW = "Luật Trật tự, an toàn giao thông đường bộ 2024 (Luật 36/2024/QH15), Điều 18 khoản 4"


@dataclass
class StopRule:
    code: str
    status: str   # Permitted | Restricted | Prohibited | Unverified
    text: str
    citation: str

    def to_json(self) -> dict:
        return {"code": self.code, "status": self.status, "text": self.text, "citation": self.citation}


ORDER = {"Permitted": 0, "Unverified": 1, "Restricted": 2, "Prohibited": 3}


def _sign_rules(g: AreaGraph, w: Way, lat: float, lon: float, intent: str, when: datetime) -> list[StopRule]:
    out = []
    for nid, tags in g.node_tags.items():
        sign = tags.get("traffic_sign", "")
        if not sign or nid not in g.nodes:
            continue
        la, lo = g.nodes[nid]
        if haversine(lat, lon, la, lo) > 40 or w.id not in g.node_ways.get(nid, {w.id}):
            continue
        s = sign.upper().replace(" ", "")
        if "P.130" in s or "P130" in s:
            out.append(StopRule("sign-P130", "Prohibited", "Biển P.130 cấm dừng và đỗ xe", "QCVN 41:2024/BGTVT, biển P.130"))
        elif intent == "park" and ("P.131A" in s or "P131A" in s):
            out.append(StopRule("sign-P131a", "Prohibited", "Biển P.131a cấm đỗ xe", "QCVN 41:2024/BGTVT, biển P.131a"))
        elif intent == "park" and ("P.131B" in s or "P131B" in s) and when.day % 2 == 1:
            out.append(StopRule("sign-P131b", "Prohibited", "Biển P.131b cấm đỗ xe ngày lẻ (hôm nay là ngày lẻ)", "QCVN 41:2024/BGTVT, biển P.131b"))
        elif intent == "park" and ("P.131C" in s or "P131C" in s) and when.day % 2 == 0:
            out.append(StopRule("sign-P131c", "Prohibited", "Biển P.131c cấm đỗ xe ngày chẵn (hôm nay là ngày chẵn)", "QCVN 41:2024/BGTVT, biển P.131c"))
    return out


def _osm_parking_tags(w: Way, intent: str) -> list[StopRule]:
    out = []
    vals = [v for k, v in w.tags.items() if k.startswith("parking:") and not k.endswith(":reason")]
    if any(v in ("no_stopping", "no_standing") for v in vals):
        out.append(StopRule("osm-no-stopping", "Prohibited", "Đoạn đường được đánh dấu cấm dừng xe", "Dữ liệu biển báo OSM"))
    elif intent == "park" and any(v in ("no", "no_parking") for v in vals):
        out.append(StopRule("osm-no-parking", "Prohibited", "Đoạn đường được đánh dấu cấm đỗ xe", "Dữ liệu biển báo OSM"))
    return out


def legality_on_street(g: AreaGraph, w: Way, wr: WidthRange, lat: float, lon: float, dist_to_junction: float,
                       intent: str, when: datetime, paid_street: dict | None = None) -> tuple[str, list[StopRule]]:
    rules: list[StopRule] = []
    if dist_to_junction < 5.0:
        rules.append(StopRule("junction-5m", "Prohibited", "Trong phạm vi 5 m tính từ mép đường giao nhau", LAW))
    for nid, tags in g.node_tags.items():
        hw = tags.get("highway")
        if hw not in ("crossing", "bus_stop"):
            continue
        la, lo = g.nodes[nid]
        d = haversine(lat, lon, la, lo)
        if hw == "crossing" and d < 6:
            rules.append(StopRule("crosswalk", "Prohibited", "Trên phần đường dành cho người đi bộ qua đường", LAW))
        if hw == "bus_stop" and d < 20:
            rules.append(StopRule("bus-stop", "Prohibited", "Tại nơi dừng của xe buýt", LAW))
    tunnel = w.tags.get("tunnel", "no") not in ("no", "") or w.tags.get("covered") == "yes" \
        or w.name.lower().startswith(("hầm", "cầu "))
    if w.tags.get("bridge", "no") not in ("no", "") or tunnel:
        rules.append(StopRule("bridge", "Prohibited", "Trên cầu, trong hầm đường bộ", LAW))
    if w.highway.endswith("_link"):
        rules.append(StopRule("ramp", "Prohibited", "Trên đường dẫn lên, xuống cầu vượt / nút giao", LAW))
    if w.highway in ("motorway", "trunk"):
        rules.append(StopRule("expressway", "Prohibited", "Đường trục chính tốc độ cao, không dừng đỗ tùy tiện", LAW))
    rules += _sign_rules(g, w, lat, lon, intent, when) + _osm_parking_tags(w, intent)

    # Single-lane roadway (most hẻm): Park is strict, Pickup/Drop-off is Restricted (Q7).
    if wr.hi < TWO_LANE_MIN_M:
        if intent == "park":
            rules.append(StopRule("single-lane", "Prohibited",
                                  "Phần đường chỉ đủ một làn xe cơ giới: không được đỗ", LAW))
        else:
            rules.append(StopRule("single-lane", "Restricted",
                                  "Không dừng, đỗ xe nơi phần đường chỉ đủ một làn xe cơ giới", LAW))
    elif wr.lo < TWO_LANE_MIN_M:
        rules.append(StopRule("lane-unknown", "Unverified",
                              f"Chưa đủ bằng chứng hẻm rộng hơn {TWO_LANE_MIN_M:g} m (đủ hai làn xe)", LAW))

    if intent == "park" and paid_street:
        rules.append(StopRule("vetc-street", "Permitted",
                              f"Điểm đỗ ô tô dưới lòng đường có thu phí ({paid_street.get('fee_note') or 'thanh toán VETC'})",
                              "Danh sách 20 tuyến đường thu phí đỗ xe ô tô, TP.HCM (VETC)"))
    elif intent == "park" and w.kind == "main" and w.highway in ("primary", "secondary"):
        rules.append(StopRule("main-road-signs", "Unverified",
                              "Đường chính: chưa có dữ liệu biển cấm đỗ tại đoạn này", "Dữ liệu biển báo chưa đầy đủ"))

    status = max((r.status for r in rules), key=lambda s: ORDER[s], default="Permitted")
    if status == "Permitted" and not rules:
        rules.append(StopRule("no-rule", "Permitted", "Không có quy định cấm dừng/đỗ được biết tại vị trí này", LAW))
    return status, rules


def legality_for_lot(lot: dict, intent: str) -> tuple[str, list[StopRule]]:
    access = lot.get("access", "")
    note = "Bãi đỗ xe" + (" dành cho khách" if access == "customers" else "")
    if lot.get("source") == "VETC":
        note = "Bãi đỗ có thanh toán điện tử VETC"
    return "Permitted", [StopRule("lot", "Permitted", note, lot.get("source_label", "Bãi đỗ ngoài đường"))]
