"""Encrypted snapshots and crash-safe restore.

Snapshots (``create_snapshot``) are made with ``sqlcipher_export`` from the open database,
encrypted with the same key version, made durable, verified (opens with the key,
``quick_check``, ``cipher_integrity_check``, LAZIS schema present) and described by a JSON
manifest with a SHA-256 checksum. A failed export leaves no partial file behind.

Restore (``restore_snapshot``) never deletes the database it replaces. Protocol, all inside the
data directory (one filesystem, so every rename is atomic):

1. take the data-directory lock — refused while any process has the database open;
2. finish any earlier interrupted restore (:func:`recover_interrupted_restore`);
3. validate the snapshot: manifest present and matching, opens with the key, integrity
   checks pass, LAZIS schema not newer than this application;
4. stage: durable copy to ``.restore/staged.db`` (0600) and verify the copy again;
5. write the journal ``.restore/journal.json`` (state ``swapping`` + the exact list of files
   about to be moved), then move the current ``lazis.db`` and its ``-wal``/``-shm``/``-journal``
   files into ``.restore/previous/`` (renames, nothing deleted — un-checkpointed WAL data
   survives);
6. install: rename ``staged.db`` → ``lazis.db`` and verify the installed file;
7. **commit point:** atomically rewrite the journal with state ``committed``;
8. finish: rename ``.restore/previous/`` → ``backups/pre-restore-<stamp>/`` (if anything was
   moved) and remove ``.restore/``.

An error before step 7 rolls back immediately. A crash before step 7 is rolled back at the
next start (``open_storage`` calls :func:`recover_interrupted_restore`); a crash after it is
completed. Recovery reads the journal instead of guessing from which files exist: with an
empty previous directory (fresh profile, or only orphan ``-wal``/``-shm`` files) the files
alone cannot tell an uncommitted install from a finished one. Recovery is idempotent.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from lazis.errors import DatabaseCorruptError, RestoreError, StorageError
from lazis.fsutil import ensure_private_dir, ensure_private_file
from lazis.ids import utc_now_iso
from lazis.security.secrets import SecretBytes
from lazis.storage import driver
from lazis.storage.database import SIDE_FILES, apply_key, file_is_plaintext_sqlite
from lazis.storage.driver import Connection
from lazis.storage.lock import DataDirLock
from lazis.storage.migrations import load_migrations

KEY_VERSION = "v1"
RESTORE_DIRNAME = ".restore"
PRE_RESTORE_PREFIX = "pre-restore-"
PRE_RESTORE_KEEP = 3
JOURNAL_NAME = "journal.json"
_PRE_RESTORE_NAME = re.compile(r"^pre-restore-[0-9]{8}T[0-9]{12}Z$")
_LABEL = re.compile(r"^[a-z0-9-]{1,40}$")
_CHUNK = 1 << 20

# Test seam: called with a step name at each critical point of a restore.
FaultHook = Callable[[str], None]


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    label: str


@dataclass(frozen=True)
class RestoreResult:
    restored_from: Path
    previous_copy: Path | None  # where the replaced database was kept (None: there was none)


# ----- durable file helpers -------------------------------------------------------------
def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _full_fsync(fd: int) -> None:
    """``F_FULLFSYNC`` on macOS (plain fsync does not flush the drive's cache)."""
    full = getattr(fcntl, "F_FULLFSYNC", None)
    if full is not None:
        try:
            fcntl.fcntl(fd, full)
            return
        except OSError:
            pass
    os.fsync(fd)


def _fsync_path(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        if path.is_file():
            _full_fsync(fd)
        else:
            os.fsync(fd)
    finally:
        os.close(fd)


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        view = view[written:]


def _copy_durable(src: Path, dst: Path, fault: FaultHook | None) -> None:
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with src.open("rb") as handle:
            first = True
            while chunk := handle.read(_CHUNK):
                _write_all(fd, chunk)
                if first:
                    _fault(fault, "staging")
                    first = False
        _full_fsync(fd)
    finally:
        os.close(fd)


def _write_json_durable(path: Path, payload: dict[str, Any]) -> None:
    tmp = path.with_name(f".{path.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.fchmod(fd, 0o600)
        _write_all(fd, json.dumps(payload, indent=2).encode("utf-8"))
        _full_fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)
    _fsync_path(path.parent)


def _fault(fault: FaultHook | None, step: str) -> None:
    if fault is not None:
        fault(step)


# ----- verification ---------------------------------------------------------------------
def latest_schema_version() -> int:
    return max((m.version for m in load_migrations("lazis")), default=0)


def verify_snapshot(path: Path, key: SecretBytes, *, max_schema_version: int | None = None) -> int:
    """Open ``path`` with ``key`` and run every integrity check. Returns its schema version."""
    if not path.is_file():
        raise StorageError("snapshot file not found")
    if file_is_plaintext_sqlite(path):
        raise StorageError("snapshot is not encrypted")
    conn = driver.connect(path)
    try:
        apply_key(conn, key)
        try:
            quick = conn.execute("PRAGMA quick_check").fetchall()
            cipher_problems = conn.execute("PRAGMA cipher_integrity_check").fetchall()
        except driver.DatabaseError:
            raise StorageError("snapshot cannot be opened with the key") from None
        if quick != [("ok",)] or cipher_problems:
            raise DatabaseCorruptError("snapshot failed integrity checks")
        try:
            row = conn.execute("SELECT coalesce(max(version), 0) FROM schema_migrations").fetchone()
        except driver.DatabaseError:
            raise StorageError("snapshot is not a LAZIS database") from None
        version = int(row[0]) if row else 0
        if version < 1:
            raise StorageError("snapshot is not a LAZIS database")
        if max_schema_version is not None and version > max_schema_version:
            raise StorageError("snapshot schema is newer than this application")
        return version
    finally:
        conn.close()


# ----- snapshots ------------------------------------------------------------------------
def create_snapshot(
    conn: Connection, key: SecretBytes, backup_dir: Path, *, label: str, keep: int
) -> BackupInfo:
    """Export the open database into a new encrypted file. Runs in the DB thread."""
    if not _LABEL.match(label):
        raise ValueError("snapshot label must match [a-z0-9-]{1,40}")
    ensure_private_dir(backup_dir)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = backup_dir / f"lazis-{stamp}-{label}.db"
    manifest_path = dest.with_suffix(".json")
    try:
        conn.execute("ATTACH DATABASE ? AS lazis_backup KEY ?", (str(dest), f"x'{key.hex()}'"))
        try:
            conn.execute("SELECT sqlcipher_export('lazis_backup')")
        finally:
            conn.execute("DETACH DATABASE lazis_backup")
        ensure_private_file(dest)
        _fsync_path(dest)
        verify_snapshot(dest, key)
        info = BackupInfo(
            path=dest,
            manifest_path=manifest_path,
            sha256=_sha256(dest),
            size_bytes=dest.stat().st_size,
            label=label,
        )
        _write_json_durable(
            manifest_path,
            {
                "format": 1,
                "created_at": utc_now_iso(),
                "label": label,
                "file": dest.name,
                "sha256": info.sha256,
                "size_bytes": info.size_bytes,
                "key_version": KEY_VERSION,
            },
        )
    except BaseException:
        for leftover in (dest, manifest_path, *(Path(f"{dest}{s}") for s in SIDE_FILES)):
            leftover.unlink(missing_ok=True)
        raise
    _apply_retention(backup_dir, keep)
    return info


def _apply_retention(backup_dir: Path, keep: int) -> None:
    snapshots = sorted(backup_dir.glob("lazis-*.db"))
    for old in snapshots[: max(0, len(snapshots) - keep)]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def _apply_pre_restore_retention(backup_dir: Path) -> None:
    copies = sorted(p for p in backup_dir.glob(f"{PRE_RESTORE_PREFIX}*") if p.is_dir())
    for old in copies[: max(0, len(copies) - PRE_RESTORE_KEEP)]:
        shutil.rmtree(old, ignore_errors=True)


# ----- restore --------------------------------------------------------------------------
def _validate_snapshot(snapshot: Path, key: SecretBytes) -> str:
    if not snapshot.is_file():
        raise RestoreError("snapshot file not found")
    try:
        raw: object = json.loads(snapshot.with_suffix(".json").read_text("utf-8"))
    except (OSError, ValueError):
        raise RestoreError("snapshot manifest is missing or unreadable") from None
    manifest = cast("dict[str, object]", raw) if isinstance(raw, dict) else {}
    expected = manifest.get("sha256")
    if not isinstance(expected, str) or manifest.get("key_version") != KEY_VERSION:
        raise RestoreError("snapshot manifest is invalid")
    if _sha256(snapshot) != expected:
        raise RestoreError("snapshot checksum does not match its manifest")
    _verify_for_restore(snapshot, key)
    return expected


def _verify_for_restore(path: Path, key: SecretBytes) -> None:
    try:
        verify_snapshot(path, key, max_schema_version=latest_schema_version())
    except StorageError as exc:
        raise RestoreError(exc.detail or exc.code) from None


def _database_files(target: Path) -> list[str]:
    """Existing files of the database at ``target``: side files first, main file last."""
    names = [f"{target.name}{suffix}" for suffix in SIDE_FILES]
    present = [n for n in names if (target.parent / n).exists()]
    if target.exists():
        present.append(target.name)
    return present


def _read_journal(work: Path) -> dict[str, object] | None:
    """The restore journal, ``None`` if absent, ``{}`` if unreadable (treated conservatively)."""
    path = work / JOURNAL_NAME
    if not path.exists():
        return None
    try:
        raw: object = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return cast("dict[str, object]", raw) if isinstance(raw, dict) else {}


def _finish_commit(work: Path, backup_dir: Path, previous_name: str) -> Path | None:
    """After the commit point: keep the replaced files, remove the work directory.
    Idempotent — a crash in here is simply finished again at the next start."""
    previous = work / "previous"
    previous_copy: Path | None = None
    if previous.is_dir() and any(previous.iterdir()):
        ensure_private_dir(backup_dir)
        previous_copy = backup_dir / previous_name
        os.replace(previous, previous_copy)
        _fsync_path(backup_dir)
    shutil.rmtree(work)
    _fsync_path(work.parent)
    if previous_copy is not None:
        _apply_pre_restore_retention(backup_dir)
    return previous_copy


def recover_interrupted_restore(target: Path, backup_dir: Path | None = None) -> str | None:
    """Finish or undo a restore interrupted by a crash. Call while holding the data-directory
    lock. Returns ``None`` (nothing to do), ``"cleaned"`` (only staging leftovers),
    ``"rolled_back"`` (an uncommitted restore was undone) or ``"completed"`` (a committed
    restore was finished)."""
    data_dir = target.parent
    backup_dir = backup_dir or data_dir / "backups"
    target.with_name(f".{target.name}.restore").unlink(missing_ok=True)  # Phase 1 temp name
    work = data_dir / RESTORE_DIRNAME
    if not work.exists():
        return None
    journal = _read_journal(work)
    previous = work / "previous"

    if journal is not None and journal.get("state") == "committed":
        name = journal.get("previous_copy")
        if not isinstance(name, str) or not _PRE_RESTORE_NAME.match(name):
            name = PRE_RESTORE_PREFIX + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        _finish_commit(work, backup_dir, name)
        return "completed"

    saved = sorted(previous.iterdir()) if previous.is_dir() else []
    if journal is None and not saved:
        shutil.rmtree(work)  # the swap never started: only staging leftovers
        _fsync_path(data_dir)
        return "cleaned"

    # The swap started but did not commit: put the original files back, exactly.
    moved = journal.get("moved") if journal else None
    if isinstance(moved, list) and all(isinstance(n, str) for n in moved):  # pyright: ignore[reportUnknownVariableType]
        # A main file at ``target`` is the restored copy unless it was due to be moved and
        # has not been moved yet. This also covers fresh profiles (no main file to move).
        main_is_restored = target.name not in moved or (previous / target.name).exists()
    else:
        # No or unreadable journal: discard the file at ``target`` only if the original main
        # file is provably safe in ``previous`` — never risk deleting the original.
        main_is_restored = (previous / target.name).exists()
    if main_is_restored and target.exists():
        # Every original was moved before the install, so anything at the target paths
        # belongs to the unconfirmed restored copy (a copy of a snapshot that still exists).
        for path in (target, *(Path(f"{target}{s}") for s in SIDE_FILES)):
            path.unlink(missing_ok=True)
    for item in saved:
        os.replace(item, data_dir / item.name)
    _fsync_path(data_dir)
    shutil.rmtree(work)
    _fsync_path(data_dir)
    return "rolled_back"


def restore_snapshot(
    snapshot: Path,
    target: Path,
    key: SecretBytes,
    *,
    backup_dir: Path | None = None,
    lock: DataDirLock | None = None,
    fault: FaultHook | None = None,
) -> RestoreResult:
    """Replace the database at ``target`` with ``snapshot``, keeping the old one.

    The database must be closed: the data-directory lock is taken here (or ``lock`` must
    already be held by the caller), so a running backend makes this fail with
    ``instance_already_running`` and nothing is touched.
    """
    data_dir = target.parent
    backup_dir = backup_dir or data_dir / "backups"
    owned = lock is None
    if lock is None:
        lock = DataDirLock(data_dir)
        lock.acquire()
    elif not lock.held:
        raise RestoreError("restore requires the data directory lock")
    try:
        recover_interrupted_restore(target, backup_dir)
        expected_sha = _validate_snapshot(snapshot, key)
        work = ensure_private_dir(data_dir / RESTORE_DIRNAME)
        staged = work / "staged.db"
        previous = work / "previous"
        try:
            _copy_durable(snapshot, staged, fault)
            _fault(fault, "staged")
            if _sha256(staged) != expected_sha:
                raise RestoreError("staged copy does not match the snapshot")
            _verify_for_restore(staged, key)
            ensure_private_dir(previous)
            moved = _database_files(target)
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            journal: dict[str, Any] = {
                "format": 1,
                "state": "swapping",
                "moved": moved,
                "previous_copy": f"{PRE_RESTORE_PREFIX}{stamp}",
            }
            _write_json_durable(work / JOURNAL_NAME, journal)
            _fault(fault, "journal")
            for name in moved:
                os.replace(data_dir / name, previous / name)
                _fault(fault, f"moved:{name}")
            _fsync_path(previous)
            _fsync_path(data_dir)
            os.replace(staged, target)
            ensure_private_file(target)
            _fsync_path(data_dir)
            _fault(fault, "installed")
            _verify_for_restore(target, key)
            _fault(fault, "verified")
            _write_json_durable(work / JOURNAL_NAME, {**journal, "state": "committed"})
        except Exception as exc:
            try:
                recover_interrupted_restore(target, backup_dir)
            except Exception as rollback_exc:
                # The previous files are still under .restore/previous; the next start
                # (open_storage) retries the rollback before opening anything.
                raise RestoreError(
                    "restore failed and the rollback is incomplete; it is retried at next start"
                ) from rollback_exc
            if isinstance(exc, RestoreError):
                raise exc from None
            raise RestoreError(f"restore aborted and rolled back ({type(exc).__name__})") from exc

        # Committed (the journal says so): from here on the restored database is current.
        _fault(fault, "committed")
        previous_copy = _finish_commit(work, backup_dir, journal["previous_copy"])
        return RestoreResult(restored_from=snapshot, previous_copy=previous_copy)
    finally:
        if owned:
            lock.release()
