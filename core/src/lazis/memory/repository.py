"""SQL for the memory tables (0004_memory). Runs on the database thread; callers own the
transaction (``UnitOfWork`` for knowledge writes, ``transaction`` for queue bookkeeping).

The FTS index is contentless with real deletes: every memory insert, text change and delete
updates ``memory_fts`` in the same transaction, keyed by ``memories.rowid``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from collections.abc import Iterable, Sequence
from typing import Any

from lazis.ids import new_ulid
from lazis.memory import registry, text
from lazis.memory.models import Entity, Evidence, InboxItem, Job, Memory
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import TRACKED_TABLES

# Tracked, deliberately not revertible: the generic row restore (``INSERT OR REPLACE``) would
# give a memory a new rowid behind the contentless FTS index and cascade-delete its evidence.
# Memory changes are undone through forget, edit and inbox decisions, which keep it consistent.
TRACKED_TABLES.setdefault("memories", "id")
TRACKED_TABLES.setdefault("memory_entities", "id")

_MEMORY_COLS = (
    "id, rowid, kind, subject_id, predicate, value, value_key, content, keywords, status, origin,"
    " confidence, importance, sensitivity, sensitivity_category, event_time, valid_from, valid_to,"
    " supersedes_id, conflict_state, recall_count, created_at, updated_at, version"
)
_MEMORY_COLS_M = ", ".join(f"m.{c.strip()}" for c in _MEMORY_COLS.split(","))
_ENTITY_INSERT_COLS = (
    "id, kind, name, name_key, relation, relation_key, description, status, merged_into,"
    " created_at, updated_at"
)
_ENTITY_COLS = _ENTITY_INSERT_COLS + ", is_user, confidence, origin"


def _memory(row: Sequence[Any]) -> Memory:
    return Memory(
        id=str(row[0]),
        rowid=int(row[1]),
        kind=str(row[2]),
        subject_id=None if row[3] is None else str(row[3]),
        predicate=str(row[4]),
        value=str(row[5]),
        value_key=str(row[6]),
        content=str(row[7]),
        keywords=str(row[8]),
        status=row[9],
        origin=row[10],
        confidence=float(row[11]),
        importance=float(row[12]),
        sensitivity=row[13],
        sensitivity_category=None if row[14] is None else str(row[14]),
        event_time=None if row[15] is None else str(row[15]),
        valid_from=None if row[16] is None else str(row[16]),
        valid_to=None if row[17] is None else str(row[17]),
        supersedes_id=None if row[18] is None else str(row[18]),
        conflict_state=row[19],
        recall_count=int(row[20]),
        created_at=str(row[21]),
        updated_at=str(row[22]),
        version=int(row[23]),
    )


def _entity(conn: Connection, row: Sequence[Any]) -> Entity:
    aliases = tuple(
        str(r[0])
        for r in conn.execute(
            "SELECT alias FROM memory_entity_aliases WHERE entity_id = ? ORDER BY alias", (row[0],)
        ).fetchall()
    )
    return Entity(
        id=str(row[0]),
        kind=row[1],
        name=str(row[2]),
        name_key=str(row[3]),
        relation=None if row[4] is None else str(row[4]),
        relation_key=None if row[5] is None else str(row[5]),
        description=None if row[6] is None else str(row[6]),
        status=row[7],
        merged_into=None if row[8] is None else str(row[8]),
        created_at=str(row[9]),
        updated_at=str(row[10]),
        aliases=aliases,
        is_user=bool(row[11]),
        confidence=float(row[12]),
        origin=str(row[13]),
    )


# ----- entities --------------------------------------------------------------------------
def insert_entity(
    conn: Connection,
    *,
    kind: str,
    name: str,
    relation: str | None,
    description: str | None,
    now: str,
    aliases: Iterable[str] = (),
) -> Entity:
    eid = new_ulid()
    conn.execute(
        f"INSERT INTO memory_entities ({_ENTITY_INSERT_COLS})"  # noqa: S608 - fixed column list
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'active', NULL, ?, ?)",
        (
            eid,
            kind,
            name.strip(),
            text.name_key(name),
            relation,
            None if relation is None else text.name_key(relation),
            description,
            now,
            now,
        ),
    )
    for alias in {name, *aliases}:
        add_alias(conn, eid, alias)
    entity = get_entity(conn, eid)
    assert entity is not None
    return entity


def add_alias(conn: Connection, entity_id: str, alias: str) -> None:
    key = text.name_key(alias)
    if key:
        conn.execute(
            "INSERT OR IGNORE INTO memory_entity_aliases (entity_id, alias, alias_key)"
            " VALUES (?, ?, ?)",
            (entity_id, alias.strip(), key),
        )


def get_entity(conn: Connection, entity_id: str) -> Entity | None:
    row = conn.execute(
        f"SELECT {_ENTITY_COLS} FROM memory_entities WHERE id = ?",  # noqa: S608
        (entity_id,),
    ).fetchone()
    return None if row is None else _entity(conn, row)


def find_entities(conn: Connection, key: str, *, kind: str | None = None) -> list[Entity]:
    """Active entities whose name or an alias has this folded key."""
    rows = conn.execute(
        f"SELECT {_ENTITY_COLS} FROM memory_entities WHERE status = 'active' AND is_user = 0"  # noqa: S608
        " AND id IN ("
        " SELECT entity_id FROM memory_entity_aliases WHERE alias_key = ?"
        " UNION SELECT id FROM memory_entities WHERE name_key = ?)"
        + (" AND kind = ?" if kind else "")
        + " ORDER BY created_at",
        (key, key, kind) if kind else (key, key),
    ).fetchall()
    return [_entity(conn, r) for r in rows]


def alias_index(conn: Connection) -> list[tuple[str, str]]:
    """(alias_key, entity_id) for every active entity — the mention scanner's dictionary."""
    rows = conn.execute(
        "SELECT a.alias_key, a.entity_id FROM memory_entity_aliases a"
        " JOIN memory_entities e ON e.id = a.entity_id WHERE e.status = 'active'"
    ).fetchall()
    return [(str(r[0]), str(r[1])) for r in rows]


