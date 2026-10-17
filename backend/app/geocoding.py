"""Shared API/agent geocoding: Goong -> local names -> polite Nominatim.

Only raw cached OSM elements are read here; resolving a name never builds/downloads
an area graph. Provider responses and the quota breaker survive process restarts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager

import httpx

from . import config
from .osm import haversine, strip_accents

log = logging.getLogger(__name__)
DB = config.STORE / 'geocoding.sqlite'
OSM_DIR = config.CACHE / 'osm'
INDEX_FILE = config.STORE / 'osm_name_index.json'
GOONG_BUDGET_S = 3.0
BREAKER_SECONDS = 30 * 60
_names = None
_index_lock = threading.Lock()
_curated = None
_nominatim_lock = threading.Lock()
_nominatim_at = 0.0


@contextmanager
def _db():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=4)
    db.execute('CREATE TABLE IF NOT EXISTS responses (provider TEXT, key TEXT, body TEXT, PRIMARY KEY(provider,key))')
    db.execute('CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value REAL)')
    try:
        with db:
            yield db
    finally:
        db.close()


def _key(params):
    params = dict(params)
    params.pop('api_key', None)
    for k in ('input', 'q'):
        if k in params:
            params[k] = strip_accents(str(params[k]))
    for k in ('location', 'latlng'):
        if k in params:
            params[k] = ','.join(f'{float(v):.3f}' for v in params[k].split(','))
    return json.dumps(params, sort_keys=True, ensure_ascii=False)


def block_goong(reason='OVER_RATE_LIMIT'):
    """Also usable to seed the breaker from a known, already observed quota error."""
    until = time.time() + BREAKER_SECONDS
    with _db() as db:
        db.execute("INSERT OR REPLACE INTO state VALUES ('goong_blocked_until', ?)", (until,))
    log.warning('Goong circuit OPEN for 30 minutes (%s), until %.0f', reason, until)
    return until


def goong_blocked_until():
    with _db() as db:
        row = db.execute("SELECT value FROM state WHERE key='goong_blocked_until'").fetchone()
    return row[0] if row else 0


def _bounded_get(url, *, timeout, **kwargs):
    # httpx timeouts bound each I/O phase, not wall time. Bound the caller as well.
    result = queue.Queue(maxsize=1)
    def run():
        try:
            result.put((True, httpx.get(url, timeout=timeout, **kwargs)))
        except Exception as exc:
            result.put((False, exc))
    threading.Thread(target=run, daemon=True).start()
    try:
        ok, value = result.get(timeout=timeout)
    except queue.Empty:
        raise httpx.TimeoutException('Geocoder deadline exceeded') from None
    if not ok:
        raise value
    return value


def goong(endpoint, params, deadline=None):
    """Disk cache first, then one shared quota gate. Never log credential URLs."""
    deadline = deadline if deadline is not None else time.monotonic() + GOONG_BUDGET_S
    key = endpoint + ':' + _key(params)
    with _db() as db:
        row = db.execute("SELECT body FROM responses WHERE provider='goong' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        # Serialize uncached calls across processes so concurrent requests see a 429.
        db.execute(f'PRAGMA busy_timeout={max(1, int((deadline - time.monotonic()) * 1000))}')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT value FROM state WHERE key='goong_blocked_until'").fetchone()
        if (row and row[0] > time.time()) or not config.GOONG_API_KEY or config.CACHED_ONLY:
            return {}
        row = db.execute("SELECT body FROM responses WHERE provider='goong' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {}
        response = _bounded_get('https://rsapi.goong.io/' + endpoint,
                                params=dict(params, api_key=config.GOONG_API_KEY), timeout=remaining)
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code == 429 or 'OVER_RATE_LIMIT' in response.text.upper():
            until = time.time() + BREAKER_SECONDS
            db.execute("INSERT OR REPLACE INTO state VALUES ('goong_blocked_until', ?)", (until,))
            log.warning('Goong circuit OPEN for 30 minutes (429/OVER_RATE_LIMIT), until %.0f', until)
            return {}
        response.raise_for_status()
        if not isinstance(body, dict) or body.get('status', 'OK') not in ('OK', 'ZERO_RESULTS'):
            return {}
        if any(k in body for k in ('predictions', 'result', 'results')):
            db.execute("INSERT OR REPLACE INTO responses VALUES ('goong', ?, ?)",
                       (key, json.dumps(body, ensure_ascii=False)))
        return body


def initialize_name_index():
    """Deduplicate all cached cells into named ways/POIs, without AreaGraph objects."""
    global _names
    with _index_lock:
        if _names is not None:
            return _names
        files = sorted(OSM_DIR.glob('*.json'))
        manifest = [(p.name, p.stat().st_size, p.stat().st_mtime_ns) for p in files]
        fingerprint = hashlib.sha256(json.dumps(manifest).encode()).hexdigest()
        try:
            saved = json.loads(INDEX_FILE.read_text())
            if saved.get('fingerprint') == fingerprint and saved.get('version') == 1:
                _names = saved['names']
                log.info('Loaded OSM name index: %d names from %d cached files', len(_names), len(files))
                return _names
        except (OSError, ValueError):
            pass
        names = {}
        for path in files:
            try:
                elements = json.loads(path.read_text())['elements']
            except (OSError, ValueError, KeyError, TypeError):
                continue
            nodes = {e['id']: [e['lat'], e['lon']] for e in elements if e.get('type') == 'node'}
            for e in elements:
                tags = e.get('tags', {})
                label = tags.get('name')
                is_way = e.get('type') == 'way' and tags.get('highway')
                is_market = tags.get('amenity') == 'marketplace'
                if not label or not (is_way or is_market):
                    continue
                identity = (e['type'], e['id'])
                if identity in names:
                    continue
                points = ([nodes[n] for n in e.get('nodes', []) if n in nodes]
                          if e['type'] == 'way' else [nodes[e['id']]])
                if not points:
                    continue
                la, lo = points[len(points) // 2]
                if not config.in_hcmc(la, lo):
                    continue
                precision = ('alley' if strip_accents(label).startswith('hem ') else 'street') if is_way else 'place'
                names[identity] = {'label': label, 'lat': la, 'lon': lo, 'way_id': e['id'],
                                   'precision': precision, 'points': points if is_way else [],
                                   'norm': strip_accents(label)}
        _names = list(names.values())
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(f'.{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps({'version': 1, 'fingerprint': fingerprint, 'names': _names}, ensure_ascii=False))
        tmp.replace(INDEX_FILE)
        log.info('Built OSM name index: %d names from %d cached files', len(_names), len(files))
        return _names


def configure_curated(presets, demo_places):
    global _curated
    places = [dict(p, source='Điểm nhà đã đối chiếu OSM', precision='house') for p in demo_places]
    # Resolve demo way midpoints directly from the shipped cache (no graph/network).
    data = json.loads((OSM_DIR / 'demo_binhthanh.json').read_text())['elements']
    nodes = {e['id']: (e['lat'], e['lon']) for e in data if e['type'] == 'node'}
    ways = {e['id']: e for e in data if e['type'] == 'way'}
    for p in presets:
        points = [nodes[n] for n in ways.get(p['way_id'], {}).get('nodes', []) if n in nodes]
        if points:
            la, lo = points[len(points) // 2]
            places.append({'label': p['label'], 'lat': la, 'lon': lo, 'source': 'Điểm demo / OSM', 'precision': 'alley'})
    campuses = config.ROOT / 'docs/eval/hutech-campuses.json'
    for p in json.loads(campuses.read_text())['campuses']:
        if 'lat' in p and 'lon' in p:
            places.append({'label': p['label'], 'lat': p['lat'], 'lon': p['lon'],
                           'aliases': [p['query'], p['name'], p['official_address'], 'HUTECH', *p.get('aliases', [])],
                           'source': 'HUTECH / địa chỉ đã đối chiếu', 'precision': 'place'})
    _curated = places


_GENERIC_PLACE_WORDS = {'cong', 'ty', 'cp', 'tnhh', 'co', 'phan', 'quan', 'hem', 'duong', 'so'}


def distinctive_tokens(text):
    # House numbers have their own exact/broad-address guard below.
    return {t for t in re.findall(r'[a-z0-9]+', strip_accents(str(text)))
            if t not in _GENERIC_PLACE_WORDS and not re.fullmatch(r'\d+[a-z]?', t)}


def distinctive_coverage(query, label):
    wanted = distinctive_tokens(query)
    # Do not combine “phạm” in a university name with “Vương” on its street.
    sections = re.split(r'[,;|\n]', strip_accents(str(label)))
    return max((len(wanted & set(re.findall(r'[a-z0-9]+', part))) / len(wanted)
                for part in sections), default=0.0) if wanted else 0.0


def fallback_matches(query, label):
    # A house-address query names its street before district/city qualifiers.
    # Require the distinctive street words together; never combine unrelated
    # words across a POI name and its address to manufacture a match.
    core = query.split(',', 1)[0] if re.match(r'(?:hem\s+)?\d', strip_accents(str(query))) else query
    return distinctive_coverage(core, label) >= .7


def _matches(query, label):
    q = re.sub(r'\bduong\s+', '', strip_accents(query).split(',')[0]).strip()
    name = re.sub(r'\bduong\s+', '', strip_accents(label)).strip()
    # Only an address query may accept a broader street name. A POI query such
    # as "Chợ Bến Thành" must not match an unrelated street ending in "Thành".
    house = re.match(r'(?:hem\s+)?\d', q)
    return bool(q and (q in name or (house and len(name.split()) >= 2 and
                                    re.search(r'(?<!\w)' + re.escape(name) + r'(?!\w)', q))))


def curated_search(q, near, limit=10):
    if _curated is None:
        from . import agent, main
        configure_curated(main.PRESETS, agent.DEMO_PLACES)
    curated = [dict(p) for p in _curated if any(_matches(q, label) for label in [p['label'], *p.get('aliases', [])])]
    for p in curated:
        p.pop('aliases', None)
    return sorted(curated, key=lambda p: haversine(*near, p['lat'], p['lon']))[:limit]


def local_search(q, near, limit=10):
    curated = curated_search(q, near, limit)
    if curated:
        return curated
    matches = [p for p in initialize_name_index() if _matches(q, p['norm']) and fallback_matches(q, p['label'])]
    matches.sort(key=lambda p: (strip_accents(q) != p['norm'], haversine(*near, p['lat'], p['lon'])))
    return [{k: v for k, v in p.items() if k not in ('points', 'norm')} | {'source': 'Tên địa điểm OpenStreetMap' if p['precision'] == 'place' else 'Tên đường/hẻm OpenStreetMap'}
            for p in matches[:limit * 4]]


def _nominatim_request(endpoint, params):
    global _nominatim_at
    key = endpoint + ':' + _key(params)
    with _db() as db:
        row = db.execute("SELECT body FROM responses WHERE provider='nominatim' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
    with _nominatim_lock, _db() as db:
        # Shared spacing across search/reverse and separate backend processes.
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT body FROM responses WHERE provider='nominatim' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        row = db.execute("SELECT value FROM state WHERE key='nominatim_at'").fetchone()
        time.sleep(max(0, 1.05 - (time.time() - (row[0] if row else 0))))
        _nominatim_at = time.monotonic()
        db.execute("INSERT OR REPLACE INTO state VALUES ('nominatim_at', ?)", (time.time(),))
        # Commit the request timestamp even if the HTTP request fails.
        db.commit()
        if config.CACHED_ONLY:
            raise ValueError('Nominatim cache miss in cached-only mode')
        response = httpx.get('https://nominatim.openstreetmap.org/' + endpoint, params=params,
                             headers={'User-Agent': 'NgoNgach/1.0 (HCMC address resolver; local demo)'}, timeout=3)
        response.raise_for_status()
        body = response.json()
        db.execute("INSERT OR REPLACE INTO responses VALUES ('nominatim', ?, ?)", (key, json.dumps(body, ensure_ascii=False)))
        return body


def nominatim(q):
    body = _nominatim_request('search', {'q': q, 'format': 'jsonv2', 'limit': 7, 'countrycodes': 'vn',
                                       'viewbox': '106.30,11.20,107.10,10.35', 'bounded': 1, 'addressdetails': 1})
    return [{'label': p['display_name'], 'lat': float(p['lat']), 'lon': float(p['lon']),
             'source': 'Nominatim / OpenStreetMap',
             'precision': 'house' if p.get('address', {}).get('house_number') else p.get('type', 'place')}
            for p in body if config.in_hcmc(float(p['lat']), float(p['lon'])) and fallback_matches(q, p['display_name'])]


def place_detail(place_id, deadline=None):
    body = goong('v2/place/detail', {'place_id': place_id}, deadline)
    p = body.get('result', {})
    loc = p.get('geometry', {}).get('location', {})
    if 'lat' in loc and 'lng' in loc and config.in_hcmc(loc['lat'], loc['lng']):
        return {'label': p.get('formatted_address') or p.get('name') or place_id,
                'lat': loc['lat'], 'lon': loc['lng'], 'source': 'Goong', 'precision': 'place'}
    return None


def resolve_id(place_id):
    try:
        result = place_detail(place_id)
        if result:
            return result
    except (httpx.HTTPError, ValueError):
        pass
    # Old tabs may still hold an autocomplete ID. Recover its cached description
    # when possible; an opaque, never-seen ID cannot be geocoded offline.
    with _db() as db:
        rows = db.execute("SELECT body FROM responses WHERE provider='goong' AND key LIKE 'v2/place/autocomplete:%'").fetchall()
    for row in rows:
        for p in json.loads(row[0]).get('predictions', []):
            if p.get('place_id') == place_id and p.get('description'):
                matches = local_search(p['description'], (10.8, 106.71))
                if matches:
                    return matches[0]
    return None


def resolve_place(query, origin=None, limit=3, nominatim_search=None, prefer_curated=False, select_nearest=True):
    """The agent's resolver, shared with autocomplete; retain house/ambiguity guards."""
    q = str(query).strip()
    if len(q) < 3:
        raise ValueError('Bạn cho biết địa chỉ hoặc địa danh cụ thể ở TP.HCM nhé?')
    norm = strip_accents(q)
    if re.search(r'\b(ha noi|hanoi|da nang|danang|can tho|hai phong|vung tau|binh duong|dong nai)\b', norm):
        return {'results': [], 'outside_service_area': True, 'note': 'Hiện chỉ có bằng chứng cho khu vực TP.HCM trước sáp nhập.'}
    near = origin or (10.7769, 106.7009)
    if prefer_curated:
        curated = curated_search(q, near, limit)
        if curated:
            return {'results': curated, 'requires_clarification': len(curated) > 1}
    resolved_key = _key({'q': q, 'location': f'{near[0]},{near[1]}'})
    with _db() as db:
        row = db.execute("SELECT body FROM responses WHERE provider='resolved_goong' AND key=?", (resolved_key,)).fetchone()
    cached = json.loads(row[0]) if row else []
    out, failures, broad = [], [], []
    deadline = time.monotonic() + GOONG_BUDGET_S
    try:
        out = cached
        body = {} if cached else goong('v2/place/autocomplete', {'input': q, 'location': f'{near[0]},{near[1]}', 'limit': 7}, deadline)
        for p in body.get('predictions', [])[:limit]:
            desc = p.get('description', '')
            if not any(s in strip_accents(desc) for s in ('ho chi minh', 'thu duc', 'sai gon')):
                continue
            if p.get('place_id'):
                resolved = place_detail(p['place_id'], deadline)
                if resolved:
                    out.append(resolved)
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        failures.append('Goong tạm không có dữ liệu')
    if out and not cached:
        with _db() as db:
            db.execute("INSERT OR REPLACE INTO responses VALUES ('resolved_goong', ?, ?)",
                       (resolved_key, json.dumps(out, ensure_ascii=False)))
    house = re.match(r'(?:hem\s+)?(\d+[a-z]?(?:/\d+[a-z]?)*)(?![a-z0-9/])', norm)
    def has_number(p, number):
        return re.search(r'(?<![a-z0-9/])' + re.escape(number) + r'(?![a-z0-9/])', strip_accents(p['label']))
    if house and out and not any(has_number(p, house[1]) for p in out):
        broad, out = out, []
    if not out:
        out = local_search(q, near, limit)
    if not out:
        try:
            out = [p for p in (nominatim_search or nominatim)(q) if fallback_matches(q, p['label'])]
        except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
            failures.append('Nominatim tạm không có dữ liệu')
    if not out:
        out = broad
    unique = []
    for p in out:
        if config.in_hcmc(p['lat'], p['lon']) and not any(
                strip_accents(p['label']) == strip_accents(x['label']) or
                (p['source'] == x['source'] and (p['source'] == 'Goong' or 'Nominatim' in p['source']) and
                 haversine(p['lat'], p['lon'], x['lat'], x['lon']) < 25) for x in unique):
            unique.append(p)
    out = unique[:limit]
    requested = re.search(r'(?<![a-z0-9])\d+[a-z]?(?:/\d+[a-z]?)*', norm)
    if requested:
        exact = [p for p in out if has_number(p, requested[0])]
        if len(exact) == 1:
            out = exact
    result = {'results': out, 'requires_clarification': len(out) > 1, 'source_warnings': failures}
    if len(out) > 1 and origin and select_nearest:
        out.sort(key=lambda p: haversine(*origin, p['lat'], p['lon']))
        result['selection_reason'] = 'Chọn điểm gần vị trí xuất phát nhất; cần xác nhận nếu khác chi nhánh bạn định tới.'
        result['requires_clarification'] = False
    if house and out and not has_number(out[0], house[1]):
        result['requires_clarification'] = True
        result['note'] = 'Chỉ tìm thấy đường hoặc hẻm lớn, chưa xác minh được số nhà nhánh. Bạn gửi ghim vị trí nhé?'
    return result


