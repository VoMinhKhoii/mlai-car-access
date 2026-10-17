"""Public HCMC traffic cameras → flood-now and traffic-now evidence (D34), flag `ai_camera_flood`.

Registry: the camera layer of Cổng thông tin giao thông TP.HCM, ~800 cameras with the portal's own
status (UP / NOT_IMAGE), fetched from the portal hourly the way its public map page does; the shipped
data/cameras/hcmc_cameras.json (pipelines/camera_registry.py) is the fallback. A job aims for two frames about 13 s apart.
When its deadline cannot cover another refresh, one frame may still provide a flood observation, but traffic is forced
unknown because a still cannot establish movement. The stored frame count is shown to the user. Offline cameras answer
a fixed placeholder image and are never sent to the model; every reading is logged to store/camera_readings.jsonl.
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
from .deadline import Expired, timeout
from .config import CAMERA_READ_TTL_S, CAMERA_STALE_MIN, DATA, STORE, CACHED_ONLY
from .storage import CorruptState, read_json, write_json
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
# Each model has its own free daily quota (only 20 requests per key for gemini-3.5-flash): when one answers 429
# on every key it rests REST_S and the next one reads. Quality order, from the model check in D34.
CAMERA_MODELS = [m.strip() for m in os.environ.get(
    "CAMERA_MODELS", "gemini-3.5-flash,gemini-3.1-flash-lite").split(",") if m.strip()]
REST_S = 600
_resting: dict[str, float] = {}

DEPTH_CM = {"kho": 0, "uot": 0, "duoi_15cm": 10, "15_30cm": 25, "30_50cm": 40, "tren_50cm": 60}
TRAFFIC = ("thong_thoang", "dong", "un_u", "ket_cung")
TRAFFIC_VI = {"thong_thoang": "Free-flowing", "dong": "Busy, moving", "un_u": "Congested",
              "ket_cung": "Gridlocked", "khong_ro": "Unknown"}

PROMPT = """Ảnh tĩnh từ {n} camera giao thông TP.HCM. Mỗi camera có 1 hoặc 2 ảnh; 2 ảnh là cùng camera chụp cách
nhau ~13 giây: so sánh vị trí xe giữa hai ảnh để biết xe đang chạy hay đứng yên. Đọc từng camera độc lập.
Trả về JSON {"cameras":[...]}, mỗi camera một phần tử:
{"camera":số thứ tự camera,
 "image_time":"giờ in trên ảnh (ảnh cuối), dạng YYYY-MM-DDTHH:MM:SS, hoặc null",
 "usable":true|false,
 "flooded":true|false,
 "depth_class":"kho|uot|duoi_15cm|15_30cm|30_50cm|tren_50cm|khong_ro",
 "traffic":"thong_thoang|dong|un_u|ket_cung|khong_ro",
 "evidence":"brief English explanation of the visible evidence",
 "confidence":0-1}
