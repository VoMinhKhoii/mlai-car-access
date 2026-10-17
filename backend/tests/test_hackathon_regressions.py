"""Offline regressions from the hackathon product review."""
import json
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import corridor, evidence, main, osm, plan, reports
from app.evidence import WidthRange
from app.flood import DepthRange

VN = timezone(timedelta(hours=7))
NOW = datetime(2026, 10, 17, 1, tzinfo=VN)


def straight_graph():
    return osm.graph_from_elements(10.8, 106.71, [
        {'type': 'node', 'id': 1, 'lat': 10.8, 'lon': 106.71},
        {'type': 'node', 'id': 2, 'lat': 10.8, 'lon': 106.716},
        {'type': 'way', 'id': 10, 'nodes': [1, 2],
         'tags': {'highway': 'tertiary', 'name': 'Fixture Road'}},
    ], 'review-fixture')


def test_door_on_long_walk_edge_is_not_excluded_by_a_fake_endpoint_detour():
    g = straight_graph()
    widths = {10: WidthRange(8, 9, 'Measured')}
    with (patch.object(plan, 'area', return_value=(g, widths, {})),
          patch.object(plan.flags, 'enabled', return_value=False),
          patch.object(plan.parking_data, 'paid_street_ways', return_value={}),
          patch.object(plan.parking_data, 'lots_near', return_value=[]),
          patch.object(plan, 'GOONG_API_KEY', ''),
          patch.object(plan, '_layers', return_value={})):
        result = plan.plan(10.8, 106.713, 'toyota-vios', 'pickup', NOW, 15)
    assert result['door'] is not None
    assert result['door']['walk']['meters'] == 0


def test_same_edge_walk_geometry_uses_the_direct_subsegment():
    g = straight_graph()
    edge = g.edges[0]
    offset = edge.length / 2
    lat, lon = plan._interp(g, edge.u, edge.v, offset - 10, edge.length)
    c = plan.Candidate('street', lat, lon, 'stop', 10,
                       data={'walk_edge_idx': 0, 'walk_offset': offset - 10})
    coords = plan._walk_geometry(g, c, {}, {1: offset, 2: offset}, edge, offset, 10.8, 106.713)
    assert len(coords) == 2
    assert osm.haversine(coords[0][1], coords[0][0], coords[1][1], coords[1][0]) == pytest.approx(10)


def test_same_edge_walk_counts_the_destination_connector_once():
    g = straight_graph()
    widths = {10: WidthRange(8, 9, 'Measured')}
    # The stop is on the road, while the destination is 20 m off it.
    destination = (10.8 + 20 / 110540, 106.713)
    with (patch.object(plan, 'area', return_value=(g, widths, {})),
          patch.object(plan.flags, 'enabled', return_value=False),
          patch.object(plan.parking_data, 'paid_street_ways', return_value={}),
          patch.object(plan.parking_data, 'lots_near', return_value=[]),
          patch.object(plan, 'GOONG_API_KEY', ''),
          patch.object(plan, '_layers', return_value={})):
        result = plan.plan(*destination, 'toyota-vios', 'pickup', NOW, 15)
    door = result['door']
    assert door is not None
    assert door['walk']['meters'] == 20
    assert door['walk']['connection']['stop_to_walk_m'] == 0
    assert door['walk']['connection']['destination_to_walk_m'] == pytest.approx(20)
    assert door['walk']['connection']['mapped'] is False


def test_walk_wading_includes_partial_edge_absent_from_predecessor_tree():
    g = straight_graph()
    edge = g.edges[0]
    offset = edge.length / 2
    lat, lon = plan._interp(g, edge.u, edge.v, offset - 10, edge.length)
    c = plan.Candidate('street', lat, lon, 'stop', 10,
                       data={'walk_edge_idx': 0, 'walk_offset': offset - 10})
    snapshot = SimpleNamespace(assess=lambda *args: SimpleNamespace(depth=DepthRange(.2, .3, [], True, False)))
    result = plan._walk_wade(g, {}, c, {}, {1: offset, 2: offset}, NOW, [], snapshot, .2, edge, offset)
    assert result['label'] == 'Walk through floodwater'
    assert result['hi'] == .3


