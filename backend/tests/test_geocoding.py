"""Offline geocoder regressions. Every provider HTTP call is mocked."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import agent, geocoding as geo, main


def response(body, status=200):
    return httpx.Response(status, json=body, request=httpx.Request('GET', 'https://mock.invalid'))


class GeocodingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        geo.configure_curated(main.PRESETS, agent.DEMO_PLACES)
        cls.curated = geo._curated

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        osm = root / 'osm'
        osm.mkdir()
        # Two disk-only cells, including a street whose midpoint is far from the
        # reverse point. No AreaGraph is loaded or fetched to find either name.
        for i, (name, lat, lon, tags) in enumerate([
            ('Đường Fixture Xa', 10.9, 106.8, {'highway': 'residential'}),
            ('Chợ Bến Thành', 10.7725, 106.698, {'amenity': 'marketplace'}),
        ]):
            elements = [{'type': 'node', 'id': i * 2, 'lat': lat, 'lon': lon},
                        {'type': 'node', 'id': i * 2 + 1, 'lat': lat, 'lon': lon + .02},
                        {'type': 'way', 'id': 100 + i, 'nodes': [i * 2, i * 2 + 1],
                         'tags': dict(tags, name=name)}]
            (osm / f'area_{i}.json').write_text(json.dumps({'elements': elements}))
        for target, value in [('DB', root / 'geo.sqlite'), ('OSM_DIR', osm),
                              ('INDEX_FILE', root / 'names.json'), ('_names', None),
                              ('_curated', self.curated)]:
            p = patch.object(geo, target, value)
            p.start()
            self.addCleanup(p.stop)
        pool = patch.object(geo, '_goong_keys', return_value=['mock-key-only'])
        pool.start()
        self.addCleanup(pool.stop)
        p = patch.object(geo.config, 'GOONG_API_KEY', 'mock-key-only')
        p.start()
        self.addCleanup(p.stop)
        self.http = patch.object(geo.httpx, 'get', side_effect=AssertionError('Unexpected external HTTP')).start()
        self.addCleanup(patch.stopall)
        self.client = TestClient(main.app)

    def test_429_persists_and_is_shared_by_all_routes_and_agent(self):
        self.http.side_effect = lambda *a, **k: response({'status': 'OVER_RATE_LIMIT'}, 429)
        result = self.client.get('/api/search', params={'q': '475A Điện Biên Phủ'}).json()
        self.assertEqual(result['results'][0]['lat'], 10.801617)
        self.assertGreater(geo.goong_blocked_until(), time.time() + 1790)
        self.assertEqual(self.client.get('/api/place/unknown-id').status_code, 424)
        self.assertIn('OpenStreetMap', self.client.get('/api/reverse', params={'lat': 10.9, 'lon': 106.80001}).json()['source'])
        self.assertTrue(agent.resolve_place('Hẻm 113/4 Võ Duy Ninh')['results'])
        # A fresh DB connection (as after restart) still observes the breaker.
        self.assertEqual(geo.goong('Geocode', {'latlng': '10.9,106.8'}), {})
        self.assertEqual(self.http.call_count, 1)

    def test_over_rate_limit_body_even_with_http_200(self):
        self.http.side_effect = lambda *a, **k: response({'status': 'OVER_RATE_LIMIT'})
        self.client.get('/api/search', params={'q': 'HUTECH'})
        self.assertGreater(geo.goong_blocked_until(), time.time())
        self.client.get('/api/search', params={'q': '475A Điện Biên Phủ'})
        self.assertEqual(self.http.call_count, 1)

    def test_agent_curated_lookup_never_uses_provider(self):
        result = agent.resolve_place('Hẻm 113/4 Võ Duy Ninh')
        self.assertEqual(result['results'][0]['lat'], 10.792106)
        self.http.assert_not_called()

    def test_429_from_place_or_reverse_opens_shared_breaker(self):
        self.http.side_effect = lambda *a, **k: response({'status': 'OVER_RATE_LIMIT'}, 429)
        for path, params in [('/api/place/missing', {}), ('/api/reverse', {'lat': 10.9, 'lon': 106.8})]:
            with self.subTest(path=path):
                with geo._db() as db:
                    db.execute('DELETE FROM state')
                self.http.reset_mock()
                self.client.get(path, params=params)
                self.assertGreater(geo.goong_blocked_until(), time.time())
                self.assertTrue(agent.resolve_place('Fixture Xa')['results'])
                self.assertEqual(self.http.call_count, 1)

    def test_all_demo_queries_with_goong_blocked(self):
        geo.block_goong('known exhausted demo quota')
        for q in ['475A Điện Biên Phủ', 'Hẻm 220/9 Xô Viết Nghệ Tĩnh',
                  'Hẻm 113/4 Võ Duy Ninh', 'Chợ Bến Thành', 'HUTECH']:
            with self.subTest(q=q):
                results = self.client.get('/api/search', params={'q': q}).json()['results']
                self.assertTrue(results)
                for p in results:
                    self.assertIn('lat', p)
                    self.assertIn('lon', p)
                    self.assertTrue(p['source'])
        self.http.assert_not_called()

    def test_goong_errors_empty_and_timeout_fall_back(self):
        for value in [response({'status': 'ERROR'}, 500), response({'predictions': [], 'status': 'ZERO_RESULTS'}),
                      httpx.ConnectError('mock error'), httpx.ReadTimeout('mock timeout')]:
            with self.subTest(value=value):
                self.http.side_effect = value if isinstance(value, Exception) else None
                self.http.return_value = value
                r = self.client.get('/api/search', params={'q': 'Hẻm 220/9 Xô Viết Nghệ Tĩnh'}).json()
                self.assertTrue(r['results'])
                self.assertIn('Demo', r['results'][0]['source'])
                self.assertEqual(geo.goong_blocked_until(), 0)
                # Don't let an empty-result disk cache mask the next failure.
                with geo._db() as db:
                    db.execute('DELETE FROM responses')

    def test_goong_autocomplete_detail_reverse_disk_cache_and_rounded_near(self):
        def get(url, **kwargs):
            self.assertLessEqual(kwargs['timeout'], 3)
            if url.endswith('autocomplete'):
                return response({'status': 'OK', 'predictions': [
                    {'description': 'Mock POI, Hồ Chí Minh', 'place_id': 'mock-poi'}]})
            if url.endswith('detail'):
                return response({'status': 'OK', 'result': {'name': 'Mock POI', 'geometry': {'location': {'lat': 10.8, 'lng': 106.71}}}})
            if url.endswith('Geocode'):
                return response({'status': 'OK', 'results': [{'formatted_address': 'Mock reverse'}]})
            raise AssertionError(url)
        self.http.side_effect = get
        params = {'q': 'Mock POI', 'lat': 10.80001, 'lon': 106.71001}
        first = self.client.get('/api/search', params=params).json()
        self.assertEqual(first['results'][0]['source'], 'Goong')
        self.assertEqual(self.http.call_count, 2)
        params.update(lat=10.80002, lon=106.71002)
        self.assertEqual(self.client.get('/api/search', params=params).json()['results'], first['results'])
        self.assertEqual(self.client.get('/api/place/mock-poi').json()['lat'], 10.8)
        self.assertEqual(self.http.call_count, 2)
        self.assertEqual(self.client.get('/api/reverse', params={'lat': 10.8, 'lon': 106.71}).json()['label'], 'Mock reverse')
        geo.block_goong()
        self.assertEqual(self.client.get('/api/place/mock-poi').status_code, 200)
        self.client.get('/api/reverse', params={'lat': 10.80001, 'lon': 106.71001})
        self.assertEqual(self.http.call_count, 3)

    def test_expired_breaker_allows_requests(self):
        with geo._db() as db:
            db.execute("INSERT INTO state VALUES ('goong_blocked_until', ?)", (time.time() - 1,))
        self.http.side_effect = lambda *a, **k: response({'status': 'OK', 'predictions': []})
        self.assertEqual(geo.goong('v2/place/autocomplete', {'input': 'test'}).get('predictions'), [])
        self.assertEqual(self.http.call_count, 1)

    def test_index_reads_all_cells_once_and_persists(self):
        names = geo.initialize_name_index()
        self.assertEqual(len(names), 2)
        with patch.object(geo.Path, 'read_text', side_effect=AssertionError('Index must be reused')):
            self.assertIs(geo.initialize_name_index(), names)
            self.assertEqual(geo.local_search('Fixture Xa', (10.9, 106.8))[0]['label'], 'Đường Fixture Xa')
        geo._names = None
        self.assertEqual(geo.initialize_name_index(), names)
        # Near the start of a long street, not its distant midpoint.
        reverse = geo.nearest_way(10.9, 106.80001)
        self.assertEqual(reverse['label'], 'Đường Fixture Xa')
        self.assertLess(reverse['distance_m'], 1)

    def test_nominatim_bounded_cached_shared_spacing_and_reverse(self):
        geo.block_goong()
        seen = []
        def get(url, **kwargs):
            seen.append(time.monotonic())
            self.assertIn('NgoNgach', kwargs['headers']['User-Agent'])
            if url.endswith('/search'):
                self.assertEqual(kwargs['params']['bounded'], 1)
                self.assertEqual(kwargs['params']['viewbox'], '106.30,11.20,107.10,10.35')
                return response([{'display_name': '42 Fixture Nominatim', 'lat': '10.85', 'lon': '106.76'}])
            return response({'display_name': 'Reverse Nominatim', 'lat': '10.5', 'lon': '106.4'})
        self.http.side_effect = get
        one = self.client.get('/api/search', params={'q': '42 Fixture Nominatim'}).json()
        self.assertIn('Nominatim', one['results'][0]['source'])
        self.client.get('/api/search', params={'q': '42 Fixture Nominatim'})
        two = self.client.get('/api/reverse', params={'lat': 10.5, 'lon': 106.4}).json()
        self.assertIn('Nominatim', two['source'])
        self.assertEqual(self.http.call_count, 2)
        self.assertGreaterEqual(seen[1] - seen[0], 1)
        self.client.get('/api/reverse', params={'lat': 10.5, 'lon': 106.4})
        self.assertEqual(self.http.call_count, 2)

    def test_old_place_id_can_use_cached_description(self):
        self.http.side_effect = lambda *a, **k: response({'status': 'OK', 'predictions': [
            {'description': '475A Điện Biên Phủ, Hồ Chí Minh', 'place_id': 'old-campus'}]})
        geo.goong('v2/place/autocomplete', {'input': '475A'})
        geo.block_goong()
        self.assertEqual(self.client.get('/api/place/old-campus').json()['lat'], 10.801617)
        self.assertEqual(self.http.call_count, 1)

    def test_wall_time_deadline_across_goong_requests(self):
        release = threading.Event()
        self.http.side_effect = lambda *a, **k: release.wait(5)
        started = time.monotonic()
        try:
            with patch.object(geo, 'GOONG_BUDGET_S', .05):
                r = self.client.get('/api/search', params={'q': 'HUTECH'}).json()
            self.assertTrue(r['results'])
            self.assertLess(time.monotonic() - started, .5)
        finally:
            release.set()

    def test_outside_hcmc_does_not_call_provider(self):
        self.assertTrue(agent.resolve_place('42 phố Huế Hà Nội')['outside_service_area'])
        self.http.assert_not_called()

    def test_api_keeps_poi_relevance_ahead_of_nearer_bus_stop(self):
        geo.block_goong()
        places = [
            {'label': 'Chợ Marketplace', 'lat': 10.77, 'lon': 106.69, 'source': 'Nominatim', 'precision': 'marketplace'},
            {'label': 'Chợ Bus Stop', 'lat': 10.8, 'lon': 106.71, 'source': 'Nominatim', 'precision': 'bus_stop'}]
        with patch.object(geo, 'local_search', return_value=[]), patch.object(geo, 'nominatim', return_value=places):
            result = self.client.get('/api/search', params={'q': 'Chợ Marketplace'}).json()
        self.assertEqual(result['results'][0]['precision'], 'marketplace')

    def test_all_hutech_campuses_and_nearby_facility_remain_selectable(self):
        geo.block_goong()
        result = self.client.get('/api/search', params={'q': 'HUTECH'}).json()
        self.assertEqual(len(result['results']), 6)

    def test_house_number_does_not_silently_use_broad_street(self):
        geo.block_goong()
        r = geo.resolve_place('99 Đường Fixture Xa')
        self.assertTrue(r['requires_clarification'])
        self.assertIn('house', r['note'])


if __name__ == '__main__':
    unittest.main()
