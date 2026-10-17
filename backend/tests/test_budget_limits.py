"""R-10: every upstream AI attempt reserves quota first; caps and corrupt counters stop spending (fail closed)."""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import httpx

from app import ai, budget, live, news, osm
from app.deadline import Expired


def gemini_ok():
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]},
                          request=httpx.Request("POST", "https://x"))


class AiQuota(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.usage = Path(self.tmp.name) / "ai_usage.json"
        self.posts: list[str] = []
        patches = [
            mock.patch.object(budget, "AI_USAGE_FILE", self.usage),
            mock.patch.object(ai.agent_budget, "FILE", Path(self.tmp.name) / "gemini.json"),
            mock.patch.object(ai.agent_budget, "STORE", Path(self.tmp.name)),
            mock.patch.object(ai, "provider", lambda: ("gemini", "test-model")),
            mock.patch.object(ai, "gemini_keys", lambda: ["key-one", "key-two"]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def counts(self) -> dict:
        day = json.loads(self.usage.read_text())
        return next(iter(day.values()))

    def test_each_upstream_attempt_is_reserved_including_key_retries(self):
        responses = [httpx.Response(429, request=httpx.Request("POST", "https://x")), gemini_ok()]

        def fake_post(*_a, params=None, **_k):
            self.posts.append(params["key"])
            return responses.pop(0)

        with mock.patch.object(ai.httpx, "post", fake_post):
            self.assertEqual(ai._call("prompt"), {"ok": True})
        self.assertEqual(self.posts, ["key-one", "key-two"])
        today = self.counts()
        self.assertEqual(today["models"], {"gemini/test-model": 2})
        self.assertEqual(sorted(today["keys"].values()), [1, 1])
        self.assertTrue(all("key-one" not in k and "key-two" not in k for k in today["keys"]))  # no raw keys

    def test_retry_stops_at_deadline_and_uses_only_remaining_time(self):
        attempts = []

        def rate_limited(*_a, params=None, timeout=None, **_k):
            attempts.append((params["key"], timeout))
            return httpx.Response(429, request=httpx.Request("POST", "https://x"))

        with mock.patch("app.deadline.time.monotonic", side_effect=[90.0, 91.0, 100.0]), \
                mock.patch.object(ai.httpx, "post", rate_limited):
            with self.assertRaises(Expired):
                ai._call("prompt", deadline=100.0)
        self.assertEqual(attempts, [("key-one", 9.0)])
        self.assertEqual(self.counts()["models"], {"gemini/test-model": 1})

    def test_listing_photo_debits_once_per_attempt(self):
        with mock.patch.object(ai.httpx, "post", lambda *a, **k: gemini_ok()), \
                mock.patch.object(ai.flags, "enabled", lambda name: True):
            ai.read_listing_photo(b"\xff\xd8\xffimage")
        self.assertEqual(self.counts()["models"], {"gemini/test-model": 1})

    def test_cap_stops_before_any_upstream_call(self):
        with mock.patch.object(budget, "AI_DAILY_CAP_PER_MODEL", 1), \
                mock.patch.object(ai.httpx, "post", lambda *a, **k: self.posts.append("x") or gemini_ok()):
            ai._call("prompt")
            with self.assertRaises(budget.OverBudget):
                ai._call("prompt")
        self.assertEqual(self.posts, ["x"])

    def test_corrupt_counter_fails_closed(self):
        self.usage.write_text("{not json")
        with mock.patch.object(ai.httpx, "post", lambda *a, **k: self.posts.append("x") or gemini_ok()):
            with self.assertRaises(budget.OverBudget):
                ai._call("prompt")
        self.assertEqual(self.posts, [])


class RuntimeDeadlinePropagation(unittest.TestCase):
    def test_listing_photo_fetch_and_model_share_the_build_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = {"deadline": time.monotonic() + 5.0,
                   "counts": {"photos_total": 0, "photos_read": 0}}
            rows = [{"match_method": "alley_chain", "images": ["https://example.test/photo.jpg"],
                     "osm_way_id": 42, "osm_name": "Hẻm Test", "url": "https://example.test/listing",
                     "posted_at": "2026-10-13T10:00:00+07:00"}]
            http_timeouts, model_deadlines = [], []

            def image(*_a, timeout=None, **_k):
                http_timeouts.append(timeout)
                return httpx.Response(200, content=b"\xff\xd8\xffimage",
                                      headers={"content-type": "image/jpeg"})

            def model(*_a, deadline=None, **_k):
                model_deadlines.append(deadline)
                return {"shows_alley": False, "gate": "INSUFFICIENT_INFORMATION"}

            with mock.patch.object(live, "DIR", Path(tmp)), \
                    mock.patch.object(live.httpx, "get", image), \
                    mock.patch.object(live.ai, "read_listing_photo", model):
                live._photos("10.800_106.700", rows, job)

        self.assertEqual(model_deadlines, [job["deadline"]])
        self.assertEqual(len(http_timeouts), 1)
        self.assertGreater(http_timeouts[0], 0)
        self.assertLessEqual(http_timeouts[0], 5.0)

    def test_overpass_uses_remaining_build_time_as_http_timeout(self):
        seen = []

        def answer(*_a, timeout=None, **_k):
            seen.append(timeout)
            return httpx.Response(200, json={"elements": [{"type": "node", "id": 1, "lat": 10.8, "lon": 106.7}]},
                                  request=httpx.Request("POST", "https://overpass.test"))

        deadline = time.monotonic() + 4.0
        with mock.patch.object(osm, "OVERPASS_ENDPOINTS", ["https://overpass.test"]), \
                mock.patch.object(osm.httpx, "post", answer):
            data = osm._fetch_overpass(10.8, 106.7, 1000, deadline=deadline)

        self.assertTrue(data["elements"])
        self.assertEqual(len(seen), 1)
        self.assertGreater(seen[0], 0)
        self.assertLessEqual(seen[0], 4.0)

    def test_overpass_does_not_sleep_or_retry_when_deadline_expires(self):
        attempts = []
        sleeps = []

        def unavailable(*_a, **_k):
            attempts.append("call")
            raise httpx.ConnectError("down")

        deadline = time.monotonic() + 2.0
        with mock.patch.object(osm, "OVERPASS_ENDPOINTS", ["https://overpass.test"]), \
                mock.patch.object(osm.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)), \
                mock.patch.object(osm.httpx, "post", unavailable):
            with self.assertRaises(Expired):
                osm._fetch_overpass(10.8, 106.7, 1000, deadline=deadline)

        self.assertEqual(attempts, ["call"])
        self.assertEqual(sleeps, [])

    def test_news_model_receives_the_area_build_deadline(self):
        deadline = time.monotonic() + 5.0
        seen = []
        item = {"street": "Điện Biên Phủ", "title": "TPHCM thi công Điện Biên Phủ",
                "url": "https://example.test/news", "source": "Tuổi Trẻ", "date": "2026-10-13"}

        def model(*_a, deadline=None, **_k):
            seen.append(deadline)
            return {"items": [{"i": 0, "relevant": True, "kind": "works", "summary": "thi công"}]}

        with mock.patch.object(news, "_search", lambda street, deadline=None: [{**item, "street": street}]), \
                mock.patch.object(news.ai, "provider", lambda: ("gemini", "test-model")), \
                mock.patch.object(news.ai, "_call", model):
            result = news.news_for(["Điện Biên Phủ"], deadline)

        self.assertEqual(seen, [deadline])
        self.assertEqual(result[0]["filter"], "gemini")

    def test_news_search_expiry_is_terminal(self):
        with mock.patch.object(news, "_search", side_effect=Expired("done")):
            with self.assertRaises(Expired):
                news.news_for(["Điện Biên Phủ"], deadline=time.monotonic() + 5.0)

    def test_news_model_expiry_is_not_replaced_by_keyword_results(self):
        item = {"street": "Điện Biên Phủ", "title": "TPHCM thi công Điện Biên Phủ",
                "url": "https://example.test/news", "source": "Tuổi Trẻ", "date": "2026-10-13"}
        with mock.patch.object(news, "_search", return_value=[item]), \
                mock.patch.object(news.ai, "provider", return_value=("gemini", "test-model")), \
                mock.patch.object(news.ai, "_call", side_effect=Expired("done")):
            with self.assertRaises(Expired):
                news.news_for(["Điện Biên Phủ"], deadline=time.monotonic() + 5.0)


class GoogleQuota(unittest.TestCase):
    def test_corrupt_google_counter_fails_closed_and_writes_are_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            usage = Path(tmp) / "google_usage.json"
            with mock.patch.object(budget, "USAGE_FILE", usage):
                budget.spend("streetview_metadata")
                json.loads(usage.read_text())
                usage.write_text("{broken")
                with self.assertRaises(budget.OverBudget):
                    budget.spend("streetview_metadata")


if __name__ == "__main__":
    unittest.main()
