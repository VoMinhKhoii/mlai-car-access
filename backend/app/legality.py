"""Stop Legality from traffic law, road signs and local ordinances (Q6, Q7).

We show the law, never advice: every Stop Rule carries its citation.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

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


def supports_legal_lane_count(wr: WidthRange) -> bool:
    """Only real clear-width evidence may establish a legal lane count."""
    return wr.decisive_clearance and wr.width_basis in ("measured_clear_width", "observed_clear_width")


def _sign_rules(g: AreaGraph, w: Way, lat: float, lon: float, intent: str, when: datetime) -> list[StopRule]:
    out = []
    for nid, tags in g.node_tags.items():
        sign = tags.get("traffic_sign", "")
        if not sign or nid not in g.nodes:
            continue
        if w.id not in g.node_ways.get(nid, {w.id}):
            continue
        la, lo = g.nodes[nid]
        if haversine(lat, lon, la, lo) > 40:
            continue
        s = sign.upper().replace(" ", "")
        if "P.130" in s or "P130" in s:
            out.append(StopRule("sign-P130", "Prohibited", "Sign P.130 prohibits stopping and parking", "QCVN 41:2024/BGTVT, biển P.130"))
        elif intent == "park" and ("P.131A" in s or "P131A" in s):
            out.append(StopRule("sign-P131a", "Prohibited", "Sign P.131a prohibits parking", "QCVN 41:2024/BGTVT, biển P.131a"))
        elif intent == "park" and ("P.131B" in s or "P131B" in s) and when.day % 2 == 1:
            out.append(StopRule("sign-P131b", "Prohibited", "Sign P.131b prohibits parking on odd dates (today is odd)", "QCVN 41:2024/BGTVT, biển P.131b"))
        elif intent == "park" and ("P.131C" in s or "P131C" in s) and when.day % 2 == 0:
            out.append(StopRule("sign-P131c", "Prohibited", "Sign P.131c prohibits parking on even dates (today is even)", "QCVN 41:2024/BGTVT, biển P.131c"))
    return out


def _osm_parking_tags(w: Way, intent: str) -> list[StopRule]:
    out = []
    vals = [v for k, v in w.tags.items() if k.startswith("parking:") and not k.endswith(":reason")]
    if any(v in ("no_stopping", "no_standing") for v in vals):
        out.append(StopRule("osm-no-stopping", "Prohibited", "Road segment marked no stopping", "OSM sign data"))
    elif intent == "park" and any(v in ("no", "no_parking") for v in vals):
        out.append(StopRule("osm-no-parking", "Prohibited", "Road segment marked no parking", "OSM sign data"))
    return out


def legality_on_street(g: AreaGraph, w: Way, wr: WidthRange, lat: float, lon: float,
                       dist_to_junction: float | None, intent: str, when: datetime,
                       paid_street: dict | None = None) -> tuple[str, list[StopRule]]:
    rules: list[StopRule] = []
    if dist_to_junction is None:
        rules.append(StopRule("junction-5m", "Unverified",
                              "Junction edge is unknown; cannot check the 5 m setback", LAW))
    elif dist_to_junction < 5.0:
        rules.append(StopRule("junction-5m", "Prohibited", "Within 5 m of the intersecting road edge", LAW))
    for nid, tags in g.node_tags.items():
        hw = tags.get("highway")
        if hw not in ("crossing", "bus_stop"):
            continue
        la, lo = g.nodes[nid]
        d = haversine(lat, lon, la, lo)
        if hw == "crossing" and d < 6:
            rules.append(StopRule("crosswalk", "Prohibited", "On a pedestrian crossing", LAW))
        if hw == "bus_stop" and d < 20:
            rules.append(StopRule("bus-stop", "Prohibited", "At a bus stop", LAW))
    tunnel = w.tags.get("tunnel", "no") not in ("no", "") or w.tags.get("covered") == "yes" \
        or w.name.lower().startswith(("hầm", "cầu "))
    if w.tags.get("bridge", "no") not in ("no", "") or tunnel:
        rules.append(StopRule("bridge", "Prohibited", "On a bridge or inside a road tunnel", LAW))
    if w.highway.endswith("_link"):
        rules.append(StopRule("ramp", "Prohibited", "On an approach or exit ramp to a flyover or junction", LAW))
    if w.highway in ("motorway", "trunk"):
        rules.append(StopRule("expressway", "Prohibited", "High-speed arterial road; stopping and parking restricted", LAW))
    rules += _sign_rules(g, w, lat, lon, intent, when) + _osm_parking_tags(w, intent)

    # A measured, complete clear-width range is required to infer legal lane count.
    if not supports_legal_lane_count(wr):
        rules.append(StopRule("lane-unknown", "Unverified",
                              "Insufficient clear-width measurements to determine the number of motor-vehicle lanes", LAW))
    elif wr.hi < TWO_LANE_MIN_M:
        if intent == "park":
            rules.append(StopRule("single-lane", "Prohibited",
                                  "Roadway fits only one motor-vehicle lane: parking prohibited", LAW))
        else:
            rules.append(StopRule("single-lane", "Restricted",
                                  "No stopping or parking where the roadway fits only one motor-vehicle lane", LAW))
    elif wr.lo < TWO_LANE_MIN_M:
        rules.append(StopRule("lane-unknown", "Unverified",
                              f"Insufficient evidence that the alley exceeds {TWO_LANE_MIN_M:g} m (two lanes)", LAW))

    if intent == "park" and paid_street:
        rules.append(StopRule("vetc-street", "Permitted",
                              f"Paid on-street parking ({paid_street.get('fee_note') or 'VETC payment'})",
                              "List of 20 paid on-street parking roads, HCMC (VETC)"))
    elif intent == "park" and w.kind == "main" and w.highway in ("primary", "secondary"):
        rules.append(StopRule("main-road-signs", "Unverified",
                              "Main road: no parking-sign data for this segment", "Incomplete sign data"))

    status = max((rule.status for rule in rules), key=lambda value: ORDER[value], default="Permitted")
    if status == "Permitted" and not rules:
        status = "Unverified"
        rules.append(StopRule("no-rule", "Unverified",
                              "Incomplete sign data at this location", "Incomplete sign data"))
    return status, rules


def legality_over_window(g: AreaGraph, w: Way, wr: WidthRange, lat: float, lon: float,
                         dist_to_junction: float | None, intent: str, arrive: datetime, depart: datetime,
                         paid_street: dict | None = None) -> tuple[str, list[StopRule]]:
    """Evaluate the full Dwell Window, including every midnight where parity signs change."""
    times = {arrive, depart}
    cursor = arrive.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    while cursor < depart:
        times.add(cursor)
        cursor += timedelta(days=1)
    by_key: dict[tuple[str, str, str], StopRule] = {}
    status = "Permitted"
    multi_day = (depart.date() > arrive.date())
    for when in sorted(times):
        current, rules = legality_on_street(g, w, wr, lat, lon, dist_to_junction, intent, when, paid_street)
        if ORDER[current] > ORDER[status]:
            status = current
        for rule in rules:
            # For parity rules (P.131b/c) across multiple days, suffix the day
            if multi_day and rule.code in ("sign-P131b", "sign-P131c"):
                day_label = f" (on {when.strftime('%a %d/%m')})"
                rule = StopRule(rule.code, rule.status, rule.text + day_label, rule.citation)
            by_key[(rule.code, rule.status, rule.text)] = rule
    return status, list(by_key.values())


def legality_for_lot(lot: dict, intent: str) -> tuple[str, list[StopRule]]:
    access = lot.get("access", "")
    note = "Car park" + (" for customers" if access == "customers" else "")
    if lot.get("source") == "VETC":
        note = "Car park with VETC electronic payment"
    return "Permitted", [StopRule("lot", "Permitted", note, lot.get("source_label", "Off-street car park"))]
