"""Shared-route estimates: nested width thresholds, real coordinates, HTTP shape."""
from copy import deepcopy
from datetime import datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app import evidence, flags, plan, vehicles
from .test_engine_routes import graph, candidate

ARRIVE = datetime.fromisoformat('2026-10-17T14:00:00+07:00')
IDS = ['class-xs', 'class-s', 'class-m', 'class-l', 'class-xl', 'toyota-fortuner', 'vinfast-vf-3']
ORDER = {'no': 0, 'unknown': 1, 'tight': 2, 'fits': 3}


@pytest.fixture
def detour(monkeypatch):
    g = graph({1: (-100, 0), 2: (0, 0), 3: (100, 0), 4: (0, 100), 5: (100, 100),
               6: (200, 0), 7: (200, 200), 8: (100, 200), 9: (150, 100)}, [
        (10, [1, 2, 3], {'highway': 'tertiary'}), (20, [2, 4, 5], {}),
        (30, [3, 6, 7, 8, 5], {}), (50, [5, 9], {})])
    ws = {wid: evidence.WidthRange(5, 5.2, 'Measured', [
        evidence.Bound(5, 5.2, 'Measured', 'Fixture clear-width survey', '', coverage_complete=True)],
        decisive_clearance=True) for wid in g.ways}
    ws[10] = evidence.WidthRange(8, 8.2, 'Measured', [
        evidence.Bound(8, 8.2, 'Measured', 'Fixture street survey', '', coverage_complete=True)],
        decisive_clearance=True)
    ws[20] = evidence.WidthRange(0, 2.2, 'Official', [
        evidence.Bound(0, 2.2, 'Official', 'Partial survey', '', coverage_complete=False, estimate_m=1.87)])
    calls = []
    def area(*args, **kwargs):
        calls.append((args, kwargs))
        return g, ws, {}
    monkeypatch.setattr(plan, 'area', area)
    monkeypatch.setattr(plan, 'GOONG_API_KEY', '')
    monkeypatch.setattr(plan, '_candidate_legality', lambda *args: ('Permitted', []))
    monkeypatch.setattr(flags, 'enabled', lambda name: False)
    return g, ws, candidate(g, 50, 25), calls


def compare(c, ids=IDS):
    return plan.compare_vehicles(c.lat, c.lon, 'park', ARRIVE, 60, [], 'Door', ids)


def test_smaller_car_evaluates_wider_cars_feasible_detour(detour):
    g, ws, c, _ = detour
    output = {}
    for vid in ('toyota-fortuner', 'vinfast-vf-3'):
        r = plan.plan(c.lat, c.lon, vid, 'park', ARRIVE, 60)
        output[vid] = r
        assert r['door']['estimate']['answer'] == 'fits'
        assert r['verdict']['estimate']['answer'] == 'fits'
        assert r['verdict']['profile']
        assert r['verdict']['decided_by'] in ('width', 'way_out', 'flood', 'legal', 'walk')
    assert ORDER[output['vinfast-vf-3']['door']['estimate']['answer']] >= ORDER[
        output['toyota-fortuner']['door']['estimate']['answer']]
    assert output['vinfast-vf-3']['stop_points'][0]['walk']['meters'] <= output[
        'toyota-fortuner']['stop_points'][0]['walk']['meters']


def test_compare_reuses_area_and_same_route_for_every_vehicle(detour):
    g, ws, c, calls = detour
    snapshot = deepcopy(ws)
    r = compare(c)
    assert len(calls) == 1
    assert {v['vehicle_id'] for v in r['vehicles']} == set(IDS)
    assert all(s['way_id'] != 20 for s in r['profile'])
    assert all(v['answer'] == 'fits' for v in r['vehicles'])
    for vehicle in r['vehicles']:
        p = vehicles.get_profile(vehicle['vehicle_id'])
        assert vehicle['needed_m'] == pytest.approx(p.fits_min)
        assert vehicle['thresholds_m']['tight'] == pytest.approx(p.tight_min)
        assert vehicle['thresholds_m']['door'] == pytest.approx(p.door_min)
    assert ws == snapshot
    r2 = compare(c, list(reversed(IDS)))
    assert r['profile'] == r2['profile']
    assert r['route_in'] == r2['route_in']
    assert {v['vehicle_id']: v['answer'] for v in r['vehicles']} == {
        v['vehicle_id']: v['answer'] for v in r2['vehicles']}


