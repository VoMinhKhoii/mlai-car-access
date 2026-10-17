"""Estimate policy properties. All fixtures are offline; hard-check tests stay separate."""
import copy
import random
import unittest
from dataclasses import replace
from app import evidence, plan, vehicles, agent
from test_engine_routes import graph, candidate


class EstimateTests(unittest.TestCase):
    def setUp(self):
        self.g = graph({1:(0,0),2:(100,0),3:(200,0)}, [(10,[1,2],{}),(20,[2,3],{})])
        self.c = candidate(self.g,20,30)
        self.c.data['walk_path'] = {'unverified':False}
        self.p = vehicles.get_profile('toyota-fortuner')
        self.checks = {'route_in':{'strict':True,'_segments':[(0,100),(1,30)]},
            'way_out':{'mode':'through','strict':True,'manoeuvre_status':'verified_model','_segments':[(1,70)]},
            'legality':{'status':'Permitted','rules':[]}, 'flood':{'stay':{'status':'passable'}}}

    def widths(self, lo=5, hi=5.2, tier='Measured', complete=True):
        return {wid:evidence.WidthRange(lo,hi,tier,[evidence.Bound(lo,hi,tier,'fixture','',coverage_complete=complete)])
                for wid in self.g.ways}

    def estimate(self, ws=None, p=None, checks=None, failures=None):
        return plan._estimate(self.c,self.g,ws or self.widths(),p or self.p,checks or self.checks,failures or [])

    def test_complete_strong_known_plan_is_high_and_sample_coverage_is_explicit(self):
        r=self.estimate()
        self.assertEqual((r['answer'],r['confidence']),('fits','high'))
        self.assertEqual(r['coverage']['sample_supported_fraction'],1)
        self.assertEqual(r['coverage']['total_segments'],2)
        self.assertIn('2/2 đoạn',r['basis'])

    def test_partial_survey_is_an_estimate_never_a_verified_width_floor(self):
        ws=self.widths(0,7.3,'Official',False)
        for w in ws.values():w.evidence[0].estimate_m=7
        r=self.estimate(ws)
        self.assertEqual((r['answer'],r['confidence']),('fits','medium'))
        self.assertEqual(plan.fit_class(ws[20],self.p),'unknown')
        self.assertEqual(r['coverage']['complete_strong_fraction'],0)

    def test_narrower_never_loses_confidence_when_wider_fits_on_same_path(self):
        rng=random.Random(4517); order={'low':0,'medium':1,'high':2}
        for _ in range(250):
            lo=rng.uniform(0,7);hi=lo+rng.uniform(.1,4)
            ws=self.widths(lo,hi,rng.choice(['Measured','Official','Observed','Declared','Inferred']))
            narrow=replace(self.p,mirror_width=self.p.mirror_width-rng.uniform(0,.5))
            wide=self.estimate(ws);small=self.estimate(ws,narrow)
            if wide['answer']=='fits':
                self.assertEqual(small['answer'],'fits')
                self.assertGreaterEqual(order[small['confidence']],order[wide['confidence']])

    def test_more_same_valued_evidence_never_lowers_confidence(self):
        order={'low':0,'medium':1,'high':2}
        for lo in (2,3,4,6):
            ws=self.widths(lo,lo+.2,'Inferred')
            before=self.estimate(ws)
            for tier in ('Observed','Official','Measured'):
                for w in ws.values():
                    w.evidence.append(evidence.Bound(lo,lo+.2,tier,'additional survey',''))
                    w.top_tier=tier
                after=self.estimate(ws)
                self.assertEqual(after['answer'],before['answer'])
                self.assertGreaterEqual(order[after['confidence']],order[before['confidence']])
                before=after

    def test_coverage_uses_traversed_edge_lengths_and_path_bottleneck(self):
        ws=self.widths();ws[10]=evidence.WidthRange(1,1.2,'Official',[evidence.Bound(1,1.2,'Official','bottleneck','')])
        r=self.estimate(ws)
        self.assertEqual((r['answer'],r['confidence']),('no','high'))
        ws[10]=evidence.WidthRange(5,5.2,'Inferred')
        r=self.estimate(ws)
        self.assertAlmostEqual(r['coverage']['sample_supported_fraction'],70/170,places=3)
        self.assertEqual(r['confidence'],'low')

    def test_unknown_flood_and_legality_cap_confidence_not_answer(self):
        ch=copy.deepcopy(self.checks);ch['flood']['stay']['status']='unknown';ch['legality']['status']='Unverified'
        r=self.estimate(checks=ch)
        self.assertEqual((r['answer'],r['confidence']),('fits','medium'))
        self.assertIn('chưa rõ ngập',r['basis'])
        ch['way_out']['mode']='unknown'
        self.assertEqual(self.estimate(checks=ch)['confidence'],'low')

    def test_conflict_is_unknown_and_weak_listing_cannot_resolve_it(self):
        ws=self.widths();ws[20].review=True
        ws[20].evidence.append(evidence.Bound(8,9,'Declared','listing',''))
        r=self.estimate(ws)
        self.assertEqual((r['answer'],r['confidence']),('unknown','low'))

    def test_hard_flood_and_cited_prohibition_override_wide_estimates(self):
        ch=copy.deepcopy(self.checks);ch['flood']['stay']['status']='blocked'
        self.assertEqual(self.estimate(checks=ch)['answer'],'no')
        ch['flood']['stay']['status']='unknown';ch['legality']={'status':'Restricted','rules':[
            {'status':'Restricted','text':'Cấm dừng','citation':'Luật Điều 18'}]}
        r=self.estimate(checks=ch)
        self.assertEqual((r['answer'],r['confidence']),('no','high'))
        self.assertIn('Luật Điều 18',r['basis'])

    def test_agent_compact_preserves_actual_caveats_and_never_invents_portal_disclaimer(self):
        s={'name':'điểm','kind':'street','way_id':20,'walk':{'meters':39,'minutes':1},
           'fit':{'class':'unknown','width_range':self.widths()[20].to_json()},
           'way_out':{'mode':'unknown','text':'Chưa rõ đường ra','manoeuvre_status':'unknown'},
           'legality':{'status':'Unverified','rules':[]},'flood':{},'verified':False,
           'unverified_reasons':['Chưa rõ đường ra'],'estimate':self.estimate()}
        compact=agent.compact_stop(s)
        self.assertEqual(compact['unverified_reasons'],s['unverified_reasons'])
        self.assertEqual(compact['way_out_status']['mode'],'unknown')
        p={'verdict':{'headline':'Nên đỗ gần cửa — độ tin cậy thấp','estimate':compact['estimate'],
                       'unverified_reasons':s['unverified_reasons']},'stop_points':[compact]}
        answer=agent.grounded_answer(p)
        self.assertIn('Vì sao:',answer);self.assertIn('Chưa rõ đường ra',answer)
        self.assertNotIn('chưa xác minh cổng',answer)

    def test_estimate_does_not_mutate_input_ranges_or_verification(self):
        ws=self.widths();snapshot=copy.deepcopy(ws)
        self.estimate(ws)
        self.assertEqual(ws,snapshot)

