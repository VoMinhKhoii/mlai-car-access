"""Public HCMC traffic cameras → flood-now and traffic-now evidence (D34), flag `ai_camera_flood`.

Registry: data/cameras/hcmc_cameras.json (pipelines/camera_registry.py), ~800 cameras of
Cổng thông tin giao thông TP.HCM. A still refreshes about every 12 s, so a reading takes two
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
from functools import lru_cache

import httpx

from . import ai, flags
from .config import CAMERA_READ_TTL_S, CAMERA_STALE_MIN, DATA, STORE
from .osm import haversine, strip_accents

VN_TZ = timezone(timedelta(hours=7))
REGISTRY = DATA / "cameras" / "hcmc_cameras.json"
READINGS_FILE = STORE / "camera_readings.jsonl"
SNAPSHOT_URL = "https://giaothong.hochiminhcity.gov.vn/render/ImageHandler.ashx?id={cam}&t={ms}"
PORTAL_URL = "https://giaothong.hochiminhcity.gov.vn/Map.aspx"
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


@lru_cache(maxsize=1)
def registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def by_id() -> dict[str, dict]:
    return {c["id"]: c for c in registry()["cameras"]}


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
