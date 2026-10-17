"""Shared API/agent geocoding: Goong -> local names -> polite Nominatim.

Only raw cached OSM elements are read here; resolving a name never builds/downloads
an area graph. Provider responses and the quota breaker survive process restarts.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import queue
import re
import sqlite3
import threading
import time
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

import httpx

from . import config
from .osm import haversine, strip_accents as _strip_accents


def strip_accents(value):
    return _strip_accents(str(value).replace('Ð', 'Đ').replace('ð', 'đ'))

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


def _goong_keys():
    """API keys only. Key 10 is a tiles credential, never a geocoder key.

    GOONG_KEY_NAMES restricts a verification process to an explicitly allowed key.
    Values and credential URLs must never appear in logs or persisted state.
    """
    allowed = os.environ.get('GOONG_KEY_NAMES')
    names = ([n.strip() for n in allowed.split(',')] if allowed is not None else
             ['GOONG_API_KEY', *[f'GOONG_API_KEY_{i}' for i in range(1, 10)]])
    values = []
    for name in names:
        if not re.fullmatch(r'GOONG_API_KEY(?:_[1-9])?', name):
            continue
        value = config.GOONG_API_KEY if name == 'GOONG_API_KEY' else os.environ.get(name, '')
        if value and value not in values:
            values.append(value)
    return values


def _breaker_key(api_key):
    return 'goong_key_' + hashlib.sha256(api_key.encode()).hexdigest()[:20]


def block_goong(reason='OVER_RATE_LIMIT', api_key=None, *, daily=False):
    """Persist a per-key breaker; daily quota errors stay parked until tomorrow."""
    until = time.time() + BREAKER_SECONDS
    if daily:
        now = datetime.now(timezone(timedelta(hours=7)))
        until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo).timestamp()
    with _db() as db:
        for credential in ([api_key] if api_key else _goong_keys()):
            db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (_breaker_key(credential), until))
    log.warning('Goong key circuit open (%s)', 'daily quota' if daily else 'temporary failure')
    return until


def goong_blocked_until(api_key=None):
    keys = [api_key] if api_key else _goong_keys()
    with _db() as db:
        states = dict(db.execute("SELECT key, value FROM state WHERE key LIKE 'goong_key_%'"))
    return min((states.get(_breaker_key(k), 0) for k in keys), default=0)


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
    """Disk cache, then bounded key rotation with cross-process quota state."""
    deadline = deadline if deadline is not None else time.monotonic() + GOONG_BUDGET_S
    key = endpoint + ':' + _key(params)
    with _db() as db:
        row = db.execute("SELECT body FROM responses WHERE provider='goong' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        keys = _goong_keys()
        if not keys or config.CACHED_ONLY:
            return {}
        db.execute(f'PRAGMA busy_timeout={max(1, int((deadline - time.monotonic()) * 1000))}')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT body FROM responses WHERE provider='goong' AND key=?", (key,)).fetchone()
        if row:
            return json.loads(row[0])
        states = dict(db.execute('SELECT key, value FROM state'))
        cursor = int(states.get('goong_cursor', 0)) % len(keys)
        ordered = keys[cursor:] + keys[:cursor]
        for credential in ordered:
            if states.get(_breaker_key(credential), 0) > time.time():
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return {}
            try:
                response = _bounded_get('https://rsapi.goong.io/' + endpoint,
                                        params=dict(params, api_key=credential), timeout=remaining)
            except httpx.HTTPError:
                # Commit already observed quota/auth failures before returning.
                return {}
            try:
                body = response.json()
            except ValueError:
                body = {}
            status = str(body.get('status', 'OK')).upper() if isinstance(body, dict) else ''
            unauthorized = response.status_code in (401, 403) or status in ('REQUEST_DENIED', 'UNAUTHORIZED', 'INVALID_API_KEY')
            quota = response.status_code == 429 or status in ('OVER_RATE_LIMIT', 'OVER_QUERY_LIMIT', 'RESOURCE_EXHAUSTED')
            if unauthorized or quota:
                until = time.time() + BREAKER_SECONDS
                if response.status_code == 429:
                    now = datetime.now(timezone(timedelta(hours=7)))
                    until = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=now.tzinfo).timestamp()
                db.execute('INSERT OR REPLACE INTO state VALUES (?, ?)', (_breaker_key(credential), until))
                continue
            if response.is_error:
                return {}
            if not isinstance(body, dict) or status not in ('OK', 'ZERO_RESULTS'):
                return {}
            db.execute("INSERT OR REPLACE INTO state VALUES ('goong_cursor', ?)", ((keys.index(credential) + 1) % len(keys),))
            if any(k in body for k in ('predictions', 'result', 'results')):
                db.execute("INSERT OR REPLACE INTO responses VALUES ('goong', ?, ?)",
                           (key, json.dumps(body, ensure_ascii=False)))
            return body
    return {}


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
            if saved.get('fingerprint') == fingerprint and saved.get('version') == 2:
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
            if not isinstance(elements, list):
                continue
            nodes = {e['id']: [e['lat'], e['lon']] for e in elements
                     if isinstance(e, dict) and e.get('type') == 'node' and
                     all(isinstance(e.get(k), (int, float)) and math.isfinite(e[k]) for k in ('id', 'lat', 'lon'))}
            for e in elements:
                if not isinstance(e, dict) or 'id' not in e:
                    continue
                tags = e.get('tags') or {}
                if not isinstance(tags, dict):
                    continue
                label = tags.get('name')
                is_way = e.get('type') == 'way' and tags.get('highway')
                is_market = any(tags.get(k) for k in ('amenity', 'shop', 'office', 'tourism', 'leisure'))
                if not isinstance(label, str) or not label or e.get('type') not in ('node', 'way') or not (is_way or is_market):
                    continue
                identity = (e['type'], e['id'])
                if identity in names:
                    continue
                if e['type'] == 'way':
                    refs = e.get('nodes') or []
                    points = [nodes[n] for n in refs if n in nodes]
                    if len(points) != len(refs):
                        log.debug('Name index skips missing vertices for OSM way %s', e['id'])
                else:
                    points = [nodes[e['id']]] if e['id'] in nodes else []
                if not points:
                    log.debug('Name index skips OSM %s %s without cached coordinates', e['type'], e['id'])
                    continue
                la, lo = points[len(points) // 2]
                if not config.in_hcmc(la, lo):
                    continue
                precision = ('alley' if re.match(r'^(hem|ngo|kiet|ngach|alley)\s', strip_accents(label)) else 'street') if is_way else 'place'
                names[identity] = {'label': label, 'lat': la, 'lon': lo, 'way_id': e['id'],
                                   'precision': precision, 'points': points if is_way else [],
                                   'norm': strip_accents(label)}
        _names = list(names.values())
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = INDEX_FILE.with_suffix(f'.{threading.get_ident()}.tmp')
        tmp.write_text(json.dumps({'version': 2, 'fingerprint': fingerprint, 'names': _names}, ensure_ascii=False))
        tmp.replace(INDEX_FILE)
        log.info('Built OSM name index: %d names from %d cached files', len(_names), len(files))
        return _names


def configure_curated(presets, demo_places):
    global _curated
    places = [dict(p, source='House location checked against OSM', precision='house') for p in demo_places]
    # Resolve demo way midpoints directly from the shipped cache (no graph/network).
    data = json.loads((OSM_DIR / 'demo_binhthanh.json').read_text())['elements']
    nodes = {e['id']: (e['lat'], e['lon']) for e in data if e['type'] == 'node'}
    ways = {e['id']: e for e in data if e['type'] == 'way'}
    for p in presets:
        points = [nodes[n] for n in ways.get(p['way_id'], {}).get('nodes', []) if n in nodes]
        if points:
            la, lo = points[len(points) // 2]
            places.append({'label': p['label'], 'lat': la, 'lon': lo, 'source': 'Demo location / OSM', 'precision': 'alley'})
    campuses = config.ROOT / 'docs/eval/hutech-campuses.json'
    for p in json.loads(campuses.read_text())['campuses']:
        if 'lat' in p and 'lon' in p:
            places.append({'label': p['label'], 'lat': p['lat'], 'lon': p['lon'],
                           'aliases': [p['query'], p['name'], p['official_address'], 'HUTECH', *p.get('aliases', [])],
                           'source': 'HUTECH / verified address', 'precision': 'place'})
    _curated = places


_GENERIC_PLACE_WORDS = {'cong', 'ty', 'cp', 'tnhh', 'co', 'phan', 'quan', 'hem', 'duong', 'so',
                        'ngo', 'kiet', 'ngach', 'alley', 'lane', 'street', 'road'}
_CHAIN = re.compile(r'^(?:hem\s+)?(\d+[a-z0-9]*(?:/\d+[a-z0-9]*)*)(?![a-z0-9/])')


def address_parts(text):
    core = strip_accents(str(text)).split(',', 1)[0].strip()
    core = re.sub(r'\s*/\s*', '/', core)
    core = re.sub(r'^(?:ngo|kiet|ngach|alley|lane)\s+', 'hem ', core)
    core = re.split(r'\s+(?:phuong|p\.|quan|q\.)\s+', core)[0]
    match = _CHAIN.match(core)
    if not match:
        return None, core
    street = re.sub(r'\b(?:duong|street|road|rd)\b', '', core[match.end():]).strip(' .-')
    return match[1], re.sub(r'\s+', ' ', street)


def distinctive_tokens(text):
    return {t for t in re.findall(r'[a-z0-9]+', strip_accents(str(text)))
            if t not in _GENERIC_PLACE_WORDS and not re.fullmatch(r'\d+[a-z]?', t)}


def distinctive_coverage(query, label):
    wanted = distinctive_tokens(query)
    if not wanted and re.match(r'^(?:duong|street|road)\s+(?:so\s+)?\d+\b', strip_accents(str(query))):
        return float(_matches(query, label))
    # Distinctive words must occur together in the POI or street label.
    sections = re.split(r'[,;|\n]', strip_accents(str(label)))
    return max((len(wanted & set(re.findall(r'[a-z0-9]+', part))) / len(wanted)
                for part in sections), default=0.0) if wanted else 0.0


def _street_matches(query, label, *, typo=False):
    road_words = {'duong', 'street', 'road', 'rd'}
    q = ' '.join(t for t in query.split() if t not in road_words)
    n = ' '.join(t for t in label.split() if t not in road_words)
    # A dropped last character in Đường is harmless when the remaining street matches exactly.
    q = re.sub(r'^duon\s+', '', q)
    if q == n:
        return True
    if typo and len(q.split()) >= 2 and len(q.split()) == len(n.split()):
        exact = len(set(q.split()) & set(n.split()))
        return exact >= len(q.split()) - 1 and SequenceMatcher(None, q, n).ratio() >= .85
    return False


def fallback_matches(query, label):
    chain, street = address_parts(query)
    if chain:
        other_chain, other_street = address_parts(label)
        return _street_matches(street, other_street, typo=bool(other_chain))
    return distinctive_coverage(str(query).split(',', 1)[0], label) >= .7


def _matches(query, label):
    chain, street = address_parts(query)
    other_chain, other_street = address_parts(label)
    if chain:
        if not _street_matches(street, other_street, typo=bool(other_chain)):
            return False
        return not other_chain or chain == other_chain or chain.startswith(other_chain + '/')
    q = re.sub(r'\bduong\s+', '', strip_accents(query).split(',')[0]).strip()
    name = re.sub(r'\bduong\s+', '', strip_accents(label)).strip()
    return bool(q and re.search(r'(?<!\w)' + re.escape(q) + r'(?!\w)', name))


def curated_search(q, near, limit=10):
    if _curated is None:
        from . import agent, main
        configure_curated(main.PRESETS, agent.DEMO_PLACES)
    curated = [dict(p) for p in _curated if any(_matches(q, label) for label in [p['label'], *p.get('aliases', [])])]
    for p in curated:
        p.pop('aliases', None)
    return sorted(curated, key=lambda p: haversine(*near, p['lat'], p['lon']))[:limit]


_local_index = None
_local_chains = {}


def local_search(q, near, limit=10):
    global _local_index, _local_chains
    names = initialize_name_index()
    chain, street = address_parts(q)
    if _local_index is not names:
        chains = {}
        for p in names:
            number, road = address_parts(p['label'])
            if number:
                chains.setdefault(number, []).append((p, road))
        _local_chains, _local_index = chains, names
    if chain:
        # Longest known prefix wins, never discard /41 in favour of bare 137.
        matches = []
        parts = chain.split('/')
        for depth in range(len(parts), 0, -1):
            number = '/'.join(parts[:depth])
            matches = [p for p,road in _local_chains.get(number, []) if _street_matches(street, road, typo=True)]
            if matches:
                break
        if not matches:
            curated = curated_search(q, near, limit)
            if curated:
                return curated
            matches = [p for p in names if p['precision']=='street' and _matches(q, p['norm'])]
    else:
        curated = curated_search(q, near, limit)
        if curated:
            return curated
        matches = [p for p in names if _matches(q, p['norm']) and fallback_matches(q, p['label'])]
    matches.sort(key=lambda p: (strip_accents(q) != p['norm'], haversine(*near, p['lat'], p['lon'])))
    return [{k: v for k, v in p.items() if k not in ('points', 'norm')} | {'source': 'OpenStreetMap place name' if p['precision'] == 'place' else 'OpenStreetMap street/alley name'}
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
        name, address = p.get('name', ''), p.get('formatted_address', '')
        label = address or name or place_id
        if name and strip_accents(name) not in strip_accents(label):
            label = name + ', ' + label
        return {'label': label,
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
        raise ValueError('Please enter a specific address or place in Ho Chi Minh City.')
    norm = strip_accents(q)
    if re.search(r'\b(ha noi|hanoi|da nang|danang|can tho|hai phong|vung tau|binh duong|dong nai)\b', norm):
        return {'results': [], 'outside_service_area': True, 'note': 'Evidence currently covers Ho Chi Minh City before the boundary expansion.'}
    near = origin or (10.7769, 106.7009)
    chain, street = address_parts(q)
    if prefer_curated:
        curated = curated_search(q, near, limit)
        if chain:
            curated = [p for p in curated if address_parts(p['label'])[0] == chain]
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
            if not fallback_matches(q, desc):
                continue
            if p.get('place_id'):
                resolved = place_detail(p['place_id'], deadline)
                if resolved:
                    out.append(resolved)
    except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
        failures.append('Goong data is temporarily unavailable')
    if out and not cached:
        with _db() as db:
            db.execute("INSERT OR REPLACE INTO responses VALUES ('resolved_goong', ?, ?)",
                       (resolved_key, json.dumps(out, ensure_ascii=False)))
    house = _CHAIN.match(re.sub(r'^(?:ngo|kiet|ngach|alley|lane)\s+', 'hem ', norm))
    out = [p for p in out if fallback_matches(q, p['label'])]
    def has_number(p, number):
        return re.search(r'(?<![a-z0-9/])' + re.escape(number) + r'(?![a-z0-9/])', strip_accents(p['label']))
    if house and out and not any(has_number(p, house[1]) for p in out):
        broad, out = out, []
    if not out:
        out = local_search(q, near, limit)
    # Preserve an actual named alley when a provider merely echoes a deep house
    # address. A provider address label alone does not pin the last house number.
    needs_parent = chain and '/' in chain and (not out or all(
        not address_parts(p['label'])[0] or (p.get('source') == 'Goong' and
        not strip_accents(p['label']).startswith('hem ') and chain.count('/') >= 2) for p in out))
    if needs_parent:
        original = out
        parts = chain.split('/')
        for depth in range(len(parts)-1, 0, -1):
            parent = '/'.join(parts[:depth])
            parent_query = f'Hẻm {parent} {street}'.strip()
            parent_matches = local_search(parent_query, near, limit)
            parent_matches = [p for p in parent_matches if address_parts(p['label'])[0] == parent]
            if not parent_matches and time.monotonic() < deadline:
                try:
                    body = goong('v2/place/autocomplete', {'input': parent_query, 'location': f'{near[0]},{near[1]}', 'limit': 7}, deadline)
                    for prediction in body.get('predictions', []):
                        desc = prediction.get('description', '')
                        if not strip_accents(desc).startswith('hem ') or address_parts(desc)[0] != parent or not fallback_matches(parent_query, desc):
                            continue
                        p = place_detail(prediction['place_id'], deadline)
                        if p and address_parts(p['label'])[0] == parent:
                            p['precision'] = 'alley'
                            parent_matches.append(p)
                            break
                except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
                    pass
            if parent_matches:
                out = parent_matches
                break
        else:
            out = original
    if not out:
        try:
            out = [p for p in (nominatim_search or nominatim)(q) if fallback_matches(q, p['label'])]
        except (httpx.HTTPError, ValueError, KeyError, sqlite3.Error):
            failures.append('Nominatim data is temporarily unavailable')
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
    requested = re.search(r'(?<![a-z0-9])\d+[a-z0-9]*(?:/\d+[a-z0-9]*)*', norm)
    if requested:
        exact = [p for p in out if has_number(p, requested[0])]
        if len(exact) == 1:
            out = exact
    result = {'results': out, 'requires_clarification': len(out) > 1, 'source_warnings': failures}
    if len(out) > 1 and origin and select_nearest:
        out.sort(key=lambda p: haversine(*origin, p['lat'], p['lon']))
        result['selection_reason'] = 'Selected the closest match to your starting point; check that this is the branch you intended.'
        result['requires_clarification'] = False
    if house and out and not has_number(out[0], house[1]):
        parent, _ = address_parts(out[0]['label'])
        if parent and chain and chain.startswith(parent + '/'):
            result['house_unpinned'] = True
            result['requested_address'] = q
            result['selection_reason'] = (f"Located at {out[0]['label']}; house {chain.split('/')[-1]} is not pinned "
                                          f"within address {chain}. The estimate applies to the mapped alley; the final branch to the house has not been checked.")
            result['note'] = result['selection_reason']
        else:
            result['requires_clarification'] = True
            result['note'] = 'Only the street was found; the house is not pinned. Please tap the destination on the map.'
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
        return {'label': best['label'], 'lat': lat, 'lon': lon, 'source': 'OpenStreetMap street/alley name',
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
    return {'label': f'{lat:.5f}, {lon:.5f}', 'lat': lat, 'lon': lon, 'source': 'coordinates'}
