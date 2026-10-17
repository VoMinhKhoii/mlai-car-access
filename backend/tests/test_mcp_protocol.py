"""Offline MCP contract tests. No provider, Goong, model, crawl or paid API calls."""
import copy
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import agent, main

server = main.mcp_server
protocol = server.protocol
HEADERS = {'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-11-25'}
ARGS = json.loads(server.PLAN_EXAMPLE)


@pytest.fixture(autouse=True)
def offline_boundary(monkeypatch):
    monkeypatch.setattr(server, 'RATE_LIMITER', protocol.RateLimiter())
    monkeypatch.delenv('MCP_AUTH_TOKEN', raising=False)
    monkeypatch.setattr(httpx, 'get', lambda *a, **kw: pytest.fail('Unexpected external HTTP GET'))
    monkeypatch.setattr(agent, 'generate', lambda *a, **kw: pytest.fail('MCP called a model'))


def rpc(method, params=None, ident=1):
    return {'jsonrpc': '2.0', 'id': ident, 'method': method, 'params': params or {}}


def dispatch(method, params=None, call=None):
    return protocol.dispatch(rpc(method, params), server.list_tools, call or server.call_tool)


def test_initialize_negotiates_stable_version_and_ping():
    for proposed in ('2025-11-25', '2025-06-18', '2025-03-26', '2099-01-01'):
        result = dispatch('initialize', {'protocolVersion': proposed, 'capabilities': {},
                                      'clientInfo': {'name': 'offline', 'version': '1'}})['result']
        assert result['protocolVersion'] == (proposed if proposed in protocol.VERSIONS else protocol.VERSIONS[0])
        assert result['serverInfo']['name'] == 'ngo-ngach'
        assert result['serverInfo']['title'] == 'Ngõ Ngách — alley access for vehicles in HCMC'
        assert result['capabilities'] == {'tools': {'listChanged': False}}
    assert dispatch('ping')['result'] == {}
    assert dispatch('initialize')['error']['code'] == -32602


def test_json_rpc_errors_notifications_and_client_response():
    for req in ([], {}, {'jsonrpc': '1.0', 'method': 'ping', 'id': 1},
                {'jsonrpc': '2.0', 'method': 'ping', 'id': True},
                {'jsonrpc': '2.0', 'method': 'ping', 'id': None}):
        assert protocol.dispatch(req, server.list_tools, server.call_tool)['error']['code'] == -32600
    assert dispatch('missing')['error']['code'] == -32601
    assert dispatch('tools/list', {'cursor': 'bad'})['error']['code'] == -32602
    assert dispatch('tools/call', {'name': 'crawl'})['error']['code'] == -32602
    for req in ({'jsonrpc': '2.0', 'method': 'notifications/initialized'},
                {'jsonrpc': '2.0', 'method': 'notifications/cancelled', 'params': {'requestId': 1}},
                {'jsonrpc': '2.0', 'id': 1, 'result': {}}):
        assert protocol.dispatch(req, server.list_tools, server.call_tool) is None
    assert protocol.dispatch(rpc('ping', [] ) | {'params': []}, server.list_tools, server.call_tool)['error']['code'] == -32602
    with pytest.raises(ValueError):
        protocol.loads('{"x":NaN}')


@pytest.mark.parametrize('patch_args', [
    {'lat': 12}, {'lon': 120}, {'lat': True}, {'lat': float('nan')}, {'lon': float('inf')},
    {'dwell_min': 0}, {'dwell_min': 2161}, {'dwell_min': 1.5}, {'intent': 'crawl'},
    {'rain_mm_per_h': -1}, {'rain_mm_per_h': 301}, {'label': ''}, {'label': 'x' * 301},
    {'vehicle_id': ''}, {'arrive_at': '2026-10-17T18:00:00'}, {'arrive_at': 'tomorrow'},
    {'arrive_at': '1800-01-01T00:00:00+07:00'}, {'extra': 'untrusted'}, {'arrive_at': '2026-10-17T18:00:00+19:00'},
    {'arrive_at': '2026-10-17T18:00:00+07'}, {'dwell_min': 10**400},
])
def test_plan_invalid_input_never_executes(patch_args):
    args = {**ARGS, **patch_args}
    with patch.object(server, 'call_tool') as call:
        result = dispatch('tools/call', {'name': 'plan_arrival', 'arguments': args}, call)
    assert result['error']['code'] == -32602
    call.assert_not_called()


