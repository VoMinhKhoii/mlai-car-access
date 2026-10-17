#!/usr/bin/env python3
"""Demand-prioritized street-level widths. Detached runner; no commits/keys/log URLs.

PYTHONPATH=backend:. AGENT_ALLOW_PAID=1 python3 pipelines/imagery_widths.py --top-n 1000
Review: --review ID --reviewer 'Name' [--reject]. There is no auto-approve switch.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import fcntl
import json
import math
import os
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT)]
# Process-local authorization for this explicitly requested batch, never a saved flag.
os.environ.setdefault('FLAG_GOOGLE_LOOKUP', '1')

import httpx
from shapely.geometry import LineString, Point
from shapely.strtree import STRtree
from app import agent_budget, budget, evidence_queue, google_lookup, imagery_evidence as ie
from app.config import CACHE

DIR = CACHE / 'live/imagery'
X, Y = 109400., 110574.


def log(event, **fields):
    print(json.dumps({'at': ie.now(), 'event': event, **fields}, ensure_ascii=False), flush=True)


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f'.{os.getpid()}.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    tmp.replace(path)


def line_for(row):
    return LineString([(lon * X, lat * Y) for lon, lat in row['coords']])


def parcel_cuts():
    by_way = {}
    paths = [CACHE / 'live/city_parcels.json', *sorted((CACHE / 'live/areas').glob('*.json'))]
    for p in paths:
        data = read(p, {})
        records = data.get('parcels', []) if p.parent.name == 'areas' else [dict(v, way_id=int(k)) for k, v in data.items() if isinstance(v, dict)]
        for row in records:
            wid = int(row['way_id'])
            for cut in row.get('cuts', []):
                if cut.get('valid', True) and isinstance(cut.get('gap_m'), (int, float)) and cut['gap_m'] > 1:
                    by_way.setdefault(wid, {})[(cut.get('lat'), cut.get('lon'), cut.get('at_m'))] = cut
    return {wid: list(cuts.values()) for wid, cuts in by_way.items()}


def targets(top_n):
    inventory = read(evidence_queue.INVENTORY, {})['ways']
    # Same implementation/ranking as GET /api/evidence/queue, with no server dependency.
    q = evidence_queue.queue(limit=len(inventory))
    if not q['available']:
        raise ValueError('Build the evidence inventory first')
    ranked = [r for r in q['items'] if r['is_alley']]
    ranks = {r['way_id']: r for r in ranked}
    selected = {r['way_id']: {'reason': 'queue', **r} for r in ranked[:top_n]}
    campuses = read(ROOT / 'docs/eval/hutech-campuses.json', {})['campuses']
    for r in ranked:
        row = inventory[str(r['way_id'])]
        line = line_for(row)
        near = [c['id'] for c in campuses if line.distance(Point(c['lon'] * X, c['lat'] * Y)) <= 500]
        if near:
            selected.setdefault(r['way_id'], {'reason': 'campus-500m', **r})['campuses'] = near
    cuts = parcel_cuts()
    # Validation pool is selected before any predictions, never by successful estimate.
    calibration = [r for r in ranked if r['way_id'] in cuts][:40]
    for r in calibration:
        selected.setdefault(r['way_id'], {'reason': 'validation', **r})['validation'] = True
    rows = sorted(selected.values(), key=lambda r: (not r.get('validation', False), -r['score'], r['way_id']))
    for r in rows:
        r['coords'] = inventory[str(r['way_id'])]['coords']
    return rows, inventory, cuts, ranks


def pano_position(meta, way, tree=None, lines=None, ids=None):
    """Reject mouth/main-road panoramas and ambiguous nearby parallel ways."""
    line = line_for(way)
    p = Point(meta['lon'] * X, meta['lat'] * Y)
    at = line.project(p)
    distance = line.distance(p)
    if distance > 3 or at < 8 or at > line.length - 8:
        return None
    if tree is not None:
        for index in tree.query(p.buffer(8)):
            if ids[index] != way['way_id'] and lines[index].distance(p) <= max(3., distance + 1.):
                return None
    a, b = line.interpolate(max(0, at - 4)), line.interpolate(min(line.length, at + 4))
    heading = math.degrees(math.atan2(b.x - a.x, b.y - a.y)) % 360
    return {'lat': meta['lat'], 'lon': meta['lon'], 'at_m': round(at, 2),
            'offset_m': round(distance, 2), 'heading': round(heading)}


def listing_backlog():
    listings = {}
    for path in sorted((CACHE / 'live/areas').glob('*.json')):
        for r in read(path, {}).get('listings', []):
            if r.get('match_method') == 'alley_chain' and 'Chợ Tốt' in r.get('source', ''):
                listings.setdefault(int(r['osm_way_id']), []).append(r)
    # Reuse the city matcher's exact-chain decisions where live.py already
    # cached the original photo URLs. No new listing fetches or coordinate match.
    ads = {str(a['ad_id']):a for path in (CACHE / 'live/chotot').glob('*.json')
           for a in read(path, {}).get('ads', []) if a.get('ad_id')}
    for r in read(ROOT / 'data/raw/listings_city/matched_records.json', []):
        ad = ads.get(str(r['listing_id']), {})
        if r.get('source') != 'chotot' or r.get('method') != 'alley_chain' or not ad.get('images'):
            continue
        listings.setdefault(int(r['way_id']), []).append({
            'osm_way_id':r['way_id'], 'url':r['url'], 'posted_at':r.get('posted_at'),
            'images':ad['images'][:2], 'match_method':'alley_chain'})
    return listings


def validation(cuts):
    _, product = ie.snapshot()
    matches, per_way = [], {}
    for row in product['records'].values():
        if not ie.valid_reading(row) or row.get('provider') not in ('streetview', 'mapillary'):
            continue  # listing coordinates are deliberately NOT measurement coordinates
        candidates = cuts.get(row['way_id'], [])
        candidates = [c for c in candidates if c.get('lat') is not None and c.get('lon') is not None]
        if not candidates:
            continue
        nearest = min(candidates, key=lambda c: math.hypot((c['lon'] - row['lon']) * X, (c['lat'] - row['lat']) * Y))
        distance = math.hypot((nearest['lon'] - row['lon']) * X, (nearest['lat'] - row['lat']) * Y)
        if distance > 15:
            continue
        target = nearest['gap_m'] - 1.  # raw gap, no legacy clamping or double deduction
        estimate = (row['width_lo'] + row['width_hi']) / 2
        error = estimate - target
        match = {'way_id': row['way_id'], 'id': row['id'], 'target_gap_minus_1_m': target,
                 'estimate_m': estimate, 'error_m': error, 'distance_m': round(distance, 2),
                 'interval_covers': row['width_lo'] <= target <= row['width_hi']}
        matches.append(match)
        per_way.setdefault(row['way_id'], []).append(error)
    errors = [statistics.mean(v) for v in per_way.values()]
    mae = statistics.mean(statistics.mean(abs(e) for e in es) for es in per_way.values()) if errors else None
    bias = statistics.mean(errors) if errors else None
    # Listing photos have an alley-name association, not a surveyed camera
    # position. Report this weaker comparison separately, never as validation
    # of spatial accuracy or a reason to auto-approve.
    proxy_by_way = {}
    for row in product['records'].values():
        if ie.valid_reading(row) and row['way_id'] in cuts:
            proxy_by_way.setdefault(row['way_id'], []).append(row)
    proxy_matches = []
    for wid, readings in proxy_by_way.items():
        target = min(c['gap_m'] - 1 for c in cuts[wid])
        estimate = min((r['width_lo'] + r['width_hi']) / 2 for r in readings)
        proxy_matches.append({'way_id': wid, 'estimate_m': estimate,
                              'target_gap_minus_1_m': target, 'error_m': estimate-target})
    result = {'at': ie.now(), 'n_ways': len(errors), 'n_images': len(matches), 'mae_m': mae, 'bias_m': bias,
              'interval_coverage': statistics.mean(m['interval_covers'] for m in matches) if matches else None,
              'auto_approve': False, 'decision': 'REVIEW-only: no independent field truth or full-way coverage; cadastral gap minus 1 m is a proxy.',
              'comparison': 'visible clear-width midpoint vs nearest valid cadastral gap_m minus 1 m, within 15 m, way-weighted',
              'matches': matches,
              'way_level_proxy': {'n_ways': len(proxy_matches),
                  'mae_m': statistics.mean(abs(r['error_m']) for r in proxy_matches) if proxy_matches else None,
                  'bias_m': statistics.mean(r['error_m'] for r in proxy_matches) if proxy_matches else None,
                  'note': 'Unlocated views vs narrowest surveyed gap minus 1 m; location/date/obstructions may differ. Not independent truth.',
                  'matches': proxy_matches}}
    with ie.product() as p:
        p['validation'] = result
    write(DIR / 'validation.json', result)
    return result


def run(args):
    DIR.mkdir(parents=True, exist_ok=True)
    lock = (DIR / 'runner.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log('already_running')
        return
    start = time.monotonic()
    day = datetime.now(budget.VN_TZ).date()
    state_path = DIR / 'run.json'
    state = read(state_path, {'started_at': ie.now(), 'ways': {}, 'errors': []})
    state.update(pid=os.getpid(), state='running', stop_reason=None)
    state.setdefault('google_before', budget.report())
    rows, inventory, cuts, ranks = targets(args.top_n)
    state['targets'] = [{k: v for k, v in r.items() if k != 'coords'} for r in rows]
    write(state_path, state)
    log('start', targets=len(rows), validation_targets=sum(bool(r.get('validation')) for r in rows), job=ie.JOB_ID)
    lines, ids = [], []
    for key, row in inventory.items():
        if len(row['coords']) >= 2:
            lines.append(line_for(row)); ids.append(int(key))
    tree = STRtree(lines)
    errors = 0
    google_stopped = not args.retry_google and any(r.get('last_status') == 'REQUEST_DENIED' for r in state['ways'].values())
    budget_stopped = False

    def expired():
        return datetime.now(budget.VN_TZ).date() != day or time.monotonic() - start >= args.max_seconds

    def checkpoint():
        state.update(updated_at=ie.now(), google_after=budget.report())
        _, product = ie.snapshot()
        readings = list(product['records'].values())
        state.update(image_readings=len(readings), legacy_readings=len(product.get('legacy_records', {})),
                     pending=sum(r['status'] == 'pending' for r in readings),
                     approved=sum(r['status'] == 'approved' for r in readings),
                     ways_with_images=len({r['way_id'] for r in readings}),
                     ways_with_usable_observations=len({r['way_id'] for r in readings if ie.valid_reading(r)}))
        ledger = agent_budget.report()
        state['job_ledger'] = ledger.get('jobs', {}).get(ie.JOB_ID, {})
        state['shared_spent_usd'] = ledger['spent_usd']
        write(state_path, state)

    def vision(rec, image):
        nonlocal errors, budget_stopped
        try:
            out = ie.generate(image)
            # Never let model overwrite source identity/geolocation/capture date.
            rec = ie.save_reading({**out, **rec, 'model': ie.MODEL})
            log('reading', way_id=rec['way_id'], provider=rec['provider'], gate=rec['gate'])
            errors = 0
            return True
        except ie.BudgetStop:
            budget_stopped = True
            log('paid_job_cap_or_reserve_stop')
            return False
        except Exception as exc:
            errors += 1
            # Exception strings may include authenticated URLs. Only types leave memory.
            state['errors'].append({'at': ie.now(), 'stage': 'vision', 'type': type(exc).__name__})
            import re
            status = re.fullmatch(r'(Paid|Free) Gemini HTTP (\d+)', str(exc))
            log('vision_error', error_type=type(exc).__name__, http_status=int(status[2]) if status else None)
            return False

    # Interleave each way with its listing backlog so imagery cannot consume all
    # allowance before listing photos are attempted.
    listings = listing_backlog()
    # All matched backlog ways are queue-ranked; retain campus and validation focus first.
    have = {r['way_id'] for r in rows}
    for wid in sorted(listings, key=lambda w: -ranks.get(w, {}).get('score', 0)):
        if wid not in have and wid in ranks:
            rows.append({'reason': 'listing-backlog', **ranks[wid], 'coords': inventory[str(wid)]['coords']})
    for way in rows:
        if expired() or errors >= 3:
            break
        wid = way['way_id']
        outcome = state['ways'].setdefault(str(wid), {})
        # Listing backlog: also re-read legacy unsupported/error readings through
        # the new reference/quality gate; do not overwrite live.py caches/reviews.
        for listing in listings.get(wid, []):
            for url in listing.get('images', [])[:2]:
                if expired() or errors >= 3:
                    break
                oid = ie.record_id('chotot', url)
                if oid in ie.snapshot()[1]['records']:
                    continue
                try:
                    resp = httpx.get(url, timeout=20, follow_redirects=True)
                    if not resp.is_success:
                        continue
                    rec = {'id': oid, 'provider': 'chotot', 'way_id': wid, 'source_url': url,
                           'listing_url': listing['url'], 'image_date': None, 'listing_posted_at': listing.get('posted_at'),
                           'location_method': 'alley_chain', 'pano_id': None}
                    if not vision(rec, resp.content) and budget_stopped:
                        break
                    outcome['listing_attempts'] = outcome.get('listing_attempts', 0) + 1
                    checkpoint()
                except Exception as exc:
                    state['errors'].append({'stage': 'listing_download', 'type': type(exc).__name__})
            if budget_stopped:
                break
        if budget_stopped:
            break
        if args.mapillary and os.environ.get('MAPILLARY_CLIENT_TOKEN'):
            xs, ys = zip(*way['coords'])
            bbox = (min(xs)-.00003, min(ys)-.00003, max(xs)+.00003, max(ys)+.00003)
            try:
                for meta in ie.mapillary_images(bbox, limit=10):
                    if expired() or budget_stopped:
                        break
                    lon, lat = meta.get('computed_geometry', {}).get('coordinates', [None, None])
                    if lat is None:
                        continue
                    position = pano_position({'lat':lat, 'lon':lon}, way, tree, lines, ids)
                    if not position:
                        continue
                    heading = float(meta.get('compass_angle') or 0)
                    delta = abs((heading-position['heading']+180) % 360-180)
                    if min(delta, 180-delta) > 30:
                        continue
                    oid = ie.record_id('mapillary', meta['id'], round(heading))
                    if oid in ie.snapshot()[1]['records']:
                        continue
                    response = httpx.get(meta['thumb_1024_url'], timeout=20)
                    if not response.is_success:
                        continue
                    captured = datetime.fromtimestamp(meta['captured_at']/1000, budget.VN_TZ).date().isoformat() if meta.get('captured_at') else None
                    vision({'id':oid, 'provider':'mapillary', 'way_id':wid, 'pano_id':meta['id'],
                            'source_url':f"https://www.mapillary.com/app/?pKey={meta['id']}",
                            'image_date':captured, **position}, response.content)
                    outcome['mapillary_attempts'] = outcome.get('mapillary_attempts', 0) + 1
                    checkpoint()
            except Exception as exc:
                state['errors'].append({'stage':'mapillary', 'type':type(exc).__name__})
        if google_stopped or outcome.get('metadata_complete'):
            continue
        line = line_for(way)
        if line.length < 16:
            outcome['metadata_complete'] = True
            continue
        panos = set()
        for fraction in (.25, .5, .75):
            if expired() or budget_stopped or errors >= 3:
                break
            point = line.interpolate(fraction, normalized=True)
            try:
                meta = google_lookup.streetview(point.y / Y, point.x / X)
                outcome['metadata_calls'] = outcome.get('metadata_calls', 0) + 1
                if not meta.get('available'):
                    outcome['last_status'] = meta.get('status')
                    if meta.get('status') in ('REQUEST_DENIED', 'OVER_QUERY_LIMIT'):
                        google_stopped = True
                        log('google_provider_stop', status=meta['status'])
                        break
                    continue
                position = pano_position(meta, way, tree, lines, ids)
                if not position or meta['pano_id'] in panos:
                    outcome['rejected_off_alley'] = outcome.get('rejected_off_alley', 0) + 1
                    continue
                panos.add(meta['pano_id'])
                oid = ie.record_id('streetview', meta['pano_id'], position['heading'])
                existing = ie.snapshot()[1]['records'].get(oid)
                if existing:
                    continue  # never transfer a cached pano to a different way
                image = google_lookup.streetview_image(meta['pano_id'], position['heading'])
                rec = {'id': oid, 'provider': 'streetview', 'way_id': wid, 'pano_id': meta['pano_id'],
                       'source_url': meta['maps_url'], 'image_date': meta.get('date'),
                       'copyright': meta.get('copyright'), **position}
                vision(rec, image)
                validation(cuts)
            except budget.OverBudget:
                google_stopped = True
                log('google_sku_cap_stop')
                break
            except google_lookup.LookupOff:
                google_stopped = True
                log('google_lookup_disabled')
                break
            except Exception as exc:
                state['errors'].append({'stage': 'streetview', 'type': type(exc).__name__})
                log('streetview_error', error_type=type(exc).__name__)
            finally:
                checkpoint()
        outcome['metadata_complete'] = not expired() and not google_stopped and not budget_stopped
        checkpoint()
        if google_stopped and not listings:
            break
    metrics = validation(cuts)
    _, product = ie.snapshot()
    records = list(product['records'].values())
    state.update(state='stopped', finished_at=ie.now(), stop_reason=(
        'job_paid_cap_or_live_reserve' if budget_stopped else 'provider_errors' if errors >= 3 else
        'time_or_day_limit' if expired() else 'google_cap_or_provider_stop' if google_stopped else 'targets_exhausted'),
        ways_attempted=sum(bool(r.get('metadata_calls') or r.get('listing_attempts') or r.get('mapillary_attempts')) for r in state['ways'].values()), ways_with_images=len({r['way_id'] for r in records}),
        ways_with_usable_observations=len({r['way_id'] for r in records if ie.valid_reading(r)}),
        image_readings=len(records), pending=sum(r['status'] == 'pending' for r in records),
        approved=sum(r['status'] == 'approved' for r in records), validation=metrics,
        mapillary='Skipped; set MAPILLARY_CLIENT_TOKEN and use imagery_evidence.mapillary_images(bbox).')
    checkpoint()
    log('finished', reason=state['stop_reason'], ways=state['ways_attempted'], images=len(records), validation_ways=metrics['n_ways'])
    return state['stop_reason']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--top-n', type=int, default=1000)
    p.add_argument('--max-seconds', type=int, default=86400)
    p.add_argument('--review'); p.add_argument('--reviewer'); p.add_argument('--reject', action='store_true')
    p.add_argument('--validate-only', action='store_true')
    p.add_argument('--mapillary', action='store_true', help='Optional MAPILLARY_CLIENT_TOKEN source; skipped without token')
    p.add_argument('--wait-for-free', action='store_true', help='After paid cap, resume once at the shared project reset today')
    p.add_argument('--retry-google', action='store_true', help='Retry a persisted REQUEST_DENIED after enabling project billing')
    args = p.parse_args()
    if args.review:
        ie.review(args.review, not args.reject, args.reviewer)
    elif args.validate_only:
        print(json.dumps(validation(parcel_cuts()), indent=2))
    else:
        DIR.mkdir(parents=True, exist_ok=True)
        supervisor = (DIR / 'supervisor.lock').open('a')
        try:
            fcntl.flock(supervisor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log('already_running_or_waiting')
            return
        reason = run(args)
        reset = agent_budget.report().get('free_project_cooldown_until', 0)
        today = datetime.now(budget.VN_TZ).date()
        if (args.wait_for_free and reason == 'job_paid_cap_or_live_reserve' and reset > time.time()
                and datetime.fromtimestamp(reset, budget.VN_TZ).date() == today):
            state_path = DIR / 'run.json'
            state = read(state_path, {})
            state.update(state='waiting_for_free_reset', free_resume_at=datetime.fromtimestamp(reset, budget.VN_TZ).isoformat())
            write(state_path, state)
            log('waiting_for_free_reset', resume_at=state['free_resume_at'])
            while time.time() < reset and datetime.now(budget.VN_TZ).date() == today:
                time.sleep(min(30, max(.1, reset-time.time())))
            if datetime.now(budget.VN_TZ).date() == today:
                # Paid job allowance never resets. Resume is free-only even if
                # the project immediately reports daily exhaustion again.
                os.environ['AGENT_ALLOW_PAID'] = '0'
                run(args)


if __name__ == '__main__':
    main()
