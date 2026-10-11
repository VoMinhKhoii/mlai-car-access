"""Route choice from camera readings and the flood forecast (D34), with Goong and the cameras stubbed.

Run:  cd backend && python3 -m unittest tests.test_corridor
"""
import unittest
from datetime import datetime, timedelta
from unittest import mock

from app import cameras, corridor
from app.flood import FloodRecord

VN = corridor.VN_TZ
O, D = (10.800, 106.700), (10.800, 106.720)
# Route A runs straight along "Đường A" past camera X; route B bends north along "Đường B" past camera Y.
CAM_X = {"id": "x", "name": "Đường A - Đường C", "lat": 10.8000, "lon": 106.7100, "code": "", "type": "tth"}
CAM_Y = {"id": "y", "name": "Đường B - Đường D", "lat": 10.8100, "lon": 106.7100, "code": "", "type": "tth"}


def _route(points, name, minutes, via=None):
    coords = [[lon, lat] for lat, lon in points]
    steps = [{"name": "", "coords": coords[:1], "m": 0},
             {"name": name, "coords": coords, "m": 1}, {"name": "", "coords": coords[-1:], "m": 0}]
    return {"geometry": coords, "steps": steps, "via": via, "distance_m": 2500 if via else 2200,
            "duration_s": minutes * 60}


def fake_goong(origin, dest, via=None):
    if via is None:
        return _route([O, (10.800, 106.710), D], "Đường A", 10)
    return _route([O, (10.810, 106.703), (10.810, 106.710), (10.810, 106.717), D], "Đường B", 14, via)


def reading(cam, traffic="thong_thoang", depth_cm=0):
    return {"id": cam["id"], "name": cam["name"], "lat": cam["lat"], "lon": cam["lon"], "state": "ok",
            "confidence": 0.9, "traffic": traffic, "depth_cm": depth_cm, "flooded": bool(depth_cm),
            "image_time": datetime.now(VN).isoformat(timespec="seconds"), "at": datetime.now(VN).isoformat()}


