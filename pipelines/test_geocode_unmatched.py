"""Offline safety tests: address identity, geometry, budget and evidence semantics."""
import copy
import json
import time

import httpx
import pytest

from pipelines import geocode_unmatched as g


def row(wid=1, metres=0, name='Hẻm 123 Nguyễn Văn Đậu', highway='service'):
    # Local projection used by the production matcher.
    y = 10.8 + metres / 111320
    return {'id': wid, 'tags': {'name': name, 'highway': highway},
            'coords': [[106.7, y], [106.701, y]]}


@pytest.mark.parametrize('name,expected', [
    ('Hẻm 123 Đường Nguyễn Văn Đậu', ('123', 'nguyenvandau')),
    ('Hẻm 123/4A Nguyễn Văn Đậu', ('123/4a', 'nguyenvandau')),
    ('Hẻm 123', None), ('Đường Nguyễn Văn Đậu', None),
    ('Hẻm 123 Nguyễn Văn Đậu - cuối hẻm', None)])
def test_chain_does_not_guess_missing_street(name, expected):
    assert g.chain(name) == expected


@pytest.mark.parametrize('label,valid', [
    ('Hẻm 123 Nguyễn Văn Đậu, Phường 11, Hồ Chí Minh', True),
    ('123 Đường Nguyễn Văn Đậu, Hồ Chí Minh', True),
    ('Hẻm 123/4 Nguyễn Văn Đậu, Hồ Chí Minh', False),
    ('Hẻm 1234 Nguyễn Văn Đậu, Hồ Chí Minh', False),
    ('Hẻm 123 Nguyễn Văn Đậu 2, Hồ Chí Minh', False),
    ('123, Nguyễn Văn Đậu, Hồ Chí Minh', False),
    ('Hẻm 123 Lê Văn Sỹ, Phường Nguyễn Văn Đậu, Hồ Chí Minh', False)])
def test_returned_address_number_and_street_are_one_exact_component(label, valid):
    assert g.strict_name(label, ('123', 'nguyenvandau')) is valid


def test_snap_requires_distance_same_chain_class_and_unique_margin():
    expected = ('123', 'nguyenvandau')
    assert g.SnapIndex({'1': row()}).snap(10.8, 106.7005, expected)['way_id'] == 1
    assert g.SnapIndex({'1': row(metres=41)}).snap(10.8, 106.7005, expected)['reason'] == 'snap_over_40m'
    index = g.SnapIndex({'1': row(), '2': row(2, 14)})
    assert index.snap(10.8, 106.7005, expected)['reason'] == 'snap_margin_under_15m'
    index = g.SnapIndex({'1': row(metres=35), '2': row(2, 45)})
    assert index.snap(10.8, 106.7005, expected)['reason'] == 'snap_margin_under_15m'
    assert g.SnapIndex({'1': row(highway='primary')}).snap(10.8, 106.7005, expected)['reason'] == 'no_same_chain_eligible_osm_way'
    assert g.SnapIndex({'1': row(name='Hẻm 123/4 Nguyễn Văn Đậu')}).snap(10.8, 106.7005, expected)['reason'] == 'no_same_chain_eligible_osm_way'
    assert g.SnapIndex({'1': row()}).snap(21, 105, expected)['reason'] == 'outside_cached_urban_hcmc_scope'
    assert g.SnapIndex({'1': row()}).snap(float('nan'), 106.7, expected)['reason'] == 'outside_cached_urban_hcmc_scope'


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_cache_budget_persists_across_runs_and_no_secret_written(tmp_path):
    secret = 'secret-test-credential'
    c = g.Goong(tmp_path, network=True, max_calls=10, daily_quota=4, key=secret,
                client=client(lambda r: httpx.Response(200, json={'results': [], 'echo': secret})))
    assert c.cap == 1  # strictly less than half, not <= half
    c.get('/v2/geocode', address='Hẻm 1 X')
    assert c.get('/v2/geocode', address='Hẻm 1 X')['echo'] == '[REDACTED]'
    with pytest.raises(g.StopGoong, match='daily_budget_exhausted'):
        c.get('/v2/geocode', address='Hẻm 2 X')
    assert c.calls == 1 and c.usage() == 1
    c.close()
    assert all(secret not in p.read_text() for p in (tmp_path/'responses').glob('*.json'))
    c = g.Goong(tmp_path, network=True, max_calls=10, daily_quota=4, key=secret)
    with pytest.raises(g.StopGoong, match='daily_budget_exhausted'):
        c.get('/v2/geocode', address='Hẻm 2 X')
    c.close()


