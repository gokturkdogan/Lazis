"""Restore must never destroy the last valid copy of the data (failure injection).

The "original" database used here is a crash image: it was copied while the backend had it
open, so its newest committed value lives only in ``lazis.db-wal``. The Phase 1 restore
deleted the WAL before replacing the file; these tests pin down that every failure path now
leaves the original — WAL included — byte-for-byte in place. Synthetic data only.
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.errors import InstanceLockedError, RestoreError
from lazis.security.secrets import SecretBytes
from lazis.storage import driver, open_storage
from lazis.storage.backup import (
    RESTORE_DIRNAME,
    create_snapshot,
    recover_interrupted_restore,
    restore_snapshot,
)
from lazis.storage.database import apply_key
from lazis.storage.lock import DataDirLock
from lazis.storage.repositories import get_setting, set_setting

SNAPSHOT_VALUE = "snapshot-value"
LATEST_VALUE = "latest-in-wal"
DB_FILES = ("lazis.db", "lazis.db-wal", "lazis.db-shm")


def _fingerprint(data_dir: Path) -> dict[str, str]:
    return {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(data_dir.glob("lazis.db*"))
        if p.is_file()
    }


def _read_value(section: StorageSection, key: SecretBytes) -> object:
    handle = open_storage(section, key, app_version="test")
    try:
        return handle.db.run_sync(lambda c: get_setting(c, "k"))
    finally:
        handle.db.close()


@pytest.fixture
def crashed(tmp_path: Path, key: SecretBytes) -> tuple[StorageSection, Path]:
    """A data directory whose newest value exists only in the WAL, plus a valid snapshot."""
    live = StorageSection(data_dir=tmp_path / "live")
    handle = open_storage(live, key, app_version="test")
    try:
        handle.db.run_sync(lambda c: set_setting(c, "k", SNAPSHOT_VALUE, actor="system"))
        info = handle.db.run_sync(
            lambda c: create_snapshot(c, key, live.backup_dir, label="manual", keep=5)
        )
        handle.db.run_sync(lambda c: set_setting(c, "k", LATEST_VALUE, actor="system"))
        section = StorageSection(data_dir=tmp_path / "crashed")
        section.data_dir.mkdir(mode=0o700)
        for name in DB_FILES:  # copied while open = what a crash leaves behind
            shutil.copy2(live.data_dir / name, section.data_dir / name)
        shutil.copytree(live.backup_dir, section.backup_dir)
    finally:
        handle.db.close()
    assert (section.data_dir / "lazis.db-wal").stat().st_size > 0
    return section, section.backup_dir / info.path.name


def _assert_original_intact(
    section: StorageSection, key: SecretBytes, before: dict[str, str]
) -> None:
    assert not (section.data_dir / RESTORE_DIRNAME).exists()
    assert _fingerprint(section.data_dir) == before
    assert _read_value(section, key) == LATEST_VALUE


def test_wal_holds_data_that_the_main_file_alone_does_not(
    crashed: tuple[StorageSection, Path], key: SecretBytes, tmp_path: Path
) -> None:
    """Why deleting -wal/-shm before a replace was dangerous."""
    section, _ = crashed
    main_only = StorageSection(data_dir=tmp_path / "main-only")
    main_only.data_dir.mkdir(mode=0o700)
    shutil.copy2(section.data_dir / "lazis.db", main_only.data_dir / "lazis.db")
    assert _read_value(main_only, key) != LATEST_VALUE
    assert _read_value(section, key) == LATEST_VALUE


def test_successful_restore_keeps_the_previous_database(
    crashed: tuple[StorageSection, Path], key: SecretBytes, tmp_path: Path
) -> None:
    section, snapshot = crashed
    before = _fingerprint(section.data_dir)
    result = restore_snapshot(snapshot, section.database_path, key)
    assert not (section.data_dir / RESTORE_DIRNAME).exists()
    assert _read_value(section, key) == SNAPSHOT_VALUE

    # The replaced database (with its WAL) is kept, untouched and private.
    assert result.previous_copy is not None
    kept = result.previous_copy
    assert kept.parent == section.backup_dir
    assert _fingerprint(kept) == before
    assert stat.S_IMODE(kept.stat().st_mode) == 0o700
    assert stat.S_IMODE(section.database_path.stat().st_mode) == 0o600
    copy = StorageSection(data_dir=tmp_path / "kept-copy")
    shutil.copytree(kept, copy.data_dir)
    assert _read_value(copy, key) == LATEST_VALUE


def test_restore_into_an_empty_directory(
    crashed: tuple[StorageSection, Path], key: SecretBytes, tmp_path: Path
) -> None:
    _, snapshot = crashed
    fresh = StorageSection(data_dir=tmp_path / "fresh")
    fresh.data_dir.mkdir(mode=0o700)
    result = restore_snapshot(snapshot, fresh.database_path, key)
    assert result.previous_copy is None
    assert _read_value(fresh, key) == SNAPSHOT_VALUE


# ----- invalid backups: rejected before anything is touched -----------------------------
def _write_manifest(snapshot: Path) -> None:
    manifest = json.loads(snapshot.with_suffix(".json").read_text())
    manifest["sha256"] = hashlib.sha256(snapshot.read_bytes()).hexdigest()
    snapshot.with_suffix(".json").write_text(json.dumps(manifest))


def _random_bytes(snapshot: Path, _key: SecretBytes) -> None:
    snapshot.write_bytes(secrets.token_bytes(8192))
    _write_manifest(snapshot)


def _bit_flip_manifest_unchanged(snapshot: Path, _key: SecretBytes) -> None:
    data = bytearray(snapshot.read_bytes())
    data[-100] ^= 0xFF
    snapshot.write_bytes(bytes(data))


def _bit_flip_manifest_rewritten(snapshot: Path, _key: SecretBytes) -> None:
    data = bytearray(snapshot.read_bytes())
    data[len(data) // 2] ^= 0xFF  # passes the checksum, fails the page HMAC
    snapshot.write_bytes(bytes(data))
    _write_manifest(snapshot)


def _manifest_missing(snapshot: Path, _key: SecretBytes) -> None:
    snapshot.with_suffix(".json").unlink()


def _truncated(snapshot: Path, _key: SecretBytes) -> None:
    snapshot.write_bytes(snapshot.read_bytes()[:4096])
    _write_manifest(snapshot)


def _plaintext_sqlite(snapshot: Path, _key: SecretBytes) -> None:
    import sqlite3

    snapshot.unlink()
    conn = sqlite3.connect(snapshot)
    conn.execute("CREATE TABLE schema_migrations (version INTEGER)")
    conn.execute("INSERT INTO schema_migrations VALUES (1)")
    conn.commit()
    conn.close()
    _write_manifest(snapshot)


def _not_a_lazis_database(snapshot: Path, key: SecretBytes) -> None:
    snapshot.unlink()
    conn = driver.connect(snapshot)
    apply_key(conn, key)
    conn.execute("CREATE TABLE other (x INTEGER)")
    conn.close()
    _write_manifest(snapshot)


def _schema_newer_than_app(snapshot: Path, key: SecretBytes) -> None:
    conn = driver.connect(snapshot)
    apply_key(conn, key)
    conn.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (999, 'future', 'x', '2099-01-01')"
    )
    conn.close()
    _write_manifest(snapshot)


@pytest.mark.parametrize(
    "damage",
    [
        _random_bytes,
        _bit_flip_manifest_unchanged,
        _bit_flip_manifest_rewritten,
        _manifest_missing,
        _truncated,
        _plaintext_sqlite,
        _not_a_lazis_database,
        _schema_newer_than_app,
    ],
)
def test_invalid_backups_are_rejected_without_touching_the_database(
    crashed: tuple[StorageSection, Path],
    key: SecretBytes,
    damage: Callable[[Path, SecretBytes], None],
) -> None:
    section, snapshot = crashed
    damage(snapshot, key)
    before = _fingerprint(section.data_dir)
    with pytest.raises(RestoreError):
        restore_snapshot(snapshot, section.database_path, key)
    _assert_original_intact(section, key, before)


def test_wrong_key_is_rejected_without_touching_the_database(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    before = _fingerprint(section.data_dir)
    with pytest.raises(RestoreError):
        restore_snapshot(snapshot, section.database_path, SecretBytes(secrets.token_bytes(32)))
    _assert_original_intact(section, key, before)


# ----- failures during the restore: rolled back immediately -----------------------------
def _raise(error: BaseException) -> Callable[[str], None]:
    def fault(_step: str) -> None:
        raise error

    return fault


@pytest.mark.parametrize(
    ("step", "error"),
    [
        ("staging", OSError(errno.ENOSPC, "No space left on device")),
        ("staged", RuntimeError("injected")),
        ("moved:lazis.db-wal", PermissionError(errno.EACCES, "Permission denied")),
        ("moved:lazis.db-shm", OSError(errno.EIO, "I/O error")),
        ("moved:lazis.db", RuntimeError("injected")),
        ("installed", OSError(errno.ENOSPC, "No space left on device")),
        ("verified", RuntimeError("injected")),
    ],
)
def test_failure_at_each_step_rolls_back(
    crashed: tuple[StorageSection, Path], key: SecretBytes, step: str, error: BaseException
) -> None:
    section, snapshot = crashed
    before = _fingerprint(section.data_dir)

    def fault(current: str) -> None:
        if current == step:
            raise error

    with pytest.raises(RestoreError):
        restore_snapshot(snapshot, section.database_path, key, fault=fault)
    _assert_original_intact(section, key, before)


def test_real_permission_error_leaves_original_and_is_cleaned_up_at_next_start(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    """The data directory turns read-only mid-restore: the move fails *and* the rollback
    cannot clean up. Nothing is lost; the next start finishes the cleanup."""
    section, snapshot = crashed
    before = _fingerprint(section.data_dir)

    def fault(step: str) -> None:
        if step == "staged":
            os.chmod(section.data_dir, 0o500)

    try:
        with pytest.raises(RestoreError, match="rollback is incomplete"):
            restore_snapshot(snapshot, section.database_path, key, fault=fault)
    finally:
        os.chmod(section.data_dir, 0o700)
    assert _fingerprint(section.data_dir) == before
    assert (section.data_dir / RESTORE_DIRNAME).exists()  # leftover staging
    assert _read_value(section, key) == LATEST_VALUE  # open_storage recovers first
    assert not (section.data_dir / RESTORE_DIRNAME).exists()


# ----- crashes (process killed) at each step: recovered at the next start ----------------
CRASH = r"""
import json, os, sys
from pathlib import Path
from lazis.security.secrets import SecretBytes
from lazis.storage.backup import restore_snapshot
args = json.loads(sys.stdin.readline())
def fault(step):
    if step == args["step"]:
        os._exit(77)  # no cleanup, no rollback: like SIGKILL or power loss
