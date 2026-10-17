"""One flag per AI feature (D22), switchable at runtime.

Defaults come from the persisted flags file, with `FLAG_<NAME>=1|0` environment overrides applied on load.
An unreadable or invalid file loads every feature disabled; after an operator recovery write, only explicitly enabled flags are on.
"""
from __future__ import annotations

import os

from .config import FLAG_FILE
from .storage import CorruptState, read_json, write_json

AI_FEATURES = {
    "live_crawl": {
        "label": "Live data collection",
        "detail": "Load OSM maps and Chợ Tốt listings around the destination when planning (cached for 12 hours), in place of the prepared dataset.",
        "default": True,
    },
    "parcel_widths": {
        "label": "Alley width from parcels (HCMC planning portal)",
        "detail": "Estimate gaps from parcel geometry. Official provenance does not make this measured clear width or confirm strict vehicle fit.",
        "default": True,
    },
    "parcel_deep_scan": {
        "label": "Detailed destination entry/exit scan (every 5 m)",
        "detail": "Sample permitted entry/exit ways at endpoints and roughly every 5 m within a 60-cut budget. Sparse or truncated scans are for reference only; even full coverage does not establish the absence of obstructions. Disable for shallow sampling only.",
        "default": True,
    },
    "footprint_widths": {
        "label": "Roof-inferred width (calibrated)",
        "detail": "Experimental, disabled by default: cadastral calibration of Overture still has ±11.4 m error and cannot distinguish narrow and wide alleys. Inferred tier; cadastral data takes precedence.",
        "default": False,
    },
    "building_gaps": {
        "label": "Width from gaps between buildings",
        "detail": "Experimental, disabled by default: gaps between building footprints on either side of an alley (Overture). Validation cannot yet distinguish narrow and wide alleys (about 2–4 m bias).",
        "default": False,
    },
    "ai_listings": {
        "label": "AI reads property listings",
        "detail": "Extract alley width, car access and through/dead-end descriptions from Chợ Tốt listings as Declared evidence.",
        "default": True,
    },
    "ai_text_rules": {
        "label": "AI reads regulations and flood news",
        "detail": "Extract stopping/parking rules and flood reports from text, through ACCEPT / REVIEW / INSUFFICIENT_INFORMATION review gates.",
        "default": False,
    },
    "ai_photo_evidence": {
        "label": "AI reads driver photos",
        "detail": "Sign photos → stopping/parking rules; alley photos → width; flood photos → water depth.",
        "default": False,
    },
    "ai_camera_flood": {
        "label": "AI reads traffic cameras",
        "detail": "About 800 public HCMC cameras; reads up to two frames about 13 seconds apart. One frame supports flood observation only, not traffic assessment. Main-road routes are selected using Goong.",
        "default": True,
    },
    "ai_voice_report": {
        "label": "Voice reporting",
        "detail": "Recognise vehicle entry/exit confirmations or blockage reports; users always review and submit the result.",
        "default": False,
    },
    "google_lookup": {
        "label": "Google lookup (Street View, alley places)",
        "detail": "Displayed live only, not stored or used as evidence. Hard spending limits stay below the free allowance.",
        "default": False,
    },
    "ai_maps_grounding": {
        "label": "Gemini reads Google Maps for this alley",
        "detail": "Gemini + Grounding with Google Maps summarises nearby reviews, shown with Google Maps sources and not stored.",
        "default": False,
    },
    "live_hydro": {
        "label": "Live tide and rain measurements",
        "detail": "Measured water levels at Phú An and hourly rain at about 40 HCMC gauges (vndms.gov.vn), followed by Open-Meteo forecasts. Disable to use the prepared tide bulletin and simulated rain only.",
        "default": True,
    },
    "ai_flood_prior": {
        "label": "Historical flood model",
        "detail": "Road-segment flood sensitivity learned from IRD 2002–2026 data against tides and rain.",
        "default": True,
    },
}

_state: dict[str, bool] = {}


def _load() -> None:
    corrupt = False
    try:
        saved = read_json(FLAG_FILE, {})
        if not isinstance(saved, dict) or any(
                name in saved and not isinstance(saved[name], bool) for name in AI_FEATURES):
            corrupt = True
    except CorruptState:
        saved, corrupt = {}, True
    for name, meta in AI_FEATURES.items():
        if corrupt:
            value = False
        else:
            value = saved.get(name, meta["default"])
            env = os.environ.get(f"FLAG_{name.upper()}")
            if env is not None:
                value = env.strip() in ("1", "true", "yes", "on")
        _state[name] = bool(value)


def enabled(name: str) -> bool:
    if not _state:
        _load()
    return _state.get(name, False)


def set_flag(name: str, value: bool) -> None:
    if name not in AI_FEATURES:
        raise KeyError(name)
    if not _state:
        _load()
    _state[name] = value
    write_json(FLAG_FILE, _state, indent=1)


def describe() -> list[dict]:
    return [{"name": n, "label": m["label"], "detail": m["detail"], "enabled": enabled(n)}
            for n, m in AI_FEATURES.items()]
