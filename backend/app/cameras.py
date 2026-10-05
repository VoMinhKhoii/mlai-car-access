"""Public HCMC traffic cameras → flood-now and traffic-now evidence (D34), flag `ai_camera_flood`.

Registry: the camera layer of Cổng thông tin giao thông TP.HCM, ~800 cameras with the portal's own
status (UP / NOT_IMAGE), fetched from the portal hourly the way its public map page does; the shipped
data/cameras/hcmc_cameras.json (pipelines/camera_registry.py) is the fallback. A still refreshes about every 12 s, so a reading takes two
frames a refresh apart and the vision model reads them together: queued traffic that has not
moved is seen, not guessed from one frame. Offline cameras answer a fixed placeholder image and
are never sent to the model. Every reading is logged to store/camera_readings.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import httpx

from . import ai, flags
from .config import CAMERA_READ_TTL_S, CAMERA_STALE_MIN, DATA, STORE
from .osm import haversine, strip_accents

VN_TZ = timezone(timedelta(hours=7))
REGISTRY = DATA / "cameras" / "hcmc_cameras.json"
READINGS_FILE = STORE / "camera_readings.jsonl"
SNAPSHOT_URL = "https://giaothong.hochiminhcity.gov.vn/render/ImageHandler.ashx?id={cam}&t={ms}"
PORTAL_URL = "https://giaothong.hochiminhcity.gov.vn/Map.aspx"
LAYER_URL = "https://giaothong.hochiminhcity.gov.vn/ajaxpro/VDMS.Web.Library.AJAX.FolderAjax,VDMS.Web.Library.ashx"
# The request the portal's map page sends when its "Camera" layer is switched on.
LAYER_QUERY = {"path": "/root/vdms/tangthu/data/layerdata/camera", "isInTree": False, "searchKey": "",
               "layer": ["CAMERA"], "detail": True, "page": 0, "limit": -1, "filterQuery": ["Publish:true"],
               "sortby": None, "returnFields": ["CamId", "Code", "Location", "CamType", "CamStatus"]}
REGISTRY_TTL_S = 3600
PLACEHOLDER_MD5 = "27bc56b5710fe8ddb7e6665dfd735f1e"  # "IMAGE NOT AVAILABLE", 2,638 bytes
REFRESH_S = 13
SNAP_TTL_S = 10
BATCH = 6  # cameras per model call: the free tier allows ~5 calls per minute per key
CAMERA_MODEL = os.environ.get("CAMERA_MODEL", "gemini-3.5-flash")

DEPTH_CM = {"kho": 0, "uot": 0, "duoi_15cm": 10, "15_30cm": 25, "30_50cm": 40, "tren_50cm": 60}
TRAFFIC = ("thong_thoang", "dong", "un_u", "ket_cung")
TRAFFIC_VI = {"thong_thoang": "Thông thoáng", "dong": "Đông, vẫn chạy", "un_u": "Ùn ứ", "ket_cung": "Kẹt cứng"}

PROMPT = """Ảnh tĩnh từ {n} camera giao thông TP.HCM. Mỗi camera có 1 hoặc 2 ảnh; 2 ảnh là cùng camera chụp cách
nhau ~13 giây: so sánh vị trí xe giữa hai ảnh để biết xe đang chạy hay đứng yên. Đọc từng camera độc lập.
Trả về JSON {"cameras":[...]}, mỗi camera một phần tử:
{"camera":số thứ tự camera,
 "image_time":"giờ in trên ảnh (ảnh cuối), dạng YYYY-MM-DDTHH:MM:SS, hoặc null",
 "usable":true|false,
 "flooded":true|false,
 "depth_class":"kho|uot|duoi_15cm|15_30cm|30_50cm|tren_50cm|khong_ro",
 "traffic":"thong_thoang|dong|un_u|ket_cung|khong_ro",
 "evidence":"ngắn gọn, tiếng Việt: dựa vào đâu",
 "confidence":0-1}
