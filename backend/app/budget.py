"""Hard spend guard for paid Google APIs.

Every paid call must go through `spend(sku)`. Monthly counters persist to disk and
each SKU is capped *below* Google's free monthly allowance, so the demo stays at $0.
The allowance is per billing account: usage elsewhere on the same account also counts,
so the caps are set at ~40–80% of the free tier.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from .config import STORE

USAGE_FILE = STORE / "google_usage.json"
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

_lock = threading.Lock()


class OverBudget(Exception):
    pass


def _load() -> dict:
    return json.loads(USAGE_FILE.read_text()) if USAGE_FILE.exists() else {}


def spend(sku: str) -> None:
    """Reserve one call or raise OverBudget. Call *before* the request is sent."""
    if sku not in CAPS:
        raise OverBudget(f"{sku}: not an allowed Google SKU")
    now = datetime.now(VN_TZ)
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    with _lock:
        u = _load()
        m = u.setdefault(month, {}).setdefault(sku, 0)
        d = u.setdefault(day, {}).setdefault(sku, 0)
        if m >= CAPS[sku][0]:
            raise OverBudget(f"{sku}: đã chạm hạn mức tháng ({CAPS[sku][0]})")
        if d >= DAILY_CAP.get(sku, 10**9):
            raise OverBudget(f"{sku}: đã chạm hạn mức ngày ({DAILY_CAP[sku]})")
        u[month][sku] = m + 1
        u[day][sku] = d + 1
        STORE.mkdir(parents=True, exist_ok=True)
        USAGE_FILE.write_text(json.dumps(u, indent=1))


def report() -> dict:
    now = datetime.now(VN_TZ)
    u = _load()
    month, day = now.strftime("%Y-%m"), now.strftime("%Y-%m-%d")
    return {sku: {"month": u.get(month, {}).get(sku, 0), "month_cap": cap, "free_allowance": free,
                  "today": u.get(day, {}).get(sku, 0), "day_cap": DAILY_CAP.get(sku), "note": note}
            for sku, (cap, free, note) in CAPS.items()}
