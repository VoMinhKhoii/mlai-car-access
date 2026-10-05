"""Live tide and rain (D35) with the portal and Open-Meteo stubbed.

Run:  cd backend && python3 -m unittest tests.test_hydro
"""
import math
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app import flood, hydro
from app.flood import FloodProfile, FloodRecord

VN = hydro.VN_TZ
T0 = datetime(2026, 10, 1, tzinfo=VN)


def sea(hours=24 * 12):
    """A clean semi-diurnal coastal tide, hourly."""
    return [(T0 + timedelta(hours=h), 1.5 * math.sin(2 * math.pi * h / 12.42)) for h in range(hours)]


def phu_an(t, lag=2.5, a=1.1, b=-0.6):
    m = hydro._interp(sea(), t - timedelta(hours=lag))
    return a * m + b


class Tide(unittest.TestCase):
    def setUp(self):
        self.obs = [(T0 + timedelta(hours=h), phu_an(T0 + timedelta(hours=h))) for h in range(6, 24 * 7, 5)]
        for p in (mock.patch.object(hydro, "_marine", sea), mock.patch.object(hydro, "tide_readings", lambda: self.obs),
                  mock.patch.object(hydro, "_cache", {})):
            p.start()
            self.addCleanup(p.stop)

    def test_fit_recovers_lag_scale_offset(self):
        lag, a, b = hydro._fit(self.obs, sea())
        self.assertAlmostEqual(lag, 2.5)
        self.assertAlmostEqual(a, 1.1, places=2)
        self.assertAlmostEqual(b, -0.6, places=2)

    def test_between_readings_is_measured_after_them_is_model(self):
        last = self.obs[-1][0]
        level, kind = hydro.tide_point(last - timedelta(hours=2))
        self.assertEqual(kind, "measured")
        self.assertAlmostEqual(level, phu_an(last - timedelta(hours=2)), places=2)
        self.assertEqual(hydro.tide_point(last + timedelta(hours=3))[1], "model")

    def test_model_is_pinned_to_the_last_reading_then_fades(self):
        last_t, last_v = self.obs[-1]
        self.obs[-1] = (last_t, last_v + 0.3)  # the river ran 30 cm above the model at the last reading
        model_only = phu_an(last_t + timedelta(hours=1))
        level, _ = hydro.tide_point(last_t + timedelta(hours=1))
        self.assertGreater(level - model_only, 0.2)
        far, _ = hydro.tide_point(last_t + timedelta(hours=hydro.TIDE_PIN_FADE_H + 1))
        # back on the model (which the outlier nudges by a few mm when refitted)
        self.assertAlmostEqual(far, phu_an(last_t + timedelta(hours=hydro.TIDE_PIN_FADE_H + 1)), places=1)

    def test_model_hour_near_an_alarm_widens_the_depth(self):
        prof = FloodProfile([FloodRecord(0, 0, "", None, "", "tide", None, "high", "")])
        t = T0 + timedelta(days=3)
        with mock.patch.object(flood.flags, "enabled", lambda name: name != "ai_flood_prior"), \
                mock.patch.object(hydro, "tide_point", lambda _: (1.45, "model")):
            d = flood.depth_at(prof, t, [])
        self.assertEqual((d.lo, d.hi), (0.0, 0.20))  # 1.45 ± 0.15 spans below BĐ1 to above BĐ2
        self.assertIn("mô hình", d.drivers[0])
        with mock.patch.object(flood.flags, "enabled", lambda name: name != "ai_flood_prior"), \
                mock.patch.object(hydro, "tide_point", lambda _: (1.45, "measured")):
            d = flood.depth_at(prof, t, [])
        self.assertEqual((d.lo, d.hi), (0.0, 0.10))


class Rain(unittest.TestCase):
    NOW = datetime(2026, 10, 5, 22, tzinfo=VN)
    GAUGES = [{"id": "a", "source": "Vrain", "name": "A", "network": "VRAIN", "lat": 10.770, "lon": 106.680},
              {"id": "b", "source": "ND", "name": "B", "network": "ND", "lat": 10.780, "lon": 106.690},
              {"id": "far", "source": "ND", "name": "Far", "network": "ND", "lat": 10.900, "lon": 106.900}]
    HOURS = {"a": {20: 30.4, 21: 2.2, 22: 0.0}, "b": {20: 7.0, 21: 13.2, 22: 0.0}, "far": {20: 99.0, 21: 99.0, 22: 99.0}}

    def spells(self, lat=10.775, lon=106.685):
        hours = lambda g: [(self.NOW.replace(hour=h), v) for h, v in self.HOURS[g["id"]].items()]
        forecast = [(self.NOW + timedelta(hours=h), mm) for h, mm in ((-1, 50.0), (1, 0.0), (2, 12.0))]
        with mock.patch.object(hydro, "rain_gauges", lambda: self.GAUGES), \
                mock.patch.object(hydro, "gauge_hours", hours), \
                mock.patch.object(hydro, "_forecast_hours", lambda la, lo: forecast):
            return hydro.rain_spells(lat, lon)

    def test_wetter_of_the_two_nearest_gauges_then_forecast(self):
        sp = self.spells()
        self.assertEqual([(s["end"][11:13], s["mm_per_h"], s["measured"]) for s in sp],
                         [("21", 30.4, True), ("22", 13.2, True), ("01", 12.0, False)])
        self.assertNotIn(99.0, [s["mm_per_h"] for s in sp])  # the far gauge is not used

    def test_an_hour_of_heavy_rain_still_counts_while_the_street_drains(self):
        sp = self.spells()
        self.assertEqual(flood.rain_rate(self.NOW.replace(hour=20, minute=30), sp), 30.4)
        self.assertEqual(flood.rain_rate(self.NOW.replace(hour=21, minute=0), sp), 30.4)  # drained by 21:00 + DRAIN_H
        self.assertEqual(flood.rain_rate(self.NOW.replace(hour=21, minute=30), sp), 13.2)

    def test_no_gauge_nearby_uses_the_forecast_only(self):
        sp = self.spells(10.45, 106.40)
        self.assertTrue(sp and not any(s["measured"] for s in sp))


class Labels(unittest.TestCase):
    def test_portal_time_labels(self):
        now = datetime(2026, 1, 2, tzinfo=VN)
        self.assertEqual(hydro._label_time("19h 5/10", datetime(2026, 10, 5, 22, tzinfo=VN)),
                         datetime(2026, 10, 5, 19, tzinfo=VN))
        self.assertEqual(hydro._label_time("1h\n28/12", now), datetime(2025, 12, 28, 1, tzinfo=VN))


if __name__ == "__main__":
    unittest.main()
