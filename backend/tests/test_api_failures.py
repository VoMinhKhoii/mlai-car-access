"""Regressions: provider failures and naive timestamps answer with a clear status, never a bare 500."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import httpx
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app import main
from app.deadline import Expired

VN = timezone(timedelta(hours=7))


class AiGuardTests(unittest.TestCase):
    def status(self, exc: Exception) -> int:
        def fail(*_):
            raise exc
        with self.assertRaises(HTTPException) as caught:
            main._ai_guard(fail)
        return caught.exception.status_code

    def test_provider_failures_are_502_not_500(self):
        request = httpx.Request("POST", "https://generativelanguage.googleapis.com/")
        rate_limited = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
        for exc in (rate_limited, httpx.ConnectError("down"), KeyError("parts"), IndexError(0),
                    ValueError("not JSON")):
            with self.subTest(exc=type(exc).__name__):
                self.assertEqual(self.status(exc), 502)

    def test_deadline_is_504(self):
        self.assertEqual(self.status(Expired("late")), 504)


class TideNaiveStartTests(unittest.TestCase):
    def test_naive_start_is_read_as_hcmc_time(self):
        pin = datetime(2026, 10, 17, 0, 0, tzinfo=VN)
        model = (lambda t: 1.0, [(pin, 0.0), (pin + timedelta(hours=72), 0.0)], [], None)
        with (patch("app.flags.enabled", side_effect=lambda name: name == "live_hydro"),
              patch("app.hydro._tide_model", return_value=model),
              patch("app.hydro.tide_status", return_value=None)):
            client = TestClient(main.app)
            naive = client.get("/api/tide", params={"start": "2026-10-17T00:00:00", "hours": 2})
            aware = client.get("/api/tide", params={"start": "2026-10-17T00:00:00+07:00", "hours": 2})
        self.assertEqual(naive.status_code, 200, naive.text)
        self.assertEqual(naive.json()["series"], aware.json()["series"])


if __name__ == "__main__":
    unittest.main()
