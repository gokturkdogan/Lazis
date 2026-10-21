"""Undoing an import safely (Phase 8, ADR-0019).

Not ``DELETE … WHERE import_id = ?``: the import's change set is replayed in reverse, row by row,
against the memory as it is *now*:

* a record the import created is **removed** — unless something changed it afterwards (a newer
  version in ``history``) or it has evidence from another source (said in chat, confirmed,
  edited): then it is **kept**, and only the import's evidence is removed;
* a record the import changed (a fact superseded, a relationship ended, a label set) is
  **restored** to its earlier state — unless it was changed since: then the user decides;
* a person the import created is removed only if nothing else refers to it once the import's
  own records are gone (a shared person stays);
* evidence the import added to existing records, "different people" marks and ``rejected``
  suppressions it created are removed.

:func:`plan` shows all of this first; :func:`undo` does it in one transaction (kind
``rollback``). A second undo changes nothing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Literal

from lazis.bootstrap import store
from lazis.ids import utc_now_iso
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory import service
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import UnitOfWork

Action = Literal["remove", "restore", "keep", "decide", "remove_evidence", "gone"]
# Columns restored automatically; a change to the text of a record is the user's to decide.
_RESTORABLE = {
    "memories": ("status", "valid_from", "valid_to", "supersedes_id", "conflict_state",
                 "confidence"),
    "memory_relationships": ("status", "valid_from", "valid_to", "supersedes_id",
                             "conflict_state", "confidence"),
    "memory_entities": ("relation", "relation_key", "description"),
}  # fmt: skip
_TEXT = {"memories": ("value", "value_key", "content", "predicate", "subject_id"),
         "memory_relationships": ("type", "source_id", "target_id", "qualifier"),
         "memory_entities": ("name", "name_key", "kind")}  # fmt: skip


class UndoRefused(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Step:
    table: str
    target_id: str
    action: Action
    label: str
    reason: str = ""


@dataclass
class Plan:
    import_id: str
    already_undone: bool = False
    steps: list[Step] = field(default_factory=list[Step])

    def count(self, action: Action) -> int:
        return sum(1 for s in self.steps if s.action == action)

    def counts(self) -> dict[str, int]:
        return {a: self.count(a) for a in ("remove", "restore", "keep", "decide",
                                           "remove_evidence", "gone")}  # fmt: skip


def _latest_version(conn: Connection, table: str, target_id: str) -> int:
    return int(conn.execute(
        "SELECT COALESCE(MAX(version), 0) FROM history WHERE target_table = ? AND target_id = ?",
        (table, target_id),
    ).fetchone()[0])  # fmt: skip


# What "changed since the import" compares: the record's content, not its version count — a
# later import that was itself undone leaves the record as this import left it.
_COMPARE = {
    "memories": (*_TEXT["memories"], "status", "valid_from", "valid_to", "supersedes_id"),
    "memory_relationships": (*_TEXT["memory_relationships"], "status", "valid_from", "valid_to",
                             "supersedes_id"),
    "memory_entities": (*_TEXT["memory_entities"], "relation", "description", "status"),
}  # fmt: skip


def _changed_since(conn: Connection, table: str, target_id: str, version: int) -> bool:
    """Whether the record differs from the state this import's last write left it in."""
    if _latest_version(conn, table, target_id) == version:
        return False
    row = conn.execute(
        "SELECT after_json FROM history WHERE target_table = ? AND target_id = ? AND version = ?",
        (table, target_id, version),
    ).fetchone()
    left = json.loads(str(row[0])) if row is not None and row[0] is not None else None
    now = _row(conn, table, target_id)
    if left is None or now is None:
        return True
    return any(left.get(c) != now.get(c) for c in _COMPARE[table])


