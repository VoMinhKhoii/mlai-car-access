"""R-06 tests for directed entry, legal egress, and split-independent junction topology."""
import unittest

from app.evidence import WidthRange
from app.osm import AreaGraph, Edge, Way
from app.parcels import path_out
from app.plan import Candidate, _route_in, _way_out
from app.vehicles import get_profile


class DirectedEgressTests(unittest.TestCase):
    def _oneway_graph(self, direction):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {1: (10.0, 106.0), 2: (10.001, 106.0), 3: (10.002, 106.0)}
        graph.ways = {
            1: Way(1, {"highway": "residential", "name": "Hẻm một chiều", "oneway": str(direction)}, [1, 2]),
            2: Way(2, {"highway": "primary", "name": "Đường lớn"}, [2, 3]),
        }
        graph.edges = [Edge(0, 1, 1, 2, 100.0), Edge(1, 2, 2, 3, 100.0)]
        return graph

    def _candidate(self, graph, side):
        return Candidate("street", 10.0005, 106.0, "Hẻm một chiều", 1, edge_idx=0,
                         offset=50.0, walk_m=10.0), {"side": side}

    def test_arrival_respects_both_oneway_directions(self):
        for direction, allowed_node, denied_node in ((1, 1, 2), (-1, 2, 1)):
            with self.subTest(direction=direction):
                graph = self._oneway_graph(direction)
                candidate, _ = self._candidate(graph, "u")
                allowed = {True: ({allowed_node: 0.0}, {}), False: ({allowed_node: 0.0}, {})}
                denied = {True: ({denied_node: 0.0}, {}), False: ({denied_node: 0.0}, {})}
                self.assertIsNotNone(_route_in(candidate, graph, allowed))
                self.assertIsNone(_route_in(candidate, graph, denied))

    def test_exit_uses_only_the_allowed_oneway_direction(self):
        profile = get_profile("toyota-vios")
        for direction, allowed_side, denied_side, target in (
            (1, "u", "v", 2), (-1, "v", "u", 1),
        ):
            with self.subTest(direction=direction):
                graph = self._oneway_graph(direction)
                candidate, _ = self._candidate(graph, allowed_side)
                networks = {True: ({target: 0.0}, {target: (1, 3)}),
                            False: ({target: 0.0}, {target: (1, 3)})}
                wrs = {1: WidthRange(0.5, 2.0, "Inferred")}
                fit = {1: "unknown", 2: "unknown"}
                outbound = _way_out(candidate, graph, wrs, fit, profile, networks,
                                    {"side": allowed_side})
                self.assertEqual(outbound["mode"], "through")
                self.assertTrue(outbound["strict"])

                wrong_candidate, _ = self._candidate(graph, denied_side)
                wrong = _way_out(wrong_candidate, graph, wrs, fit, profile, networks,
                                 {"side": denied_side})
                self.assertEqual(wrong["mode"], "none")

    def _reverse_graph(self, intermediate_oneway=0):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.nodes = {
            1: (10.0, 106.0), 2: (10.001, 106.0), 3: (10.002, 106.0),
            4: (10.003, 106.0), 5: (10.004, 106.0), 6: (10.003, 106.001),
        }
        graph.ways = {
            1: Way(1, {"highway": "residential", "name": "Hẻm cụt"}, [5, 1]),
            2: Way(2, {"highway": "residential", "oneway": str(intermediate_oneway)}, [5, 4]),
            3: Way(3, {"highway": "primary", "name": "Đường lớn"}, [4, 2]),
            4: Way(4, {"highway": "residential"}, [4, 6]),
        }
        graph.edges = [
            Edge(0, 1, 5, 1, 100.0), Edge(1, 2, 5, 4, 10.0),
            Edge(2, 3, 4, 2, 10.0), Edge(3, 4, 4, 6, 10.0),
        ]
        graph.drive_adj = {5: [(0, 1), (1, 4)], 4: [(1, 5), (2, 2), (3, 6)]}
        return graph

    def test_reverse_distance_boundaries_and_intermediate_oneway_guard(self):
        profile = get_profile("toyota-vios")
        wrs = {1: WidthRange(0.5, 2.0, "Inferred")}
        fit = {1: "fits", 2: "fits", 3: "fits", 4: "fits"}
        for offset, expected_mode, expected_reverse in ((20.0, "reverse", 30), (50.0, "reverse", 60),
                                                        (51.0, "none", None)):
            with self.subTest(offset=offset):
                graph = self._reverse_graph()
                candidate = Candidate("street", 10.0, 106.0, "Hẻm cụt", 1, edge_idx=0,
                                      offset=offset, walk_m=5.0)
                ext = {True: ({5: 0.0}, {5: (1, 4)}), False: ({5: 0.0}, {5: (1, 4)})}
                result = _way_out(candidate, graph, wrs, fit, profile, ext, {"side": "u"})
                self.assertEqual(result["mode"], expected_mode)
                if expected_reverse is not None:
                    self.assertEqual(result["reverse_m"], expected_reverse)
                    self.assertFalse(result["strict"])
                    self.assertFalse(result["turn_verified"])

        for direction in (1, -1):
            with self.subTest(intermediate_oneway=direction):
                graph = self._reverse_graph(intermediate_oneway=direction)
                candidate = Candidate("street", 10.0, 106.0, "Hẻm cụt", 1, edge_idx=0,
                                      offset=20.0, walk_m=5.0)
                ext = {True: ({5: 0.0}, {5: (1, 4)}), False: ({5: 0.0}, {5: (1, 4)})}
                result = _way_out(candidate, graph, wrs, fit, profile, ext, {"side": "u"})
                self.assertEqual(result["mode"], "none")

    def test_deep_egress_scan_follows_the_directed_exit_path(self):
        for direction in (1, -1):
            with self.subTest(direction=direction):
                graph = self._oneway_graph(direction)
                if direction == 1:
                    graph.drive_adj = {1: [(0, 2)], 2: [(1, 3)]}
                else:
                    graph.ways[2] = Way(2, {"highway": "primary", "name": "Đường lớn"}, [1, 3])
                    graph.edges[1] = Edge(1, 2, 1, 3, 100.0)
                    graph.drive_adj = {2: [(0, 1)], 1: [(1, 3)], 3: [(1, 1)]}
                paths = path_out(graph, 10.0005, 106.0)
                self.assertTrue(paths)
                self.assertEqual(paths[0][0], 1)

    def test_way_splitting_does_not_create_a_false_junction(self):
        graph = AreaGraph(center=(10.0, 106.0))
        graph.ways = {
            1: Way(1, {"highway": "residential"}, [1, 2]),
            2: Way(2, {"highway": "residential"}, [2, 3]),
            3: Way(3, {"highway": "service"}, [2, 4]),
        }
        graph.node_ways = {2: {1, 2, 3}}
        self.assertEqual(graph.drive_degree(2), 3)
        graph.node_ways[2] = {1, 2}
        self.assertEqual(graph.drive_degree(2), 2)


if __name__ == "__main__":
    unittest.main()
