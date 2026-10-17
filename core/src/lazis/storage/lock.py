"""Exclusive lock on a data directory.

Held by the running backend for its whole lifetime and taken by maintenance operations
(restore), so a database is never replaced while a process has it open. ``flock`` locks are
released by the kernel when the holder exits, even after a crash, so a leftover lock file is
never "stale".
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType

from lazis.errors import InstanceLockedError
from lazis.fsutil import ensure_private_dir

LOCK_FILENAME = ".lazis-core.lock"


class DataDirLock:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self._path = data_dir / LOCK_FILENAME
        self._fd: int | None = None

    @property
    def held(self) -> bool:
        return self._fd is not None

    def acquire(self) -> None:
        ensure_private_dir(self.data_dir)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            raise InstanceLockedError("another process holds the data directory lock") from None
        os.fchmod(fd, 0o600)
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fd = fd

    def release(self) -> None:
        if self._fd is not None:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
            self._fd = None

    def __enter__(self) -> DataDirLock:
        self.acquire()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.release()