def test_tight_catalogue_and_schema_examples():
    tools = dispatch('tools/list')['result']['tools']
    assert {t['name'] for t in tools} == {'find_place', 'plan_arrival', 'check_alley_fit',
                                       'find_nearby_stops', 'list_vehicles', 'tide_levels'}
    for tool in tools:
        assert tool['annotations']['readOnlyHint'] is True
        assert tool['inputSchema']['additionalProperties'] is False
        assert 'Example:' in tool['description']
    result = dispatch('tools/call', {'name': 'list_vehicles', 'arguments': {}})
    assert result['result']['isError'] is False
    assert len(protocol.dumps(result).encode()) < 65_000
    data = result['result']['structuredContent']
    assert {'class-xs', 'class-s', 'class-m', 'class-l', 'class-xl', 'toyota-fortuner'} <= {p['id'] for p in data['vehicles']}
    for vehicle in data['vehicles']:
        if 'source_ref' in vehicle:
            assert data['sources'][vehicle['source_ref']].startswith('https://')


def test_tool_errors_do_not_leak_provider_credentials():
    def broken(*_):
        raise ValueError('https://provider.invalid/?key=NEVER-EXPOSE-THIS')
    result = dispatch('tools/call', {'name': 'list_vehicles'}, broken)
    assert result['result']['isError']
    assert 'NEVER-EXPOSE' not in json.dumps(result)
    assert result['result']['structuredContent']['error'] == 'tool_unavailable'


def test_http_media_origin_session_and_response_semantics(monkeypatch):
    client = TestClient(main.app)
    assert client.get('/mcp').status_code == 405
    assert client.delete('/mcp').headers['allow'] == 'POST'
    assert client.post('/mcp', headers=HEADERS, content='broken').status_code == 415
    assert client.post('/mcp', headers=HEADERS, json=rpc('ping')).status_code == 200
    assert client.post('/mcp', headers={'Accept': 'application/json'}, json=rpc('ping')).status_code == 406
    assert client.post('/mcp', headers={**HEADERS, 'Accept': 'application/json;q=0, text/event-stream'}, json=rpc('ping')).status_code == 406
    assert client.post('/mcp', headers={**HEADERS, 'Origin': 'https://evil.example'}, json=rpc('ping')).status_code == 403
    assert client.get('/mcp', headers={'Origin': 'null'}).status_code == 403
    monkeypatch.setenv('MCP_ALLOWED_ORIGINS', 'https://inspector.example')
    assert client.post('/mcp', headers={**HEADERS, 'Origin': 'https://inspector.example'}, json=rpc('ping')).status_code == 200
    for sid in ('', 'white space', '\tbad'):
        assert client.post('/mcp', headers={**HEADERS, 'Mcp-Session-Id': sid}, json=rpc('ping')).status_code == 400
    response = client.post('/mcp', headers={**HEADERS, 'Mcp-Session-Id': 'client-supplied-valid'}, json=rpc('ping'))
    assert response.status_code == 200
    assert 'mcp-session-id' not in response.headers
    for req in ({'jsonrpc': '2.0', 'method': 'notifications/initialized'}, {'jsonrpc': '2.0', 'id': 1, 'result': {}}):
        response = client.post('/mcp', headers=HEADERS, json=req)
        assert response.status_code == 202 and response.content == b''
    assert client.post('/mcp', headers={**HEADERS, 'MCP-Protocol-Version': 'bad'}, json=rpc('ping')).status_code == 400
    response = client.post('/mcp', headers={**HEADERS, 'Content-Type': 'application/json'}, content='{')
    assert response.status_code == 400 and response.json()['error']['code'] == -32700
    assert client.post('/mcp', headers={**HEADERS, 'Content-Type': 'application/json'}, content='x' * 64_001).status_code == 413
    monkeypatch.setenv('MCP_AUTH_TOKEN', 'offline-token')
    assert client.post('/mcp', headers=HEADERS, json=rpc('ping')).status_code == 401
    assert client.post('/mcp', headers={**HEADERS, 'Authorization': 'Bearer offline-token'}, json=rpc('ping')).status_code == 200


def test_rate_limit_is_per_client_and_bounded():
    client = TestClient(main.app)
    for _ in range(60):
        assert client.post('/mcp', headers=HEADERS, json=rpc('ping')).status_code == 200
    response = client.post('/mcp', headers={**HEADERS, 'X-Forwarded-For': 'different-ip'}, json=rpc('ping'))
    assert response.status_code == 429 and response.headers['retry-after'] == '60'
    limiter = protocol.RateLimiter(limit=2, window=60, max_clients=2)
    assert limiter.allow('a', 0) and limiter.allow('a', 1)
    assert not limiter.allow('a', 2)
    assert limiter.allow('b', 2)
    assert not limiter.allow('c', 3)
    assert limiter.allow('a', 61)
    assert limiter.allow('c', 63)


