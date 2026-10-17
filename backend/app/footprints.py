"""Read-only footprint product; independent of the cadastral portal.

Reload after mtime/size changes; retain the last good snapshot on partial writes.
"""
from __future__ import annotations

import json
import threading

from .config import CACHE

PATH = CACHE / "live/footprint_widths.json"
_lock = threading.Lock()
_stamp = None
_data: dict = {}


def snapshot() -> tuple[tuple | None, dict]:
    global _stamp, _data
    with _lock:
        try:
            st = PATH.stat()
        except FileNotFoundError:
            _stamp, _data = None, {}
            return _stamp, _data
        stamp = (st.st_mtime_ns, st.st_size)
        if stamp != _stamp:
            try:
                data = json.loads(PATH.read_text())
                if data.get("schema_version") != 1 or data.get("tier") != "Inferred":
                    raise ValueError("Unsupported footprint cache")
                if not isinstance(data.get("ways"), dict):
                    raise ValueError("Missing footprint ways")
            except (OSError, ValueError):
                return _stamp, _data
            _stamp, _data = stamp, data
        return _stamp, _data
