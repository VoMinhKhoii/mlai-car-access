"""Offline regression checks for breadth caching, atomic tide updates and OSM halos."""
import json
import sys
import tempfile
import subprocess
import threading
import time
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from app import coverage, parcels, portal_gate, tide_refresh
from app.parcel_points import ParcelPoints
from shapely.geometry import Polygon
import osm_city_cache

ROOT = Path(__file__).resolve().parents[1]


class PointCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.cache = ParcelPoints(Path(self.temp.name) / 'points.db')
        self.poly = Polygon([(106.7000, 10.8000), (106.7002, 10.8000),
                             (106.7002, 10.8002), (106.7000, 10.8002)])

    def tearDown(self):
        self.cache.close()
        self.cache.db().close()
        self.temp.cleanup()

    def test_inside_polygon_reused_but_outside_never_extrapolated(self):
        with patch.object(parcels, '_parcel', return_value={'id': 'p1', 'poly': self.poly}) as fetch:
            self.cache(10.80005, 106.70005)
            self.cache(10.80015, 106.70015)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(self.cache.stats['polygon_hits'], 1)
            self.assertFalse(self.cache.lookup(10.80015, 106.70025)[0])

    def test_null_is_exact_and_transport_failure_not_cached(self):
        with patch.object(parcels, '_parcel', return_value=None) as fetch:
            self.cache(10.8, 106.7)
            self.cache(10.8, 106.7)
            fetch.assert_called_once()
            self.assertFalse(self.cache.lookup(10.80001, 106.7)[0])
        with patch.object(parcels, '_parcel', side_effect=parcels.Unavailable()):
            with self.assertRaises(parcels.Unavailable):
                self.cache(10.9, 106.8)
            self.assertFalse(self.cache.lookup(10.9, 106.8)[0])

    def test_expired_polygon_does_not_count_as_fresh(self):
        self.cache.remember(10.8, 106.7, {'id': 'p1', 'poly': self.poly})
        with self.cache.db() as db:
            db.execute('UPDATE parcels SET fetched_at=0')
        self.assertFalse(self.cache.lookup(10.80005, 106.70005)[0])

    def test_cached_geometry_keeps_exact_cross_section_semantics(self):
        # 4 m surveyed gap -> 3 m usable, with the original offsets/rays/margin.
        lat0, lon0 = 10.8, 106.7
        left = Polygon([(lon0-10/parcels.KX,lat0-10/parcels.KY), (lon0-2/parcels.KX,lat0-10/parcels.KY),
                        (lon0-2/parcels.KX,lat0+10/parcels.KY),(lon0-10/parcels.KX,lat0+10/parcels.KY)])
        right = Polygon([(lon0+2/parcels.KX,lat0-10/parcels.KY), (lon0+10/parcels.KX,lat0-10/parcels.KY),
                         (lon0+10/parcels.KX,lat0+10/parcels.KY),(lon0+2/parcels.KX,lat0+10/parcels.KY)])
        self.cache.remember(lat0,lon0,{'id':'left','poly':left})
        self.cache.remember(lat0,lon0,{'id':'right','poly':right})
        def lookup(la,lo):
            hit, result = self.cache.lookup(la,lo)
            return result if hit else None
        gap = parcels._cross_section((lat0,lon0),(1,0),lat0,lon0,lookup)
        self.assertAlmostEqual(gap,4.0)


class GraphCacheTests(unittest.TestCase):
    def test_crossing_way_keeps_external_nodes_and_tagged_node(self):
        lat,lon=10.8,106.7
        data={'elements':[
            {'type':'node','id':1,'lat':lat,'lon':lon-.02,'tags':{'highway':'stop'}},
            {'type':'node','id':1,'lat':lat,'lon':lon-.02},
            {'type':'node','id':2,'lat':lat,'lon':lon+.02},
            {'type':'way','id':9,'nodes':[1,2],'tags':{'highway':'residential'}},
            {'type':'node','id':3,'lat':lat+.04,'lon':lon},
            {'type':'node','id':4,'lat':lat+.05,'lon':lon},
            {'type':'way','id':10,'nodes':[3,4],'tags':{'highway':'residential'}}]}
        area=osm_city_cache.Batch(data).area(lat,lon)
        self.assertEqual({e['id'] for e in area['elements'] if e['type']=='way'},{9})
        self.assertEqual({e['id'] for e in area['elements'] if e['type']=='node'},{1,2})
        self.assertEqual(next(e for e in area['elements'] if e['id']==1)['tags'],{'highway':'stop'})

    def test_atomic_graph_replacement_invalidates_memory_cache(self):
        from app import osm
        with tempfile.TemporaryDirectory() as temp, patch.object(osm,'CACHE',Path(temp)), \
             patch.object(osm,'DEMO_FILE',Path(temp)/'absent.json'), \
             patch.object(osm,'_GRAPHS',{}),patch.object(osm,'_GRAPH_STAMPS',{}), \
             patch.object(osm,'_fetch_overpass',side_effect=AssertionError('unexpected network')):
            key=osm.area_key(10.9,106.85)
            path=Path(temp)/'osm'/f'area_{key}.json';path.parent.mkdir()
            data={'elements':[{'type':'node','id':1,'lat':10.9,'lon':106.85},
                              {'type':'node','id':2,'lat':10.9001,'lon':106.85},
                              {'type':'way','id':9,'nodes':[1,2],'tags':{'highway':'residential'}}]}
            path.write_text(json.dumps(data))
            self.assertEqual(osm.cached_graph(10.9,106.85).nodes[2][0],10.9001)
            data['elements'][1]['lat']=10.900222
            replacement=path.with_suffix('.tmp');replacement.write_text(json.dumps(data));replacement.replace(path)
            self.assertEqual(osm.cached_graph(10.9,106.85).nodes[2][0],10.900222)


class TideTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.target=Path(self.temp.name)/'tide.json'
        self.target.write_text(json.dumps({'issued_at':'2026-10-16T09:08:00+07:00','keep':'last good'}))

    def tearDown(self):
        self.temp.cleanup()

    def test_parse_official_fixture_exactly_and_preserve_ct(self):
        fixture=ROOT/'data/flood/snapshots-2026-10-16/HCMC_TVHN_20261016.pdf'
        if not fixture.exists():
            self.skipTest('Historical source PDF is not shipped in this checkout')
        actual=tide_refresh.parse_pdf(fixture.read_bytes(),'https://kttvnb.vn/attachments/article/29368/HCMC_TVHN_20261016.pdf')
        reference=json.loads((ROOT/'pipelines/fixtures/tide_289_2026_expected.json').read_text())
        for key in ['issued_at','highs','lows','alarm_levels_m','low_level_m']:
            self.assertEqual(actual[key],reference[key])
        self.assertEqual(len(actual['highs']),11)
        self.assertFalse(any(h['t'].startswith('2026-10-18') and h['t'][11:16]!='08:00' for h in actual['highs']))

    def test_failure_preserves_last_good_file(self):
        before=self.target.read_bytes()
        with patch.object(tide_refresh,'TARGET',self.target), \
             patch.object(tide_refresh,'STATUS',Path(self.temp.name)/'status.json'), \
             patch.object(tide_refresh,'_get',side_effect=RuntimeError('network failed')):
            status=tide_refresh.refresh()
        self.assertEqual(status['state'],'error')
        self.assertEqual(self.target.read_bytes(),before)

    def test_malformed_pdf_does_not_parse_as_data(self):
        with self.assertRaises(Exception):
            tide_refresh.parse_pdf(b'%PDF not a valid bulletin','https://kttvnb.vn/bad.pdf')


