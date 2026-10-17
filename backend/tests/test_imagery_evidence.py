"""Offline budget/review/spatial checks. Never use real credentials/network."""
import json
from unittest.mock import patch

import pytest

from app import agent_budget as ab, imagery_evidence as ie
from app.evidence import EvidenceStore
from pipelines.imagery_widths import pano_position, validation


def reading(**overrides):
    return dict(id='test', provider='streetview', way_id=123, inside_alley=True,
                view_axis='along_alley', opposing_edges_visible=True,
                quality='daylight_clear', width_lo=1.8, width_hi=2.4,
                references_used=[{'object': 'motorbike', 'assumed_m': .7}], confidence=.9,
                reject_reason=None, image_date='2025-08', lat=10.8, lon=106.7, **overrides)


def test_job_cap_restart_and_live_reserve(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, 'STORE', tmp_path)
    monkeypatch.setattr(ab, 'FILE', tmp_path / 'paid.json')
    monkeypatch.delenv('AGENT_PAID_LIMIT_USD', raising=False)
    monkeypatch.delenv('AGENT_PAID_CALL_LIMIT', raising=False)
    body = {'generationConfig': {'maxOutputTokens': 2048}}
    with ab.ledger() as data:
        data['spent_usd'] = .01
    rid = ab.reserve(body, job_id='imagery', leave_usd=1.9)
    ab.finish(rid, {'promptTokenCount': 100, 'candidatesTokenCount': 20, 'thoughtsTokenCount': 30})
    assert ab.report()['jobs']['imagery']['spent_usd'] == pytest.approx(.0006)
    with ab.ledger() as data:
        data['jobs']['imagery']['spent_usd'] = .999
    with pytest.raises(ValueError, match='paid ceiling'):
        ab.reserve(body, job_id='imagery', leave_usd=1.9)
    with ab.ledger() as data:
        data['jobs']['imagery']['spent_usd'] = 0
        data['spent_usd'] = 1.09
    with pytest.raises(ValueError, match='3 USD'):
        ab.reserve(body, job_id='imagery', leave_usd=1.9)
    assert not ab.report()['reservations']


def test_review_and_mtime_reload_do_not_certify_unseen_span(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, 'PATH', tmp_path / 'imagery.json')
    ie.save_reading(reading())
    store = EvidenceStore()
    version = store.version
    another = reading(); another['id'] = 'another'
    ie.save_reading(another)
    ie.refresh(store)
    assert store.version == version  # pending batch writes do not churn live plan caches
    assert not [b for b in store.by_way.get(123, []) if b.measurement_schema.startswith('imagery')]
    ie.review('test', True, 'Human reviewer')
    ie.refresh(store)
    bounds = [b for b in store.by_way[123] if b.measurement_schema.startswith('imagery')]
    assert len(bounds) == 1 and bounds[0].tier == 'Observed'
    assert bounds[0].lo == 0 and bounds[0].hi == 2.4 and not bounds[0].coverage_complete
    ie.review('test', False, 'Human reviewer')
    ie.refresh(store)
    assert not [b for b in store.by_way.get(123, []) if b.measurement_schema.startswith('imagery')]


@pytest.mark.parametrize('field,value', [('quality', 'night'), ('quality', 'blur'),
    ('view_axis', 'frontage'), ('opposing_edges_visible', False),
    ('inside_alley', False), ('references_used', []), ('width_hi', float('nan'))])
def test_bad_imagery_never_publishes(tmp_path, monkeypatch, field, value):
    monkeypatch.setattr(ie, 'PATH', tmp_path / 'imagery.json')
    row = reading(); row[field] = value
    assert ie.save_reading(row)['status'] == 'rejected'
    with pytest.raises(ValueError):
        ie.review('test', True, 'Human')


def test_pano_must_be_inside_not_on_frontage():
    way = {'way_id': 123, 'coords': [[106.7, 10.8], [106.7, 10.801]]}
    assert pano_position({'lon': 106.7, 'lat': 10.8005}, way)['heading'] == 0
    assert pano_position({'lon': 106.7, 'lat': 10.8}, way) is None
    assert pano_position({'lon': 106.7001, 'lat': 10.8005}, way) is None


def test_validation_uses_raw_gap_not_clamped_width(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, 'PATH', tmp_path / 'imagery.json')
    monkeypatch.setattr(__import__('pipelines.imagery_widths', fromlist=['DIR']), 'DIR', tmp_path)
    ie.save_reading(reading())
    cuts = {123: [{'lat': 10.8, 'lon': 106.7, 'gap_m': 3., 'width_m': 999}]}
    v = validation(cuts)
    assert v['n_ways'] == 1 and v['bias_m'] == pytest.approx(.1)
    assert not v['auto_approve']


