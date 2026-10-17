"""Conversation tables on the encrypted database: upgrade, integrity rules, rollback, locking,
no plaintext on disk, corruption. Synthetic data only."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.conversation import repository
from lazis.errors import (
    DatabaseBusyError,
    DatabaseCorruptError,
    DatabaseKeyError,
    MessageSaveError,
    MigrationError,
)
from lazis.ids import utc_now_iso
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, driver, open_storage
from lazis.storage.database import apply_key
from lazis.storage.migrations import Migration, load_migrations
from lazis.storage.repositories import get_setting, set_setting

MARKER = "GİZLİ-SOHBET-İÇERİĞİ-7c1e"


def _seed(storage: StorageHandle, text: str = "Merhaba") -> str:
    now = utc_now_iso()

    def write(conn: driver.Connection) -> str:
        with repository.transaction(conn):
            conv = repository.insert_conversation(conn, title="Deneme", model="m", now=now)
            user = repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="user",
                content=text,
                status="complete",
                now=now,
                client_id="client-seed-0001",
            )
            repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="assistant",
                content="Yanıt",
                status="complete",
                now=now,
                reply_to=user.id,
            )
        return conv.id

    return storage.db.run_sync(write)


def test_existing_v1_database_is_upgraded_with_a_backup(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    v1 = load_migrations("lazis")[:1]
    old = open_storage(storage_section, key, app_version="p2", migrations=v1)
    old.db.run_sync(lambda c: set_setting(c, "ui.theme", "dark", actor="user"))
    assert old.schema_version == 1
    old.db.close()

    upgraded = open_storage(storage_section, key, app_version="p3")
    try:
        assert upgraded.migration.applied == (2,)
        assert upgraded.db.run_sync(lambda c: get_setting(c, "ui.theme")) == "dark"
        assert _seed(upgraded)
        backups = list(storage_section.backup_dir.glob("lazis-*-pre-migration-v1.db"))
        assert len(backups) == 1
        # The backup is encrypted too: plain SQLite cannot read it.
        with pytest.raises(sqlite3.DatabaseError):
            sqlite3.connect(backups[0]).execute("SELECT count(*) FROM sqlite_master").fetchone()
    finally:
        upgraded.db.close()


def test_failed_later_migration_keeps_conversations_intact(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    cid = _seed(handle)
    handle.db.close()
    broken = [*load_migrations("lazis"), Migration(3, "broken", "DROP TABLE messages;\nNOT SQL;")]
    with pytest.raises(MigrationError):
        open_storage(storage_section, key, app_version="test", migrations=broken)
    again = open_storage(storage_section, key, app_version="test")
    try:
        assert again.schema_version == 2
        assert len(again.db.run_sync(lambda c: repository.messages_between(c, cid, 1))) == 2
    finally:
        again.db.close()


def test_sequence_and_idempotency_keys_are_enforced(storage: StorageHandle) -> None:
    cid = _seed(storage)
    now = utc_now_iso()

    def duplicate_seq(conn: driver.Connection) -> None:
        conn.execute(
            "INSERT INTO messages (id, conversation_id, seq, role, content, status, created_at)"
            " VALUES ('x1', ?, 1, 'user', 'x', 'complete', ?)",
            (cid, now),
        )

    def duplicate_client(conn: driver.Connection) -> None:
        with repository.transaction(conn):
            repository.insert_message(
                conn,
                conversation_id=cid,
                role="user",
                content="x",
                status="complete",
                now=now,
                client_id="client-seed-0001",
            )

    with pytest.raises(driver.DatabaseError):
        storage.db.run_sync(duplicate_seq)
    with pytest.raises(MessageSaveError):
        storage.db.run_sync(duplicate_client)
    conv = storage.db.run_sync(lambda c: repository.get_conversation(c, cid))
    assert conv is not None and conv.last_seq == 2 and conv.message_count == 2


def test_failed_transaction_leaves_nothing_behind(storage: StorageHandle) -> None:
    cid = _seed(storage)

    def half(conn: driver.Connection) -> None:
        with repository.transaction(conn):
            repository.insert_message(
                conn,
                conversation_id=cid,
                role="user",
                content="yarım",
                status="complete",
                now=utc_now_iso(),
            )
            raise RuntimeError("simulated failure after the first write")

    with pytest.raises(RuntimeError):
        storage.db.run_sync(half)
    msgs = storage.db.run_sync(lambda c: repository.messages_between(c, cid, 1))
    conv = storage.db.run_sync(lambda c: repository.get_conversation(c, cid))
    assert (
        [m.content for m in msgs] == ["Merhaba", "Yanıt"]
        and conv is not None
        and conv.last_seq == 2
    )


def test_foreign_keys_cascade_and_orphans_are_refused(storage: StorageHandle) -> None:
    cid = _seed(storage)
    with pytest.raises(MessageSaveError):
        storage.db.run_sync(lambda c: _insert_orphan(c))
    storage.db.run_sync(lambda c: c.execute("DELETE FROM conversations WHERE id = ?", (cid,)))
    assert storage.db.run_sync(lambda c: repository.count_rows(c, cid))["messages"] == 0


def _insert_orphan(conn: driver.Connection) -> None:
    with repository.transaction(conn):
        repository.insert_message(
            conn,
            conversation_id="01JNOTEXISTING0000000000000",
            role="user",
            content="x",
            status="complete",
            now=utc_now_iso(),
        )


def test_locked_database_reports_busy(
    storage: StorageHandle, storage_section: StorageSection, key: SecretBytes
) -> None:
    _seed(storage)
    other = driver.connect(storage_section.database_path)
    try:
        apply_key(other, key)
        other.execute("BEGIN IMMEDIATE")

        def write(conn: driver.Connection) -> None:
            conn.execute("PRAGMA busy_timeout = 50")
            try:
                with repository.transaction(conn):
                    repository.touch_conversation(conn, "x", utc_now_iso())
            finally:
                conn.execute("PRAGMA busy_timeout = 5000")

        with pytest.raises(DatabaseBusyError):
            storage.db.run_sync(write)
    finally:
        other.execute("ROLLBACK")
        other.close()


def test_conversation_text_never_reaches_disk_in_plaintext(
    storage_section: StorageSection, key: SecretBytes, tmp_path: Path
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        _seed(handle, f"{MARKER} kardeşimin doğum günü")
        files = [p for p in storage_section.data_dir.rglob("*") if p.is_file()]
        assert any(p.name.endswith("-wal") for p in files)  # WAL is live and checked too
        for path in files:
            data = path.read_bytes()
            assert MARKER.encode() not in data and "kardeşimin".encode() not in data, path.name
    finally:
        handle.db.close()
    for path in [p for p in storage_section.data_dir.rglob("*") if p.is_file()]:
        assert MARKER.encode() not in path.read_bytes(), path.name


def test_corrupted_database_is_refused_not_repaired(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    for i in range(30):
        _seed_many(handle, i)
    handle.db.close()
    path = storage_section.database_path
    data = bytearray(path.read_bytes())
    for offset in range(8192, min(len(data), 8192 + 4096)):
        data[offset] ^= 0xFF
    path.write_bytes(bytes(data))
    before = path.read_bytes()
    with pytest.raises((DatabaseCorruptError, DatabaseKeyError)):
        open_storage(storage_section, key, app_version="test")
    assert path.read_bytes() == before  # never "repaired" behind the user's back


def _seed_many(storage: StorageHandle, i: int) -> None:
    now = utc_now_iso()

    def write(conn: driver.Connection) -> None:
        with repository.transaction(conn):
            conv = repository.insert_conversation(conn, title=f"t{i}", model="m", now=now)
            for _ in range(10):
                repository.insert_message(
                    conn,
                    conversation_id=conv.id,
                    role="user",
                    content="x" * 200,
                    status="complete",
                    now=now,
                )

    storage.db.run_sync(write)