usable=false khi ảnh lỗi, mất tín hiệu, bị che, hoặc quá tối/mờ để thấy mặt đường.
Ngập: chỉ khi thấy nước đọng phủ mặt đường. Mặt đường ướt do mưa là "uot", không phải ngập. Ước lượng độ sâu
bằng vật tham chiếu (bánh xe máy cao ~60 cm, lề đường ~15 cm, nước tóe quanh bánh xe).
Giao thông trên lòng đường camera nhìn rõ nhất: thong_thoang = xe chạy tự do, nhiều khoảng trống;
dong = nhiều xe nhưng vẫn chạy đều; un_u = xe chen kín, nhích chậm; ket_cung = xe kín lòng đường và gần như
không di chuyển giữa hai ảnh. Đường vắng ban đêm là thong_thoang."""


class FeatureOff(Exception):
    pass


_reg: dict = {"t": 0.0, "data": None, "by_id": {}}
_reg_lock = threading.Lock()


def registry() -> dict:
    """Cameras with the portal's current status; refreshed hourly, the shipped file if the portal is down."""
    with _reg_lock:
        if time.time() - _reg["t"] > REGISTRY_TTL_S:
            _reg["t"] = time.time()  # a portal outage is retried next hour, not on every request
            try:
                _set_registry({"source": "Cổng thông tin giao thông TP.HCM (camera layer, live)",
                               "fetched_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
                               "cameras": fetch_official()})
            except Exception as exc:
                print(f"camera registry: portal unavailable ({type(exc).__name__}), using shipped file")
                if _reg["data"] is None:
                    _set_registry(json.loads(REGISTRY.read_text(encoding="utf-8")))
        return _reg["data"]


def _set_registry(data: dict) -> None:
    _reg["data"], _reg["by_id"] = data, {c["id"]: c for c in data["cameras"]}


def by_id() -> dict[str, dict]:
    registry()
    return _reg["by_id"]


def fetch_official() -> list[dict]:
    """The portal's camera layer, asked for exactly as its public map page asks (anonymous visitor session)."""
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 (VaoDuoc-hackathon)"}, timeout=60,
                      follow_redirects=True) as c:
        c.get(PORTAL_URL).raise_for_status()
        r = c.post(LAYER_URL, content=json.dumps(LAYER_QUERY),
                   headers={"Content-Type": "text/plain; charset=utf-8", "X-AjaxPro-Method": "SearchQuery"})
        r.raise_for_status()
    value = _ajaxpro_json(r.text)["value"]
    rows = next(t for t in value[1] if isinstance(t, list) and t and isinstance(t[0], list)
                and any(col[0] == "CamId" for col in t[0]))
    cams = []
    for row in _table(rows):
        point = re.match(r"POINT\(([\d.]+) ([\d.]+)\)", (_table(row["Location"]) or [{}])[0].get("Shape") or "")
        if not row.get("CamId") or not point:
            continue
        cams.append({"id": row["CamId"], "name": (row.get("DisplayName") or row.get("Title") or "").strip(),
                     "lat": round(float(point.group(2)), 7), "lon": round(float(point.group(1)), 7),
                     "code": row.get("Code") or "", "type": row.get("CamType") or "",
                     "status": row.get("CamStatus") or ""})
    if len(cams) < 100:
        raise ValueError(f"only {len(cams)} cameras")
    return cams


_DATATABLE = "new Ajax.Web.DataTable("


def _ajaxpro_json(text: str):
    """AjaxPro answers JSON with `new Ajax.Web.DataTable(cols, rows)` literals; turn those into arrays."""
    out, i, in_str, n = [], 0, False, len(text)
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\":
                out.append(text[i + 1])
                i += 2
                continue
            in_str = ch != '"'
        elif ch == '"':
            in_str = True
            out.append(ch)
        elif text.startswith(_DATATABLE, i):
            out.append("[")
            i += len(_DATATABLE)
            continue
        else:
            out.append("]" if ch == ")" else ch)
        i += 1
    return json.loads("".join(out))


