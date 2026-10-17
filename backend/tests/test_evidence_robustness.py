"""Regressions: malformed flood reports, missing live rain, and order-independent turn-in checks."""
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import flood, plan, vehicles
from app.evidence import WidthRange
from app.flood import FloodProfile, FloodRecord, FloodSnapshot
from app.osm import AreaGraph, Way

VN = timezone(timedelta(hours=7))
T0 = datetime(2026, 10, 11, 8, 0, tzinfo=VN)


class MalformedFloodReportTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("app.flood.flags.enabled", side_effect=lambda name: name != "live_hydro")  # offline
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_malformed_reports_are_skipped_not_fatal(self):
        good = {"street": "Trần Não", "observed_at": (T0 - timedelta(minutes=30)).isoformat(),
                "depth_cm": "40", "source": "text"}
        reports = [
            {"street": "Trần Não", "observed_at": "17/10/2026 08:00", "depth_cm": 20, "source": "text"},
            {"street": "Trần Não", "observed_at": T0.isoformat(), "depth_cm": "20-30", "source": "text"},
            {"street": "Trần Não", "observed_at": None, "depth_cm": 20, "source": "text"},
            good,
        ]
        snap = FloodSnapshot([], reports=reports)
        self.assertEqual(len(snap.reports), 1)
        snap.sample_times(T0 - timedelta(hours=1), T0 + timedelta(hours=1))
        assessment = snap.assess(None, T0, safe_depth=0.2, name="Trần Não")
        self.assertEqual(assessment.status, "blocked")

    def test_torn_jsonl_line_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            live = Path(tmp) / "live.jsonl"
            live.write_text(
                '{"street": "A", "observed_at": "2026-10-11T08:00:00+07:00", "depth_cm": 10}\n'
                '{"street": "B", "observed_at": "2026-10-11T08:0\n', encoding="utf-8")
            with patch.object(flood, "LIVE_FILE", live):
                self.assertEqual([r["street"] for r in flood.live_reports()], ["A"])


class MissingLiveRainTests(unittest.TestCase):
    def setUp(self):
        patcher = patch("app.flood.flags.enabled", return_value=False)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.rain_street = FloodProfile([FloodRecord(10.7, 106.6, "Hẻm Mưa", 2024, "", "rain", 30, "high", "")])

    def test_time_beyond_rain_coverage_is_not_known_passable(self):
        snap = FloodSnapshot([], reports=[], rain_known_until=T0)
        later = snap.assess(self.rain_street, T0 + timedelta(days=3), safe_depth=0.2, name="Hẻm Mưa")
        self.assertEqual(later.knowledge, "missing_rain")
        self.assertEqual(later.status, "risky")
        covered = snap.assess(self.rain_street, T0 - timedelta(hours=1), safe_depth=0.2, name="Hẻm Mưa")
        self.assertEqual(covered.knowledge, "known")

    def test_explicit_scenario_and_streets_without_rain_history_stay_known(self):
        unbounded = FloodSnapshot([], reports=[])
        self.assertEqual(unbounded.assess(self.rain_street, T0 + timedelta(days=3), 0.2, "Hẻm Mưa").knowledge, "known")
        no_coverage = FloodSnapshot([], reports=[], rain_known_until=datetime.min.replace(tzinfo=VN))
        self.assertEqual(no_coverage.assess(None, T0, 0.2, "").knowledge, "missing_history")


class TurnInOrderTests(unittest.TestCase):
    def test_unmeasured_junction_is_unknown_in_either_node_order(self):
        g = AreaGraph(center=(10.8, 106.7), source="t")
        for n, (la, lo) in enumerate([(10.8, 106.7), (10.8005, 106.7), (10.801, 106.7), (10.8015, 106.7)], 1):
            g.nodes[n] = (la, lo)
        alley = Way(100, {"highway": "service", "service": "alley"}, [2, 3])
        unmeasured = Way(200, {"highway": "residential"}, [1, 2])
        measured = Way(300, {"highway": "residential"}, [3, 4])
        for w in (alley, unmeasured, measured):
            g.ways[w.id] = w
            for a, b in zip(w.nodes, w.nodes[1:]):
                g.node_ways.setdefault(a, set()).add(w.id)
                g.node_ways.setdefault(b, set()).add(w.id)
        p = vehicles.get_profile("toyota-vios")
        wrs = {100: WidthRange(p.fits_min + 0.05, p.fits_min + 0.2, "Measured", decisive_clearance=True),
               200: WidthRange(3.0, 40, "Inferred", decisive_clearance=False),
               300: WidthRange(4.0, 4.5, "Measured", decisive_clearance=True)}
        with patch.object(plan, "blocked_ways_today", lambda: {}):
            for nodes in ([2, 3], [3, 2]):
                with self.subTest(nodes=nodes):
                    alley.nodes = nodes
                    fit, _ = plan.compute_fit(g, wrs, p)
                    self.assertEqual(fit[100], "unknown")


if __name__ == "__main__":
    unittest.main()