usable=false khi ảnh lỗi, mất tín hiệu, bị che, hoặc quá tối/mờ để thấy mặt đường.
Ngập: chỉ khi thấy nước đọng phủ mặt đường. Mặt đường ướt do mưa là "uot", không phải ngập. Ước lượng độ sâu
bằng vật tham chiếu (bánh xe máy cao ~60 cm, lề đường ~15 cm, nước tóe quanh bánh xe).
Giao thông trên lòng đường camera nhìn rõ nhất: thong_thoang = xe chạy tự do, nhiều khoảng trống;
dong = nhiều xe nhưng vẫn chạy đều; un_u = xe chen kín, nhích chậm; ket_cung = xe kín lòng đường và gần như
không di chuyển giữa hai ảnh. Một ảnh không xác định được chuyển động: bắt buộc traffic="khong_ro", nhưng vẫn
đánh giá ngập từ ảnh đó. Đường vắng ban đêm là thong_thoang. Nếu hai chiều đường khác nhau, đánh giá theo chiều
kẹt hơn và nói rõ chiều nào trong evidence."""


class FeatureOff(Exception):
    pass


_reg: dict = {"t": 0.0, "data": None, "by_id": {}, "pending": False}
_reg_lock = threading.Lock()
_registry_pool = ThreadPoolExecutor(1, thread_name_prefix="camera-registry")


def registry(deadline: float | None = None) -> dict:
    """Return the published registry, scheduling an hourly refresh only for no-deadline readers."""
    submit = False
    previous_attempt = 0.0
    with _reg_lock:
        _seed_registry_locked()
        now = time.time()
        if not CACHED_ONLY and deadline is None and not _reg["pending"] and now - _reg["t"] > REGISTRY_TTL_S:
            previous_attempt = _reg["t"]
            _reg["t"] = now
            _reg["pending"] = True
            submit = True
        data = _reg["data"]
    if submit:
        try:
            _registry_pool.submit(_refresh_registry)
        except RuntimeError as exc:
            with _reg_lock:
                _reg["pending"] = False
                _reg["t"] = previous_attempt
            print(f"camera registry: refresh unavailable ({type(exc).__name__}), using published registry")
    return data


def _seed_registry_locked() -> None:
    if _reg["data"] is None:
        _set_registry_locked(json.loads(REGISTRY.read_text(encoding="utf-8")))


def _set_registry_locked(data: dict) -> None:
    _reg["data"], _reg["by_id"] = data, {c["id"]: c for c in data["cameras"]}


def _refresh_registry() -> None:
    try:
        cameras = fetch_official()
        data = {"source": "HCMC Traffic Portal (camera layer, live)",
                "fetched_at": datetime.now(VN_TZ).isoformat(timespec="seconds"),
                "cameras": cameras}
        with _reg_lock:
            _set_registry_locked(data)
            _reg["t"] = time.time()
    except Exception as exc:
        print(f"camera registry: portal unavailable ({type(exc).__name__}), using published registry")
    finally:
        with _reg_lock:
            _reg["pending"] = False








def by_id(deadline: float | None = None) -> dict[str, dict]:
    registry(deadline)
    with _reg_lock:
        return _reg["by_id"]


def _cached_by_id() -> dict[str, dict]:
    """Current in-memory registry, or the shipped registry, without scheduling a portal request."""
    with _reg_lock:
        _seed_registry_locked()
        return _reg["by_id"]


def fetch_official(deadline: float | None = None) -> list[dict]:
    """The portal's camera layer, asked for exactly as its public map page asks (anonymous visitor session)."""
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0 (VaoDuoc-hackathon)"},
                      follow_redirects=True) as c:
        c.get(PORTAL_URL, timeout=timeout(deadline, 60)).raise_for_status()
        r = c.post(LAYER_URL, content=json.dumps(LAYER_QUERY),
                   headers={"Content-Type": "text/plain; charset=utf-8", "X-AjaxPro-Method": "SearchQuery"},
                   timeout=timeout(deadline, 60))
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


def snapshot(cam_id: str, max_age_s: float = SNAP_TTL_S, *, deadline: float | None = None) -> bytes | None:
    """Current still, or None if the camera is offline (placeholder image) or unreachable."""
    hit = _snaps.get(cam_id)
    if hit and time.time() - hit[0] < max_age_s:
        return hit[1]
    if CACHED_ONLY:
        return hit[1] if hit else None
    timeout(deadline, 12)
    cameras = by_id(deadline)
    if cameras.get(cam_id, {}).get("status") == "NOT_IMAGE":  # the portal itself says it has no picture
        return None
    img = None
    try:
        r = httpx.get(SNAPSHOT_URL.format(cam=cam_id, ms=int(time.time() * 1000)),
                      timeout=timeout(deadline, 12),
                      headers={"User-Agent": "Mozilla/5.0 (VaoDuoc-hackathon)"})
        if r.status_code == 200 and r.headers.get("content-type", "").startswith("image/") \
                and hashlib.md5(r.content).hexdigest() != PLACEHOLDER_MD5:
            img = r.content
    except httpx.HTTPError:
        pass
    _snaps[cam_id] = (time.time(), img)
    return img


# ---- readings and jobs ------------------------------------------------------------
#
# A reading normally uses two stills ~13 s apart. If the job deadline cannot cover another refresh, one still may be
# used for flood observation only; traffic is forced unknown because one frame cannot show movement. This work runs
# in bounded jobs, never inside the route request. An operator queues at most MAX_JOB_CAMERAS cameras;
# MAX_ACTIVE_JOBS run at once, MAX_QUEUED_CAMERAS wait, and a camera already being read is coalesced.