def _other_evidence(conn: Connection, table: str, target_id: str, item_ids: set[str]) -> int:
    ev = "memory_evidence" if table == "memories" else "memory_relationship_evidence"
    col = "memory_id" if table == "memories" else "relationship_id"
    rows = conn.execute(f"SELECT source_type, source_ref FROM {ev} WHERE {col} = ?",  # noqa: S608
                        (target_id,)).fetchall()  # fmt: skip
    return sum(1 for t, ref in rows if not (t == "import" and ref in item_ids))


def _label(conn: Connection, table: str, target_id: str) -> str:
    if table == "memories":
        m = repo.get_memory(conn, target_id)
        return m.content if m else target_id
    if table == "memory_relationships":
        from lazis.memory import relationships

        r = gs.get_relationship(conn, target_id)
        return (
            relationships.statement_for(conn, r.source_id, r.type, r.target_id) if r else target_id
        )
    e = repo.get_entity(conn, target_id)
    return service.entity_label(e) if e else target_id


def _row(conn: Connection, table: str, target_id: str) -> dict[str, Any] | None:
    cur = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (target_id,))  # noqa: S608
    r = cur.fetchone()
    return None if r is None else dict(zip([d[0] for d in cur.description], r, strict=True))


def _history(conn: Connection, change_set_id: str) -> list[tuple[str, str, int, str, Any]]:
    rows = conn.execute(
        "SELECT target_table, target_id, version, change, before_json FROM history"
        " WHERE change_set_id = ? ORDER BY rowid DESC",
        (change_set_id,),
    ).fetchall()
    return [(str(t), str(i), int(v), str(c), b) for t, i, v, c, b in rows]


