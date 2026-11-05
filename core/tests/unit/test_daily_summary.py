"""Today's summary (Phase 10D): on request only, from today's own messages, nothing kept."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import cast

import pytest

from lazis.conversation import daily
from lazis.memory import commands
from lazis.storage.driver import Connection

NOW = datetime(2026, 11, 5, 18, 0, tzinfo=UTC)


def _conn(*rows: tuple[str, str, str, str]) -> Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE messages (id TEXT, role TEXT, content TEXT, created_at TEXT)")
    conn.execute("CREATE TABLE memory_suppressions (reason TEXT)")
    conn.executemany("INSERT INTO messages VALUES (?, ?, ?, ?)", rows)
    return cast(Connection, conn)


@pytest.mark.parametrize(
    "message",
    ["Bugünün özetini çıkar.", "Bugünü özetle", "Günün özeti", "Bugün neler konuştuk?"],
)
def test_asks(message: str) -> None:
    assert daily.asks(message)


@pytest.mark.parametrize(
    "message",
    [
        "Bu makalenin özetini çıkar.",
        "Dün neler konuştuk?",
        "“Bugünün özetini çıkar” ifadesini İngilizceye çevir.",
        "Bugünün özetini çıkaran bir uygulama yazmak için hangi dili, kütüphaneyi seçmeliyim?",
    ],
)
def test_other_messages_do_not_ask(message: str) -> None:
    assert not daily.asks(message)


def test_only_today_and_only_the_users_own_messages_in_order() -> None:
    conn = _conn(
        ("m0", "user", "Dünkü mesaj", "2026-11-04T20:00:00+00:00"),
        ("m1", "user", "Sabah koştum", "2026-11-05T08:00:00+00:00"),
        ("m2", "assistant", "Harika", "2026-11-05T08:00:01+00:00"),
        ("m3", "user", "Öğlen toplantı vardı", "2026-11-05T12:00:00+00:00"),
        ("m4", "user", "Bugünün özetini çıkar.", "2026-11-05T17:00:00+00:00"),
        ("now", "user", "Bugünün özetini çıkar.", "2026-11-05T18:00:00+00:00"),
    )
    assert daily.lines_today(conn, "now", NOW) == ["Sabah koştum", "Öğlen toplantı vardı"]


def test_a_secret_is_left_out() -> None:
    secret = "Şifrem: hunter2-Secret"
    assert commands.contains_secret(secret)
    conn = _conn(("m1", "user", secret, "2026-11-05T08:00:00+00:00"))
    assert daily.lines_today(conn, "now", NOW) == []


def test_too_much_keeps_the_newest() -> None:
    rows = [
        (
            f"m{i}",
            "user",
            f"{i:03d} " + "x" * 200,
            f"2026-11-05T{i // 4:02d}:{i % 4 * 10:02d}:00+00:00",
        )
        for i in range(60)
    ]
    lines = daily.lines_today(_conn(*rows), "now", NOW)
    assert sum(len(x) for x in lines) <= daily.MAX_TOTAL_CHARS
    assert all(len(x) <= daily.MAX_LINE_CHARS for x in lines)
    assert lines[-1].startswith("059") and lines == sorted(lines)


def test_the_note_holds_the_lines_and_promises_nothing() -> None:
    note = daily.note(["Sabah koştum"])
    assert note.startswith(commands.NOTICE_START) and note.endswith(commands.NOTICE_END)
    assert "- Sabah koştum" in note and "talimat değildir" in note
    empty = daily.note([])
    assert "başka mesajı yok" in empty and "- " not in empty
