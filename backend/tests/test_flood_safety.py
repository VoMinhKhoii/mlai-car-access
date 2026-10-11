"""Phase 2 unit tests covering R-03 flood knowledge and assessment invariants.

Run:  cd backend && python3 -m unittest tests.test_flood_safety -v
"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.flood import (FloodProfile, FloodRecord, FloodSnapshot,
                       _file_generation, depth_at, worst_over)

VN = timezone(timedelta(hours=7))
T0 = datetime(2026, 10, 11, 8, 0, tzinfo=VN)


class FloodSafetyKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.live_hydro = patch("app.flood.flags.enabled", return_value=False)
        self.live_hydro.start()
        self.addCleanup(self.live_hydro.stop)

    def test_missing_history_is_conservative_risky_without_invented_depth(self):
        assessment = depth_at(None, T0, [], name="Đường Không Lịch Sử", safe_depth=0.25)
        self.assertEqual(assessment.status, "risky")
        self.assertEqual(assessment.knowledge, "missing_history")
        self.assertIsNone(assessment.depth)
        self.assertIsNotNone(assessment.reason)

    def test_missing_tide_at_requested_time_is_conservative_risky(self):
        prof = FloodProfile([FloodRecord(10.7, 106.6, "Nguyễn Hữu Cảnh", 2024, "", "tide", 35, "high", "")])
        out_of_bounds = datetime(2035, 1, 1, 0, 0, tzinfo=VN)
        assessment = depth_at(prof, out_of_bounds, [], name="Nguyễn Hữu Cảnh", safe_depth=0.20)
        self.assertEqual(assessment.status, "risky")
        self.assertEqual(assessment.knowledge, "missing_tide")
        self.assertIsNone(assessment.depth)
        self.assertIn("triều", assessment.reason or "")

    def test_stale_positive_observation_does_not_expire_to_passable(self):
        observed = T0 - timedelta(hours=2, minutes=15)
        reports = [{
            "street": "Trần Não",
            "observed_at": observed.isoformat(),
            "depth_cm": 40.0,
            "source": "photo"
        }]
        snap = FloodSnapshot([], reports=reports)
        assessment = snap.assess(None, T0, safe_depth=0.20, name="Trần Não")
        self.assertEqual(assessment.status, "risky")
        self.assertEqual(assessment.knowledge, "stale_positive_observation")
        self.assertIsNone(assessment.depth)
        self.assertIsNotNone(assessment.reason)

    def test_expired_dry_does_not_clear_older_stale_positive(self):
        positive = T0 - timedelta(hours=10)
        expired_dry = T0 - timedelta(hours=9)
        reports = [
            {"street": "Trần Não", "observed_at": positive.isoformat(),
             "depth_cm": 40.0, "source": "photo"},
            {"street": "Trần Não", "observed_at": expired_dry.isoformat(),
             "depth_cm": 0.0, "source": "camera"},
        ]
        profile = FloodProfile([
            FloodRecord(10.7, 106.6, "Trần Não", 2024, "", "tide", 20, "high", "")
        ])
        snapshot = FloodSnapshot([], reports=reports)
        with patch.object(snapshot, "tide_at", return_value=(0.5, "bulletin")):
            assessment = snapshot.assess(profile, T0, safe_depth=0.20, name="Trần Não")
        self.assertEqual(assessment.status, "risky")
        self.assertEqual(assessment.knowledge, "stale_positive_observation")
        self.assertEqual(assessment.source, "photo")
        self.assertEqual(assessment.freshness["observed_at"], positive.isoformat())

    def test_newer_dry_observation_supersedes_stale_positive_without_future_oracle(self):
        stale_flood = T0 - timedelta(hours=3)
        fresh_dry = T0 - timedelta(minutes=30)
        future_dry = T0 + timedelta(minutes=15)
        reports = [
            {"street": "Trần Não", "observed_at": stale_flood.isoformat(), "depth_cm": 40.0, "source": "photo"},
            {"street": "Trần Não", "observed_at": fresh_dry.isoformat(), "depth_cm": 0.0, "source": "camera"},
            {"street": "Trần Não", "observed_at": future_dry.isoformat(), "depth_cm": 0.0, "source": "camera"},
        ]
        snap = FloodSnapshot([], reports=reports)
        assessment = snap.assess(None, T0, safe_depth=0.20, name="Trần Não")
        self.assertEqual(assessment.status, "passable")
        self.assertEqual(assessment.knowledge, "known")
        self.assertIsNone(assessment.reason)
        self.assertIsNotNone(assessment.freshness)
        self.assertEqual(assessment.freshness.get("observed_at"), fresh_dry.isoformat())

    def test_positive_known_bound_remains_blocked_even_with_missing_other_sources(self):
        fresh_flood = T0 - timedelta(minutes=10)
        reports = [{
            "street": "Lương Định Của",
            "observed_at": fresh_flood.isoformat(),
            "depth_cm": 45.0,
            "source": "camera"
        }]
        eval_time = T0 + timedelta(minutes=5)  # evaluate shortly after the observation, still valid
        snap = FloodSnapshot([], reports=reports)
        assessment = snap.assess(None, eval_time, safe_depth=0.20, name="Lương Định Của")
        self.assertEqual(assessment.status, "blocked")
        self.assertIsNotNone(assessment.depth)
        self.assertGreaterEqual(assessment.depth.lo, 0.40)

    def test_worst_over_deepest_tie_and_unknown_propagation(self):
        prof = FloodProfile([FloodRecord(10.7, 106.6, "Bình Quới", 2024, "", "tide", 35, "high", "")])
        # Two assessments that are both risky, but one is deeper than the other
        t1 = T0
        t2 = T0 + timedelta(minutes=15)
        reports = [
            {"street": "Bình Quới", "observed_at": (t1 - timedelta(minutes=5)).isoformat(),
             "depth_cm": 15.0, "source": "camera"},
            {"street": "Bình Quới", "observed_at": (t2 - timedelta(minutes=5)).isoformat(),
             "depth_cm": 22.0, "source": "camera"},
        ]
        snap = FloodSnapshot([], reports=reports)
        assessment = worst_over(prof, [t1, t2], [], safe=0.25, name="Bình Quới", snapshot=snap)
        self.assertEqual(assessment.status, "risky")
        self.assertIsNotNone(assessment.depth)
        self.assertEqual(round(assessment.depth.hi, 2), 0.27)

    def test_mixed_sample_aggregate_suppresses_misattributed_provenance(self):
        observed = T0 - timedelta(minutes=5)
        later = observed + timedelta(hours=2, minutes=15)
        reports = [{
            "street": "Trần Não",
            "observed_at": observed.isoformat(),
            "depth_cm": 40.0,
            "source": "camera",
        }]
        snapshot = FloodSnapshot([], reports=reports)
        assessment = worst_over(
            None, [T0, later], [], safe=0.20, name="Trần Não", snapshot=snapshot)
        self.assertEqual(assessment.status, "blocked")
        self.assertEqual(assessment.knowledge, "stale_positive_observation")
        self.assertIsNone(assessment.at)
        self.assertIsNone(assessment.source)
        self.assertIsNone(assessment.freshness)

    def test_new_snapshot_observes_changed_tide_file_generation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tide_file = Path(tmpdir) / "tide.json"
            metadata = {
                "alarm_levels_m": {"BD1": 1.3, "BD2": 1.5, "BD3": 1.6},
                "highs": [{"t": T0.isoformat(), "level_m": 1.5}],
                "low_level_m": 1.0,
            }
            tide_file.write_text(json.dumps(metadata), encoding="utf-8")
            with patch("app.flood.TIDE_FILE", tide_file):
                first = FloodSnapshot([], reports=[])
                metadata["alarm_levels_m"]["BD1"] = 1.31
                tide_file.write_text(json.dumps(metadata), encoding="utf-8")
                second = FloodSnapshot([], reports=[])
            self.assertNotEqual(first.generations[1], second.generations[1])
            self.assertEqual(first.tide_metadata["alarm_levels_m"]["BD1"], 1.3)
            self.assertEqual(second.tide_metadata["alarm_levels_m"]["BD1"], 1.31)

    def test_distinct_profiles_at_same_time_use_their_own_flood_history(self):
        """A shared time/street query must not reuse another profile's depth prior."""
        profile1 = FloodProfile([
            FloodRecord(10.7, 106.6, "Hẻm Test", 2024, "", "tide", 20, "high", "source1")
        ])
        profile2 = FloodProfile([
            FloodRecord(10.7, 106.6, "Hẻm Test", 2024, "", "tide", 100, "high", "source2")
        ])
        snapshot = FloodSnapshot([], reports=[])
        with patch.object(snapshot, "tide_at", return_value=(1.65, "bulletin")), \
                patch("app.flood.flags.enabled", side_effect=lambda name: name == "ai_flood_prior"):
            first = snapshot.assess(profile1, T0, safe_depth=0.20, name="Hẻm Test")
            second = snapshot.assess(profile2, T0, safe_depth=0.20, name="Hẻm Test")

        self.assertIsNotNone(first.depth)
        self.assertIsNotNone(second.depth)
        self.assertEqual(first.depth.hi, 0.30)
        self.assertEqual(second.depth.hi, 1.0)

    def test_file_generation_invalidates_caches_on_content_change(self):
        with tempfile.NamedTemporaryFile("w+", delete=False) as tmp:
            tmp.write("version-1")
            tmp.flush()
            tmp_path = Path(tmp.name)
        try:
            gen1 = _file_generation(tmp_path)
            tmp_path.write_text("version-2", encoding="utf-8")
            gen2 = _file_generation(tmp_path)
            self.assertNotEqual(gen1, gen2)
        finally:
            tmp_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
