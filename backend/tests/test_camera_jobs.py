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

import httpx

from app import cameras, corridor

CAMS = {f"c{i}": {"id": f"c{i}", "name": f"Cam {i}", "lat": 10.8, "lon": 106.7, "status": "UP"} for i in range(60)}


class CameraJobs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.read_calls: list[list[str]] = []
        self.deadlines: list[float | None] = []
        self.gate = threading.Event()
        self.gate.set()
        self.fail = False
        patches = [
            mock.patch.object(cameras, "JOBS_FILE", Path(self.tmp.name) / "camera_jobs.json"),
            mock.patch.object(cameras, "by_id", lambda deadline=None: CAMS),
            mock.patch.object(cameras, "_cached_by_id", lambda: CAMS),
            mock.patch.object(cameras.flags, "enabled", lambda name: True),
            mock.patch.object(cameras, "_read_batch", self.fake_read),
            mock.patch.dict(cameras._reads, clear=True),
            mock.patch.dict(cameras._jobs, clear=True),
            mock.patch.dict(cameras._inflight, clear=True),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def fake_read(self, todo, *, deadline=None):
        self.read_calls.append(list(todo))
        self.deadlines.append(deadline)
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

    def wait_workers(self, jobs):
        ids = {j["id"] for j in jobs}
        for _ in range(200):
            with cameras._state:
                if all(not cameras._jobs[jid].get("_worker_pending") for jid in ids if jid in cameras._jobs):
                    return
            time.sleep(0.02)
        self.fail("camera workers did not exit")

    def test_submit_failure_does_not_leave_a_queued_job(self):
        with mock.patch.object(cameras._job_pool, "submit", side_effect=RuntimeError("pool stopped")):
            with self.assertRaises(cameras.Busy):
                cameras.schedule(["c0"])
        self.assertEqual(cameras._jobs, {})

    def test_job_is_capped_and_returns_its_readings(self):
        job = cameras.schedule([f"c{i}" for i in range(40)])
        self.assertEqual(len(job["cameras"]), cameras.MAX_JOB_CAMERAS)
        done = self.wait_done(job["id"])
        self.assertEqual(done["state"], "ready")
        self.assertEqual(len(done["readings"]), cameras.MAX_JOB_CAMERAS)
        self.assertEqual(done["unread"], [])
        self.assertIsNotNone(self.deadlines[0])

    def test_worker_persist_failure_releases_inflight_events_and_job_capacity(self):
        calls = []

        def persist():
            calls.append("persist")
            if len(calls) == 2:
                raise OSError("disk full")

        with mock.patch.object(cameras, "_persist", side_effect=persist):
            job = cameras.schedule(["c0"])
            failed = self.wait_done(job["id"])

        self.assertEqual(calls, ["persist", "persist"])
        self.assertEqual(failed["state"], "error")
        with cameras._state:
            state = cameras._jobs[job["id"]]
            self.assertFalse(state["_worker_pending"])
            self.assertTrue(state["_worker_started"])
        self.assertNotIn("c0", cameras._inflight)

    def test_snapshot_uses_remaining_job_time_as_its_timeout(self):
        seen = []

        def image(*_a, timeout=None, **_k):
            seen.append(timeout)
            return httpx.Response(200, content=b"camera-image", headers={"content-type": "image/jpeg"})

        with mock.patch.dict(cameras._snaps, clear=True), \
                mock.patch("app.deadline.time.monotonic", return_value=10.0), \
                mock.patch.object(cameras.httpx, "get", image):
            self.assertEqual(cameras.snapshot("c0", max_age_s=0, deadline=13.0), b"camera-image")
        self.assertEqual(seen, [3.0])

    def test_camera_model_receives_the_job_deadline(self):
        seen = []

        def model(*_a, deadline=None, **_k):
            seen.append(deadline)
            return {"cameras": []}

        with mock.patch.object(cameras, "CAMERA_MODELS", ["model"]), \
                mock.patch.object(cameras, "_resting", {}), \
                mock.patch.object(cameras.ai, "_call", model):
            cameras._ask(["c0"], {"c0": b"a"}, {"c0": b"b"},
                         datetime.now(cameras.VN_TZ), deadline=123.0)
        self.assertEqual(seen, [123.0])

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

    def test_expired_jobs_remain_counted_until_their_workers_exit(self):
        self.gate.clear()
        jobs = []
        try:
            with mock.patch.object(cameras, "JOB_TTL_S", 0.1):
                jobs = [cameras.schedule([f"c{i * 12 + k}" for k in range(12)]) for i in range(2)]
                for _ in range(100):
                    if len(self.read_calls) == 2:
                        break
                    time.sleep(0.01)
                jobs += [cameras.schedule([f"c{24 + i * 12 + k}" for k in range(12)]) for i in range(2)]
                time.sleep(0.12)
                expired_active = cameras.job_view(jobs[0]["id"])
                expired_queued = cameras.job_view(jobs[2]["id"])
                self.assertEqual(expired_active["state"], "expired")
                self.assertEqual(expired_queued["state"], "expired")
                with cameras._state:
                    self.assertTrue(cameras._jobs[jobs[0]["id"]]["_worker_pending"])
                    self.assertTrue(cameras._jobs[jobs[0]["id"]]["_worker_started"])
                    self.assertTrue(cameras._jobs[jobs[2]["id"]]["_worker_pending"])
                    self.assertFalse(cameras._jobs[jobs[2]["id"]]["_worker_started"])
                with self.assertRaises(cameras.Busy):
                    cameras.schedule(["c59"])
        finally:
            self.gate.set()
            self.wait_workers(jobs)
        with cameras._state:
            self.assertTrue(all(cameras._jobs[j["id"]]["state"] == "expired" for j in jobs))

    def test_failed_reading_stays_unknown_not_clear(self):
        self.fail = True
        job = cameras.schedule(["c5"])
        done = self.wait_done(job["id"])
        self.assertEqual(done["state"], "error")
        self.assertEqual(done["unread"], ["c5"])
        self.assertEqual(done["readings"], [])
        self.assertIsNone(cameras.latest("c5"))

    def test_expired_job_still_exposes_fresh_readings(self):
        cameras._store({"id": "c5", "name": "Cam 5", "lat": 10.8, "lon": 106.7, "state": "ok",
                        "traffic": "dong", "at": datetime.now(cameras.VN_TZ).isoformat(timespec="seconds")})
        now = datetime.now(cameras.VN_TZ)
        cameras._jobs["expired-job"] = {
            "id": "expired-job", "state": "expired", "cameras": ["c5"],
            "created_at": now.isoformat(timespec="seconds"),
            "expires_at": datetime.fromtimestamp(now.timestamp() + 60, cameras.VN_TZ).isoformat(timespec="seconds"),
            "finished_at": now.isoformat(timespec="seconds"), "error": "Hết thời hạn đọc camera",
            "_worker_pending": True,
        }

        view = cameras.job_view("expired-job")

        self.assertEqual([reading["id"] for reading in view["readings"]], ["c5"])
        self.assertEqual(view["unread"], [])

    def test_restart_marks_running_jobs_interrupted(self):
        cameras.JOBS_FILE.write_text(json.dumps({"0123456789ab": {
            "id": "0123456789ab", "state": "running", "cameras": ["c1"], "created_at": "2026-10-12T10:00:00+07:00",
            "expires_at": "2099-01-01T00:00:00+07:00", "finished_at": None, "error": None}}))
        with mock.patch.object(cameras, "_restored", False), \
                mock.patch.object(cameras, "READINGS_FILE", Path(self.tmp.name) / "none.jsonl"):
            cameras._restore()
        self.assertEqual(cameras.job_view("0123456789ab")["state"], "interrupted")

    def test_restore_legacy_successful_readings_without_frame_count_as_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            readings_path = Path(tmp) / "readings.jsonl"
            jobs_path = Path(tmp) / "jobs.json"
            at = datetime.now(cameras.VN_TZ).isoformat(timespec="seconds")
            readings_path.write_text(json.dumps({
                "id": "legacy", "name": "Legacy camera", "lat": 10.8, "lon": 106.7,
                "at": at, "state": "ok", "traffic": "thong_thoang",
            }) + "\n")
            with mock.patch.object(cameras, "_restored", False), \
                    mock.patch.object(cameras, "READINGS_FILE", readings_path), \
                    mock.patch.object(cameras, "JOBS_FILE", jobs_path), \
                    mock.patch.dict(cameras._reads, clear=True), \
                    mock.patch.dict(cameras._jobs, clear=True):
                cameras._restore()
                public = cameras.public(cameras.latest("legacy"))

        self.assertIsNone(public["frames"])
        self.assertEqual(public["traffic"], "khong_ro")
        self.assertEqual(public["traffic_vi"], "Unknown")



class CameraRegistryRefresh(unittest.TestCase):
    def wait_refresh(self):
        for _ in range(200):
            with cameras._reg_lock:
                if not cameras._reg["pending"]:
                    return
            time.sleep(0.01)
        self.fail("registry refresh did not finish")

    def test_stale_request_returns_published_registry_while_refresh_is_blocked(self):
        old = {"source": "cached", "cameras": [CAMS["c0"]]}
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        result = []

        def portal(deadline=None):
            started.set()
            release.wait(timeout=2)
            return [CAMS["c1"]]

        def read_registry():
            result.append(cameras.registry())
            returned.set()

        with mock.patch.dict(cameras._reg, {
                "t": 0.0, "data": old, "by_id": {"c0": CAMS["c0"]}, "pending": False}, clear=True), \
                mock.patch.object(cameras, "fetch_official", side_effect=portal):
            reader = threading.Thread(target=read_registry)
            reader.start()
            try:
                self.assertTrue(returned.wait(timeout=0.5))
                self.assertTrue(started.wait(timeout=0.5))
                self.assertIs(result[0], old)
                self.assertFalse(release.is_set())
            finally:
                release.set()
                reader.join(timeout=1)
                self.wait_refresh()

    def test_request_and_schedule_stay_nonblocking_during_refresh(self):
        old = {"source": "cached", "cameras": [CAMS["c0"]]}
        started, release, returned = threading.Event(), threading.Event(), threading.Event()
        result = {}

        def portal(deadline=None):
            started.set()
            release.wait(timeout=2)
            return [CAMS["c1"]]

        def read_and_schedule():
            result["registry"] = cameras.registry()
            result["job"] = cameras.schedule(["c0", "c1"])
            returned.set()

        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cameras, "JOBS_FILE", Path(tmp) / "camera_jobs.json"), \
                mock.patch.object(cameras.flags, "enabled", return_value=True), \
                mock.patch.dict(cameras._reg, {
                    "t": 0.0, "data": old, "by_id": {"c0": CAMS["c0"]}, "pending": False}, clear=True), \
                mock.patch.dict(cameras._jobs, clear=True), \
                mock.patch.object(cameras._job_pool, "submit") as job_submit, \
                mock.patch.object(cameras, "fetch_official", side_effect=portal):
            cameras.registry()
            self.assertTrue(started.wait(timeout=0.5))
            reader = threading.Thread(target=read_and_schedule)
            reader.start()
            try:
                self.assertTrue(returned.wait(timeout=0.5))
                self.assertIs(result["registry"], old)
                self.assertEqual(result["job"]["cameras"], ["c0"])
                job_submit.assert_called_once()
            finally:
                release.set()
                reader.join(timeout=1)
                self.wait_refresh()

    def test_one_inflight_refresh_publishes_data_and_index_together(self):
        old = {"source": "cached", "cameras": [CAMS["c0"]]}
        started, release = threading.Event(), threading.Event()

        def portal(deadline=None):
            started.set()
            release.wait(timeout=2)
            return [CAMS["c1"]]

        with mock.patch.dict(cameras._reg, {
                "t": 0.0, "data": old, "by_id": {"c0": CAMS["c0"]}, "pending": False}, clear=True), \
                mock.patch.object(cameras, "fetch_official", side_effect=portal), \
                mock.patch.object(cameras._registry_pool, "submit",
                                  wraps=cameras._registry_pool.submit) as submit:
            self.assertIs(cameras.registry(), old)
            self.assertTrue(started.wait(timeout=0.5))
            for _ in range(5):
                self.assertIs(cameras.registry(), old)
                self.assertEqual(cameras.by_id(), {"c0": CAMS["c0"]})
            submit.assert_called_once()
            release.set()
            self.wait_refresh()
            published = cameras.registry(deadline=1.0)
            index = cameras.by_id(deadline=1.0)

        self.assertEqual(published["source"], "HCMC Traffic Portal (camera layer, live)")
        self.assertEqual(published["cameras"], [CAMS["c1"]])
        self.assertEqual(index, {"c1": CAMS["c1"]})

    def test_failed_refresh_keeps_prior_registry_and_retries_only_after_backoff(self):
        old = {"source": "cached", "cameras": [CAMS["c0"]]}
        now = [10000.0]
        calls = []

        def portal(deadline=None):
            calls.append(now[0])
            raise RuntimeError("portal down")

        with mock.patch.dict(cameras._reg, {
                "t": 0.0, "data": old, "by_id": {"c0": CAMS["c0"]}, "pending": False}, clear=True), \
                mock.patch.object(cameras.time, "time", side_effect=lambda: now[0]), \
                mock.patch.object(cameras, "fetch_official", side_effect=portal):
            self.assertIs(cameras.registry(), old)
            self.wait_refresh()
            now[0] = 13599.0
            self.assertIs(cameras.registry(), old)
            self.assertEqual(calls, [10000.0])
            self.assertEqual(cameras.by_id(deadline=1.0), {"c0": CAMS["c0"]})
            now[0] = 13601.0
            self.assertIs(cameras.registry(), old)
            self.wait_refresh()

        self.assertEqual(calls, [10000.0, 13601.0])

    def test_deadline_reader_seeds_shipped_data_without_attempting_refresh(self):
        shipped = {"source": "shipped", "cameras": [CAMS["c0"]]}
        with tempfile.TemporaryDirectory() as tmp:
            registry_file = Path(tmp) / "cameras.json"
            registry_file.write_text(json.dumps(shipped), encoding="utf-8")
            with mock.patch.object(cameras, "REGISTRY", registry_file), \
                    mock.patch.dict(cameras._reg, {
                        "t": 321.0, "data": None, "by_id": {}, "pending": False}, clear=True), \
                    mock.patch.object(cameras._registry_pool, "submit") as submit, \
                    mock.patch.object(cameras, "fetch_official") as fetch:
                data = cameras.registry(deadline=500.0)
                index = cameras.by_id(deadline=500.0)
                attempted_at = cameras._reg["t"]

        self.assertEqual(data, shipped)
        self.assertEqual(index, {"c0": CAMS["c0"]})
        self.assertEqual(attempted_at, 321.0)
        submit.assert_not_called()
        fetch.assert_not_called()


