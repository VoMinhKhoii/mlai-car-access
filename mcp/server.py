"""Read-only MCP boundary over the arrival engine; never enters the agent model loop.

Kept outside app.agent so changes to conversational summaries cannot silently
change the public MCP contract. Only the six names below can be dispatched.
"""
from __future__ import annotations

import importlib.util
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

_spec = importlib.util.spec_from_file_location('ngo_ngach_mcp_protocol', Path(__file__).with_name('protocol.py'))
protocol = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(protocol)
RATE_LIMITER = protocol.RateLimiter()
VN_TZ = timezone(timedelta(hours=7))
PUBLIC_ORIGIN = 'https://concerts-message-concerns-performer.trycloudflare.com'

LAT = {'type': 'number', 'minimum': 10.35, 'maximum': 11.20,
       'description': 'HCMC service-area latitude; use coordinates returned by find_place.'}
LON = {'type': 'number', 'minimum': 106.30, 'maximum': 107.10,
       'description': 'HCMC service-area longitude.'}
WHEN = {'type': 'string', 'format': 'date-time', 'minLength': 20, 'maxLength': 40,
        'description': 'ISO 8601 timestamp with timezone, e.g. 2026-10-17T18:00:00+07:00. No forecast beyond source coverage.'}
VEHICLE = {'type': 'string', 'minLength': 1, 'maxLength': 80,
           'description': 'Catalogue ID or recognized model alias, e.g. toyota-fortuner, Fortuner, class-m.'}
PLAN_PROPERTIES = {
    'lat': LAT, 'lon': LON, 'label': {'type': 'string', 'minLength': 1, 'maxLength': 300},
    'vehicle_id': VEHICLE, 'arrive_at': WHEN,
    'dwell_min': {'type': 'integer', 'minimum': 1, 'maximum': 2160},
    'intent': {'type': 'string', 'enum': ['park', 'pickup']},
    'rain_mm_per_h': {'type': 'number', 'minimum': 0, 'maximum': 300}}
PLAN_REQUIRED = ['lat', 'lon', 'label', 'vehicle_id', 'arrive_at', 'dwell_min', 'intent']
PLAN_EXAMPLE = '{"lat":10.792106,"lon":106.716661,"label":"Hẻm 113/4 Võ Duy Ninh","vehicle_id":"toyota-fortuner","arrive_at":"2026-10-17T18:00:00+07:00","dwell_min":120,"intent":"park"}'


def tool(name, description, properties, required):
    return {'name': name, 'description': description,
            'inputSchema': {'type': 'object', 'properties': properties, 'required': required,
                            'additionalProperties': False},
            'annotations': {'readOnlyHint': True, 'destructiveHint': False,
                            'idempotentHint': True, 'openWorldHint': True}}


TOOLS = [
    tool('find_place', 'Search HCMC addresses/POIs, up to three coordinate candidates; resolve ambiguity before planning. '
         'Example: {"query":"Hẻm 113/4 Võ Duy Ninh, Bình Thạnh"}.',
         {'query': {'type': 'string', 'minLength': 3, 'maxLength': 200}}, ['query']),
    tool('plan_arrival', 'Full arrival plan: preserve verdict.estimate, access versus legal status, stop points, walking, exit, flood, '
         'citations, evidence tiers and caveats. Unknown is not safe; physical access does not authorize stopping. '
         'Uses existing cached areas only; cannot build or crawl. Example: ' + PLAN_EXAMPLE + '.',
         PLAN_PROPERTIES, PLAN_REQUIRED),
    tool('check_alley_fit', 'Single-alley fit only; not whole-route, exit, flood or legal certification. Cached areas only. '
         'Example: {"lat":10.792106,"lon":106.716661,"way_id":464839531,"vehicle_id":"Fortuner"}.',
         {'lat': LAT, 'lon': LON, 'way_id': {'type': 'integer', 'minimum': 1, 'maximum': 9_007_199_254_740_991},
          'vehicle_id': VEHICLE}, ['lat', 'lon', 'way_id', 'vehicle_id']),
    tool('find_nearby_stops', 'Nearby stop points only; no door/standard-route payload. Preserve legal restrictions and unverified evidence. '
         'Cached areas only. Example: ' + PLAN_EXAMPLE + '.', PLAN_PROPERTIES, PLAN_REQUIRED),
    tool('list_vehicles', 'Vehicle catalogue and conservative size classes; dimensions in metres. Source references resolve in sources. '
         'Mirror estimates and class envelopes are assumptions, not surveyed clearance. Example: {}.', {}, []),
    tool('tide_levels', 'Tide extrema and alarm thresholds, at most 36 hours; missing_points means unknown, not no flood. '
         'Example: {"start":"2026-10-17T12:00:00+07:00","hours":24}.',
         {'start': WHEN, 'hours': {'type': 'integer', 'minimum': 1, 'maximum': 36}}, ['start']),
]


