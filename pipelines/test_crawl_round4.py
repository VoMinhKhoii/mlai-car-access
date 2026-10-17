"""Offline checks: VOI order, geometry selection, shared gate and one night only."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock,patch
import crawl_city
import crawl_ranked as ranked
import schedule_crawl as schedule
from app import parcels,portal_gate as gate

ROOT=Path(__file__).resolve().parents[1]


class RankedTests(unittest.TestCase):
    def planner(self,hints=None,coords=None):
        coords=coords or [[106.7,10.8],[106.7,10.8+100/parcels.KY]]
        planner=ranked.CutPlanner({'ways':{'1':{'tags':{'highway':'service','service':'alley'},'coords':coords}}},city={},hints=hints or {})
        planner.junctions=lambda *args:[]
        return planner

    def test_queue_then_inner_then_breadth_with_deduplication(self):
        rows={str(i):{'tags':{'highway':'service','service':'alley'}} for i in range(1,26)}
        queue={'items':[{'way_id':i} for i in range(20,0,-1)]}
        items=ranked.ordered_items(queue,{'3','21','22'},rows)
        self.assertEqual([r['way_id'] for r in items[:20]],list(range(20,0,-1)))
        self.assertEqual([(r['way_id'],r['phase']) for r in items[20:]],[(21,'campus-inner'),(22,'campus-inner'),(23,'breadth'),(24,'breadth'),(25,'breadth')])

    def test_narrowest_located_station_selected_instead_of_even_midpoint(self):
        planner=self.planner({'1':[{'at_m':15,'gap_m':3},{'at_m':50,'gap_m':5}]})
        with patch.object(parcels,'_parcel',side_effect=AssertionError('No portal allowed')):
            plan=planner.select({'way_id':1,'thresholds_straddled':['sedan']})
        self.assertEqual(plan['at_m'],15)
        self.assertEqual(plan['thresholds_m'],{'sedan':2.18})
        self.assertEqual(plan['cut_reason'],'narrowest_cached_footprint_station')

    def test_junction_station_is_skipped_before_any_portal_query(self):
        planner=self.planner({'1':[{'at_m':5,'gap_m':2},{'at_m':20,'gap_m':3}]})
        planner.junctions=lambda *args:[(10.8+5/parcels.KY,106.7)]
        plan=planner.select({'way_id':1})
        self.assertEqual(plan['at_m'],20)
        self.assertIn('junction_frontage_unvalidated',plan['rejected_candidates'])

    def test_engine_corner_guard_is_reused(self):
        planner=self.planner({'1':[{'at_m':19,'gap_m':2},{'at_m':50,'gap_m':3}]},
                             [[106.7,10.8],[106.7,10.8+20/parcels.KY],[106.7+80/parcels.KX,10.8+20/parcels.KY]])
        plan=planner.select({'way_id':1})
        self.assertEqual(plan['at_m'],50)
        self.assertIn('corner_or_degenerate_cut',plan['rejected_candidates'])

    def test_missing_cached_graph_never_causes_overpass_or_portal_fetch(self):
        planner=self.planner();planner.junctions=lambda *args:None
        with patch.object(parcels,'_parcel',side_effect=AssertionError('No portal')):
            plan=planner.select({'way_id':1})
        self.assertEqual(plan['status'],'skip')

    def test_partial_measurement_preserves_old_cut_and_never_certifies_whole_way(self):
        old={'deep':True,'cuts':[{'at_m':10,'lat':10.8,'lon':106.7,'gap_m':4,'width_m':3,'valid':True}]}
        new={'samples':[2],'cuts':[{'at_m':20,'lat':10.8001,'lon':106.7,'gap_m':3,'width_m':2,'valid':True}],
             'coverage':{'complete':True,'all_valid':True}}
        merged=ranked.merge_result(old,new,{'at_m':20})
        self.assertEqual(merged['samples'],[3,2]);self.assertFalse(merged['coverage']['complete'])
        self.assertFalse(merged['deep']);self.assertTrue(merged['prior_scan_deep'])

    def test_runner_consumes_the_first_twenty_in_api_order(self):
        ids=list(range(20,0,-1));snapshot={'generated_at':'test','items':[{'way_id':i} for i in ids]}
        inventory={str(i):{'tags':{'highway':'service','service':'alley'}} for i in ids}
        planner=Mock();planner.ways=inventory;planner.inventory={}
        planner.coords.return_value=[(10.8,106.7),(10.801,106.7)]
        selected=[];stop=threading.Event()
        def select(row):
            selected.append(row['way_id'])
            return {**row,'status':'ready','fraction':.25,'at_m':25,'cut_lat':10.80025,'cut_lon':106.7,'cut_reason':'test'}
        planner.select.side_effect=select
        def measure(*args,**kwargs):
            if len(selected)==20:stop.set()
            return {'samples':[2], 'cuts':[{'at_m':25,'lat':10.80025,'lon':106.7,'width_m':2,'gap_m':3,'valid':True}], 'coverage':{}}
        state={'campus_inner_targets':{},'blocked':0,'errors':0};cache={}
        with patch.object(ranked,'CutPlanner',return_value=planner),patch.object(ranked,'queue_snapshot',return_value=(snapshot,'test')),             patch.object(gate,'observe_api_backoff'),patch.object(gate,'cooldown_until',return_value=0),patch.object(parcels,'measure',side_effect=measure):
            ranked.run(state,cache,Mock(),stop,Mock(),Mock())
        self.assertEqual(selected,ids)
        self.assertEqual(len(cache),20)
        self.assertTrue(all(not result['coverage']['complete'] for result in cache.values()))

    def test_remote_queue_url_is_rejected(self):
        with self.assertRaises(ValueError):ranked.queue_snapshot('https://example.com')


class ConservativeGateTests(unittest.TestCase):
    def test_default_backoff_is_two_four_eight_hours_and_persisted(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(gate,'DIRECTORY',Path(temp)),patch.object(gate,'_role','api'):
            stamp=time.time();gate.configure_crawler(stamp+200000,180)
            for i,expected in enumerate([7200,14400,28800,28800]):
                with patch.object(gate.time,'time',return_value=stamp+61*i):gate.backoff()
                data=json.loads((Path(temp)/'crawler_backoff.json').read_text())
                self.assertEqual(data['recovery_s'],expected)
                self.assertGreaterEqual(data['interval_s'],180)
            gate.release_crawler()
            self.assertEqual(gate.cooldown_until(),0)

    def test_active_crawler_backoff_cannot_block_new_or_legacy_api(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(gate,'DIRECTORY',Path(temp)),patch.object(gate,'_role','api'):
            root=Path(temp)
            (root/'cooldown.json').write_text(json.dumps({'owner':'crawler','until':time.time()+100,'interval_s':30}))
            gate.configure_crawler(time.time()+10000,180);gate.backoff()
            lease=json.loads((root/'crawler_lease.json').read_text());legacy=json.loads((root/'cooldown.json').read_text())
            self.assertEqual(lease['interval_s'],.5);self.assertEqual(legacy['until'],0)
            self.assertGreater(lease['crawler_interval_s'],0)
            with patch.object(gate,'_role','api'):
                self.assertEqual(gate.cooldown_until(),0);self.assertEqual(gate.request_interval(),.5)
            self.assertGreater(gate.cooldown_until(),time.time())

    def test_api_lock_is_adopted_with_stricter_crawler_recovery(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(gate,'DIRECTORY',Path(temp)),patch.object(gate,'_role','api'):
            stamp=time.time();gate.backoff()
            api_until=gate.cooldown_until();gate.configure_crawler(stamp+20000,180)
            gate.observe_api_backoff()
            self.assertGreaterEqual(gate.cooldown_until(),stamp+7200)
            with patch.object(gate,'_role','api'):self.assertEqual(gate.cooldown_until(),api_until)

    def test_history_increases_spacing_and_does_not_treat_recovery_gap_as_quota(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(gate,'DIRECTORY',Path(temp)):
            rows=[{'role':'crawler','pid':1,'kind':'request_start','interval_s':30,'at':1},
                  {'role':'crawler','pid':1,'kind':'response','locked':True,'at':3601}]
            (Path(temp)/'portal_events.jsonl').write_text('\n'.join(json.dumps(row) for row in rows))
            learning=gate.learned_spacing(180)
            self.assertEqual(learning['interval_s'],180)
            self.assertEqual(learning['largest_failed_configured_spacing_s'],30)
            (Path(temp)/'crawler_backoff.json').write_text(json.dumps({'interval_s':360}))
            self.assertEqual(gate.learned_spacing(180)['interval_s'],360)

    def test_waiting_crawler_releases_rate_lock_for_api(self):
        code="""