def plan(conn: Connection, import_id: str) -> Plan:
    b = store.get_batch(conn, import_id)
    if b.status == "undone":
        return Plan(import_id, already_undone=True)
    if b.status != "applied" or b.apply_change_set_id is None:
        raise UndoRefused("not_applied")
    item_ids = {it.id for it in store.items(conn, import_id)}
    out = Plan(import_id)
    created: dict[str, set[str]] = {"memories": set(), "memory_relationships": set(),
                                    "memory_entities": set()}  # fmt: skip
    removing: set[str] = set()
    seen: set[tuple[str, str]] = set()
    rows = _history(conn, b.apply_change_set_id)
    # A record created and then updated in the same change set counts as created; "changed
    # later" compares with the last version this change set wrote.
    made = {(t, i) for t, i, _v, c, _b in rows if c == "create"}
    last: dict[tuple[str, str], int] = {}
    first_before: dict[tuple[str, str], Any] = {}
    for t, i, v, _c, bj in sorted(rows, key=lambda r: r[2]):
        last[(t, i)] = max(last.get((t, i), 0), v)
        first_before.setdefault((t, i), bj)
    # Records first (facts, relationships), people last: whether a person can go depends on them.
    order = {"memories": 0, "memory_relationships": 1, "memory_entities": 2}
    for table, tid in sorted({(t, i) for t, i, *_ in rows}, key=lambda r: order.get(r[0], 9)):
        if (table, tid) in seen or table not in order:
            continue
        seen.add((table, tid))
        change = "create" if (table, tid) in made else "update"
        before_json = first_before[(table, tid)]
        now_row = _row(conn, table, tid)
        if now_row is None:
            out.steps.append(Step(table, tid, "gone", tid, "already_deleted"))
            continue
        label = _label(conn, table, tid)
        later = _changed_since(conn, table, tid, last[(table, tid)])
        if change == "create":
            created[table].add(tid)
            if table == "memory_entities":
                continue  # decided below, once the records are known
            if later:
                out.steps.append(Step(table, tid, "keep", label, "changed_later"))
            elif _other_evidence(conn, table, tid, item_ids):
                out.steps.append(Step(table, tid, "keep", label, "confirmed_elsewhere"))
                out.steps.append(Step(table, tid, "remove_evidence", label))
            else:
                out.steps.append(Step(table, tid, "remove", label))
                removing.add(tid)
        elif change == "update":
            if later:
                out.steps.append(Step(table, tid, "decide", label, "changed_later"))
                continue
            before = json.loads(str(before_json)) if before_json else None
            if before is None:
                continue
            if any(before.get(c) != now_row.get(c) for c in _TEXT.get(table, ())):
                out.steps.append(Step(table, tid, "decide", label, "text_changed"))
                continue
            if any(before.get(c) != now_row.get(c) for c in _RESTORABLE.get(table, ())):
                out.steps.append(Step(table, tid, "restore", label))
    # Evidence the import added to records it did not create (duplicates it confirmed).
    for table, ev, col in (("memories", "memory_evidence", "memory_id"),
                           ("memory_relationships", "memory_relationship_evidence",
                            "relationship_id")):  # fmt: skip
        marks = ",".join("?" * len(item_ids)) or "''"
        for (tid,) in conn.execute(
            f"SELECT DISTINCT {col} FROM {ev} WHERE source_type = 'import'"  # noqa: S608
            f" AND source_ref IN ({marks})",
            tuple(item_ids),
        ).fetchall():
            tid = str(tid)
            listed = {(s.table, s.target_id) for s in out.steps if s.action == "remove_evidence"}
            if tid in created[table] or (table, tid) in listed:
                continue
            out.steps.append(Step(table, tid, "remove_evidence", _label(conn, table, tid)))
    # People the import created: removed only if nothing else refers to them.
    for eid in created["memory_entities"]:
        label = _label(conn, "memory_entities", eid)
        refs_mem = [str(r[0]) for r in conn.execute(
            "SELECT id FROM memories WHERE subject_id = ?", (eid,)).fetchall()]  # fmt: skip
        refs_rel = [str(r[0]) for r in conn.execute(
            "SELECT id FROM memory_relationships WHERE source_id = ? OR target_id = ?",
            (eid, eid)).fetchall()]  # fmt: skip
        others = [x for x in [*refs_mem, *refs_rel] if x not in removing]
        # Its own name is always an alias; any other was added afterwards (by the user).
        aliases = conn.execute(
            "SELECT COUNT(*) FROM memory_entity_aliases a JOIN memory_entities e ON e.id ="
            " a.entity_id WHERE a.entity_id = ? AND a.alias_key != e.name_key",
            (eid,),
        ).fetchone()[0]
        changed_later = _changed_since(conn, "memory_entities", eid, last[("memory_entities", eid)])
        if others or changed_later or int(aliases) > 0:
            out.steps.append(Step("memory_entities", eid, "keep", label, "still_referred_to"))
        else:
            out.steps.append(Step("memory_entities", eid, "remove", label))
    # A record the import replaced comes back only if its replacement goes: a kept replacement
    # (changed or confirmed since) and a restored original would both be current.
    kept = {s.target_id for s in out.steps if s.action == "keep"}
    replaced: set[str] = set()
    for table in ("memories", "memory_relationships"):
        for tid in kept & created[table]:
            row = _row(conn, table, tid)
            if row is not None and row.get("supersedes_id"):
                replaced.add(str(row["supersedes_id"]))
    out.steps = [
        replace(s, action="decide", reason="replacement_kept")
        if s.action == "restore" and s.target_id in replaced else s
        for s in out.steps
    ]  # fmt: skip
    return out