def list_tools():
    return TOOLS


def _pick(data, keys):
    return {k: data[k] for k in keys if k in data}


def _without_geometry(value):
    if isinstance(value, dict):
        return {k: _without_geometry(v) for k, v in value.items()
                if k not in ('geometry', 'coordinates', 'features', 'layers', 'edge_ids', 'node_ids', '_c')}
    if isinstance(value, list):
        return [_without_geometry(v) for v in value]
    return value


def _width(wr, evidence_limit=2):
    result = _pick(wr or {}, ('lo', 'hi', 'label', 'top_tier', 'review', 'width_basis', 'coverage', 'decisive_clearance'))
    evidence = (wr or {}).get('evidence') or []
    # Keep the strongest evidence first; never promote a weaker tier by truncating.
    top = result.get('top_tier')
    ordered = sorted(evidence, key=lambda e: e.get('tier') != top)
    result['evidence'] = [_pick(e, ('tier', 'source', 'detail', 'url', 'source_url', 'lo', 'hi',
                                          'width_basis', 'uncertainty_m')) for e in ordered[:evidence_limit]]
    if len(evidence) > evidence_limit:
        result['omitted_evidence_count'] = len(evidence) - evidence_limit
    return result


def _flood(value):
    if not value:
        return value
    # The aggregate is the worst assessment, so omitting per-way duplicate legs
    # does not change a pass/fail or conceal the limiting status.
    return _pick(value, ('status', 'depth', 'knowledge', 'reason', 'freshness', 'at', 'source', 'interval'))


def _stop(stop, evidence_limit=2):
    if not stop:
        return None
    result = _pick(stop, ('name', 'kind', 'way_id', 'lat', 'lon', 'ok', 'tier', 'verified', 'estimate',
                         'access_verdict', 'legal_verdict', 'failure_codes', 'fail_reasons', 'unverified_reasons'))
    fit = stop.get('fit') or {}
    result['fit'] = {**_pick(fit, ('class', 'note')), 'width_range': _width(fit.get('width_range'), evidence_limit)}
    estimate = result.get('estimate')
    if isinstance(estimate, dict):
        result['estimate'] = {k: v for k, v in estimate.items() if k not in ('coverage', 'limiting_width', 'stop_width')}
    result['walk'] = _without_geometry(stop.get('walk'))
    if result['walk'] and isinstance(result['walk'].get('connection'), dict):
        result['walk']['connection'] = _pick(result['walk']['connection'], ('mapped', 'reason'))
    result['way_out'] = _pick(stop.get('way_out') or {}, ('available', 'mode', 'reverse_m', 'tight_exit', 'text', 'strict', 'route_verified', 'manoeuvre_status', 'reason', 'flood', 'unverified_reasons'))
    if isinstance(result['way_out'], dict) and 'flood' in result['way_out']:
        result['way_out']['flood'] = _flood(result['way_out']['flood'])
    result['flood'] = {k: _flood(v) for k, v in (stop.get('flood') or {}).items()}
    result['legality'] = stop.get('legality')  # retain every legal rule and citation
    # Route geometry stays in the map. Here keep route confidence and length only.
    result['route_in'] = _pick(stop.get('route_in') or {}, ('strict', 'meters', 'reason', 'mode'))
    return _without_geometry(result)


def _omit_optional_nulls(value):
    if isinstance(value, dict):
        # Unknown measurements retain explicit nulls. Omit only optional empty
        # annotations, never legal rules, false checks or uncertainty strings.
        return {k: _omit_optional_nulls(v) for k, v in value.items()
                if v is not None or k in ('depth', 'level_m', 'hi', 'value_m')}
    if isinstance(value, list):
        return [_omit_optional_nulls(v) for v in value]
    return value


def compact_plan(raw, stops_only=False):
    from app.flood import tide_meta
    meta = tide_meta()
    base = _pick(raw, ('destination', 'window', 'verdict', 'timing', 'intent', 'no_stop_reason',
                       'access_verdict', 'legal_verdict'))
    base['vehicle'] = _pick(raw.get('vehicle') or {}, ('id', 'label', 'mirror_width'))
    base['tide_source'] = _pick(meta, ('station', 'bulletin', 'issued_at', 'source_url'))
    window = raw.get('window') or {}
    if any((window.get(key) or {}).get('level_m') is None for key in ('tide_arrive', 'tide_depart')):
        base['tide_note'] = 'No tide forecast covers this time; flood conditions remain unverified.'
    # Use the canonical merged engine verdict without reinterpreting access as legality.
    # Shrink alternatives/evidence only; preserve legal rules, estimate and safety caveats.
    stops = raw.get('stop_points') or []
    for count, evidence_limit in ((3, 2), (2, 1), (1, 1)):
        result = {**base, 'stop_points': [_stop(s, evidence_limit) for s in stops[:count]]}
        if len(stops) > count:
            result['omitted_stop_points_count'] = len(stops) - count
        if not stops_only:
            result['door'] = _stop(raw.get('door'), evidence_limit)
        result = _omit_optional_nulls(_without_geometry(result))
        if len(protocol.dumps(result).encode()) < 60_000:
            return result
    # Never silently drop a safety field to fit the budget.
    return {'error': 'compact_result_too_large',
            'note': 'Result exceeds the compact response budget. No safety conclusion; request a single-alley check.'}