def aliases_matching(conn: Connection, keys: Iterable[str]) -> dict[str, list[str]]:
    """alias key → active entity ids (oldest first), for the given keys only (indexed)."""
    hits: dict[str, list[str]] = {}
    ordered = sorted(set(keys))
    for i in range(0, len(ordered), 400):
        chunk = ordered[i : i + 400]
        rows = conn.execute(
            "SELECT a.alias_key, a.entity_id FROM memory_entity_aliases a"  # noqa: S608
            " JOIN memory_entities e ON e.id = a.entity_id"
            f" WHERE e.status = 'active' AND a.alias_key IN ({','.join('?' * len(chunk))})"
            " ORDER BY e.created_at",
            chunk,
        ).fetchall()
        for key, eid in rows:
            ids = hits.setdefault(str(key), [])
            if str(eid) not in ids:
                ids.append(str(eid))
    return hits


def list_entities(
    conn: Connection, *, kind: str | None = None, query: str | None = None, limit: int = 200
) -> list[Entity]:
    sql = f"SELECT {_ENTITY_COLS} FROM memory_entities WHERE status = 'active' AND is_user = 0"  # noqa: S608
    args: list[Any] = []
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if query:
        sql += (
            " AND (name_key LIKE ? OR id IN"
            " (SELECT entity_id FROM memory_entity_aliases WHERE alias_key LIKE ?))"
        )
        like = f"%{text.name_key(query)}%"
        args += [like, like]
    sql += " ORDER BY updated_at DESC LIMIT ?"
    args.append(limit)
    return [_entity(conn, r) for r in conn.execute(sql, args).fetchall()]