@pytest.mark.parametrize('status', [403, 429])
def test_refusal_is_cached_and_stops_new_queries_and_new_runs(tmp_path, status):
    calls = []
    def handle(request):
        calls.append(request)
        return httpx.Response(status, json={'error': 'blocked'})
    c = g.Goong(tmp_path, network=True, key='secret', client=client(handle))
    with pytest.raises(g.StopGoong, match='goong_blocked'):
        c.get('/v2/geocode', address='Hẻm 1 X')
    with pytest.raises(g.StopGoong, match='goong_blocked'):
        c.get('/v2/geocode', address='Hẻm 2 X')
    assert len(calls) == 1
    c.close()
    c = g.Goong(tmp_path, network=True, key='secret', client=client(handle))
    with pytest.raises(g.StopGoong, match='goong_blocked'):
        c.get('/v2/geocode', address='Hẻm 3 X')
    assert c.calls == 0
    c.close()


def test_timeout_consumes_budget_and_has_no_credential_exception_string(tmp_path):
    def handle(request):
        raise httpx.ReadTimeout('sensitive-credential', request=request)
    c = g.Goong(tmp_path, network=True, key='sensitive-credential', client=client(handle))
    with pytest.raises(g.StopGoong, match='goong_http_ReadTimeout'):
        c.get('/v2/geocode', address='1 X')
    assert c.calls == 1
    assert 'sensitive-credential' not in next((tmp_path/'responses').glob('*.json')).read_text()
    c.close()


def test_starts_are_rate_limited_and_other_traffic_reduces_budget(tmp_path, monkeypatch):
    at = [1000000.0]
    monkeypatch.setattr(g.time, 'time', lambda: at[0])
    monkeypatch.setattr(g.time, 'sleep', lambda seconds: at.__setitem__(0, at[0] + seconds))
    starts = []
    def handle(request):
        starts.append(at[0])
        return httpx.Response(200, json={'results': []})
    c = g.Goong(tmp_path, network=True, daily_quota=10, already_used=2, key='test', client=client(handle), delay=0)
    for i in range(2):
        c.get('/v2/geocode', address=f'{i} X')
    assert starts[1] - starts[0] >= .5 and c.cap == 2
    with pytest.raises(g.StopGoong, match='budget'):
        c.get('/v2/geocode', address='3 X')
    c.close()


def test_network_disabled_is_really_offline(tmp_path):
    c = g.Goong(tmp_path, key='test', client=client(lambda _: pytest.fail('network called')))
    with pytest.raises(g.StopGoong, match='network_disabled'):
        c.get('/v2/geocode', address='1 X')
    assert c.calls == 0
    c.close()


def entry():
    return {'names': ['Hẻm 123 Nguyễn Văn Đậu'], 'ward': 'Phường Gia Định', 'district': 'Bình Thạnh'}


def result(name='123 Nguyễn Văn Đậu, Hồ Chí Minh', lat=10.8, lon=106.7005):
    return {'formatted_address': name, 'geometry': {'location': {'lat': lat, 'lng': lon}}}


def test_locate_rejects_wrong_city_number_and_conflicting_goong_candidates(tmp_path):
    index = g.SnapIndex({'1': row()})
    for response in [result('123 Nguyễn Văn Đậu, Hà Nội'), result('123/4 Nguyễn Văn Đậu, Hồ Chí Minh')]:
        class API:
            def get(self, *args, **kwargs):
                return {'results': [response]}
        assert g.locate_cached_geocode(entry(), API(), index, True)['reason'] == 'no_accepted_result'
    index = g.SnapIndex({'1': row(), '2': row(2, 100)})
    class API:
        def get(self, *args, **kwargs):
            return {'results': [result(), result(lat=10.8+100/111320)]}
    assert g.locate_cached_geocode(entry(), API(), index, True)['reason'] == 'multiple_goong_way_candidates'


@pytest.mark.parametrize('has_coordinates,expected_endpoints', [(True, ['autocomplete']), (False, ['autocomplete', 'detail'])])
def test_one_autocomplete_and_detail_only_if_coordinates_are_missing(has_coordinates, expected_endpoints):
    calls = []
    class API:
        def get(self, endpoint, **params):
            calls.append(endpoint.rsplit('/', 1)[-1])
            if endpoint.endswith('autocomplete'):
                prediction = {'description': 'Hẻm 123 Nguyễn Văn Đậu, Hồ Chí Minh', 'place_id': 'id'}
                if has_coordinates:
                    prediction['geometry'] = result()['geometry']
                return {'predictions': [prediction]}
            return {'result': result()}
    assert g.locate(entry(), API(), g.SnapIndex({'1': row()}))['reason'] == 'accepted'
    assert calls == expected_endpoints