def test_review_pagination_survives_cursor_report_being_approved(tmp_path):
    with patch.object(reports, 'PENDING_FILE', tmp_path / 'pending.json'):
        first = reports.submit('stop_rule', {}, 'fixture', report_id='a')
        second = reports.submit('stop_rule', {}, 'fixture', report_id='b')
        page = reports.list_reports('pending', limit=1)
        assert page['next_cursor'] == first['report_id']
        reports.decide(first['report_id'], True, 'operator')
        next_page = reports.list_reports('pending', cursor=page['next_cursor'], limit=1)
        assert [r['report_id'] for r in next_page['items']] == [second['report_id']]


def test_blockage_submission_and_expiry_use_the_vietnam_day(tmp_path):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz or timezone.utc)

    class ServerDate(date):
        @classmethod
        def today(cls):
            return NOW.astimezone(timezone.utc).date()

    client_request = type('Request', (), {'client': None})()
    captured = {}
    def submit(kind, payload, source):
        captured.update(payload)
        return {'report_id': 'fixture'}

    with (patch.object(main, 'datetime', Clock), patch.object(main, 'date', ServerDate, create=True),
          patch.object(main, '_guest_limit'), patch.object(main, '_graph_with'),
          patch.object(main.reports, 'submit', side_effect=submit)):
        main.blockage(main.Blockage(lat=10.8, lon=106.71, way_id=10, reason='obstruction'), client_request)
    assert captured['date'] == '2026-10-17'
    path = tmp_path / 'blockages.jsonl'
    path.write_text(json.dumps({'way_id': 10, 'date': '2026-10-16'}) + '\n')
    with (patch.object(evidence, 'BLOCKAGE_FILE', path),
          patch.object(evidence, 'date', ServerDate, create=True),
          patch.object(evidence, 'datetime', Clock, create=True)):
        assert evidence.blocked_ways_today() == {}
        path.write_text(json.dumps({'way_id': 10, 'date': '2026-10-17'}) + '\n')
        assert 10 in evidence.blocked_ways_today()


@pytest.mark.parametrize('legs', [[], [{'steps': []}], [{'steps': [{'polyline': {'points': '~'}}]}]])
def test_invalid_goong_geometry_fails_as_unavailable_instead_of_crashing(legs):
    with patch.object(corridor, 'CACHED_ONLY', False), \
            patch.object(corridor, 'goong_direction', return_value={'routes': [{'legs': legs}]}):
        assert corridor.goong_route((10.8, 106.7), (10.8, 106.72)) is None


def test_valid_goong_geometry_passes_finite_coordinate_and_metric_checks():
    legs = [{'steps': [{'polyline': {'points': '_p~iF~ps|U_ulLnnqC_mqNvxq`@'},
                        'distance': {'value': 200}}],
             'distance': {'value': 200}, 'duration': {'value': 30}}]
    with patch.object(corridor, 'CACHED_ONLY', False), \
            patch.object(corridor, 'goong_direction', return_value={'routes': [{'legs': legs}]}):
        result = corridor.goong_route((10.8, 106.7), (10.8, 106.72))
    assert len(result['geometry']) == 3
    assert result['distance_m'] == 200
    assert result['duration_s'] == 30


def test_goong_direction_rotates_past_an_exhausted_key():
    from app import geocoding
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params['api_key'])
        code = 429 if params['api_key'] == 'dead' else 200
        return SimpleNamespace(status_code=code, is_error=code >= 400, json=lambda: {'routes': [{'legs': []}]})

    with patch.object(geocoding, '_goong_keys', return_value=['dead', 'live']), \
            patch.object(geocoding, 'goong_blocked_until', return_value=0), \
            patch.object(geocoding, 'block_goong') as block, patch.object(geocoding.httpx, 'get', fake_get):
        body = geocoding.goong_direction({'origin': '10.8,106.7', 'destination': '10.8,106.72'})
    assert body == {'routes': [{'legs': []}]}
    assert calls == ['dead', 'live']
    block.assert_called_once_with(api_key='dead', daily=True)
