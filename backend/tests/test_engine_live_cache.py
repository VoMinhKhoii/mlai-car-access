"""HTTP regressions for server-owned legacy parcel cache compatibility.

The production area loader, graph loader, evidence view and cut validation run
unchanged through FastAPI. Only filesystem paths/feature flags are isolated.
"""
import copy
from datetime import datetime, timedelta
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import flags, live, osm, plan
from app.storage import LRU


CASE = json.loads((Path(__file__).parent/'fixtures/engine_regressions.json').read_text())['cases'][0]
LAT, LON = 10.7889312, 106.697545
KEY, WAY = '10.788_106.696', 35115025


@pytest.fixture
def cached_http(tmp_path, monkeypatch):
    from app.main import app
    cache = tmp_path/'cache'
    (cache/'osm').mkdir(parents=True)
    (cache/'osm'/f'area_{KEY}.json').write_text(json.dumps({'elements': CASE['elements']}))
    areas = cache/'live/areas'
    areas.mkdir(parents=True)
    finished = datetime.now(live.VN_TZ)-timedelta(hours=2)
    record = {'key': KEY, 'status': {'key': KEY, 'state': 'done', 'error': None,
        'finished_at': finished.isoformat(), 'steps': {'parcels': {'state': 'done'}}, 'counts': {}},
        'parcels': copy.deepcopy(CASE['parcels']),
        'listings': [{'osm_way_id': WAY, 'width_m': 99, 'source': 'Legacy unreviewed listing'}],
        'photos': [{'id': 'unreviewed', 'way_id': WAY, 'status': 'approved', 'width_m': 99,
                    'gate': 'ACCEPT', 'shows_alley': True}], 'news': []}
    path = areas/f'{KEY}.json'
    path.write_text(json.dumps(record))
    for module, name, value in [
        (osm, 'CACHE', cache), (osm, '_GRAPHS', LRU(32)), (osm, '_GRAPH_STAMPS', {}),
        (live, 'AREAS_DIR', areas), (live, 'CITY_PARCELS', cache/'live/city_parcels.json'),
        (live, 'PHOTO_REVIEWS', tmp_path/'reviews.json'), (live, '_areas', LRU(32)),
        (live, '_plan_cache', LRU(32)), (live, '_jobs', {}),
        (plan, '_WR', LRU(32)), (plan, '_FP', LRU(32)), (plan, 'GOONG_API_KEY', ''),
        (flags, '_state', {k: k == 'parcel_widths' for k in flags.AI_FEATURES}),
    ]:
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(osm, '_fetch_overpass', lambda *a, **k: pytest.fail('Network forbidden'))
    return TestClient(app), path, record


def test_ministop_legacy_cache_reaches_http_evidence_and_plan(cached_http):
    client, path, record = cached_http
    original = path.read_bytes()
    response = client.post(f'/api/evidence/way/{WAY}', json={'lat': LAT, 'lon': LON})
    assert response.status_code == 200
    data = response.json()
    width = data['width_range']
    parcel = next(b for b in width['evidence'] if b['ai_feature'] == 'parcel_widths')
    assert parcel['sample_quality']['accepted_cuts'] == 5
    assert parcel['sample_quality']['rejected_cuts'] == []
    assert parcel['estimate_m'] == 5.56
    assert parcel['tier'] == 'Inferred'  # Automatic geometry does not become Official clearance.
    assert width['sampled_estimate']['lo'] == 5.26
    assert width['sampled_estimate']['hi'] == 5.86
    assert width['lo'] == 0 and not width['decisive_clearance']
    assert not data['photos']
    assert not any('Legacy unreviewed' in b['source'] for b in width['evidence'])
    result = client.post('/api/plan', json={'lat': LAT, 'lon': LON, 'vehicle_id': 'class-m',
        'intent': 'park', 'dwell_min': 120, 'arrive_at': '2026-10-17T12:00:00+07:00'})
    assert result.status_code == 200
    result = result.json()
    estimate = result['door']['estimate']
    assert estimate['stop_width']['value_m'] == 5.56
    assert estimate['limiting_width']['value_m'] == 3.58
    assert estimate['coverage']['all_sampled_segments'] == 6
    assert estimate['coverage']['total_segments'] == 10
    assert (estimate['answer'], estimate['confidence']) == ('fits', 'low')
    assert not result['door']['verified']
    assert result['area']['state'] == 'partial'
    assert datetime.fromisoformat(result['area']['expires_at']) == (
        datetime.fromisoformat(record['status']['finished_at']) + live.TTL)
    assert path.read_bytes() == original  # Read compatibility never refreshes or rewrites evidence.


@pytest.mark.parametrize('mutation,expected_state', [
    ('expired', 'stale'), ('missing_time', 'missing'), ('naive_time', 'missing'),
    ('future_time', 'missing'), ('unfinished', 'missing'), ('wrong_key', 'missing'),
    ('unknown_schema', 'missing'),
])
def test_legacy_cache_fails_closed_without_fresh_completed_server_record(cached_http, mutation, expected_state):
    client, path, record = cached_http
    if mutation == 'expired':
        record['status']['finished_at'] = (datetime.now(live.VN_TZ)-live.TTL-timedelta(minutes=1)).isoformat()
    elif mutation == 'missing_time':
        record['status'].pop('finished_at')
    elif mutation == 'naive_time':
        record['status']['finished_at'] = datetime.now().isoformat()
    elif mutation == 'future_time':
        record['status']['finished_at'] = (datetime.now(live.VN_TZ)+timedelta(hours=1)).isoformat()
    elif mutation == 'unfinished':
        record['status']['state'] = 'running'
    elif mutation == 'wrong_key':
        record['key'] = '10.700_106.600'
    elif mutation == 'unknown_schema':
        record['schema_version'] = 999
    path.write_text(json.dumps(record))
    _, status = live.area_status(LAT, LON)
    assert status['state'] == expected_state
    response = client.post(f'/api/evidence/way/{WAY}', json={'lat': LAT, 'lon': LON})
    assert response.status_code == 200
    assert not any(b['ai_feature'] == 'parcel_widths' for b in response.json()['width_range']['evidence'])
