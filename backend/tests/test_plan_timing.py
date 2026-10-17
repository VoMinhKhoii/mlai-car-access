"""Phase 2 unit tests covering R-04 safe departure timing and route flood checks.

Run:  cd backend && python3 -m unittest tests.test_plan_timing -v
"""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.evidence import WidthRange
from app.flood import DepthRange, FloodAssessment, FloodSnapshot, worst_over
from app.legality import legality_over_window
from app.osm import AreaGraph, Edge, Way
from app.plan import (Candidate, PlanContext, _aggregate_flood, _candidate_timing_qualified,
                      _evaluate, _flood_timing, _needs_flood_timing, _timing_static_eligible,
                      dijkstra)
from app.vehicles import get_profile

VN = timezone(timedelta(hours=7))
T0 = datetime(2026, 10, 11, 8, 0, tzinfo=VN)
COMPLETE_COVERAGE = {
    "cut_count": 5, "start_covered": True, "end_covered": True,
    "max_spacing_m": 5.0, "truncated": False, "complete": True, "reason": None,
}


def measured_width(lo, hi):
    return WidthRange(lo, hi, "Measured", width_basis="measured_clear_width",
                      coverage=COMPLETE_COVERAGE, decisive_clearance=True)


def make_tiny_graph():
    """Construct a minimal synthetic AreaGraph for isolated unit testing.

    Ways:
      1: main road (Kind: main, Width: 10m)
      2: alley (Kind: alley, Width: 4m, Drivable/Walkable)
    Nodes:
      1: (10.770, 106.690) - on main road
      2: (10.771, 106.690) - junction
      3: (10.772, 106.690) - door destination
    """
    g = AreaGraph(center=(10.771, 106.690))
    g.nodes = {1: (10.770, 106.690), 2: (10.771, 106.690), 3: (10.772, 106.690)}
    g.node_tags = {}
    g.ways = {
        1: Way(1, {"highway": "primary", "name": "Đường Lớn"}, [1, 2]),
        2: Way(2, {"highway": "residential", "name": "Hẻm Nhỏ"}, [2, 3])
    }
    g.edges = [
        Edge(0, 1, 1, 2, 100.0),
        Edge(1, 1, 2, 1, 100.0),
        Edge(2, 2, 2, 3, 110.0),
        Edge(3, 2, 3, 2, 110.0),
    ]
    g.drive_adj = {
        1: [(0, 2)],
        2: [(1, 1), (2, 3)],
        3: [(3, 2)],
    }
    g.walk_adj = dict(g.drive_adj)
    g.node_ways = {1: {1}, 2: {1, 2}, 3: {2}}
    return g