restore_snapshot(Path(args["snapshot"]), Path(args["target"]),
                 SecretBytes(bytes.fromhex(args["key"])), fault=fault)
"""


@pytest.mark.parametrize(
    "step",
    [
        "staging",
        "staged",
        "moved:lazis.db-wal",
        "moved:lazis.db-shm",
        "moved:lazis.db",
        "installed",
        "verified",
    ],
)
def test_crash_before_commit_is_rolled_back_at_next_start(
    crashed: tuple[StorageSection, Path], key: SecretBytes, step: str
) -> None:
    section, snapshot = crashed
    before = _fingerprint(section.data_dir)
    args = {
        "snapshot": str(snapshot),
        "target": str(section.database_path),
        "key": key.hex(),  # synthetic test key, passed on stdin like the real app does
        "step": step,
    }
    proc = subprocess.run(
        [sys.executable, "-c", CRASH], input=json.dumps(args) + "\n", text=True, timeout=60
    )
    assert proc.returncode == 77
    assert (section.data_dir / RESTORE_DIRNAME).exists()

    with DataDirLock(section.data_dir):
        outcome = recover_interrupted_restore(section.database_path)
        assert outcome in ("rolled_back", "cleaned")
        assert recover_interrupted_restore(section.database_path) is None  # idempotent
    _assert_original_intact(section, key, before)


def test_crash_after_commit_keeps_the_restored_database(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    args = {
        "snapshot": str(snapshot),
        "target": str(section.database_path),
        "key": key.hex(),
        "step": "committed",
    }
    proc = subprocess.run(
        [sys.executable, "-c", CRASH], input=json.dumps(args) + "\n", text=True, timeout=60
    )
    assert proc.returncode == 77
    assert _read_value(section, key) == SNAPSHOT_VALUE  # open_storage finishes the cleanup
    assert not (section.data_dir / RESTORE_DIRNAME).exists()
    assert len(list(section.backup_dir.glob("pre-restore-*"))) == 1


def test_interrupted_restore_is_recovered_by_open_storage_and_audited(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    args = {
        "snapshot": str(snapshot),
        "target": str(section.database_path),
        "key": key.hex(),
        "step": "installed",
    }
    subprocess.run(
        [sys.executable, "-c", CRASH], input=json.dumps(args) + "\n", text=True, timeout=60
    )
    handle = open_storage(section, key, app_version="test")
    try:
        assert handle.db.run_sync(lambda c: get_setting(c, "k")) == LATEST_VALUE
        rows = handle.db.run_sync(
            lambda c: c.execute(
                "SELECT reason_code FROM audit_log WHERE action = 'restore_recovered'"
            ).fetchall()
        )
        assert rows == [("rolled_back",)]
    finally:
        handle.db.close()


# ----- concurrency and locking ----------------------------------------------------------
def test_restore_is_refused_while_the_database_is_open(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    handle = open_storage(section, key, app_version="test")
    try:
        with pytest.raises(InstanceLockedError):
            restore_snapshot(snapshot, section.database_path, key)
        assert not (section.data_dir / RESTORE_DIRNAME).exists()
    finally:
        handle.db.close()
    assert _read_value(section, key) == LATEST_VALUE


def test_restore_with_a_lock_the_caller_does_not_hold_is_refused(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    with pytest.raises(RestoreError):
        restore_snapshot(snapshot, section.database_path, key, lock=DataDirLock(section.data_dir))
    with DataDirLock(section.data_dir) as held:
        restore_snapshot(snapshot, section.database_path, key, lock=held)
    assert _read_value(section, key) == SNAPSHOT_VALUE


def test_previous_copies_are_retained_with_a_limit(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, snapshot = crashed
    for _ in range(5):
        restore_snapshot(snapshot, section.database_path, key)
    assert len(list(section.backup_dir.glob("pre-restore-*"))) == 3


def test_leftover_phase1_temp_file_is_removed(
    crashed: tuple[StorageSection, Path], key: SecretBytes
) -> None:
    section, _ = crashed
    legacy = section.data_dir / ".lazis.db.restore"
    legacy.write_bytes(b"partial")
    assert _read_value(section, key) == LATEST_VALUE
    assert not legacy.exists()


# ----- snapshots ------------------------------------------------------------------------
def test_failed_snapshot_leaves_no_partial_files(
    storage_section: StorageSection, key: SecretBytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    import lazis.storage.backup as backup

    handle = open_storage(storage_section, key, app_version="test")
    try:

        def broken_verify(*_args: object, **_kwargs: object) -> int:
            raise RuntimeError("injected")

        monkeypatch.setattr(backup, "verify_snapshot", broken_verify)
        with pytest.raises(RuntimeError):
            handle.db.run_sync(
                lambda c: create_snapshot(
                    c, key, storage_section.backup_dir, label="manual", keep=5
                )
            )
        assert list(storage_section.backup_dir.iterdir()) == []
        with pytest.raises(ValueError):
            handle.db.run_sync(
                lambda c: create_snapshot(
                    c, key, storage_section.backup_dir, label="../evil", keep=5
                )
            )
    finally:
        handle.db.close()


def test_snapshot_files_are_private_even_with_a_permissive_umask(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    old = os.umask(0o022)
    try:
        handle = open_storage(storage_section, key, app_version="test")
        try:
            info = handle.db.run_sync(
                lambda c: create_snapshot(
                    c, key, storage_section.backup_dir, label="manual", keep=5
                )
            )
        finally:
            handle.db.close()
    finally:
        os.umask(old)
    assert stat.S_IMODE(storage_section.backup_dir.stat().st_mode) == 0o700
    for path in (info.path, info.manifest_path):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def _logical_dump(conn: driver.Connection) -> dict[str, tuple[int, str]]:
    """Per table: row count and a checksum over every row (SEC-05)."""
    tables = [
        str(r[0])
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name"
        ).fetchall()
    ]
    dump: dict[str, tuple[int, str]] = {}
    for table in tables:
        rows = conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid').fetchall()
        dump[table] = (len(rows), hashlib.sha256(repr(rows).encode()).hexdigest())
    return dump


def test_restore_yields_a_logically_identical_database(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    """SEC-05: backup → restore gives identical row counts and checksums for every table."""
    handle = open_storage(storage_section, key, app_version="test")
    try:
        for i in range(25):
            handle.db.run_sync(lambda c, i=i: set_setting(c, f"k{i}", {"n": i}, actor="system"))
        expected = handle.db.run_sync(_logical_dump)
        info = handle.db.run_sync(
            lambda c: create_snapshot(c, key, storage_section.backup_dir, label="manual", keep=5)
        )
        handle.db.run_sync(lambda c: set_setting(c, "k0", "changed later", actor="system"))
    finally:
        handle.db.close()
    restore_snapshot(info.path, storage_section.database_path, key)
    restored = open_storage(storage_section, key, app_version="test")
    try:
        actual = restored.db.run_sync(_logical_dump)
    finally:
        restored.db.close()
    assert actual == expected  # every table, including history and audit_log
    assert expected["settings"][0] == 25 and expected["history"][0] >= 25
