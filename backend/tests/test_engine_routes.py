import unittest
from unittest.mock import patch
from app import plan, osm, evidence, vehicles


def xy(x,y): return 10.8+y/110540,106.71+x/109400


def graph(points,ways,tags=None):
    elements=[{'type':'node','id':n,'lat':xy(x,y)[0],'lon':xy(x,y)[1], 'tags':(tags or {}).get(n,{})} for n,(x,y) in points.items()]
    elements += [{'type':'way','id':wid,'nodes':ns,'tags':{'highway':'residential',**ts}} for wid,ns,ts in ways]
    return osm.graph_from_elements(*xy(0,0),elements,'engine-test')


def widths(g,default=4): return {wid:evidence.WidthRange(default,default+.3,'Measured') for wid in g.ways}


def candidate(g,wid,offset):
    e=next(e for e in g.edges if e.way_id==wid)
    return plan.Candidate('door',*plan._interp(g,e.u,e.v,offset,e.length),'test',wid,e.idx,offset,walk_m=0)


def solver(g,ws,vid='toyota-vios'):
    p=vehicles.get_profile(vid)
    fits,_=plan.compute_fit(g,ws,p)
    fl={wid:('passable',None,None) for wid in g.ways}
    return plan._DriveSearch(g,ws,fits,p,fl,fl)


class DirectedManoeuvreTests(unittest.TestCase):
    def test_shortest_tree_cannot_hide_forward_loop(self):
        g=graph({1:(-50,0),2:(0,0),3:(50,0),4:(0,200),5:(20,200),6:(20,0)},
                [(10,[1,2,3],{'highway':'tertiary'}),(20,[2,4],{}),(30,[4,5,6,2],{})])
        ws=widths(g);ws[10]=evidence.WidthRange(8,8.3,'Measured');ws[20]=evidence.WidthRange(3.4,3.7,'Measured')
        for vid in ('vinfast-vf-3','kia-carnival'):
            self.assertEqual(solver(g,ws,vid).exit(candidate(g,20,100),{'side':'u'})['mode'],'through')

    def test_oneway_never_returns_against_direction(self):
        g=graph({1:(-100,0),2:(0,0),3:(100,0),4:(0,100)},
                [(10,[1,2,3],{'highway':'tertiary'}),(20,[2,4],{'oneway':'yes'})])
        for w in (4,9):
            self.assertEqual(solver(g,widths(g,w)).exit(candidate(g,20,20),{'side':'u'})['mode'],'none')

    def test_physical_junction_is_split_invariant_and_unknown_without_turn_area(self):
        points={1:(-100,0),2:(0,0),3:(100,0),4:(0,100),5:(0,200),6:(100,100)}
        main=(10,[1,2,3],{'highway':'tertiary'})
        answers=[]
        for ways in ([main,(20,[2,4,5],{}),(30,[4,6],{})],
                     [main,(20,[2,4],{}),(21,[4,5],{}),(30,[4,6],{})]):
            g=graph(points,ways);out=solver(g,widths(g)).exit(candidate(g,30,20),{'side':'u'})
            answers.append((out['mode'],out.get('reverse_m'),out['strict']))
        self.assertEqual(answers[0],answers[1])
        self.assertEqual(answers[0],('unknown',20,False))

    def test_carnival_right_angle_not_certified(self):
        g=graph({1:(0,0),2:(0,200),3:(200,200)},[(10,[1,2],{}),(20,[2,3],{})])
        s=solver(g,widths(g),'kia-carnival')
        self.assertEqual(s.turn(0,2,1),'unknown')
        self.assertNotIn((3,1),s.arr[True][0])

    def test_main_road_handoff_cannot_skip_the_junction_turn(self):
        g=graph({1:(-100,0),2:(0,0),3:(100,0),4:(0,100)},
                [(10,[1,2,3],{'highway':'tertiary'}),(20,[2,4],{})])
        s=solver(g,widths(g),'kia-carnival')
        options=list(s.arrival_options(candidate(g,20,50)))
        self.assertTrue(options)
        self.assertFalse(any(r['strict'] for r in options))
        alley=next(e for e in g.edges if e.way_id==20)
        self.assertNotIn((2,alley.idx),s.ext[True][0])

    def test_turn_beyond_right_angle_needs_additional_evidence(self):
        g=graph({1:(0,0),2:(100,0),3:(91.28,99.62)},[(10,[1,2],{}),(20,[2,3],{})])
        self.assertEqual(solver(g,widths(g,10)).turn(0,2,1),'unknown')

    def test_short_widening_cannot_certify_turnaround(self):
        g=graph({1:(0,0),2:(0,8)},[(20,[1,2],{})])
        self.assertFalse(plan._turning_space(candidate(g,20,4),g,widths(g,10),vehicles.get_profile('toyota-vios')))

    def test_both_arrival_orientations_are_available(self):
        g=graph({1:(-100,0),2:(0,0),3:(100,0),4:(0,100),5:(100,100)},
                [(10,[1,2,3],{'highway':'tertiary'}),(20,[2,4,5,3],{})])
        s=solver(g,widths(g,8))
        self.assertEqual({r['side'] for r in s.arrival_options(candidate(g,20,50))},{'u','v'})

if __name__=='__main__': unittest.main()
