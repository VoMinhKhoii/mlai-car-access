"""Offline checks for the overnight cache contract. Run: python3 pipelines/test_crawl_city.py."""
import tempfile
import subprocess
import sys
import unittest
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import crawl_city as crawl
from app import live, osm, parcels, portal_gate


class CityCacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "city.json"
        self.patcher = patch.object(live, "CITY_PARCELS", self.path)
        self.patcher.start()
        self.g = SimpleNamespace(ways={42: object()})
        self.res = {"samples": [2.1], "cuts": [{"lat": 10.8, "lon": 106.7, "at_m": 10,
                                              "gap_m": 3.1, "width_m": 2.1}]}

    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_atomic_reload_null_and_graph_filter(self):
        self.assertEqual(live.city_parcels(), {})
        crawl.atomic_json(self.path, {"42": self.res, "43": self.res})
        self.assertEqual(live._merge_city(self.g, []), [{"way_id": 42, **self.res, "deep": False}])
        crawl.atomic_json(self.path, {"42": None})
        self.assertEqual(live._merge_city(self.g, []), [])
        self.assertFalse(self.path.with_suffix(".json.tmp").exists())

    def test_apply_without_area_and_browser_deep_precedence(self):
        crawl.atomic_json(self.path, {"42": self.res})
        with patch.object(live, "cached_area", return_value=None), patch.object(live, "build_graph", return_value=self.g), \
                patch.object(live.STORE_EVIDENCE, "set_live") as store:
            key = live.apply(None, 10.8017, 106.7148)
            self.assertEqual(store.call_args.args[-1], [{"way_id": 42, **self.res, "deep": False}])
            deep = {"way_id": 42, **self.res, "deep": True}
            live.apply({"key": key, "parcels": [deep]}, 10.8017, 106.7148)
            self.assertEqual(store.call_args.args[-1], [deep])

    def test_warm_path_keeps_destination_deep_scan_and_preserves_existing_deep(self):
        branch = SimpleNamespace(id=43, kind="alley", drivable=True, nodes=[1, 2])
        graph = SimpleNamespace(ways={43: branch}, nodes={1: (10.8, 106.7), 2: (10.8001, 106.7)},
                                edges=[SimpleNamespace(way_id=43, u=1, v=2)])
        with patch.object(parcels, "path_into", return_value=[(42, [])]), \
                patch.object(parcels, "measure", return_value=None) as measure:
            self.assertEqual(parcels.measure_area(graph, 10.8, 106.7, {}, osm.haversine, {"42": None}), [])
            self.assertEqual(measure.call_args.kwargs["step"], 5.0)
            out = parcels.measure_area(graph, 10.8, 106.7, {}, osm.haversine, {"42": self.res})
            self.assertFalse(out[0]["deep"])
            measure.reset_mock()
            out = parcels.measure_area(graph, 10.8, 106.7, {"deep:10.80000,106.70000:42": self.res},
                                       osm.haversine, {"42": self.res})
            self.assertTrue(out[0]["deep"])
            measure.assert_not_called()

    def test_full_warm_build_reuses_photos_and_keyword_news(self):
        crawl.atomic_json(self.path, {"42": self.res})
        self.g.source = "cache:test"
        job = {"key": "test", "steps": {}, "counts": {"in_area": 0, "matched": 0, "alleys": 0},
               "state": "running", "parcels": [], "error": None}
        with patch.object(live, "DIR", Path(self.tmp.name)), patch.object(live, "build_graph", return_value=self.g), \
                patch.object(live.parcels, "path_into", return_value=[(42, [])]), \
                patch.object(live.parcels, "measure_area", return_value=[]), \
                patch.object(live.flags, "enabled", return_value=True), \
                patch.object(live.ai, "provider", return_value=("gemini", "test")), \
                patch.object(live, "nearest_districts", return_value=[]), \
                patch.object(live, "_listings", return_value=[]), \
                patch.object(live, "_streets_near", return_value=["Test Street"]), \
                patch.object(live.news, "news_for", return_value=[]) as news, \
                patch.object(live, "_photos", return_value=[]) as photos:
            live._run(job, 10.8, 106.7)
        self.assertEqual(job["state"], "done")
        self.assertIsNone(job["error"])
        news.assert_called_once_with(["Test Street"], use_ai=False)
        self.assertEqual(photos.call_args.args[1], [])

    def test_transport_failure_is_retryable_not_null(self):
        import httpx
        with patch.object(portal_gate, "slot", side_effect=nullcontext), patch.object(portal_gate, "event"), \
                patch.object(parcels.httpx, "post", side_effect=httpx.ConnectError("offline")):
            with self.assertRaises(parcels.Unavailable):
                parcels._parcel(10.8, 106.7)

    def test_portal_plain_text_lock_and_http_limits_are_blocked(self):
        from unittest.mock import Mock
        for status, text in [(200, "{'error' : 'The land is temporarily locked!'}"), (429, "Too many requests")]:
            response = Mock(status_code=status, text=text)
            with patch.object(portal_gate, "slot", side_effect=nullcontext), \
                    patch.object(portal_gate, "backoff"), patch.object(portal_gate, "event"), \
                    patch.object(parcels.httpx, "post", return_value=response) as post:
                with self.assertRaises(parcels.Blocked):
                    parcels._parcel(10.8, 106.7)
                post.assert_called_once()

    def test_cells_cover_all_urban_districts_and_are_density_ordered(self):
        points = crawl.cells()
        self.assertNotEqual(points[0], crawl.HUTECH)
        self.assertEqual(len(points), len({osm.area_key(*p) for p in points}))
        scope = crawl.city_scope.schedule()
        self.assertEqual(len({p["district_id"] for p in scope}), 17)
        self.assertGreater(max(p[0] for p in points), 10.90)
        self.assertLess(min(p[1] for p in points), 106.57)
        self.assertGreater(max(p[1] for p in points), 106.88)

    def test_polite_overpass_tries_next_mirror(self):
        import httpx
        from unittest.mock import Mock
        response = Mock()
        response.json.return_value = {"elements": [{"id": 1}]}
        with patch.object(osm, "OVERPASS_ENDPOINTS", ["https://one.invalid", "https://two.invalid"]), \
                patch.object(osm.httpx, "post", side_effect=[httpx.ConnectError("offline"), response]) as post, \
                patch.object(osm.time, "sleep"):
            self.assertEqual(osm._fetch_overpass(10.8, 106.7, 1200, polite=True), {"elements": [{"id": 1}]})
            self.assertEqual([call.args[0] for call in post.call_args_list],
                             ["https://one.invalid", "https://two.invalid"])

    def test_map_warmup_includes_intervening_osm_keys(self):
        points = crawl.graph_cells()
        keys = {osm.area_key(*p) for p in points}
        self.assertEqual(len(keys), len(points))
        self.assertTrue({osm.area_key(*p) for p in crawl.cells()} <= keys)
        self.assertIn(osm.area_key(10.760, 106.704), keys)
        self.assertLess(len(keys), 4000)

    def test_deadline_exits_even_while_waiting_for_prebuild(self):
        code = """
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, 'pipelines')
import crawl_city as c
c.DIR = Path(sys.argv[1])
c.CITY = c.DIR / 'city.json'
c.STATE = c.DIR / 'state.json'
c.portal_gate.DIRECTORY = c.DIR / 'points'
point_class = c.ParcelPoints
c.ParcelPoints = lambda: point_class(c.DIR / 'points.sqlite3')
c.prebuild_running = lambda: True
sys.argv = ['crawl_city.py', '--stop-at', (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()]
c.main()
"""
        result = subprocess.run([sys.executable, "-c", code, self.tmp.name], cwd=crawl.Path(__file__).resolve().parents[1],
                                capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr.decode())
        self.assertTrue((Path(self.tmp.name) / "state.json").exists())


if __name__ == "__main__":
    unittest.main()