class CameraDeadlineBoundaries(unittest.TestCase):

    def test_read_batch_skips_an_interframe_wait_that_exceeds_remaining_budget(self):
        snapshots = []
        asks = []
        sleeps = []

        def snapshot(cam_id, max_age_s=0, *, deadline=None):
            snapshots.append((cam_id, deadline))
            return b"first-frame"

        def ask(group, first, second, now, *, deadline=None):
            asks.append((list(group), dict(first), dict(second), deadline))

        with mock.patch.object(cameras, "snapshot", side_effect=snapshot), \
                mock.patch.object(cameras, "_ask", side_effect=ask), \
                mock.patch.object(cameras.time, "monotonic", return_value=100.0), \
                mock.patch.object(cameras.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)):
            cameras._read_batch(["c0"], deadline=105.0)

        self.assertEqual(snapshots, [("c0", 105.0)])
        self.assertEqual(sleeps, [])
        self.assertEqual(asks, [(["c0"], {"c0": b"first-frame"}, {}, 105.0)])

    def test_read_batch_does_not_wait_after_every_camera_has_a_distinct_second_frame(self):
        snapshots, sleeps, asks = [], [], []

        def snapshot(cam_id, max_age_s=0, *, deadline=None):
            snapshots.append(cam_id)
            return b"frame-1" if len(snapshots) == 1 else b"frame-2"

        def ask(group, first, second, now, *, deadline=None):
            asks.append((dict(first), dict(second)))

        with mock.patch.object(cameras, "snapshot", side_effect=snapshot), \
                mock.patch.object(cameras, "_ask", side_effect=ask), \
                mock.patch.object(cameras.time, "monotonic", return_value=100.0), \
                mock.patch.object(cameras.time, "sleep", side_effect=lambda duration: sleeps.append(duration)):
            cameras._read_batch(["c0"], deadline=130.0)

        self.assertEqual(snapshots, ["c0", "c0"])
        self.assertEqual(sleeps, [cameras.REFRESH_S])
        self.assertEqual(asks, [({"c0": b"frame-1"}, {"c0": b"frame-2"})])

    def test_read_batch_uses_first_frame_when_second_snapshot_expires(self):
        snapshots = []
        asks = []

        def snapshot(cam_id, max_age_s=0, *, deadline=None):
            snapshots.append((cam_id, deadline))
            if len(snapshots) == 1:
                return b"first-frame"
            raise cameras.Expired("deadline boundary")

        def ask(group, first, second, now, *, deadline=None):
            asks.append((list(group), dict(first), dict(second), deadline))

        with mock.patch.object(cameras, "snapshot", side_effect=snapshot), \
                mock.patch.object(cameras, "_sleep_with_deadline", return_value=True), \
                mock.patch.object(cameras, "_ask", side_effect=ask):
            cameras._read_batch(["c0"])

        self.assertEqual(snapshots, [("c0", None), ("c0", None)])
        self.assertEqual(asks, [(["c0"], {"c0": b"first-frame"}, {}, None)])

    def test_read_batch_preserves_initial_snapshot_expiry(self):
        with mock.patch.object(cameras, "snapshot",
                               side_effect=cameras.Expired("initial snapshot expired")), \
                mock.patch.object(cameras, "_ask") as ask:
            with self.assertRaises(cameras.Expired):
                cameras._read_batch(["c0"], deadline=105.0)
        ask.assert_not_called()

    def test_camera_removed_during_refresh_is_skipped_without_failing_surviving_batch(self):
        available = {"c1": CAMS["c1"]}
        stored, prompts = [], []
        response = {"cameras": [{"camera": 1, "traffic": "dong", "usable": True, "confidence": 0.9}]}

        def model(prompt, parts, *, deadline=None, **_kwargs):
            prompts.append((prompt, parts))
            return response

        with mock.patch.object(cameras, "by_id", lambda deadline=None: available), \
                mock.patch.object(cameras, "CAMERA_MODELS", ["model"]), \
                mock.patch.object(cameras, "_resting", {}), \
                mock.patch.object(cameras.ai, "_call", model), \
                mock.patch.object(cameras.ai, "provider", return_value=("gemini", "test-model")), \
                mock.patch.object(cameras, "_log"), \
                mock.patch.object(cameras, "_store", stored.append):
            cameras._ask(["c0", "c1"], {"c0": b"old", "c1": b"new"}, {},
                         datetime.now(cameras.VN_TZ))

        self.assertEqual(len(prompts), 1)
        self.assertEqual([part for part in prompts[0][1] if isinstance(part, str)], ["Camera 1: Cam 1 (1 frame)"])
        self.assertEqual([reading["id"] for reading in stored], ["c1"])

    def test_one_frame_cannot_contribute_a_corridor_traffic_score(self):
        output = {"image_time": None, "usable": True, "flooded": True, "depth_class": "15_30cm",
                  "traffic": "ket_cung", "evidence": "nước thấy rõ", "confidence": 0.9}
        with mock.patch.object(cameras, "_log"), \
                mock.patch.object(cameras.ai, "provider", return_value=("gemini", "model")):
            reading = cameras._record(CAMS["c0"], output, 1, datetime.now(cameras.VN_TZ), "model")
        cluster_camera = {**CAMS["c0"], "along_m": 0.0}
        observed = corridor._observe([[cluster_camera]], {"c0": reading},
                                     mock.Mock(safe_water_depth=0.4))
        self.assertEqual(reading["traffic"], "khong_ro")
        self.assertNotIn("khong_ro", cameras.TRAFFIC)
        self.assertIsNone(observed[0]["traffic"])
        self.assertTrue(reading["flooded"])
        self.assertEqual(reading["depth_cm"], 25)

        appended = []
        with mock.patch.object(cameras.ai, "_append", side_effect=lambda _path, payload: appended.append(payload)), \
                mock.patch.object(cameras.ai, "_gate", return_value="REVIEW"), \
                mock.patch.object(cameras, "street_names", return_value=["Street X"]):
            cameras._log(CAMS["c0"], reading)
        self.assertEqual(appended[1]["frames"], 1)


if __name__ == "__main__":
    unittest.main()
