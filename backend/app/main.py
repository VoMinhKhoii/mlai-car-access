"""HTTP API for Vào Được (working name). Run: uvicorn app.main:app --reload --port 8787"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import agent, agent_budget, ai, budget, coverage, evidence_routes, flags, geocoding, google_lookup, live, plan, tide_refresh, vehicles
from .config import FRONTEND_DIST, GOONG_API_KEY, GOONG_MAPTILES_KEY, STORE, in_hcmc
from .evidence import BLOCKAGE_FILE, CONFIRM_FILE, STORE_EVIDENCE
from .flood import tide_meta, tide_series
from .osm import build_graph, haversine

VN_TZ = timezone(timedelta(hours=7))
FALLBACK_STYLE = "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json"
GOONG_STYLE = "https://tiles.goong.io/assets/goong_map_web.json?api_key={key}"
DEMO_CENTER = (10.8, 106.71)

@asynccontextmanager
async def lifespan(app):
    geocoding.initialize_name_index()
    geocoding.configure_curated(PRESETS, agent.DEMO_PLACES)
    stop, thread = tide_refresh.start_refresher()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1)


app = FastAPI(title="Ngõ Ngách API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(evidence_routes.router_for(app))  # isolated evidence-engine routes and response hooks
app.include_router(__import__("app.field_routes", fromlist=["router_for"]).router_for(app))  # isolated field kit


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

DEMO_BLOCKAGE = {"way_id": 192512291, "reason": "Rạp đám tang chiếm hết lòng hẻm", "source": "Mô phỏng (tài xế báo)",
                 "date": "demo"}


def _seed_demo() -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    existing = BLOCKAGE_FILE.read_text(encoding="utf-8") if BLOCKAGE_FILE.exists() else ""
    if '"date": "demo"' not in existing:
        with open(BLOCKAGE_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(DEMO_BLOCKAGE, ensure_ascii=False) + "\n")


_seed_demo()


@app.get("/api/config")
def config():
    return {
        "map_style": GOONG_STYLE.format(key=GOONG_MAPTILES_KEY) if GOONG_MAPTILES_KEY else FALLBACK_STYLE,
        "goong": {"tiles": bool(GOONG_MAPTILES_KEY), "api": bool(GOONG_API_KEY)},
        "ai_provider": ai.provider(),
        "flags": flags.describe(),
        "tide": {k: tide_meta()[k] for k in ("station", "bulletin", "issued_at", "source_url", "alarm_levels_m", "note")},
        "coverage": coverage.summary(),
        "demo_center": DEMO_CENTER,
        "presets": [{**p, "lat": _way_mid(p["way_id"])[0], "lon": _way_mid(p["way_id"])[1]} for p in PRESETS],
        "personas": [
            {"id": "park", "label": "Tự lái, cần chỗ đỗ", "enabled": True},
            {"id": "pickup", "label": "Xe công nghệ đón/trả khách", "enabled": True},
            {"id": "emergency", "label": "Xe cứu hỏa / cứu thương", "enabled": False, "note": "Sắp có"},
        ],
    }


@app.get("/api/vehicles")
def list_vehicles():
    ps = vehicles.all_profiles()
    return {"classes": [p.to_json() for p in ps.values() if p.kind == "class"],
            "models": sorted([p.to_json() for p in ps.values() if p.kind == "model"], key=lambda x: x["label"])}


@app.get("/api/search")
def search(q: str, lat: float | None = None, lon: float | None = None):
    near = (lat, lon) if lat is not None and lon is not None else DEMO_CENTER
    if len(q.strip()) < 3:
        return {"results": []}
    return geocoding.resolve_place(q, near, limit=10, select_nearest=False)


@app.get("/api/place/{place_id}")
def place(place_id: str):
    try:
        result = geocoding.resolve_id(place_id)
    except (httpx.HTTPError, ValueError):
        result = None
    if result:
        return result
    raise HTTPException(424, "Nguồn địa điểm tạm gián đoạn. Hãy tìm lại để dùng kết quả có tọa độ.")


class PlanRequest(BaseModel):
    lat: float
    lon: float
    label: str = ""
    vehicle_id: str
    intent: str = "park"
    arrive_at: str | None = None
    dwell_min: int | None = None
    rain: list[dict] = []
    origin: list[float] | None = None  # [lat, lon] for the Goong Standard Route
    area: dict | None = None  # result of /api/area/build, sent back by the browser


@app.post("/api/plan")
def make_plan(req: PlanRequest):
    if req.intent not in ("park", "pickup"):
        raise HTTPException(400, "intent must be park or pickup")
    if not in_hcmc(req.lat, req.lon):
        raise HTTPException(422, "Ngõ Ngách hiện chỉ hỗ trợ điểm đến trong TP.HCM.")
    try:
        vehicles.get_profile(req.vehicle_id)
    except KeyError:
        raise HTTPException(404, f"unknown vehicle {req.vehicle_id}")
    arrive = datetime.fromisoformat(req.arrive_at) if req.arrive_at else None
    key = live.apply(req.area, req.lat, req.lon)
    origin = tuple(req.origin) if req.origin and len(req.origin) == 2 else None
    result = plan.plan(req.lat, req.lon, req.vehicle_id, req.intent, arrive, req.dwell_min, req.rain, req.label,
                       origin=origin)
    result["origin"] = {"lat": origin[0], "lon": origin[1]} if origin else None
    result["area_key"] = key
    result["live_crawl"] = flags.enabled("live_crawl")
    return result


@app.get("/api/reverse")
def reverse(lat: float, lon: float):
    return geocoding.reverse(lat, lon)


@app.get("/api/tide")
def tide(start: str | None = None, hours: int = 48):
    t0 = datetime.fromisoformat(start) if start else datetime.now(VN_TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    return {"series": tide_series(t0, hours), "alarm_levels_m": tide_meta()["alarm_levels_m"],
            "station": tide_meta()["station"], "source_url": tide_meta()["source_url"]}


class WayQuery(BaseModel):
    lat: float
    lon: float
    area: dict | None = None


@app.post("/api/evidence/way/{way_id}")
def evidence_for_way(way_id: int, req: WayQuery):
    live.apply(req.area, req.lat, req.lon)
    try:
        out = plan.way_evidence(req.lat, req.lon, way_id)
    except KeyError:
        raise HTTPException(404, "way not in area")
    out["photos"] = [p for p in (req.area or {}).get("photos", []) if p.get("way_id") == way_id and p.get("shows_alley")]
    return out


class Point(BaseModel):
    lat: float
    lon: float


@app.post("/api/area/build")
def area_build(req: Point):
    if not in_hcmc(req.lat, req.lon):
        raise HTTPException(422, "Ngõ Ngách hiện chỉ hỗ trợ TP.HCM.")
    """Streams the Live Area Build as NDJSON; the last line carries the area evidence."""
    return StreamingResponse(live.build(req.lat, req.lon), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


class PhotoReview(BaseModel):
    key: str
    approve: bool


@app.post("/api/photo/{photo_id}/review")
def review_photo(photo_id: str, req: PhotoReview):
    live.review_photo(req.key, photo_id, req.approve)
    return {"ok": True}


@app.post("/api/evidence/reload")
def reload_evidence():
    STORE_EVIDENCE.reload()
    plan.invalidate_evidence()
    return {"ok": True}


class Confirmation(BaseModel):
    lat: float
    lon: float
    vehicle_id: str
    result: str  # in | tight | no
    way_ids: list[int]


@app.post("/api/confirm")
def confirm(c: Confirmation):
    p = vehicles.get_profile(c.vehicle_id)
    rec = {"date": date.today().isoformat(), "vehicle_id": p.id, "vehicle_label": p.label,
           "body_width": p.body_width, "mirror_width": p.mirror_width, "result": c.result, "way_ids": c.way_ids,
           "lat": c.lat, "lon": c.lon}
    STORE.mkdir(parents=True, exist_ok=True)
    with open(CONFIRM_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    STORE_EVIDENCE.reload()
    plan.invalidate_evidence()
    return {"ok": True, "recorded": rec}


class Blockage(BaseModel):
    way_id: int
    reason: str


@app.post("/api/blockage")
def blockage(b: Blockage):
    rec = {"way_id": b.way_id, "reason": b.reason, "source": "Tài xế báo", "date": date.today().isoformat()}
    with open(BLOCKAGE_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return {"ok": True}


class FlagUpdate(BaseModel):
    name: str
    enabled: bool


@app.get("/api/flags")
def get_flags():
    return {"flags": flags.describe()}


@app.post("/api/flags")
def update_flag(f: FlagUpdate):
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


class TextIn(BaseModel):
    text: str
    source: str = ""


@app.post("/api/ai/text")
def ai_text(t: TextIn):
    return _ai_guard(ai.extract_text, t.text, t.source)


@app.post("/api/ai/photo")
async def ai_photo(file: UploadFile = File(...), lat: float | None = Form(None), lon: float | None = Form(None),
                   way_id: int | None = Form(None)):
    data = await file.read()
    return _ai_guard(ai.read_photo, data, file.content_type or "image/jpeg", lat, lon, way_id)


class CameraIn(BaseModel):
    camera_id: str
    street: str
    lat: float
    lon: float


@app.post("/api/ai/camera")
def ai_camera(c: CameraIn):
    return _ai_guard(ai.read_camera, c.camera_id, c.street, c.lat, c.lon)


@app.get("/api/ai/review")
def ai_review():
    return {"items": ai.review_queue()}


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
    import math
    p1, p2, dl = math.radians(lat1), math.radians(lat2), math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


@app.get("/api/lookup/streetview")
def lookup_streetview(lat: float, lon: float, way_id: int | None = None):
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
def lookup_streetview_image(pano: str, heading: float = 0):
    img = _lookup_guard(google_lookup.streetview_image, pano, heading)
    return Response(img, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@app.get("/api/lookup/places")
def lookup_places(lat: float, lon: float):
    return {"places": _lookup_guard(google_lookup.nearby_places, lat, lon, 80)}


@app.get("/api/lookup/place/{place_id}")
def lookup_place(place_id: str):
    return _lookup_guard(google_lookup.place_details, place_id)


class AskIn(BaseModel):
    lat: float
    lon: float
    alley: str


@app.post("/api/lookup/ask")
def lookup_ask(a: AskIn):
    return _lookup_guard(google_lookup.ask_maps, a.lat, a.lon, a.alley)


@app.post("/api/agent")
def arrival_agent(req: agent.AgentRequest):
    return StreamingResponse(agent.stream(req), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@app.post("/api/agent/cancel/{request_id}")
def cancel_agent(request_id: str):
    agent.cancel(request_id)
    return {"cancelled": True}


@app.get("/api/agent/tools")
def agent_tools():
    return [{"name": t["name"], "description": t["description"], "inputSchema": t["parameters"]} for t in agent.TOOLS]


@app.post("/api/agent/tool/{name}")
def agent_tool(name: str, args: dict):
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    spec = spec_from_file_location("ngo_ngach_mcp", Path(__file__).resolve().parents[2] / "mcp" / "protocol.py")
    protocol = module_from_spec(spec)
    spec.loader.exec_module(protocol)
    schema = next((t["parameters"] for t in agent.TOOLS if t["name"] == name), None)
    if schema is None: raise HTTPException(404, "Công cụ không tồn tại.")
    try:
        protocol.schema_args(schema, args)
        result, _ = agent.call_tool(name, args)
        return result
    except protocol.RPCError as exc: raise HTTPException(422, exc.message)
    except Exception as exc: raise HTTPException(422, agent.safe_error(exc))


# MCP Streamable HTTP, stable 2025-11-25, stateless JSON response mode.
# GET is explicitly 405 (no unsolicited SSE stream); no dependency on the MCP SDK.
from fastapi import Request as MCPRequest


@app.api_route("/mcp", methods=["POST", "GET", "DELETE"])
async def mcp_http(request: MCPRequest):
    import hmac
    import os
    from importlib.util import module_from_spec, spec_from_file_location
    from pathlib import Path
    from fastapi.responses import JSONResponse
    from starlette.concurrency import run_in_threadpool
    origins = {"http://localhost:8787", "http://127.0.0.1:8787", "http://localhost:5173", "http://127.0.0.1:5173"}
    origins.update(x.strip() for x in os.environ.get("MCP_ALLOWED_ORIGINS", "").split(",") if x.strip())
    if request.headers.get("origin") and request.headers["origin"] not in origins:
        return JSONResponse({"error":"Origin not allowed"},status_code=403)
    token=os.environ.get("MCP_AUTH_TOKEN")
    if token and not hmac.compare_digest(request.headers.get("authorization", ""), "Bearer "+token):
        return JSONResponse({"error":"Unauthorized"},status_code=401)
    if request.method != "POST": return Response(status_code=405,headers={"Allow":"POST"})
    if "application/json" not in request.headers.get("content-type", ""):
        return JSONResponse({"error":"Content-Type must be application/json"},status_code=415)
    accept=request.headers.get("accept", "")
    if not all(t in accept for t in ("application/json","text/event-stream")):
        return JSONResponse({"error":"Accept must include application/json and text/event-stream"},status_code=406)
    spec=spec_from_file_location("ngo_ngach_mcp",Path(__file__).resolve().parents[2]/"mcp"/"protocol.py")
    protocol=module_from_spec(spec);spec.loader.exec_module(protocol)
    version=request.headers.get("mcp-protocol-version", "2025-03-26")
    if version not in protocol.VERSIONS[0:3]: return JSONResponse({"error":"Unsupported MCP protocol version"},status_code=400)
    raw=await request.body()
    if len(raw)>64_000: return JSONResponse({"error":"Request too large"},status_code=413)
    try: body=json.loads(raw)
    except (ValueError,UnicodeDecodeError):
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}},status_code=400)
    response=await run_in_threadpool(protocol.dispatch,body,agent_tools,lambda name,args:agent_tool(name,args))
    if response is None: return Response(status_code=202)
    return JSONResponse(response,headers={"Cache-Control":"no-store"})


@app.get("/api/budget")
def google_budget():
    return {"usage": budget.report(), "gemini_paid": agent_budget.report()}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = FRONTEND_DIST / path
        return FileResponse(f if path and f.is_file() else FRONTEND_DIST / "index.html")
