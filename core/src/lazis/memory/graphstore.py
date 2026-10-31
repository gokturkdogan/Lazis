"""SQL for relationships, their evidence and identity distinctions (0005_graph). Runs on the
database thread; callers own the transaction (``UnitOfWork``)."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Sequence
from typing import Any

from lazis.ids import new_ulid
from lazis.memory import relations
from lazis.memory import repository as repo
from lazis.memory.models import Relationship
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import TRACKED_TABLES

TRACKED_TABLES.setdefault("memory_relationships", "id")

_COLS = (
    "id, source_id, type, target_id, qualifier, status, origin, confidence, sensitivity,"
    " sensitivity_category, time_text, valid_from, valid_to, supersedes_id, conflict_state,"
    " version, created_at, updated_at"
)


def _rel(row: Sequence[Any]) -> Relationship:
    return Relationship(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), row[4], row[5], row[6],
        float(row[7]), row[8], row[9], row[10], row[11], row[12], row[13], row[14],
        int(row[15]), str(row[16]), str(row[17]),
    )  # fmt: skip


def insert_relationship(
    conn: Connection,
    *,
    source_id: str,
    type: str,
    target_id: str,
    qualifier: str | None,
    status: str,
    origin: str,
    confidence: float,
    sensitivity: str,
    sensitivity_category: str | None,
    time_text: str | None,
    supersedes_id: str | None,
    change_set_id: str,
    now: str,
) -> Relationship:
    rid = new_ulid()
    conn.execute(
        f"INSERT INTO memory_relationships ({_COLS}, change_set_id)"  # noqa: S608
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'none', 1, ?, ?, ?)",
        (rid, source_id, type, target_id, qualifier, status, origin, confidence, sensitivity,
         sensitivity_category, time_text, now if status == "active" else None, supersedes_id,
         now, now, change_set_id),
    )  # fmt: skip
    rel = get_relationship(conn, rid)
    assert rel is not None
    return rel


def get_relationship(conn: Connection, rel_id: str) -> Relationship | None:
    row = conn.execute(
        f"SELECT {_COLS} FROM memory_relationships WHERE id = ?",  # noqa: S608
        (rel_id,),
    ).fetchone()
    return None if row is None else _rel(row)


def relationships_of(
    conn: Connection, entity_id: str, *, statuses: Sequence[str] | None = None
) -> list[Relationship]:
    """Every relationship touching the entity, in either direction."""
    sql = f"SELECT {_COLS} FROM memory_relationships WHERE (source_id = ? OR target_id = ?)"  # noqa: S608
    args: list[Any] = [entity_id, entity_id]
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    sql += " ORDER BY created_at"
    return [_rel(r) for r in conn.execute(sql, args).fetchall()]


def edges_from(conn: Connection, entity_id: str, statuses: Sequence[str]) -> list[Relationship]:
    """Relationships stored with this entity as the source (index: source, status, type)."""
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT {_COLS} FROM memory_relationships WHERE source_id = ? AND status IN ({marks})",  # noqa: S608
        (entity_id, *statuses),
    ).fetchall()
    return [_rel(r) for r in rows]


def edges_to(conn: Connection, entity_id: str, statuses: Sequence[str]) -> list[Relationship]:
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT {_COLS} FROM memory_relationships WHERE target_id = ? AND status IN ({marks})",  # noqa: S608
        (entity_id, *statuses),
    ).fetchall()
    return [_rel(r) for r in rows]


def relationships_between(
    conn: Connection, a: str, b: str, *, statuses: Sequence[str] | None = None
) -> list[Relationship]:
    sql = (
        f"SELECT {_COLS} FROM memory_relationships"  # noqa: S608
        " WHERE ((source_id = ? AND target_id = ?) OR (source_id = ? AND target_id = ?))"
    )
    args: list[Any] = [a, b, b, a]
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    return [_rel(r) for r in conn.execute(sql + " ORDER BY created_at", args).fetchall()]


def list_relationships(
    conn: Connection, *, type: str | None = None, statuses: Sequence[str] | None = None,
    limit: int = 200,
) -> list[Relationship]:  # fmt: skip
    sql = f"SELECT {_COLS} FROM memory_relationships WHERE 1 = 1"  # noqa: S608
    args: list[Any] = []
    if type:
        sql += " AND type = ?"
        args.append(type)
    if statuses:
        sql += f" AND status IN ({','.join('?' * len(statuses))})"
        args += list(statuses)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    return [_rel(r) for r in conn.execute(sql, args).fetchall()]


def set_status(
    conn: Connection, rel_id: str, status: str, now: str, *, ended: bool = False
) -> None:
    conn.execute(
        "UPDATE memory_relationships SET status = ?, valid_to = CASE WHEN ? THEN ? ELSE valid_to"
        " END, updated_at = ?, version = version + 1 WHERE id = ?",
        (status, 1 if ended else 0, now, now, rel_id),
    )


def set_conflict(conn: Connection, rel_id: str, state: str, now: str) -> None:
    conn.execute(
        "UPDATE memory_relationships SET conflict_state = ?, updated_at = ? WHERE id = ?",
        (state, now, rel_id),
    )


def update_relationship(
    conn: Connection, rel_id: str, *, type: str, qualifier: str | None, status: str,
    time_text: str | None, origin: str, now: str,
) -> None:  # fmt: skip
    conn.execute(
        "UPDATE memory_relationships SET type = ?, qualifier = ?, time_text = ?, origin = ?,"
        " confidence = 1.0, conflict_state = 'none', updated_at = ?, version = version + 1,"
        # Ending stamps valid_to once; going back to current clears it.
        " valid_to = CASE WHEN ? = 'ended' THEN COALESCE(valid_to, ?) ELSE NULL END,"
        " valid_from = CASE WHEN ? = 'active' THEN COALESCE(valid_from, ?) ELSE valid_from END,"
        " status = ? WHERE id = ?",
        (type, qualifier, time_text, origin, now, status, now, status, now, status, rel_id),
    )


def repoint(conn: Connection, rel_id: str, *, source_id: str, target_id: str, now: str) -> None:
    conn.execute(
        "UPDATE memory_relationships SET source_id = ?, target_id = ?, updated_at = ?,"
        " version = version + 1 WHERE id = ?",
        (source_id, target_id, now, rel_id),
    )


def delete_relationship(conn: Connection, rel_id: str) -> None:
    """Hard delete: the row, its evidence (cascade) and the content of its history versions."""
    conn.execute("DELETE FROM memory_relationships WHERE id = ?", (rel_id,))
    repo.purge_history(conn, "memory_relationships", rel_id)


def count_relationships(conn: Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM memory_relationships GROUP BY status"
    ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


# ----- evidence ---------------------------------------------------------------------------
def add_evidence(
    conn: Connection, rel_id: str, *, source_type: str, source_ref: str | None,
    quote: str | None, now: str,
) -> None:  # fmt: skip
    conn.execute(
        "INSERT INTO memory_relationship_evidence"
        " (id, relationship_id, source_type, source_ref, quote, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (new_ulid(), rel_id, source_type, source_ref, quote, now),
    )


def evidence_for(conn: Connection, rel_id: str) -> list[tuple[str, str | None, str | None, str]]:
    rows = conn.execute(
        "SELECT source_type, source_ref, quote, created_at FROM memory_relationship_evidence"
        " WHERE relationship_id = ? ORDER BY created_at",
        (rel_id,),
    ).fetchall()
    return [(str(r[0]), r[1], r[2], str(r[3])) for r in rows]


def move_evidence(conn: Connection, from_rel: str, to_rel: str) -> None:
    conn.execute(
        "UPDATE memory_relationship_evidence SET relationship_id = ? WHERE relationship_id = ?",
        (to_rel, from_rel),
    )


# ----- identity distinctions ("these are different people") --------------------------------
def add_distinction(conn: Connection, a: str, b: str, now: str) -> None:
    lo, hi = sorted((a, b))
    conn.execute(
        "INSERT OR IGNORE INTO memory_entity_distinctions (entity_a, entity_b, created_at)"
        " VALUES (?, ?, ?)",
        (lo, hi, now),
    )


def are_distinct(conn: Connection, a: str, b: str) -> bool:
    lo, hi = sorted((a, b))
    return (
        conn.execute(
            "SELECT 1 FROM memory_entity_distinctions WHERE entity_a = ? AND entity_b = ?",
            (lo, hi),
        ).fetchone()
        is not None
    )


# ----- suppression fingerprints (keyed, no text) -------------------------------------------
def _hmac(key: bytes, msg: str) -> str:
    return hmac.new(key, msg.encode(), hashlib.sha256).hexdigest()


def rel_fingerprint_with(key: bytes, source_id: str, type: str, target_id: str) -> str:
    """Order-free for symmetric types (Ahmet–Mehmet kardeş = Mehmet–Ahmet kardeş); a directed
    type is also recognised when read from the other end (mother ↔ child)."""
    t = relations.get(type)
    if t is not None and t.symmetric:
        a, b = sorted((source_id, target_id))
        return _hmac(key, f"rel\x00{a}\x00{type}\x00{b}")
    return _hmac(key, f"rel\x00{source_id}\x00{type}\x00{target_id}")


def pair_fingerprint_with(key: bytes, a: str, b: str) -> str:
    lo, hi = sorted((a, b))
    return _hmac(key, f"pair\x00{lo}\x00{hi}")


def rel_fingerprint(conn: Connection, source_id: str, type: str, target_id: str) -> str:
    return rel_fingerprint_with(repo.fingerprint_key(conn), source_id, type, target_id)


def pair_fingerprint(conn: Connection, a: str, b: str) -> str:
    return pair_fingerprint_with(repo.fingerprint_key(conn), a, b)


def suppress(conn: Connection, fp: str, reason: str, now: str) -> None:
    # subject/predicate left empty: Phase 6 lists forgotten *topics* from them.
    repo.add_suppression(conn, fp=fp, subject_id=None, predicate=None, reason=reason, now=now)


def edges_touching(
    conn: Connection, ids: Sequence[str], statuses: Sequence[str]
) -> list[tuple[str, Relationship]]:
    """(node, relationship) for every relationship with a listed node at either end — the
    graph walker's batched adjacency read (both indexes, one round trip per 400 nodes)."""
    out: list[tuple[str, Relationship]] = []
    st = ",".join("?" * len(statuses))
    for i in range(0, len(ids), 400):
        chunk = list(ids[i : i + 400])
        marks = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT source_id, {_COLS} FROM memory_relationships"  # noqa: S608
            f" WHERE source_id IN ({marks}) AND status IN ({st})"
            f" UNION ALL SELECT target_id, {_COLS} FROM memory_relationships"
            f" WHERE target_id IN ({marks}) AND status IN ({st})",
            (*chunk, *statuses, *chunk, *statuses),
        ).fetchall()
        out += [(str(r[0]), _rel(r[1:])) for r in rows]
    return out


def entity_statuses(conn: Connection, ids: Sequence[str]) -> dict[str, str]:
    """id → status for entities that still exist (a deleted one is simply absent)."""
    out: dict[str, str] = {}
    unique = list(dict.fromkeys(ids))
    for i in range(0, len(unique), 400):
        chunk = unique[i : i + 400]
        rows = conn.execute(
            f"SELECT id, status FROM memory_entities WHERE id IN ({','.join('?' * len(chunk))})",  # noqa: S608
            chunk,
        ).fetchall()
        out.update({str(r[0]): str(r[1]) for r in rows})
    return out
