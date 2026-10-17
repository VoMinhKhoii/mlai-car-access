"""Small evidence adapter: field CSV semantics and cross-process hot reload.

No network access. Legacy seven-column tape measurements retain their meaning.
"""
from __future__ import annotations

import csv
import math


def stamp(path):
    try:
        s = path.stat()
        return s.st_mtime_ns, s.st_size
    except FileNotFoundError:
        return None


def current_stamp():
    from . import evidence
    from . import crowd
    return stamp(evidence.FIELD_FILE), stamp(evidence.CONFIRM_FILE), stamp(crowd.DB)


def refresh(store):
    if current_stamp() != getattr(store, '_field_stamp', None):
        store.reload()


def load_into(store):
    from . import evidence
    store._field_stamp = current_stamp()
    if not evidence.FIELD_FILE.exists():
        return
    with evidence.FIELD_FILE.open(encoding='utf-8', newline='') as handle:
        for row in csv.DictReader(handle):
            try:
                width = float(row['width_m'])
                wid = int(row['osm_way_id'])
                if not math.isfinite(width) or not .5 <= width <= 15 or wid <= 0:
                    continue
            except (ValueError, TypeError, KeyError):
                continue
            method = row.get('method') or 'tape'  # legacy rows were tape-measured
            if method not in ('tape', 'lidar', 'pacing'):
                continue  # an unknown method must never acquire Measured trust
            tier, pad = ('Observed', .5) if method == 'pacing' else ('Measured', .1)
            complete = not row.get('submission_id') or row.get('coverage_complete', '').lower() == 'true'
            lo = max(.5, width-pad) if complete else 0.
            method_vi = {'tape': 'thước dây', 'lidar': 'LiDAR', 'pacing': 'bước chân'}[method]
            detail = f"{width:g} m; {method_vi}; {row.get('measured_by', '')}. "
            detail += 'Đã kiểm tra cả đoạn và đo chỗ hẹp nhất.' if complete else 'Mẫu tại một vị trí, chưa chứng nhận toàn đoạn.'
            if row.get('note'):
                detail += ' ' + row['note']
            store._add(evidence.Bound(lo, width+pad, tier,
                       row.get('source') or f'Nhóm đo hiện trường ({method_vi})', detail,
                       observed_on=row.get('date', ''), url=row.get('photo_url', ''),
                       coverage_complete=complete, measurement_schema='field-clear-width-v1',
                       estimate_m=width), wid)