def update_entity(
    conn: Connection,
    entity_id: str,
    *,
    now: str,
    name: str | None = None,
    relation: str | None = None,
    description: str | None = None,
    clear_relation: bool = False,
) -> None:
    sets, args = ["updated_at = ?"], [now]
    if name is not None:
        sets += ["name = ?", "name_key = ?"]
        args += [name.strip(), text.name_key(name)]
    if relation is not None or clear_relation:
        sets += ["relation = ?", "relation_key = ?"]
        args += [relation, None if relation is None else text.name_key(relation)]
    if description is not None:
        sets.append("description = ?")
        args.append(description)
    conn.execute(f"UPDATE memory_entities SET {', '.join(sets)} WHERE id = ?", (*args, entity_id))  # noqa: S608
    if name is not None:
        add_alias(conn, entity_id, name)
    reindex_subject(conn, entity_id)


def mark_merged(conn: Connection, entity_id: str, into: str, now: str) -> None:
    conn.execute(
        "UPDATE memory_entities SET status = 'merged', merged_into = ?, updated_at = ?"
        " WHERE id = ?",
        (into, now, entity_id),
    )


def delete_entity(conn: Connection, entity_id: str) -> None:
    """The entity, its memories, and the records merged into it (they still hold its other
    names). History content of all of them is purged."""
    merged = [
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM memory_entities WHERE merged_into = ?", (entity_id,)
        ).fetchall()
    ]
    for mid in merged:
        delete_entity(conn, mid)
    for m in memories_for_subject(conn, entity_id, statuses=("active", "superseded", "retracted")):
        delete_memory(conn, m)
    conn.execute("DELETE FROM memory_entities WHERE id = ?", (entity_id,))
    purge_history(conn, "memory_entities", entity_id)


# ----- memories --------------------------------------------------------------------------
# bm25 column weights: the memory's own words, then predicate label/hints.
FTS_WEIGHTS = (1.0, 0.2)


def _fts_body(
    conn: Connection, *, content: str, keywords: str, predicate: str, subject_id: str | None
) -> tuple[str, str]:
    parts = [content, keywords]
    if subject_id is not None:
        e = get_entity(conn, subject_id)
        if e is not None:
            parts += [e.name, *(e.aliases), e.relation or ""]
    p = registry.get(predicate)
    hints = f"{p.label} {registry.HINTS.get(predicate, '')}" if p is not None else ""
    return " ".join(text.words(" ".join(parts))), " ".join(text.words(hints))


def insert_memory(
    conn: Connection,
    *,
    kind: str,
    subject_id: str | None,
    predicate: str,
    value: str,
    content: str,
    keywords: str,
    status: str,
    origin: str,
    confidence: float,
    importance: float,
    sensitivity: str,
    sensitivity_category: str | None,
    event_time: str | None,
    valid_from: str | None,
    supersedes_id: str | None,
    change_set_id: str,
    now: str,
) -> Memory:
    mid = new_ulid()
    conn.execute(
        "INSERT INTO memories (id, kind, subject_id, predicate, value, value_key, content,"
        " keywords, status, origin, confidence, importance, sensitivity, sensitivity_category,"
        " event_time, valid_from, valid_to, supersedes_id, conflict_state, change_set_id,"
        " created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, 'none', ?, ?, ?)",
        (
            mid,
            kind,
            subject_id,
            predicate,
            value,
            text.fold(value).strip(),
            content,
            keywords,
            status,
            origin,
            confidence,
            importance,
            sensitivity,
            sensitivity_category,
            event_time,
            valid_from,
            supersedes_id,
            change_set_id,
            now,
            now,
        ),
    )
    memory = get_memory(conn, mid)
    assert memory is not None
    body, hints = _fts_body(
        conn, content=content, keywords=keywords, predicate=predicate, subject_id=subject_id
    )
    conn.execute(
        "INSERT INTO memory_fts (rowid, body, hints) VALUES (?, ?, ?)",
        (memory.rowid, f"{body} {' '.join(text.words(value))}", hints),
    )
    return memory


