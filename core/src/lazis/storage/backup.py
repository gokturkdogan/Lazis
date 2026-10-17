"""Encrypted snapshots via ``sqlcipher_export`` (consistent copy while the app runs).

Snapshots are SQLCipher databases encrypted with the same key version as the live database,
verified after creation (opens, quick_check, plaintext-header check) and described by a JSON
manifest with a SHA-256 checksum. Restore replaces the database file only after verifying the
snapshot and only while the database is closed.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from lazis.errors import DatabaseCorruptError, StorageError
from lazis.fsutil import ensure_private_dir, ensure_private_file
from lazis.ids import utc_now_iso
from lazis.security.secrets import SecretBytes
from lazis.storage import driver
from lazis.storage.database import SIDE_FILES, apply_key, file_is_plaintext_sqlite
from lazis.storage.driver import Connection

KEY_VERSION = "v1"


@dataclass(frozen=True)
class BackupInfo:
    path: Path
    manifest_path: Path
    sha256: str
    size_bytes: int
    label: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_snapshot(path: Path, key: SecretBytes) -> None:
    if file_is_plaintext_sqlite(path):
        raise StorageError("snapshot is not encrypted")
    conn = driver.connect(path)
    try:
        apply_key(conn, key)
        try:
            rows = conn.execute("PRAGMA quick_check").fetchall()
        except driver.DatabaseError:
            raise StorageError("snapshot cannot be opened with the key") from None
        if rows != [("ok",)]:
            raise DatabaseCorruptError("snapshot failed quick_check")
    finally:
        conn.close()


def create_snapshot(
    conn: Connection, key: SecretBytes, backup_dir: Path, *, label: str, keep: int
) -> BackupInfo:
    """Export the open database into a new encrypted file. Runs in the DB thread."""
    ensure_private_dir(backup_dir)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = backup_dir / f"lazis-{stamp}-{label}.db"
    conn.execute("ATTACH DATABASE ? AS lazis_backup KEY ?", (str(dest), f"x'{key.hex()}'"))
    try:
        conn.execute("SELECT sqlcipher_export('lazis_backup')")
    finally:
        conn.execute("DETACH DATABASE lazis_backup")
    ensure_private_file(dest)
    verify_snapshot(dest, key)
    info = BackupInfo(
        path=dest,
        manifest_path=dest.with_suffix(".json"),
        sha256=_sha256(dest),
        size_bytes=dest.stat().st_size,
        label=label,
    )
    manifest = {
        "format": 1,
        "created_at": utc_now_iso(),
        "label": label,
        "file": dest.name,
        "sha256": info.sha256,
        "size_bytes": info.size_bytes,
        "key_version": KEY_VERSION,
    }
    info.manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ensure_private_file(info.manifest_path)
    _apply_retention(backup_dir, keep)
    return info


def _apply_retention(backup_dir: Path, keep: int) -> None:
    snapshots = sorted(backup_dir.glob("lazis-*.db"))
    for old in snapshots[: max(0, len(snapshots) - keep)]:
        old.unlink(missing_ok=True)
        old.with_suffix(".json").unlink(missing_ok=True)


def restore_snapshot(snapshot: Path, target: Path, key: SecretBytes) -> None:
    """Replace ``target`` with ``snapshot`` (database must be closed). Verifies first."""
    manifest_path = snapshot.with_suffix(".json")
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text("utf-8"))
        if manifest.get("sha256") != _sha256(snapshot):
            raise StorageError("snapshot checksum does not match its manifest")
    verify_snapshot(snapshot, key)
    temp = target.with_name(f".{target.name}.restore")
    shutil.copyfile(snapshot, temp)
    ensure_private_file(temp)
    for suffix in SIDE_FILES:
        Path(f"{target}{suffix}").unlink(missing_ok=True)
    os.replace(temp, target)
