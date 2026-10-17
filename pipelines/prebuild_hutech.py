"""Force full live.build for confirmed HUTECH sites, using free Gemini keys only.

Run with nice -n 10. --ids accepts comma-separated manifest IDs. Writes a separate
build-status artifact; the long-running crawler remains sole owner of crawl state.
"""
import argparse
import json
import logging
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
import campus_priority
from app.tide_refresh import atomic_json


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ids")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    points = json.loads(campus_priority.CAMPUSES.read_text())["campuses"]
    if args.ids:
        selected = set(args.ids.split(","))
        points = [p for p in points if p["id"] in selected]
    state = {"campuses": {p["id"]: {"map_ready_at": campus_priority.now()} for p in points}}
    def save():
        atomic_json(ROOT / "docs/eval/hutech-area-builds.json", state)
    campus_priority.prebuild(points, state, threading.Event(), save, logging.getLogger("hutech-builds"), threading.RLock())
    print(json.dumps(state, ensure_ascii=False, indent=2))
