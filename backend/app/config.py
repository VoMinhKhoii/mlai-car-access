"""Paths, environment and the tunable numbers from docs/decision-log.md."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
CACHE = ROOT / "backend" / "cache"
STORE = ROOT / "backend" / "store"
FLAG_FILE = ROOT / "backend" / "flags.json"
FRONTEND_DIST = ROOT / "frontend" / "dist"

# On Vercel the bundle is read-only: copy the shipped caches and state to /tmp once per instance and write there.
if os.environ.get("VERCEL"):
    _tmp = Path("/tmp/vaoduoc")
    for src, name in ((CACHE, "cache"), (STORE, "store")):
        if not (_tmp / name).exists() and src.exists():
            shutil.copytree(src, _tmp / name)
    if FLAG_FILE.exists() and not (_tmp / "flags.json").exists():
        shutil.copy(FLAG_FILE, _tmp / "flags.json")
    CACHE, STORE, FLAG_FILE = _tmp / "cache", _tmp / "store", _tmp / "flags.json"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split("#", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


_load_env_file(ROOT / ".env.local")

GOONG_API_KEY = os.environ.get("GOONG_API_KEY", "")
GOONG_MAPTILES_KEY = os.environ.get("GOONG_MAPTILES_KEY", "")

# Raced in parallel; the first valid answer wins (overpass-api.de is usually ~1 s, kumi ~35 s).
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Q5 / D16: reversing beyond this downgrades a Stop Point to "tight exit".
REVERSE_LIMIT_M = 30.0
# Q6: Walk Leg caps (placeholders).
WALK_CAP_M = {"park": 400.0, "pickup": 150.0}
# Q12: Dwell Window default for Pickup/Drop-off.
PICKUP_DWELL_MIN = 15
# D15: Alley Fit margins (metres).
SIDE_CLEARANCE_M = 0.3
PARKED_MOTORBIKE_ROW_M = 0.7
TIGHT_MARGIN_M = 0.2
DOOR_OPEN_M = 0.6
# Q7: a roadway narrower than this fits a single motor-vehicle lane.
TWO_LANE_MIN_M = 5.5
# D14: moving water this deep blocks every car.
MOVING_WATER_BLOCK_M = 0.30
# D19: walking through water deeper than this is labelled "lội nước".
WALK_WADE_M = 0.15
# Area graph radius around a destination.
AREA_RADIUS_M = 1200.0
