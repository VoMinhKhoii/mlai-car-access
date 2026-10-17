"""Stop Legality from traffic law, road signs and local ordinances (Q6, Q7).

We show the law, never advice: every Stop Rule carries its citation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from ...config import TWO_LANE_MIN_M
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


def _index(g):
    """Immutable graph-local feature index; no complete tag scan per candidate."""
    if hasattr(g, '_legal_index'):
        return g._legal_index
    signs, cells = {}, {}
    for nid, tags in g.node_tags.items():
        if nid not in g.nodes:
            continue
        if tags.get('traffic_sign'):
            for wid in g.node_ways.get(nid, ()):
                signs.setdefault(wid, []).append((nid,tags))
        if tags.get('highway') in ('crossing','bus_stop'):
            la,lo=g.nodes[nid]
            cells.setdefault((int(la*110540//50),int(lo*109400//50)),[]).append((nid,tags))
    neighbors={}
    for e in g.edges:
        if g.ways[e.way_id].drivable:
            neighbors.setdefault(e.u,set()).add(e.v)
            neighbors.setdefault(e.v,set()).add(e.u)
    g._legal_index=(signs,cells,neighbors)
    return g._legal_index


def junction_distance(g, edge, offset, wrs):
    """Along-road distance to the intersecting roadway edge, through shape nodes."""
    import heapq
    _,_,neighbors=_index(g)
    incident={}
    # Built once per graph; uses physical edges rather than OSM way counts.
    if not hasattr(g,'_legal_incident'):
        for e in g.edges:
            if g.ways[e.way_id].drivable:
                incident.setdefault(e.u,[]).append(e)
                incident.setdefault(e.v,[]).append(e)
        g._legal_incident=incident
    incident=g._legal_incident
    pq=[(offset,edge.u,edge.idx),(edge.length-offset,edge.v,edge.idx)];heapq.heapify(pq)
    seen={};best=math.inf
    while pq:
        d,n,previous=heapq.heappop(pq)
        if d>=seen.get(n,math.inf) or d>40:
            continue
        seen[n]=d
        if len(neighbors.get(n,()))>=3:
            incoming=g.edges[previous]
            before=incoming.v if incoming.u==n else incoming.u
            lat,lon=g.nodes[n]
            ax,ay=(g.nodes[before][1]-lon)*math.cos(math.radians(lat)),g.nodes[before][0]-lat
            across=[]
            for arm in incident.get(n,()):
                after=arm.v if arm.u==n else arm.u
                bx,by=(g.nodes[after][1]-lon)*math.cos(math.radians(lat)),g.nodes[after][0]-lat
                den=math.hypot(ax,ay)*math.hypot(bx,by)
                if den and abs((ax*bx+ay*by)/den)<math.cos(math.radians(15)) and arm.way_id in wrs:
                    across.append(wrs[arm.way_id].lo)
            best=min(best,max(0,d-max(across,default=0)/2))
        for e in incident.get(n,()):
            other=e.v if e.u==n else e.u
            heapq.heappush(pq,(d+e.length,other,e.idx))
    return best


def _sign_rules(g: AreaGraph, w: Way, lat: float, lon: float, intent: str, when: datetime) -> list[StopRule]:
    out = []
    for nid, tags in _index(g)[0].get(w.id, ()):
        sign = tags.get("traffic_sign", "")
        if not sign or nid not in g.nodes:
            continue
        la, lo = g.nodes[nid]
        # Association is required; an unattached nearby sign has no invented scope.
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
    supported = {'parking:both', 'parking:both:restriction', 'parking:lane:both', 'parking:condition:both'}
    vals = [v for k, v in w.tags.items() if k in supported]
    side_vals = [v for k,v in w.tags.items() if k in {'parking:left:restriction','parking:right:restriction',
                 'parking:condition:left','parking:condition:right','parking:lane:left','parking:lane:right'}]
    if any(v in ('no','no_parking','no_stopping','no_standing') for v in side_vals):
        out.append(StopRule('curb-side-unknown','Unverified','Có hạn chế theo phía lề; chưa xác minh phía dừng/đỗ','Dữ liệu OSM theo phía lề'))
    if any(v in ("no_stopping", "no_standing") for v in vals):
        out.append(StopRule("osm-no-stopping", "Prohibited", "Đoạn đường được đánh dấu cấm dừng xe", "Dữ liệu biển báo OSM"))
    elif intent == "park" and any(v in ("no", "no_parking") for v in vals):
        out.append(StopRule("osm-no-parking", "Prohibited", "Đoạn đường được đánh dấu cấm đỗ xe", "Dữ liệu biển báo OSM"))
    return out


def legality_on_street(g: AreaGraph, w: Way, wr: WidthRange, lat: float, lon: float, dist_to_junction: float,
                       intent: str, when: datetime, paid_street: dict | None = None,
                       until: datetime | None = None) -> tuple[str, list[StopRule]]:
    rules: list[StopRule] = []
    if dist_to_junction < 5.0:
        rules.append(StopRule("junction-5m", "Prohibited", "Trong phạm vi 5 m tính từ mép đường giao nhau", LAW))
    cells=_index(g)[1]
    y,x=int(lat*110540//50),int(lon*109400//50)
    nearby=[item for dy in (-1,0,1) for dx in (-1,0,1) for item in cells.get((y+dy,x+dx),())]
    for nid, tags in nearby:
        hw = tags.get("highway")
        if hw not in ("crossing", "bus_stop"):
            continue
        la, lo = g.nodes[nid]
        d = haversine(lat, lon, la, lo)
        if hw == "crossing" and d < 6:
            rules.append(StopRule("crosswalk", "Prohibited", "Trên phần đường dành cho người đi bộ qua đường", LAW))
        if hw == "bus_stop" and d < 20:
            rules.append(StopRule("bus-stop", "Prohibited", "Tại nơi dừng của xe buýt", LAW))
    tunnel = w.tags.get("tunnel", "no") not in ("no", "")
    if w.tags.get("bridge", "no") not in ("no", "") or tunnel:
        rules.append(StopRule("bridge", "Prohibited", "Trên cầu, trong hầm đường bộ", LAW))
    if w.highway.endswith("_link"):
        rules.append(StopRule("ramp", "Prohibited", "Trên đường dẫn lên, xuống cầu vượt / nút giao", LAW))
    if w.highway == "motorway":
        rules.append(StopRule("expressway", "Prohibited", "Đường trục chính tốc độ cao, không dừng đỗ tùy tiện", LAW))
    times=[when]
    if until is not None:
        t=when.replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
        while t<=until:
            times.append(t);t+=timedelta(days=1)
        times.append(until)
    for t in times:
        for rule in _sign_rules(g,w,lat,lon,intent,t):
            if rule not in rules:
                rules.append(rule)
    rules += _osm_parking_tags(w, intent)

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

    # A missing sign/curb survey is not positive authorization (D38).
    if not rules:
        rules.append(StopRule("no-rule", "Unverified",
                              "Không thấy quy định cấm đã biết trong dữ liệu hiện có; chưa xác minh đầy đủ biển báo và vị trí dừng/đỗ",
                              "Dữ liệu pháp lý tại vị trí chưa đầy đủ"))
    status = max((r.status for r in rules), key=lambda s: ORDER[s], default="Unverified")
    return status, rules


def legality_for_lot(lot: dict, intent: str) -> tuple[str, list[StopRule]]:
    access = lot.get("access", "")
    note = "Bãi đỗ xe" + (" dành cho khách" if access == "customers" else "")
    if lot.get("source") == "VETC":
        note = "Bãi đỗ có thanh toán điện tử VETC"
    authorized = lot.get("authorization_verified") is True and access not in ("private", "no", "customers")
    status = "Permitted" if authorized else "Unverified"
    if not authorized:
        note += ": chưa xác minh quyền vào bãi và giờ hoạt động"
    return status, [StopRule("lot", status, note, lot.get("source_label", "Bãi đỗ ngoài đường"))]
