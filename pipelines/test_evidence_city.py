"""Offline safety checks for listings and the evidence queue; no crawler writes."""
import json
import sqlite3
import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import declared_index, evidence, evidence_queue, evidence_routes, flags, plan
from app.osm import AreaGraph, Way
from pipelines import listings_city as lc


def test_parent_claim_never_propagates_numeric_width_or_no_car_upper_bound():
    assert lc.listing_bounds({'width_m': 1.5, 'access_claim': 'xe_may'}, 'alley_chain_parent')[0] is None
    assert lc.listing_bounds({'width_m': 8., 'access_claim': 'xe_hoi'}, 'alley_chain_parent')[0] == (2.2, 40.)


def record(i, width, seller, property_key):
    return {'way_id': 9, 'listing_id': str(i), 'source': 'chotot', 'name': 'Hẻm 9 X',
            'url': 'https://example.com/'+str(i), 'posted_at': '2026-10-17', 'bounds': [.5, width],
            'width_m': width, 'access_claim': None, 'review': False, 'extractor': 'regex-v1',
            'independence_key': seller, 'independence_keys': [seller, property_key], 'method': 'alley_chain'}


def test_disagreement_widens_and_same_house_brokers_are_not_independent():
    p = lc.aggregate([record(1, 2., 'seller:a', 'house:a'), record(2, 6., 'seller:b', 'house:a'),
                      record(3, 4., 'seller:c', 'house:b')])['9']
    assert p['independent_listings'] == 2
    assert p['n_listings'] == 3
    assert p['lo'] == .5 and p['hi'] == 6.
    assert p['review']


def product(lo=.5, hi=8., review=True):
    return {'schema_version': 1, 'tier': 'Declared', 'ways': {
        '9876543210': {'lo': lo, 'hi': hi, 'review': review, 'claims': []}}}


def setup_store(monkeypatch, tmp_path, data=None):
    p = tmp_path/'declared.json'
    p.write_text(json.dumps(data or product()))
    monkeypatch.setattr(declared_index, 'PATH', p)
    monkeypatch.setattr(declared_index, '_stamp', None)
    monkeypatch.setattr(declared_index, '_data', {})
    monkeypatch.setattr(flags, '_state', {k: False for k in flags.AI_FEATURES} | {'ai_listings': True})
    s = evidence.EvidenceStore()
    monkeypatch.setattr(evidence, 'STORE_EVIDENCE', s)
    monkeypatch.setattr(plan, 'STORE_EVIDENCE', s)
    g = AreaGraph((10.8, 106.7), source='test-city-evidence')
    g.ways[9876543210] = Way(9876543210, {'highway': 'service', 'service': 'alley'}, [])
    return p, s, g


def test_review_hull_survives_generic_road_priors_and_duplicate_live_claim(monkeypatch, tmp_path):
    _, s, g = setup_store(monkeypatch, tmp_path)
    s._add(evidence.Bound(.5, 2., 'Declared', 'live listing', 'test', feature='ai_listings'), 9876543210)
    wr = evidence.width_ranges(g)[9876543210]
    assert (wr.lo, wr.hi, wr.top_tier, wr.review) == (.5, 8., 'Declared', True)


@pytest.mark.parametrize('tier', ['Measured','Official'])
def test_official_and_measured_never_narrowed_by_advertisements(monkeypatch, tmp_path, tier):
    _, s, g = setup_store(monkeypatch, tmp_path, product(3.9, 8.))
    s._add(evidence.Bound(3., 4., tier, 'survey', 'test'), 9876543210)
    wr = evidence.width_ranges(g)[9876543210]
    assert (wr.lo, wr.hi, wr.top_tier) == (3., 4., tier)
    assert any(getattr(b, '_city_declared', False) for b in wr.overruled)


def test_atomic_reload_invalidates_existing_plan_width_cache(monkeypatch, tmp_path):
    p, s, g = setup_store(monkeypatch, tmp_path)
    monkeypatch.setattr(plan, 'build_graph', lambda *a: g)
    monkeypatch.setattr(plan, 'flood_profiles', lambda g: {})
    monkeypatch.setattr(plan, '_WR', {})
    monkeypatch.setattr(plan, '_FP', {})
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 8.
    replacement = tmp_path/'replacement.json'
    replacement.write_text(json.dumps(product(hi=10.)))
    replacement.replace(p)
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 10.
    p.write_text('{')
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 10.
    p.unlink()
    assert plan.area(10.8, 106.7)[1][9876543210].hi == 4.5


def test_feature_flag_removes_city_listing_bounds(monkeypatch, tmp_path):
    _, s, g = setup_store(monkeypatch, tmp_path)
    monkeypatch.setitem(flags._state, 'ai_listings', False)
    assert evidence.width_ranges(g)[9876543210].hi == 4.5


def test_invalid_bounds_do_not_replace_last_good_product(monkeypatch, tmp_path):
    p, _, _ = setup_store(monkeypatch, tmp_path)
    stamp, good = declared_index.snapshot()
    p.write_text(json.dumps(product(lo=9, hi=1)))
    assert declared_index.snapshot() == (stamp, good)


