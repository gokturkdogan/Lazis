"""Private filesystem helpers: directories 0700, files 0600, owned by the current user."""

from __future__ import annotations

import os
import stat
from pathlib import Path

DIR_MODE = 0o700
FILE_MODE = 0o600


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(mode=DIR_MODE, parents=True, exist_ok=True)
    os.chmod(path, DIR_MODE)
    return path


def ensure_private_file(path: Path) -> None:
    if path.exists():
        os.chmod(path, FILE_MODE)


def is_private(path: Path) -> bool:
    """True if only the owner (the current user) can access ``path``."""
    info = path.stat()
    if info.st_uid != os.getuid():
        return False
    return stat.S_IMODE(info.st_mode) & 0o077 == 0
