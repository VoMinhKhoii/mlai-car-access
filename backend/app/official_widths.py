"""Read-only Official historical widths/planned ROW, separate from Clear Width.

A planning corridor is not a measured usable carriageway, nor a guaranteed upper
bound on today's width. No record in this module produces a Bound (D49).
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
import threading

from .config import CACHE

PATH = CACHE / 'live/official_widths.json'
_lock = threading.RLock()
_stamp, _data = None, {}


def snapshot():
    global _stamp, _data
    with _lock:
        try:
            stat = PATH.stat()
        except FileNotFoundError:
            _stamp, _data = None, {}
            return _stamp, _data
        stamp = stat.st_mtime_ns, stat.st_size
        if stamp != _stamp:
            try:
                data = json.loads(PATH.read_text(encoding='utf-8'))
                if (data.get('schema_version') != 1 or
                    data.get('semantics') != 'official_historical_and_planned_metadata_only' or
                    not isinstance(data.get('ways'), dict) or not isinstance(data.get('sources'), dict)):
                    raise ValueError('Unsupported Official metadata product')
                for wid, records in data['ways'].items():
                    if not str(wid).isdigit() or not isinstance(records, list):
                        raise ValueError('Invalid way records')
                    for r in records:
                        if (not isinstance(r, dict) or r.get('source_id') not in data['sources'] or
                            not isinstance(r.get('source_date'), str) or not isinstance(r.get('url'), str)):
                            raise ValueError('Missing source provenance')
                        for field in ('road_base_width_m', 'reported_road_width_m', 'planned_right_of_way_m'):
                            val = r.get(field)
                            if val is not None and (not isinstance(val,list) or len(val)!=2 or
                                not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in val) or
                                not 0 < val[0] <= val[1] <= 100):
                                raise ValueError('Invalid metadata width range')
            except (OSError, ValueError, TypeError, AttributeError):
                return _stamp, _data  # malformed replacement does not erase the last valid product
            _stamp, _data = stamp, data
        return _stamp, _data


def refresh(store):
    """Invalidate cached API serialization before plan's evidence-version check."""
    stamp, _ = snapshot()
    if stamp != getattr(store, '_official_width_stamp', None):
        store._official_width_stamp = stamp
        store.version += 1


def for_way(way_id):
    _, data = snapshot()
    out = []
    for row in data.get('ways', {}).get(str(way_id), []):
        source = data['sources'][row['source_id']]
        out.append({**deepcopy(row), 'tier':'Official', 'affects_clear_width':False,
                    'source_title':source['title'], 'reuse':source['reuse'],
                    'attribution':source.get('attribution',''),
                    'detail':'Số liệu nền đường / lộ giới theo hồ sơ có ngày; chưa xác minh hiện trạng thông thủy. '
                             'Không dùng để kết luận xe vào được hoặc không vào được.'})
    return out