def test_queue_demand_uncertainty_and_tier_value():
    unknown = {'lo': .5, 'hi': 40., 'top_tier': None}
    assert evidence_queue.rank(unknown, 9)[0] > evidence_queue.rank(unknown, 0)[0]
    assert evidence_queue.rank(unknown, 0)[0] > evidence_queue.rank({**unknown,'top_tier':'Official'}, 0)[0]
    assert len(evidence_queue.rank(unknown, 0)[1]) == 3
    assert evidence_queue.rank({'lo':1.95,'hi':2.18,'top_tier':'Declared'},0)[1] == ['sedan']


def test_usage_deduplication_and_persistence(tmp_path):
    p = tmp_path/'usage.sqlite'
    evidence_queue.record_way_ids([1, 1, 2, False, -1], p)
    evidence_queue.record_way_ids([1], p)
    assert {k:v['plan_requests'] for k,v in evidence_queue.usage(p).items()} == {1:2,2:1}


def test_route_logging_does_not_count_all_visible_ways_or_crossings():
    def feature(wid, coords):
        return {'properties':{'way_id':wid},'geometry':{'coordinates':coords}}
    result = {'door':{'way_id':1},'stop_points':[{'way_id':2,'route_in':{'geometry':[[0,0],[.001,0]]}}],
              'layers':{'fit':{'features':[feature(3,[[0,0],[.001,0]]),feature(4,[[0,1],[1,1]]),
                                           feature(5,[[.0005,-.001],[.0005,.001]])]}}}
    assert evidence_queue.touched_way_ids(result) == {1,2,3}


def test_free_extractor_cannot_use_paid_alias_and_caches_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(lc, 'RAW', tmp_path)
    for key in list(lc.os.environ):
        if key.startswith('GEMINI_API_KEY'):
            monkeypatch.delenv(key)
    monkeypatch.setenv('PROD_GEMINI_API_KEY','fake-paid')
    monkeypatch.setenv('GEMINI_API_KEY','fake-paid')
    ex = lc.FreeExtractor(9000)
    assert ex.keys == [] and ex.remaining == 1500
    assert ex.extract('ambiguous', {})['reason'] == 'no_free_call'
    monkeypatch.setenv('GEMINI_API_KEY','fake-free')
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise RuntimeError('hidden')
    monkeypatch.setattr(lc.httpx,'post', fail)
    monkeypatch.setattr(lc.time,'sleep', lambda *a:None)
    ex = lc.FreeExtractor(1)
    first = ex.extract('ambiguous', {})
    assert ex.extract('ambiguous', {}) == first
    assert calls == [1] and ex.calls == 1
    assert 'hidden' not in json.dumps(first)


def test_router_augments_config_and_logs_without_changing_plan(monkeypatch, tmp_path):
    monkeypatch.setattr(evidence_queue,'USAGE',tmp_path/'usage.sqlite')
    monkeypatch.setattr(evidence_queue,'city_state',lambda:{'available':True,'ways':{},'coverage':{'evidence_ways_with_sources':3}})
    app = FastAPI()
    app.include_router(evidence_routes.router_for(app))
    @app.get('/api/config')
    def config():
        return {'coverage':{'existing':1}}
    expected = {'door':{'way_id':9},'verdict':{'code':'unknown'}}
    @app.post('/api/plan')
    def plan_endpoint():
        return expected
    client = TestClient(app)
    assert client.get('/api/config').json()['coverage'] == {'existing':1,'evidence_ways_with_sources':3}
    assert client.post('/api/plan').json() == expected
    assert evidence_queue.usage()[9]['plan_requests'] == 1
    assert client.get('/api/evidence/queue?bbox=nan,0,1,1').status_code == 422
    assert client.get('/api/evidence/queue?limit=1001').status_code == 422


def test_listing_archive_keeps_revisions_after_page_refresh(monkeypatch, tmp_path):
    monkeypatch.setattr(lc,'RAW',tmp_path)
    a={'source':'chotot','ad_id':1,'subject':'same house','body':'hẻm 4m'}
    lc.archive_ads([a])
    all_rows=lc.archive_ads([{**a,'body':'hẻm 6m'}])
    assert len(all_rows)==2
    assert len(lc.archive_ads([]))==2


def test_source_backoff_is_persistent_and_no_key_rotation(monkeypatch, tmp_path):
    import httpx
    import pytest
    monkeypatch.setattr(lc,'RAW',tmp_path)
    monkeypatch.setattr(lc.time,'sleep',lambda *a:None)
    calls=[]
    def get(*a,**kw):
        calls.append(1)
        return httpx.Response(429,headers={'retry-after':'3600'},request=httpx.Request('GET','https://example.com'))
    monkeypatch.setattr(lc.httpx.Client,'get',get)
    http=lc.PoliteHTTP()
    with pytest.raises(RuntimeError,match='source_backoff_http_429'):
        http.get('https://example.com')
    with pytest.raises(RuntimeError,match='source_in_persisted_cooldown'):
        lc.PoliteHTTP().get('https://example.com')
    assert calls==[1]
    assert json.loads((tmp_path/'http_state.json').read_text())['example.com']['retry_at'] > lc.time.time()+3500


def test_free_call_cap_counts_all_prior_results_across_builds(monkeypatch, tmp_path):
    monkeypatch.setattr(lc,'RAW',tmp_path)
    ex=lc.FreeExtractor(1)
    ex.keys=['fake-free']
    with ex.db:
        ex.db.executemany('INSERT INTO results VALUES (?,?,?)',[(str(i),'{}','2026-10-17') for i in range(1500)])
    assert ex.extract('new unmatched text',{})['reason']=='lifetime_cap'
    assert ex.calls==0