def stop_fixture():
    return {'name': 'Fixture alley', 'kind': 'door', 'way_id': 42, 'lat': 10.79, 'lon': 106.71,
            'ok': False, 'verified': False,
            'estimate': {'answer': 'no', 'access_answer': 'fits', 'legal_status': 'Prohibited',
                         'confidence': 'low', 'basis': 'Only a width estimate'},
            'fit': {'class': 'unknown', 'width_range': {'lo': 2.2, 'hi': 3.4, 'top_tier': 'Official',
                    'width_basis': 'parcel_gap_estimate', 'decisive_clearance': False,
                    'evidence': [{'tier': 'Official', 'source': 'Fixture parcels', 'url': 'https://example.org/citation'}]}},
            'walk': {'meters': 25, 'minutes': 1, 'geometry': [[106, 10]]},
            'way_out': {'mode': 'unknown', 'manoeuvre_status': 'unknown', 'geometry': [[106, 10]]},
            'flood': {'stay': {'status': 'unknown'}},
            'legality': {'status': 'Prohibited', 'rules': [{'text': 'Cấm đỗ', 'citation': 'Fixture law article 18'}]},
            'unverified_reasons': ['Missing exit survey'], 'failure_codes': ['legality'], 'fail_reasons': ['Cấm đỗ']}


def plan_fixture():
    stop = stop_fixture()
    return {'destination': {'label': 'Fixture', 'lat': 10.79, 'lon': 106.71},
            'vehicle': {'id': 'toyota-fortuner', 'label': 'Fortuner', 'mirror_width': 2.1},
            'verdict': {'headline': 'Chưa xác minh', 'estimate': copy.deepcopy(stop['estimate'])},
            'window': {'tide_arrive': {'level_m': None}, 'tide_depart': {'level_m': None}},
            'stop_points': [copy.deepcopy(stop)], 'door': stop,
            'layers': {'type': 'FeatureCollection', 'features': []}}


def test_projection_preserves_safety_and_citations_without_geometry():
    raw = plan_fixture()
    result = server.compact_plan(raw)
    assert result['verdict'] == raw['verdict']
    assert result['door']['estimate']['access_answer'] == 'fits'
    assert result['door']['legality']['rules'] == raw['door']['legality']['rules']
    assert result['door']['fit']['width_range']['evidence'][0]['tier'] == 'Official'
    assert result['door']['way_out']['mode'] == 'unknown'
    assert result['door']['flood']['stay']['status'] == 'unknown'
    assert 'tide_note' in result
    assert 'geometry' not in json.dumps(result) and 'FeatureCollection' not in json.dumps(result)
    assert 'door' not in server.compact_plan(raw, stops_only=True)
    assert 'standard_route' not in server.compact_plan(raw, stops_only=True)


def test_cache_miss_refuses_plan_and_crawl():
    with patch('app.osm.cached_graph', return_value=None), patch('app.plan.plan') as plan, patch('app.live.schedule') as build:
        result = server._execute('plan_arrival', ARGS)
    assert result['error'] == 'area_not_cached'
    plan.assert_not_called()
    build.assert_not_called()


def test_plan_adapter_uses_merged_engine_without_model_calls():
    with patch('app.osm.cached_graph', return_value=object()), patch('app.live.area_status', return_value=(None, {})), \
         patch('app.plan.plan', return_value=plan_fixture()) as plan:
        result = server._execute('plan_arrival', ARGS)
        stops = server._execute('find_nearby_stops', ARGS)
    assert result['verdict']['estimate']['access_answer'] == 'fits'
    assert 'door' not in stops
    assert plan.call_args.args[2] == 'toyota-fortuner'
    assert plan.call_args.args[4].utcoffset().total_seconds() == 7 * 3600
    assert 'origin' not in plan.call_args.kwargs


def test_oversize_fails_explicitly_and_keeps_small_envelope():
    result = dispatch('tools/call', {'name': 'list_vehicles'}, lambda *_: {'large': 'x' * 70_000})
    assert result['result']['isError']
    assert len(protocol.dumps(result).encode()) < 65_000


