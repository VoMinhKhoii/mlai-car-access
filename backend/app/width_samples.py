"""Read-only quality checks for automatic parcel cross-sections.

Reject impossible frontage geometry, not credible constrictions. MAD identifies
an uncorroborated low tail for confidence review; it cannot erase an obstacle.
No check here upgrades a parcel gap into physical clear-width evidence.
"""
from __future__ import annotations

import math
import statistics

from shapely.geometry import LineString, Point

from .osm import DRIVABLE, haversine


def assess(g, way, cuts):
    coords = [g.nodes[n] for n in way.nodes if n in g.nodes]
    lat0, lon0 = coords[0] if coords else g.center
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    local = lambda lat, lon: ((lon-lon0)*kx, (lat-lat0)*ky)
    xy = [local(*p) for p in coords]
    line = LineString(xy) if len(xy) >= 2 and any(p != xy[0] for p in xy[1:]) else None
    junctions = [g.nodes[n] for n in way.nodes if n in g.nodes and len({m for ei, m in g.walk_adj.get(n, [])
                  if g.ways[g.edges[ei].way_id].highway in DRIVABLE}) >= 3]
    corners, along = [], 0.0
    for a, b, c in zip(xy, xy[1:], xy[2:]):
        along += math.dist(a, b)
        ax, ay, bx, by = b[0]-a[0], b[1]-a[1], c[0]-b[0], c[1]-b[1]
        norm = math.hypot(ax, ay)*math.hypot(bx, by)
        if norm and (ax*bx+ay*by)/norm < math.cos(math.radians(15)):
            corners.append(along)
    accepted, rejected, locations = [], [], []
    for cut in cuts:
        reason = None
        located = line is not None and cut.get('lat') is not None and cut.get('lon') is not None
        if located:
            point = Point(local(cut['lat'], cut['lon']))
            offset = line.project(point)
            if line.distance(point) > 1.5:
                reason = 'off_centerline_over_1_5m'
            elif any(haversine(cut['lat'], cut['lon'], *p) < 5 for p in junctions):
                reason = 'within_5m_of_junction'
            elif any(abs(offset-d) < 5 for d in corners):
                reason = 'within_5m_of_bend_over_15deg'
        (rejected if reason else accepted).append({**cut, 'rejection_reason': reason} if reason else cut)
        if not reason:
            locations.append(located)
    widths = [c['width_m'] for c in accepted]
    median = statistics.median(widths) if widths else None
    mad = statistics.median(abs(v-median) for v in widths) if widths else None
    narrow = min(widths) if widths else None
    # 0.6 m is twice the existing ±0.3 m measurement allowance, not a
    # calibrated probability. Equal-location duplicates cannot corroborate.
    supporters = [c for c in accepted if c['width_m'] <= narrow + .6] if widths else []
    independent = []
    for cut in supporters:
        if cut.get('lat') is not None and cut.get('lon') is not None:
            if any(c.get('lat') is not None and c.get('lon') is not None and
                   haversine(cut['lat'], cut['lon'], c['lat'], c['lon']) < 1 for c in independent):
                continue
        elif cut.get('at_m') is not None:
            if any(c.get('at_m') is not None and abs(cut['at_m']-c['at_m']) < 1 for c in independent):
                continue
        else:
            continue  # repeated unlocated numbers cannot corroborate a bottleneck
        independent.append(cut)
    outlier = bool(len(widths) >= 3 and len(independent) < 2 and
                   median-narrow > max(.6, 3*1.4826*mad))
    return accepted, {'accepted_cuts': len(accepted), 'rejected_cuts': rejected,
                      'bottleneck_support': len(independent), 'median_m': median, 'mad_m': mad,
                      'isolated_low_outlier': outlier,
                      'geometry_checked': bool(locations and all(locations)),
                      'sample_min_m': narrow, 'sample_max_m': max(widths) if widths else None,
                      'confidence_note': 'isolated_low_cut_requires_confirmation' if outlier else None}
