import unittest
from unittest.mock import patch
from datetime import datetime,timedelta
from app import flood,plan

T=datetime.fromisoformat('2026-10-17T12:00+07:00')

def profile(cause): return flood.FloodProfile([flood.FloodRecord(10.8,106.71,'test',2020,'',cause,60,'high','test')])


class FloodCoverageAndEventsTests(unittest.TestCase):
    def test_missing_forecast_and_missing_history_are_unknown(self):
        with patch.object(flood,'tide_level',return_value=None):
            self.assertEqual(flood.worst_over(profile('tide'),[T],[],.35)[0],'unknown')
        rain=[{'start':T.isoformat(),'end':(T+timedelta(hours=1)).isoformat(),'mm_per_h':100}]
        d=flood.depth_at(None,T,rain)
        self.assertEqual(flood.flood_status(d,.175),'unknown')
        self.assertIsNone(d.to_json()['hi'])
        self.assertFalse(plan._usable('fits','unknown',True))

    def test_moving_water_upper_bound_blocks_every_car(self):
        self.assertEqual(flood.flood_status(flood.DepthRange(.1,.3,['rain'],True,False),.4),'blocked')

    def test_rain_pulse_inside_dwell_and_retention_are_detected(self):
        rain=[{'start':(T+timedelta(minutes=1)).isoformat(),'end':(T+timedelta(minutes=14)).isoformat(),'mm_per_h':60}]
        self.assertEqual(flood.worst_over(profile('rain'),[T,T+timedelta(minutes=15)],rain,.133)[0],'blocked')
        self.assertEqual(flood.worst_over(profile('rain'),[T+timedelta(minutes=15)],rain,.133)[0],'blocked')

    def test_plus_seven_minute_tide_extremum_is_detected(self):
        ex=[(T,1.39),(T+timedelta(minutes=7),1.65),(T+timedelta(minutes=15),1.39)]
        with patch.object(flood,'_extremes',return_value=ex):
            status,d,t=flood.worst_over(profile('tide'),[T,T+timedelta(minutes=15)],[],.133)
        self.assertEqual(status,'blocked')
        self.assertEqual(t,T+timedelta(minutes=7))

    def test_overlap_order_is_irrelevant(self):
        rain=[{'start':T.isoformat(),'end':(T+timedelta(hours=1)).isoformat(),'mm_per_h':r} for r in (10,60)]
        self.assertEqual(flood.rain_rate(T,rain),flood.rain_rate(T,rain[::-1]))
        self.assertEqual(flood.rain_rate(T,rain),60)

    def test_worst_depth_and_time_update_when_status_ties(self):
        with patch.object(flood,'evaluation_times',return_value=[T,T+timedelta(minutes=15)]), \
             patch.object(flood,'depth_at',side_effect=[flood.DepthRange(.01,.02,[],False,False),flood.DepthRange(.1,.12,[],False,False)]):
            status,d,t=flood.worst_over(None,[T,T+timedelta(minutes=15)],[],.175)
        self.assertEqual((status,d.hi,t),('passable',.12,T+timedelta(minutes=15)))

if __name__=='__main__': unittest.main()

class TimingRecheckTests(unittest.TestCase):
    def test_both_timing_alternatives_require_accepted_full_plan(self):
        seen=[]
        def check(t):
            seen.append(t)
            return {'checked_departure':t.isoformat()} if t in (T+timedelta(minutes=90),T+timedelta(minutes=150)) else None
        timing=plan._flood_timing(None,T,T+timedelta(minutes=120),[],recheck=check)
        self.assertEqual(timing['if_leave_before']['checked_departure'],(T+timedelta(minutes=90)).isoformat())
        self.assertEqual(timing['if_stay_until']['checked_departure'],(T+timedelta(minutes=150)).isoformat())
        self.assertIn(T+timedelta(minutes=150),seen)
        self.assertIsNone(plan._flood_timing(None,T,T+timedelta(minutes=120),[],recheck=lambda t:None))
