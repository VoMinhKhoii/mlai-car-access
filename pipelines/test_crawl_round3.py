"""Offline regression checks for fair sampling and demo-safe portal leases."""
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import crawl_city  # establishes backend import path
import campus_priority as campus
import crawl_scheduler as scheduler
from app import parcels, portal_gate as gate


class Round3Tests(unittest.TestCase):
    def test_inner_circle_includes_crossing_and_ring_excludes_another_campus_inner(self):
        state = {'ways_meta': {'1': {'coords': [(10.8,106.7),(10.8001,106.7)]},
                                '2': {'coords': [(10.81,106.7),(10.8101,106.7)]}},
                 'campuses': {'a': {}, 'b': {}}}
        points = [{'id':'a','lat':10.8,'lon':106.7}, {'id':'b','lat':10.81,'lon':106.7}]
        inner, ring = campus.classify(state, {'a':{'1','2'},'b':{'1','2'}}, points)
        self.assertEqual(inner, {'1','2'}); self.assertEqual(ring, set())
        self.assertEqual(state['campus_deep_ways_target'],2)
        self.assertTrue(campus.within([(10.8,106.69),(10.8,106.71)],10.8,106.7,500))

    def test_extra_breadth_cuts_never_call_network(self):
        lookup = Mock(); lookup.lookup.return_value = (False,None)
        coords = [(10.8,106.7),(10.8002,106.7)]
        with patch.object(parcels,'measure', side_effect=[{'samples':[3],'cuts':[]}, scheduler.CacheMiss()]):
            value, count = scheduler.breadth_measure(coords, lookup)
        self.assertEqual(count,1); self.assertEqual(value['samples'],[3])
        lookup.assert_not_called()

    def test_offline_centre_cache_miss_remains_unknown(self):
        lookup=Mock();lookup.lookup.return_value=(False,None)
        with self.assertRaises(scheduler.CacheMiss):
            scheduler.breadth_measure([(10.8,106.7),(10.8002,106.7)],lookup,True)
        lookup.assert_not_called()

    def test_dead_or_expired_crawler_cooldown_does_not_block_api(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gate,'DIRECTORY',Path(temp)), patch.object(gate,'_role','api'):
            root=Path(temp)
            for lease in [{'pid':os.getpid(),'until':time.time()-1}, {'pid':99999999,'until':time.time()+600}]:
                (root/'crawler_lease.json').write_text(json.dumps(lease))
                (root/'cooldown.json').write_text(json.dumps({'until':time.time()+600,'owner':'crawler','interval_s':20}))
                self.assertEqual(gate.cooldown_until(),0)
                self.assertEqual(gate.request_interval(),.5)
                with gate.slot():pass

    def test_release_clears_owned_cooldown_but_preserves_api_backoff(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gate,'DIRECTORY',Path(temp)), patch.object(gate,'_role','api'):
            gate.configure_crawler(time.time()+600,6)
            gate.backoff(600)
            self.assertGreater(gate.cooldown_until(),time.time())
            gate.release_crawler()
            self.assertEqual(gate.cooldown_until(),0)
            gate.configure_crawler(time.time()+600,6)
            with patch.object(gate,'_role','api'):gate.backoff(600)
            gate.release_crawler()
            with patch.object(gate,'_role','api'):
                self.assertGreater(gate.cooldown_until(),time.time())

    def test_repeated_crawler_locks_increase_quiet_time_without_leaking_to_api(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gate,'DIRECTORY',Path(temp)), patch.object(gate,'_role','api'):
            stamp=time.time();gate.configure_crawler(stamp+10000,6)
            gate.backoff(60)
            with patch.object(gate.time,'time',return_value=stamp+61):gate.backoff(60)
            data=json.loads((Path(temp)/'crawler_backoff.json').read_text())
            self.assertEqual(data['recovery_s'],120)
            self.assertEqual(data['interval_s'],24)
            gate.release_crawler();self.assertEqual(gate.cooldown_until(),0)

    def test_configure_cannot_replace_another_live_crawler_lease(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(gate,'DIRECTORY',Path(temp)), patch.object(gate,'_role','api'):
            value={'pid':os.getppid(),'until':time.time()+600,'interval_s':6}
            (Path(temp)/'crawler_lease.json').write_text(json.dumps(value))
            with self.assertRaises(RuntimeError):gate.configure_crawler(time.time()+600,6)
            self.assertEqual(json.loads((Path(temp)/'crawler_lease.json').read_text()),value)

    def test_rate_file_is_read_from_start_and_threads_are_actually_spaced(self):
        starts=[]
        def work():
            with gate.slot():starts.append(time.time())
        with tempfile.TemporaryDirectory() as temp, patch.object(gate,'DIRECTORY',Path(temp)), patch.object(gate,'request_interval',return_value=.2):
            threads=[threading.Thread(target=work) for _ in range(4)]
            for thread in threads:thread.start()
            for thread in threads:thread.join()
        starts.sort()
        self.assertTrue(all(b-a >= .19 for a,b in zip(starts,starts[1:])),starts)

    def test_deep_chunks_resume_at_five_metre_spacing_without_premature_completion(self):
        coords=[(10.8,106.7),(10.8+101/parcels.KY,106.7)]
        partial=None;positions=[]
        with patch.object(parcels,'_cut_at',side_effect=lambda line,at,*args: positions.append(at) or {'width_m':3}):
            result,cuts,partial=scheduler.deep_chunk(coords,Mock(),partial)
            self.assertEqual(cuts,2);self.assertIsNotNone(partial)
            while partial is not None:
                result,cuts,partial=scheduler.deep_chunk(coords,Mock(),partial)
        self.assertEqual(positions,[2.5+5*i for i in range(20)])
        self.assertEqual(len(result['samples']),20)

    def test_deep_chunk_matches_original_tail_cut_clamp(self):
        coords=[(10.8,106.7),(10.8+8/parcels.KY,106.7)];positions=[]
        with patch.object(parcels,'_cut_at',side_effect=lambda line,at,*args: positions.append(at)):
            scheduler.deep_chunk(coords,Mock())
        self.assertAlmostEqual(positions[0],2.5)
        self.assertAlmostEqual(positions[1],7,places=5)

    def test_missing_first_side_skips_only_unnecessary_opposite_queries(self):
        query=Mock(return_value=None)
        self.assertIsNone(parcels._cross_section((10.8,106.7),(1,0),10.8,106.7,query))
        self.assertEqual(query.call_count,len(parcels.OFFSETS))

    def test_city_completes_before_inner_queue_is_exhausted(self):
        inner={str(i) for i in range(1,11)}; ring={str(i) for i in range(11,21)}
        cityids=iter(str(i) for i in range(21,41))
        class City:
            def __init__(self,*args):self.finished=False;self.queue=[]
            def next(self):
                value=next(cityids,None)
                self.finished=value is None
                return value
        state={'campus_deep_done':{},'campuses':{},'ways_meta':{str(i):{'coords':[(10.8,106.7),(10.8001,106.7)]} for i in range(1,41)},'blocked':0,'errors':0}
        result={'samples':[3.0],'cuts':[]};cache={}
        with patch.object(scheduler,'CityQueue',City),patch.object(gate,'cooldown_until',return_value=0), \
             patch.object(scheduler,'deep_chunk',return_value=(result,2,None)),patch.object(scheduler,'breadth_measure',return_value=(result,1)):
            scheduler.run(state,cache,SimpleNamespace(stats={'requests':0}),inner,ring,[],{},threading.Event(),Mock(),Mock(),threading.RLock())
        events=state['round3_completion_events'];firstcity=next(i for i,e in enumerate(events) if e['kind']=='city')
        self.assertLess(sum(e['kind']=='inner' for e in events[:firstcity]),10)
        self.assertEqual(state['round3_completed'],{'inner':10,'ring':10,'city':20})


if __name__=='__main__':unittest.main()
