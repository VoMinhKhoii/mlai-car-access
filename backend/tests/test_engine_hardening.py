import unittest
from datetime import datetime,timedelta
from unittest.mock import patch
from dataclasses import replace
from app import plan,vehicles,parcels,evidence,legality,osm
from .test_engine_routes import graph,xy,widths,candidate,solver

T=datetime.fromisoformat('2026-10-17T23:00+07:00')

class RemainingAuditRegressions(unittest.TestCase):
    def test_fee_is_not_a_ban_and_unassociated_sign_is_not_attached(self):
        w=osm.Way(20,{'highway':'residential','parking:both:fee':'no'},[1,2])
        self.assertEqual(legality._osm_parking_tags(w,'park'),[])
        g=graph({1:(0,0),2:(100,0),3:(50,20)},[(20,[1,2],{})],{3:{'traffic_sign':'VN:P.130'}})
        self.assertEqual(legality._sign_rules(g,g.ways[20],*xy(50,0),'park',T),[])

    def test_same_road_sign_beyond_40m_and_midnight_stay(self):
        g=graph({1:(0,0),2:(200,0)},[(20,[1,2],{})],{1:{'traffic_sign':'VN:P.130'}})
        self.assertTrue(legality._sign_rules(g,g.ways[20],*xy(60,0),'park',T))
        g=graph({1:(0,0),2:(200,0)},[(20,[1,2],{})],{1:{'traffic_sign':'VN:P.131c'}})
        status,rules=legality.legality_on_street(g,g.ways[20],widths(g,8)[20],*xy(20,0),100,'park',T,until=T+timedelta(hours=2))
        self.assertEqual(status,'Prohibited')
        self.assertTrue(any(r.code=='sign-P131c' for r in rules))

    def test_junction_buffer_uses_road_edge_and_is_split_invariant(self):
        pts={1:(-100,0),2:(0,0),3:(3,0),4:(100,0),5:(0,100)}
        values=[]
        for ways in ([(20,[1,2,3,4],{}),(30,[2,5],{})],[(20,[1,2],{}),(21,[2,3,4],{}),(30,[2,5],{})]):
            g=graph(pts,ways);e=next(e for e in g.edges if e.u==3)
            values.append(legality.junction_distance(g,e,1,widths(g,8)))
        self.assertEqual(values,[0,0])

    def test_gate_and_vehicle_restrictions_and_specific_override(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{'vehicle':'no'})])
        self.assertEqual(plan.compute_fit(g,widths(g,8),vehicles.get_profile('toyota-vios'))[0][20],'no')
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{'motor_vehicle':'no','motorcar':'yes'})])
        self.assertIn((0,2),plan._car_adjacency(g)[1])
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})],{2:{'barrier':'gate','access':'private'}})
        self.assertEqual(plan._car_adjacency(g),{})

    def test_limits_are_independent_of_physical_width_tier(self):
        for tags,expected in (({'maxwidth':'1.8'},'no'),({'maxwidth':'1.8','maxwidth:physical':'8'},'no'),({'maxweight':'1'},'unknown')):
            g=graph({1:(0,0),2:(100,0)},[(20,[1,2],tags)])
            self.assertEqual(plan.compute_fit(g,widths(g,8),vehicles.get_profile('ford-transit'))[0][20],expected)

    def test_implicit_roundabout_is_directed(self):
        g=graph({1:(0,0),2:(100,0)},[(20,[1,2],{'junction':'roundabout'})])
        self.assertEqual(plan._car_adjacency(g),{1:[(0,2)]})

    def test_graph_revision_cache_refreshes_widths(self):
        a=graph({1:(0,0),2:(100,0)},[(10,[1,2],{})]);b=graph({1:(0,0),2:(100,0)},[(20,[1,2],{})])
        with patch.object(plan,'build_graph',side_effect=[a,b]),patch.object(plan,'flood_profiles',return_value={}):
            plan.area(*xy(0,0));_,ws,_=plan.area(*xy(0,0))
        self.assertIn(20,ws);self.assertNotIn(10,ws)

    def test_vehicle_dimensions_invalidate_turn_cache_and_units_match(self):
        p=replace(vehicles.get_profile('toyota-vios'),id='audit-spec-key');changed=replace(p,length=12)
        with patch.object(vehicles,'_members',return_value=[p]),patch.object(vehicles.geometry,'min_width_for_moves',return_value=(7,12)):
            self.assertEqual(vehicles.three_point_envelope('audit')[0],7)
        with patch.object(vehicles,'_members',return_value=[changed]),patch.object(vehicles.geometry,'min_width_for_moves',return_value=(13,20)):
            self.assertEqual(vehicles.three_point_envelope('audit')[0],13)
        self.assertEqual(vehicles._safe_water({'wading_depth_mm':'.2','powertrain':'ICE'},.15)[0],.15)
        self.assertAlmostEqual(p.door_min,p.mirror_width+.9)
        self.assertTrue(vehicles.get_profile('vinfast-vf-8-the-all-new-2026').turning_radius_estimated)

    def test_parcel_budget_counts_failed_attempts_not_successes(self):
        g=graph({1:(0,0),2:(0,400),3:(0,800)},[(20,[1,2],{}),(21,[2,3],{})])
        calls=[]
        def partial(coords,step=None,max_cuts=2,**kw):
            calls.append(max_cuts)
            return {'samples':[3],'cuts':[{'width_m':3,'gap_m':4}]}
        with patch.object(parcels,'path_into',return_value=[(20,[xy(0,0),xy(0,400)]),(21,[xy(0,400),xy(0,800)])]),patch.object(parcels,'measure',side_effect=partial):
            parcels.measure_area(g,*xy(0,800),{},osm.haversine)
        self.assertLessEqual(sum(calls),60)

    def test_junction_frontage_cut_is_retained_as_invalid(self):
        g=graph({1:(-20,0),2:(0,0),3:(20,0),4:(0,20)},[(20,[1,2,3],{}),(30,[2,4],{})])
        lat,lon=xy(0,0)
        result={'samples':[6], 'cuts':[{'lat':lat,'lon':lon,'width_m':6,'gap_m':7}]}
        with patch.object(parcels,'path_into',return_value=[(20,[xy(-20,0),xy(20,0)])]), patch.object(parcels,'measure',return_value=result):
            rows=parcels.measure_area(g,*xy(0,0),{},osm.haversine)
        row=next(r for r in rows if r['way_id']==20)
        self.assertEqual(row['samples'],[])
        self.assertEqual(row['cuts'][0]['reason'],'junction_frontage_unvalidated')

    def test_weighted_route_reports_physical_length(self):
        g=graph({1:(0,0),2:(100,0),3:(200,0)},[(10,[1,2],{}),(20,[2,3],{})])
        d,pred=plan.dijkstra(g.drive_adj,{1:0},lambda e:True,lambda ei:g.edges[ei].length*1.3)
        route=plan._route_in(candidate(g,20,10),g,{True:(d,pred),False:(d,pred)})
        self.assertAlmostEqual(route['meters'],110,delta=1)

if __name__=='__main__': unittest.main()
