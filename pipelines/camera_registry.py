"""HCMC traffic-camera registry → data/cameras/hcmc_cameras.json (fallback for the backend).

The backend reads the camera layer of Cổng thông tin giao thông TP.HCM live (hourly), the same request
the portal's public map page sends when its "Camera" layer is switched on. This snapshot is only used
when the portal is unreachable.

    python3 pipelines/camera_registry.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from app import cameras  # noqa: E402


def main() -> None:
    cams = cameras.fetch_official()
    cameras.REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    cameras.REGISTRY.write_text(json.dumps({
        "source": "Cổng thông tin giao thông TP.HCM (giaothong.hochiminhcity.gov.vn), camera layer",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cameras": cams,
    }, ensure_ascii=False, indent=0))
    up = sum(1 for c in cams if c["status"] == "UP")
    print(f"{len(cams)} cameras ({up} UP) → {cameras.REGISTRY}")


if __name__ == "__main__":
    main()
