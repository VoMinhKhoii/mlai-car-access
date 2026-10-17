import unittest
from unittest.mock import patch
from datetime import datetime
from app import plan, flood
from .test_engine_routes import graph, candidate, xy


class WalkPathTests(unittest.TestCase):
    def test_same_edge_is_ten_meters_in_every_field(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        c=candidate(g,20,80)
        walk=plan._WalkSearch(g,*xy(90,0),150).path(c)
        self.assertAlmostEqual(walk['meters'],10,delta=.2)
        self.assertAlmostEqual(plan._geometry_length(walk['geometry']),walk['meters'],places=6)
        self.assertEqual(walk['edges'],[0])

    def test_cap_checks_chosen_geometry_before_rounding(self):
        g=graph({1:(0,0),2:(200,0)},[(20,[1,2],{})])
        c=candidate(g,20,0)
        self.assertIsNone(plan._WalkSearch(g,*xy(150.5,0),150).path(c))

    def test_partial_edge_is_included_in_wading(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        c=candidate(g,20,80); c.data['walk_path']=plan._WalkSearch(g,*xy(90,0),150).path(c)
        with patch.object(plan,'depth_at',return_value=flood.DepthRange(.1,.2,['test'],True,False)):
            self.assertEqual(plan._walk_wade(g,{},c,{},datetime.now(),[])['label'],'Lội nước')

    def test_forbidden_and_private_partial_edges_are_unavailable(self):
        for tags in ({'foot':'no'},{'access':'private'}):
            g=graph({1:(0,0),2:(100,0)},[(20,[1,2],tags)])
            self.assertIsNone(plan._WalkSearch(g,*xy(90,0),150).path(candidate(g,20,80)))

    def test_two_partial_edges_cannot_cross_a_private_gate(self):
        g=graph({1:(0,0),2:(100,0),3:(200,0)},[(20,[1,2],{}),(30,[2,3],{})],
                {2:{'barrier':'gate','access':'private'}})
        self.assertIsNone(plan._WalkSearch(g,*xy(150,0),150).path(candidate(g,20,80)))

    def test_no_walk_edges_is_coverage_uncertainty(self):
        from app import evidence
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{'highway':'motorway'})])
        with patch.object(plan,'area',return_value=(g,{20:evidence.WidthRange(8,8.3,'Measured')},{})), \
             patch.object(plan.parking_data,'lots_near',return_value=[]):
            r=plan.plan(*xy(50,0),'toyota-vios','pickup',datetime.fromisoformat('2026-10-17T12:00+07:00'),15,_nested=True)
        self.assertEqual(r['verdict']['coverage'],'unknown')
        self.assertEqual(r['stop_points'],[])

if __name__=='__main__': unittest.main()
