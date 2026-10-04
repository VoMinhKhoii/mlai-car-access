"""HCMC traffic-camera registry → data/cameras/hcmc_cameras.json.

The cameras are the public ones on Cổng thông tin giao thông TP.HCM (giaothong.hochiminhcity.gov.vn).
Their ids and positions come from the portal's camera layer as mirrored in the open helitoo/venha
project (src/data/data-camera.json). Stills are fetched live by the backend (backend/app/cameras.py).

    python3 pipelines/camera_registry.py
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import requests

SOURCE = "https://raw.githubusercontent.com/helitoo/venha/main/src/data/data-camera.json"
OUT = Path(__file__).resolve().parent.parent / "data" / "cameras" / "hcmc_cameras.json"
HCMC_BBOX = (10.35, 106.30, 11.20, 107.10)  # s, w, n, e (same as backend config)


def main() -> None:
    raw = requests.get(SOURCE, timeout=60, headers={"User-Agent": "VaoDuoc-hackathon-pipeline/0.1"}).json()
    s, w, n, e = HCMC_BBOX
    cams, seen = [], set()
    for c in raw:
        lat, lon = c.get("Lat"), c.get("Lng")
        if not c.get("CamId") or c["CamId"] in seen or lat is None or lon is None:
            continue
        if not (s <= lat <= n and w <= lon <= e):
            continue
        seen.add(c["CamId"])
        cams.append({"id": c["CamId"], "name": (c.get("CamName") or "").strip(), "lat": round(lat, 7),
                     "lon": round(lon, 7), "code": c.get("Code") or "", "type": c.get("CamType") or ""})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        "source": "Cổng thông tin giao thông TP.HCM (giaothong.hochiminhcity.gov.vn), camera layer",
        "mirror": SOURCE,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cameras": cams,
    }, ensure_ascii=False, indent=0))
    print(f"{len(cams)} cameras → {OUT}")


if __name__ == "__main__":
    main()
