"""Agent/MCP boundary tests. Fake sources cover failures without model charges."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from app import agent, agent_budget, geocoding, main


class AgentProductionTests(unittest.TestCase):
    def setUp(self):
        # A disabled primary key no longer disables the numbered rotation pool.
        # These boundary tests must remain offline regardless of local env keys.
        pool = patch.object(geocoding, '_goong_keys', return_value=[])
        pool.start()
        self.addCleanup(pool.stop)

    def test_fallback_keeps_destination_and_does_not_confuse_tonight_or_don(self):
        args,question=agent.driver_request(agent.AgentRequest(message='Tôi lái Vios tới 132 Bến Vân Đồn, Quận 4, đỗ xe 2 tiếng tối nay 7h. Vào được không?'))
        self.assertIsNone(question)
        self.assertEqual(args['query'],'132 Bến Vân Đồn, Quận 4')
        self.assertEqual(args['intent'],'park')
        self.assertEqual(agent.datetime.fromisoformat(args['arrive_at']).hour,19)
        self.assertEqual(args['dwell_min'],120)
        args,_=agent.driver_request(agent.AgentRequest(message='Vios tới 12 Quang Trung, Gò Vấp, đỗ 2 giờ'))
        self.assertEqual(agent.datetime.fromisoformat(args['arrive_at']).hour,agent.datetime.now(agent.VN_TZ).hour)
        args,question=agent.driver_request(agent.AgentRequest(message='VF3 đón khách tại bệnh viện Chợ Rẫy sáng mai 8 giờ, dừng 10 phút.'))
        self.assertEqual(args['query'],'bệnh viện Chợ Rẫy')
        self.assertEqual(args['intent'],'pickup')
        self.assertEqual(args['dwell_min'],10)

    def test_vehicle_aliases_and_relative_local_time(self):
        for label,vid in [('VF3','vinfast-vf-3'),('VF 5','vinfast-vf-5'),('Fortuner','toyota-fortuner'),('xe 7 chỗ','class-m'),('xe cỡ nhỏ','class-xs')]:
            self.assertEqual(agent.normalize_vehicle(label),vid)
        now=agent.datetime(2026,12,31,22,tzinfo=agent.VN_TZ)
        self.assertEqual(agent.parse_arrival('sáng mai 8h',now).isoformat(),'2027-01-01T08:00:00+07:00')
        self.assertEqual(agent.parse_arrival('tối nay 7h',now).hour,19)
        self.assertEqual(agent.parse_arrival('2026-10-17T08:00:00').utcoffset(),agent.timedelta(hours=7))

    def test_tool_deadline_and_progress(self):
        release=threading.Event()
        runner=agent.bounded(lambda:release.wait(5),.02)
        try:
            with self.assertRaisesRegex(ValueError,'timed out'):list(runner)
        finally:release.set()
        with patch.object(agent.queue.Queue,'get',side_effect=[agent.queue.Empty,(True,'done')]), patch.object(agent.threading.Thread,'start'):
            runner=agent.bounded(lambda:None,5)
            self.assertEqual(next(runner)['type'],'progress')
            with self.assertRaises(StopIteration) as caught:next(runner)
            self.assertEqual(caught.exception.value,'done')
            agent._TOOL_SLOTS.release() # mocked worker cannot release its admission slot

    def test_goong_failure_falls_through_osm_then_nominatim(self):
        import httpx
        with patch.object(agent.httpx,'get',side_effect=httpx.ConnectError('redacted')),patch.object(geocoding,'local_search',return_value=[]),patch.object(agent,'_nominatim',return_value=[{'label':'42 Võ Văn Ngân, Thủ Đức','lat':10.85,'lon':106.76,'source':'Nominatim'}]) as nom:
            r=agent.resolve_place('42 Võ Văn Ngân, Thủ Đức')
        self.assertEqual(r['results'][0]['source'],'Nominatim');nom.assert_called_once()

    def test_ambiguity_nearest_origin_and_exact_house(self):
        places=[{'label':'Highlands A','lat':10.8,'lon':106.7,'source':'fixture'}, {'label':'Highlands B','lat':10.9,'lon':106.7,'source':'fixture'}]
        with patch('app.config.GOONG_API_KEY',''),patch.object(geocoding,'local_search',return_value=[]),patch.object(agent,'_nominatim',return_value=places):
            r=agent.resolve_place('Highlands')
            self.assertTrue(r['requires_clarification'])
            r=agent.resolve_place('Highlands',(10.89,106.7))
            self.assertFalse(r['requires_clarification']);self.assertEqual(r['results'][0]['label'],'Highlands B')
            self.assertIn('closest',r['selection_reason'])

    def test_number_guard_repairs_answer_and_history(self):
        call={'role':'model','parts':[{'functionCall':{'name':'lap_ke_hoach','args':{}}}]}
        reply={'role':'model','parts':[{'text':'Hẻm rộng 99 m, đi bộ 999 m.'}]}
        result={'verdict':{'headline':'Chưa đủ bằng chứng.'},'stop_points':[], 'request':{'dwell_min':120}}
        with patch.object(agent,'generate',side_effect=[{'candidates':[{'content':call}]},{'candidates':[{'content':reply}]}]),patch.object(agent,'execute',return_value=(result,None)):
            events=list(agent.events(agent.AgentRequest(message='Kiểm tra')))
        self.assertTrue(any(e['type']=='validation' for e in events))
        answer=next(e['text'] for e in events if e['type']=='answer')
        self.assertNotIn('99',answer)
        self.assertEqual(events[-1]['contents'][-1]['parts'],[{'text':answer}])
        self.assertFalse(agent.number_violations('1,90 m lúc 08:00',[{'width':1.9,'time':'08:00'}]))

    def test_no_duplicate_tool_execution_or_unresolved_coordinates(self):
        call={'role':'model','parts':[{'functionCall':{'name':'tim_dia_diem','args':{'query':'unknown'}}}]}
        reply={'role':'model','parts':[{'text':'Xin xác nhận địa chỉ.'}]}
        with patch.object(agent,'generate',side_effect=[{'candidates':[{'content':copy.deepcopy(call)}]},{'candidates':[{'content':copy.deepcopy(call)}]},{'candidates':[{'content':reply}]}]),patch.object(agent,'execute',return_value=({'results':[]},None)) as tool:
            list(agent.events(agent.AgentRequest(message='Tìm địa chỉ')))
        self.assertEqual(tool.call_count,1)

    def test_quota_fallback_and_cancellation(self):
        req=agent.AgentRequest(message='asdfgh ???',request_id='cancel-test')
        with patch.object(agent,'generate',side_effect=ValueError('Gemini miễn phí đang bận')):
            events=list(agent.events(req))
        self.assertEqual(events[-1]['type'],'done')
        agent.cancel('cancel-test')
        with patch.object(agent,'generate') as generate:
            events=list(agent.events(req));generate.assert_not_called()
        self.assertEqual(events[-1]['type'],'error')

    def test_free_hard_cap_and_paid_rejection_releases_reservation(self):
        import httpx
        with tempfile.TemporaryDirectory() as d,patch.object(agent_budget,'STORE',Path(d)),patch.object(agent_budget,'FILE',Path(d)/'ledger.json'),patch.dict(os.environ,{'AGENT_FREE_CALL_LIMIT':'1','AGENT_ALLOW_PAID':'1'}):
            agent_budget.free_call()
            with self.assertRaises(ValueError):agent_budget.free_call()
            body={'contents':[],'generationConfig':{'maxOutputTokens':32}}
            with patch.object(agent.ai,'gemini_keys',return_value=[]),patch.dict(os.environ,{'PROD_GEMINI_API_KEY':'test-secret'}),patch.object(agent.httpx,'post',return_value=httpx.Response(403)):
                with self.assertRaises(ValueError):agent.generate(body,True)
            r=agent_budget.report();self.assertEqual(r['spent_usd'],0);self.assertFalse(r['reservations'])

    def test_raw_http_protocol_and_new_tools(self):
        client=TestClient(main.app)
        headers={'Accept':'application/json, text/event-stream','MCP-Protocol-Version':'2025-11-25'}
        def rpc(method,params=None,ident=1):return client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':ident,'method':method,'params':params or {}})
        r=rpc('initialize',{'protocolVersion':'2025-11-25'})
        self.assertEqual(r.json()['result']['protocolVersion'],'2025-11-25')
        r=rpc('tools/list'); names={t['name'] for t in r.json()['result']['tools']}
        self.assertTrue({'check_alley_fit','find_nearby_stops','list_vehicles'}<=names)
        r=rpc('tools/call',{'name':'danh_sach_xe','arguments':{}})
        self.assertFalse(r.json()['result']['isError']);self.assertTrue(r.json()['result']['structuredContent']['vehicles'])
        self.assertEqual(rpc('tools/call',{'name':'lap_ke_hoach','arguments':{}}).json()['error']['code'],-32602)
        self.assertEqual(rpc('missing').json()['error']['code'],-32601)
        self.assertEqual(client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'}).status_code,202)
        self.assertEqual(client.get('/mcp').status_code,405)
        self.assertEqual(client.post('/mcp',headers={**headers,'Origin':'https://evil.example'},json={}).status_code,403)
        self.assertEqual(client.post('/mcp',headers={**headers,'MCP-Protocol-Version':'invalid'},json={}).status_code,400)
        self.assertEqual(client.post('/mcp',headers={**headers,'Content-Type':'application/json'},content='{').json()['error']['code'],-32700)
        self.assertEqual(rpc('tools/call',{'name':'kiem_tra_xe_vao_hem','arguments':{'way_id':True,'lat':10.8,'lon':106.7,'vehicle_id':'VF3'}}).json()['error']['code'],-32602)

    def test_single_alley_and_stop_only_are_engine_adapters(self):
        from types import SimpleNamespace
        wr=SimpleNamespace(to_json=lambda:{'lo':1.8,'hi':2.0,'evidence':[{'source':'fixture'}]})
        with patch.object(main.plan,'area',return_value=(object(),{123:wr},{})),patch.object(main.plan,'compute_fit',return_value=({123:'no'},{})):
            result,_=agent.execute('kiem_tra_xe_vao_hem',{'lat':10.8,'lon':106.7,'way_id':123,'vehicle_id':'VF3'})
        self.assertEqual(result['fit'],'no');self.assertTrue(result['evidence'])
        compact={'destination':{},'vehicle':{},'window':{},'stop_points':[],'door':{},'standard_route':{}}
        with patch.object(main.plan,'plan',return_value={}),patch.object(agent,'compact_plan',return_value=compact):
            result,_=agent.execute('tim_cho_do_gan',{'lat':10.8,'lon':106.7,'label':'fixture','vehicle_id':'VF3','arrive_at':'2026-10-17T08:00:00+07:00','dwell_min':15,'intent':'pickup'})
        self.assertNotIn('door',result);self.assertNotIn('standard_route',result)

if __name__=='__main__':unittest.main()
