"""Bounded Goong recovery of cached HCMC records; no portal, LLM or OSM HTTP.

python3 pipelines/geocode_unmatched.py prepare
python3 pipelines/geocode_unmatched.py run --network
python3 pipelines/geocode_unmatched.py run  # replay cache only, zero API calls

The conservative default is the documented Free plan: 1,000 requests/day.
Fewer than 50% (499) may be reserved across ALL runs in a rolling 24 hours.
Responses (including errors) are cached by endpoint + query, without credentials.
Validation runs first. Unprocessed records remain in the audit with a reason.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import fcntl
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
sys.path.insert(0, str(ROOT / 'pipelines'))
import httpx
from common import fold, load_env_local, norm_name, USER_AGENT
from listings_city import (atomic, read, inventory, all_ads, districts, graph_for,
                           listing_bounds, aggregate, cadastral, validation, digest, now)
from extract_regex import extract, Gazetteer, _chain_from
from official_bulk import metric_line
from shapely.geometry import Point

RAW = ROOT / 'data/raw/geocode_unmatched'
ACCEPTED = ROOT / 'data/processed/geocode_unmatched.json'
REPORT = ROOT / 'docs/eval/geocode-unmatched.json'
QUOTA_URL = 'https://help.goong.io/kb/qa/question/nhung-cau-hoi-thuong-gap-trong-qua-trinh-tich-hop-goong-map-api/'
API = 'https://rsapi.goong.io'


class StopGoong(RuntimeError):
    pass


class Goong:
    """Crash-safe reservations, one process, <= 4 request starts/s, no retries."""
    def __init__(self, directory=RAW, network=False, max_calls=499, daily_quota=1000,
                 already_used=0, key=None, client=None, delay=.3):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = (self.directory / 'api.lock').open('a+')
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise StopGoong('another_geocode_process_active') from None
        self.db = sqlite3.connect(self.directory / 'calls.sqlite')
        self.db.execute('CREATE TABLE IF NOT EXISTS calls (at REAL, endpoint TEXT, query_hash TEXT, status TEXT)')
        self.db.commit()
        self.network, self.max_calls = network, max(0, max_calls)
        self.quota, self.already_used = daily_quota, max(0, already_used)
        self.cap = max(0, math.ceil(daily_quota * .5) - 1 - self.already_used)
        self.key = key if key is not None else load_env_local().get('GOONG_API_KEY', '')
        self.client = client or httpx.Client(timeout=15, headers={'User-Agent': USER_AGENT})
        self.delay = max(.25, delay)
        self.calls = self.cache_hits = 0
        self.stop_reason = None

    def close(self):
        self.client.close()
        self.db.close()
        self.lock.close()

    def usage(self):
        return self.db.execute('SELECT COUNT(*) FROM calls WHERE at>?', (time.time()-86400,)).fetchone()[0]

    def get(self, endpoint, **params):
        if endpoint not in ('/v2/geocode', '/v2/place/autocomplete', '/v2/place/detail'):
            raise ValueError('unsupported_endpoint')
        if any('key' in k.lower() for k in params):
            raise ValueError('credentials_must_not_be_query_identity')
        identity = json.dumps([endpoint, params], ensure_ascii=False, sort_keys=True)
        query_hash = hashlib.sha256(identity.encode()).hexdigest()
        path = self.directory / 'responses' / f'{query_hash}.json'
        cached = read(path)
        if cached:
            self.cache_hits += 1
            if cached.get('http_status') in (403, 429) or cached.get('blocked'):
                self.stop_reason = f"goong_blocked_{cached.get('http_status')}"
                raise StopGoong(self.stop_reason)
            if cached.get('http_status') is None or cached['http_status'] >= 400:
                raise StopGoong(f"cached_goong_http_{cached.get('http_status')}")
            return cached.get('body', {})
        if self.stop_reason:
            raise StopGoong(self.stop_reason)
        if not self.network:
            raise StopGoong('cache_miss_network_disabled')
        blocked = read(self.directory / 'STOP.json')
        if blocked:
            self.stop_reason = blocked['reason']
            raise StopGoong(self.stop_reason)
        if not self.key:
            raise StopGoong('missing_goong_api_key')
        if self.calls >= self.max_calls or self.usage() >= self.cap:
            self.stop_reason = 'daily_budget_exhausted'
            raise StopGoong(self.stop_reason)
        last = self.db.execute('SELECT MAX(at) FROM calls').fetchone()[0] or 0
        time.sleep(max(0, self.delay - (time.time() - last)))
        # Reserve before sending. A crash or timeout consumes budget conservatively.
        with self.db:
            cur = self.db.execute('INSERT INTO calls VALUES (?,?,?,?)', (time.time(), endpoint, query_hash, 'reserved'))
            rowid = cur.lastrowid
        self.calls += 1
        status, body, reason = None, {}, None
        try:
            response = self.client.get(API + endpoint, params={**params, 'api_key': self.key})
            status = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = {'error': 'non_json_response'}
            if not isinstance(body, dict):
                body = {'error': 'non_object_response'}
        except httpx.HTTPError as exc:
            # Do not persist exception strings or request URLs (they contain the key).
            reason = type(exc).__name__
            body = {'error': reason}
        # Some providers echo request URLs in error bodies. Remove our key recursively.
        body = json.loads(json.dumps(body, ensure_ascii=False).replace(self.key, '[REDACTED]'))
        api_status = str(body.get('status', '')).upper()
        blocked = status in (403, 429) or api_status in ('OVER_QUERY_LIMIT', 'REQUEST_DENIED', 'PERMISSION_DENIED')
        atomic(path, {'endpoint': endpoint, 'query': params, 'fetched_at': now(),
                      'http_status': status, 'body': body, 'blocked': blocked})
        with self.db:
            self.db.execute('UPDATE calls SET status=? WHERE rowid=?', (str(status or reason), rowid))
        if blocked:
            self.stop_reason = f'goong_blocked_{status}_{api_status}'
            atomic(self.directory / 'STOP.json', {'reason': self.stop_reason, 'at': now()})
            raise StopGoong(self.stop_reason)
        if status is None or status >= 400:
            self.stop_reason = f'goong_http_{status or reason}'
            raise StopGoong(self.stop_reason)
        return body


def chain(name):
    """Exact alley number chain + street, with accents/punctuation normalized.

    Never drop a child number, change a digit, fuzzy-match a street, or infer a
    street for a source containing only a number. Spaced PDF syllables normalize
    only for comparison, without inventing a corrected Vietnamese query.
    """
    value = re.sub(r'\s+', ' ', fold(name)).strip()
    m = re.fullmatch(r'(?:hem|ngo|kiet)\s+(?:so\s+)?(\d+[a-z]?(?:/\d+[a-z]?)*)\s+(?:duong\s+|d\.\s*)?(.+)', value)
    if not m or re.search(r'[,;():]|\s[-–]\s|\b(?:den|nhanh|cuoi)\b', m[2]):
        return None
    street = re.sub(r'[^a-z0-9]', '', re.sub(r'^so\s+', '', m[2]))
    return (m[1], street) if street else None


def strict_name(name, expected):
    """Returned address must explicitly contain the exact number + street.

    Limit matching to a comma-separated address component; a street name from
    one component cannot be combined with a number from a ward or district.
    """
    if not expected:
        return False
    number, street = expected
    for component in re.split(r'[,;\n]', fold(name)):
        for m in re.finditer(r'(?<![a-z0-9/])(\d+[a-z]?(?:/\d+[a-z]?)*)\s+(?:duong\s+|d\.\s*)?(.+)', component):
            if m[1] != number:
                continue
            suffix = re.sub(r'[^a-z0-9]', '', re.sub(r'^so\s+', '', m[2].strip()))
            if suffix == street:
                return True
    return False


def old_district(centre):
    if not centre:
        return ''
    from city_scope import districts as boundaries
    p = Point(centre[1], centre[0])
    return next((d['name'].title() for d in boundaries() if d['prepared'].covers(p)), '')


def address_queries(entry, name):
    ward = entry.get('ward') or ''
    if ward and not re.match(r'(?i)^(phường|xã|đặc khu)\b', ward):
        ward = 'Phường ' + ward.title()
    district = entry.get('district') or ''
    # Preserve source-date geography first; old district is an explicit fallback
    # when Goong's post-2025 ward names no longer match the source.
    suffixes = [[ward, district], [district], [ward]]
    return list(dict.fromkeys(', '.join(v for v in [name, *parts, 'Thành phố Hồ Chí Minh'] if v)
                              for parts in suffixes))


class SnapIndex:
    def __init__(self, rows):
        self.by_chain = defaultdict(list)
        for r in rows.values():
            tags = r['tags']
            if tags.get('highway') not in ('service', 'residential', 'living_street', 'unclassified', 'road'):
                continue
            c = chain(tags.get('name', ''))
            if not c or len(r.get('coords', [])) < 2:
                continue
            self.by_chain[c].append((r, metric_line(r['coords'])))

    def snap(self, lat, lon, expected):
        # The graph and this predicate restrict the product to existing urban
        # HCMC caches, not the entire enlarged post-2025 municipality.
        from city_scope import contains
        if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
                and not isinstance(lat, bool) and not isinstance(lon, bool)
                and math.isfinite(lat + lon) and contains(lat, lon)):
            return {'reason': 'outside_cached_urban_hcmc_scope'}
        p = Point(lon * 111320 * math.cos(math.radians(10.82)), lat * 111320)
        candidates = sorted((line.distance(p), int(r['id']), r) for r, line in self.by_chain.get(expected, []))
        if not candidates:
            return {'reason': 'no_same_chain_eligible_osm_way'}
        distance, wid, r = candidates[0]
        if distance > 40:
            return {'reason': 'snap_over_40m', 'nearest_m': round(distance, 3)}
        second = candidates[1][0] if len(candidates) > 1 else None
        if second is not None and second - distance < 15:
            return {'reason': 'snap_margin_under_15m', 'nearest_m': round(distance, 3), 'second_m': round(second, 3)}
        return {'reason': 'accepted', 'way_id': wid, 'osm_name': r['tags'].get('name'),
                'distance_m': round(distance, 3), 'second_distance_m': round(second, 3) if second is not None else None,
                'lat': lat, 'lon': lon, 'provenance': f'Goong geocode + snap, distance {distance:.1f} m'}


def locate(entry, api, index, validation_only=False):
    attempts, accepted = [], {}
    names = [n for n in entry['names'] if chain(n)]
    if not names:
        return {'reason': 'no_explicit_alley_number_and_street', 'attempts': []}
    for name in names:
        queries = address_queries(entry, name)
        if validation_only:
            queries = queries[:1]
        for query in queries:
            try:
                doc = api.get('/v2/geocode', address=query, has_deprecated_administrative_unit='true')
            except StopGoong as exc:
                attempts.append({'query': query, 'reason': str(exc)})
                return {'reason': str(exc), 'attempts': attempts}
            results = doc.get('results', [])
            # Geocode already supplies coordinates. Autocomplete + detail is a
            # bounded fallback, and only details for strict-name predictions.
            if not results and not validation_only:
                try:
                    suggestions = api.get('/v2/place/autocomplete', input=query, limit=3)
                    results = []
                    for suggestion in suggestions.get('predictions', [])[:3]:
                        if not strict_name(suggestion.get('description', ''), chain(name)):
                            continue
                        pid = suggestion.get('place_id')
                        if pid:
                            result = api.get('/v2/place/detail', place_id=pid).get('result', {})
                            results.append(result)
                except StopGoong as exc:
                    attempts.append({'query': query, 'reason': str(exc)})
                    return {'reason': str(exc), 'attempts': attempts}
            reasons = []
            for result in results:
                returned = [result.get('name', ''), result.get('formatted_address', '')]
                address = ', '.join(returned)
                if 'ho chi minh' not in fold(address):
                    reasons.append('returned_address_not_hcmc')
                    continue
                if not any(strict_name(label, chain(name)) for label in returned):
                    reasons.append('returned_name_missing_exact_number_street')
                    continue
                location = result.get('geometry', {}).get('location', {})
                snap = index.snap(location.get('lat'), location.get('lng'), chain(name))
                reasons.append(snap['reason'])
                if snap['reason'] == 'accepted':
                    accepted[snap['way_id']] = {**snap, 'query': query, 'returned_address': address,
                                                'source_chain': name, 'place_id': result.get('place_id')}
            attempts.append({'query': query, 'geocoded': True, 'reasons': reasons or ['no_goong_results']})
            if accepted:
                break
        if validation_only:
            break
    if len(accepted) == 1:
        return {**next(iter(accepted.values())), 'attempts': attempts}
    return {'reason': 'multiple_goong_way_candidates' if accepted else 'no_accepted_result', 'attempts': attempts}


def source_entries(inv):
    wards = read(ROOT / 'data/raw/qd4582_wards.json')
    fire = read(ROOT / 'data/raw/listings_city/fire_audit.json').get('items', [])
    entries, known = [], []
    for r in fire:
        e = {'id': f"fire:{r['item']}", 'source': 'fire', 'names': [r['name']], 'ward': r.get('ward'),
             'district': old_district(wards.get(r.get('ward'))), 'source_date': '2026-07-24', 'record': r}
        (known if r['way_ids'] else entries).append(e)
    for r in read(ROOT / 'data/official/alley_widths_q9_2009.json').get('records', []):
        if r.get('way_ids'):
            continue
        entries.append({'id': r['id'], 'source': 'q9', 'names': r.get('candidate_names', []),
                        'ward': r['ward'], 'district': 'Quận 9', 'source_date': r['source_date'], 'record': r})
    # Reproduce deterministic extraction and the original no-coordinate gate.
    # Ambiguous width/access texts remain excluded even if location is resolved.
    g, by_name = graph_for(inv['ways'])
    gaz = Gazetteer({w.name for w in g.ways.values() if w.name and not w.is_alley})
    ads, _ = all_ads()
    district_names = {d['id']: d['name'] for d in districts()}
    for a in ads:
        lat, lon = a.get('latitude'), a.get('longitude')
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in (lat, lon)):
            continue
        street = a.get('street_name') or ''
        text = f"{a.get('subject', '')}\n{a.get('body', '')}\n{street}"
        ex = extract(text, street or None, gaz)
        if not ex['access_claim'] and any(v in (2, '2') for v in a.get('pty_characteristics') or []):
            ex['access_claim'] = 'xe_hoi'
        if a.get('source') == 'alonhadat' and a.get('road_front_m') and ('hem' in fold(a.get('kind', '')) or '/' in a.get('street_number', '')):
            if isinstance(a['road_front_m'], (int, float)) and 1 <= a['road_front_m'] <= 15:
                ex['width_m'] = a['road_front_m']
        if ex.get('width_m') is None and not ex.get('access_claim'):
            continue
        ambiguous = len(ex['width_mentions_m']) > 1 or (len(set(ex['access_claims_all']) - {'xe_hoi', 'xe_hoi_tranh'}) > 0 and 'xe_hoi' in ex['access_claims_all'])
        names = ex['alley_chain']
        num = str(a.get('street_number') or '').strip().strip('/')
        if not names and '/' in num and street:
            names = _chain_from(num, re.sub(r'^Đường\s+', '', street))
        candidates = next((by_name[norm_name(n)] for n in reversed(names) if norm_name(n) in by_name), [])
        if not ambiguous and len(candidates) == 1:
            continue
        bound, conflict = listing_bounds(ex, 'alley_chain')
        posted = a.get('posted_at', '')
        if a.get('list_time'):
            posted = datetime.fromtimestamp(a['list_time']/1000, timezone.utc).isoformat()[:10]
        rs = {'listing_id': str(a['ad_id']), 'url': a.get('url') or f"https://www.nhatot.com/{a.get('list_id')}.htm",
              'source': a['source'], 'posted_at': str(posted)[:10], 'bounds': list(bound),
              'width_m': ex.get('width_m'), 'access_claim': ex.get('access_claim'), 'review': conflict,
              'independence_key': digest(str(a.get('seller_hash') or digest(fold(text))))[:20],
              'independence_keys': ['content:'+digest(fold(text)), 'ad:'+a['source']+':'+str(a['ad_id'])],
              'extractor': 'regex-v1', 'method': 'goong_geocode_snap'}
        if a.get('seller_hash'):
            rs['independence_keys'].append('seller:' + a['seller_hash'])
        if names:
            rs['independence_keys'].append('property:' + norm_name(names[-1]))
        entries.append({'id': 'listing:'+a['source']+':'+str(a['ad_id']), 'source': 'listing',
                        'names': names[-1:] if names else [], 'ward': '',
                        'district': district_names.get(a.get('district_id'), ''), 'source_date': str(posted)[:10],
                        'record': rs, 'excluded_reason': 'ambiguous_claim_review_required' if ambiguous else None})
    return entries, known


def merge_declared(product, records=None):
    """Called by both this pipeline and listings rebuilds, so refreshes retain matches."""
    records = records if records is not None else read(ACCEPTED).get('records', [])
    listings = [r for r in records if r['source'] == 'listing']
    by_way = defaultdict(list)
    for e in listings:
        match, row = e['match'], e['record']
        by_way[str(match['way_id'])].append({**row, 'way_id': match['way_id'], 'name': match['osm_name']})
    for wid, rs in by_way.items():
        original = product['ways'].get(wid)
        # The original immutable claim records preserve duplicate grouping.
        baseline = [r for r in read(ROOT / 'data/raw/listings_city/matched_records.json', []) if str(r['way_id']) == wid]
        if original and not baseline:
            raise ValueError('missing_original_listing_records')
        identities = {(r['source'], r['listing_id']) for r in baseline}
        rs = [r for r in rs if (r['source'], r['listing_id']) not in identities]
        merged = aggregate(baseline + rs)[wid]
        provenance = {e['record']['listing_id']: e['match']['provenance'] for e in listings if str(e['match']['way_id']) == wid}
        for claim in merged['claims']:
            if claim['listing_id'] in provenance:
                claim['provenance'] = provenance[claim['listing_id']]
        product['ways'][wid] = merged
    fire = defaultdict(list)
    for e in records:
        if e['source'] == 'fire':
            fire[str(e['match']['way_id'])].append(e)
    for wid, es in fire.items():
        detail = '; '.join(f"{e['record']['name']} ({e['record'].get('ward', '')}): {e['match']['provenance']}" for e in es)
        previous = product.setdefault('fire_supplemental', {}).get(wid, {})
        baseline_detail = previous.get('pre_geocode_detail', previous.get('detail', '') if not previous.get('geocode_matches') else '')
        product.setdefault('fire_supplemental', {})[wid] = {
            'lo': .5, 'hi': 3.5, 'tier': 'Declared', 'source': 'QĐ 4582/QĐ-UBND TP.HCM (24/7/2026)',
            'detail': (baseline_detail + '; ' if baseline_detail else '') + detail + '. Xe chữa cháy không vào được; có thể do cua, dây thấp, ngõ cụt; chưa đo thông thủy.',
            'observed_on': '2026-07-24', 'url': read(ROOT/'data/official/fire_access_4582.json').get('url', ''),
            'geocode_matches': [e['match'] for e in es], 'pre_geocode_detail': baseline_detail}
    product['geocode_recovery'] = {'records': len(records), 'generated_at': now()}
    return product


def merge_official(product, records=None):
    records = records if records is not None else read(ACCEPTED).get('records', [])
    for e in records:
        if e['source'] != 'q9':
            continue
        m = e['match']
        rows = product['ways'].setdefault(str(m['way_id']), [])
        row = {**e['record'], 'way_ids': [m['way_id']], 'osm_names': [m['osm_name']],
               'match_method': 'goong_geocode_snap', 'match': m, 'provenance': m['provenance'], 'status': 'matched'}
        rows[:] = [r for r in rows if (r.get('source_id'), r.get('id')) != (row['source_id'], row['id'])]
        rows.append(row)
    return product


def merge_fire_source(product, records):
    """Persist fire recovery in its established source file as well as the index.

    A listings daemon that loaded the old builder before this change can later
    replace declared_index.json. Its existing fire loader must still retain the
    recovery; no server/daemon restart is required to keep the new bounds.
    """
    rows = product['items']
    for e in records:
        if e['source'] != 'fire':
            continue
        rows[:] = [r for r in rows if r.get('geocode_source_item') != e['id']]
        match = e['match']
        rows.append({'ward': e['record'].get('ward'), 'name': e['record']['name'],
                     'way_ids': [match['way_id']], 'dist_m': match['distance_m'],
                     'geocode_source_item': e['id'], 'provenance': match['provenance'], 'geocode_match': match})
    product['geocode_added_items'] = sum(bool(r.get('geocode_source_item')) for r in rows)
    product['unmatched'] = product['parsed'] - len(rows)
    return product


def publish(records):
    atomic(ACCEPTED, {'schema_version': 1, 'generated_at': now(), 'records': records})
    path = ROOT / 'data/official/fire_access_4582.json'
    atomic(path, merge_fire_source(read(path), records))
    path = ROOT / 'backend/cache/live/declared_index.json'
    product = merge_declared(read(path), records)
    product['generated_at'] = now()
    atomic(path, product)
    path = ROOT / 'backend/cache/live/official_widths.json'
    product = merge_official(read(path), records)
    product['generated_at'] = now()
    atomic(path, product)


def run(args):
    previous_report = read(REPORT)
    inv = inventory()
    entries, known = source_entries(inv)
    atomic(RAW / 'entries.json', entries)
    eligible = sorted((e for e in known if any(chain(n) for n in e['names'])), key=lambda e: e['id'])
    # Fixed seed, without replacement; selected before any Goong result is known.
    sample = random.Random(4582).sample(eligible, min(args.sample_size, len(eligible)))
    atomic(RAW / 'validation_sample.json', sample)
    if args.command == 'prepare':
        print(json.dumps({'entries': dict(Counter(e['source'] for e in entries)), 'validation_sample': len(sample),
                          'strict_queryable': dict(Counter(e['source'] for e in entries if any(chain(n) for n in e['names'])))}))
        return
    from app.evidence_queue import city_state
    before = city_state()
    before_ids = {wid for wid, r in before['ways'].items() if r['top_tier']}
    index = SnapIndex(inv['ways'])
    api = Goong(network=args.network, max_calls=args.max_calls, already_used=args.already_used)
    results, checks, accepted = [], [], []
    try:
        for i, e in enumerate(sample):
            result = locate(e, api, index, validation_only=True)
            checks.append({'id': e['id'], 'expected_way_ids': e['record']['way_ids'], **result,
                           'same_way': result.get('way_id') in [int(w) for w in e['record']['way_ids']]})
            if (i+1) % 20 == 0:
                print(json.dumps({'validation': i+1, 'calls': api.calls}), flush=True)
        # Fair source round-robin; stable hash order avoids source-page geography bias.
        queues = [[e for e in entries if e['source'] == source] for source in ('fire', 'q9', 'listing')]
        queues = [sorted(q, key=lambda e: (not any(chain(n) in index.by_chain for n in e['names']), digest(e['id']))) for q in queues]
        for batch in itertools.zip_longest(*queues):
            for e in batch:
                if e is None:
                    continue
                if e.get('excluded_reason'):
                    result = {'reason': e['excluded_reason'], 'attempts': []}
                else:
                    result = locate(e, api, index)
                results.append({'id': e['id'], 'source': e['source'], **result})
                if result['reason'] == 'accepted':
                    accepted.append({**e, 'match': result})
                if len(results) % 100 == 0:
                    print(json.dumps({'processed': len(results), 'accepted': len(accepted), 'calls': api.calls}), flush=True)
        # Prior accepted recoveries survive budget exhaustion and cache-only runs.
        prior = {e['id']: e for e in read(ACCEPTED).get('records', [])}
        prior.update({e['id']: e for e in accepted})
        publish(list(prior.values()))
        atomic(RAW / 'audit.json', {'generated_at': now(), 'items': results, 'validation': checks})
        after = city_state()
        after_ids = {wid for wid, r in after['ways'].items() if r['top_tier']}
        snapped = [r for r in checks if r['reason'] == 'accepted']
        attempted = [r for r in checks if any(a.get('geocoded') for a in r['attempts'])]
        compare_records = []
        for e in prior.values():
            if e['source'] == 'q9':
                continue
            row = e['record'] if e['source'] == 'listing' else {'bounds': [.5, 3.5], 'width_m': None, 'access_claim': None}
            compare_records.append({**row, 'way_id': e['match']['way_id'], 'method': 'goong_geocode_snap'})
        from official_bulk import validate, cadastral_snapshot
        metadata = merge_official({'ways': {}}, list(prior.values()))
        report = {'generated_at': now(), 'quota': {'documented_free_daily': 1000, 'source': QUOTA_URL,
                  'actual_key_plan': 'unverified; conservative Free ceiling', 'max_task_calls_rolling_24h': api.cap,
                  'requests_per_second_max': 4, 'calls_this_run': api.calls, 'calls_rolling_24h': api.usage(),
                  'cache_hits': api.cache_hits, 'other_key_traffic': 'unknown unless supplied through --already-used',
                  'stop_reason': api.stop_reason}, 'inventory_fingerprint': inv['fingerprint'],
                  'entries': dict(Counter(e['source'] for e in entries)),
                  'ambiguous_listing_texts_excluded': len(read(ROOT / 'data/raw/listings_city/reviews.json', [])),
                  'accepted_entries': dict(Counter(e['source'] for e in prior.values())),
                  'accepted_this_run': dict(Counter(e['source'] for e in accepted)),
                  'accepted_ways_by_source': {s: len({e['match']['way_id'] for e in prior.values() if e['source'] == s}) for s in ('fire', 'q9', 'listing')},
                  'unresolved': {s: dict(Counter(r['reason'] for r in results if r['source'] == s and r['reason'] != 'accepted')) for s in ('fire', 'q9', 'listing')},
                  'validation': {'sample_size': len(checks), 'geocoded_entries': len(attempted), 'accepted_snaps': len(snapped),
                   'same_way': sum(r['same_way'] for r in checks), 'different_way': sum(not r['same_way'] for r in snapped),
                   'same_way_pct_all_sample': round(100*sum(r['same_way'] for r in checks)/len(checks), 2) if checks else None,
                   'precision_proxy_pct_accepted': round(100*sum(r['same_way'] for r in snapped)/len(snapped), 2) if snapped else None,
                   'caveat': 'Name-matched QĐ 4582 sample, fixed seed 4582; reference may itself be wrong. One geocode query each to reserve validation budget; no autocomplete fallback. Acceptance precision and recovery rate have different denominators.'},
                  'cadastral_declared': validation(compare_records, cadastral()),
                  'cadastral_q9_metadata': validate(metadata['ways'], cadastral_snapshot(RAW/'cadastral_snapshot.json')),
                  'coverage_before': before['coverage'], 'coverage_after': after['coverage'],
                  'net_new_ways_this_run': sorted(after_ids-before_ids),
                  'accepted_previously_unsourced_ways': sorted({e['match']['way_id'] for e in prior.values()
                      if e['source'] in ('fire', 'listing') and str(e['match']['way_id']) not in before_ids}),
                  'gain_over_14863': after['coverage']['evidence_ways_with_sources']-14863,
                  'portal_calls': 0, 'gemini_calls': 0}
        # Keep cumulative task outcomes on cache-only replay, not just this run's
        # (necessarily zero) new coverage and HTTP call counts.
        previous_new = previous_report.get('new_source_way_ids', previous_report.get('net_new_ways_this_run', []))
        report['new_source_way_ids'] = sorted(set(previous_new) | (after_ids-before_ids))
        report['new_source_ways'] = len(report['new_source_way_ids'])
        report['initial_coverage_before'] = previous_report.get('initial_coverage_before', before['coverage'])
        times = [r[0] for r in api.db.execute('SELECT at FROM calls ORDER BY at')]
        report['quota'].update(calls_total_this_task=len(times),
            http_status_counts=dict(api.db.execute('SELECT status,COUNT(*) FROM calls GROUP BY status')),
            minimum_request_start_spacing_s=round(min(b-a for a,b in zip(times,times[1:])), 6) if len(times)>1 else None,
            maximum_starts_in_one_second=max((sum(t<=v<t+1 for v in times) for t in times), default=0),
            documented_daily_fraction_used=len(times)/1000, api_calls_after_429=0)
        report['entries_with_geocode_response'] = {s: sum(r['source']==s and any(a.get('geocoded') for a in r['attempts'])
            for r in results) for s in ('fire', 'q9', 'listing')}
        # Live verification is deliberately a separate, read-only request.
        for field in ('live_verification', 'credential_scan', 'q9_metadata_new_ways'):
            if field in previous_report:
                report[field] = previous_report[field]
        atomic(REPORT, report)
        print(json.dumps({k: report[k] for k in ('quota', 'accepted_entries', 'validation', 'gain_over_14863')}, ensure_ascii=False), flush=True)
    finally:
        api.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=('prepare', 'run'))
    p.add_argument('--network', action='store_true')
    p.add_argument('--max-calls', type=int, default=499)
    p.add_argument('--already-used', type=int, default=0, help='Other Goong calls used in the last day, deducted from the half-quota cap')
    p.add_argument('--sample-size', type=int, default=100)
    args = p.parse_args()
    if args.sample_size < 100:
        p.error('validation requires at least 100 entries')
    try:
        run(args)
    except StopGoong as exc:
        raise SystemExit(str(exc)) from None


if __name__ == '__main__':
    main()
