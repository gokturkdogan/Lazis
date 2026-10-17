"""The data-directory lock that keeps restores away from an open database."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from lazis.errors import InstanceLockedError
from lazis.storage.lock import LOCK_FILENAME, DataDirLock


def test_second_holder_is_refused_even_in_the_same_process(tmp_path: Path) -> None:
    # flock locks belong to the open file description, so a second open in the same process
    # conflicts too — restore relies on this to refuse while this process has the DB open.
    with DataDirLock(tmp_path), pytest.raises(InstanceLockedError):
        DataDirLock(tmp_path).acquire()
    with DataDirLock(tmp_path) as again:
        assert again.held
    assert not again.held


def test_lock_file_is_private_with_a_permissive_umask(tmp_path: Path) -> None:
    old = os.umask(0o022)
    try:
        with DataDirLock(tmp_path / "data"):
            pass
    finally:
        os.umask(old)
    assert stat.S_IMODE((tmp_path / "data").stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "data" / LOCK_FILENAME).stat().st_mode) == 0o600