def nearest_way(lat, lon):
    best, distance = None, 250.0
    # Distance to segments, not way midpoints (long streets can span many cells).
    scale_x, scale_y = 111195 * math.cos(math.radians(lat)), 111195
    for p in initialize_name_index():
        points = p['points']
        if len(points) < 2:
            continue
        for a, b in zip(points, points[1:]):
            ax, ay = (a[1] - lon) * scale_x, (a[0] - lat) * scale_y
            bx, by = (b[1] - lon) * scale_x, (b[0] - lat) * scale_y
            if min(ax, bx) > distance or max(ax, bx) < -distance or min(ay, by) > distance or max(ay, by) < -distance:
                continue
            dx, dy = bx - ax, by - ay
            t = max(0, min(1, -(ax * dx + ay * dy) / (dx * dx + dy * dy))) if dx or dy else 0
            d = math.hypot(ax + t * dx, ay + t * dy)
            if d < distance:
                best, distance = p, d
    if best:
        return {'label': best['label'], 'lat': lat, 'lon': lon, 'source': 'Tên đường/hẻm OpenStreetMap',
                'precision': best['precision'], 'distance_m': round(distance, 1)}
    return None


def reverse(lat, lon):
    try:
        body = goong('Geocode', {'latlng': f'{lat},{lon}'})
        if body.get('results'):
            return {'label': body['results'][0]['formatted_address'], 'lat': lat, 'lon': lon, 'source': 'Goong'}
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        pass
    local = nearest_way(lat, lon)
    if local:
        return local
    try:
        p = _nominatim_request('reverse', {'lat': round(lat, 5), 'lon': round(lon, 5), 'format': 'jsonv2', 'zoom': 18})
        if p.get('display_name') and config.in_hcmc(float(p['lat']), float(p['lon'])):
            return {'label': p['display_name'], 'lat': lat, 'lon': lon, 'source': 'Nominatim / OpenStreetMap'}
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        pass
    return {'label': f'{lat:.5f}, {lon:.5f}', 'lat': lat, 'lon': lon, 'source': 'toạ độ'}
