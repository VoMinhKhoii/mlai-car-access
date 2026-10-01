"""Forward geocoding with a swappable backend.

Default: Nominatim (OSM), <=1 req/s with a descriptive User-Agent, results cached on disk.
Swap-in: Goong (`rsapi.goong.io/v2/geocode`) is used automatically once GOONG_API_KEY is set in
<repo>/.env.local or the environment. The Goong path is written against the documented v2
response shape (Google-like `results[].geometry.location`) but has NOT been exercised yet.

Both backends implement:  geocode(query, viewbox) -> list[Candidate]
A caller then picks the first candidate that passes its own name check.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Protocol

from common import RAW, http_get, load_env_local

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
GOONG_URL = "https://rsapi.goong.io/v2/geocode"
CACHE_PATH = RAW / "geocode_cache.json"


@dataclass
class Candidate:
    lat: float
    lon: float
    label: str          # display name / formatted address
    kind: str           # e.g. "building/commercial", "highway/secondary", "goong/street_address"
    importance: float   # provider score, 0..1 when available


class Geocoder(Protocol):
    name: str

    def geocode(self, query: str, viewbox: tuple[float, float, float, float] | None = None) -> list[Candidate]:
        """viewbox = (south, west, north, east); results outside it are dropped."""
        ...


class _Cache:
    def __init__(self):
        self.data = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}

    def get(self, key):
        return self.data.get(key)

    def put(self, key, value):
        self.data[key] = value
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))


_cache = _Cache()


class NominatimGeocoder:
    name = "nominatim"
    min_interval_s = 1.1

    def __init__(self):
        self._last = 0.0

    def geocode(self, query, viewbox=None):
        key = f"nominatim|{query}|{viewbox}"
        hit = _cache.get(key)
        if hit is None:
            params = {"q": query, "format": "jsonv2", "limit": 5, "countrycodes": "vn", "accept-language": "vi"}
            if viewbox:
                s, w, n, e = viewbox
                params.update(viewbox=f"{w},{n},{e},{s}", bounded=1)
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            try:
                hit = http_get(NOMINATIM_URL, params=params, timeout=90).json()
            finally:
                self._last = time.monotonic()
            _cache.put(key, hit)
        return [
            Candidate(float(x["lat"]), float(x["lon"]), x.get("display_name", ""),
                      f"{x.get('category')}/{x.get('type')}", float(x.get("importance") or 0))
            for x in hit
        ]


class GoongGeocoder:
    """Drop-in replacement once a key exists. Untested: no key was available when this was written."""
    name = "goong"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def geocode(self, query, viewbox=None):
        key = f"goong|{query}"
        hit = _cache.get(key)
        if hit is None:
            hit = http_get(GOONG_URL, params={"address": query, "api_key": self.api_key}, timeout=30).json()
            _cache.put(key, hit)
        out = []
        for r in hit.get("results", []):
            loc = r.get("geometry", {}).get("location", {})
            if "lat" not in loc:
                continue
            c = Candidate(float(loc["lat"]), float(loc["lng"]), r.get("formatted_address", ""),
                          "goong/" + ",".join(r.get("types", []) or ["?"]), 1.0)
            if viewbox is None or (viewbox[0] <= c.lat <= viewbox[2] and viewbox[1] <= c.lon <= viewbox[3]):
                out.append(c)
        return out


def get_geocoder() -> Geocoder:
    key = load_env_local().get("GOONG_API_KEY")
    return GoongGeocoder(key) if key else NominatimGeocoder()


