"""Small repositories for the Phase 1 system tables (app_meta, settings, audit_log)."""

from __future__ import annotations

import json
from typing import Any, Literal

from lazis.ids import new_ulid, utc_now_iso
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import Actor, UnitOfWork

Outcome = Literal["success", "failure", "denied"]


# ----- app_meta ------------------------------------------------------------------------
def ensure_instance_meta(conn: Connection, *, app_version: str) -> dict[str, str]:
    """Create the instance identity on first start; return all meta values."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        for key, value in (
            ("instance_id", new_ulid()),
            ("created_at", utc_now_iso()),
            ("created_by_version", app_version),
        ):
            conn.execute("INSERT OR IGNORE INTO app_meta (key, value) VALUES (?, ?)", (key, value))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    rows = conn.execute("SELECT key, value FROM app_meta").fetchall()
    return {str(k): str(v) for k, v in rows}


# ----- settings ------------------------------------------------------------------------
def get_setting(conn: Connection, key: str) -> Any | None:
    row = conn.execute("SELECT value_json FROM settings WHERE key = ?", (key,)).fetchone()
    return None if row is None else json.loads(str(row[0]))


def set_setting(conn: Connection, key: str, value: Any, *, actor: Actor) -> str:
    """Write one setting inside its own change set. Returns the change-set id."""
    with UnitOfWork(conn, kind="settings_update", actor=actor, summary="1 ayar") as uow:
        before = uow.snapshot("settings", key)
        conn.execute(
            "INSERT INTO settings (key, value_json, updated_at, updated_change_set_id)"
            " VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,"
            " updated_at = excluded.updated_at,"
            " updated_change_set_id = excluded.updated_change_set_id",
            (key, json.dumps(value, ensure_ascii=False), utc_now_iso(), uow.change_set_id),
        )
        uow.record("settings", key, "create" if before is None else "update", before)
    return uow.change_set_id


# ----- audit_log -----------------------------------------------------------------------
def write_audit(
    conn: Connection,
    *,
    category: str,
    action: str,
    outcome: Outcome,
    actor: str = "system",
    reason_code: str | None = None,
    target_refs: list[str] | None = None,
    change_set_id: str | None = None,
    details: dict[str, str | int | float | bool | None] | None = None,
) -> str:
    """Append an audit row. Callers pass identifiers and counts only — never content."""
    audit_id = new_ulid()
    conn.execute(
        "INSERT INTO audit_log (id, at, category, action, actor, target_refs, change_set_id,"
        " outcome, reason_code, details_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            audit_id,
            utc_now_iso(),
            category,
            action,
            actor,
            None if target_refs is None else json.dumps(target_refs),
            change_set_id,
            outcome,
            reason_code,
            None if details is None else json.dumps(details, ensure_ascii=False),
        ),
    )
    return audit_id


def count_audit(conn: Connection, category: str, action: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) FROM audit_log WHERE category = ? AND action = ?", (category, action)
    ).fetchone()
    return int(row[0])