def _table(dt) -> list[dict]:
    if not dt:
        return []
    names = [c[0] for c in dt[0]]
    return [dict(zip(names, r)) for r in dt[1]]


def near(lat: float, lon: float, radius_m: float) -> list[dict]:
    return [c for c in registry()["cameras"] if haversine(lat, lon, c["lat"], c["lon"]) <= radius_m]


def street_names(cam: dict) -> list[str]:
    """Normalised street names in a camera name: "Cầu Sài Gòn 2 (dạ cầu)" → ["cau sai gon"]."""
    out = []
    for part in re.split(r"\s+[-–]\s+", re.sub(r"\(.*?\)", "", cam["name"])):
        s = re.sub(r"\s+\d+$", "", strip_accents(part)).strip()
        s = re.sub(r"^(nut giao|vong xoay|duong)\s+", "", s)
        if s:
            out.append(s)
    return out


# ---- stills ---------------------------------------------------------------------

_snaps: dict[str, tuple[float, bytes | None]] = {}


def snapshot(cam_id: str, max_age_s: float = SNAP_TTL_S) -> bytes | None:
    """Current still, or None if the camera is offline (placeholder image) or unreachable."""
    hit = _snaps.get(cam_id)
    if hit and time.time() - hit[0] < max_age_s:
        return hit[1]
    if by_id().get(cam_id, {}).get("status") == "NOT_IMAGE":  # the portal itself says it has no picture
        return None
    img = None
    try:
        r = httpx.get(SNAPSHOT_URL.format(cam=cam_id, ms=int(time.time() * 1000)), timeout=12,
                      headers={"User-Agent": "Mozilla/5.0 (VaoDuoc-hackathon)"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") \
                and hashlib.md5(r.content).hexdigest() != PLACEHOLDER_MD5:
            img = r.content
    except httpx.HTTPError:
        pass
    _snaps[cam_id] = (time.time(), img)
    return img


# ---- readings -------------------------------------------------------------------

_reads: dict[str, dict] = {}
_busy = threading.Lock()  # one batch at a time per instance, so parallel requests share readings


def latest(cam_id: str) -> dict | None:
    r = _reads.get(cam_id)
    return r if r and time.time() - r["_t"] < CAMERA_READ_TTL_S else None


def read_many(cam_ids: list[str]) -> dict[str, dict]:
    """Read cameras: first frames now, second frames one refresh later, then BATCH cameras per model call.

    Readings are cached for CAMERA_READ_TTL_S; failed model calls are not cached, so the next request retries.
    """
    if not flags.enabled("ai_camera_flood"):
        raise FeatureOff("ai_camera_flood")
    ids = list(dict.fromkeys(c for c in cam_ids if c in by_id()))
    with _busy:
        todo = [c for c in ids if not latest(c)]
        if todo:
            _read_batch(todo)
    return {c: public(_reads.get(c) or {"id": c, **_where(c), "state": "error"}) for c in ids}


def _where(cam_id: str) -> dict:
    c = by_id()[cam_id]
    return {"name": c["name"], "lat": c["lat"], "lon": c["lon"]}


def _read_batch(todo: list[str]) -> None:
    now = datetime.now(VN_TZ)
    with ThreadPoolExecutor(12) as pool:
        first = dict(zip(todo, pool.map(lambda c: snapshot(c, max_age_s=0), todo)))
        t0 = time.time()
        live = [c for c in todo if first[c]]
        second: dict[str, bytes | None] = {}
        for wait in (REFRESH_S, 6):  # the next refresh, so the two frames differ
            time.sleep(max(0.0, t0 + wait - time.time()))
            t0 = time.time()
            left = [c for c in live if not second.get(c) or second[c] == first[c]]
            second.update(zip(left, pool.map(lambda c: snapshot(c, max_age_s=0), left)))
        for c in todo:
            if not first[c]:
                _store({"id": c, **_where(c), "at": now.isoformat(timespec="seconds"), "state": "offline"})
        groups = [live[i:i + BATCH] for i in range(0, len(live), BATCH)]
        list(pool.map(lambda g: _ask(g, first, second, now), groups))


def _ask(group: list[str], first: dict, second: dict, now: datetime) -> None:
    parts: list = []
    frames = {}
    for i, c in enumerate(group, 1):
        fs = [first[c]] + ([second[c]] if second.get(c) and second[c] != first[c] else [])
        frames[c] = len(fs)
        parts += [f"Camera {i}: {by_id()[c]['name']} ({len(fs)} ảnh)"] + fs
    try:
        out = ai._call(PROMPT.replace("{n}", str(len(group))), parts, model=CAMERA_MODEL)
    except ai.NoModel:
        for c in group:
            _store({"id": c, **_where(c), "at": now.isoformat(timespec="seconds"), "state": "no_model"})
        return
    except Exception as exc:  # rate limit or bad JSON: not cached, so the next request retries
        code = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
        print(f"camera batch failed: {code}")
        return
    answers = {int(a.get("camera", 0)): a for a in out.get("cameras", []) if isinstance(a, dict)}
    for i, c in enumerate(group, 1):
        a = answers.get(i)
        if a:
            _store(_record(by_id()[c], a, frames[c], now))


def _record(cam: dict, out: dict, frames: int, now: datetime) -> dict:
    rec = {"id": cam["id"], "name": cam["name"], "lat": cam["lat"], "lon": cam["lon"],
           "at": now.isoformat(timespec="seconds"), "frames": frames, "image_time": out.get("image_time"),
           "usable": bool(out.get("usable", True)), "flooded": bool(out.get("flooded")),
           "depth_class": out.get("depth_class"), "traffic": out.get("traffic"),
           "evidence": out.get("evidence"), "confidence": float(out.get("confidence") or 0),
           "model": f"gemini/{CAMERA_MODEL}" if (ai.provider() or ("",))[0] == "gemini" else "/".join(ai.provider())}
    rec["depth_cm"] = DEPTH_CM.get(rec["depth_class"]) if rec["flooded"] else 0
    rec["stale"] = _stale(rec["image_time"], now)
    rec["state"] = "ok" if rec["usable"] and not rec["stale"] else "stale" if rec["stale"] else "unusable"
    _log(cam, rec)
    return rec


def _store(rec: dict) -> None:
    rec["_t"] = time.time()
    _reads[rec["id"]] = rec


def _stale(image_time: str | None, now: datetime) -> bool:
    if not image_time:
        return False
    try:
        t = datetime.fromisoformat(image_time)
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=VN_TZ)
    return abs((now - t).total_seconds()) > CAMERA_STALE_MIN * 60


def _log(cam: dict, rec: dict) -> None:
    ai._append(READINGS_FILE, rec)
    # A flooded street becomes flood-now evidence for the Arrival Plan too, through the same review gate.
    if rec["state"] == "ok" and rec["flooded"] and rec["depth_cm"]:
        names = street_names(cam)
        flood = {"kind": "flood_report", "street": names[0] if names else cam["name"],
                 "lat": cam["lat"], "lon": cam["lon"], "camera_id": cam["id"], "depth_cm": rec["depth_cm"],
                 "observed_at": rec["at"], "confidence": rec["confidence"], "evidence": rec["evidence"],
                 "source": "camera", "streets": names}
        flood["gate"] = ai._gate(flood, ["street", "depth_cm", "observed_at"])
        ai._append(ai.REVIEW_FILE, flood)
        if flood["gate"] == "ACCEPT":
            ai._append(ai.LIVE_FLOOD_FILE, flood)


def public(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    out["image_url"] = f"/api/cameras/{rec['id']}.jpg"
    if out.get("traffic") in TRAFFIC_VI:
        out["traffic_vi"] = TRAFFIC_VI[out["traffic"]]
    return out
