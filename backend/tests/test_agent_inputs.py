"""Input regressions: providers/models/engine are mocked, no quota is spent."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import httpx
from app import agent, geocoding as geo
from app.vehicle_aliases import resolve_vehicle


def point(label, lat=10.761, lon=106.690, precision='alley', wid=123):
    return {'label':label,'lat':lat,'lon':lon,'precision':precision,'way_id':wid,
            'points':[[lat,lon]],'norm':geo.strip_accents(label)}


def response(body, status=200):
    return httpx.Response(status,json=body,request=httpx.Request('GET','https://mock.invalid'))


REAL_GOONG_KEYS = geo._goong_keys


class InputTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        patches=[patch.object(geo,'DB',Path(self.temp.name)/'geo.sqlite'),
                 patch.object(geo,'_curated',[]),patch.object(geo.config,'CACHED_ONLY',False),
                 patch.object(geo,'_goong_keys',return_value=['mock-a']),
                 patch.object(geo.httpx,'get',side_effect=AssertionError('Unexpected external HTTP')),
                 patch.object(geo,'nominatim',return_value=[]),patch.object(agent,'_nominatim',return_value=[])]
        for p in patches:p.start();self.addCleanup(p.stop)

    def test_reported_chain_uses_parent_and_runs_plan_with_disclosures(self):
        names=[point('Trần Đình Xu',precision='street',wid=1),point('Hẻm 137/41 Trần Đình Xu')]
        plan={'verdict':{'headline':'Ước tính vào chật.', 'estimate':{'answer':'tight','confidence':'low','basis':'bề rộng OSM'}},
              'stop_points':[], 'request':{'vehicle_id':'class-m'}}
        real=agent.execute
        def execute(name,args,*rest):
            if name=='lap_ke_hoach':return copy.deepcopy(plan),dict(args)
            return real(name,args,*rest)
        message='137/41/18 Trần Đình Xu, Cầu Ông Lãnh, Hồ Chí Minh, Vietnam - Merc GLC 200'
        with patch.object(geo,'initialize_name_index',return_value=names),patch.object(geo,'goong',return_value={}),patch.object(agent,'execute',side_effect=execute) as tool:
            req=agent.AgentRequest(message=message)
            events=list(agent.fallback_events(req,[]))
        calls=[c for c in tool.call_args_list if c.args[0]=='lap_ke_hoach']
        self.assertEqual(len(calls),1)
        self.assertEqual(calls[0].args[1]['vehicle_id'],'class-m')
        self.assertEqual(calls[0].args[1]['label'],'Hẻm 137/41 Trần Đình Xu')
        answer=next(e['text'] for e in events if e['type']=='answer')
        for word in ('137/41','house 18','not pinned','size class M','Estimate','Low confidence'):
            self.assertIn(word,answer)

    def test_chain_aliases_alpha_suffixes_and_one_typo(self):
        for label in ('Hẻm 5/2A Phan Văn Trị','Hẻm 5/2A/3/4 Phan Văn Trị','Hẻm 137/3A31 Cao Xuân Dục'):
            with patch.object(geo,'initialize_name_index',return_value=[point(label)]),patch.object(geo,'goong',return_value={}):
                for prefix in ('Hẻm','ngõ','kiệt','ngách','alley'):
                    q=label.replace('Hẻm',prefix).replace('Phan','Pha')+', phường Cầu Ông Lãnh, Hồ Chí Minh'
                    r=geo.resolve_place(q)
                    self.assertEqual(r['results'][0]['label'],label,q)
                    self.assertFalse(r['requires_clarification'])

    def test_full_chain_beats_parent_street_and_parent_alley(self):
        names=[point('Phan Văn Trị',precision='street',wid=1),point('Hẻm 5 Phan Văn Trị',wid=2),point('Hẻm 5/2A Phan Văn Trị',wid=3)]
        with patch.object(geo,'initialize_name_index',return_value=names),patch.object(geo,'goong',return_value={}):
            r=geo.resolve_place('5/2A/18 Phan Văn Trị')
        self.assertEqual(r['results'][0]['way_id'],3)
        self.assertTrue(r['house_unpinned']);self.assertFalse(r['requires_clarification'])

    def test_wrong_poi_never_matches_across_name_and_street(self):
        bad='Trường Đại học Sư phạm TP.HCM, 280 An Dương Vương'
        self.assertLess(geo.distinctive_coverage('Cong ty CP Vuong Pham',bad),.7)
        with patch.object(geo,'initialize_name_index',return_value=[]),patch.object(geo,'goong',return_value={'predictions':[{'description':bad+', Hồ Chí Minh','place_id':'bad'}]}),patch.object(geo,'place_detail') as detail:
            self.assertFalse(geo.resolve_place('Vương Phạm')['results']);detail.assert_not_called()

    def test_map_features_checked_before_provider_and_preserve_chain(self):
        ctx={'center':{'lat':10.761,'lon':106.690},'zoom':17,'candidates':[
            {'name':'Trần Đình Xu','lat':10.761,'lon':106.69,'layer':'streets'},
            {'name':'Hẻm 137/41 Trần Đình Xu','lat':10.7612,'lon':106.6901,'layer':'streets'},
            {'name':'Cong Ty CP Vuong Pham','lat':10.7613,'lon':106.6902,'layer':'point_map'}]}
        with patch.object(geo,'resolve_place',side_effect=AssertionError('Map feature must win')):
            for query in ('137/41/18 Trần Đình Xu','Cong ty CP Vuong Pham'):
                r=agent.resolve_place(query,map_context=ctx)
                self.assertEqual(len(r['results']),1);self.assertEqual(r['results'][0]['source'],'On the map')
                if query.startswith('137'):self.assertIn('137/41',r['results'][0]['label']);self.assertTrue(r['house_unpinned'])

    def test_supported_families_map_to_existing_profiles(self):
        samples={'Merc GLC 200':'class-m','Mercedes GLC300':'class-m','Mercedes C200':'mercedes-benz-c-class',
                 'Mercedes E300':'class-m','BMW X3':'class-m','Kia Sorento':'class-m','Honda CR-V':'class-m',
                 'Hyundai Tucson':'class-m','Honda City':'honda-city','Ford Ranger':'ford-ranger','16 chỗ':'class-xl',
                 'bán tải':'class-l','VF8':'vinfast-vf-8-the-all-new-2026'}
        for value,vid in samples.items():
            actual,note=resolve_vehicle(value);self.assertEqual(actual,vid,value)
            self.assertIn(actual,agent.vehicles.all_profiles())
            if vid=='class-m':self.assertIn('size class M',note)
        for bad in ('Honda Wave','xe máy','motorbike'):
            args,question=agent.driver_request(agent.AgentRequest(message=bad+' đến 137 Trần Đình Xu'))
            self.assertIsNone(args);self.assertIn('car',question)

    def test_model_cannot_stop_after_resolving_known_point_and_vehicle(self):
        geo_result={'results':[{'label':'Hẻm 137/41 Trần Đình Xu','lat':10.761,'lon':106.69}], 'requires_clarification':False}
        outputs=[{'candidates':[{'content':{'role':'model','parts':[{'functionCall':{'name':'tim_dia_diem','args':{'query':'137/41/18 Trần Đình Xu'}}}]}}]},
                 {'candidates':[{'content':{'role':'model','parts':[{'text':'Xin xác nhận địa chỉ.'}]}}]}]
        plan={'verdict':{'headline':'Ước tính vào chật.','estimate':{'answer':'tight','confidence':'low','basis':'OSM'}},'stop_points':[]}
        def execute(name,args,*rest):return (geo_result,None) if name=='tim_dia_diem' else (copy.deepcopy(plan),args)
        with patch.object(agent,'generate',side_effect=outputs),patch.object(agent,'execute',side_effect=execute) as tool:
            events=list(agent.events(agent.AgentRequest(message='137/41/18 Trần Đình Xu - Merc GLC 200')))
        self.assertEqual([c.args[0] for c in tool.call_args_list],['tim_dia_diem','lap_ke_hoach'])
        self.assertIn('Low confidence',next(e['text'] for e in events if e['type']=='answer'))

    def test_key_rotation_unauthorized_daily_quota_and_cache(self):
        keys=['mock-a','mock-b','mock-c'];seen=[]
        def get(url,**kw):
            key=kw['params']['api_key'];seen.append(key)
            return response({'status':'OVER_RATE_LIMIT'},429) if key=='mock-a' else response({'status':'REQUEST_DENIED'},403) if key=='mock-b' else response({'status':'OK','predictions':[]})
        with patch.object(geo,'_goong_keys',return_value=keys),patch.object(geo.httpx,'get',side_effect=get):
            first=geo.goong('v2/place/autocomplete',{'input':'test'})
            self.assertEqual(seen,keys)
            self.assertGreater(geo.goong_blocked_until('mock-a'),time.time()+1800)
            self.assertGreater(geo.goong_blocked_until('mock-b'),time.time()+1790)
            self.assertEqual(geo.goong('v2/place/autocomplete',{'input':'test'}),first)
            self.assertEqual(len(seen),3)
            geo.goong('v2/place/autocomplete',{'input':'next'})
            self.assertEqual(seen[-1],'mock-c');self.assertEqual(len(seen),4)
        with geo._db() as db:
            stored=json.dumps(db.execute('SELECT * FROM state').fetchall())
        self.assertNotIn('mock-a',stored);self.assertNotIn('mock-b',stored)


    def test_english_output_keeps_vietnamese_input_and_proper_names(self):
        self.assertIn('Always answer in ENGLISH', agent.system_prompt(True))
        for message in ('VF3 đến Hẻm 5/2A Phan Văn Trị', 'VF3 to Hẻm 5/2A Phan Văn Trị at 20:00, for 2 hours'):
            args, question = agent.driver_request(agent.AgentRequest(message=message))
            self.assertIsNone(question)
            self.assertEqual(args['query'], 'Hẻm 5/2A Phan Văn Trị')
        answer = agent.grounded_answer({'verdict':{'headline':'Chưa đủ bằng chứng',
            'estimate':{'answer':'tight','confidence':'medium','basis':'bề rộng OSM'},
            'unverified_reasons':['chưa xác minh pháp lý']},'stop_points':[]})
        self.assertIn('Medium confidence',answer)
        self.assertNotIn('Chưa',answer)
        self.assertIn('Stopping legality',answer)
        for text in ('Tôi lái Vios tới Hẻm 5 lúc 8h sáng', 'Vios toi Hem 5 luc 8h sang', 'Vios tới Hẻm 5 lúc 8h'):
            self.assertEqual(agent.parse_arrival(text).hour,8,text)
        self.assertEqual(agent.parse_arrival('Vios toi Hem 5 luc 7h toi nay').hour,19)

    def test_new_address_never_reuses_the_previous_turn_geocode(self):
        prior = {'results':[{'label':'Old destination','lat':10.8,'lon':106.7}], 'requires_clarification':False}
        history = [{'role':'user','parts':[{'functionResponse':{'name':'tim_dia_diem','response':prior}}]}]
        reply = {'candidates':[{'content':{'role':'model','parts':[{'text':'Please confirm the address.'}]}}]}
        new = {'results':[{'label':'Hẻm 5/2A Phan Văn Trị','lat':10.85,'lon':106.75}], 'requires_clarification':False}
        def execute(name,args,*rest):
            if name == 'tim_dia_diem':return new,None
            return {'verdict':{'estimate':{'answer':'tight','confidence':'low','basis':'fixture'}},'stop_points':[]},args
        with patch.object(agent,'generate',return_value=reply),patch.object(agent,'execute',side_effect=execute) as tool:
            list(agent.events(agent.AgentRequest(message='VF3 đến Hẻm 5/2A Phan Văn Trị',contents=history)))
        self.assertEqual([c.args[0] for c in tool.call_args_list],['tim_dia_diem','lap_ke_hoach'])
        self.assertEqual(tool.call_args_list[-1].args[1]['lat'],10.85)

    def test_punctuation_and_vehicle_only_followup_are_not_addresses(self):
        for text in ('Còn VF3?', 'VF3?', 'Mercedes C200?', 'Vios??'):
            self.assertIsNone(agent._destination_text(text),text)
        args,question=agent.driver_request(agent.AgentRequest(message='Còn VF3?'))
        self.assertIsNone(args);self.assertIn('address',question)

    def test_rotation_keeps_observed_breaker_when_next_key_times_out(self):
        with patch.object(geo,'_goong_keys',return_value=['mock-a','mock-b']),patch.object(geo.httpx,'get',side_effect=[
                response({'status':'REQUEST_DENIED'},403),httpx.ReadTimeout('mock timeout')]):
            self.assertEqual(geo.goong('v2/place/autocomplete',{'input':'timeout'}),{})
            self.assertGreater(geo.goong_blocked_until('mock-a'),time.time()+1790)

    def test_tiles_key_is_excluded_and_allowlist_selects_only_key_three(self):
        with patch.dict(os.environ, {'GOONG_KEY_NAMES':'GOONG_API_KEY_3,GOONG_API_KEY_10,GOONG_MAPTILES_KEY',
                                     'GOONG_API_KEY_3':'mock-3','GOONG_API_KEY_10':'mock-tiles'}):
            self.assertEqual(REAL_GOONG_KEYS(),['mock-3'])

    def test_numbered_street_and_latin_eth_names(self):
        names=[point('Đường Số 7',precision='street'),point('Hẻm 137 Trần Ðình Xu')]
        with patch.object(geo,'initialize_name_index',return_value=names),patch.object(geo,'goong',return_value={}):
            self.assertEqual(geo.resolve_place('Đường Số 7')['results'][0]['label'],'Đường Số 7')
            self.assertEqual(geo.resolve_place('Hẻm 137 Trần Đình Xu')['results'][0]['label'],'Hẻm 137 Trần Ðình Xu')


if __name__=='__main__':unittest.main()
