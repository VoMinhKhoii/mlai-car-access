"""Monotonic deadlines for background work: every upstream call gets min(its own limit, time left)."""
from __future__ import annotations

import time


class Expired(Exception):
    """The job's deadline passed; stop issuing upstream requests."""


def timeout(deadline: float | None, limit: float, exc: type[Exception] = Expired) -> float:
    """HTTP timeout for the next call, or `exc` when (almost) no time is left. `deadline` is time.monotonic()."""
    if deadline is None:
        return limit
    left = deadline - time.monotonic()
    if left <= 0.5:
        raise exc("collection deadline exceeded")
    return min(limit, left)