if __name__=='__main__':unittest.main()

class SamplePointTests(unittest.TestCase):
    def test_legacy_cadastral_point_is_not_half_the_missing_coverage_interval(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'gaps.csv'
            path.write_text('osm_way_id,width_m\n20,4.8\n')
            store=object.__new__(evidence.EvidenceStore);store.by_way={};store.by_name={}
            with patch.object(evidence,'PARCEL_FILE',path):
                store._load_csv(path,'Official','fixture',None)
            b=store.by_way[20][0]
        self.assertEqual(b.lo,0)
        self.assertFalse(b.coverage_complete)
        wr=evidence.WidthRange(b.lo,b.hi,'Official',[b])
        self.assertAlmostEqual(plan._width_estimate(wr),3.8)
        self.assertEqual(plan.fit_class(wr,vehicles.get_profile('vinfast-vf-3')),'unknown')

    def test_declared_numeric_claim_supports_estimate_without_certifying_clearance(self):
        store=object.__new__(evidence.EvidenceStore);store.by_way={};store.by_name={};store.way_out_by_way={}
        store._add_listing({'osm_way_id':20,'match_method':'alley_chain','width_m':6},'listing')
        b=store.by_way[20][0];wr=evidence.WidthRange(b.lo,b.hi,b.tier,[b])
        self.assertEqual(plan._width_estimate(wr),6)
        self.assertEqual(plan.fit_class(wr,vehicles.get_profile('toyota-vios')),'unknown')

class NegativeConfidenceTests(unittest.TestCase):
    setUp = EstimateTests.setUp
    widths = EstimateTests.widths
    estimate = EstimateTests.estimate
    def test_weak_upper_bound_cannot_borrow_official_confidence(self):
        ws=self.widths()
        ws[20]=evidence.WidthRange(0,1.5,'Official',[
            evidence.Bound(0,7,'Official','partial survey','',coverage_complete=False,estimate_m=6.7),
            evidence.Bound(.5,1.5,'Declared','listing','')])
        result=self.estimate(ws,failures=['Không đủ chỗ mở cửa'])
        self.assertEqual((result['answer'],result['confidence']),('no','low'))

    def test_official_stop_upper_below_door_need_is_a_confident_negative(self):
        hi=(self.p.tight_min+self.p.door_min)/2
        ws=self.widths(hi-.1,hi,'Official')
        result=self.estimate(ws,failures=['Không đủ chỗ mở cửa'])
        self.assertEqual((result['answer'],result['confidence']),('no','high'))

class EstimateDetourTests(unittest.TestCase):
    def test_small_car_uses_plausible_detour_instead_of_doubtful_shortcut(self):
        from datetime import datetime
        from unittest.mock import patch
        g=graph({1:(-100,0),2:(0,0),3:(100,0),4:(0,100),5:(100,100),
                 6:(200,0),7:(200,200),8:(100,200),9:(100,150)},[
            (10,[1,2,3],{'highway':'tertiary'}),(20,[2,4,5],{}),
            (30,[3,6,7,8,5],{}),(50,[5,9],{})])
        ws={wid:evidence.WidthRange(8,8.2,'Measured',[evidence.Bound(8,8.2,'Measured','survey','')]) for wid in g.ways}
        ws[20]=evidence.WidthRange(0,2.2,'Official',[evidence.Bound(0,2.2,'Official','partial','',
                                  coverage_complete=False,estimate_m=1.87)])
        p=vehicles.get_profile('vinfast-vf-3');fits,notes=plan.compute_fit(g,ws,p)
        fl={wid:('passable',None,None) for wid in g.ways}
        search=plan._DriveSearch(g,ws,fits,p,fl,fl)
        c=candidate(g,50,25);c.data['walk_path']={'unverified':False}
        now=datetime.fromisoformat('2026-10-17T12:00:00+07:00')
        with patch.object(plan,'worst_over',return_value=('passable',None,None)), \
             patch.object(plan,'legality_on_street',return_value=('Permitted',[])):
            result=plan._evaluate(c,g,ws,{},fits,notes,{},p,'park',now,now,[now],[],search,search,fl,fl)
        self.assertTrue(result['ok'])
        self.assertEqual(fits[20],'unknown')
        self.assertEqual(result['estimate']['answer'],'fits')
        self.assertTrue(hasattr(search,'estimate_search'))
        self.assertGreater(result['route_in']['meters'],300)
