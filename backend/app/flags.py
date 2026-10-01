"""One flag per AI feature (D22), switchable at runtime.

Defaults come from `backend/flags.json` if present, then env vars `FLAG_<NAME>=1|0`.
When a flag is off, the engine behaves exactly as if that AI source did not exist.
"""
from __future__ import annotations

import json
import os

from .config import FLAG_FILE

AI_FEATURES = {
    "live_crawl": {
        "label": "Thu thập dữ liệu trực tiếp",
        "detail": "Khi lập kế hoạch, tải bản đồ OSM và tin rao Chợ Tốt quanh điểm đến ngay lúc đó (cache 12 giờ), thay cho bộ dữ liệu soạn sẵn.",
        "default": True,
    },
    "ai_listings": {
        "label": "AI đọc tin rao nhà đất",
        "detail": "Trích bề rộng hẻm, 'hẻm xe hơi', 'hẻm thông/cụt' từ tin rao Chợ Tốt → bằng chứng mức Tự khai.",
        "default": True,
    },
    "ai_text_rules": {
        "label": "AI đọc văn bản quy định & tin ngập",
        "detail": "Trích quy định dừng/đỗ và báo cáo ngập từ văn bản, qua cổng duyệt ACCEPT / REVIEW / INSUFFICIENT_INFORMATION.",
        "default": False,
    },
    "ai_photo_evidence": {
        "label": "AI đọc ảnh tài xế gửi",
        "detail": "Ảnh biển báo → quy định dừng/đỗ; ảnh hẻm → bề rộng; ảnh ngập → mức ngập.",
        "default": False,
    },
    "ai_camera_flood": {
        "label": "AI đọc camera giao thông",
        "detail": "Ảnh camera công khai của TP.HCM gần điểm ngập → bằng chứng ngập hiện tại.",
        "default": False,
    },
    "google_lookup": {
        "label": "Tra cứu Google (Street View, quán trong hẻm)",
        "detail": "Chỉ hiển thị trực tiếp, không lưu, không dùng làm bằng chứng. Có giới hạn chi phí cứng dưới mức miễn phí.",
        "default": False,
    },
    "ai_maps_grounding": {
        "label": "Gemini đọc Google Maps cho hẻm này",
        "detail": "Gemini + Grounding with Google Maps tóm tắt đánh giá quanh hẻm; hiển thị kèm nguồn Google Maps, không lưu.",
        "default": False,
    },
    "ai_flood_prior": {
        "label": "Mô hình ngập theo lịch sử",
        "detail": "Độ nhạy ngập từng đoạn đường học từ dữ liệu IRD 2002–2026 theo mức triều và mưa.",
        "default": True,
    },
}

_state: dict[str, bool] = {}


def _load() -> None:
    saved = json.loads(FLAG_FILE.read_text()) if FLAG_FILE.exists() else {}
    for name, meta in AI_FEATURES.items():
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
    FLAG_FILE.write_text(json.dumps(_state, indent=1))


def describe() -> list[dict]:
    return [{"name": n, "label": m["label"], "detail": m["detail"], "enabled": enabled(n)}
            for n, m in AI_FEATURES.items()]