def test_ambiguous_query_is_skipped_and_ambiguous_predictions_do_not_get_detail():
    class Never:
        def get(self, *a, **kw):
            pytest.fail('ambiguous query made a request')
    e = {**entry(), 'names': ['Hẻm 123 Nguyễn Văn Đậu', 'Hẻm 124 Nguyễn Văn Đậu']}
    ix = g.SnapIndex({'1': row()})
    assert g.locate(e, Never(), ix)['reason'] == 'ambiguous_source_address_before_call'
    calls = []
    class API:
        def get(self, endpoint, **params):
            calls.append(endpoint)
            return {'predictions': [{'description': 'Hẻm 123 Nguyễn Văn Đậu, Hồ Chí Minh', 'place_id': pid} for pid in ('a', 'b')]}
    assert g.locate(entry(), API(), ix)['reason'] == 'ambiguous_goong_predictions_before_detail'
    assert calls == ['/v2/place/autocomplete']


def test_job_cap_from_environment_is_shared_across_runs(tmp_path, monkeypatch):
    monkeypatch.setenv('GOONG_JOB_MAX_REQUESTS', '2')
    c = g.Goong(tmp_path, network=True, key='test', client=client(lambda _: httpx.Response(200, json={})))
    assert c.cap == 2 and c.delay >= .5
    c.get('/v2/place/autocomplete', input='first')
    c.close()
    c = g.Goong(tmp_path, network=True, key='test', client=client(lambda _: httpx.Response(200, json={})))
    c.get('/v2/place/autocomplete', input='second')
    with pytest.raises(g.StopGoong, match='budget'):
        c.get('/v2/place/autocomplete', input='third')
    assert c.usage() == 2
    c.close()


@pytest.mark.parametrize('body', [{'error': {'code': 'OVER_RATE_LIMIT'}}, {'status': 'OVER_QUERY_LIMIT'}, {'message': 'Daily quota exceeded'}])
def test_quota_message_even_with_http_200_persists_stop(tmp_path, body):
    c = g.Goong(tmp_path, network=True, key='test', client=client(lambda _: httpx.Response(200, json=body)))
    with pytest.raises(g.StopGoong, match='blocked'):
        c.get('/v2/place/autocomplete', input='first')
    with pytest.raises(g.StopGoong, match='blocked'):
        c.get('/v2/place/autocomplete', input='second')
    assert c.calls == 1 and (tmp_path/'STOP.json').exists()
    c.close()


def test_queue_fire_candidates_come_before_other_sources_and_density():
    ix = g.SnapIndex({'1': row(), '2': row(2, name='Hẻm 456 Nguyễn Văn Đậu')})
    entries = [{**entry(), 'id': 'a', 'source': 'fire'},
               {**entry(), 'id': 'b', 'source': 'fire', 'names': ['Hẻm 456 Nguyễn Văn Đậu']},
               {**entry(), 'id': 'c', 'source': 'q9', 'names': ['Hẻm 456 Nguyễn Văn Đậu']}]
    ranked = g.prioritize(entries, ix, queue_doc={'items': [{'way_id': 2, 'score': 6}]}, campuses=[])
    assert ranked[0]['id'] == 'b' and ranked[0]['priority']['high_value_fire']
    ranked = g.prioritize(entries, ix, queue_doc={'items': []}, campuses=[{'id': 'campus', 'lat': 10.8, 'lon': 106.7}])
    assert all(e['source'] == 'fire' for e in ranked[:2])
    assert all('campus' in e['priority']['near_campus_ids'] for e in ranked)


def test_old_source_district_retained_in_query_variants():
    queries = g.address_queries({'ward': 'Phú Hữu', 'district': 'Quận 9'}, 'Hẻm 1031 Nguyễn Duy Trinh')
    assert 'Phường Phú Hữu, Quận 9' in queries[0]
    assert any('Quận 9' in q and 'Phường' not in q for q in queries)


