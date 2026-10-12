"""R-10: every upstream AI attempt reserves quota first; caps and corrupt counters stop spending (fail closed)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

from app import ai, budget


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