def get_memory(conn: Connection, memory_id: str) -> Memory | None:
    row = conn.execute(f"SELECT {_MEMORY_COLS} FROM memories WHERE id = ?", (memory_id,)).fetchone()  # noqa: S608
    return None if row is None else _memory(row)


def memories_by_rowid(conn: Connection, rowids: Sequence[int]) -> list[Memory]:
    if not rowids:
        return []
    marks = ",".join("?" * len(rowids))
    rows = conn.execute(
        f"SELECT {_MEMORY_COLS} FROM memories WHERE rowid IN ({marks})",  # noqa: S608
        tuple(rowids),
    ).fetchall()
    return [_memory(r) for r in rows]


def memories_for_subject(
    conn: Connection,
    subject_id: str | None,
    *,
    predicate: str | None = None,
    statuses: Sequence[str] = ("active",),
) -> list[Memory]:
    marks = ",".join("?" * len(statuses))
    subject_sql = "subject_id IS NULL" if subject_id is None else "subject_id = ?"
    args: list[Any] = [] if subject_id is None else [subject_id]
    sql = f"SELECT {_MEMORY_COLS} FROM memories WHERE {subject_sql} AND status IN ({marks})"  # noqa: S608
    args += list(statuses)
    if predicate is not None:
        sql += " AND predicate = ?"
        args.append(predicate)
    sql += " ORDER BY created_at"
    return [_memory(r) for r in conn.execute(sql, args).fetchall()]


def consolidation_candidates(
    conn: Connection,
    subject_id: str | None,
    predicate: str,
    *,
    value: str,
    replaces: str | None,
    limit: int = 40,
) -> list[Memory]:
    """The current records a new value must be compared with. A single-valued predicate has
    few; a multi-valued one can have thousands ("likes"), so only records sharing a word with
    the new value (or with the value it replaces) are candidates — found through the index,
    not by comparing every record."""
    pred = registry.get(predicate)
    if pred is None or pred.cardinality == "single":
        return memories_for_subject(conn, subject_id, predicate=predicate)
    subject_sql = "m.subject_id IS NULL" if subject_id is None else "m.subject_id = ?"
    base: list[Any] = [] if subject_id is None else [subject_id]
    rows = conn.execute(
        f"SELECT {_MEMORY_COLS_M} FROM memories m WHERE {subject_sql} AND m.predicate = ?"  # noqa: S608
        " AND m.status = 'active' AND m.value_key = ?",
        (*base, predicate, text.fold(value).strip()),
    ).fetchall()
    found = {r[0]: r for r in rows}
    match = text.fts_match(text.query_terms(f"{value} {replaces or ''}"))
    if match is not None:
        # CROSS JOIN keeps the index hits as the outer loop: one rowid lookup per hit instead of
        # walking every record of a large predicate (measured: 16 ms → under 1 ms at 50k).
        rows = conn.execute(
            f"SELECT {_MEMORY_COLS_M} FROM (SELECT rowid AS r FROM memory_fts"  # noqa: S608
            " WHERE memory_fts MATCH ? LIMIT 500) f CROSS JOIN memories m ON m.rowid = f.r"
            f" WHERE {subject_sql} AND m.predicate = ? AND m.status = 'active'"
            " ORDER BY m.updated_at DESC LIMIT ?",
            (match, *base, predicate, limit),
        ).fetchall()
        for r in rows:
            found.setdefault(r[0], r)
    return [_memory(r) for r in found.values()]


def pinned_memories(conn: Connection, predicates: Sequence[str], limit: int) -> list[Memory]:
    marks = ",".join("?" * len(predicates))
    rows = conn.execute(
        f"SELECT {_MEMORY_COLS} FROM memories WHERE subject_id IS NULL AND status = 'active'"  # noqa: S608
        f" AND predicate IN ({marks}) ORDER BY updated_at DESC LIMIT ?",
        (*predicates, limit),
    ).fetchall()
    return [_memory(r) for r in rows]


