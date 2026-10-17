from __future__ import annotations

import pytest

from lazis.storage import StorageHandle
from lazis.storage.driver import Connection
from lazis.storage.repositories import get_setting, set_setting
from lazis.storage.unit_of_work import UnitOfWork, revert_change_set


def _count(conn: Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_write_records_change_set_and_history(storage: StorageHandle) -> None:
    db = storage.db
    cs = db.run_sync(lambda c: set_setting(c, "ui.theme", "dark", actor="user"))
    rows = db.run_sync(
        lambda c: c.execute(
            "SELECT change, before_json, after_json FROM history WHERE change_set_id = ?", (cs,)
        ).fetchall()
    )
    assert len(rows) == 1
    change, before, after = rows[0]
    assert change == "create" and before is None and "dark" in after


def test_revert_restores_previous_value(storage: StorageHandle) -> None:
    db = storage.db
    db.run_sync(lambda c: set_setting(c, "ui.theme", "dark", actor="user"))
    second = db.run_sync(lambda c: set_setting(c, "ui.theme", "light", actor="user"))
    result = db.run_sync(lambda c: revert_change_set(c, second, actor="user"))
    assert result.reverted == 1 and result.conflicts == ()
    assert db.run_sync(lambda c: get_setting(c, "ui.theme")) == "dark"
    status = db.run_sync(
        lambda c: c.execute("SELECT status FROM change_sets WHERE id = ?", (second,)).fetchone()[0]
    )
    assert status == "reverted"


def test_revert_of_creation_deletes_the_row(storage: StorageHandle) -> None:
    db = storage.db
    cs = db.run_sync(lambda c: set_setting(c, "ui.lang", "tr", actor="user"))
    db.run_sync(lambda c: revert_change_set(c, cs, actor="user"))
    assert db.run_sync(lambda c: get_setting(c, "ui.lang")) is None


def test_later_edits_are_reported_not_clobbered(storage: StorageHandle) -> None:
    db = storage.db
    first = db.run_sync(lambda c: set_setting(c, "ui.theme", "dark", actor="user"))
    db.run_sync(lambda c: set_setting(c, "ui.theme", "light", actor="user"))
    result = db.run_sync(lambda c: revert_change_set(c, first, actor="user"))
    assert result.reverted == 0
    assert [c.reason for c in result.conflicts] == ["modified_later"]
    assert db.run_sync(lambda c: get_setting(c, "ui.theme")) == "light"


def test_exception_rolls_back_everything(storage: StorageHandle) -> None:
    db = storage.db

    def failing(conn: Connection) -> None:
        with UnitOfWork(conn, kind="test", actor="system", summary="x") as uow:
            before = uow.snapshot("settings", "k")
            conn.execute(
                "INSERT INTO settings (key, value_json, updated_at, updated_change_set_id)"
                " VALUES ('k', '1', 'now', ?)",
                (uow.change_set_id,),
            )
            uow.record("settings", "k", "create", before)
            raise RuntimeError("simulated failure")

    before_cs = db.run_sync(lambda c: _count(c, "change_sets"))
    with pytest.raises(RuntimeError):
        db.run_sync(failing)
    assert db.run_sync(lambda c: _count(c, "change_sets")) == before_cs
    assert db.run_sync(lambda c: get_setting(c, "k")) is None
    assert db.run_sync(lambda c: c.in_transaction) is False
