"""Hard spend guards: paid Google APIs (per SKU) and AI model calls (per provider/model/key).

Every paid Google call goes through `spend(sku)`; every upstream AI attempt goes through `reserve_ai(...)` before the
request is sent, including retries on another key or model. Counters persist to STORE and are written atomically.
A counter file that exists but cannot be read stops spending (fail closed) instead of starting from zero.
Caps protect one backend's own spend; they are not a $0 billing guarantee for a shared billing account.
"""
from __future__ import annotations

import hashlib
import fcntl
import os
import threading
from datetime import datetime, timedelta, timezone

from .config import STORE
from .storage import CorruptState, read_json, write_json

USAGE_FILE = STORE / "google_usage.json"
AI_USAGE_FILE = STORE / "ai_usage.json"
VN_TZ = timezone(timedelta(hours=7))

# sku → (monthly cap we allow, Google free monthly allowance, note)
CAPS = {
    "streetview_metadata": (5000, None, "Street View metadata: free, unlimited"),
    "streetview_static": (4000, 10000, "Street View Static: 10k free / month"),
    "places_nearby_pro": (800, 5000, "Nearby Search (Pro fields): 5k free / month; capped under 1k in case the field mask bills higher"),
    "places_details_atmosphere": (400, 1000, "Place Details with reviews/parking: 1k free / month"),
    "gemini_maps_grounding": (300, None, "Gemini grounding with Google Maps: counted defensively"),
}
DAILY_CAP = {"streetview_static": 400, "places_nearby_pro": 100, "places_details_atmosphere": 60,
             "gemini_maps_grounding": 60, "streetview_metadata": 1000}
# Daily AI attempt caps, configurable per deployment.
AI_DAILY_CAP_PER_KEY = int(os.environ.get("AI_DAILY_CAP_PER_KEY", "200"))
AI_DAILY_CAP_PER_MODEL = int(os.environ.get("AI_DAILY_CAP_PER_MODEL", "500"))

_lock = threading.Lock()


class OverBudget(Exception):
    pass


def _load(path) -> dict:
    try:
        return read_json(path, {})
    except CorruptState as exc:
        raise OverBudget(f"không đọc được bộ đếm chi phí ({exc}); dừng để không tốn phí") from exc


def spend(sku: str) -> None:
    """Reserve one call or raise OverBudget. Call *before* the request is sent."""
    if sku not in CAPS:
        raise OverBudget(f"{sku}: not an allowed Google SKU")
    now = datetime.now(VN_TZ)
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with _lock, USAGE_FILE.with_suffix(".lock").open("a") as lease:
        fcntl.flock(lease, fcntl.LOCK_EX)
        u = _load(USAGE_FILE)
        m = u.setdefault(month, {}).setdefault(sku, 0)
        d = u.setdefault(day, {}).setdefault(sku, 0)
        if m >= CAPS[sku][0]:
            raise OverBudget(f"{sku}: đã chạm hạn mức tháng ({CAPS[sku][0]})")
        if d >= DAILY_CAP.get(sku, 10**9):
            raise OverBudget(f"{sku}: đã chạm hạn mức ngày ({DAILY_CAP[sku]})")
        u[month][sku] = m + 1
        u[day][sku] = d + 1
        write_json(USAGE_FILE, u, indent=1)


def key_fingerprint(key: str) -> str:
    """A short, non-reversible label for an API key (the key itself is never stored or reported)."""
    return hashlib.sha256(key.encode()).hexdigest()[:8]


def reserve_ai(provider: str, model: str, key: str) -> None:
    """Reserve one upstream AI attempt for this key and model today, or raise OverBudget."""
    day = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    key_id, model_id = f"{provider}/{model}/{key_fingerprint(key)}", f"{provider}/{model}"
    with _lock:
        u = _load(AI_USAGE_FILE)
        today = u.setdefault(day, {"keys": {}, "models": {}})
        if today["keys"].get(key_id, 0) >= AI_DAILY_CAP_PER_KEY:
            raise OverBudget(f"{key_id}: đã chạm hạn mức ngày ({AI_DAILY_CAP_PER_KEY} lần gọi)")
        if today["models"].get(model_id, 0) >= AI_DAILY_CAP_PER_MODEL:
            raise OverBudget(f"{model_id}: đã chạm hạn mức ngày ({AI_DAILY_CAP_PER_MODEL} lần gọi)")
        today["keys"][key_id] = today["keys"].get(key_id, 0) + 1
        today["models"][model_id] = today["models"].get(model_id, 0) + 1
        for old in sorted(k for k in u if k < day)[:-30]:  # keep a month of history
            del u[old]
        write_json(AI_USAGE_FILE, u, indent=1)


def report() -> dict:
    now = datetime.now(VN_TZ)
    try:
        u = _load(USAGE_FILE)
    except OverBudget:
        u = {}
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    return {sku: {"month": u.get(month, {}).get(sku, 0), "month_cap": cap, "free_allowance": free,
                  "today": u.get(day, {}).get(sku, 0), "day_cap": DAILY_CAP.get(sku), "note": note}
            for sku, (cap, free, note) in CAPS.items()}


def ai_report() -> dict:
    day = datetime.now(VN_TZ).strftime("%Y-%m-%d")
    try:
        today = _load(AI_USAGE_FILE).get(day, {"keys": {}, "models": {}})
    except OverBudget as exc:
        return {"error": str(exc)}
    return {"day": day, "per_key_cap": AI_DAILY_CAP_PER_KEY, "per_model_cap": AI_DAILY_CAP_PER_MODEL, **today}