class PortalGateTests(unittest.TestCase):
    def test_shared_backoff_rejects_without_request(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(portal_gate,'DIRECTORY',Path(temp)):
            portal_gate.backoff(60)
            self.assertGreaterEqual(portal_gate.request_interval(),1.0)
            with self.assertRaises(parcels.Blocked):
                with portal_gate.slot():
                    self.fail('request should not start')

    def test_two_request_cap_across_threads(self):
        active, maximum = 0, 0
        guard=threading.Lock()
        def work():
            nonlocal active,maximum
            with portal_gate.slot():
                with guard:
                    active+=1; maximum=max(maximum,active)
                time.sleep(.25)
                with guard: active-=1
        with tempfile.TemporaryDirectory() as temp, patch.object(portal_gate,'DIRECTORY',Path(temp)), patch.object(portal_gate,'request_interval',return_value=.20):
            threads=[threading.Thread(target=work) for _ in range(6)]
            for t in threads:t.start()
            for t in threads:t.join()
        self.assertEqual(maximum,2)


class CampusTests(unittest.TestCase):
    def test_full_way_has_no_sixty_cut_cap(self):
        import campus_priority
        coords=[(10.8,106.7),(10.8+700/parcels.KY,106.7)]
        with patch.object(parcels,'measure',return_value={'samples':[3.0],'cuts':[]}) as measure:
            _,count=campus_priority.full_measure(coords,lambda *args:None)
        self.assertGreater(measure.call_args.kwargs['max_cuts'],60)
        self.assertEqual(count,140)
        self.assertEqual(measure.call_args.kwargs['step'],5.0)

    def test_circle_includes_segment_crossing_even_if_ends_are_outside(self):
        import campus_priority
        coords=[(10.8,106.7-.03),(10.8,106.7+.03)]
        self.assertTrue(campus_priority.within(coords,10.8,106.7))
        self.assertFalse(campus_priority.within([(10.85,106.7),(10.86,106.7)],10.8,106.7))

    def test_overlapping_campuses_share_completion_and_missing_deep_data_is_honest(self):
        import campus_priority
        state={'campus_deep_done':{'1':{'attempted_cuts':4,'with_data':False}},
               'ways_meta':{'1':{'alley':True}},'campuses':{
                   'a':{'started_at':campus_priority.now()},'b':{'started_at':campus_priority.now()}}}
        campus_priority.update_counts(state,{'1':{'samples':[3.0],'deep':False}}, {'a':{'1'},'b':{'1'}})
        for c in state['campuses'].values():
            self.assertEqual(c['ways_deep_completed'],1)
            self.assertEqual(c['ways_with_cadastral_width'],1)
            self.assertEqual(c['ways_deep_with_width'],0)
            self.assertIn('finished_at',c)

    def test_deep_city_width_survives_stale_shallow_area(self):
        from app import live
        from types import SimpleNamespace
        deep={'samples':[2.0],'cuts':[], 'deep':True}
        shallow={'way_id':1,'samples':[4.0],'cuts':[], 'deep':False}
        with patch.object(live,'city_parcels',return_value={'1':deep}):
            got=live._merge_city(SimpleNamespace(ways={1:object()}),[shallow])
        self.assertEqual(got,[{'way_id':1,**deep}])

    def test_only_changed_destination_cache_keys_overwrite_concurrent_updates(self):
        from app import live
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'parcels.json'
            path.write_text(json.dumps({'old':{'samples':[2]},'other':{'samples':[3]}}))
            live._save_parcel_cache(path,{'old':{'samples':[1]},'new':None},{'old':{'samples':[1]}})
            self.assertEqual(json.loads(path.read_text()),{'old':{'samples':[2]},'other':{'samples':[3]},'new':None})

    def test_shared_area_preserves_each_campus_listing_and_news(self):
        from app import live
        with tempfile.TemporaryDirectory() as temp,patch.object(live,'AREAS_DIR',Path(temp)),patch.object(live,'_areas',__import__('app.storage',fromlist=['LRU']).LRU(32)):
            def area(wid,url):
                return {'key':'demo','complete':True,'steps':{},'counts':{},'parcels':[], 'listings':[{'listing_id':wid,'url':url}],
                        'news':[{'street':str(wid),'url':url}], 'photos':[]}
            live._publish(area(1,'first'))
            live._publish(area(2,'second'))
            saved=live._load_area('demo')
            self.assertEqual(len(saved['listings']),2)
            self.assertEqual(len(saved['news']),2)
            self.assertEqual(saved['revision'],2)

    def test_cooldown_scan_is_offline_and_never_completes_a_cache_miss(self):
        import campus_priority
        from types import SimpleNamespace
        state={'ways_meta':{'1':{'coords':[(10.8,106.7),(10.8002,106.7)],'alley':True},
                            '2':{'coords':[(10.81,106.7),(10.8102,106.7)],'alley':True}},
               'campus_deep_done':{},'campuses':{'a':{'started_at':campus_priority.now()}}}
        lookup=SimpleNamespace(stats={'requests':0},lookup=lambda lat,lon:(True,None) if lat<10.805 else (False,None))
        queue=['1','2'];cache={}
        with patch.object(parcels,'_parcel',side_effect=AssertionError('network forbidden')) as network:
            campus_priority.offline_pass(queue,state,cache,lookup,{'a':{'1','2'}},threading.Event(),Mock(),Mock(),threading.RLock())
        network.assert_not_called()
        self.assertEqual(queue,['2'])
        self.assertIn('1',state['campus_deep_done'])
        self.assertNotIn('2',state['campus_deep_done'])
        self.assertTrue(state['campus_deep_done']['1']['offline'])

    def test_full_campus_scan_survives_an_older_partial_deep_area(self):
        from app import live
        from types import SimpleNamespace
        full={'samples':[2.0]*7,'cuts':[], 'deep':True,'sample_strategy':'campus-full-5m','queried_at':'2026-10-17T00:25:00+07:00'}
        partial={'way_id':1,'samples':[4.0]*3,'cuts':[], 'deep':True}
        with patch.object(live,'city_parcels',return_value={'1':full}):
            got=live._merge_city(SimpleNamespace(ways={1:object()}),[partial])
        self.assertEqual(got,[{'way_id':1,**full}])


class MultiProcessGateTests(unittest.TestCase):
    def test_request_limit_is_shared_across_processes(self):
        code="""
import sys,time,json,threading
from pathlib import Path
sys.path.insert(0,'backend')
from app import portal_gate
portal_gate.DIRECTORY=Path(sys.argv[1])
portal_gate.request_interval=lambda:.20
def work():
    with portal_gate.slot():
        start=time.time()
        time.sleep(.45)
        print(json.dumps([start,time.time()]),flush=True)
threads=[threading.Thread(target=work) for _ in range(3)]
for t in threads:t.start()
for t in threads:t.join()
"""
        with tempfile.TemporaryDirectory() as temp:
            children=[subprocess.Popen([sys.executable,'-c',code,temp],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
            intervals=[]
            for child in children:
                stdout,stderr=child.communicate(timeout=10)
                self.assertEqual(child.returncode,0,stderr)
                intervals.extend(json.loads(line) for line in stdout.splitlines())
        events=sorted([(a,1) for a,b in intervals]+[(b,-1) for a,b in intervals])
        current=maximum=0
        for _,delta in events:
            current+=delta;maximum=max(maximum,current)
        self.assertEqual(len(intervals),6)
        self.assertEqual(maximum,2)


if __name__=='__main__':
    unittest.main()