def search(conn: Connection, match: str, *, limit: int) -> list[tuple[int, float]]:
    """(rowid, bm25) for an FTS5 MATCH expression; lower bm25 is better."""
    rows = conn.execute(
        "SELECT rowid, bm25(memory_fts, ?, ?) AS score FROM memory_fts WHERE memory_fts MATCH ?"
        " ORDER BY score LIMIT ?",
        (*FTS_WEIGHTS, match, limit),
    ).fetchall()
    return [(int(r[0]), float(r[1])) for r in rows]


def list_memories(
    conn: Connection,
    *,
    kind: str | None = None,
    subject_id: str | None = None,
    user_only: bool = False,
    status: str | None = "active",
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
    created_since: str | None = None,
) -> list[Memory]:
    sql = f"SELECT {_MEMORY_COLS} FROM memories WHERE 1 = 1"  # noqa: S608
    args: list[Any] = []
    if created_since:
        sql += " AND created_at >= ?"
        args.append(created_since)
    if status:
        sql += " AND status = ?"
        args.append(status)
    if kind:
        sql += " AND kind = ?"
        args.append(kind)
    if user_only:
        sql += " AND subject_id IS NULL"
    elif subject_id:
        sql += " AND subject_id = ?"
        args.append(subject_id)
    if query:
        match = text.fts_match(text.query_terms(query))
        if match is None:
            return []
        sql += " AND rowid IN (SELECT rowid FROM memory_fts WHERE memory_fts MATCH ?)"
        args.append(match)
    sql += f" ORDER BY {'created_at' if created_since else 'updated_at'} DESC LIMIT ? OFFSET ?"
    args += [limit, offset]
    return [_memory(r) for r in conn.execute(sql, args).fetchall()]


def set_status(
    conn: Connection, memory: Memory, status: str, now: str, *, valid_to: str | None = None
) -> None:
    conn.execute(
        "UPDATE memories SET status = ?, valid_to = COALESCE(?, valid_to), updated_at = ?,"
        " version = version + 1 WHERE id = ?",
        (status, valid_to, now, memory.id),
    )


def set_conflict(conn: Connection, memory_id: str, state: str, now: str) -> None:
    conn.execute(
        "UPDATE memories SET conflict_state = ?, updated_at = ? WHERE id = ?",
        (state, now, memory_id),
    )


def update_memory_text(
    conn: Connection,
    memory: Memory,
    *,
    value: str,
    content: str,
    keywords: str | None,
    now: str,
    origin: str | None = None,
    confidence: float | None = None,
) -> None:
    conn.execute(
        "UPDATE memories SET value = ?, value_key = ?, content = ?,"
        " keywords = COALESCE(?, keywords),"
        " origin = COALESCE(?, origin), confidence = COALESCE(?, confidence), updated_at = ?,"
        " version = version + 1 WHERE id = ?",
        (value, text.fold(value).strip(), content, keywords, origin, confidence, now, memory.id),
    )
    reindex_memory(conn, memory.id)


def touch(conn: Connection, memory_id: str, now: str, *, confidence: float | None = None) -> None:
    conn.execute(
        "UPDATE memories SET updated_at = ?,"
        " confidence = MAX(confidence, COALESCE(?, confidence)) WHERE id = ?",
        (now, confidence, memory_id),
    )


def move_subject(conn: Connection, memory_id: str, subject_id: str | None, now: str) -> None:
    conn.execute(
        "UPDATE memories SET subject_id = ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (subject_id, now, memory_id),
    )
    reindex_memory(conn, memory_id)


def reindex_memory(conn: Connection, memory_id: str) -> None:
    m = get_memory(conn, memory_id)
    if m is None:
        return
    conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (m.rowid,))
    body, hints = _fts_body(
        conn, content=m.content, keywords=m.keywords, predicate=m.predicate, subject_id=m.subject_id
    )
    conn.execute(
        "INSERT INTO memory_fts (rowid, body, hints) VALUES (?, ?, ?)",
        (m.rowid, f"{body} {' '.join(text.words(m.value))}", hints),
    )


