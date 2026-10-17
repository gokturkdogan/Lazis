from __future__ import annotations

import json
import secrets
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.errors import StorageError
from lazis.security import recovery
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage
from lazis.storage.backup import create_snapshot, restore_snapshot, verify_snapshot
from lazis.storage.database import PLAINTEXT_HEADER
from lazis.storage.repositories import get_setting, set_setting


def test_snapshot_is_encrypted_verified_and_has_manifest(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        handle.db.run_sync(lambda c: set_setting(c, "k", "v1", actor="system"))
        info = handle.db.run_sync(
            lambda c: create_snapshot(c, key, storage_section.backup_dir, label="manual", keep=5)
        )
    finally:
        handle.db.close()
    assert info.path.read_bytes()[:16] != PLAINTEXT_HEADER
    manifest = json.loads(info.manifest_path.read_text())
    assert manifest["sha256"] == info.sha256 and manifest["key_version"] == "v1"
    verify_snapshot(info.path, key)
    with pytest.raises(StorageError):
        verify_snapshot(info.path, SecretBytes(secrets.token_bytes(32)))


def test_restore_round_trip(storage_section: StorageSection, key: SecretBytes) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        handle.db.run_sync(lambda c: set_setting(c, "k", "before-backup", actor="system"))
        info = handle.db.run_sync(
            lambda c: create_snapshot(c, key, storage_section.backup_dir, label="manual", keep=5)
        )
        handle.db.run_sync(lambda c: set_setting(c, "k", "after-backup", actor="system"))
    finally:
        handle.db.close()
    restore_snapshot(info.path, storage_section.database_path, key)
    restored = open_storage(storage_section, key, app_version="test")
    try:
        assert restored.db.run_sync(lambda c: get_setting(c, "k")) == "before-backup"
    finally:
        restored.db.close()


def test_tampered_snapshot_is_not_restored(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        info = handle.db.run_sync(
            lambda c: create_snapshot(c, key, storage_section.backup_dir, label="manual", keep=5)
        )
    finally:
        handle.db.close()
    data = bytearray(info.path.read_bytes())
    data[-100] ^= 0xFF
    info.path.write_bytes(bytes(data))
    with pytest.raises(StorageError):
        restore_snapshot(info.path, storage_section.database_path, key)


def test_retention_keeps_the_newest(storage_section: StorageSection, key: SecretBytes) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        for _ in range(4):
            handle.db.run_sync(
                lambda c: create_snapshot(
                    c, key, storage_section.backup_dir, label="manual", keep=2
                )
            )
    finally:
        handle.db.close()
    assert len(list(Path(storage_section.backup_dir).glob("lazis-*.db"))) == 2


def test_recovery_code_restores_access_to_synthetic_data(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    """Simulates a lost Keychain item: only the recovery code (shown once) remains."""
    handle = open_storage(storage_section, key, app_version="test")
    try:
        handle.db.run_sync(
            lambda c: set_setting(c, "synthetic.profile", {"ad": "Deniz"}, actor="system")
        )
    finally:
        handle.db.close()
    code = recovery.encode(key.reveal())
    del key  # the "Keychain" is gone
    restored_key = SecretBytes(recovery.decode(code))
    reopened = open_storage(storage_section, restored_key, app_version="test")
    try:
        assert reopened.db.run_sync(lambda c: get_setting(c, "synthetic.profile")) == {
            "ad": "Deniz"
        }
    finally:
        reopened.db.close()
