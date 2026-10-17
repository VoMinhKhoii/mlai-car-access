"""`fcntl.flock` for every platform the backend runs on.

POSIX re-exports the real module. Windows has no `fcntl`, so `flock` is emulated with
`msvcrt.locking` on one byte far past any real content (Windows locks are mandatory, so
locking the data bytes would block the lock holder's own reads through other handles).
As with `flock`, closing the file releases the lock.
"""
from __future__ import annotations

import os
import sys
import time

if sys.platform != "win32":
    from fcntl import LOCK_EX, LOCK_NB, LOCK_SH, LOCK_UN, flock  # noqa: F401
else:
    import msvcrt

    LOCK_SH, LOCK_EX, LOCK_NB, LOCK_UN = 1, 2, 4, 8
    _LOCK_OFFSET = 0x7FFFFFFF  # beyond any lock/state file the app writes

    def flock(file, operation: int) -> None:
        fd = file if isinstance(file, int) else file.fileno()
        here = os.lseek(fd, 0, os.SEEK_CUR)
        try:
            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            if operation & LOCK_UN:
                try:
                    msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass  # not locked: flock(LOCK_UN) is a no-op too
                return
            while True:
                try:
                    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                    return
                except OSError as exc:
                    if operation & LOCK_NB:
                        raise BlockingIOError(*exc.args) from exc
                    time.sleep(0.05)  # LK_LOCK gives up after ~10 s; flock(LOCK_EX) waits forever
        finally:
            os.lseek(fd, here, os.SEEK_SET)
