"""Read-only crawl/campus status with cache sizes; never reads or prints API keys."""
import argparse
import json
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def report():
    def read(path):
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError):
            return {}
    state = read(ROOT / "backend/cache/live/crawl_city_state.json")
    widths = read(ROOT / "backend/cache/live/city_parcels.json")
    area_files = list((ROOT / "backend/cache/osm").glob("area_*.json"))
    demo = ROOT / "backend/cache/osm/demo_binhthanh.json"
    areas = area_files + ([demo] if demo.exists() else [])
    batches = list((ROOT / "backend/cache/osm/city_batches").glob("*.json"))
    pid = state.get("pid")
    try:
        os.kill(pid, 0)
        running, niceness = True, os.getpriority(os.PRIO_PROCESS, pid)
    except (OSError, TypeError):
        running, niceness = False, None
    inner_ids = set().union(*(set(ids) for ids in state.get("campus_inner_targets", {}).values()))
    deep_done = {wid: value for wid, value in state.get("campus_deep_done", {}).items() if not inner_ids or wid in inner_ids}
    out = {"observed_at": datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).isoformat(),
           "pid": pid, "running": running, "niceness": niceness,
           "stage": state.get("stage"), "stop_at": state.get("stop_at"),
           "ways_measured": len(widths), "ways_with_data": sum(bool(v and v.get("samples")) for v in widths.values()),
           "ways_deep_with_data": sum(bool(v and v.get("deep") and v.get("samples")) for v in widths.values()),
           "cells_visited": len(state.get("cells_visited", [])), "cells_complete": len(state.get("cells_done", [])),
           "cells_target": state.get("cells_target"), "osm_cells_target": state.get("osm_cells_target"),
           "osm_area_files": len(areas), "osm_area_bytes": sum(p.stat().st_size for p in areas),
           "osm_batch_files": len(batches), "osm_batch_bytes": sum(p.stat().st_size for p in batches),
           "last_crawl_at": state.get("updated_at"), "point_cache": state.get("point_cache"),
           "point_cache_note": "requests counts cache-miss lookup attempts, including calls blocked before HTTP send; it is not an HTTP request counter",
           "portal_cooldown_until": state.get("cooldown_until"), "blocked_responses_total": state.get("blocked"),
           "campus_unique_target": state.get("campus_deep_ways_target"),
           "campus_deep_completed": len(deep_done),
           "campus_cuts_target": state.get("campus_deep_cuts_target"),
           "campus_cuts_completed": sum(x["attempted_cuts"] for x in deep_done.values()),
           "round3_progress": state.get("round3_progress"),
           "campuses": state.get("campuses", {}),
           "tide_refresher": read(ROOT / "backend/cache/flood/tide_refresh_status.json")}
    return out


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output")
    args = parser.parse_args()
    data = report()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if args.output:
        (ROOT / args.output).write_text(text)
    print(text)