def _catalogue():
    from app import vehicles
    sources, rows = [], []
    for p in vehicles.all_profiles().values():
        row = {k: getattr(p, k) for k in ('id', 'label', 'size_class', 'mirror_width', 'length')}
        if p.kind == 'class':
            row['kind'] = 'class'
        row['mirror_width'] = round(row['mirror_width'], 3)
        if not p.mirror_estimated:
            row['mirror_estimated'] = False
        if p.source_url:
            if p.source_url not in sources:
                sources.append(p.source_url)
            row['source_ref'] = sources.index(p.source_url)
        rows.append(row)
    return {'vehicles': rows, 'sources': sources, 'units': 'metres', 'defaults': {'kind': 'model', 'mirror_estimated': True},
            'caveats': 'mirror_estimated uses body width + allowance; classes are conservative envelopes, not a specific model. '
                       'Catalogue dimensions do not certify alley clearance, manoeuvres or safe flood depth.'}


def _execute(name, args):
    from app import agent, config, live, osm, plan, vehicles
    name = protocol.TOOL_ALIASES.get(name, name)
    if name == 'list_vehicles':
        return _catalogue()
    if name == 'find_place':
        result = agent.resolve_place(args['query'])
        # Defence in depth: never return an out-of-area provider candidate.
        result['results'] = [r for r in result.get('results', [])
                             if config.in_hcmc(r['lat'], r['lon'])][:3]
        result['requires_clarification'] = bool(result.get('requires_clarification') or len(result['results']) > 1)
        return _without_geometry(result)
    if name == 'tide_levels':
        result, _ = agent.execute('muc_trieu', args)
        return _without_geometry(result)
    # No build_graph on a cache miss, no live.build_area / request_build / crawler.
    if osm.cached_graph(args['lat'], args['lon']) is None:
        return {'error': 'area_not_cached',
                'note': 'No cached map is available for this area. MCP will not start a build or crawl; no access conclusion is available.'}
    vehicle_id = agent.normalize_vehicle(args['vehicle_id'])
    live_area, _ = live.area_status(args['lat'], args['lon'])
    if name == 'check_alley_fit':
        graph, widths, _ = plan.area(args['lat'], args['lon'], live_area=live_area)
        wid = args['way_id']
        if wid not in widths:
            return {'error': 'way_not_in_area', 'note': 'The requested alley segment is not in the cached area map.'}
        vehicle = vehicles.get_profile(vehicle_id)
        fits, notes = plan.compute_fit(graph, widths, vehicle)
        width = plan._width_estimate(widths[wid])
        answer = ('unknown' if width is None else 'fits' if width >= vehicle.fits_min
                  else 'tight' if width >= vehicle.tight_min else 'no')
        if fits[wid] in ('no', 'blocked'):
            answer = 'no'
        return {'way_id': wid, 'vehicle': {'id': vehicle.id, 'label': vehicle.label, 'mirror_width': vehicle.mirror_width},
                'fit': fits[wid], 'note': notes.get(wid), 'width_range': _width(widths[wid].to_json(), 3),
                'estimate': {'answer': answer, 'confidence': 'low',
                             'basis': 'Single-segment estimate only; the full route, exit, flood conditions and legality have not been checked.'},
                'scope': 'Single segment width only; not a full-route, exit, flood or legal check.'}
    arrive = datetime.fromisoformat(args['arrive_at'].replace('Z', '+00:00')).astimezone(VN_TZ)
    rain = [{'start': arrive.isoformat(), 'end': (arrive + timedelta(minutes=args['dwell_min'])).isoformat(),
             'mm_per_h': args['rain_mm_per_h']}] if args.get('rain_mm_per_h') else []
    raw = plan.plan(args['lat'], args['lon'], vehicle_id, args['intent'], arrive,
                    args['dwell_min'], rain, args['label'], live_area=live_area)
    return compact_plan(raw, stops_only=name == 'find_nearby_stops')


def call_tool(name, args):
    from app import agent
    # Use the existing deadline/admission mechanism, never agent.generate/events.
    runner = agent.bounded(_execute, min(40, float(os.environ.get('AGENT_TOOL_TIMEOUT', '40'))), name, args)
    while True:
        try:
            next(runner)
        except StopIteration as done:
            return done.value
        except Exception:
            return {'error': 'tool_unavailable',
                    'note': 'The data source is unavailable or the vehicle is not recognized. Retry or use list_vehicles.'}