def reindex_subject(conn: Connection, subject_id: str) -> None:
    for m in memories_for_subject(conn, subject_id, statuses=("active", "superseded", "retracted")):
        reindex_memory(conn, m.id)


def delete_memory(conn: Connection, memory: Memory) -> None:
    """Hard delete: the row, its evidence (cascade), its FTS terms, and the content of its
    history versions (a content-free tombstone stays)."""
    conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (memory.rowid,))
    conn.execute("DELETE FROM memories WHERE id = ?", (memory.id,))
    purge_history(conn, "memories", memory.id)


def purge_history(conn: Connection, table: str, target_id: str) -> None:
    conn.execute(
        "UPDATE history SET before_json = NULL, after_json = NULL"
        " WHERE target_table = ? AND target_id = ?",
        (table, target_id),
    )


def optimize_index(conn: Connection) -> None:
    """Rewrite the FTS index so deleted terms do not linger in old segments."""
    conn.execute("INSERT INTO memory_fts (memory_fts) VALUES ('optimize')")


def count_memories(conn: Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) FROM memories GROUP BY status").fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def record_recall(conn: Connection, memory_ids: Sequence[str], now: str) -> None:
    conn.executemany(
        "UPDATE memories SET recall_count = recall_count + 1, last_recalled_at = ? WHERE id = ?",
        [(now, mid) for mid in memory_ids],
    )


# ----- evidence --------------------------------------------------------------------------
def add_evidence(
    conn: Connection,
    memory_id: str,
    *,
    source_type: str,
    source_ref: str | None,
    quote: str | None,
    now: str,
) -> bool:
    """One piece of evidence per source: the same message (or import item) read again — a
    retried job, a re-import — is not a second confirmation. False when it was known."""
    if (
        source_ref is not None
        and conn.execute(
            "SELECT 1 FROM memory_evidence WHERE memory_id = ? AND source_type = ?"
            " AND source_ref = ?",
            (memory_id, source_type, source_ref),
        ).fetchone()
    ):
        return False
    conn.execute(
        "INSERT INTO memory_evidence (id, memory_id, source_type, source_ref, quote, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (new_ulid(), memory_id, source_type, source_ref, quote, now),
    )
    return True


def independent_sources(conn: Connection, memory_id: str) -> int:
    """How many different messages / imports / edits back a memory."""
    row = conn.execute(
        "SELECT COUNT(DISTINCT source_type || ':' || COALESCE(source_ref, id)) FROM"
        " memory_evidence WHERE memory_id = ?",
        (memory_id,),
    ).fetchone()
    return int(row[0]) if row else 0


def evidence_for(conn: Connection, memory_id: str) -> list[Evidence]:
    rows = conn.execute(
        "SELECT id, memory_id, source_type, source_ref, quote, created_at FROM memory_evidence"
        " WHERE memory_id = ? ORDER BY created_at",
        (memory_id,),
    ).fetchall()
    return [Evidence(str(r[0]), str(r[1]), r[2], r[3], r[4], str(r[5])) for r in rows]


def move_evidence(conn: Connection, from_memory: str, to_memory: str) -> None:
    conn.execute(
        "UPDATE memory_evidence SET memory_id = ? WHERE memory_id = ?", (to_memory, from_memory)
    )


# ----- inbox -----------------------------------------------------------------------------
def insert_inbox(
    conn: Connection,
    *,
    type: str,
    summary: str,
    payload: dict[str, Any],
    now: str,
    conversation_id: str | None = None,
    source_message_id: str | None = None,
) -> str:
    iid = new_ulid()
    conn.execute(
        "INSERT INTO memory_inbox (id, type, status, summary, payload_json, conversation_id,"
        " source_message_id, created_at) VALUES (?, ?, 'open', ?, ?, ?, ?, ?)",
        (
            iid,
            type,
            summary,
            json.dumps(payload, ensure_ascii=False),
            conversation_id,
            source_message_id,
            now,
        ),
    )
    return iid


