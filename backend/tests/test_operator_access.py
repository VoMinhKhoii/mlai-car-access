"""R-08: operator sessions, CSRF origin guard, guest limits, report review lifecycle, upload limits, SPA containment.

Everything runs in a subprocess whose state paths, operator secret and frontend dist are set before app import,
with the network disabled; nothing touches the repository store or a real secret.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DEMO_CACHE = BACKEND / "cache" / "osm" / "demo_binhthanh.json"
MARKER = "VAODUOC_OPERATOR_RESULTS="
SECRET = "test-operator-secret-not-real"

CASES = r'''
import json, os
from pathlib import Path
original_read_text = Path.read_text
Path.read_text = lambda p, *a, **k: "" if p.name == ".env.local" else original_read_text(p, *a, **k)
import httpx
def no_network(*a, **k):
    raise AssertionError("operator tests must not access the network")
httpx.get = no_network
httpx.post = no_network

from fastapi.testclient import TestClient
from app import config, evidence, flags, parcels, reports
from app.main import app
import app.main as main
from app.osm import build_graph
Path.read_text = original_read_text

out = {}
def packed(r):
    try:
        body = r.json()
    except ValueError:
        body = r.text[:200]
    return {"status": r.status_code, "json": body, "set_cookie": r.headers.get("set-cookie", "")}

store = Path(os.environ["VAODUOC_STORE"])
out["legacy_confirm_lines_after_start"] = [l for l in (store / "confirmations.jsonl").read_text().splitlines() if l.strip()]
out["legacy_blockage_lines_after_start"] = [l for l in (store / "blockages.jsonl").read_text().splitlines() if l.strip()]
out["quarantine_files"] = sorted(p.name.split(".")[0] for p in (store / "quarantine").glob("*.jsonl"))
out["legacy_pending"] = sorted(r["type"] for r in reports.list_reports("pending", limit=100)["items"] if r["legacy"])

guest = TestClient(app)
cfg = guest.get("/api/config")
out["initial_flag_values"] = {item["name"]: item["enabled"] for item in cfg.json()["flags"]}
out["config_operator"] = cfg.json()["operator"]
out["config_has_secret"] = os.environ["OPERATOR_SECRET_VALUE"] in cfg.text

for name, method, url, body in [
    ("guest_flags", "post", "/api/flags", {"name": "live_crawl", "enabled": True}),
    ("guest_build", "post", "/api/area/build", {"lat": 10.8, "lon": 106.71}),
    ("guest_ai_text", "post", "/api/ai/text", {"text": "x"}),
    ("guest_reload", "post", "/api/evidence/reload", {}),
    ("guest_photo_review", "post", "/api/photo/0123456789ab/review", {"approve": True}),
    ("guest_reports", "get", "/api/reports", None),
    ("guest_budget", "get", "/api/budget", None),
    ("guest_lookup", "get", "/api/lookup/places?lat=10.8&lon=106.71", None),
]:
    out[name] = packed(getattr(guest, method)(url, json=body) if body is not None else getattr(guest, method)(url))
out["flags_file_after_guest"] = json.loads(Path(os.environ["VAODUOC_FLAGS"]).read_text())

out["login_wrong"] = packed(guest.post("/api/operator/login", json={"secret": "wrong"}))
op = TestClient(app)
out["login_ok"] = packed(op.post("/api/operator/login", json={"secret": os.environ["OPERATOR_SECRET_VALUE"]}))
cookie = op.cookies.get("vd_operator")
out["op_status"] = op.get("/api/operator/status").json()

# Corrupt persisted flags fail closed. An authenticated write repairs the file and enables only the chosen flag.
flags_file = Path(os.environ["VAODUOC_FLAGS"])
saved_flags_file = flags_file.read_bytes()
flags_file.write_text("{broken")
flags._state.clear()
out["corrupt_flags"] = packed(guest.get("/api/flags"))
out["recover_corrupt_flags"] = packed(op.post("/api/flags", json={"name": "live_crawl", "enabled": True}))
out["flags_after_corrupt_recovery"] = json.loads(flags_file.read_text())
out["op_flags"] = packed(op.post("/api/flags", json={"name": "google_lookup", "enabled": False}))
out["op_cross_origin"] = packed(op.post("/api/flags", json={"name": "google_lookup", "enabled": False},
                                         headers={"Origin": "https://evil.example"}))
out["op_allowed_origin"] = packed(op.post("/api/flags", json={"name": "google_lookup", "enabled": False},
                                           headers={"Origin": "https://app.example"}))
flags_file.write_bytes(saved_flags_file)
flags._state.clear()
flags._load()
out["flags_restored_after_corrupt_test"] = dict(flags._state)

# Guest reports wait for review; the plan does not change until an operator approves.
g = build_graph(10.8, 106.71)
way_id = next(w.id for w in g.ways.values() if w.drivable)
main_road_stop = next((
    (w, g.nodes[node])
    for w in g.ways.values() if w.drivable and w.kind == "main"
    for node in w.nodes
    if main.cached_graph(*g.nodes[node]) is not None and not parcels.path_into(g, *g.nodes[node])
), None)
if main_road_stop is None:
    raise AssertionError("demo graph has no cached main-road stop")
main_road, (lat, lon) = main_road_stop
main_road_way_id = main_road.id
alley_point = None
for w in g.ways.values():
    if not w.drivable or not w.is_alley:
        continue
    candidate_lat = (g.nodes[w.nodes[0]][0] + g.nodes[w.nodes[-1]][0]) / 2
    candidate_lon = (g.nodes[w.nodes[0]][1] + g.nodes[w.nodes[-1]][1]) / 2
    if main.cached_graph(candidate_lat, candidate_lon) is not None and parcels.path_into(g, candidate_lat, candidate_lon) and parcels.path_out(g, candidate_lat, candidate_lon):
        alley_point = (w, candidate_lat, candidate_lon)
        break
if alley_point is None:
    raise AssertionError("demo graph has no alley with a server-computed ingress and egress")
alley, stop_lat, stop_lon = alley_point
out["confirm_extra_field"] = packed(guest.post("/api/confirm", json={
    "stop_lat": stop_lat, "stop_lon": stop_lon, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown", "way_ids": [way_id], "status": "approved"}))
out["confirm_unknown_stop"] = packed(guest.post("/api/confirm", json={
    "stop_lat": 21.0, "stop_lon": 105.0, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown"}))
out["confirm_bad_exit"] = packed(guest.post("/api/confirm", json={
    "stop_lat": stop_lat, "stop_lon": stop_lon, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "not-an-exit"}))
pending_before_main_road = len(reports._load()["reports"])
out["confirm_main_road"] = packed(guest.post("/api/confirm", json={
    "stop_lat": lat, "stop_lon": lon, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown"}))
out["pending_count_before_main_road"] = pending_before_main_road
out["pending_count_after_main_road"] = len(reports._load()["reports"])
pending_before_non_alley = len(reports._load()["reports"])
non_alley_stop = None
for w in g.ways.values():
    if not w.drivable or w.is_alley or w.kind == "main":
        continue
    candidate = ((g.nodes[w.nodes[0]][0] + g.nodes[w.nodes[-1]][0]) / 2,
                 (g.nodes[w.nodes[0]][1] + g.nodes[w.nodes[-1]][1]) / 2)
    ingress = parcels.path_into(g, *candidate)
    if ingress and not g.ways[ingress[-1][0]].is_alley and main.cached_graph(*candidate) is not None:
        non_alley_stop = candidate
        break
if non_alley_stop is None:
    raise AssertionError("demo graph has no cached non-alley terminal stop")
out["confirm_non_alley"] = packed(guest.post("/api/confirm", json={
    "stop_lat": non_alley_stop[0], "stop_lon": non_alley_stop[1], "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown"}))
out["pending_before_non_alley"] = pending_before_non_alley
out["pending_after_non_alley"] = len(reports._load()["reports"])

off_way_stop = None
for dlat, dlon in ((.0001, 0), (-.0001, 0), (0, .0001), (0, -.0001),
                   (.0002, 0), (-.0002, 0), (0, .0002), (0, -.0002),
                   (.0004, 0), (-.0004, 0), (0, .0004), (0, -.0004),
                   (.0008, 0), (-.0008, 0), (0, .0008), (0, -.0008)):
    candidate = (stop_lat + dlat, stop_lon + dlon)
    if main.cached_graph(*candidate) is None:
        continue
    ingress = parcels.path_into(g, *candidate)
    if ingress and g.ways[ingress[-1][0]].is_alley \
       and main.haversine(*candidate, *ingress[-1][1][-1]) > 5.0:
        off_way_stop = candidate
        break
if off_way_stop is None:
    raise AssertionError("demo graph has no cached stop point more than 5 m from an alley projection")
pending_before_off_way = len(reports._load()["reports"])
out["confirm_off_way_stop"] = packed(guest.post("/api/confirm", json={
    "stop_lat": off_way_stop[0], "stop_lon": off_way_stop[1], "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown"}))
out["pending_before_off_way"] = pending_before_off_way
out["pending_after_off_way"] = len(reports._load()["reports"])
original_allow_guest = reports.allow_guest
original_cached_graph = main.cached_graph
def deny_guest(_client, **kwargs):
    raise reports.RateLimited()
def fail_if_graph_is_loaded(*_args):
    raise AssertionError("rate-limited confirmation must not load the graph")
reports.allow_guest = deny_guest
main.cached_graph = fail_if_graph_is_loaded
out["confirm_rate_limited_before_graph"] = packed(guest.post("/api/confirm", json={
    "stop_lat": stop_lat, "stop_lon": stop_lon, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "unknown"}))
reports.allow_guest = original_allow_guest
main.cached_graph = original_cached_graph
original_allow_guest_2 = reports.allow_guest
def deny_guest_blockage(_client, **kwargs):
    raise reports.RateLimited()
def fail_if_graph_is_loaded_blockage(*_args, **kwargs):
    raise AssertionError("rate-limited blockage must not load the graph")
reports.allow_guest = deny_guest_blockage
main.cached_graph = fail_if_graph_is_loaded_blockage
out["blockage_rate_limited_before_graph"] = packed(guest.post("/api/blockage", json={
    "lat": lat, "lon": lon, "way_id": main_road_way_id, "reason": "test"}))
reports.allow_guest = original_allow_guest_2
main.cached_graph = original_cached_graph
sub = guest.post("/api/confirm", json={
    "stop_lat": stop_lat, "stop_lon": stop_lon, "vehicle_id": "toyota-vios",
    "result": "in", "exit": "turned"})
out["confirm_guest"] = packed(sub)
rid = sub.json()["report_id"]
confirm_payload = reports._load()["reports"][rid]["payload"]
out["confirm_payload"] = confirm_payload
confirm_ingress = [w for w, _ in parcels.path_into(g, stop_lat, stop_lon)]
out["confirm_full_ingress_way_ids"] = confirm_ingress
out["confirm_selected_alley_way_id"] = alley.id
out["confirm_expected_stop_way_id"] = confirm_ingress[-1]
out["confirm_expected_way_ids"] = [confirm_ingress[-1]]
out["confirm_expected_way_out_ids"] = [w for w, _ in parcels.path_out(g, stop_lat, stop_lon)]
confirm_file = store / "confirmations.jsonl"
count = lambda: sum(1 for l in confirm_file.read_text().splitlines() if rid in l) if confirm_file.exists() else 0
out["projected_before_approval"] = count()
out["approve"] = packed(op.post(f"/api/reports/{rid}", json={"approve": True}))
out["projected_after_approval"] = count()
out["approve_again"] = packed(op.post(f"/api/reports/{rid}", json={"approve": True}))
out["reject_after_approve"] = packed(op.post(f"/api/reports/{rid}", json={"approve": False}))
out["projected_after_repeat"] = count()
# Crash between the committed decision and its projection: reconcile restores it exactly once.
confirm_file.write_text("".join(l + "\n" for l in confirm_file.read_text().splitlines() if rid not in l))
reports.reconcile(); reports.reconcile()
out["projected_after_crash_reconcile"] = count()
out["evidence_has_confirmation"] = any(
    "Arrival confirmation" == bound.source
    for way_id in confirm_payload["way_ids"]
    for bound in evidence.STORE_EVIDENCE.snapshot.by_way.get(way_id, [])
)
out["evidence_has_exit_claim"] = any(
    "turn around and exit" in bound.detail
    for way_id in confirm_payload["way_out_ids"]
    for bound in evidence.STORE_EVIDENCE.snapshot.way_out_by_way.get(way_id, [])
)

# Expired reports never promote.
data = json.loads(reports.PENDING_FILE.read_text())
old = reports.submit("blockage", {"way_id": way_id, "reason": "x", "source": "test", "date": "2000-01-01"}, "test")
data = json.loads(reports.PENDING_FILE.read_text())
data["reports"][old["report_id"]]["expires_at"] = "2000-01-02T00:00:00+07:00"
reports.PENDING_FILE.write_text(json.dumps(data))
out["approve_expired"] = packed(op.post(f"/api/reports/{old['report_id']}", json={"approve": True}))

# More than 50 pending reports are all reachable through the cursor.
for i in range(60):
    reports.submit("blockage", {"way_id": way_id, "reason": f"r{i}", "source": "test", "date": reports.today()}, "t")
seen, cursor, pages = [], None, 0
while True:
    page = op.get("/api/reports", params={"status": "pending", "limit": 50, **({"cursor": cursor} if cursor else {})}).json()
    seen += [r["report_id"] for r in page["items"]]
    pages += 1
    cursor = page["next_cursor"]
    if not cursor:
        break
out["paginated_pending"] = {"pages": pages, "count": len(seen), "unique": len(set(seen))}

# Uploads are bounded and type-checked before any model call.
big = b"\xff\xd8\xff" + b"0" * (8 * 1024 * 1024)
out["upload_too_big"] = packed(op.post("/api/ai/photo", files={"file": ("a.jpg", big, "image/jpeg")}))
out["upload_wrong_type"] = packed(op.post("/api/ai/photo", files={"file": ("a.jpg", b"GIF89a....", "image/jpeg")}))

# Unknown API and SPA containment.
out["unknown_api"] = packed(guest.get("/api/does-not-exist"))
out["area_key_bad"] = packed(guest.get("/api/area/build/..%2F..%2Fsecret"))
out["area_key_regex"] = packed(guest.get("/api/area/build/not_a_key"))
out["spa_route"] = packed(guest.get("/some/app/route"))
out["spa_dotdot"] = packed(guest.get("/%2e%2e/%2e%2e/secret.txt"))
out["spa_symlink"] = packed(guest.get("/leak.txt"))
out["spa_missing_asset"] = packed(guest.get("/missing.js"))

# Logout revokes the session; replaying the old cookie is refused.
out["logout"] = packed(op.post("/api/operator/logout"))
replay = TestClient(app)
replay.cookies.set("vd_operator", cookie)
out["replay_after_logout"] = packed(replay.post("/api/flags", json={"name": "google_lookup", "enabled": False}))

# Without a configured secret, operator features are unavailable, never open.
os.environ["OPERATOR_SECRET_FILE"] = str(store / "no-such-secret")
out["no_secret_status"] = guest.get("/api/operator/status").json()
out["no_secret_flags"] = packed(guest.post("/api/flags", json={"name": "live_crawl", "enabled": True}))

print("VAODUOC_OPERATOR_RESULTS=" + json.dumps(out, ensure_ascii=False))
'''


class OperatorAccess(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls._temp.cleanup)
        root = Path(cls._temp.name).resolve()
        store, cache, dist = root / "store", root / "cache", root / "dist"
        store.mkdir()
        (cache / "osm").mkdir(parents=True)
        shutil.copyfile(DEMO_CACHE, cache / "osm" / DEMO_CACHE.name)
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><title>app shell</title>", encoding="utf-8")
        secret_file = root / "secret.txt"
        secret_file.write_text(SECRET, encoding="utf-8")
        os.symlink(secret_file, dist / "leak.txt")
        flags = root / "flags.json"
        flags.write_text(json.dumps({"live_crawl": False, "live_hydro": False}), encoding="utf-8")
        # Legacy community files written by unauthenticated guests before review existed.
        (store / "confirmations.jsonl").write_text(json.dumps({
            "date": "2026-10-01", "vehicle_id": "toyota-vios", "vehicle_label": "Toyota Vios", "body_width": 1.73,
            "mirror_width": 1.98, "result": "in", "way_ids": [32584409], "lat": 10.8, "lon": 106.71}) + "\n")
        (store / "blockages.jsonl").write_text(
            json.dumps({"way_id": 192512291, "reason": "demo", "source": "x", "date": "demo"}) + "\n"
            + json.dumps({"way_id": 1, "reason": "old", "source": "Tài xế báo", "date": "2026-10-01"}) + "\n")
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(BACKEND), "PYTHONDONTWRITEBYTECODE": "1",
            "VAODUOC_STORE": str(store), "VAODUOC_CACHE": str(cache), "VAODUOC_FLAGS": str(flags),
            "VAODUOC_DIST": str(dist), "OPERATOR_SECRET_FILE": str(secret_file), "OPERATOR_SECRET_VALUE": SECRET,
            "APP_ORIGINS": "https://app.example", "VERCEL": "", "GOONG_API_KEY": "", "GOONG_MAPTILES_KEY": "",
            "GEMINI_API_KEY": "", "OPENAI_API_KEY": "", "ANTHROPIC_API_KEY": "", "GOOGLE_MAPS_API_KEY": "",
            "FLAG_LIVE_CRAWL": "0", "FLAG_LIVE_HYDRO": "0",
        })
        env.pop("OPERATOR_SECRET", None)
        done = subprocess.run([sys.executable, "-c", CASES], cwd=BACKEND, env=env, capture_output=True, text=True,
                              timeout=180)
        if done.returncode:
            raise AssertionError(f"operator subprocess failed\nstdout:\n{done.stdout}\nstderr:\n{done.stderr}")
        line = next((x for x in done.stdout.splitlines() if x.startswith(MARKER)), None)
        if line is None:
            raise AssertionError(f"operator subprocess returned no results:\n{done.stdout}\n{done.stderr}")
        cls.r = json.loads(line.removeprefix(MARKER))
        cls.root = root

    def status(self, name: str) -> int:
        return self.r[name]["status"]

    def test_guests_cannot_change_state_or_spend(self):
        for name in ("guest_flags", "guest_build", "guest_ai_text", "guest_reload", "guest_photo_review",
                     "guest_reports", "guest_budget", "guest_lookup"):
            with self.subTest(case=name):
                self.assertEqual(self.status(name), 401, self.r[name])
        self.assertEqual(self.r["flags_file_after_guest"], {"live_crawl": False, "live_hydro": False})

    def test_login_issues_a_strict_httponly_cookie_and_never_exposes_the_secret(self):
        self.assertEqual(self.status("login_wrong"), 401)
        self.assertEqual(self.status("login_ok"), 200)
        cookie = self.r["login_ok"]["set_cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertEqual(self.r["op_status"], {"available": True, "operator": True})
        self.assertEqual(self.r["config_operator"], {"available": True, "signed_in": False})
        self.assertFalse(self.r["config_has_secret"])

    def test_cross_origin_mutation_is_refused_even_with_a_valid_session(self):
        self.assertEqual(self.status("op_flags"), 200)
        self.assertEqual(self.status("op_cross_origin"), 403)
        self.assertEqual(self.status("op_allowed_origin"), 200)

    def test_logout_revokes_and_a_replayed_cookie_is_refused(self):
        self.assertEqual(self.status("logout"), 200)
        self.assertEqual(self.status("replay_after_logout"), 401)

    def test_missing_secret_makes_operator_features_unavailable_not_open(self):
        self.assertEqual(self.r["no_secret_status"], {"available": False, "operator": False})
        self.assertEqual(self.status("no_secret_flags"), 503)

    def test_corrupt_flags_fail_closed_and_operator_api_recovers(self):
        corrupt = self.r["corrupt_flags"]
        self.assertEqual(corrupt["status"], 200)
        self.assertTrue(all(not flag["enabled"] for flag in corrupt["json"]["flags"]))
        self.assertEqual(self.status("recover_corrupt_flags"), 200)
        recovered = self.r["flags_after_corrupt_recovery"]
        self.assertTrue(recovered["live_crawl"])
        self.assertTrue(all(isinstance(value, bool) for value in recovered.values()))
        self.assertEqual(self.r["flags_restored_after_corrupt_test"], self.r["initial_flag_values"])

    def test_guest_report_waits_for_review_and_projects_exactly_once(self):
        self.assertEqual(self.status("confirm_rate_limited_before_graph"), 429)
        self.assertEqual(self.status("blockage_rate_limited_before_graph"), 429)
        self.assertEqual(self.status("confirm_extra_field"), 422)
        self.assertEqual(self.status("confirm_unknown_stop"), 422)
        self.assertEqual(self.status("confirm_bad_exit"), 422)
        self.assertEqual(
            self.r["confirm_main_road"]["json"]["detail"],
            "Confirmations apply only to alleys mapped by the server. Choose a blockage report to report obstructions.",
        )
        self.assertEqual(self.r["pending_count_before_main_road"], self.r["pending_count_after_main_road"])
        self.assertEqual(self.status("confirm_main_road"), 422)
        self.assertEqual(self.status("confirm_non_alley"), 422)
        self.assertIn("mapped directly to an alley", self.r["confirm_non_alley"]["json"]["detail"])
        self.assertEqual(self.r["pending_before_non_alley"], self.r["pending_after_non_alley"])
        self.assertEqual(self.status("confirm_off_way_stop"), 422)
        self.assertIn("mapped directly to an alley", self.r["confirm_off_way_stop"]["json"]["detail"])
        self.assertEqual(self.r["pending_before_off_way"], self.r["pending_after_off_way"])
        self.assertEqual(self.status("confirm_guest"), 202)
        self.assertEqual(self.r["confirm_guest"]["json"]["status"], "pending")
        self.assertEqual(self.r["projected_before_approval"], 0)
        self.assertEqual(self.status("approve"), 200)
        self.assertEqual(self.r["projected_after_approval"], 1)
        self.assertEqual(self.status("approve_again"), 200)
        self.assertEqual(self.status("reject_after_approve"), 409)
        self.assertEqual(self.r["projected_after_repeat"], 1)
        self.assertEqual(self.r["projected_after_crash_reconcile"], 1)
        self.assertTrue(self.r["evidence_has_confirmation"])
        payload = self.r["confirm_payload"]
        self.assertEqual(self.r["confirm_selected_alley_way_id"], self.r["confirm_expected_stop_way_id"])
        self.assertEqual(payload["way_ids"], self.r["confirm_expected_way_ids"])
        self.assertEqual(payload["way_out_ids"], self.r["confirm_expected_way_out_ids"])
        self.assertEqual(payload["exit"], "turned")
        self.assertTrue(self.r["evidence_has_exit_claim"])

    def test_expired_reports_never_promote(self):
        self.assertEqual(self.status("approve_expired"), 409)

    def test_more_than_fifty_pending_reports_are_all_reachable(self):
        page = self.r["paginated_pending"]
        self.assertGreaterEqual(page["pages"], 2)
        self.assertEqual(page["count"], page["unique"])
        self.assertGreaterEqual(page["count"], 60)

    def test_legacy_unreviewed_lines_are_quarantined_and_queued_and_demo_is_not_reseeded(self):
        self.assertEqual(self.r["legacy_confirm_lines_after_start"], [])
        self.assertEqual(self.r["legacy_blockage_lines_after_start"], [])
        self.assertEqual(self.r["quarantine_files"], ["blockages", "confirmations"])
        self.assertEqual(self.r["legacy_pending"], ["blockage", "confirmation"])

    def test_uploads_are_bounded_and_typed_before_any_model_call(self):
        self.assertEqual(self.status("upload_too_big"), 413)
        self.assertEqual(self.status("upload_wrong_type"), 415)

    def test_unknown_api_is_json_and_spa_stays_inside_dist(self):
        self.assertEqual(self.status("unknown_api"), 404)
        self.assertIsInstance(self.r["unknown_api"]["json"], dict)
        self.assertIn(self.status("area_key_bad"), (404, 422))
        self.assertEqual(self.status("area_key_regex"), 422)
        self.assertEqual(self.status("spa_route"), 200)
        self.assertIn("app shell", str(self.r["spa_route"]["json"]))
        for name in ("spa_dotdot", "spa_symlink", "spa_missing_asset"):
            with self.subTest(case=name):
                self.assertEqual(self.status(name), 404, self.r[name])
                self.assertNotIn(SECRET, str(self.r[name]["json"]))


if __name__ == "__main__":
    unittest.main()
