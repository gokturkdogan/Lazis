"""Unit of work: one transaction == one change set, with per-row history for undo.

Revert support is generic over the tables registered in :data:`REVERTIBLE_TABLES` (table →
primary-key column). Tables whose rows need history but cannot be restored row by row (they
have derived state, e.g. the memory FTS index) register in :data:`TRACKED_TABLES` instead;
a revert reports them as ``table_not_revertible``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from types import TracebackType
from typing import Any, Literal

from lazis.errors import StorageError
from lazis.ids import new_ulid, utc_now_iso
from lazis.storage.driver import Connection

Actor = Literal["user", "pipeline", "import", "system"]
Change = Literal["create", "update", "delete", "restore"]

REVERTIBLE_TABLES: dict[str, str] = {"settings": "key"}
TRACKED_TABLES: dict[str, str] = {}


def _pk(table: str) -> str:
    return REVERTIBLE_TABLES.get(table) or TRACKED_TABLES[table]


def _row_as_dict(conn: Connection, table: str, pk: str, target_id: str) -> dict[str, Any] | None:
    cursor = conn.execute(f"SELECT * FROM {table} WHERE {pk} = ?", (target_id,))  # noqa: S608
    row = cursor.fetchone()
    if row is None:
        return None
    columns = [d[0] for d in cursor.description]
    return dict(zip(columns, row, strict=True))


class UnitOfWork:
    """Usage (inside the DB thread)::

    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 ayar") as uow:
        before = uow.snapshot("settings", "ui.theme")
        conn.execute(...)
        uow.record("settings", "ui.theme", "update", before)
    """

    def __init__(
        self,
        conn: Connection,
        *,
        kind: str,
        actor: Actor,
        summary: str,
        source_ref: str | None = None,
        reverts: str | None = None,
    ) -> None:
        self.conn = conn
        self.change_set_id = new_ulid()
        self._kind = kind
        self._actor = actor
        self._summary = summary
        self._source_ref = source_ref
        self._reverts = reverts

    def __enter__(self) -> UnitOfWork:
        if self.conn.in_transaction:
            raise StorageError("nested unit of work is not supported")
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            "INSERT INTO change_sets (id, kind, actor, source_ref, summary, reverts_change_set_id,"
            " status, created_at) VALUES (?, ?, ?, ?, ?, ?, 'applied', ?)",
            (
                self.change_set_id,
                self._kind,
                self._actor,
                self._source_ref,
                self._summary,
                self._reverts,
                utc_now_iso(),
            ),
        )
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if exc_type is None:
            self.conn.execute("COMMIT")
        else:
            self.conn.execute("ROLLBACK")

    def snapshot(self, table: str, target_id: str) -> dict[str, Any] | None:
        pk = _pk(table)
        return _row_as_dict(self.conn, table, pk, target_id)

    def record(
        self, table: str, target_id: str, change: Change, before: dict[str, Any] | None
    ) -> None:
        pk = _pk(table)
        after = _row_as_dict(self.conn, table, pk, target_id)
        version = self.conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM history"
            " WHERE target_table = ? AND target_id = ?",
            (table, target_id),
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO history (target_table, target_id, version, change, change_set_id,"
            " before_json, after_json, at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                table,
                target_id,
                version,
                change,
                self.change_set_id,
                None if before is None else json.dumps(before, ensure_ascii=False),
                None if after is None else json.dumps(after, ensure_ascii=False),
                utc_now_iso(),
            ),
        )


@dataclass(frozen=True)
class RevertConflict:
    table: str
    target_id: str
    reason: str


@dataclass(frozen=True)
class RevertResult:
    change_set_id: str
    reverted: int
    conflicts: tuple[RevertConflict, ...] = field(default_factory=tuple)


def _restore_row(conn: Connection, table: str, data: dict[str, Any]) -> None:
    columns = [str(r[1]) for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    unknown = set(data) - set(columns)
    if unknown:
        raise StorageError(f"history snapshot has unknown columns for {table}")
    names = list(data)
    placeholders = ", ".join("?" for _ in names)
    conn.execute(
        f"INSERT OR REPLACE INTO {table} ({', '.join(names)}) VALUES ({placeholders})",  # noqa: S608
        [data[n] for n in names],
    )


def revert_change_set(conn: Connection, change_set_id: str, *, actor: Actor) -> RevertResult:
    """Undo a change set. Rows modified by later change sets are reported, not clobbered."""
    rows = conn.execute(
        "SELECT target_table, target_id, version, before_json FROM history"
        " WHERE change_set_id = ? ORDER BY version DESC, rowid DESC",
        (change_set_id,),
    ).fetchall()
    if not rows:
        raise StorageError("change set has no history to revert")
    conflicts: list[RevertConflict] = []
    reverted = 0
    with UnitOfWork(
        conn, kind="rollback", actor=actor, summary="geri alma", reverts=change_set_id
    ) as uow:
        for table, target_id, version, before_json in rows:
            table_name, row_id = str(table), str(target_id)
            if table_name not in REVERTIBLE_TABLES:
                conflicts.append(RevertConflict(table_name, row_id, "table_not_revertible"))
                continue
            latest = conn.execute(
                "SELECT MAX(version) FROM history WHERE target_table = ? AND target_id = ?",
                (table_name, row_id),
            ).fetchone()[0]
            if latest != version:
                conflicts.append(RevertConflict(table_name, row_id, "modified_later"))
                continue
            before = uow.snapshot(table_name, row_id)
            pk = REVERTIBLE_TABLES[table_name]
            if before_json is None:
                conn.execute(f"DELETE FROM {table_name} WHERE {pk} = ?", (row_id,))  # noqa: S608
                uow.record(table_name, row_id, "delete", before)
            else:
                data = json.loads(str(before_json))
                if table_name == "settings":
                    # The restored row now belongs to the rollback change set.
                    data["updated_change_set_id"] = uow.change_set_id
                _restore_row(conn, table_name, data)
                uow.record(table_name, row_id, "restore", before)
            reverted += 1
        status = "reverted" if not conflicts else "partially_reverted"
        conn.execute("UPDATE change_sets SET status = ? WHERE id = ?", (status, change_set_id))
    return RevertResult(uow.change_set_id, reverted, tuple(conflicts))