def undo(conn: Connection, import_id: str, *, restore: frozenset[str] = frozenset()
         ) -> tuple[Plan, str | None]:  # fmt: skip
    """Undo an applied import (plan computed again, inside the transaction). Returns the plan
    that was carried out and the rollback change set (None when it was already undone).

    ``restore``: records the plan left for the user to decide (changed since the import) that
    the user chose to restore anyway; the others are kept as they are now."""
    b = store.get_batch(conn, import_id)
    if b.status == "undone":
        return Plan(import_id, already_undone=True), None
    item_ids = {it.id for it in store.items(conn, import_id)}
    now = utc_now_iso()
    with UnitOfWork(conn, kind="rollback", actor="user", summary="aktarım geri alındı",
                    source_ref=import_id, reverts=b.apply_change_set_id) as uow:  # fmt: skip
        p = plan(conn, import_id)  # again, inside the transaction: the memory as it is now
        if (
            conn.execute(
                "UPDATE import_batches SET status = 'undone', undone_at = ?, updated_at = ?,"
                " undo_change_set_id = ? WHERE id = ? AND status = 'applied'",
                (now, now, uow.change_set_id, import_id),
            ).rowcount
            != 1
        ):
            raise UndoRefused("not_applied")
        for s in p.steps:
            if s.action == "remove_evidence":
                ev = "memory_evidence" if s.table == "memories" else "memory_relationship_evidence"
                col = "memory_id" if s.table == "memories" else "relationship_id"
                marks = ",".join("?" * len(item_ids))
                conn.execute(f"DELETE FROM {ev} WHERE {col} = ? AND source_type = 'import'"  # noqa: S608
                             f" AND source_ref IN ({marks})", (s.target_id, *item_ids))  # fmt: skip
            elif s.action == "remove" and s.table == "memories":
                m = repo.get_memory(conn, s.target_id)
                if m is not None:
                    uow.record("memories", m.id, "delete", uow.snapshot("memories", m.id))
                    repo.delete_memory(conn, m)
            elif s.action == "remove" and s.table == "memory_relationships":
                uow.record("memory_relationships", s.target_id, "delete",
                           uow.snapshot("memory_relationships", s.target_id))  # fmt: skip
                gs.delete_relationship(conn, s.target_id)
            elif s.action == "remove" and s.table == "memory_entities":
                uow.record("memory_entities", s.target_id, "delete",
                           uow.snapshot("memory_entities", s.target_id))  # fmt: skip
                conn.execute("DELETE FROM memory_entity_distinctions WHERE entity_a = ? OR"
                             " entity_b = ?", (s.target_id, s.target_id))  # fmt: skip
                repo.delete_entity(conn, s.target_id)
            elif s.action == "restore" or (s.action == "decide" and s.target_id in restore):
                _restore(conn, uow, b.apply_change_set_id or "", s.table, s.target_id)
        for a, c in b.effects.get("distinctions", []):
            conn.execute(
                "DELETE FROM memory_entity_distinctions WHERE entity_a = ? AND entity_b = ?", (a, c)
            )
        for fp in b.effects.get("suppressions", []):
            conn.execute("DELETE FROM memory_suppressions WHERE fingerprint = ? AND reason ="
                         " 'rejected'", (fp,))  # fmt: skip
        conn.execute("UPDATE import_batches SET counts_json = ? WHERE id = ?",
                     (json.dumps({**b.counts, "undo": {**p.counts(), "restored_by_choice":
                      sum(1 for s in p.steps if s.action == "decide" and s.target_id in restore)}}),
                      import_id))  # fmt: skip
        write_audit(conn, category="memory", action="bootstrap_undo", outcome="success",
                    actor="user", change_set_id=uow.change_set_id,
                    details={k: v for k, v in p.counts().items()})  # fmt: skip
        cs = uow.change_set_id
    repo.optimize_index(conn)
    return p, cs


def _restore(conn: Connection, uow: UnitOfWork, change_set_id: str, table: str, tid: str) -> None:
    row = conn.execute(
        "SELECT before_json FROM history WHERE change_set_id = ? AND target_table = ?"
        " AND target_id = ? ORDER BY version ASC LIMIT 1",
        (change_set_id, table, tid),
    ).fetchone()
    if row is None or row[0] is None:
        return
    before = json.loads(str(row[0]))
    cols = [c for c in _RESTORABLE[table] if c in before]
    snap = uow.snapshot(table, tid)
    sets = ", ".join(f"{c} = ?" for c in cols)
    conn.execute(f"UPDATE {table} SET {sets}, updated_at = ? WHERE id = ?",  # noqa: S608
                 (*[before[c] for c in cols], utc_now_iso(), tid))  # fmt: skip
    uow.record(table, tid, "restore", snap)
