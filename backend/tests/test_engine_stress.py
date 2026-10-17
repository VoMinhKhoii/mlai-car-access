"""Real cached regressions plus independent safeguards for automatic cuts."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from app import evidence as ev, osm, plan, vehicles
from test_engine_routes import graph, candidate


class StressWidthRules(unittest.TestCase):
    def test_failed_official_survey_with_finite_prior_cannot_invent_1_5m(self):
        w = osm.Way(1185234990, {'highway':'residential','name':'Đường Nguyễn Thành Ý'}, [1,2])
        bounds = ev._osm_bounds(w) + [ev.Bound(0,40,'Official','failed survey','',
                    coverage_complete=False, measurement_schema='parcel-survey-unresolved-v2')]
        lo,hi,tier,review,overruled = ev._combine(bounds)
        wr = ev.WidthRange(lo,hi,tier,bounds,review,overruled)
        self.assertEqual((lo,hi),(0,15))
        self.assertEqual(plan.fit_class(wr,vehicles.get_profile('toyota-vios')),'unknown')
        hypothesis = plan._width_hypothesis(wr)
        self.assertEqual(hypothesis['value_m'],5)
        self.assertEqual(hypothesis['tier'],'Inferred')
        self.assertTrue(hypothesis['fallback_from_unresolved'])

    def test_weaker_cap_cannot_be_reported_as_official_sample(self):
        wr=ev.WidthRange(0,1.5,'Official',[
            ev.Bound(0,7,'Official','sample','',coverage_complete=False,estimate_m=6.7),
            ev.Bound(.5,1.5,'Declared','listing','')])
        h=plan._width_hypothesis(wr)
        self.assertEqual(h['value_m'],6.7)
        self.assertEqual(h['source'],'sample')
        # The separate fused cap is still a hard exclusion.
        self.assertEqual(plan.fit_class(wr,vehicles.get_profile('toyota-vios')),'no')

    def parcel_bound(self,g,widths,positions=None):
        cuts=[]
        for i,width in enumerate(widths):
            c={'width_m':width,'gap_m':width+1,'valid':True}
            if positions:
                la,lo=positions[i];c.update(lat=la,lon=lo)
            cuts.append(c)
        store=object.__new__(ev.EvidenceStore);store.by_way={};store.by_name={}
        store.live={'test':{'listings':[],'photos':[],'parcels':[{'way_id':20,'cuts':cuts,'samples':widths}]}}
        store._load_live()
        return ev._validate_parcel_bound(g,g.ways[20],store.by_way[20][0])

    def estimate(self,g,b):
        wr=ev.WidthRange(b.lo,b.hi,b.tier,[b]);ws={20:wr}
        c=candidate(g,20,20);c.data['walk_path']={'unverified':False}
        checks={'route_in':{'strict':False,'_segments':[(0,20)]},
                'way_out':{'mode':'through','strict':False,'_segments':[(0,80)]},
                'legality':{'status':'Unverified','rules':[]},'flood':{'stay':{'status':'unknown'}}}
        return plan._estimate(c,g,ws,vehicles.get_profile('toyota-vios'),checks,['Width bottleneck'])

    def test_single_or_isolated_valid_bottleneck_stays_hard_but_low_confidence(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        for widths in ([1],[1,4,4,4,4]):
            b=self.parcel_bound(g,widths)
            self.assertLessEqual(b.hi,1.3)
            self.assertEqual(plan.fit_class(ev.WidthRange(b.lo,b.hi,b.tier),vehicles.get_profile('toyota-vios')),'no')
            self.assertEqual(self.estimate(g,b)['confidence'],'low')

    def test_two_consistent_independent_cuts_can_confirm_a_negative(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        b=self.parcel_bound(g,[1,1.1,4],positions=[g.nodes[1],g.nodes[2],
                                                ((g.nodes[1][0]+g.nodes[2][0])/2,g.nodes[1][1])])
        self.assertEqual(b.sample_quality['bottleneck_support'],2)
        self.assertEqual(self.estimate(g,b)['confidence'],'high')

    def test_duplicate_locations_cannot_corroborate_a_bottleneck(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        b=self.parcel_bound(g,[1,1],positions=[g.nodes[1],g.nodes[1]])
        self.assertEqual(b.sample_quality['bottleneck_support'],1)
        self.assertEqual(self.estimate(g,b)['confidence'],'low')

    def test_cached_junction_cut_is_removed_but_other_samples_survive(self):
        g=graph({1:(0,0),2:(100,0),3:(200,0),4:(100,100)},[
            (20,[1,2,3],{}),(30,[2,4],{})])
        b=self.parcel_bound(g,[.4,5,5.1],positions=[g.nodes[2],g.nodes[1],g.nodes[3]])
        self.assertEqual(b.estimate_m,5)
        self.assertEqual(b.lo,0)
        self.assertEqual(b.sample_quality['rejected_cuts'][0]['rejection_reason'],'within_5m_of_junction')

    def test_all_invalid_cuts_remain_unresolved_not_a_positive_guarantee(self):
        g=graph({1:(0,0),2:(100,0),3:(200,0),4:(100,100)},[
            (20,[1,2,3],{}),(30,[2,4],{})])
        b=self.parcel_bound(g,[.4],positions=[g.nodes[2]])
        self.assertEqual((b.lo,b.hi,b.estimate_m),(0,40,None))
        self.assertFalse(b.coverage_complete)


class RealCachedStressRegressions(unittest.TestCase):
    """Fixtures carry raw OSM/cut inputs; no local caches or network are needed."""
    @classmethod
    def setUpClass(cls):
        cls.path=Path(__file__).parents[2]/'docs/eval/stress-regressions.json'
        cls.cases=json.loads(cls.path.read_text()) if cls.path.exists() else []

    def test_at_least_eleven_concrete_regressions_are_frozen(self):
        self.assertGreaterEqual(len(self.cases),11)

    def test_real_cached_way_hypotheses_and_cut_quality(self):
        for case in self.cases:
            with self.subTest(name=case['name'],way=case['way_id']):
                g=osm.graph_from_elements(case['lat'],case['lon'],case['elements'],'stress-regression')
                store=object.__new__(ev.EvidenceStore);store.by_way={};store.by_name={}
                store.live={'case':{'listings':[],'photos':[],'parcels':case['parcels']}}
                store._load_live()
                with patch.object(ev,'STORE_EVIDENCE',store),patch.object(store,'refresh_footprints',create=True), \
                     patch.object(store,'bounds_for',side_effect=lambda w:store.by_way.get(w.id,[])), \
                     patch.object(store,'way_out_for',return_value=[]):
                    widths=ev.width_ranges(g)
                wr=widths[case['way_id']];hyp=plan._width_hypothesis(wr)
                expected=case['expected']
                self.assertEqual(wr.lo,0)
                self.assertEqual(plan.fit_class(wr,vehicles.get_profile('toyota-vios')),expected['strict_fit'])
                if expected.get('min_estimate_m') is not None:
                    self.assertIsNotNone(hyp)
                    self.assertGreaterEqual(hyp['value_m'],expected['min_estimate_m'])
                if expected.get('tier'):self.assertEqual(hyp['tier'],expected['tier'])
                if expected.get('rejected_cut'):
                    self.assertTrue(any(b.sample_quality.get('rejected_cuts') for b in wr.evidence))
                if expected.get('single_support'):
                    self.assertTrue(any(b.sample_quality.get('bottleneck_support')==1 for b in wr.evidence))


if __name__=='__main__':unittest.main()
