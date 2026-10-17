from __future__ import annotations

from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.errors import MigrationError
from lazis.security.secrets import SecretBytes
from lazis.storage import open_storage
from lazis.storage.database import Database
from lazis.storage.migrations import Migration, current_version, load_migrations, migrate

SHIPPED = len(load_migrations("lazis"))
NEXT = SHIPPED + 1


def _db(section: StorageSection, key: SecretBytes) -> Database:
    db = Database(section.database_path, key)
    db.open()
    return db


def test_shipped_migrations_load_and_are_contiguous() -> None:
    migrations = load_migrations("lazis")
    assert [m.version for m in migrations] == list(range(1, len(migrations) + 1))
    assert migrations[0].name == "system"


def test_migrate_from_empty_creates_system_tables(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        tables = handle.db.run_sync(
            lambda c: {
                r[0]
                for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        )
        assert {
            "schema_migrations",
            "app_meta",
            "change_sets",
            "history",
            "settings",
            "audit_log",
            "conversations",
            "messages",
            "context_summaries",
            "conversation_context",
        } <= tables
        assert handle.schema_version == SHIPPED
        assert handle.migration.applied == tuple(range(1, SHIPPED + 1))
    finally:
        handle.db.close()


def test_rerun_is_a_no_op(storage_section: StorageSection, key: SecretBytes) -> None:
    open_storage(storage_section, key, app_version="test").db.close()
    again = open_storage(storage_section, key, app_version="test")
    try:
        assert again.migration.applied == ()
    finally:
        again.db.close()


def test_modified_applied_migration_is_detected(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    db = _db(storage_section, key)
    try:
        original = load_migrations("lazis")
        db.run_sync(lambda c: migrate(c, original))
        tampered = [Migration(1, original[0].name, original[0].sql + "\n-- edited")]
        with pytest.raises(MigrationError, match="checksum"):
            db.run_sync(lambda c: migrate(c, tampered))
    finally:
        db.close()


def test_database_newer_than_code_is_refused(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    db = _db(storage_section, key)
    try:
        steps = [*load_migrations("lazis"), Migration(NEXT, "future", "CREATE TABLE future (x);")]
        db.run_sync(lambda c: migrate(c, steps))
        with pytest.raises(MigrationError, match="newer"):
            db.run_sync(lambda c: migrate(c, steps[:SHIPPED]))
    finally:
        db.close()


def test_failed_migration_rolls_back_atomically(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    db = _db(storage_section, key)
    try:
        good = load_migrations("lazis")
        db.run_sync(lambda c: migrate(c, good))
        broken = Migration(NEXT, "broken", "CREATE TABLE half_done (x);\nTHIS IS NOT SQL;")
        with pytest.raises(MigrationError):
            db.run_sync(lambda c: migrate(c, [*good, broken]))
        names = db.run_sync(
            lambda c: {
                r[0]
                for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            }
        )
        assert "half_done" not in names
        assert db.run_sync(current_version) == SHIPPED
    finally:
        db.close()


def test_pre_migration_backup_is_taken_for_existing_schema(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    open_storage(storage_section, key, app_version="test").db.close()
    steps = [*load_migrations("lazis"), Migration(NEXT, "add_example", "CREATE TABLE example (x);")]
    handle = open_storage(storage_section, key, app_version="test", migrations=steps)
    try:
        assert handle.migration.applied == (NEXT,)
        backups = list(
            Path(storage_section.backup_dir).glob(f"lazis-*-pre-migration-v{SHIPPED}.db")
        )
        assert len(backups) == 1
    finally:
        handle.db.close()


def test_no_backup_for_a_fresh_database(storage_section: StorageSection, key: SecretBytes) -> None:
    open_storage(storage_section, key, app_version="test").db.close()
    assert not storage_section.backup_dir.exists() or not any(storage_section.backup_dir.iterdir())
