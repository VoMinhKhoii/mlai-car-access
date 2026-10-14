"""HTTP API for Vào Được (working name). Run: uvicorn app.main:app --host 127.0.0.1 --port 8787 --workers 1

One continuously running process owns all state (area builds, reviews, sessions, quotas, camera jobs): run a single
worker with persistent VAODUOC_STORE / VAODUOC_CACHE / VAODUOC_FLAGS.

Access: guests read plans, corridors (forecast and cached camera readings) and evidence, and submit reports that wait
for review. Anything that changes state, spends AI or paid-Google quota, or schedules background work needs an
operator session (auth.py).
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from typing import Annotated, Literal

import httpx
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from .config import FRONTEND_DIST, GOONG_API_KEY, GOONG_MAPTILES_KEY, SIDE_CLEARANCE_M, in_hcmc
from . import ai, auth, budget, cameras, corridor, flags, geometry, google_lookup, hydro, live, parcels, plan, reports, vehicles
from .evidence import STORE_EVIDENCE
from .flood import tide_meta, tide_series
from .osm import build_graph, cached_graph, haversine, strip_accents
from .deadline import Expired
from .storage import CorruptState

VN_TZ = timezone(timedelta(hours=7))
FALLBACK_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
GOONG_STYLE = "https://tiles.goong.io/assets/goong_map_web.json?api_key={key}"
DEMO_CENTER = (10.8, 106.71)
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_MAGIC = ((b"\xff\xd8\xff", "image/jpeg"), (b"\x89PNG\r\n\x1a\n", "image/png"))
JOB_ID = re.compile(r"^[0-9a-f]{12}$")
REPORT_ID = re.compile(r"^(r-\d{8}-[0-9a-f]{12}|legacy-[0-9a-f]{16})$")

app = FastAPI(title="Vào Được API")
app.add_middleware(CORSMiddleware, allow_origins=sorted(auth.allowed_origins()), allow_credentials=True,
                   allow_methods=["GET", "POST"], allow_headers=["content-type"])


@app.middleware("http")
async def origin_guard(request: Request, call_next):
    """CSRF guard: a browser may only change state from this server's own origin or an APP_ORIGINS entry."""
    if request.method not in ("GET", "HEAD", "OPTIONS") and not auth.origin_ok(request):
        return JSONResponse(status_code=403, content={"detail": "Nguồn yêu cầu không được phép"})
    return await call_next(request)


@app.exception_handler(RequestValidationError)
def validation_error(_request, exc: RequestValidationError):
    # Rejected inputs can contain non-finite floats; never echo them in JSON errors.
    return JSONResponse(status_code=422, content={"detail": [
        {"loc": error["loc"], "msg": error["msg"], "type": error["type"]}
        for error in exc.errors()
    ]})


@app.exception_handler(CorruptState)
def corrupt_state(_request, exc: CorruptState):
    # Review state that cannot be read is never guessed: the action stops, nothing is published.
    return JSONResponse(status_code=503, content={"detail": f"Dữ liệu trạng thái bị hỏng, cần kiểm tra: {exc}"})


# Startup (one process): unreviewed legacy community lines move to the review queue, approved reports are
# re-projected if a crash interrupted a projection, then evidence is rebuilt from the reviewed files only.
reports.migrate_legacy()
reports.reconcile()
STORE_EVIDENCE.reload()

Lat = Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
Lon = Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]
DurationMinutes = Annotated[int, Field(strict=True, gt=0, le=7 * 24 * 60)]
WayId = Annotated[int, Field(gt=0)]


class Strict(BaseModel):
    """Request bodies reject unknown fields: a client cannot slip in trusted-looking state (status, area, …)."""
    model_config = ConfigDict(extra="forbid")


