"""Shared helpers for the data pipelines: polite HTTP, Overpass, text and geo utils."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
import unicodedata
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"

USER_AGENT = (
    "VaoDuoc-hackathon-pipeline/0.1 (MLAI Hackathon 2026 research prototype; "
    "low-volume; contact pkhoa1331@gmail.com)"
)
# kumi first (overpass-api.de answered 406/504 for us); mail.ru mirror as fallback when kumi is saturated
OVERPASS_URLS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# (south, west, north, east)
DEMO_BBOX = (10.790, 106.695, 10.810, 106.722)
HCMC_BBOX = (10.70, 106.60, 10.86, 106.78)

_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT


def http_get(url: str, params: dict | None = None, timeout: int = 60, retries: int = 3) -> requests.Response:
    for attempt in range(retries):
        try:
            r = _session.get(url, params=params, timeout=timeout)
            if r.status_code in (429, 502, 503, 504):
                raise requests.HTTPError(f"{r.status_code}")
            r.raise_for_status()
            return r
        except (requests.RequestException,) as exc:
            if attempt == retries - 1:
                raise
            wait = 5 * (attempt + 1)
            print(f"  retry {attempt + 1} after {exc!r}; sleeping {wait}s")
            time.sleep(wait)
    raise AssertionError("unreachable")


def overpass(query: str, cache_name: str, refresh: bool = False) -> dict:
    """Run an Overpass query on the kumi mirror, caching the JSON under data/raw/osm/."""
    cache = RAW / "osm" / f"{cache_name}-{hashlib.sha1(query.encode()).hexdigest()[:10]}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text())
    cache.parent.mkdir(parents=True, exist_ok=True)
    for attempt, url in enumerate(OVERPASS_URLS):
        try:
            r = _session.post(url, data={"data": query}, timeout=180)
            r.raise_for_status()
            data = r.json()
            break
        except (requests.RequestException, ValueError) as exc:
            if attempt == len(OVERPASS_URLS) - 1:
                raise
            print(f"  overpass {url} failed ({exc!r}); trying next mirror")
            time.sleep(5)
    cache.write_text(json.dumps(data, ensure_ascii=False))
    return data


def load_env_local() -> dict[str, str]:
    """Read KEY=VALUE pairs from <repo>/.env.local (if present), overlaid by the real environment."""
    env: dict[str, str] = {}
    path = ROOT / ".env.local"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GOONG")})
    return env


# ---------- text ----------

def fold(text: str) -> str:
    """Lowercase and strip Vietnamese diacritics, one output char per input char (indexes stay aligned)."""
    out = []
    for ch in unicodedata.normalize("NFC", text):
        if ch in "đĐ":
            out.append("d")
            continue
        base = unicodedata.normalize("NFD", ch)[0]
        out.append(base.lower()[0])
    return "".join(out)


_PREFIX = re.compile(r"^(duong|d\.|đ\.|pho|street)\s+")


def norm_name(name: str) -> str:
    """Normalise a street/alley name for comparison: fold accents, drop 'Đường'/'Đ.' prefixes, squash spaces."""
    s = fold(unicodedata.normalize("NFC", name or "")).strip()
    s = re.sub(r"[,;]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = _PREFIX.sub("", s)
    s = re.sub(r"\bthang tam\b", "thang 8", s)          # "Cách Mạng Tháng Tám" == "Cách Mạng Tháng 8"
    # "hem 12 duong xo viet nghe tinh" -> "hem 12 xo viet nghe tinh"
    s = re.sub(r"^(hem|kiet|ngo)\s+([\w/]+)\s+(duong|d\.)\s+", r"\1 \2 ", s)
    return s.strip()


# ---------- geo ----------

def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class LocalProj:
    """Equirectangular projection to metres around a reference latitude (fine at city scale)."""

    def __init__(self, lat0: float, lon0: float):
        self.lat0, self.lon0 = lat0, lon0
        self.kx = 111320.0 * math.cos(math.radians(lat0))
        self.ky = 110574.0

    def xy(self, lat: float, lon: float) -> tuple[float, float]:
        return ((lon - self.lon0) * self.kx, (lat - self.lat0) * self.ky)


def buffer_bbox(bbox: tuple[float, float, float, float], metres: float) -> tuple[float, float, float, float]:
    s, w, n, e = bbox
    dlat = metres / 110574.0
    dlon = metres / (111320.0 * math.cos(math.radians((s + n) / 2)))
    return (s - dlat, w - dlon, n + dlat, e + dlon)


def in_bbox(lat: float, lon: float, bbox: tuple[float, float, float, float]) -> bool:
    s, w, n, e = bbox
    return s <= lat <= n and w <= lon <= e


def bbox_str(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{v:.5f}" for v in bbox)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1))