class PlanTimingAndSafetyTests(unittest.TestCase):
    def setUp(self):
        self.live_hydro = patch("app.flood.flags.enabled", return_value=False)
        self.live_hydro.start()
        self.addCleanup(self.live_hydro.stop)
        self.graph = make_tiny_graph()
        self.vehicle = get_profile("toyota-vios")
        self.wrs = {
            1: measured_width(10.0, 12.0),
            2: measured_width(3.5, 4.0),
        }
        self.fit = {1: "fits", 2: "fits"}
        self.fit_notes = {}
        self.paid = {}

    def _networks(self):
        network = dijkstra(
            self.graph.drive_adj, {1: 0.0, 2: 0.0}, lambda edge: True,
            lambda edge: self.graph.edges[edge].length)
        reachable = {True: network, False: network}
        unreachable = {True: ({}, {}), False: ({}, {})}
        return reachable, unreachable

    def _context(self, *, intent="park", snapshot=None):
        return PlanContext(
            self.graph, self.wrs, {}, self.fit, self.fit_notes, self.paid,
            self.vehicle, intent, [], snapshot or FloodSnapshot([], reports=[]), []
        )

    def test_midnight_parity_rule_triggers_prohibited_over_window(self):
        """P.131c even-day parking ban must invalidate an overnight park spanning midnight."""
        # 11th is odd, 12th is even: P.131c forbids parking on the 12th.
        arrive = datetime(2026, 10, 11, 22, 0, tzinfo=VN)
        depart = datetime(2026, 10, 12, 6, 0, tzinfo=VN)
        w = self.graph.ways[2]
        self.graph.node_tags[3] = {"traffic_sign": "P.131c"}
        status, rules = legality_over_window(
            self.graph, w, self.wrs[2], 10.772, 106.690, 10.0, "park", arrive, depart
        )
        self.assertEqual(status, "Prohibited")
        self.assertTrue(any("sign-P131c" in r.code for r in rules))

    def test_lot_access_names_and_deterministic_no_edge_behavior(self):
        reports = [{
            "street": "Hẻm Nhỏ",
            "observed_at": (T0 - timedelta(minutes=10)).isoformat(),
            "depth_cm": 40.0,
            "source": "camera"
        }]
        snap = FloodSnapshot([], reports=reports)
        ctx = PlanContext(
            self.graph, self.wrs, {}, self.fit, self.fit_notes, self.paid,
            self.vehicle, "park", [], snap, []
        )
        # Lot with connected access ways
        res = _aggregate_flood(ctx, [2], [T0], T0, T0 + timedelta(minutes=15))
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(len(res["legs"]), 1)
        self.assertEqual(res["legs"][0]["name"], "Hẻm Nhỏ")

        # Lot with no access edges should be unverified/missing_history, never empty arbitrary edge
        res_empty = _aggregate_flood(ctx, [], [T0], T0, T0 + timedelta(minutes=15))
        self.assertEqual(res_empty["status"], "risky")
        self.assertEqual(res_empty["knowledge"], "missing_history")

    def test_live_timing_predicate_requires_known_route_stop_and_exit(self):
        reachable, _ = self._networks()
        self.paid = {1: {"fee_note": "fixture"}}
        candidate = Candidate(
            "street", 10.7705, 106.690, "Đường Lớn", 1, edge_idx=0, offset=50.0, walk_m=20)
        lot = Candidate(
            "lot", 10.772, 106.690, "Bãi thử", None, walk_m=20, entrance=2,
            lot={"name": "Bãi thử", "source_label": "Fixture"},
            data={"entrance_d": 0.0, "access_way_ids": [2]},
        )
        fresh_dry = FloodSnapshot([], reports=[{
            "street": "Đường Lớn", "observed_at": (T0 - timedelta(minutes=5)).isoformat(),
            "depth_cm": 0.0, "source": "camera",
        }])
        stale_positive = FloodSnapshot([], reports=[{
            "street": "Đường Lớn", "observed_at": (T0 - timedelta(hours=3)).isoformat(),
            "depth_cm": 40.0, "source": "camera",
        }])
        self.assertTrue(_candidate_timing_qualified(
            candidate, self._context(snapshot=fresh_dry), T0, T0 + timedelta(minutes=15),
            [T0], reachable, reachable, [T0], [T0]))
        self.assertFalse(_candidate_timing_qualified(
            candidate, self._context(snapshot=stale_positive), T0, T0 + timedelta(minutes=15),
            [T0], reachable, reachable, [T0], [T0]))
        # A lot's entrance, turnaround and exit geometry is unproven, so it never qualifies a timing slot.
        self.assertFalse(_candidate_timing_qualified(
            lot, self._context(snapshot=fresh_dry), T0, T0 + timedelta(minutes=15),
            [T0], reachable, reachable, [T0], [T0]))

    def test_timing_gate_requires_no_chosen_stop_and_flood_failure_code(self):
        chosen = [{"ok": True}]
        no_fit = {"ok": False, "failure_codes": ["no_fit"]}
        flooded = {"ok": False, "failure_codes": ["flood_exit"]}
        self.assertFalse(_needs_flood_timing(chosen, [no_fit]))
        self.assertFalse(_needs_flood_timing(chosen, [flooded]))
        self.assertFalse(_needs_flood_timing([], [{"failure_codes": ["dead_end"]}]))
        self.assertTrue(_needs_flood_timing([], [{"failure_codes": ["flood_stay"]}]))

    def test_pickup_timing_reports_arrival_adjustment_without_claiming_a_sweep(self):
        """Pickup cannot be rescheduled by stretching the requested arrival window."""
        def must_not_probe(_arrive, _depart):
            self.fail("pickup timing must not evaluate departure windows")

        timing = _flood_timing(
            "pickup", T0, T0 + timedelta(minutes=120), must_not_probe,
            ["flood_stay"])
        self.assertIsNone(timing["leave_before_at"])
        self.assertIsNone(timing["or_after_at"])
        self.assertEqual(
            timing["reason"], "Try another arrival time for pickup.")
        self.assertEqual(timing["failure_codes"], ["flood_stay"])

    def test_flood_timing_no_qualified_slot_returns_reason_without_clocks(self):
        """When no slot qualifies across the 12h horizon, clocks are None and reason is populated."""
        qualifies = lambda arr, dep: False
        timing = _flood_timing("park", T0, T0 + timedelta(hours=2), qualifies, ["flood_stay"])
        self.assertIsNone(timing["leave_before_at"])
        self.assertIsNone(timing["or_after_at"])
        self.assertIsNotNone(timing["reason"])

    def test_park_timing_never_publishes_arrival_as_departure_clock(self):
        timing = _flood_timing(
            "park", T0, T0 + timedelta(minutes=15),
            lambda _arrive, _depart: True, ["flood_exit"])
        self.assertIsNone(timing["leave_before_at"])

    def test_interval_flood_blocks_when_departure_instant_is_dry(self):
        depart = T0
        reports = [
            {"street": "Hẻm Nhỏ", "observed_at": (depart - timedelta(minutes=5)).isoformat(),
             "depth_cm": 0.0, "source": "camera"},
            {"street": "Hẻm Nhỏ", "observed_at": (depart + timedelta(minutes=5)).isoformat(),
             "depth_cm": 40.0, "source": "camera"},
        ]
        snapshot = FloodSnapshot([], reports=reports)
        instant = snapshot.assess(None, depart, self.vehicle.safe_water_depth, "Hẻm Nhỏ")
        interval = worst_over(
            None, [depart, depart + timedelta(minutes=5)], [],
            self.vehicle.safe_water_depth, "Hẻm Nhỏ", snapshot)
        self.assertEqual(instant.status, "passable")
        self.assertEqual(interval.status, "blocked")
        self.assertEqual(interval.at, depart + timedelta(minutes=5))

    def test_lot_candidate_evaluation_uses_connected_access_way(self):
        reachable, _ = self._networks()
        reports = [{
            "street": "Hẻm Nhỏ",
            "observed_at": (T0 - timedelta(minutes=5)).isoformat(),
            "depth_cm": 40.0,
            "source": "camera",
        }]
        ctx = self._context(snapshot=FloodSnapshot([], reports=reports))
        candidate = Candidate(
            "lot", 10.772, 106.690, "Bãi thử", None, walk_m=20, entrance=2,
            lot={"name": "Bãi thử", "source_label": "Fixture"},
            data={"entrance_d": 0.0, "access_way_ids": [2]},
        )
        result = _evaluate(
            candidate, ctx, T0, T0 + timedelta(minutes=15), [T0],
            reachable, reachable, reachable, reachable, [T0], [T0])
        self.assertEqual(result["flood"]["stay"]["status"], "blocked")
        self.assertEqual(result["flood"]["stay"]["legs"][0]["way_id"], 2)
        self.assertEqual(result["flood"]["stay"]["legs"][0]["name"], "Hẻm Nhỏ")
        self.assertIn("flood_stay", result["failure_codes"])
        self.assertFalse(result["flood"]["stay"]["interval"]["approximate"])

    def test_tight_stop_remains_eligible_for_timing_sweep(self):
        candidate = Candidate("street", 10.771, 106.690, "Hẻm Nhỏ", 2)
        route = {"strict": True}
        way_out = {"strict": True, "mode": "through"}
        self.assertTrue(_timing_static_eligible(
            candidate, {2: "tight"}, self.wrs, self.vehicle, route, way_out))

    def test_timing_reports_leave_before_and_or_after_directions(self):
        requested_depart = T0 + timedelta(hours=2)
        before = _flood_timing(
            "park", T0, requested_depart,
            lambda _arr, dep: dep <= T0 + timedelta(hours=1), ["flood_exit"])
        self.assertEqual(before["leave_before_at"], (T0 + timedelta(hours=1)).isoformat())
        self.assertIsNone(before["or_after_at"])

        after = _flood_timing(
            "park", T0, requested_depart,
            lambda _arr, dep: dep >= requested_depart + timedelta(minutes=30), ["flood_exit"])
        self.assertIsNone(after["leave_before_at"])
        self.assertEqual(
            after["or_after_at"], (requested_depart + timedelta(minutes=30)).isoformat())

    def test_evaluate_contract_classifies_exit_flood_and_populates_leg_floods(self):
        self.wrs[2] = measured_width(6.0, 7.0)
        reachable, unreachable = self._networks()
        candidate = Candidate(
            "street", 10.7715, 106.690, "Hẻm Nhỏ", 2, edge_idx=2, offset=55.0,
            walk_m=20)
        arrive, depart = T0 - timedelta(minutes=30), T0

        def assessment(_profile, times, _rain, _safe, _name, _snapshot):
            at = max(times)
            if at > depart:
                return FloodAssessment(
                    "blocked", DepthRange(0.4, 0.45, ["fixture"], False, False),
                    "known", None, {"source": "fixture"}, at, "fixture")
            return FloodAssessment("passable", None, "known", None, None, at, "fixture")

        with patch("app.plan.worst_over", side_effect=assessment):
            result = _evaluate(
                candidate, self._context(), arrive, depart, [arrive, depart],
                reachable, unreachable, reachable, reachable,
                [arrive - timedelta(minutes=15), arrive],
                [depart, depart + timedelta(minutes=15)])
        self.assertEqual(result["failure_codes"], ["flood_exit"])
        self.assertEqual(result["route_in"]["flood"]["status"], "passable")
        self.assertEqual(result["way_out"]["flood"]["status"], "blocked")
        self.assertFalse(result["way_out"]["available"])

    def test_evaluate_reuses_legality_for_same_candidate_and_calendar_window(self):
        self.wrs[2] = measured_width(6.0, 7.0)
        reachable, _ = self._networks()
        candidate = Candidate(
            "street", 10.7715, 106.690, "Hẻm Nhỏ", 2, edge_idx=2, offset=55.0,
            walk_m=20)
        context = self._context()
        known = FloodAssessment("passable", None, "known", None, None, T0, "fixture")
        with (patch("app.plan.worst_over", return_value=known),
              patch("app.plan.legality_over_window", wraps=legality_over_window) as legality):
            for offset in (0, 15):
                arrive = T0 + timedelta(minutes=offset)
                depart = arrive + timedelta(minutes=15)
                _evaluate(
                    candidate, context, arrive, depart, [arrive, depart],
                    reachable, reachable, reachable, reachable, [arrive], [depart])
        self.assertEqual(legality.call_count, 1)

    def test_evaluate_arrival_block_and_no_fit_do_not_fabricate_exit_flood(self):
        self.wrs[2] = measured_width(6.0, 7.0)
        reachable, unreachable = self._networks()
        candidate = Candidate(
            "street", 10.7715, 106.690, "Hẻm Nhỏ", 2, edge_idx=2, offset=55.0,
            walk_m=20)
        known = FloodAssessment("passable", None, "known", None, None, T0, "fixture")
        with patch("app.plan.worst_over", return_value=known):
            flooded_arrival = _evaluate(
                candidate, self._context(), T0, T0 + timedelta(minutes=15), [T0],
                unreachable, reachable, reachable, reachable, [T0], [T0])
            no_fit = _evaluate(
                candidate, self._context(), T0, T0 + timedelta(minutes=15), [T0],
                unreachable, reachable, unreachable, reachable, [T0], [T0])
        self.assertIn("flood_arrival", flooded_arrival["failure_codes"])
        self.assertNotIn("flood_exit", flooded_arrival["failure_codes"])
        self.assertIsNone(flooded_arrival["way_out"]["flood"])
        self.assertIn("no_fit", no_fit["failure_codes"])
        self.assertNotIn("dead_end", no_fit["failure_codes"])
        self.assertNotIn("flood_exit", no_fit["failure_codes"])
        self.assertIsNone(no_fit["route_in"]["flood"])



if __name__ == "__main__":
    unittest.main()