def test_profile_is_ordered_and_preserves_partial_edge_metres(detour):
    g, _, c, _ = detour
    r = compare(c)
    total = 0
    for segment in r['profile']:
        assert segment['start_m'] == pytest.approx(total, abs=.02)
        assert set(('way_id', 'name', 'length_m', 'start_m', 'width_lo', 'width_hi',
                    'estimate_m', 'tier', 'source', 'sampled')) <= segment.keys()
        total += segment['length_m']
    assert total == pytest.approx(r['route_in']['meters'], abs=1)
    assert r['profile'][-1]['length_m'] == pytest.approx(c.offset, abs=.02)


@pytest.mark.parametrize('width', [1.8, 2.4, 2.9, 3.2, 3.5, 4])
def test_width_thresholds_are_monotone_including_door_space(detour, width):
    g, ws, c, _ = detour
    ws[50] = evidence.WidthRange(0, width+.3, 'Official', [
        evidence.Bound(0, width+.3, 'Official', 'Sampled door', '', estimate_m=width)])
    r = compare(c)
    ordered = sorted(r['vehicles'], key=lambda v: v['mirror_width'])
    assert all(ORDER[a['answer']] >= ORDER[b['answer']] for a, b in zip(ordered, ordered[1:]))
    assert len({v['answer'] for v in ordered}) > 1 or width in (1.8, 2.4, 4)


def test_compare_http_defaults_validation_and_explicit_selection(detour, monkeypatch):
    from app.main import app
    from app import live
    monkeypatch.setattr(live, 'area_status', lambda *args: (None, {'key': 'fixture', 'state': 'missing'}))
    _, _, c, _ = detour
    client = TestClient(app)
    body = {'lat': c.lat, 'lon': c.lon, 'vehicle_id': 'toyota-fortuner',
            'arrive_at': ARRIVE.isoformat(), 'dwell_min': 60}
    response = client.post('/api/plan/compare', json=body)
    assert response.status_code == 200, response.text
    assert len(response.json()['vehicles']) == 6
    body['vehicle_ids'] = ['vinfast-vf-3', 'toyota-fortuner', 'vinfast-vf-3']
    response = client.post('/api/plan/compare', json=body)
    assert [v['vehicle_id'] for v in response.json()['vehicles']] == ['vinfast-vf-3', 'toyota-fortuner']
    assert client.post('/api/plan/compare', json={**body, 'vehicle_ids': ['missing']}).status_code == 404
    assert client.post('/api/plan/compare', json={**body, 'vehicle_ids': []}).status_code == 422
    assert client.post('/api/plan/compare', json={**body, 'lat': 0}).status_code == 422


def test_width_negative_is_not_relabelled_unknown_by_missing_exit(detour):
    g, ws, c, _ = detour
    ws[50] = evidence.WidthRange(0, 2.3, 'Inferred', [
        evidence.Bound(0, 2.3, 'Inferred', 'Sampled gap', '', estimate_m=2)])
    shared = plan._SharedRoutes(g, ws)
    route = shared.route(c)
    checks = {'route_in': route, 'way_out': {'mode': 'none', '_segments': []},
              'fit': {'class': 'unknown'}, 'flood': {'stay': {'status': 'risky'}},
              'legality': {'status': 'Unverified', 'rules': []}}
    r = plan._estimate(c, g, ws, vehicles.get_profile('vinfast-vf-3'), checks, ['No suitable exit'])
    assert (r['answer'], r['confidence'], r['decided_by']) == ('no', 'low', 'width')



