"""Crash-safe JSON state files and bounded in-memory caches.

Every state file the backend owns (flags, quotas, pending reports, area builds, camera jobs) is written through
`write_json`: a temp file in the same directory, fsync, then os.replace, so a crash leaves either the old or the new
file and never a half-written one.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from collections import OrderedDict
from pathlib import Path


class CorruptState(Exception):
    """A state file exists but cannot be parsed; callers that guard safety or spend must fail closed."""


def write_json(path: Path, data, indent: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(path: Path, default):
    """The parsed file, `default` if it does not exist, CorruptState if it exists but is not valid JSON."""
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorruptState(f"{path.name}: {exc}") from exc


class LRU:
    """Thread-safe bounded mapping: the least recently used entry is evicted past `size`."""

    def __init__(self, size: int) -> None:
        self.size = size
        self._data: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key, default=None):
        with self._lock:
            if key not in self._data:
                return default
            self._data.move_to_end(key)
            return self._data[key]

    def put(self, key, value) -> None:
        with self._lock:
            self._data[key] = value
            self._data.move_to_end(key)
            while len(self._data) > self.size:
                self._data.popitem(last=False)

    def __contains__(self, key) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    def pop(self, key, default=None):
        with self._lock:
            return self._data.pop(key, default)