MAX_JOB_CAMERAS = 12
MAX_ACTIVE_JOBS = 2
MAX_QUEUED_CAMERAS = 24
JOB_TTL_S = 300
JOBS_FILE = STORE / "camera_jobs.json"

_reads: dict[str, dict] = {}
_state = threading.Lock()
_inflight: dict[str, threading.Event] = {}
_jobs: dict[str, dict] = {}
_job_pool = ThreadPoolExecutor(MAX_ACTIVE_JOBS, thread_name_prefix="camera-job")
_restored = False


class Busy(Exception):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"retry after {retry_after}s")
        self.retry_after = retry_after


def _restore() -> None:
    """After a restart: recent readings come back from the log; jobs that were running are interrupted."""
    global _restored
    if _restored:
        return
    _restored = True
    if READINGS_FILE.exists():
        now = datetime.now(VN_TZ)
        for line in READINGS_FILE.read_text(encoding="utf-8").splitlines()[-500:]:
            try:
                rec = json.loads(line)
                age = (now - datetime.fromisoformat(rec["at"])).total_seconds()
            except (ValueError, KeyError, TypeError):
                continue
            if 0 <= age < CAMERA_READ_TTL_S and rec.get("id"):
                rec.setdefault("frames", None)
                if rec.get("state") == "ok" and (not isinstance(rec["frames"], int) or rec["frames"] < 2):
                    rec["traffic"] = "khong_ro"
                rec["_t"] = time.time() - age
                _reads[rec["id"]] = rec
    try:
        saved = read_json(JOBS_FILE, {})
    except CorruptState:
        saved = {}
    for jid, job in saved.items():
        if job.get("state") in ("queued", "running"):
            job.update(state="interrupted", error="Server restarted during camera reading")
        _jobs[jid] = job


def _persist() -> None:
    write_json(JOBS_FILE, {jid: {k: v for k, v in j.items() if not k.startswith("_")} for jid, j in _jobs.items()})


def latest(cam_id: str) -> dict | None:
    r = _reads.get(cam_id)
    return r if r and time.time() - r["_t"] < CAMERA_READ_TTL_S else None


def cached(cam_ids: list[str]) -> dict[str, dict]:
    """Readings that are still fresh, for the cameras that have one."""
    return {c: public(r) for c in dict.fromkeys(cam_ids) if (r := latest(c))}


def schedule(cam_ids: list[str]) -> dict:
    """Queue one reading job for up to MAX_JOB_CAMERAS cameras. Raises FeatureOff or Busy."""
    if not flags.enabled("ai_camera_flood"):
        raise FeatureOff("ai_camera_flood")
    available = _cached_by_id()
    ids = [c for c in dict.fromkeys(cam_ids) if c in available][:MAX_JOB_CAMERAS]
    now = datetime.now(VN_TZ)
    with _state:
        if _expire(now):
            _persist()
        waiting = sum(len(j["cameras"]) for j in _jobs.values()
                      if j.get("_worker_pending") and not j.get("_worker_started"))
        if waiting + len(ids) > MAX_QUEUED_CAMERAS:
            raise Busy(retry_after=30)
        jid = hashlib.sha1(f"{now.isoformat()}:{','.join(ids)}:{os.urandom(4).hex()}".encode()).hexdigest()[:12]
        job = {"id": jid, "state": "queued", "cameras": ids, "created_at": now.isoformat(timespec="seconds"),
               "expires_at": (now + timedelta(seconds=JOB_TTL_S)).isoformat(timespec="seconds"),
               "finished_at": None, "error": None, "_deadline": time.monotonic() + JOB_TTL_S,
               "_worker_pending": True, "_worker_started": False}
        _jobs[jid] = job
        try:
            _persist()
        except Exception:
            _jobs.pop(jid, None)
            raise
    try:
        _job_pool.submit(_run_job, jid)
    except RuntimeError as exc:
        with _state:
            _jobs.pop(jid, None)
            _persist()
        raise Busy(retry_after=30) from exc
    return job_view(jid)


