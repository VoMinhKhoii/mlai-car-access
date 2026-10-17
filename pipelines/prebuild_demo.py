"""Pre-build the Live Area for every demo destination so nothing is crawled on stage.

Run from the repo root: python3 pipelines/prebuild_demo.py [--force]
Results land in backend/cache/live/areas/<key>.json and are served by /api/area/build and /api/plan.
AI photo reading uses only the free GEMINI_API_KEY* keys (the paid key is never used here).
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app import live  # noqa: E402
from app.main import PRESETS, _way_mid  # noqa: E402

EXTRA = [
    ("HUTECH, 475A Điện Biên Phủ, Bình Thạnh", 10.8017, 106.7148),
]

points = [(p["label"], *_way_mid(p["way_id"])) for p in PRESETS] + EXTRA
for label, lat, lon in points:
    t = time.time()
    last = {}
    for line in live.build(lat, lon, force="--force" in sys.argv):
        last = json.loads(line)
    st = last.get("status", {})
    area = last.get("area") or {}
    print(f"{label}: {st.get('state')} in {time.time() - t:.0f}s, key={st.get('key')}, "
          f"parcels={len(area.get('parcels', []))}, listings={len(area.get('listings', []))}, "
          f"photos={len(area.get('photos', []))} {st.get('error') or ''}", flush=True)
