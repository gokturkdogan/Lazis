"""Conversation tables on the encrypted database: upgrade, integrity rules, rollback, locking,
no plaintext on disk, corruption. Synthetic data only."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

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
            # Earlier test sessions are closed first: only one session may be active.
            repository.archive_active_session(conn)
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
        assert upgraded.migration.applied == tuple(range(2, len(load_migrations("lazis")) + 1))
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
    shipped = load_migrations("lazis")
    broken = [*shipped, Migration(len(shipped) + 1, "broken", "DROP TABLE messages;\nNOT SQL;")]
    with pytest.raises(MigrationError):
        open_storage(storage_section, key, app_version="test", migrations=broken)
    again = open_storage(storage_section, key, app_version="test")
    try:
        assert again.schema_version == len(shipped)
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
            repository.archive_active_session(conn)
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


def _v2_with_parallel_conversations(section: StorageSection, key: SecretBytes) -> dict[str, Any]:
    """A Phase 3 (v2) database as the owner may have it: three conversations used in
    parallel, interleaved timestamps, a summary, context rows, partial replies."""
    v2 = load_migrations("lazis")[:2]
    handle = open_storage(section, key, app_version="p3", migrations=v2)

    def write(conn: driver.Connection) -> dict[str, Any]:
        stamps = [f"2026-10-17T10:{m:02d}:00.000Z" for m in range(60)]
        convs: list[str] = []
        with repository.transaction(conn):
            for i in range(3):
                cid = f"01J0000000000000000000000{i}"
                conn.execute(
                    "INSERT INTO conversations (id, title, title_source, model, status,"
                    " message_count, last_seq, created_at, updated_at)"
                    " VALUES (?, ?, 'auto', 'm', 'active', 0, 0, ?, ?)",
                    (cid, f"Sohbet {i}", stamps[i], stamps[i]),
                )
                convs.append(cid)
            # Interleave: A1 B1 C1 A2 B2 … with identical timestamps across conversations.
            for turn in range(4):
                for i, cid in enumerate(convs):
                    for role in ("user", "assistant"):
                        seq = conn.execute(
                            "UPDATE conversations SET last_seq = last_seq + 1, message_count ="
                            " message_count + 1, updated_at = ? WHERE id = ? RETURNING last_seq",
                            (stamps[10 + turn * 3 + i], cid),
                        ).fetchone()[0]
                        status = "complete"
                        if (i, turn, role) == (1, 3, "assistant"):
                            status = "cancelled"
                        if (i, turn, role) == (2, 3, "assistant"):
                            status = "interrupted"
                        conn.execute(
                            "INSERT INTO messages (id, conversation_id, seq, role, content, status,"
                            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                            (
                                f"{cid}-{seq:03d}",
                                cid,
                                seq,
                                role,
                                f"{cid[-1]}:{seq}",
                                status,
                                stamps[10 + turn],
                            ),
                        )
            conn.execute(
                "INSERT INTO context_summaries (id, conversation_id, version, from_seq, to_seq,"
                " status, content_json, rendered, token_count, token_source, model,"
                " prompt_version, created_at) VALUES ('S1', ?, 1, 1, 4, 'active', '{}', 'özet',"
                " 3, 'estimate', 'm', 's3-v3', ?)",
                (convs[0], stamps[30]),
            )
            conn.execute(
                "INSERT INTO conversation_context (conversation_id, context_version,"
                " prompt_version, strategy, window_start_seq, summary_id, budget_tokens,"
                " updated_at) VALUES (?, 2, 'p3-v2', 'summary_window', 5, 'S1', 13721, ?)",
                (convs[0], stamps[30]),
            )
        # Make conversation 1 the most recently used one.
        conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (stamps[59], convs[1]))
        rows = conn.execute(
            "SELECT id, conversation_id, seq, content, status FROM messages"
        ).fetchall()
        return {"convs": convs, "messages": sorted(tuple(r) for r in rows)}

    before = handle.db.run_sync(write)
    handle.db.close()
    return before


def test_v2_parallel_conversations_become_one_timeline_without_any_loss(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    before = _v2_with_parallel_conversations(storage_section, key)
    convs = before["convs"]
    upgraded = open_storage(storage_section, key, app_version="p3-timeline")
    try:
        assert upgraded.migration.applied == (3,)
        after = upgraded.db.run_sync(
            lambda c: c.execute(
                "SELECT id, conversation_id, seq, content, status, timeline_seq FROM messages"
            ).fetchall()
        )
        # Nothing lost, nothing duplicated, nothing rewritten: same ids, content and statuses.
        assert sorted(tuple(r[:5]) for r in after) == before["messages"]
        seqs = sorted(int(r[5]) for r in after)
        assert seqs == list(range(1, len(after) + 1))  # unique, contiguous, no NULLs
        # Sessions stay contiguous blocks (no interleaving by timestamp); the most recently
        # used session (convs[1]) is last; inside a block, the original per-session order.
        order = [(str(r[1]), int(r[2])) for r in sorted(after, key=lambda r: int(r[5]))]
        blocks = [cid for i, (cid, _) in enumerate(order) if i == 0 or order[i - 1][0] != cid]
        assert blocks == [convs[0], convs[2], convs[1]]
        for cid in convs:
            mine = [s for c, s in order if c == cid]
            assert mine == sorted(mine)
        status = dict(
            upgraded.db.run_sync(
                lambda c: c.execute("SELECT id, status FROM conversations").fetchall()
            )
        )
        assert status == {convs[0]: "archived", convs[1]: "active", convs[2]: "archived"}
        # Summaries and context state untouched.
        summary = upgraded.db.run_sync(lambda c: repository.get_summary(c, "S1"))
        ctx = upgraded.db.run_sync(lambda c: repository.get_context(c, convs[0]))
        assert summary is not None and summary.status == "active" and summary.rendered == "özet"
        assert ctx is not None and ctx.summary_id == "S1" and ctx.window_start_seq == 5
        assert all(
            m.channel == "text"
            for m in upgraded.db.run_sync(lambda c: repository.timeline_page(c, limit=100))
        )

        # Only one active session can exist from now on.
        def second_active(conn: driver.Connection) -> None:
            with repository.transaction(conn):
                repository.insert_conversation(conn, title="x", model="m", now="t")

        with pytest.raises(MessageSaveError):
            upgraded.db.run_sync(second_active)
        assert list(storage_section.backup_dir.glob("lazis-*-pre-migration-v2.db"))
    finally:
        upgraded.db.close()
    again = open_storage(storage_section, key, app_version="p3-timeline")
    try:
        assert again.migration.applied == ()  # re-running is a no-op: nothing duplicated
        count = again.db.run_sync(
            lambda c: c.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        )
        assert count == len(before["messages"])
    finally:
        again.db.close()


def test_new_messages_extend_the_timeline_after_migrated_history(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    before = _v2_with_parallel_conversations(storage_section, key)
    handle = open_storage(storage_section, key, app_version="p3-timeline")
    try:

        def add(conn: driver.Connection) -> repository.Message:
            with repository.transaction(conn):
                active = repository.get_active_session(conn)
                assert active is not None and active.id == before["convs"][1]
                return repository.insert_message(
                    conn,
                    conversation_id=active.id,
                    role="user",
                    content="yeni",
                    status="complete",
                    now="t",
                )

        msg = handle.db.run_sync(add)
        assert msg.timeline_seq == len(before["messages"]) + 1 and msg.seq == 9
    finally:
        handle.db.close()