class Corridor(unittest.TestCase):
    def setUp(self):
        self.readings = {}
        self.records = []
        patches = [
            mock.patch.object(corridor, "GOONG_API_KEY", "test"),
            mock.patch.object(corridor, "goong_route", fake_goong),
            mock.patch.object(corridor, "_via_candidates", lambda o, d, pts: [CAM_Y]),
            mock.patch.object(corridor, "load_records", lambda: self.records),
            mock.patch.object(cameras, "registry", lambda: {"cameras": [CAM_X, CAM_Y]}),
            mock.patch.object(cameras, "read_many", lambda ids: {i: self.readings[i] for i in ids if i in self.readings}),
            mock.patch.object(corridor.flags, "enabled", lambda name: name != "live_hydro"),  # offline
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def run_corridor(self, **kw):
        out = corridor.corridor(O, D, "toyota-vios", **kw)
        return out, next(r for r in out["routes"] if r["chosen"])

    def test_cameras_match_their_own_route(self):
        out, _ = self.run_corridor()
        a, b = out["routes"]
        self.assertEqual([h["name"] for h in a["hotspots"]], [CAM_X["name"]])
        self.assertEqual([h["name"] for h in b["hotspots"]], [CAM_Y["name"]])

    def test_clear_roads_keep_the_faster_route(self):
        self.readings = {"x": reading(CAM_X), "y": reading(CAM_Y)}
        out, best = self.run_corridor()
        self.assertTrue(best["is_goong"])
        self.assertTrue(out["live"])

    def test_jam_on_the_short_route_switches(self):
        self.readings = {"x": reading(CAM_X, "ket_cung"), "y": reading(CAM_Y)}
        out, best = self.run_corridor()
        self.assertEqual(best["label"], "qua Đường B")
        self.assertIn("kẹt cứng", out["summary"])
        self.assertGreaterEqual(out["routes"][0]["delay_min"], corridor.TRAFFIC_QUEUE_MIN["ket_cung"])

    def test_slow_traffic_is_not_worth_a_longer_detour(self):
        self.readings = {"x": reading(CAM_X, "dong"), "y": reading(CAM_Y)}
        _, best = self.run_corridor()
        self.assertTrue(best["is_goong"])  # 10 + 2 min still beats 14 min

    def test_unwatched_roads_take_the_typical_traffic(self):
        # Rush hour everywhere: a route is not "faster" just because fewer cameras watch it.
        self.readings = {"x": reading(CAM_X, "dong")}
        out, _ = self.run_corridor()
        self.assertEqual(out["typical_factor"], corridor.TRAFFIC_FACTOR["dong"])
        self.assertGreater(out["routes"][1]["delay_min"], 0)

    def test_water_deeper_than_the_car_can_wade_blocks_the_route(self):
        self.readings = {"x": reading(CAM_X, depth_cm=40), "y": reading(CAM_Y)}
        out, best = self.run_corridor()
        self.assertEqual(out["routes"][0]["status"], "blocked")
        self.assertFalse(best["is_goong"])
        self.assertIn("ngập", out["summary"])

    def test_unreadable_cameras_change_nothing(self):
        self.readings = {"x": {**reading(CAM_X, "ket_cung"), "state": "stale"},
                         "y": {**reading(CAM_Y), "confidence": 0.2}}
        _, best = self.run_corridor()
        self.assertTrue(best["is_goong"])

    def test_cameras_are_ignored_for_a_later_departure(self):
        self.readings = {"x": reading(CAM_X, "ket_cung"), "y": reading(CAM_Y)}
        out, best = self.run_corridor(depart_at=datetime.now(VN) + timedelta(hours=3))
        self.assertFalse(out["live"])
        self.assertTrue(best["is_goong"])
        self.assertIn("dự báo ngập", out["live_note"])

    def test_flood_forecast_on_route_counts_without_cameras(self):
        # A rain-flooding street on route A, with 45 mm/h of rain while driving.
        self.records = [FloodRecord(10.8000, 106.7050, "Đường A", 2020, "", "rain", 40, "high", "")]
        now = datetime.now(VN)
        rain = [{"start": (now - timedelta(hours=1)).isoformat(), "end": (now + timedelta(hours=4)).isoformat(),
                 "mm_per_h": 45}]
        out, best = self.run_corridor(depart_at=now + timedelta(hours=2), rain=rain)
        a = out["routes"][0]
        self.assertEqual([f["street"] for f in a["flood_forecast"]], ["Đường A"])
        self.assertIn(a["status"], ("risky", "blocked"))
        self.assertFalse(best["is_goong"])


class GroupNaming(unittest.TestCase):
    def group(self, *levels):
        cams = [{**CAM_X, "id": f"c{i}", "name": f"Đường A - Đường {i}", "along_m": 1000 + i} for i in range(len(levels))]
        readings = {c["id"]: reading(c, lv) for c, lv in zip(cams, levels)}
        return corridor._observe([cams], readings, corridor.get_profile("toyota-vios"))[0]

    def test_one_camera_catching_a_queue_does_not_rate_the_junction(self):
        h = self.group("thong_thoang", "un_u", "dong")
        self.assertEqual(h["traffic"], "dong")

    def test_a_jam_most_cameras_see_counts(self):
        h = self.group("ket_cung", "ket_cung", "dong")
        self.assertEqual((h["traffic"], h["cameras"][0]["traffic"]), ("ket_cung", "ket_cung"))
        self.assertEqual(h["name"], h["cameras"][0]["name"])


class OfficialRegistry(unittest.TestCase):
    def test_ajaxpro_datatables(self):
        # Shape of the portal's answer: nested DataTable literals, and ")" inside names.
        raw = ('{"value":[{},[[],new Ajax.Web.DataTable([["CamId","System.Object"],["DisplayName","System.Object"],'
               '["Location","System.Object"]],[["abc","PVĐ (hướng đi Sân bay)",new Ajax.Web.DataTable('
               '[["Shape","System.Object"]],[["POINT(106.7 10.8)"]])]])],1]}')
        rows = cameras._table(cameras._ajaxpro_json(raw)["value"][1][1])
        self.assertEqual(rows[0]["DisplayName"], "PVĐ (hướng đi Sân bay)")
        self.assertEqual(cameras._table(rows[0]["Location"])[0]["Shape"], "POINT(106.7 10.8)")


class ModelFallback(unittest.TestCase):
    def test_next_model_reads_when_the_first_is_out_of_quota(self):
        import httpx
        from datetime import datetime
        calls = []

        def fake_call(prompt, parts, model=None):
            calls.append(model)
            if model == "first":
                raise httpx.HTTPStatusError("quota", request=httpx.Request("POST", "http://x"),
                                            response=httpx.Response(429))
            return {"cameras": [{"camera": 1, "traffic": "dong", "usable": True, "confidence": 0.9}]}

        stored = []
        with mock.patch.object(cameras, "CAMERA_MODELS", ["first", "second"]), \
                mock.patch.object(cameras, "_resting", {}), \
                mock.patch.object(cameras.ai, "_call", fake_call), \
                mock.patch.object(cameras.ai, "provider", lambda: ("gemini", "test-model")), \
                mock.patch.object(cameras, "by_id", lambda: {"x": CAM_X}), \
                mock.patch.object(cameras, "_log", lambda cam, rec: None), \
                mock.patch.object(cameras, "_store", stored.append):
            cameras._ask(["x"], {"x": b"a"}, {"x": b"b"}, datetime.now(VN))
            cameras._ask(["x"], {"x": b"a"}, {"x": b"b"}, datetime.now(VN))
        self.assertEqual(calls, ["first", "second", "second"])  # the spent model rests instead of being retried
        self.assertTrue(stored[0]["model"].endswith("second") or stored[0]["model"] == "second")


class CameraNames(unittest.TestCase):
    def test_street_names(self):
        self.assertEqual(cameras.street_names({"name": "Cầu Sài Gòn 2 (dạ cầu)"}), ["cau sai gon"])
        self.assertEqual(cameras.street_names({"name": "Phạm Văn Đồng - Nguyễn Xí (hướng đi Sân bay)"}),
                         ["pham van dong", "nguyen xi"])
        self.assertEqual(cameras.street_names({"name": "Nút giao Hàng Xanh 6 (Cầu Điện Biên Phủ - Hàng Xanh)"}),
                         ["hang xanh"])


if __name__ == "__main__":
    unittest.main()