def test_geocoded_listing_merge_preserves_original_claim_and_disagreement(monkeypatch):
    def record(i, hi):
        return {'way_id': 9, 'listing_id': str(i), 'source': 'chotot', 'name': 'Hẻm 9 X',
                'url': 'https://example.com', 'posted_at': '2026-10-17', 'bounds': [.5, hi],
                'width_m': hi, 'access_claim': None, 'review': False, 'extractor': 'regex-v1',
                'independence_key': str(i), 'independence_keys': [str(i)], 'method': 'alley_chain'}
    baseline, recovered = record(1, 2), record(2, 6)
    recovered['method'] = 'goong_geocode_snap'
    monkeypatch.setattr(g, 'read', lambda *a, **kw: [baseline])
    e = {'source': 'listing', 'record': recovered,
         'match': {'way_id': 9, 'osm_name': 'Hẻm 9 X', 'provenance': 'Goong geocode + snap, distance 2.0 m'}}
    product = {'ways': g.aggregate([baseline])}
    merged = g.merge_declared(product, [e])['ways']['9']
    assert (merged['lo'], merged['hi'], merged['review']) == (.5, 6, True)
    assert merged['n_listings'] == merged['independent_listings'] == 2
    assert merged['claims'][0]['listing_id'] == '1'
    assert merged['claims'][1]['provenance'] == e['match']['provenance']
    assert g.merge_declared(product, [e])['ways']['9'] == merged


def test_fire_and_metadata_stay_in_original_tiers(monkeypatch, tmp_path):
    from app import declared_index, evidence, official_widths, flags
    e = {'source': 'fire', 'record': {'name': 'Hẻm 123 Nguyễn Văn Đậu', 'ward': 'Phường Gia Định'},
         'match': {'way_id': 9876543210, 'osm_name': 'Hẻm 123 Nguyễn Văn Đậu', 'distance_m': 3.,
                   'provenance': 'Goong geocode + snap, distance 3.0 m'}}
    product = {'schema_version': 1, 'tier': 'Declared', 'ways': {}}
    path = tmp_path/'declared.json'
    g.atomic(path, g.merge_declared(product, [e]))
    monkeypatch.setattr(declared_index, 'PATH', path)
    monkeypatch.setattr(declared_index, '_stamp', None)
    monkeypatch.setattr(declared_index, '_data', {})
    store = evidence.EvidenceStore()
    bounds = store.by_way[9876543210]
    b = next(b for b in bounds if 'Goong geocode' in b.detail)
    assert (b.lo, b.hi, b.tier) == (.5, 3.5, 'Declared')
    e['source'] = 'q9'
    e['record'] = {'id': 'q9-1', 'source_id': 'q9_2009', 'source_date': '2009-02-16',
                   'url': 'https://example.gov.vn', 'planned_right_of_way_m': [6., 6.]}
    op = {'schema_version': 1, 'semantics': 'official_historical_and_planned_metadata_only',
          'sources': {'q9_2009': {'title': 'Gazette', 'reuse': 'attribution'}}, 'ways': {}}
    merged = g.merge_official(op, [e])
    assert len(g.merge_official(copy.deepcopy(merged), [e])['ways']['9876543210']) == 1
    path = tmp_path/'official.json'
    g.atomic(path, merged)
    monkeypatch.setattr(official_widths, 'PATH', path)
    monkeypatch.setattr(official_widths, '_stamp', None)
    monkeypatch.setattr(official_widths, '_data', {})
    assert official_widths.for_way(9876543210)[0]['affects_clear_width'] is False
    assert 'Goong geocode' in official_widths.for_way(9876543210)[0]['provenance']


def test_fire_source_survives_an_old_listing_daemon_replacement(monkeypatch, tmp_path):
    from app import evidence, declared_index
    e = {'id': 'fire:42', 'source': 'fire', 'record': {'name': 'Hẻm 123 X', 'ward': 'Phường Y'},
         'match': {'way_id': 9876543210, 'distance_m': 2., 'provenance': 'Goong geocode + snap, distance 2.0 m'}}
    product = {'parsed': 10, 'unmatched': 10, 'items': [], 'url': 'https://example.gov.vn'}
    merged = g.merge_fire_source(product, [e])
    assert len(g.merge_fire_source(copy.deepcopy(merged), [e])['items']) == 1
    assert merged['unmatched'] == 9
    path = tmp_path/'fire.json'
    g.atomic(path, merged)
    monkeypatch.setattr(evidence, 'FIRE_FILE', path)
    # An old listing builder publishes a product without geocoded supplemental rows.
    declared = tmp_path/'declared.json'
    g.atomic(declared, {'schema_version': 1, 'tier': 'Declared', 'ways': {}})
    monkeypatch.setattr(declared_index, 'PATH', declared)
    store = evidence.EvidenceStore()
    b = next(b for b in store.by_way[9876543210] if 'Goong geocode' in b.detail)
    assert (b.tier, b.lo, b.hi) == ('Declared', .5, 3.5)
