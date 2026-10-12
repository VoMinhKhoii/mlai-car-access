"""R-05/R-06 tests for conservative route, turn, legality, and walking boundaries."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.evidence import WidthRange
from app.flood import FloodSnapshot
from app.osm import AreaGraph, Edge, Way
from app.plan import (Candidate, PlanContext, _candidate_legality, _route_in, _walk_geometry,
                      _way_out, plan)
from app.vehicles import get_profile, three_point_width


VN = timezone(timedelta(hours=7))
NOW = datetime(2026, 10, 12, 10, 0, tzinfo=VN)
COMPLETE = {
    "cut_count": 5, "start_covered": True, "end_covered": True,
    "max_spacing_m": 5.0, "truncated": False, "complete": True, "reason": None,
}


def measured_width(lo, hi):
    return WidthRange(lo, hi, "Measured", width_basis="measured_clear_width",
                      coverage=COMPLETE, decisive_clearance=True)


class PlanBoundaryTests(unittest.TestCase):
    def test_sparse_clearance_cannot_authorize_turn_and_measured_width_stays_unverified(self):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {1: (10.0, 106.0), 2: (10.001, 106.0)}
        graph.ways = {1: Way(1, {"highway": "residential", "name": "Hẻm cụt"}, [1, 2])}
        graph.edges = [Edge(0, 1, 1, 2, 100.0)]
        candidate = Candidate("street", 10.0005, 106.0, "Hẻm cụt", 1, edge_idx=0, offset=20.0)
        vehicle = get_profile("toyota-vios")
        ext = {True: ({1: 0.0}, {}), False: ({1: 0.0}, {})}
        fit = {1: "fits"}

        sparse = _way_out(candidate, graph, {1: WidthRange(8.0, 9.0, "Inferred")},
                           fit, vehicle, ext, {"side": "u"})
        self.assertNotEqual(sparse["mode"], "turn_here")
        self.assertFalse(sparse["strict"])

        measured = _way_out(candidate, graph, {1: measured_width(three_point_width(vehicle.id) + 0.1,
                                                                   three_point_width(vehicle.id) + 0.5)},
                            fit, vehicle, ext, {"side": "u"})
        self.assertEqual(measured["mode"], "turn_here")
        self.assertFalse(measured["strict"])
        self.assertFalse(measured["turn_verified"])
        self.assertIn("chưa có bằng chứng vùng quét quay xe", measured["text"])

    def test_lot_in_and_out_remain_unverified_without_mapped_entrance_geometry(self):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {1: (10.0, 106.0), 2: (10.001, 106.0)}
        graph.ways = {1: Way(1, {"highway": "residential"}, [1, 2])}
        graph.edges = [Edge(0, 1, 1, 2, 100.0)]
        candidate = Candidate("lot", 10.0001, 106.0, "Bãi xe", None, walk_m=20.0,
                              lot={"name": "Bãi xe"}, entrance=1,
                              data={"entrance_d": 10.0, "access_way_ids": [1]})
        network = ({1: 0.0}, {})
        routes = {True: network, False: network}

        route_in = _route_in(candidate, graph, routes)
        route_out = _way_out(candidate, graph, {}, {1: "fits"}, get_profile("toyota-vios"), routes, route_in)
        self.assertFalse(route_in["strict"])
        self.assertEqual(route_out["mode"], "lot")
        self.assertFalse(route_out["strict"])
        self.assertFalse(route_out["turn_verified"])
        self.assertIn("chưa được xác minh", route_out["text"])

    def test_unmapped_walk_endpoint_connectors_are_not_drawn_as_shortcuts(self):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {1: (10.0, 106.0), 2: (10.001, 106.0), 3: (10.002, 106.0)}
        graph.ways = {1: Way(1, {"highway": "footway"}, [1, 2]),
                      2: Way(2, {"highway": "footway"}, [2, 3])}
        graph.edges = [Edge(0, 1, 1, 2, 100.0), Edge(1, 2, 2, 3, 100.0)]
        candidate = Candidate("lot", 11.0, 107.0, "Bãi", None,
                              data={"walk_edge_idx": 0, "walk_offset": 50.0,
                                    "walk_connector_m": 12.0, "walk_destination_connector_m": 20.0})
        geometry = _walk_geometry(
            graph, candidate, {1: (0, 2)}, {1: 20.0, 2: 15.0, 3: 10.0},
            graph.edges[1], 50.0, 12.0, 13.0,
        )
        self.assertNotIn([107.0, 11.0], geometry)
        self.assertNotIn([106.0, 10.0], geometry)
        self.assertAlmostEqual(geometry[0][1], 10.0005, places=6)
        self.assertAlmostEqual(geometry[-1][1], 10.0015, places=6)

    def test_missing_or_far_walk_graph_returns_explicit_no_stop_reason(self):
        profile = get_profile("toyota-vios")
        no_walk = AreaGraph(center=(10.0, 106.0))
        far_walk = AreaGraph(center=(10.0, 106.0))
        far_walk.nodes = {1: (10.0, 106.001), 2: (10.001, 106.001)}
        far_walk.ways = {1: Way(1, {"highway": "footway"}, [1, 2])}
        far_walk.edges = [Edge(0, 1, 1, 2, 100.0)]
        empty_layers = {"fit": {"type": "FeatureCollection", "features": []},
                        "flood": {"type": "FeatureCollection", "features": []}}
        patches = (
            patch("app.plan.area", side_effect=lambda *_args: (no_walk, {}, {})),
            patch("app.plan.flags.enabled", return_value=False),
            patch("app.plan.parking_data.paid_street_ways", return_value={}),
            patch("app.plan.parking_data.lots_near", return_value=[]),
            patch("app.plan._standard_route", return_value=None),
            patch("app.plan._layers", return_value=empty_layers),
            patch("app.plan.GOONG_API_KEY", ""),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
            missing = plan(10.0, 106.0, profile.id, "pickup", NOW, 15)
        self.assertEqual(missing["no_stop_reason"], "missing_walk_connection")
        self.assertEqual(missing["stop_points"], [])

        with (patch("app.plan.area", side_effect=lambda *_args: (far_walk, {}, {})),
              patch("app.plan.flags.enabled", return_value=False),
              patch("app.plan.parking_data.paid_street_ways", return_value={}),
              patch("app.plan.parking_data.lots_near", return_value=[]),
              patch("app.plan._standard_route", return_value=None),
              patch("app.plan._layers", return_value=empty_layers),
              patch("app.plan.GOONG_API_KEY", "")):
            far = plan(10.0, 106.0, profile.id, "pickup", NOW, 15)
        self.assertEqual(far["no_stop_reason"], "missing_walk_connection")
        self.assertEqual(far["stop_points"], [])

    def test_junction_buffer_subtracts_cross_road_half_width_and_unknown_stays_unknown(self):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {
            1: (10.0, 106.0), 2: (10.0001, 106.0),
            3: (10.0001, 106.0001), 4: (10.0001, 105.9999),
        }
        graph.ways = {
            1: Way(1, {"highway": "residential"}, [1, 2]),
            2: Way(2, {"highway": "primary"}, [2, 3]),
            3: Way(3, {"highway": "service"}, [2, 4]),
        }
        graph.edges = [Edge(0, 1, 1, 2, 8.0), Edge(1, 2, 2, 3, 20.0), Edge(2, 3, 2, 4, 20.0)]
        graph.node_ways = {1: {1}, 2: {1, 2, 3}, 3: {2}, 4: {3}}
        profile = get_profile("toyota-vios")
        candidate = Candidate("street", 10.0, 106.0, "Hẻm", 1, edge_idx=0, offset=0.0)
        fit = {1: "fits", 2: "fits", 3: "fits"}

        measured = {1: measured_width(6.0, 6.2), 2: measured_width(8.0, 8.2),
                    3: measured_width(4.0, 4.2)}
        context = PlanContext(graph, measured, {}, fit, {}, {}, profile, "park", [],
                              FloodSnapshot([], reports=[]), [])
        status, rules = _candidate_legality(candidate, context, NOW, NOW + timedelta(minutes=15))
        junction = next(rule for rule in rules if rule.code == "junction-5m")
        self.assertEqual(junction.status, "Prohibited")
        self.assertEqual(status, "Prohibited")

        unknown = dict(measured)
        unknown[2] = WidthRange(6.0, 10.0, "Inferred")
        context = PlanContext(graph, unknown, {}, fit, {}, {}, profile, "park", [],
                              FloodSnapshot([], reports=[]), [])
        status, rules = _candidate_legality(candidate, context, NOW, NOW + timedelta(minutes=15))
        junction = next(rule for rule in rules if rule.code == "junction-5m")
        self.assertEqual(junction.status, "Unverified")
        self.assertEqual(status, "Unverified")


if __name__ == "__main__":
    unittest.main()