def _way_mid(way_id: int):
    g = build_graph(*DEMO_CENTER)
    w = g.ways[way_id]
    return g.nodes[w.nodes[len(w.nodes) // 2]]


PRESETS = [
    {"id": "friend-house", "title": "Nhà bạn trong hẻm, giờ triều cường", "way_id": 32584409,
     "label": "Hẻm 220/9 Xô Viết Nghệ Tĩnh, Bình Thạnh", "intent": "park", "vehicle_id": "toyota-vios",
     "arrive_at": "2026-09-29T16:30:00+07:00", "dwell_min": 120,
     "story": "Vios đến 16:30, ở 2 tiếng. Đỉnh triều 18:10 (1,66 m) làm ngập đường ra. Đổi sang Fortuner để so sánh."},
    {"id": "cafe-ngo-tat-to", "title": "Quán cà phê gần đường hay ngập", "way_id": 544982029,
     "label": "Hẻm 160 Ngô Tất Tố, Bình Thạnh", "intent": "park", "vehicle_id": "class-s",
     "arrive_at": "2026-09-29T14:00:00+07:00", "dwell_min": 90,
     "rain": [{"start": "2026-09-29T14:30:00+07:00", "end": "2026-09-29T15:30:00+07:00", "mm_per_h": 45}],
     "story": "Mưa 45 mm/h lúc 14:30 trên nền triều lên. Ngô Tất Tố có 6 lần ngập trong lịch sử IRD."},
    {"id": "pickup-narrow", "title": "Đón khách trong hẻm không vào được ô tô", "way_id": 136507381,
     "label": "Hẻm 328 Xô Viết Nghệ Tĩnh, Bình Thạnh", "intent": "pickup", "vehicle_id": "vinfast-vf-5",
     "arrive_at": "2026-09-29T10:00:00+07:00", "dwell_min": 15,
     "story": "Tài xế xe công nghệ. Hẻm được đánh dấu không vào được ô tô: điểm đón gần nhất và quãng khách phải đi bộ."},
    {"id": "nguyen-huu-canh", "title": "Hẻm gần Nguyễn Hữu Cảnh", "way_id": 193085696,
     "label": "Hẻm 91 Nguyễn Hữu Cảnh, Bình Thạnh", "intent": "park", "vehicle_id": "class-m",
     "arrive_at": "2026-09-30T17:00:00+07:00", "dwell_min": 120,
     "story": "Đường ngập nhiều năm nhất trong dữ liệu (10 năm). Triều 30/09 dự báo 1,67 m lúc 18:50."},
]


# ---- operator session ---------------------------------------------------------------

class LoginIn(Strict):
    secret: str = Field(min_length=1, max_length=512)


@app.post("/api/operator/login")
def operator_login(body: LoginIn, request: Request, response: Response):
    auth.login(request, response, body.secret)
    return {"operator": True}


@app.post("/api/operator/logout")
def operator_logout(request: Request, response: Response):
    auth.logout(request, response)
    return {"operator": False}


@app.get("/api/operator/status")
def operator_status(request: Request):
    return {"available": auth.available(), "operator": auth.is_operator(request)}


Operator = Annotated[str, Depends(auth.require_operator)]


# ---- read-only -------------------------------------------------------------------------

@app.get("/api/config")
def config(request: Request):
    return {
        "map_style": GOONG_STYLE.format(key=GOONG_MAPTILES_KEY) if GOONG_MAPTILES_KEY else FALLBACK_STYLE,
        "goong": {"tiles": bool(GOONG_MAPTILES_KEY), "api": bool(GOONG_API_KEY)},
        "ai_provider": ai.provider(),
        "flags": flags.describe(),
        "tide": {k: tide_meta()[k] for k in ("station", "bulletin", "issued_at", "source_url", "alarm_levels_m", "note")},
        "demo_center": DEMO_CENTER,
        "presets": [{**p, "lat": _way_mid(p["way_id"])[0], "lon": _way_mid(p["way_id"])[1]} for p in PRESETS],
        "personas": [
            {"id": "park", "label": "Tự lái, cần chỗ đỗ", "enabled": True},
            {"id": "pickup", "label": "Xe công nghệ đón/trả khách", "enabled": True},
            {"id": "emergency", "label": "Xe cứu hỏa / cứu thương", "enabled": False, "note": "Sắp có"},
        ],
        # Booleans only: never the secret or a session id.
        "operator": {"available": auth.available(), "signed_in": auth.is_operator(request)},
    }


@app.get("/api/vehicles")
def list_vehicles():
    ps = vehicles.all_profiles()
    return {"classes": [p.to_json() for p in ps.values() if p.kind == "class"],
            "models": sorted([p.to_json() for p in ps.values() if p.kind == "model"], key=lambda x: x["label"])}


@lru_cache(maxsize=256)
def _maneuver_result(vehicle_id: str, width_cm: int) -> dict:
    profile = vehicles.get_profile(vehicle_id)
    if profile.kind == "class":
        # The width requirement is based on the worst member; simulate that actual member rather than a
        # synthetic profile assembled from several different cars.
        profile = max(vehicles._members(vehicle_id), key=lambda member: vehicles.three_point_width(member.id))
    width = width_cm / 100
    moves, length, poses = geometry.k_turn_path(
        profile.body_width, profile.length, profile.wheelbase, profile.turning_radius,
        width, c=SIDE_CLEARANCE_M, T=profile.track,
    )
    return {
        "vehicle_id": vehicle_id,
        "simulated_vehicle_label": profile.label,
        "width_m": width,
        "vehicle_length_m": round(profile.length, 2),
        "vehicle_mirror_width_m": round(profile.mirror_width, 2),
        "body_center_offset_m": round(geometry.body_center_offset(profile.length, profile.wheelbase), 4),
        "moves": moves,
        "length_m": round(length, 2) if length is not None else None,
        "poses": [[round(x, 4), round(y, 4), round(heading, 5)] for x, y, heading in poses]
        if moves is not None else None,
        "frame": "corridor",
    }


@app.get("/api/vehicles/{vehicle_id}/maneuver")
def vehicle_maneuver(vehicle_id: Annotated[str, Field(max_length=80)],
                     width: Annotated[float, Field(ge=1.5, le=15, allow_inf_nan=False)]):
    try:
        return _maneuver_result(vehicle_id, round(width * 100))
    except KeyError:
        raise HTTPException(404, f"unknown vehicle {vehicle_id}")


@app.get("/api/search")
def search(q: Annotated[str, Field(max_length=200)], lat: Lat | None = None, lon: Lon | None = None):
    """Goong place search (all of Vietnam) ranked around the given point, plus alley names from the street
    graph of that area when it is already loaded (Goong often does not know small alleys by name)."""
    near = (lat, lon) if lat is not None and lon is not None else DEMO_CENTER
    q_norm = strip_accents(q)
    goong, alleys = [], []
    try:
        if GOONG_API_KEY:
            r = httpx.get("https://rsapi.goong.io/v2/place/autocomplete",
                          params={"api_key": GOONG_API_KEY, "input": q, "location": f"{near[0]},{near[1]}",
                                  "limit": 7}, timeout=10)
            for p in r.json().get("predictions", []):
                desc = p.get("description") or ""
                if strip_accents("Hồ Chí Minh") not in strip_accents(desc):
                    continue  # HCMC only (D30)
                goong.append({"label": desc, "place_id": p.get("place_id"), "source": "Goong"})
        else:
            r = httpx.get("https://nominatim.openstreetmap.org/search",
                          params={"q": q, "format": "jsonv2", "limit": 7, "countrycodes": "vn",
                                  "viewbox": "106.30,11.20,107.10,10.35", "bounded": 1},
                          headers={"User-Agent": "VaoDuoc-hackathon/0.3"}, timeout=10)
            for p in r.json():
                goong.append({"label": p["display_name"], "lat": float(p["lat"]), "lon": float(p["lon"]),
                              "source": "Nominatim"})
    except Exception:
        pass
    g = cached_graph(*near)
    if g and len(q_norm) >= 3:
        seen = set()
        for w in g.ways.values():
            if w.name and w.is_alley and q_norm in strip_accents(w.name) and w.name not in seen:
                seen.add(w.name)
                la, lo = g.nodes[w.nodes[len(w.nodes) // 2]]
                alleys.append({"label": w.name, "lat": la, "lon": lo, "source": "Tên hẻm (OSM)"})
                if len(alleys) >= 3:
                    break
    # Goong first; alley names fill in what Goong does not know.
    return {"results": (goong[:7] + alleys)[:10]}


@app.get("/api/place/{place_id}")
def place(place_id: Annotated[str, Field(max_length=300)]):
    if not GOONG_API_KEY:
        raise HTTPException(424, "Chưa có GOONG_API_KEY")
    r = httpx.get("https://rsapi.goong.io/v2/place/detail", params={"api_key": GOONG_API_KEY, "place_id": place_id},
                  timeout=10).json()
    loc = r["result"]["geometry"]["location"]
    return {"lat": loc["lat"], "lon": loc["lng"], "label": r["result"].get("formatted_address") or r["result"].get("name")}


def _require_iso_datetime_string(value: object) -> object:
    if value is not None and not isinstance(value, str):
        raise ValueError("must be an ISO 8601 string with a timezone")
    return value


class RainSpell(Strict):
    start: AwareDatetime
    end: AwareDatetime
    mm_per_h: Annotated[float, Field(ge=0, le=300, allow_inf_nan=False)]

    @field_validator("start", "end", mode="before")
    @classmethod
    def must_be_string(cls, value: object) -> object:
        return _require_iso_datetime_string(value)

    def as_dict(self) -> dict:
        if self.end <= self.start:
            raise HTTPException(422, "rain: end must be after start")
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "mm_per_h": self.mm_per_h}


Rain = Annotated[list[RainSpell], Field(max_length=24)]


class PlanRequest(Strict):
    lat: Lat
    lon: Lon
    label: Annotated[str, Field(max_length=300)] = ""
    vehicle_id: Annotated[str, Field(max_length=80)]
    intent: Literal["park", "pickup"] = "park"
    arrive_at: AwareDatetime | None = None
    dwell_min: DurationMinutes | None = None
    rain: Rain = []
    origin: Annotated[list[Annotated[float, Field(allow_inf_nan=False)]], Field(min_length=2, max_length=2)] | None = None

    @field_validator("arrive_at", mode="before")
    @classmethod
    def arrive_at_must_be_string(cls, value: object) -> object:
        return _require_iso_datetime_string(value)


@app.post("/api/plan")
def make_plan(req: PlanRequest, request: Request):
    if not in_hcmc(req.lat, req.lon):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ điểm đến trong TP.HCM.")
    try:
        vehicles.get_profile(req.vehicle_id)
    except KeyError:
        raise HTTPException(404, f"unknown vehicle {req.vehicle_id}")
    origin = tuple(req.origin) if req.origin else None
    if origin and not in_hcmc(*origin):
        raise HTTPException(422, "Điểm đi phải ở TP.HCM.")
    live_area, area = live.area_status(req.lat, req.lon)
    result = plan.plan(req.lat, req.lon, req.vehicle_id, req.intent, req.arrive_at, req.dwell_min,
                       [r.as_dict() for r in req.rain], req.label, origin=origin, live_area=live_area)
    result["origin"] = {"lat": origin[0], "lon": origin[1]} if origin else None
    result["area_key"] = area["key"]
    result["area"] = area
    result["area_data"] = live.public_area(live_area)
    result["live_crawl"] = flags.enabled("live_crawl")
    return result


@app.get("/api/reverse")
def reverse(lat: Lat, lon: Lon):
    """Address for a point (Goong reverse geocoding), used for "Vị trí của tôi" and map clicks."""
    if GOONG_API_KEY:
        try:
            r = httpx.get("https://rsapi.goong.io/Geocode", params={"latlng": f"{lat},{lon}", "api_key": GOONG_API_KEY},
                          timeout=10).json()
            if r.get("results"):
                return {"label": r["results"][0]["formatted_address"], "source": "Goong"}
        except Exception:
            pass
    return {"label": f"{lat:.5f}, {lon:.5f}", "source": "toạ độ"}


@app.get("/api/tide")
def tide(start: str | None = None, hours: Annotated[int, Field(gt=0, le=168)] = 48):
    try:
        t0 = datetime.fromisoformat(start) if start else datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(422, "start must be an ISO 8601 datetime")
    live_tide = hydro.tide_status() if flags.enabled("live_hydro") else None
    return {"series": tide_series(t0, hours), "alarm_levels_m": tide_meta()["alarm_levels_m"],
            "station": tide_meta()["station"], "source_url": (live_tide or {}).get("source_url") or tide_meta()["source_url"],
            "readings": (live_tide or {}).get("readings", []), "last_reading": (live_tide or {}).get("last_reading"),
            "model_err_m": (live_tide or {}).get("model_err_m")}


class WayQuery(Strict):
    lat: Lat
    lon: Lon


@app.post("/api/evidence/way/{way_id}")
def evidence_for_way(way_id: WayId, req: WayQuery):
    if not in_hcmc(req.lat, req.lon):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ TP.HCM.")
    live_area, _ = live.area_status(req.lat, req.lon)
    try:
        out = plan.way_evidence(req.lat, req.lon, way_id, live_area)
    except KeyError:
        raise HTTPException(404, "way not in area")
    photos = (live.public_area(live_area) or {}).get("photos", [])
    out["photos"] = [p for p in photos if p.get("way_id") == way_id and p.get("shows_alley")]
    return out


# ---- live area builds (operator schedules, everyone reads) ---------------------------------

class Point(Strict):
    lat: Lat
    lon: Lon


@app.post("/api/area/build", status_code=202)
def area_build(req: Point, _op: Operator):
    if not in_hcmc(req.lat, req.lon):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ TP.HCM.")
    if not flags.enabled("live_crawl"):
        raise HTTPException(409, "Thu thập dữ liệu trực tiếp đang tắt")
    try:
        return live.schedule(req.lat, req.lon)
    except live.Busy as exc:
        raise HTTPException(429, "Đang có quá nhiều lần thu thập, thử lại sau",
                            headers={"Retry-After": str(exc.retry_after)})


@app.get("/api/area/build/{key}")
def area_build_status(key: str):
    if not live.KEY_RE.match(key):
        raise HTTPException(422, "invalid area key")
    job = live.job_status(key)
    if job is None:
        raise HTTPException(404, "Không có lần thu thập nào đang chạy cho khu vực này")
    return job


class PhotoReview(Strict):
    approve: bool


@app.post("/api/photo/{photo_id}/review")
def review_photo(photo_id: str, req: PhotoReview, reviewer: Operator):
    if not JOB_ID.match(photo_id):
        raise HTTPException(422, "invalid photo id")
    rec = live.review_photo(photo_id, req.approve, reviewer)
    plan.invalidate_evidence()
    return rec


@app.post("/api/evidence/reload")
def reload_evidence(_op: Operator):
    STORE_EVIDENCE.reload()
    plan.invalidate_evidence()
    return {"ok": True}


# ---- community reports (guest submits, operator reviews) ----------------------------------

def _graph_with(lat: float, lon: float, way_ids: list[int]):
    if not in_hcmc(lat, lon):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ TP.HCM.")
    g = cached_graph(lat, lon)
    if g is None:
        raise HTTPException(422, "Khu vực này chưa có bản đồ trên máy chủ")
    missing = [w for w in way_ids if w not in g.ways]
    if missing:
        raise HTTPException(422, f"Đoạn đường không thuộc khu vực: {missing[:3]}")
    return g


def _guest_limit(request: Request, bucket: str = "reports") -> None:
    try:
        reports.allow_guest(request.client.host if request.client else "?", bucket=bucket)
    except reports.RateLimited:
        raise HTTPException(429, "Bạn đã gửi quá nhiều báo cáo, thử lại sau", headers={"Retry-After": "600"})


class Confirmation(Strict):
    stop_lat: Lat
    stop_lon: Lon
    vehicle_id: Annotated[str, Field(max_length=80)]
    result: Literal["in", "tight", "no"]
    exit: Literal["through", "turned", "reversed", "unknown"] = "unknown"


@app.post("/api/confirm", status_code=202)
def confirm(c: Confirmation, request: Request):
    try:
        p = vehicles.get_profile(c.vehicle_id)
    except KeyError:
        raise HTTPException(404, f"unknown vehicle {c.vehicle_id}")
    if not in_hcmc(c.stop_lat, c.stop_lon):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ TP.HCM.")
    _guest_limit(request)
    g = cached_graph(c.stop_lat, c.stop_lon)
    if g is None:
        raise HTTPException(422, "Khu vực này chưa có bản đồ trên máy chủ")
    ingress_path = parcels.path_into(g, c.stop_lat, c.stop_lon)
    if not ingress_path:
        raise HTTPException(422, "Xác nhận chỉ dành cho hẻm được máy chủ ánh xạ. Để báo cáo vật cản, vui lòng chọn loại báo cáo khác.")
    stop_way_id = ingress_path[-1][0]
    stop_projection = ingress_path[-1][1][-1]
    if not g.ways[stop_way_id].is_alley or haversine(c.stop_lat, c.stop_lon, *stop_projection) > plan.WALK_SNAP_M:
        raise HTTPException(422, "Chỉ xác nhận điểm dừng được ánh xạ trực tiếp lên hẻm (cách đường ≤ 5 m); bãi đỗ hoặc đường không phải hẻm không tạo bằng chứng.")
    way_out_ids = list(dict.fromkeys(way_id for way_id, _ in parcels.path_out(g, c.stop_lat, c.stop_lon)))
    way_ids = [stop_way_id]
    payload = {
        "date": date.today().isoformat(), "vehicle_id": p.id, "vehicle_label": p.label,
        "body_width": vehicles.min_body_width(p.id), "mirror_width": p.mirror_width,
        "result": c.result, "exit": c.exit, "way_ids": way_ids, "way_out_ids": way_out_ids,
        "stop_lat": c.stop_lat, "stop_lon": c.stop_lon,
    }
    rec = reports.submit("confirmation", payload, "Tài xế xác nhận sau khi đến")
    return {"status": "pending", "report_id": rec["report_id"]}


class VoiceParse(Strict):
    text: Annotated[str, Field(min_length=1, max_length=300)]


@app.post("/api/voice/parse")
def parse_voice_report(body: VoiceParse, request: Request):
    from time import monotonic
    _guest_limit(request, bucket="voice_parse")
    deadline = monotonic() + 10
    try:
        return ai.parse_voice_report(body.text, deadline=deadline)
    except ai.FeatureOff as exc:
        raise HTTPException(403, f"Tính năng AI '{exc}' đang tắt")
    except (ai.NoModel, budget.OverBudget, Expired, httpx.HTTPError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return {"kind": "unclear", "question": "Không nhận diện được. Hãy chọn loại báo cáo thủ công."}


class Blockage(Strict):
    lat: Lat
    lon: Lon
    way_id: WayId
    reason: Annotated[str, Field(min_length=1, max_length=200)]


@app.post("/api/blockage", status_code=202)
def blockage(b: Blockage, request: Request):
    _guest_limit(request)
    _graph_with(b.lat, b.lon, [b.way_id])
    payload = {"way_id": b.way_id, "reason": b.reason, "source": "Tài xế báo", "date": date.today().isoformat()}
    rec = reports.submit("blockage", payload, "Tài xế báo vật cản")
    return {"status": "pending", "report_id": rec["report_id"]}


@app.get("/api/reports")
def list_reports(_op: Operator, status: Literal["pending", "approved", "rejected", "expired"] | None = None,
                 cursor: str | None = None, limit: Annotated[int, Field(gt=0, le=100)] = 50):
    if cursor is not None and not REPORT_ID.match(cursor):
        raise HTTPException(422, "invalid cursor")
    return reports.list_reports(status, cursor, limit)


class Decision(Strict):
    approve: bool
    revision: Annotated[int, Field(gt=0)] | None = None


@app.post("/api/reports/{report_id}")
def decide_report(report_id: str, d: Decision, reviewer: Operator):
    if not REPORT_ID.match(report_id):
        raise HTTPException(422, "invalid report id")
    try:
        rec = reports.decide(report_id, d.approve, reviewer, d.revision)
    except KeyError:
        raise HTTPException(404, "Không có báo cáo này")
    except reports.Conflict as exc:
        raise HTTPException(409, str(exc))
    if d.approve:
        STORE_EVIDENCE.reload()
        plan.invalidate_evidence()
    return rec


# ---- flags and AI (operator) ------------------------------------------------------------

class FlagUpdate(Strict):
    name: Annotated[str, Field(max_length=60)]
    enabled: bool


@app.get("/api/flags")
def get_flags():
    return {"flags": flags.describe()}


@app.post("/api/flags")
def update_flag(f: FlagUpdate, _op: Operator):
    try:
        flags.set_flag(f.name, f.enabled)
    except KeyError:
        raise HTTPException(404, f.name)
    return {"flags": flags.describe()}


def _ai_guard(fn, *args):
    try:
        return fn(*args)
    except ai.FeatureOff as exc:
        raise HTTPException(403, f"Tính năng AI '{exc}' đang tắt")
    except ai.NoModel as exc:
        raise HTTPException(424, str(exc))
    except budget.OverBudget as exc:
        raise HTTPException(429, f"Dừng để không tốn phí: {exc}")


class TextIn(Strict):
    text: Annotated[str, Field(min_length=1, max_length=12000)]
    source: Annotated[str, Field(max_length=300)] = ""


@app.post("/api/ai/text")
def ai_text(t: TextIn, _op: Operator):
    return _ai_guard(ai.extract_text, t.text, t.source)


def _sniff(head: bytes) -> str | None:
    for magic, mime in PHOTO_MAGIC:
        if head.startswith(magic):
            return mime
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    return None


@app.post("/api/ai/photo")
async def ai_photo(_op: Operator, file: UploadFile = File(...),
                   lat: Annotated[float | None, Form(ge=-90, le=90, allow_inf_nan=False)] = None,
                   lon: Annotated[float | None, Form(ge=-180, le=180, allow_inf_nan=False)] = None,
                   way_id: Annotated[int | None, Form(gt=0)] = None):
    data = await file.read(MAX_PHOTO_BYTES + 1)  # capped read: never pull an unbounded upload into memory
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "Ảnh lớn hơn 8 MiB")
    mime = _sniff(data[:16])
    if mime is None:
        raise HTTPException(415, "Chỉ nhận ảnh JPEG, PNG hoặc WebP")
    # The model call is blocking network I/O: run it off the event loop.
    return await run_in_threadpool(_ai_guard, ai.read_photo, data, mime, lat, lon, way_id)


# ---- cameras -------------------------------------------------------------------------------

@app.get("/api/cameras")
def list_cameras():
    """Every public HCMC traffic camera, with its latest reading when one is cached."""
    reg = cameras.registry()
    return {"source": reg["source"], "portal": cameras.PORTAL_URL, "reading": flags.enabled("ai_camera_flood"),
            "cameras": [{**c, "reading": (r := cameras.latest(c["id"])) and cameras.public(r)} for c in reg["cameras"]]}


@app.get("/api/cameras/{cam_id}.jpg")
def camera_image(cam_id: str):
    if cam_id not in cameras.by_id():
        raise HTTPException(404, "unknown camera")
    img = cameras.snapshot(cam_id)
    if img is None:
        raise HTTPException(404, "Camera đang mất tín hiệu")
    return Response(img, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.post("/api/cameras/{cam_id}/read")
def camera_read(cam_id: str, request: Request, response: Response):
    """A fresh cached reading now; otherwise (operator only) a background job to poll."""
    if cam_id not in cameras.by_id():
        raise HTTPException(404, "unknown camera")
    hit = cameras.cached([cam_id]).get(cam_id)
    if hit:
        return {"state": "ready", "reading": hit, "job": None}
    auth.require_operator(request)
    try:
        job = cameras.schedule([cam_id])
    except cameras.FeatureOff as exc:
        raise HTTPException(403, f"Tính năng AI '{exc}' đang tắt")
    except cameras.Busy as exc:
        raise HTTPException(429, "Hàng đợi đọc camera đang đầy", headers={"Retry-After": str(exc.retry_after)})
    response.status_code = 202
    return {"state": job["state"], "reading": None, "job": job}


@app.get("/api/camera-jobs/{job_id}")
def camera_job(job_id: str):
    if not JOB_ID.match(job_id):
        raise HTTPException(422, "invalid job id")
    job = cameras.job_view(job_id)
    if job is None:
        raise HTTPException(404, "Không có lượt đọc camera này (đã hết hạn)")
    return job


class CorridorRequest(Strict):
    origin: Annotated[list[Annotated[float, Field(allow_inf_nan=False)]], Field(min_length=2, max_length=2)]
    destination: Annotated[list[Annotated[float, Field(allow_inf_nan=False)]], Field(min_length=2, max_length=2)]
    vehicle_id: Annotated[str, Field(max_length=80)]
    depart_at: AwareDatetime | None = None
    rain: Rain = []

    @field_validator("depart_at", mode="before")
    @classmethod
    def depart_at_must_be_string(cls, value: object) -> object:
        return _require_iso_datetime_string(value)


@app.post("/api/corridor")
def route_corridor(req: CorridorRequest, request: Request):
    """Large-road route choice from A to B: flood forecast plus cached camera readings, answered immediately.
    An operator request also queues the most relevant unread cameras (see `camera_job` in the answer)."""
    if not (in_hcmc(*req.origin) and in_hcmc(*req.destination)):
        raise HTTPException(422, "Vào Được hiện chỉ hỗ trợ TP.HCM.")
    try:
        vehicles.get_profile(req.vehicle_id)
    except KeyError:
        raise HTTPException(404, f"unknown vehicle {req.vehicle_id}")
    return corridor.corridor(tuple(req.origin), tuple(req.destination), req.vehicle_id, req.depart_at,
                             [r.as_dict() for r in req.rain], schedule_cameras=auth.is_operator(request))


# ---- paid Google lookups (operator) ----------------------------------------------------------

def _lookup_guard(fn, *args):
    try:
        return fn(*args)
    except google_lookup.LookupOff as exc:
        raise HTTPException(403, f"Tra cứu Google đang tắt hoặc thiếu khóa: {exc}")
    except budget.OverBudget as exc:
        raise HTTPException(429, f"Dừng để không tốn phí: {exc}")
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Google từ chối yêu cầu ({exc.response.status_code}). Kiểm tra API đã bật cho khóa.")


def _bearing(lat1, lon1, lat2, lon2):
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


@app.get("/api/lookup/streetview")
def lookup_streetview(lat: Lat, lon: Lon, _op: Operator, way_id: WayId | None = None):
    sv = _lookup_guard(google_lookup.streetview, lat, lon)
    if sv.get("available"):
        heading = 0.0
        if way_id:
            g = build_graph(lat, lon)
            if way_id in g.ways:  # look down the alley: towards its node farthest from the camera
                far = max(g.ways[way_id].nodes, key=lambda n: haversine(sv["lat"], sv["lon"], *g.nodes[n]))
                heading = _bearing(sv["lat"], sv["lon"], *g.nodes[far])
        sv["heading"] = round(heading)
        sv["image"] = f"/api/lookup/streetview.jpg?pano={sv['pano_id']}&heading={round(heading)}"
    return sv


@app.get("/api/lookup/streetview.jpg")
def lookup_streetview_image(pano: Annotated[str, Field(max_length=200)], _op: Operator,
                            heading: Annotated[float, Field(ge=0, le=360, allow_inf_nan=False)] = 0):
    img = _lookup_guard(google_lookup.streetview_image, pano, heading)
    return Response(img, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@app.get("/api/lookup/places")
def lookup_places(lat: Lat, lon: Lon, _op: Operator):
    return {"places": _lookup_guard(google_lookup.nearby_places, lat, lon, 80)}


@app.get("/api/lookup/place/{place_id}")
def lookup_place(place_id: Annotated[str, Field(max_length=300)], _op: Operator):
    return _lookup_guard(google_lookup.place_details, place_id)


class AskIn(Strict):
    lat: Lat
    lon: Lon
    alley: Annotated[str, Field(min_length=1, max_length=200)]


@app.post("/api/lookup/ask")
def lookup_ask(a: AskIn, _op: Operator):
    return _lookup_guard(google_lookup.ask_maps, a.lat, a.lon, a.alley)


@app.get("/api/budget")
def spend_report(_op: Operator):
    return {"usage": budget.report(), "ai": budget.ai_report()}


# ---- unknown API paths and the single-page app --------------------------------------------------
# Registered last, so every real API route above wins.

@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def unknown_api(rest: str):
    return JSONResponse(status_code=404, content={"detail": "Không có API này"})


if FRONTEND_DIST.exists():
    _DIST = FRONTEND_DIST.resolve()
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path:
            target = (_DIST / path).resolve()  # follows symlinks and "..", then must stay inside dist
            if not target.is_relative_to(_DIST):
                raise HTTPException(404)
            if target.is_file():
                return FileResponse(target)
            if "." in path.rsplit("/", 1)[-1]:
                raise HTTPException(404)  # a missing asset is a 404, not the app shell
        return FileResponse(_DIST / "index.html")
