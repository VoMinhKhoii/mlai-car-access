"""Regressions at the product/night-work integration boundaries."""
import json
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import agent, auth, flood, main, osm, parcels


def test_official_lows_are_preserved_by_content_generation_cache(tmp_path):
    target = tmp_path / 'tide.json'
    metadata = {'highs': [{'t':'2026-10-17T12:00:00+07:00', 'level_m':1.2}],
                'lows': [{'t':'2026-10-17T06:00:00+07:00', 'level_m':-.5},
                         {'t':'2026-10-17T18:00:00+07:00', 'level_m':-.8}],
                'low_level_m': -1.9}
    target.write_text(json.dumps(metadata))
    with patch.object(flood, 'TIDE_FILE', target):
        extremes = flood._extremes()
        assert [value for _, value in extremes] == [-.5, 1.2, -.8]
        assert flood._bulletin_level(datetime.fromisoformat(metadata['lows'][1]['t'])) == -.8


def test_tide_freshness_keeps_measurements_and_newer_official_forecasts():
    issued = datetime.fromisoformat('2026-10-17T09:00:00+07:00')
    meta = {'issued_at':issued.isoformat()}
    with patch.object(flood.hydro, '_cache', {'marine':(issued.timestamp()-3600, [])}):
        assert flood._select_tide(issued, (1.6,'measured'), 1.2, meta) == (1.6,'measured')
        assert flood._select_tide(issued, (1.6,'model'), 1.2, meta) == (1.2,'bulletin')
    with patch.object(flood.hydro, '_cache', {'marine':(issued.timestamp()+3600, [])}):
        assert flood._select_tide(issued, (1.6,'model'), 1.2, meta) == (1.6,'model')


def test_failed_deep_cuts_still_consume_shared_attempt_budget():
    graph = osm.graph_from_elements(10.8,106.7,[
        {'type':'node','id':i,'lat':10.8+i*.004,'lon':106.7} for i in (1,2,3)
    ] + [{'type':'way','id':20,'nodes':[1,2],'tags':{'highway':'residential'}},
         {'type':'way','id':21,'nodes':[2,3],'tags':{'highway':'residential'}}])
    with patch.object(parcels,'path_into',return_value=[(20,[]),(21,[])]), \
         patch.object(parcels,'path_out',return_value=[]), \
         patch.object(parcels,'measure',return_value=None) as measure:
        parcels.measure_area(graph,10.808,106.7,{},osm.haversine)
    assert sum(call.kwargs['max_cuts'] for call in measure.call_args_list
               if call.kwargs.get('step')) <= parcels.DEEP_MAX_CUTS


def test_guest_alleyai_cannot_start_model_spending():
    with patch.object(auth,'is_operator',return_value=False), \
         patch.object(agent,'stream',return_value=iter(['{"type":"done","contents":[]}\n'])) as stream:
        response = TestClient(main.app).post('/api/agent',json={'message':'Tìm HUTECH','contents':[]})
    assert response.status_code == 200
    assert stream.call_args.kwargs['allow_model'] is False