def test_real_merged_engine_shape_fits_entire_response_budget():
    from pathlib import Path
    fixture = Path(__file__).resolve().parents[2] / 'mcp' / 'testdata' / 'arrival_plan.json'
    raw = json.loads(fixture.read_text())
    data = server.compact_plan(raw)
    result = dispatch('tools/call', {'name': 'plan_arrival', 'arguments': ARGS}, lambda *_: data)
    assert not result['result']['isError']
    assert len(protocol.dumps(result).encode()) < 65_000
    assert data['verdict'] == server._omit_optional_nulls(raw['verdict'])
    assert data['door']['unverified_reasons'] == raw['door']['unverified_reasons']
    assert data['stop_points'][0]['legality'] == raw['stop_points'][0]['legality']
    shown = len(data['stop_points'])
    assert data.get('omitted_stop_points_count', 0) == max(0, len(raw['stop_points']) - shown)


def test_search_and_tide_adapters_are_read_only_and_filter_area():
    places = {'results': [
        {'label': 'Fixture HCMC', 'lat': 10.8, 'lon': 106.7},
        {'label': 'Outside', 'lat': 21.0, 'lon': 105.8}], 'requires_clarification': False}
    with patch.object(agent, 'resolve_place', return_value=places):
        found = server._execute('find_place', {'query': 'Fixture'})
    assert [p['label'] for p in found['results']] == ['Fixture HCMC']
    tide = {'extrema': [], 'highest': None, 'missing_points': 97, 'note': 'No coverage'}
    with patch.object(agent, 'execute', return_value=(tide, None)) as execute:
        assert server._execute('tide_levels', {'start': ARGS['arrive_at']}) == tide
    execute.assert_called_once_with('muc_trieu', {'start': ARGS['arrive_at']})


def test_single_alley_reads_engine_and_discloses_limited_scope():
    from types import SimpleNamespace
    width = SimpleNamespace(to_json=lambda: {'lo': 3.1, 'hi': 3.7, 'top_tier': 'Official',
                'evidence': [{'tier': 'Official', 'source': 'Fixture', 'url': 'https://example.org/source'}]})
    with patch('app.osm.cached_graph', return_value=object()), patch('app.live.area_status', return_value=(None, {})), \
         patch('app.plan.area', return_value=(object(), {42: width}, {})), \
         patch('app.plan.compute_fit', return_value=({42: 'unknown'}, {})), \
         patch('app.plan._width_estimate', return_value=3.4):
        result = server._execute('check_alley_fit', {'lat': 10.8, 'lon': 106.7, 'way_id': 42, 'vehicle_id': 'Fortuner'})
    assert result['fit'] == 'unknown'
    assert result['estimate']['confidence'] == 'low'
    assert result['width_range']['evidence'][0]['tier'] == 'Official'
    assert 'not a full-route' in result['scope']


@pytest.mark.parametrize('legacy,canonical', list(protocol.TOOL_ALIASES.items()))
def test_legacy_aliases_resolve_without_duplicate_listings(legacy, canonical):
    schema = next(t['inputSchema'] for t in server.list_tools() if t['name'] == canonical)
    examples = {'find_place': {'query': 'Fixture place'},
                'check_alley_fit': {'lat': 10.8, 'lon': 106.7, 'way_id': 42, 'vehicle_id': 'Fortuner'},
                'tide_levels': {'start': ARGS['arrive_at']}, 'list_vehicles': {}}
    args = examples.get(canonical, ARGS)
    with patch.object(server, 'call_tool', return_value={'verdict': {'headline': 'Chưa xác minh',
                           'estimate': {'answer': 'unknown', 'confidence': 'low'}}}) as call:
        result = dispatch('tools/call', {'name': legacy, 'arguments': args}, call)
    call.assert_called_once_with(canonical, args)
    assert not result['result']['isError']
    assert legacy not in {t['name'] for t in server.list_tools()}
    assert result['result']['content'][0]['text'].isascii()
    assert 'Chưa' not in result['result']['content'][0]['text']


def test_english_text_does_not_echo_source_prose_or_raw_errors():
    data = {'verdict': {'headline': 'Chưa đủ bằng chứng', 'estimate': {'answer': 'tight', 'confidence': 'low'}}}
    result = dispatch('tools/call', {'name': 'plan_arrival', 'arguments': ARGS}, lambda *_: data)
    text = result['result']['content'][0]['text']
    assert text.startswith('Arrival estimate: tight. Confidence: low.')
    assert text.isascii()
    # Preserve cited engine/source material in structured data, without presenting
    # it as untranslated MCP text or attempting an unverified legal translation.
    assert result['result']['structuredContent'] == data
    result = dispatch('tools/call', {'name': 'list_vehicles'}, lambda *_: {'error': 'Lỗi nguồn chưa sẵn sàng'})
    assert result['result']['isError']
    assert result['result']['content'][0]['text'].isascii()
