"""R-07: area evidence is server-owned, versioned and per-request; builds are single-flight, bounded and deadlined."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from app import live
from app.evidence import EvidenceStore, width_ranges
from app.osm import AreaGraph, Way

WAY = 920001
LISTING = {"osm_way_id": WAY, "match_method": "alley_chain", "access_claim": "xe_hoi", "width_m": 3.0,
           "source": "Tin rao thử", "posted_at": "2026-10-01", "url": "https://example.test/1"}


def graph() -> AreaGraph:
    return AreaGraph(center=(10.7, 106.6), ways={WAY: Way(WAY, {"highway": "residential", "name": "Hẻm thử"}, [1, 2])})


class OverlayIsolation(unittest.TestCase):
    def test_area_overlay_reaches_only_its_own_request(self):
        store = EvidenceStore.evaluation_snapshot(field_file=Path("/nonexistent.csv"))
        before = store.snapshot
        area = {"listings": [LISTING], "photos": [], "parcels": []}
        with mock.patch("app.evidence.flags.enabled", return_value=True):
            with_area = width_ranges(graph(), store.view(area))[WAY]
            without = width_ranges(graph(), store.view())[WAY]
        self.assertTrue(any(b.source == "Tin rao thử" for b in with_area.evidence))
        self.assertFalse(any(b.source == "Tin rao thử" for b in without.evidence))
        self.assertIs(store.snapshot, before)  # building a view never mutates the shared snapshot

    def test_reload_publishes_a_new_snapshot_and_leaves_held_ones_intact(self):
        store = EvidenceStore.evaluation_snapshot(field_file=Path("/nonexistent.csv"))
        held = store.snapshot
        held_ways = dict(held.by_way)
        version = store.version
        store.reload()
        self.assertIsNot(store.snapshot, held)
        self.assertEqual(held.by_way, held_ways)
        self.assertEqual(store.version, version + 1)


class AreaRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(live, "AREAS_DIR", root / "areas"),
            mock.patch.object(live, "PHOTO_REVIEWS", root / "photo_reviews.json"),
            mock.patch.object(live, "_areas", live.LRU(32)),
            mock.patch.object(live, "_plan_cache", live.LRU(32)),
            mock.patch.dict(live._jobs, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.lat, self.lon = 10.70, 106.60  # outside the demo area: a real area key

    def job(self, complete=True):
        return {"key": live.area_key(self.lat, self.lon), "complete": complete, "steps": {}, "counts": {},
                "listings": [LISTING], "photos": [{"id": "0123456789ab", "way_id": WAY, "width_m": 3.2,
                                                   "gate": "ACCEPT", "image_url": "https://example.test/p.jpg"}],
                "news": [], "parcels": []}

    def test_missing_fresh_partial_and_stale(self):
        rec, status = live.area_status(self.lat, self.lon)
        self.assertIsNone(rec)
        self.assertEqual(status["state"], "missing")

        live._publish(self.job())
        rec, status = live.area_status(self.lat, self.lon)
        self.assertEqual(status["state"], "fresh")
        self.assertEqual(status["revision"], 1)
        self.assertEqual(rec["photos"][0]["status"], "pending")  # never approved by the model or the browser

        live._publish(self.job(complete=False))
        _, status = live.area_status(self.lat, self.lon)
        self.assertEqual((status["state"], status["revision"]), ("partial", 2))

        path = live._area_path(status["key"])
        data = json.loads(path.read_text())
        data["expires_at"] = (datetime.now(live.VN_TZ) - timedelta(minutes=1)).isoformat()
        path.write_text(json.dumps(data))
        live._areas.clear()
        rec, status = live.area_status(self.lat, self.lon)
        self.assertIsNone(rec)  # expired evidence is not used
        self.assertEqual(status["state"], "stale")

    def test_operator_photo_review_changes_the_overlay_revision(self):
        live._publish(self.job())
        rec1, _ = live.area_status(self.lat, self.lon)
        live.review_photo("0123456789ab", True, "operator")
        rec2, _ = live.area_status(self.lat, self.lon)
        self.assertEqual(rec2["photos"][0]["status"], "approved")
        self.assertNotEqual(rec1["revision"], rec2["revision"])

    def test_corrupt_area_record_is_treated_as_missing(self):
        path = live._area_path(live.area_key(self.lat, self.lon))
        path.parent.mkdir(parents=True)
        path.write_text("{broken")
        rec, status = live.area_status(self.lat, self.lon)
        self.assertIsNone(rec)
        self.assertEqual(status["state"], "missing")

    def test_invalid_area_key_never_becomes_a_path(self):
        with self.assertRaises(ValueError):
            live._area_path("../../etc/passwd")


class BuildJobs(unittest.TestCase):
    def setUp(self):
        self.gate = threading.Event()
        self.started: list[str] = []
        patches = [mock.patch.dict(live._jobs, clear=True), mock.patch.object(live, "_run", self.fake_run)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self.gate.set)

    def fake_run(self, job, lat, lon):
        job["state"] = "running"
        self.started.append(job["key"])
        self.gate.wait(timeout=10)
        job["state"] = "done"
        job["_finished"] = time.monotonic()

    def test_single_flight_and_bounded_queue(self):
        coords = [(10.70 + 0.01 * i, 106.60) for i in range(7)]
        first = live.schedule(*coords[0])
        again = live.schedule(*coords[0])
        self.assertEqual(first["key"], again["key"])
        self.assertEqual(len([j for j in live._jobs.values()]), 1)  # the second request joined the first
        for c in coords[1:6]:
            live.schedule(*c)  # 2 running + 4 waiting
        with self.assertRaises(live.Busy):
            live.schedule(*coords[6])
        self.gate.set()


def new_job(lat=10.70, lon=106.60):
    return {"key": live.area_key(lat, lon), "state": "queued", "error": None, "revision": None,
            "complete": True, "steps": {s: {"state": "pending", "detail": ""} for s in live.STEPS},
            "counts": {"fetched": 0, "unique": 0, "in_area": 0, "matched": 0, "alleys": 0,
                       "photos_total": 0, "photos_read": 0},
            "listings": [], "photos": [], "news": [], "parcels": []}


class BuildDeadline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        patches = [
            mock.patch.object(live, "AREAS_DIR", root / "areas"),
            mock.patch.object(live, "_areas", live.LRU(32)),
            mock.patch.object(live, "_plan_cache", live.LRU(32)),
            mock.patch.object(live, "DIR", root),
            mock.patch.object(live, "build_graph", lambda lat, lon, deadline=None: graph()),
            mock.patch.object(live, "nearest_districts", lambda lat, lon, deadline=None: []),
            mock.patch.object(live.news, "news_for", lambda streets, deadline=None: []),
            mock.patch.object(live, "_streets_near", lambda g, lat, lon, n=4: []),  # the fake graph has no coordinates
            mock.patch.dict(live._jobs, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_build_past_its_deadline_errors_and_publishes_nothing(self):
        map_deadlines = []

        def map_graph(lat, lon, deadline=None):
            map_deadlines.append(deadline)
            return graph()

        with mock.patch.object(live, "BUILD_DEADLINE_S", 0.0), \
                mock.patch.object(live, "build_graph", map_graph), \
                mock.patch.object(live.flags, "enabled", lambda name: False), \
                mock.patch.object(live.httpx, "get", lambda *a, **k: self.fail("no request after the deadline")):
            job = new_job()
            live._run(job, 10.70, 106.60)
        self.assertEqual(map_deadlines, [job["deadline"]])
        self.assertEqual(job["state"], "error")
        self.assertIn("deadline", job["error"])
        self.assertFalse(live.AREAS_DIR.exists())

    def test_alonhadat_expiry_is_not_swallowed_as_a_source_failure(self):
        district = [{"region": "test", "id": "1", "name": "Test district"}]
        with mock.patch.object(live.flags, "enabled", lambda name: False), \
                mock.patch.object(live, "nearest_districts", return_value=district), \
                mock.patch.object(live, "_pull", return_value=[]), \
                mock.patch.object(live.alonhadat, "pull_district", side_effect=live.Expired("deadline")):
            job = new_job()
            live._run(job, 10.70, 106.60)

        self.assertEqual(job["state"], "error")
        self.assertIn("deadline", job["error"])
        self.assertFalse(live.AREAS_DIR.exists())

    def test_slow_parcel_portal_leaves_a_partial_area_instead_of_losing_the_build(self):
        measured = {"way_id": WAY, "samples": [3.0], "cuts": [{"at_m": 5.0, "gap_m": 4.0, "width_m": 3.0}], "deep": False}

        def slow_portal(*_a, **_k):
            exc = live.parcels.DeadlineExceeded()
            exc.partial = [measured]
            raise exc

        with mock.patch.object(live.flags, "enabled", lambda name: name == "parcel_widths"), \
                mock.patch.object(live.parcels, "measure_area", slow_portal):
            job = new_job()
            live._run(job, 10.70, 106.60)
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["steps"]["parcels"]["state"], "error")
        rec, status = live.area_status(10.70, 106.60)
        self.assertEqual(status["state"], "partial")
        self.assertEqual([p["way_id"] for p in rec["parcels"]], [WAY])  # what was measured is kept, the rest unknown


if __name__ == "__main__":
    unittest.main()
