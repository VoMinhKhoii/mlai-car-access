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
        "label": "Thu thập dữ liệu trực tiếp",
        "detail": "Khi lập kế hoạch, tải bản đồ OSM và tin rao Chợ Tốt quanh điểm đến ngay lúc đó (cache 12 giờ), thay cho bộ dữ liệu soạn sẵn.",
        "default": True,
    },
    "parcel_widths": {
        "label": "Bề rộng hẻm theo thửa đất (cổng quy hoạch TP.HCM)",
        "detail": "Dùng hình học thửa đất để ước tính khoảng trống; nguồn gốc chính thức nhưng không phải clear width đo thực tế và không xác nhận strict fit.",
        "default": True,
    },
    "parcel_deep_scan": {
        "label": "Quét sâu đường vào/ra điểm đến (mỗi 5 m)",
        "detail": "Quét các ways trên lối vào/ra theo chiều hợp lệ, lấy mẫu đầu-cuối và xấp xỉ mỗi 5 m trong ngân sách 60 cuts. Quét thưa/cắt cụt chỉ để tham khảo; ngay cả phủ đủ cũng không chứng minh hết vật cản. Tắt thì chỉ có mẫu nông.",
        "default": True,
    },
    "building_gaps": {
        "label": "Bề rộng từ khoảng cách giữa hai dãy nhà",
        "detail": "Thử nghiệm, tắt mặc định: khoảng cách giữa footprint nhà hai bên hẻm (Overture). Kiểm chứng cho thấy chưa phân biệt được hẻm hẹp và hẻm rộng (lệch ~2–4 m).",
        "default": False,
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
        "detail": "~800 camera công khai của TP.HCM; đọc tối đa hai khung hình cách ~13 giây. Một khung hình chỉ cho thấy ngập, không kết luận giao thông. Tuyến đường lớn được chọn theo Goong.",
        "default": True,
    },
    "ai_voice_report": {
        "label": "Báo cáo bằng giọng nói",
        "detail": "Nhận diện ý định xác nhận xe vào/ra hoặc báo vật cản; kết quả luôn cần người dùng xem lại và gửi.",
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
    "live_hydro": {
        "label": "Triều và mưa đo trực tiếp",
        "detail": "Mực nước đo tại trạm Phú An và lượng mưa từng giờ ở ~40 trạm đo mưa TP.HCM (vndms.gov.vn), rồi dự báo Open-Meteo cho các giờ tới. Tắt thì dùng bản tin triều soạn sẵn và chỉ mưa giả định.",
        "default": True,
    },
    "ai_flood_prior": {
        "label": "Mô hình ngập theo lịch sử",
        "detail": "Độ nhạy ngập từng đoạn đường học từ dữ liệu IRD 2002–2026 theo mức triều và mưa.",
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