def test_zero_length_door_edge_still_counts_its_validated_width_sample(detour):
    g, ws, c, _ = detour
    c.offset = 0
    route = {'strict': False, '_segments': [(c.edge_idx, 0)], 'way_ids': [c.way_id]}
    checks = {'route_in': route, 'way_out': {'mode': 'none', '_segments': []},
              'legality': {'status': 'Unverified', 'rules': []}, 'flood': {'stay': {'status': 'risky'}}}
    estimate = plan._estimate(c, g, ws, vehicles.get_profile('vinfast-vf-3'), checks, [])
    assert estimate['coverage']['sampled_segments'] == 1
    assert estimate['coverage']['sample_supported_fraction'] == 1
    profile = plan._segment_profile(g, ws, route)
    assert profile == []  # no driven distance; do not emit a zero-width chart segment
    assert plan._segment_profile(g, ws, {**route, '_segments': [(c.edge_idx, .004)]}) == []



def test_comparison_does_not_present_missing_exit_as_positive_access(detour, monkeypatch):
    _, _, c, _ = detour
    monkeypatch.setattr(plan._SharedRoutes, 'exit', lambda self, candidate, route: {
        'mode': 'none', 'strict': False, 'text': 'Exit unverified',
        'way_ids': [], 'edge_ids': [], '_segments': []})
    r = compare(c)
    assert all(v['answer'] == 'unknown' and v['confidence'] == 'low' and
               v['decided_by'] == 'way_out' for v in r['vehicles'])


def test_shared_exit_finds_wide_forward_loop_before_narrow_shortcut(monkeypatch):
    g = graph({1: (-100, 0), 2: (0, 0), 3: (100, 0), 4: (200, 0), 5: (300, 0),
               6: (100, 100), 7: (100, 200), 8: (200, 200), 9: (200, 100)}, [
        (10, [1, 2, 3, 4, 5], {'highway': 'tertiary'}), (30, [3, 6], {}),
        (50, [6, 7], {}), (40, [7, 8, 9, 4], {}), (20, [7, 2], {})])
    ws = {wid: evidence.WidthRange(0, 5.3, 'Official', [
        evidence.Bound(0, 5.3, 'Official', 'Portal fixture', '', estimate_m=5)]) for wid in g.ways}
    ws[20] = evidence.WidthRange(0, 2.2, 'Official', [
        evidence.Bound(0, 2.2, 'Official', 'Narrow shortcut', '', estimate_m=1.87)])
    c = candidate(g, 50, 80)
    shared = plan._SharedRoutes(g, ws)
    exit_route = shared.exit(c, shared.route(c))
    assert exit_route['mode'] == 'through'
    assert 40 in exit_route['way_ids'] and 20 not in exit_route['way_ids']


def test_entry_and_exit_are_ranked_together_for_smaller_vehicle(monkeypatch):
    g = graph({1: (-100, 0), 2: (0, 0), 3: (100, 0), 4: (200, 0), 5: (300, 0),
               6: (100, 100), 7: (100, 200), 9: (300, 200)}, [
        (10, [1, 2, 3, 4, 5], {'highway': 'tertiary'}),
        (30, [3, 9, 7], {'oneway': 'yes'}), (40, [4, 6], {}), (50, [6, 7], {})])
    ws = {wid: evidence.WidthRange(0, 5.3, 'Official', [
        evidence.Bound(0, 5.3, 'Official', 'Portal fixture', '', estimate_m=5)]) for wid in g.ways}
    ws[40] = evidence.WidthRange(0, 3.5, 'Official', [
        evidence.Bound(0, 3.5, 'Official', 'Narrow approach', '', estimate_m=3.2)])
    c = candidate(g, 50, 80)
    monkeypatch.setattr(plan, 'area', lambda *a, **kw: (g, ws, {}))
    monkeypatch.setattr(plan, 'GOONG_API_KEY', '')
    monkeypatch.setattr(flags, 'enabled', lambda name: False)
    monkeypatch.setattr(plan, '_candidate_legality', lambda *a: ('Permitted', []))
    out = {vid: plan.plan(c.lat, c.lon, vid, 'park', ARRIVE, 60) for vid in
           ('vinfast-vf-3', 'toyota-fortuner')}
    assert out['vinfast-vf-3']['door']['estimate']['answer'] == 'fits'
    assert out['toyota-fortuner']['door']['estimate']['answer'] == 'tight'
