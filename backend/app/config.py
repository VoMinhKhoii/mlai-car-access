"""Paths, environment and the tunable numbers from docs/decision-log.md."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


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


def _path_override(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser().resolve() if value else default


_load_env_file(ROOT / ".env.local")

# One continuously running process owns operator sessions, review state, quotas and background jobs. A serverless
# platform gives each instance its own throwaway copy of that state, so it is refused rather than silently wrong.
if os.environ.get("VERCEL"):
    raise RuntimeError("Ngõ Ngách backend needs one persistent process; run it with uvicorn --workers 1, not serverless")

CACHE = _path_override("VAODUOC_CACHE", ROOT / "backend" / "cache")
STORE = _path_override("VAODUOC_STORE", ROOT / "backend" / "store")
FLAG_FILE = _path_override("VAODUOC_FLAGS", ROOT / "backend" / "flags.json")
FRONTEND_DIST = _path_override("VAODUOC_DIST", ROOT / "frontend" / "dist")

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
# R-04: conservative traversal windows cover a return-speed allowance plus this fixed uncertainty margin.
ALLEY_SPEED_MPS = 15 / 3.6
FLOOD_TRAVERSAL_MARGIN_MIN = 5
FLOOD_TIMING_STEP_MIN = 15
FLOOD_TIMING_HORIZON_H = 12
FLOOD_REPORT_VALID_H = 2
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
# Service area (D30): Ho Chi Minh City only. Tide, flood history and listings all describe HCMC.
HCMC_BBOX = (10.35, 106.30, 11.20, 107.10)  # s, w, n, e


def in_hcmc(lat: float, lon: float) -> bool:
    s, w, n, e = HCMC_BBOX
    return s <= lat <= n and w <= lon <= e


# Area graph radius around a destination.
AREA_RADIUS_M = 1200.0

# D34: live traffic cameras. A reading is reused for this long; a frame whose clock is further off is stale.
CAMERA_READ_TTL_S = 180
CAMERA_STALE_MIN = 10
# D34: travel-time factor on the stretch a camera watches, per traffic level, plus a queue a still cannot
# measure. Stretches no camera watches take the typical factor of all cameras read (placeholders; tune from
# store/camera_readings.jsonl).
TRAFFIC_FACTOR = {"thong_thoang": 1.0, "dong": 1.3, "un_u": 2.0, "ket_cung": 4.0}
TRAFFIC_QUEUE_MIN = {"un_u": 3, "ket_cung": 10}

# Read-only local verification: refuse cache misses rather than contacting upstream services.
CACHED_ONLY = os.environ.get("NGONGACH_CACHED_ONLY", "0") == "1"
