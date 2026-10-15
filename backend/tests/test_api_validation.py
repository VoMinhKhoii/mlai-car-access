"""API-boundary regressions with state and network isolated before app import."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DEMO_CACHE = BACKEND / "cache" / "osm" / "demo_binhthanh.json"
RESULT_MARKER = "VAODUOC_API_RESULTS="

SUBPROCESS_CASES = r'''
import json
from pathlib import Path
original_read_text = Path.read_text


def isolated_read_text(path, *args, **kwargs):
    if path.name == ".env.local":
        return ""
    return original_read_text(path, *args, **kwargs)


Path.read_text = isolated_read_text


import httpx


def no_network(*args, **kwargs):
    raise AssertionError("API validation tests must not access the network")


httpx.get = no_network
httpx.post = no_network

from fastapi.testclient import TestClient
from app import ai, budget, cameras, config, evidence, flags, flood, live, osm, plan as route_plan, reports, vehicles, deadline
from app.main import app

Path.read_text = original_read_text


def packed(response):
    return {"status": response.status_code, "json": response.json()}


client = TestClient(app)
preset_response = client.get("/api/config")
preset_response.raise_for_status()
preset = preset_response.json()["presets"][0]
base = {
    "lat": preset["lat"],
    "lon": preset["lon"],
    "label": preset["label"],
    "vehicle_id": "class-s",
    "intent": "park",
    "arrive_at": None,
    "dwell_min": 15,
    "rain": [],
    "origin": None,
}
corridor_base = {
    "origin": [10.80, 106.70],
    "destination": [10.80, 106.72],
    "vehicle_id": "class-s",
    "depart_at": None,
    "rain": [],
}

responses = {}
responses["synthetic_demo_data"] = preset_response.json().get("synthetic_demo_data")
for name, value in {
    "plan_malformed": "not-a-date",
    "plan_naive": "2026-10-11T09:30:00",
    "plan_non_string": 1791691800,
}.items():
    responses[name] = packed(client.post("/api/plan", json={**base, "arrive_at": value}))
for name, value in {
    "corridor_malformed": "not-a-date",
    "corridor_naive": "2026-10-11T09:30:00",
    "corridor_non_string": 1791691800,
}.items():
    responses[name] = packed(client.post("/api/corridor", json={**corridor_base, "depart_at": value}))

responses["plan_null"] = packed(client.post("/api/plan", json=base))
responses["corridor_null"] = packed(client.post("/api/corridor", json=corridor_base))
responses["maneuver"] = packed(client.get("/api/vehicles/toyota-fortuner/maneuver", params={"width": 12}))
responses["maneuver_unknown_vehicle"] = packed(client.get("/api/vehicles/unknown/maneuver", params={"width": 8}))
responses["maneuver_low_width"] = packed(client.get("/api/vehicles/toyota-fortuner/maneuver", params={"width": 1.49}))
responses["maneuver_high_width"] = packed(client.get("/api/vehicles/toyota-fortuner/maneuver", params={"width": 15.01}))
responses["outside_hcmc"] = packed(client.post("/api/plan", json={**base, "lat": 21.0285, "lon": 105.8542}))
original_voice_call = ai._call
voice_deadlines = []
flags.set_flag("ai_voice_report", True)
def successful_voice_call(prompt, **kwargs):
    voice_deadlines.append(kwargs.get("deadline"))
    return {"kind": "confirmation", "result": "tight", "exit": "reversed", "confidence": 0.95}
ai._call = successful_voice_call
responses["voice_confirmation"] = packed(client.post("/api/voice/parse", json={"text": "Vào được nhưng phải gập gương, ra phải lùi"}))
ai._call = lambda prompt, **kwargs: {"kind": "blockage", "reason": "Xe ba gác chắn đầu hẻm", "confidence": 0.9}
responses["voice_blockage"] = packed(client.post("/api/voice/parse", json={"text": "Đầu hẻm có xe ba gác chắn"}))
ai._call = lambda prompt, **kwargs: {"kind": "confirmation", "result": "in", "exit": "unknown", "confidence": 0.2}
responses["voice_unclear"] = packed(client.post("/api/voice/parse", json={"text": "Hẻm này thế nào?"}))
ai._call = lambda prompt, **kwargs: []
responses["voice_non_object"] = packed(client.post("/api/voice/parse", json={"text": "Tôi vào hẻm"}))
ai._call = lambda prompt, **kwargs: {"kind": "confirmation", "result": "in", "confidence": "cao"}
responses["voice_bad_confidence"] = packed(client.post("/api/voice/parse", json={"text": "Tôi vào hẻm"}))
def no_voice_model(prompt, **kwargs):
    raise ai.NoModel("no test model")
ai._call = no_voice_model
responses["voice_no_model"] = packed(client.post("/api/voice/parse", json={"text": "Xe tôi vào được"}))
for name, error_type in (
    ("voice_empty_candidates", IndexError),
    ("voice_invalid_provider_shape", AttributeError),
    ("voice_deadline_expired", deadline.Expired),
):
    def fail_voice_parse(prompt, error=error_type(), **kwargs):
        raise error
    ai._call = fail_voice_parse
    responses[name] = packed(client.post("/api/voice/parse", json={"text": "Xe tôi vào hẻm"}))
responses["voice_too_long"] = packed(client.post("/api/voice/parse", json={"text": "x" * 301}))
import time
reports._rate.clear()
ai._call = successful_voice_call
responses["voice_quota_calls"] = [
    client.post("/api/voice/parse", json={"text": "Tôi vào hẻm"}).status_code for _ in range(20)
]
responses["voice_deadline_seconds"] = voice_deadlines[-1] - time.monotonic()
responses["voice_quota_21st"] = packed(client.post("/api/voice/parse", json={"text": "Tôi vào hẻm"}))
reports._rate.clear()
reports.allow_guest("testclient")
ai._call = original_voice_call
flags.set_flag("ai_voice_report", False)
responses["voice_flag_off"] = packed(client.post("/api/voice/parse", json={"text": "Xe tôi vào được"}))
responses["maneuver"] = packed(client.get("/api/vehicles/toyota-fortuner/maneuver", params={"width": 12}))

responses["unknown_vehicle"] = packed(client.post("/api/plan", json={**base, "vehicle_id": "unknown-vehicle"}))
for name, value in {
    "duration_zero": 0,
    "duration_negative": -1,
    "duration_fractional": 1.5,
}.items():
    responses[name] = packed(client.post("/api/plan", json={**base, "dwell_min": value}))
overflow_json = json.dumps({k: v for k, v in base.items() if k != "dwell_min"})[:-1] + ', "dwell_min": 1e309}'
responses["duration_non_finite"] = packed(client.post(
    "/api/plan", content=overflow_json, headers={"content-type": "application/json"}
))

original_key = route_plan.GOONG_API_KEY
original_drive = route_plan.goong_drive
route_plan.GOONG_API_KEY = "isolated-test"
try:
    route_plan.goong_drive = lambda origin, dest: None
    responses["plan_goong_fallback"] = packed(client.post(
        "/api/plan", json={**base, "arrive_at": "2026-10-11T09:30:00+07:00"}
    ))
    route_plan.goong_drive = lambda origin, dest: {
        "geometry": [[dest[1], dest[0]], [dest[1], dest[0]]],
        "distance_m": 1000,
        "duration_s": 300,
    }
    responses["plan_goong"] = packed(client.post(
        "/api/plan", json={**base, "arrive_at": "2026-10-11T09:30:00+07:00"}
    ))
finally:
    route_plan.GOONG_API_KEY = original_key
    route_plan.goong_drive = original_drive

paths = {
    "config_store": config.STORE,
    "config_cache": config.CACHE,
    "config_flags": config.FLAG_FILE,
    "ai_review": ai.REVIEW_FILE,
    "ai_live_flood": ai.LIVE_FLOOD_FILE,
    "budget_usage": budget.USAGE_FILE,
    "budget_ai_usage": budget.AI_USAGE_FILE,
    "camera_readings": cameras.READINGS_FILE,
    "camera_jobs": cameras.JOBS_FILE,
    "evidence_confirmations": evidence.CONFIRM_FILE,
    "evidence_blockages": evidence.BLOCKAGE_FILE,
    "pending_reports": reports.PENDING_FILE,
    "photo_reviews": live.PHOTO_REVIEWS,
    "live_areas": live.AREAS_DIR,
    "flood_live": flood.LIVE_FILE,
    "live_cache": live.DIR,
    "osm_demo": osm.DEMO_FILE,
    "vehicle_turning": vehicles._TP_CACHE,
}
print("VAODUOC_API_RESULTS=" + json.dumps({
    "responses": responses,
    "paths": {name: str(path) for name, path in paths.items()},
}, ensure_ascii=False))
'''


class ApiValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temp.cleanup)
        cls.temp_root = Path(cls._temp.name).resolve()
        store = cls.temp_root / "store"
        cache = cls.temp_root / "cache"
        flags = cls.temp_root / "flags.json"
        store.mkdir()
        (cache / "osm").mkdir(parents=True)
        shutil.copyfile(DEMO_CACHE, cache / "osm" / DEMO_CACHE.name)
        flags.write_text(json.dumps({"live_crawl": False, "live_hydro": False}), encoding="utf-8")

        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(BACKEND),
            "PYTHONDONTWRITEBYTECODE": "1",
            "VAODUOC_STORE": str(store),
            "VAODUOC_CACHE": str(cache),
            "VAODUOC_FLAGS": str(flags),
            "VERCEL": "",
            "GOONG_API_KEY": "",
            "GOONG_MAPTILES_KEY": "",
            "GEMINI_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GOOGLE_MAPS_API_KEY": "",
            "FLAG_LIVE_CRAWL": "0",
            "FLAG_LIVE_HYDRO": "0",
        })
        completed = subprocess.run(
            [sys.executable, "-c", SUBPROCESS_CASES],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if completed.returncode:
            raise AssertionError(
                f"isolated API subprocess failed ({completed.returncode})\n"
                f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        line = next((line for line in completed.stdout.splitlines() if line.startswith(RESULT_MARKER)), None)
        if line is None:
            raise AssertionError(f"isolated API subprocess returned no results:\n{completed.stdout}")
        result = json.loads(line.removeprefix(RESULT_MARKER))
        cls.responses = result["responses"]
        cls.paths = {name: Path(path) for name, path in result["paths"].items()}

    def assert_status(self, name: str, expected: int) -> None:
        self.assertEqual(self.responses[name]["status"], expected, self.responses[name]["json"])

    def test_datetime_fields_reject_malformed_naive_and_non_string_values(self) -> None:
        for name in (
            "plan_malformed",
            "plan_naive",
            "plan_non_string",
            "corridor_malformed",
            "corridor_naive",
            "corridor_non_string",
        ):
            with self.subTest(case=name):
                self.assert_status(name, 422)

    def test_null_datetime_uses_current_timezone_aware_time(self) -> None:
        self.assert_status("plan_null", 200)
        self.assert_status("corridor_null", 200)
        arrive = datetime.fromisoformat(self.responses["plan_null"]["json"]["window"]["arrive"])
        self.assertIsNotNone(arrive.utcoffset())
        self.assertLess(abs((datetime.now(arrive.tzinfo) - arrive).total_seconds()), 120)

    def test_existing_endpoint_status_contracts_are_preserved(self) -> None:
        self.assert_status("outside_hcmc", 422)
        self.assert_status("unknown_vehicle", 404)

    def test_maneuver_endpoint_returns_bounded_path_and_rejects_bad_inputs(self) -> None:
        self.assert_status("maneuver", 200)
        result = self.responses["maneuver"]["json"]
        self.assertEqual(result["vehicle_id"], "toyota-fortuner")
        self.assertTrue(result["simulated_vehicle_label"])
        self.assertEqual(result["width_m"], 12)
        self.assertIn("vehicle_length_m", result)
        self.assertIn("vehicle_mirror_width_m", result)
        self.assertIn("body_center_offset_m", result)
        self.assertIsInstance(result["vehicle_length_m"], (int, float))
        self.assertIsInstance(result["vehicle_mirror_width_m"], (int, float))
        self.assertIsInstance(result["body_center_offset_m"], (int, float))
        self.assertIsNotNone(result["moves"])
        self.assertGreater(len(result["poses"]), 1)
        self.assertLessEqual(len(result["poses"]), 120)
        self.assert_status("maneuver_unknown_vehicle", 404)
        for name in ("maneuver_low_width", "maneuver_high_width"):
            with self.subTest(case=name):
                self.assert_status(name, 422)

    def test_voice_parse_normalizes_intents_and_falls_back_without_model(self) -> None:
        self.assert_status("voice_confirmation", 200)
        self.assertEqual(self.responses["voice_confirmation"]["json"], {
            "kind": "confirmation", "result": "tight", "exit": "reversed",
        })
        self.assert_status("voice_blockage", 200)
        self.assertEqual(self.responses["voice_blockage"]["json"], {
            "kind": "blockage", "reason": "Xe ba gác chắn đầu hẻm",
        })
        for name in (
            "voice_unclear", "voice_no_model", "voice_empty_candidates",
            "voice_invalid_provider_shape", "voice_deadline_expired",
        ):
            with self.subTest(case=name):
                self.assert_status(name, 200)
                self.assertEqual(self.responses[name]["json"]["kind"], "unclear")
        self.assert_status("voice_too_long", 422)
        self.assertEqual(self.responses["voice_quota_calls"], [200] * 20)
        self.assertEqual(self.responses["voice_quota_21st"]["status"], 429)
        self.assertGreater(self.responses["voice_deadline_seconds"], 0)
        self.assertLessEqual(self.responses["voice_deadline_seconds"], 10)
        for name in ("voice_non_object", "voice_bad_confidence"):
            with self.subTest(case=name):
                self.assert_status(name, 200)
                self.assertEqual(self.responses[name]["json"]["kind"], "unclear")
        self.assert_status("voice_flag_off", 403)

    def test_duration_must_be_a_finite_positive_integer(self) -> None:
        for name in ("duration_zero", "duration_negative", "duration_fractional", "duration_non_finite"):
            with self.subTest(case=name):
                self.assert_status(name, 422)

    def test_standard_route_source_is_explicit_for_both_providers(self) -> None:
        self.assertEqual(self.responses["plan_null"]["json"]["standard_route"]["source"], "osm")
        self.assert_status("plan_goong_fallback", 200)
        self.assertEqual(self.responses["plan_goong_fallback"]["json"]["standard_route"]["source"], "osm")
        self.assert_status("plan_goong", 200)
        self.assertEqual(self.responses["plan_goong"]["json"]["standard_route"]["source"], "goong")

    def test_synthetic_demo_data_is_disabled_by_default(self) -> None:
        self.assertIs(self.responses["synthetic_demo_data"], False)
        self.assertIs(self.responses["plan_null"]["json"]["synthetic_demo_data"], False)

    def test_all_derived_runtime_paths_use_the_temporary_root(self) -> None:
        expected = {
            "config_store": self.temp_root / "store",
            "config_cache": self.temp_root / "cache",
            "config_flags": self.temp_root / "flags.json",
        }
        for name, path in expected.items():
            self.assertEqual(self.paths[name], path)
        for name, path in self.paths.items():
            with self.subTest(path=name):
                path.relative_to(self.temp_root)


if __name__ == "__main__":
    unittest.main()
