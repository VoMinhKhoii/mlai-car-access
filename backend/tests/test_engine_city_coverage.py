"""HTTP regression: genuine city deep scans count as sampled route evidence."""
import json
from fastapi.testclient import TestClient
from app import flags, live, osm, plan
from app.storage import LRU

# Hẻm 441/14 Điện Biên Phủ: real cached 15-cut planning-portal scan.
DEEP_RECORD = {'attempted_cuts': 18,
 'cuts': [{'at_m': 7.5, 'gap_m': 2.81, 'lat': 10.8021103, 'lon': 106.7134809, 'width_m': 1.81},
          {'at_m': 12.5, 'gap_m': 2.56, 'lat': 10.8021005, 'lon': 106.7135256, 'width_m': 1.56},
          {'at_m': 17.5, 'gap_m': 2.48, 'lat': 10.8020908, 'lon': 106.7135702, 'width_m': 1.48},
          {'at_m': 22.5, 'gap_m': 2.5, 'lat': 10.802081, 'lon': 106.7136148, 'width_m': 1.5},
          {'at_m': 37.5, 'gap_m': 5.55, 'lat': 10.8021033, 'lon': 106.7137151, 'width_m': 4.55},
          {'at_m': 42.5, 'gap_m': 4.78, 'lat': 10.8020934, 'lon': 106.7137597, 'width_m': 3.78},
          {'at_m': 47.5, 'gap_m': 4.19, 'lat': 10.8020835, 'lon': 106.7138043, 'width_m': 3.19},
          {'at_m': 52.5, 'gap_m': 4.67, 'lat': 10.8020917, 'lon': 106.7138372, 'width_m': 3.67},
          {'at_m': 57.5, 'gap_m': 4.29, 'lat': 10.8021359, 'lon': 106.7138466, 'width_m': 3.29},
          {'at_m': 62.5, 'gap_m': 3.96, 'lat': 10.8021802, 'lon': 106.7138561, 'width_m': 2.96},
          {'at_m': 67.5, 'gap_m': 2.07, 'lat': 10.8022051, 'lon': 106.7138797, 'width_m': 1.07},
          {'at_m': 72.5, 'gap_m': 2.01, 'lat': 10.8022003, 'lon': 106.7139251, 'width_m': 1.01},
          {'at_m': 77.5, 'gap_m': 2.0, 'lat': 10.8021955, 'lon': 106.7139706, 'width_m': 1.0},
          {'at_m': 82.5, 'gap_m': 1.96, 'lat': 10.8021907, 'lon': 106.714016, 'width_m': 0.96},
          {'at_m': 86.6, 'gap_m': 1.93, 'lat': 10.8021868, 'lon': 106.7140529, 'width_m': 0.93}],
 'deep': True,
 'queried_at': '2026-10-17T00:36:10.400021+07:00',
 'sample_strategy': 'campus-full-5m',
 'samples': [1.81, 1.56, 1.48, 1.5, 4.55, 3.78, 3.19, 3.67, 3.29, 2.96, 1.07, 1.01, 1.0, 0.96, 0.93]}


def test_city_deep_cuts_survive_real_http_loader_and_edge_scope(tmp_path, monkeypatch):
    from app.main import app
    cache = tmp_path/'cache'
    cache.mkdir()
    demo = cache/'demo.json'
    demo.write_bytes(osm.DEMO_FILE.read_bytes())
    city = cache/'city_parcels.json'
    city.write_text(json.dumps({'610082013': DEEP_RECORD}))
    areas = cache/'areas'
    areas.mkdir()
    for module, name, value in [
        (osm, 'CACHE', cache), (osm, 'DEMO_FILE', demo), (osm, '_GRAPHS', LRU(32)),
        (osm, '_GRAPH_STAMPS', {}), (live, 'CITY_PARCELS', city),
        (live, '_city_stamp', None), (live, '_city_cache', {}), (live, 'AREAS_DIR', areas),
        (live, '_areas', LRU(32)), (live, '_plan_cache', LRU(32)), (live, '_jobs', {}),
        (plan, '_WR', LRU(32)), (plan, '_FP', LRU(32)), (plan, 'GOONG_API_KEY', ''),
        (flags, '_state', {key: key == 'parcel_widths' for key in flags.AI_FEATURES}),
    ]:
        monkeypatch.setattr(module, name, value)
    monkeypatch.setattr(osm, '_fetch_overpass', lambda *a, **kw: (_ for _ in ()).throw(AssertionError('Network forbidden')))
    client = TestClient(app)
    body = {'lat': 10.802186, 'lon': 106.714062, 'vehicle_id': 'toyota-vios',
            'intent': 'park', 'dwell_min': 60, 'arrive_at': '2026-10-17T14:00:00+07:00'}
    response = client.post('/api/plan', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    door = result['door']
    coverage = door['estimate']['coverage']
    assert coverage['sampled_segments'] > 0
    assert coverage['sample_supported_fraction'] > 0
    assert result['verdict']['door_estimate']['coverage'] == coverage
    assert door['fit']['width_range']['lo'] == 0
    parcel = next(b for b in door['fit']['width_range']['evidence'] if b['ai_feature'] == 'parcel_widths')
    assert parcel['tier'] == 'Official'
    assert parcel['sample_quality']['accepted_cuts'] == 10
    assert len(parcel['sample_quality']['rejected_cuts']) == 5
    assert parcel['estimate_m'] == .93
    assert not door['verified']
    assert not door['fit']['width_range']['decisive_clearance']
    segments = [s for s in result['verdict']['door_profile'] if s['way_id'] == 610082013]
    assert segments and all(s['sampled'] for s in segments)
    assert all(s['estimate_m'] == .93 and s['width_lo'] == 0 and s['tier'] == 'Official' for s in segments)
    assert result['area']['state'] == 'missing'  # city data works without an area-build record
    assert json.loads(city.read_text()) == {'610082013': DEEP_RECORD}