def _expire(now: datetime) -> bool:
    changed = False
    for jid in list(_jobs):
        job = _jobs[jid]
        if datetime.fromisoformat(job["expires_at"]) <= now:
            if job["state"] in ("queued", "running"):
                job["state"], job["error"] = "expired", "Camera reading deadline exceeded"
                changed = True
            elif job["state"] in ("ready", "error", "interrupted", "expired"):
                if (now - datetime.fromisoformat(job["expires_at"])).total_seconds() > JOB_TTL_S \
                        and not job.get("_worker_pending"):
                    del _jobs[jid]  # forgotten one TTL after expiry, never while its worker still occupies capacity
                    changed = True
                elif job["state"] == "ready":
                    job["state"] = "expired"
                    changed = True
    return changed


def _run_job(jid: str) -> None:
    with _state:
        job = _jobs[jid]
        job["_worker_started"] = True
        deadline = job["_deadline"]
        already_expired = job["state"] == "expired" or time.monotonic() >= deadline
        if already_expired:
            job["state"], job["error"] = "expired", "Camera reading deadline exceeded"
            mine, theirs = [], []
        else:
            job["state"] = "running"
            mine, theirs = [], []
            for c in job["cameras"]:
                if latest(c):
                    continue
                if c in _inflight:
                    theirs.append(_inflight[c])
                else:
                    _inflight[c] = threading.Event()
                    mine.append(c)
        try:
            _persist()
        except Exception as exc:
            job["state"], job["error"] = "error", f"Could not save camera state ({type(exc).__name__})"
            job["finished_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
            job["_worker_pending"] = False
            job["_finished"] = time.monotonic()
            for cam_id in mine:
                event = _inflight.pop(cam_id, None)
                if event is not None:
                    event.set()
            return
    expired, failure = already_expired, None
    try:
        if mine:
            _read_batch(mine, deadline=deadline)
    except Expired:
        expired = True
    except Exception as exc:  # the job fails; the cameras stay unread (unknown), never "clear"
        failure = f"{type(exc).__name__}"
    finally:
        with _state:
            for c in mine:
                _inflight.pop(c).set()
    if not expired:
        for ev in theirs:
            try:
                ev.wait(timeout=timeout(deadline, 90))
            except Expired:
                expired = True
                break
    with _state:
        expired = expired or job["state"] == "expired" or time.monotonic() >= deadline
        read = [c for c in job["cameras"] if latest(c)]
        if expired:
            job["state"], job["error"] = "expired", "Camera reading deadline exceeded"
        else:
            job["state"] = "ready" if read else "error"
            job["error"] = failure or (None if read else "No cameras could be read (offline or AI quota exhausted)")
        job["finished_at"] = datetime.now(VN_TZ).isoformat(timespec="seconds")
        job["_worker_pending"] = False
        _persist()


def job_view(jid: str) -> dict | None:
    with _state:
        changed = _expire(datetime.now(VN_TZ))
        job = _jobs.get(jid)
        if changed:
            _persist()
        if job is None:
            return None
        out = {k: v for k, v in job.items() if not k.startswith("_")}
    reads = cached(out["cameras"])
    out["readings"] = list(reads.values()) if out["state"] in ("ready", "error", "expired") else []
    out["unread"] = [c for c in out["cameras"] if c not in reads]
    return out


def _where(cam_id: str, deadline: float | None = None) -> dict | None:
    camera = by_id(deadline).get(cam_id)
    if camera is None:
        return None
    return {"name": camera["name"], "lat": camera["lat"], "lon": camera["lon"]}

def _sleep_with_deadline(seconds: float, deadline: float | None) -> bool:
    if deadline is None:
        time.sleep(seconds)
        return True
    left = deadline - time.monotonic()
    if left <= 0.5 or seconds > left - 0.5:
        return False
    time.sleep(seconds)
    return True


def _read_batch(todo: list[str], *, deadline: float | None = None) -> None:
    now = datetime.now(VN_TZ)
    with ThreadPoolExecutor(12) as pool:
        first = dict(zip(todo, pool.map(lambda c: snapshot(c, max_age_s=0, deadline=deadline), todo)))
        t0 = time.monotonic()
        live = [c for c in todo if first[c]]
        second: dict[str, bytes | None] = {}
        for wait in (REFRESH_S, 6):  # attempt another frame only when the job deadline can cover the wait
            left = [c for c in live if not second.get(c) or second[c] == first[c]]
            if not left:
                break
            if not _sleep_with_deadline(max(0.0, t0 + wait - time.monotonic()), deadline):
                break
            t0 = time.monotonic()
            try:
                second.update(zip(left, pool.map(
                    lambda c: snapshot(c, max_age_s=0, deadline=deadline), left)))
            except Expired:
                break
        timeout(deadline, 1)
        for c in todo:
            if not first[c]:
                location = _where(c, deadline)
                if location is not None:
                    _store({"id": c, **location, "at": now.isoformat(timespec="seconds"), "state": "offline"})
        groups = [live[i:i + BATCH] for i in range(0, len(live), BATCH)]
        list(pool.map(lambda g: _ask(g, first, second, now, deadline=deadline), groups))


def _ask(group: list[str], first: dict, second: dict, now: datetime, *,
         deadline: float | None = None) -> None:
    cameras = by_id(deadline)
    group = [camera_id for camera_id in group if camera_id in cameras and camera_id in first]
    if not group:
        return
    parts: list = []
    frames = {}
    for i, camera_id in enumerate(group, 1):
        fs = [first[camera_id]] + (
            [second[camera_id]] if second.get(camera_id) and second[camera_id] != first[camera_id] else []
        )
        frames[camera_id] = len(fs)
        parts += [f"Camera {i}: {cameras[camera_id]['name']} ({len(fs)} frame{'s' if len(fs) != 1 else ''})"] + fs
    out, model = None, None
    for model in CAMERA_MODELS:
        if _resting.get(model, 0) > time.time():
            continue
        try:
            out = ai._call(PROMPT.replace("{n}", str(len(group))), parts, model=model, deadline=deadline)
            break
        except Expired:
            raise
        except ai.NoModel:
            for camera_id in group:
                camera = cameras[camera_id]
                _store({"id": camera_id, "name": camera["name"], "lat": camera["lat"], "lon": camera["lon"],
                        "at": now.isoformat(timespec="seconds"), "state": "no_model"})
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in (429, 503):  # quota spent on every key, or overloaded: next model
                _resting[model] = time.time() + (REST_S if exc.response.status_code == 429 else 60)
                continue
            print(f"camera batch failed: {model} {exc.response.status_code}")
            return
        except Exception as exc:  # bad JSON, timeout: not cached, so the next request retries
            print(f"camera batch failed: {model} {type(exc).__name__}")
            return
    if out is None:
        print("camera batch failed: every camera model is out of quota")
        return
    answers = {int(a.get("camera", 0)): a for a in out.get("cameras", []) if isinstance(a, dict)}
    for i, camera_id in enumerate(group, 1):
        answer = answers.get(i)
        if answer:
            _store(_record(cameras[camera_id], answer, frames[camera_id], now, model))


def _record(cam: dict, out: dict, frames: int, now: datetime, model: str) -> dict:
    rec = {"id": cam["id"], "name": cam["name"], "lat": cam["lat"], "lon": cam["lon"],
           "at": now.isoformat(timespec="seconds"), "frames": frames, "image_time": out.get("image_time"),
           "usable": bool(out.get("usable", True)), "flooded": bool(out.get("flooded")),
           "depth_class": out.get("depth_class"),
           "traffic": out.get("traffic") if frames >= 2 else "khong_ro",
           "evidence": out.get("evidence"), "confidence": float(out.get("confidence") or 0),
           "model": f"gemini/{model}" if (ai.provider() or ("",))[0] == "gemini" else "/".join(ai.provider())}
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
                 "lat": cam["lat"], "lon": cam["lon"], "camera_id": cam["id"], "frames": rec["frames"],
                 "depth_cm": rec["depth_cm"], "observed_at": rec["at"],
                 "confidence": rec["confidence"], "evidence": rec["evidence"],
                 "source": "camera", "streets": names}
        flood["gate"] = ai._gate(flood, ["street", "depth_cm", "observed_at"])
        ai._append(ai.REVIEW_FILE, flood)
        # Published without operator review on purpose: the image comes from the city's own camera portal, not from
        # a user, and holding a positive flood sighting back could let a plan call a flooded street dry.
        if flood["gate"] == "ACCEPT":
            ai._append(ai.LIVE_FLOOD_FILE, flood)


def public(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if not k.startswith("_")}
    out["image_url"] = f"/api/cameras/{rec['id']}.jpg"
    if out.get("traffic") in TRAFFIC_VI:
        out["traffic_vi"] = TRAFFIC_VI[out["traffic"]]
    return out


_restore()