def _inbox(row: Sequence[Any]) -> InboxItem:
    return InboxItem(
        id=str(row[0]),
        type=row[1],
        status=row[2],
        summary=str(row[3]),
        payload=json.loads(row[4]),
        conversation_id=row[5],
        source_message_id=row[6],
        created_at=str(row[7]),
        resolved_at=row[8],
        resolution=row[9],
    )


_INBOX_COLS = (
    "id, type, status, summary, payload_json, conversation_id, source_message_id, created_at,"
    " resolved_at, resolution"
)


def get_inbox(conn: Connection, item_id: str) -> InboxItem | None:
    row = conn.execute(
        f"SELECT {_INBOX_COLS} FROM memory_inbox WHERE id = ?",  # noqa: S608
        (item_id,),
    ).fetchone()
    return None if row is None else _inbox(row)


def list_inbox(
    conn: Connection, *, status: str = "open", types: Sequence[str] | None = None, limit: int = 100
) -> list[InboxItem]:
    sql = f"SELECT {_INBOX_COLS} FROM memory_inbox WHERE status = ?"  # noqa: S608
    args: list[Any] = [status]
    if types:
        sql += f" AND type IN ({','.join('?' * len(types))})"
        args += list(types)
    sql += " ORDER BY created_at DESC LIMIT ?"
    args.append(limit)
    return [_inbox(r) for r in conn.execute(sql, args).fetchall()]


def resolve_inbox(
    conn: Connection, item_id: str, *, status: str, resolution: str, now: str
) -> None:
    # A closed item keeps no text: a rejected sensitive fact or an applied import batch must
    # not linger in the database. The decision itself (status, resolution) stays.
    conn.execute(
        "UPDATE memory_inbox SET status = ?, resolution = ?, resolved_at = ?, summary = '',"
        " payload_json = '{}' WHERE id = ?",
        (status, resolution, now, item_id),
    )


def delete_inbox(conn: Connection, item_id: str) -> None:
    conn.execute("DELETE FROM memory_inbox WHERE id = ?", (item_id,))


# ----- jobs ------------------------------------------------------------------------------
_JOB_COLS = "id, user_message_id, conversation_id, model, status, attempts, last_error, created_at"


def _job(row: Sequence[Any]) -> Job:
    return Job(
        str(row[0]), str(row[1]), str(row[2]), str(row[3]), row[4], int(row[5]), row[6], str(row[7])
    )


def enqueue_job(
    conn: Connection,
    *,
    user_message_id: str,
    conversation_id: str,
    model: str,
    status: str,
    now: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO memory_jobs (id, user_message_id, conversation_id, model, status,"
        " attempts, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 0, ?, ?)",
        (new_ulid(), user_message_id, conversation_id, model, status, now, now),
    )


def next_jobs(
    conn: Connection, *, conversation_id: str, statuses: Sequence[str], limit: int
) -> list[Job]:
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT {_JOB_COLS} FROM memory_jobs WHERE conversation_id = ? AND status IN ({marks})"  # noqa: S608
        " ORDER BY created_at LIMIT ?",
        (conversation_id, *statuses, limit),
    ).fetchall()
    return [_job(r) for r in rows]


def job_for_message(conn: Connection, user_message_id: str) -> Job | None:
    row = conn.execute(
        f"SELECT {_JOB_COLS} FROM memory_jobs WHERE user_message_id = ?",  # noqa: S608
        (user_message_id,),
    ).fetchone()
    return None if row is None else _job(row)


def set_job(
    conn: Connection,
    job_id: str,
    *,
    status: str,
    now: str,
    error: str | None = None,
    result: dict[str, int] | None = None,
    attempt: bool = False,
) -> None:
    conn.execute(
        "UPDATE memory_jobs SET status = ?, last_error = ?, result_json = COALESCE(?, result_json),"
        " attempts = attempts + ?, updated_at = ? WHERE id = ?",
        (
            status,
            error,
            None if result is None else json.dumps(result),
            1 if attempt else 0,
            now,
            job_id,
        ),
    )


