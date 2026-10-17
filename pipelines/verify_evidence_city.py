"""Real ASGI plan/config/queue verification with ALL external HTTP blocked."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'backend'))
sys.path.insert(0,str(ROOT))
import httpx
from fastapi.testclient import TestClient
from app import declared_index, evidence_queue, flags, main, osm, plan
from pipelines.listings_city import cadastral


def main_verify():
    product = declared_index.snapshot()[1]
    inv = evidence_queue.read(evidence_queue.INVENTORY)
    cad = cadastral()
    only, both = [], []
    names = set()
    for wid, r in product['ways'].items():
        row = inv['ways'][wid]
        lon,lat = row['coords'][len(row['coords'])//2]
        if not (osm.CACHE/'osm'/f'area_{osm.area_key(lat,lon)}.json').exists() and not osm._inside(lat,lon,osm.DEMO_BBOX):
            continue
        if wid in cad:
            both.append((wid,lat,lon))
        elif r['name'] not in names:
            only.append((wid,lat,lon))
            names.add(r['name'])
    selected = only[:3] + both[:2]
    results = []
    def forbidden(*a,**kw):
        raise AssertionError('External HTTP forbidden in evidence verification')
    with tempfile.TemporaryDirectory(prefix='evidence-verify-') as tmp, \
            patch.object(httpx.HTTPTransport,'handle_request',forbidden), \
            patch.object(plan,'GOONG_API_KEY',''), patch.object(main,'GOONG_API_KEY',''), \
            patch.object(evidence_queue,'USAGE',Path(tmp)/'usage.sqlite'):
        client = TestClient(main.app)  # deliberately no lifespan/background refresher
        for wid,lat,lon in selected:
            start=time.monotonic()
            response=client.post('/api/plan',json={'lat':lat,'lon':lon,'vehicle_id':'toyota-vios','intent':'pickup',
                                                 'arrive_at':'2026-10-17T10:00:00+07:00','dwell_min':15})
            assert response.status_code == 200, response.status_code
            wr=plan.area(lat,lon)[1][int(wid)]
            city=[b for b in wr.evidence if getattr(b,'_city_declared',False)]
            assert city
            official = wid in cad
            before=(wr.lo,wr.hi,wr.top_tier)
            if official:
                assert wr.top_tier in ('Measured','Official')
                assert any(getattr(b,'_city_declared',False) for b in wr.overruled)
                old=flags._state['ai_listings']
                flags._state['ai_listings']=False
                try:
                    after=plan.area(lat,lon)[1][int(wid)]
                    assert before == (after.lo,after.hi,after.top_tier)
                finally:
                    flags._state['ai_listings']=old
            body=response.json()
            results.append({'way_id':int(wid),'name':inv['ways'][wid]['tags'].get('name'), 'lat':lat,'lon':lon,
                            'http_status':response.status_code,'runtime_s':round(time.monotonic()-start,3),
                            'width_range':{'lo':wr.lo,'hi':None if wr.hi>=40 else wr.hi,'top_tier':wr.top_tier,'review':wr.review},
                            'official_overlap':official,'official_unchanged_without_city_listings':official,
                            'verdict':body['verdict']['code'],'door_way_id':(body.get('door') or {}).get('way_id')})
        response=client.get('/api/config')
        assert response.status_code==200
        coverage=response.json()['coverage']
        counts=coverage['evidence_ways_by_strongest_tier']
        assert sum(counts.values())==coverage['evidence_ways_with_sources']
        q=client.get('/api/evidence/queue?limit=5')
        assert q.status_code==200 and len(q.json()['items'])==5
        touched=evidence_queue.usage()
        assert touched
        report={'requests':results,'config_http_status':response.status_code,'queue_http_status':q.status_code,
                'distinct_logged_ways':len(touched),'logged_way_request_counts':sum(v['plan_requests'] for v in touched.values()),
                'external_http_calls':0,'portal_calls':0,'ai_calls':0,'coverage':coverage,
                'queue_sample':q.json()['items'],'usage_database':'temporary; does not contaminate live demand'}
    out=ROOT/'docs/eval/evidence-verification.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'plans':len(results),'all_http_200':True,'official_overlaps':sum(r['official_overlap'] for r in results),
                      'distinct_logged_ways':report['distinct_logged_ways'],'external_http_calls':0}))


if __name__=='__main__':
    main_verify()
