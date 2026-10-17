"""Read-only geometry checks for cached automatic cadastral cuts.

Numerical outliers alone are not discarded: a genuine local constriction can
be the narrowest observation. Geometry-invalid cuts supply no upper bound.
"""
from __future__ import annotations

import math
import statistics

from shapely.geometry import LineString, Point

from .osm import DRIVABLE, haversine


def assess(g, way, cuts):
    coords = [g.nodes[n] for n in way.nodes]
    lat0, lon0 = coords[0]
    kx, ky = 111320 * math.cos(math.radians(lat0)), 110540
    local = lambda lat, lon: ((lon-lon0)*kx, (lat-lat0)*ky)
    xy = [local(*p) for p in coords]
    line = LineString(xy)
    junctions = [g.nodes[n] for n in way.nodes if len({m for ei, m in g.walk_adj.get(n, [])
                  if g.ways[g.edges[ei].way_id].highway in DRIVABLE}) >= 3]
    corners, along = [], 0.0
    for a, b, c in zip(xy, xy[1:], xy[2:]):
        along += math.dist(a, b)
        ax, ay, bx, by = b[0]-a[0], b[1]-a[1], c[0]-b[0], c[1]-b[1]
        norm = math.hypot(ax, ay)*math.hypot(bx, by)
        if norm and (ax*bx+ay*by)/norm < math.cos(math.radians(15)):
            corners.append(along)
    accepted, rejected = [], []
    for cut in cuts:
        reason = None
        if cut.get('lat') is not None and cut.get('lon') is not None:
            point = Point(local(cut['lat'], cut['lon']))
            offset = line.project(point)
            if line.distance(point) > 1.5:
                reason = 'off_centerline_over_1_5m'
            elif any(haversine(cut['lat'], cut['lon'], *p) < 5 for p in junctions):
                reason = 'within_5m_of_junction'
            elif any(abs(offset-d) < 5 for d in corners):
                reason = 'within_5m_of_bend_over_15deg'
        (rejected if reason else accepted).append({**cut, 'rejection_reason': reason} if reason else cut)
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
            if any(haversine(cut['lat'], cut['lon'], c['lat'], c['lon']) < 1 for c in independent):
                continue
        independent.append(cut)
    outlier = bool(widths and len(widths) >= 3 and median-narrow > max(.6, 3*1.4826*mad))
    return accepted, {'accepted_cuts': len(accepted), 'rejected_cuts': rejected,
                      'bottleneck_support': len(independent), 'median_m': median, 'mad_m': mad,
                      'isolated_low_outlier': outlier}
