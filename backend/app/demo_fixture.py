"""Loopback-only launcher for the synthetic width-coverage demo.

Run from ``backend`` with::

    ../.venv/bin/python -m app.demo_fixture

This entrypoint isolates every writable backend path under a unique temporary
directory. It is the only entrypoint that installs the synthetic field fixture;
``app.main:app`` continues to use the normal field data and production paths.
"""
from __future__ import annotations

import csv
import os
import shutil
import tempfile
from pathlib import Path
import secrets
from typing import TYPE_CHECKING

import uvicorn

if TYPE_CHECKING:
    from fastapi import FastAPI

HOST = "127.0.0.1"
PORT = 8787
LOCAL_URL = f"http://{HOST}:{PORT}"
DEMO_OPERATOR_SECRET = secrets.token_urlsafe(24)

_STORIES = {
    "cafe-ngo-tat-to": (
        "Dry scenario at Hẻm 160: Vios arrives at 14:00 and stays 90 min. "
        "Review entry, stop, exit and water conditions during the stay."
    ),
    "pickup-narrow": (
        "Comparison using existing repository data. No field width measurements; "
        "retains the fit status and warnings from existing sources."
    ),
    "friend-house": (
        "Tide comparison using existing repository data. No width fixture is loaded; "
        "missing data does not establish vehicle access."
    ),
    "nguyen-huu-canh": (
        "Comparison using existing repository data. No field width measurements; "
        "retains the unverified status."
    ),
    "cafe-ngo-tat-to-rain": (
        "Rain at 45 mm/h during the stay; review estimated water depth and alley exit options."
    ),
}


def _disable_provider_credentials() -> None:
    """Prevent this local demo from inheriting real paid-provider credentials."""
    for name in tuple(os.environ):
        if (name in {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_MAPS_API_KEY"}
                or name == "GEMINI_API_KEY" or name.startswith("GEMINI_API_KEY_")):
            os.environ.pop(name, None)


def _set_demo_environment(root: Path) -> None:
    os.environ.update({
        "VAODUOC_STORE": str(root / "store"),
        "VAODUOC_CACHE": str(root / "cache"),
        "VAODUOC_FLAGS": str(root / "flags.json"),
        "OPERATOR_SECRET": DEMO_OPERATOR_SECRET,
        "OPERATOR_SECRET_FILE": "",
        "APP_ORIGINS": "http://127.0.0.1:5173",
        "GOONG_API_KEY": "",
        "GOONG_MAPTILES_KEY": "",
        "GOOGLE_MAPS_API_KEY": "",
        "GEMINI_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "AI_MODEL": "",
        "FLAG_AI_VOICE_REPORT": "1",
        "FLAG_LIVE_CRAWL": "0",
        "FLAG_LIVE_HYDRO": "0",
    })
    os.environ.pop("VERCEL", None)


def _assert_isolated_paths(root: Path) -> None:
    # Import only after overrides are set: backend modules derive their paths once at import time.
    from . import config

    expected = {
        "VAODUOC_STORE": (root / "store").resolve(),
        "VAODUOC_CACHE": (root / "cache").resolve(),
        "VAODUOC_FLAGS": (root / "flags.json").resolve(),
    }
    actual = {
        "VAODUOC_STORE": config.STORE,
        "VAODUOC_CACHE": config.CACHE,
        "VAODUOC_FLAGS": config.FLAG_FILE,
    }
    mismatches = [name for name, path in expected.items() if actual[name] != path]
    if mismatches:
        joined = ", ".join(mismatches)
        raise RuntimeError(f"Demo fixture refused non-isolated backend paths: {joined}")


def _copy_osm_cache(backend_dir: Path, root: Path) -> None:
    source = backend_dir / "cache" / "osm" / "demo_binhthanh.json"
    target = root / "cache" / "osm" / source.name
    if not source.is_file():
        raise RuntimeError(f"Demo OSM cache is missing: {source}")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    except OSError as exc:
        raise RuntimeError(f"Could not prepare isolated demo OSM cache: {exc}") from exc


def _customize_presets(main_module) -> None:
    presets = []
    for preset in main_module.PRESETS:
        updated = dict(preset)
        updated["story"] = _STORIES[preset["id"]]
        if preset["id"] == "cafe-ngo-tat-to":
            # The positive width example must not also inject the normal heavy-rain scenario.
            updated.pop("rain", None)
        presets.append(updated)
    dry_case = next(preset for preset in presets if preset["id"] == "cafe-ngo-tat-to")
    dry_case["vehicle_id"] = "toyota-vios"
    rain_case = dict(dry_case)
    rain_case.update({
        "id": "cafe-ngo-tat-to-rain",
        "title": "Rain 45 mm/h · Hẻm 160",
        "rain": [{
            "start": "2026-09-29T14:30:00+07:00",
            "end": "2026-09-29T15:30:00+07:00",
            "mm_per_h": 45,
        }],
        "story": _STORIES["cafe-ngo-tat-to-rain"],
    })
    presets.append(rain_case)
    main_module.PRESETS = presets


def _build_fixture_app(fixture_path: Path) -> FastAPI:
    if not fixture_path.is_file():
        raise RuntimeError(f"Synthetic measurement fixture is missing: {fixture_path}")

    from . import main

    main.app.state.synthetic_demo_data = True
    _customize_presets(main)
    h160 = next(preset for preset in main.PRESETS if preset["id"] == "cafe-ngo-tat-to")
    lat, lon = main._way_mid(h160["way_id"])
    with fixture_path.open(encoding="utf-8", newline="") as source:
        way_ids = frozenset(
            int(row["osm_way_id"]) for row in csv.DictReader(source) if row.get("osm_way_id")
        )
    if h160["way_id"] not in way_ids:
        raise RuntimeError("Synthetic measurement fixture has no Hẻm 160 access rows.")
    main.app.state.synthetic_demo_scenarios = {
        scenario: {"lat": lat, "lon": lon, "max_distance_m": 200.0, "way_ids": way_ids}
        for scenario in ("cafe-ngo-tat-to", "cafe-ngo-tat-to-rain")
    }
    main.app.state.synthetic_demo_fixture_file = str(fixture_path)
    return main.app


def run() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    fixture_path = backend_dir / "tests" / "fixtures" / "synthetic_demo_measurements.csv"

    with tempfile.TemporaryDirectory(prefix="vaoduoc-synthetic-demo-") as temp_dir:
        root = Path(temp_dir)
        _set_demo_environment(root)
        _assert_isolated_paths(root)
        # .env.local is loaded with setdefault by config; remove any additional
        # numbered Gemini keys it may have supplied before importing AI modules.
        _disable_provider_credentials()
        _copy_osm_cache(backend_dir, root)
        app = _build_fixture_app(fixture_path)

        print(
            "\nSynthetic data · not field measurements.\n"
            f"Local synthetic demo: {LOCAL_URL}\n"
            f"Loopback-only demo operator password: {DEMO_OPERATOR_SECRET}\n"
            f"Temporary isolated state: {root}\n",
            flush=True,
        )
        uvicorn.run(app, host=HOST, port=PORT, workers=1)


if __name__ == "__main__":
    run()
