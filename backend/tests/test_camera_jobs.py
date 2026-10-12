"""R-09: camera readings run as bounded, coalesced background jobs; failures stay unknown; restarts interrupt."""
from __future__ import annotations

import json
import tempfile
import threading
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from app import cameras

CAMS = {f"c{i}": {"id": f"c{i}", "name": f"Cam {i}", "lat": 10.8, "lon": 106.7, "status": "UP"} for i in range(60)}


class CameraJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.read_calls: list[list[str]] = []
        self.gate = threading.Event()
        self.gate.set()
        self.fail = False
        patches = [
            mock.patch.object(cameras, "JOBS_FILE", Path(self.tmp.name) / "camera_jobs.json"),
            mock.patch.object(cameras, "by_id", lambda: CAMS),
            mock.patch.object(cameras.flags, "enabled", lambda name: True),
            mock.patch.object(cameras, "_read_batch", self.fake_read),
            mock.patch.dict(cameras._reads, clear=True),
            mock.patch.dict(cameras._jobs, clear=True),
            mock.patch.dict(cameras._inflight, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_read(self, todo):
        self.read_calls.append(list(todo))
        self.gate.wait(timeout=10)
        if self.fail:
            raise RuntimeError("upstream down")
        for c in todo:
            cameras._store({"id": c, "name": c, "lat": 10.8, "lon": 106.7, "state": "ok", "traffic": "dong",
                            "at": datetime.now(cameras.VN_TZ).isoformat(timespec="seconds")})

    def wait_done(self, jid):
        for _ in range(200):
            job = cameras.job_view(jid)
            if job["state"] not in ("queued", "running"):
                return job
            time.sleep(0.02)
        self.fail("job did not finish")

    def test_job_is_capped_and_returns_its_readings(self):
        job = cameras.schedule([f"c{i}" for i in range(40)])
        self.assertEqual(len(job["cameras"]), cameras.MAX_JOB_CAMERAS)
        done = self.wait_done(job["id"])
        self.assertEqual(done["state"], "ready")
        self.assertEqual(len(done["readings"]), cameras.MAX_JOB_CAMERAS)
        self.assertEqual(done["unread"], [])

    def test_overlapping_jobs_read_each_camera_once(self):
        self.gate.clear()
        a = cameras.schedule(["c0", "c1", "c2"])
        for _ in range(100):  # let job A register its cameras as in flight
            if self.read_calls:
                break
            time.sleep(0.01)
        b = cameras.schedule(["c1", "c2", "c3"])
        time.sleep(0.1)
        self.gate.set()
        self.assertEqual(self.wait_done(a["id"])["state"], "ready")
        self.assertEqual(self.wait_done(b["id"])["state"], "ready")
        read = [c for call in self.read_calls for c in call]
        self.assertEqual(sorted(read), ["c0", "c1", "c2", "c3"])

    def test_queue_is_bounded(self):
        self.gate.clear()
        jobs = [cameras.schedule([f"c{i * 12 + k}" for k in range(12)]) for i in range(2)]  # both running
        for _ in range(100):
            if len(self.read_calls) == 2:
                break
            time.sleep(0.01)
        jobs += [cameras.schedule([f"c{24 + i * 12 + k}" for k in range(12)]) for i in range(2)]  # 24 waiting
        with self.assertRaises(cameras.Busy):
            cameras.schedule(["c59"])
        self.gate.set()
        for j in jobs:
            self.wait_done(j["id"])

    def test_failed_reading_stays_unknown_not_clear(self):
        self.fail = True
        job = cameras.schedule(["c5"])
        done = self.wait_done(job["id"])
        self.assertEqual(done["state"], "error")
        self.assertEqual(done["unread"], ["c5"])
        self.assertEqual(done["readings"], [])
        self.assertIsNone(cameras.latest("c5"))

    def test_restart_marks_running_jobs_interrupted(self):
        cameras.JOBS_FILE.write_text(json.dumps({"0123456789ab": {
            "id": "0123456789ab", "state": "running", "cameras": ["c1"], "created_at": "2026-10-12T10:00:00+07:00",
            "expires_at": "2099-01-01T00:00:00+07:00", "finished_at": None, "error": None}}))
        with mock.patch.object(cameras, "_restored", False), \
                mock.patch.object(cameras, "READINGS_FILE", Path(self.tmp.name) / "none.jsonl"):
            cameras._restore()
        self.assertEqual(cameras.job_view("0123456789ab")["state"], "interrupted")


if __name__ == "__main__":
    unittest.main()