def recover_running_jobs(conn: Connection, now: str) -> int:
    """A job left 'running' by a crash or shutdown goes back to the queue."""
    cur = conn.execute(
        "UPDATE memory_jobs SET status = 'queued', updated_at = ? WHERE status = 'running'", (now,)
    )
    return cur.rowcount


def conversations_with_jobs(conn: Connection, statuses: Sequence[str]) -> list[str]:
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT DISTINCT conversation_id FROM memory_jobs WHERE status IN ({marks})",  # noqa: S608
        tuple(statuses),
    ).fetchall()
    return [str(r[0]) for r in rows]


def job_counts(conn: Connection) -> dict[str, int]:
    rows = conn.execute("SELECT status, COUNT(*) FROM memory_jobs GROUP BY status").fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


# ----- suppressions ----------------------------------------------------------------------
def _fingerprint_key(conn: Connection) -> bytes:
    row = conn.execute("SELECT value FROM app_meta WHERE key = 'memory_fingerprint_key'").fetchone()
    if row is not None:
        return bytes.fromhex(str(row[0]))
    key = secrets.token_bytes(32)
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES ('memory_fingerprint_key', ?)", (key.hex(),)
    )
    return key


def fingerprint(conn: Connection, subject_id: str | None, predicate: str, value_key: str) -> str:
    return fingerprint_with(_fingerprint_key(conn), subject_id, predicate, value_key)


def fingerprint_with(key: bytes, subject_id: str | None, predicate: str, value_key: str) -> str:
    msg = f"{subject_id or 'user'}\x00{predicate}\x00{value_key}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def fingerprint_key(conn: Connection) -> bytes:
    """The key of every suppression fingerprint (for checks that hash many candidates)."""
    return _fingerprint_key(conn)


def value_fingerprint_with(key: bytes, subject_id: str | None, value_key: str) -> str:
    """A forgotten value of a subject, whatever its predicate (Phase 10A): lets a sentence be
    checked for it (:mod:`lazis.memory.forgotten`) without knowing which field it was."""
    msg = f"value\x00{subject_id or 'user'}\x00{value_key}".encode()
    return hmac.new(key, msg, hashlib.sha256).hexdigest()


def forgotten_fingerprints(conn: Connection) -> frozenset[str]:
    rows = conn.execute(
        "SELECT fingerprint FROM memory_suppressions WHERE reason = 'forgotten'"
    ).fetchall()
    return frozenset(str(r[0]) for r in rows)


def add_suppression(
    conn: Connection,
    *,
    fp: str,
    subject_id: str | None,
    predicate: str | None,
    reason: str,
    now: str,
) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO memory_suppressions"
        " (fingerprint, subject_id, predicate, reason, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (fp, subject_id, predicate, reason, now),
    )


def is_suppressed(conn: Connection, fps: Sequence[str]) -> bool:
    if not fps:
        return False
    marks = ",".join("?" * len(fps))
    return (
        conn.execute(
            f"SELECT 1 FROM memory_suppressions WHERE fingerprint IN ({marks}) LIMIT 1",  # noqa: S608
            tuple(fps),
        ).fetchone()
        is not None
    )


def remove_suppressions(conn: Connection, fps: Sequence[str]) -> None:
    conn.executemany("DELETE FROM memory_suppressions WHERE fingerprint = ?", [(f,) for f in fps])


def suppressed_topics(
    conn: Connection, subject_ids: Sequence[str | None]
) -> list[tuple[str | None, str]]:
    """(subject_id, predicate) pairs forgotten as a whole ('forget his job')."""
    out: list[tuple[str | None, str]] = []
    for sid in subject_ids:
        rows = conn.execute(
            "SELECT predicate FROM memory_suppressions"  # noqa: S608 - two fixed variants
            " WHERE reason = 'forgotten' AND predicate IS NOT NULL"
            + (" AND subject_id IS NULL" if sid is None else " AND subject_id = ?"),
            () if sid is None else (sid,),
        ).fetchall()
        out += [(sid, str(r[0])) for r in rows]
    return out
