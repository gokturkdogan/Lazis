"""Encryption is verified, not assumed (Phase 1 §9)."""

from __future__ import annotations

import secrets
import shutil
import sqlite3  # stdlib, plaintext SQLite — used only to prove it cannot read our files
import stat
import subprocess
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.errors import (
    DatabaseKeyError,
    EncryptionUnavailableError,
    PlaintextDatabaseError,
)
from lazis.security.secrets import SecretBytes
from lazis.storage import driver, open_storage
from lazis.storage.database import PLAINTEXT_HEADER, Database
from lazis.storage.repositories import get_setting, set_setting

MARKER = "SENTETIK-GIZLI-DEGER-7f3a91"


def _write_marker(section: StorageSection, key: SecretBytes) -> None:
    handle = open_storage(section, key, app_version="test")
    try:
        handle.db.run_sync(lambda c: set_setting(c, "test.marker", MARKER, actor="system"))
    finally:
        handle.db.close()


def test_new_database_is_encrypted_on_disk(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _write_marker(storage_section, key)
    path = storage_section.database_path
    assert path.read_bytes()[: len(PLAINTEXT_HEADER)] != PLAINTEXT_HEADER
    for candidate in [path, *(Path(f"{path}{s}") for s in ("-wal", "-shm"))]:
        if candidate.exists():
            assert MARKER.encode() not in candidate.read_bytes(), candidate.name


def test_wal_is_encrypted_while_database_is_open(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        handle.db.run_sync(lambda c: set_setting(c, "test.marker", MARKER, actor="system"))
        wal = Path(f"{storage_section.database_path}-wal")
        assert wal.exists() and wal.stat().st_size > 0
        assert MARKER.encode() not in wal.read_bytes()
    finally:
        handle.db.close()


def test_opens_with_correct_key_and_data_survives_restart(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _write_marker(storage_section, key)
    first = open_storage(storage_section, key, app_version="test")
    instance = first.meta["instance_id"]
    first.db.close()
    second = open_storage(storage_section, key, app_version="test")
    try:
        assert second.db.run_sync(lambda c: get_setting(c, "test.marker")) == MARKER
        assert second.meta["instance_id"] == instance
        assert second.migration.applied == ()  # nothing re-applied on restart
    finally:
        second.db.close()


def test_wrong_key_is_rejected(storage_section: StorageSection, key: SecretBytes) -> None:
    _write_marker(storage_section, key)
    with pytest.raises(DatabaseKeyError):
        open_storage(storage_section, SecretBytes(secrets.token_bytes(32)), app_version="test")


def test_stdlib_sqlite_cannot_read_the_database(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _write_marker(storage_section, key)
    conn = sqlite3.connect(storage_section.database_path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="not a database"):
            conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        conn.close()


@pytest.mark.skipif(shutil.which("sqlite3") is None, reason="system sqlite3 CLI not available")
def test_system_sqlite_cli_cannot_read_the_database(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _write_marker(storage_section, key)
    result = subprocess.run(
        ["sqlite3", str(storage_section.database_path), "SELECT count(*) FROM sqlite_master;"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "not a database" in result.stderr


SQLCIPHER_CLI = "/opt/homebrew/opt/sqlcipher/bin/sqlcipher"


@pytest.mark.skipif(not Path(SQLCIPHER_CLI).exists(), reason="Homebrew sqlcipher CLI not installed")
def test_independent_sqlcipher_cli_reads_it_only_with_the_key(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    """Cross-check with a separately built SQLCipher (key passed via stdin, not argv)."""
    _write_marker(storage_section, key)
    script = f"PRAGMA key = \"x'{key.hex()}'\";\nSELECT value_json FROM settings;\n"
    ok = subprocess.run(
        [SQLCIPHER_CLI, str(storage_section.database_path)],
        input=script,
        capture_output=True,
        text=True,
        check=False,
    )
    assert MARKER in ok.stdout
    wrong = f"PRAGMA key = \"x'{secrets.token_hex(32)}'\";\nSELECT value_json FROM settings;\n"
    bad = subprocess.run(
        [SQLCIPHER_CLI, str(storage_section.database_path)],
        input=wrong,
        capture_output=True,
        text=True,
        check=False,
    )
    assert MARKER not in bad.stdout
    assert "not a database" in bad.stdout + bad.stderr


def test_plaintext_file_is_refused(storage_section: StorageSection, key: SecretBytes) -> None:
    storage_section.data_dir.mkdir(parents=True)
    plain = sqlite3.connect(storage_section.database_path)
    plain.execute("CREATE TABLE t (x)")
    plain.commit()
    plain.close()
    with pytest.raises(PlaintextDatabaseError):
        open_storage(storage_section, key, app_version="test")


def test_no_fallback_when_sqlcipher_is_inactive(
    storage_section: StorageSection, key: SecretBytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(driver, "cipher_version", lambda _conn: None)
    with pytest.raises(EncryptionUnavailableError):
        open_storage(storage_section, key, app_version="test")
    assert not storage_section.database_path.exists() or (
        storage_section.database_path.stat().st_size == 0
    )


def test_database_open_refuses_inactive_cipher_even_if_driver_check_is_bypassed(
    storage_section: StorageSection, key: SecretBytes, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = Database(storage_section.database_path, key)
    monkeypatch.setattr(driver, "cipher_version", lambda _conn: None)
    with pytest.raises(EncryptionUnavailableError):
        db.open()
    db.close()


def test_files_and_directories_are_private(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _write_marker(storage_section, key)
    assert stat.S_IMODE(storage_section.data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(storage_section.database_path.stat().st_mode) == 0o600


def test_integrity_checks_pass(storage_section: StorageSection, key: SecretBytes) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        assert handle.db.quick_check() == "ok"
        assert handle.db.cipher_integrity_check() == []
        status = handle.db.status()
        assert status.encrypted and status.encryption_verified
        assert status.cipher_version.startswith("4.")
    finally:
        handle.db.close()
