"""Fetch/validate the latest official Phú An 5-day bulletin; no AI or keys required."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.tide_refresh import refresh

if __name__ == "__main__":
    result = refresh()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(1 if result["state"] == "error" else 0)