def test_mae_does_not_cancel_opposite_errors_on_one_way(tmp_path, monkeypatch):
    monkeypatch.setattr(ie, 'PATH', tmp_path / 'imagery.json')
    monkeypatch.setattr(__import__('pipelines.imagery_widths', fromlist=['DIR']), 'DIR', tmp_path)
    low = reading(); low.update(id='low', width_lo=.9, width_hi=1.1)
    high = reading(); high.update(id='high', width_lo=2.9, width_hi=3.1)
    ie.save_reading(low); ie.save_reading(high)
    v = validation({123: [{'lat':10.8, 'lon':106.7, 'gap_m':3.}]})
    assert v['bias_m'] == 0 and v['mae_m'] == 1


def test_paid_model_and_low_thinking_free_project_skip(tmp_path, monkeypatch):
    monkeypatch.setenv('AGENT_ALLOW_PAID', '1')
    monkeypatch.setenv('PROD_GEMINI_API_KEY', 'test-placeholder')
    monkeypatch.setattr(ab, 'free_project_available', lambda: False)
    monkeypatch.setattr(ab, 'reserve', lambda body, **kw: 'rid')
    settlements = []
    monkeypatch.setattr(ab, 'finish', lambda *args: settlements.append(args))
    monkeypatch.setattr(ie, 'small_image', lambda raw: b'small')
    def post(url, **kwargs):
        assert 'aiplatform.googleapis.com' in url and 'gemini-2.5-flash' in url
        config = kwargs['json']['generationConfig']
        assert kwargs['json']['contents'][0]['role'] == 'user'
        assert config['maxOutputTokens'] >= 2048 and config['thinkingConfig']['thinkingBudget'] == 0
        import httpx
        return httpx.Response(200, json={'candidates': [{'content': {'parts': [{'text': '{"inside_alley":false}'}]}}],
                                         'usageMetadata': {'promptTokenCount': 10}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(ie.httpx, 'post', post)
    assert ie.generate(b'image')['inside_alley'] is False
    assert settlements[0][1] == {'promptTokenCount': 10}


def test_simultaneous_reservations_cannot_bypass_job_cap(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(ab, 'STORE', tmp_path)
    monkeypatch.setattr(ab, 'FILE', tmp_path / 'paid.json')
    monkeypatch.delenv('AGENT_PAID_LIMIT_USD', raising=False)
    monkeypatch.delenv('AGENT_PAID_CALL_LIMIT', raising=False)
    def reserve(_):
        try:
            return ab.reserve({}, job_id='imagery', leave_usd=1.9)
        except ValueError:
            return None
    with ThreadPoolExecutor(8) as pool:
        ids = list(pool.map(reserve, range(80)))
    report = ab.report()
    assert 0 < sum(x is not None for x in ids) < len(ids)
    assert sum(report['jobs']['imagery']['reservations'].values()) <= 1
    assert report['spent_usd'] + report['reserved_usd'] <= 1.1


def test_google_sku_counters_are_atomic_without_changing_caps(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from app import budget
    monkeypatch.setattr(budget, 'STORE', tmp_path)
    monkeypatch.setattr(budget, 'USAGE_FILE', tmp_path / 'google.json')
    original_caps = dict(budget.CAPS)
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: budget.spend('streetview_static'), range(30)))
    assert budget.report()['streetview_static']['today'] == 30
    assert budget.CAPS == original_caps


def test_mapillary_skips_without_token_and_uses_header_when_configured(monkeypatch):
    monkeypatch.delenv('MAPILLARY_CLIENT_TOKEN', raising=False)
    with patch.object(ie.httpx, 'get') as get:
        assert ie.mapillary_images((106.7, 10.8, 106.71, 10.81)) == []
        get.assert_not_called()
    monkeypatch.setenv('MAPILLARY_CLIENT_TOKEN', 'test-placeholder')
    def get(url, **kwargs):
        assert url == 'https://graph.mapillary.com/images'
        assert kwargs['headers']['Authorization'] == 'OAuth test-placeholder'
        assert 'access_token' not in kwargs['params']
        import httpx
        return httpx.Response(200, json={'data': [{'id': 'pano'}]})
    monkeypatch.setattr(ie.httpx, 'get', get)
    assert ie.mapillary_images((106.7, 10.8, 106.71, 10.81)) == [{'id': 'pano'}]