import sys,time
from pathlib import Path
sys.path.insert(0,'backend')
from app import portal_gate as g
g.DIRECTORY=Path(sys.argv[1])
g.configure_crawler(time.time()+20,3)
(g.DIRECTORY/'rate.lock').write_text(str(time.time()))
(g.DIRECTORY/'ready').write_text('ready')
with g.slot():pass
"""
        api="""
import sys,time
from pathlib import Path
sys.path.insert(0,'backend')
from app import portal_gate as g
g.DIRECTORY=Path(sys.argv[1]);start=time.monotonic()
with g.slot():pass
print(time.monotonic()-start)
"""
        with tempfile.TemporaryDirectory() as temp:
            child=subprocess.Popen([sys.executable,'-c',code,temp],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
            try:
                deadline=time.monotonic()+5
                while not (Path(temp)/'ready').exists() and time.monotonic()<deadline:time.sleep(.02)
                self.assertTrue((Path(temp)/'ready').exists())
                result=subprocess.run([sys.executable,'-c',api,temp],cwd=ROOT,capture_output=True,text=True,timeout=3)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertLess(float(result.stdout.strip()),1.2)
            finally:
                child.terminate();child.communicate(timeout=3)


class NightWindowTests(unittest.TestCase):
    def test_wait_window_never_dispatches_early_or_after_stop(self):
        stamp=[10.0];stop=threading.Event()
        def wait(seconds):stamp[0]+=seconds
        self.assertTrue(schedule.wait_window(100,200,stop,clock=lambda:stamp[0],wait=wait))
        self.assertEqual(stamp[0],100)
        self.assertFalse(schedule.wait_window(100,100,stop,clock=lambda:stamp[0],wait=wait))
        stop.set();self.assertFalse(schedule.wait_window(100,200,stop,clock=lambda:150,wait=wait))

    def test_cancelled_schedule_has_no_exec_network_or_portal_lease(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(sys,'argv',['schedule','--status',str(Path(temp)/'status.json')]), \
             patch.object(schedule,'wait_window',return_value=False),patch.object(os,'execv') as execute, \
             patch.object(gate,'configure_crawler') as configure, patch.object(schedule.signal,'signal'), patch('builtins.print'):
            schedule.main()
            execute.assert_not_called();configure.assert_not_called()
            self.assertEqual(json.loads((Path(temp)/'status.json').read_text())['portal_requests_before_start'],0)

    def test_dispatch_is_ranked_with_fixed_deadline_and_retains_same_pid(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(sys,'argv',['schedule','--status',str(Path(temp)/'status.json')]), \
             patch.object(schedule,'wait_window',return_value=True),patch.object(os,'execv') as execute, \
             patch.object(os,'chdir'),patch.dict(os.environ,{},clear=False), patch.object(schedule.signal,'signal'), patch('builtins.print'):
            schedule.main();args=execute.call_args.args[1]
            self.assertIn('--ranked',args);self.assertIn('180',args)
            self.assertIn('2026-10-18T07:00:00+07:00',args)
            status=json.loads((Path(temp)/'status.json').read_text())
            self.assertEqual(status['pid'],os.getpid());self.assertFalse(status['recurring'])


if __name__=='__main__':unittest.main()
