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
    assert parcel['tier'] == 'Official'  # Portal provenance, never a continuous clearance guarantee.
    assert 'not continuous clear width' in width['clear_width_caveat']
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
    ('missing_time', 'missing'), ('naive_time', 'missing'),
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


@pytest.mark.parametrize('versioned', [False, True])
def test_expired_area_retains_only_dated_static_portal_cuts_through_http(cached_http, versioned):
    client, path, record = cached_http
    observed = (datetime.now(live.VN_TZ)-timedelta(days=30)).isoformat()
    record['status']['finished_at'] = observed
    if versioned:
        record.update(schema_version=live.SCHEMA_VERSION, revision=7, collected_at=observed,
                      expires_at=(datetime.fromisoformat(observed)+live.TTL).isoformat(), complete=True,
                      steps={}, counts={})
    path.write_text(json.dumps(record))
    original = path.read_bytes()
    assert live.area_status(LAT, LON)[0] is None  # Dynamic evidence remains expired.
    data = client.post(f'/api/evidence/way/{WAY}', json={'lat': LAT, 'lon': LON}).json()
    parcel = next(b for b in data['width_range']['evidence'] if b['ai_feature'] == 'parcel_widths')
    assert parcel['tier'] == 'Official' and parcel['estimate_m'] == 5.56
    assert parcel['sample_quality']['accepted_cuts'] == 5
    assert parcel['observed_on'] == observed
    assert parcel['url'] == 'https://thongtinquyhoach.hochiminhcity.gov.vn/'
    assert 'not continuous clear width' in data['width_range']['clear_width_caveat']
    assert not data['photos']
    assert not any('Legacy unreviewed' in b['source'] for b in data['width_range']['evidence'])
    result = client.post('/api/plan', json={'lat': LAT, 'lon': LON, 'vehicle_id': 'class-m',
        'intent': 'park', 'dwell_min': 60, 'arrive_at': '2026-10-17T14:00:00+07:00'}).json()
    assert result['area']['state'] == 'stale'
    assert result['door']['estimate']['coverage']['all_sampled_segments'] == 6
    assert result['door']['estimate']['stop_width']['value_m'] == 5.56
    assert not result['door']['verified']
    assert path.read_bytes() == original


def test_expired_legacy_partial_does_not_mask_richer_city_deep_survey(cached_http):
    client, path, record = cached_http
    record['status']['finished_at'] = (datetime.now(live.VN_TZ)-timedelta(days=30)).isoformat()
    path.write_text(json.dumps(record))
    parcel = next(p for p in record['parcels'] if p['way_id'] == WAY)
    city = {**parcel, 'deep': False, 'prior_scan_deep': True}
    assert len(city['cuts']) == 5
    record['parcels'] = [{**parcel, 'cuts': parcel['cuts'][:1], 'samples': parcel['samples'][:1], 'deep': True}]
    path.write_text(json.dumps(record))
    live.CITY_PARCELS.write_text(json.dumps({str(WAY): city}))
    result = client.post(f'/api/evidence/way/{WAY}', json={'lat': LAT, 'lon': LON}).json()
    parcel = next(b for b in result['width_range']['evidence'] if b['ai_feature'] == 'parcel_widths')
    assert parcel['sample_quality']['accepted_cuts'] == 5
