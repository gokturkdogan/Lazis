"""Helpers for the Phase 8 import tests: synthetic profiles, decisions, and snapshots of the
memory (to compare "before the import" with "after undo"). Synthetic data only."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any

from lazis.bootstrap import apply, files, pipeline, store, undo
from lazis.memory import repository as repo
from lazis.memory import service
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.storage import StorageHandle, driver

Conn = driver.Connection


def run[T](storage: StorageHandle, fn: Callable[[Conn], T]) -> T:
    return storage.db.run_sync(fn)


def profile_bytes(doc: dict[str, Any]) -> bytes:
    return json.dumps({"schema_version": "1.0", **doc}, ensure_ascii=False, indent=1).encode()


def start(storage: StorageHandle, doc: dict[str, Any], name: str = "profil.json") -> str:
    f = files.read(name, profile_bytes(doc))
    return run(storage, lambda c: pipeline.start_json(c, f))


def people(storage: StorageHandle, iid: str) -> list[store.Person]:
    return run(storage, lambda c: store.people(c, iid))


def items(storage: StorageHandle, iid: str) -> list[store.Item]:
    return run(storage, lambda c: store.items(c, iid))


def person(storage: StorageHandle, iid: str, label: str) -> store.Person:
    found = [p for p in people(storage, iid) if p.label == label or p.name == label]
    assert len(found) == 1, (label, [p.label for p in people(storage, iid)])
    return found[0]


def item(storage: StorageHandle, iid: str, value: str) -> store.Item:
    """The one item whose value (or relationship type) is ``value``."""
    found = [it for it in items(storage, iid)
             if it.payload.get("value") == value or it.payload.get("type") == value]  # fmt: skip
    assert len(found) == 1, (value, [(i.payload.get("value"), i.payload.get("type"))
                                     for i in items(storage, iid)])  # fmt: skip
    return found[0]


def decide_person(storage: StorageHandle, iid: str, label: str, decision: str,
                  link: str | None = None) -> None:  # fmt: skip
    pid = person(storage, iid, label).id
    run(storage, lambda c: store.decide_person(c, iid, pid, decision, link))  # type: ignore[arg-type]


def decide(storage: StorageHandle, iid: str, item_id: str, decision: str, *,
           resolution: str | None = None, edited: str | None = None) -> None:  # fmt: skip
    run(storage, lambda c: store.decide_item(c, iid, item_id, decision, resolution=resolution,  # type: ignore[arg-type]
                                             edited_value=edited))  # fmt: skip


def approve_all(storage: StorageHandle, iid: str, resolution: str = "update") -> None:
    """What a user does by clicking every "approve" (tests only; the UI has no such button)."""
    for it in items(storage, iid):
        if it.classification == "excluded":
            continue
        res = resolution if it.classification in store.NEEDS_RESOLUTION else None
        decide(storage, iid, it.id, "approve", resolution=res)


def create_all_people(storage: StorageHandle, iid: str) -> None:
    for p in people(storage, iid):
        run(storage, lambda c, p=p: store.decide_person(c, iid, p.id, "create"))


def do_apply(storage: StorageHandle, iid: str) -> apply.ApplyResult:
    return run(storage, lambda c: apply.apply(c, iid))


def plan(storage: StorageHandle, iid: str) -> undo.Plan:
    return run(storage, lambda c: undo.plan(c, iid))


def do_undo(storage: StorageHandle, iid: str, restore: Iterable[str] = ()) -> undo.Plan:
    chosen = frozenset(restore)
    return run(storage, lambda c: undo.undo(c, iid, restore=chosen))[0]


def remember(storage: StorageHandle, predicate: str, value: str, statement: str, *,
             entity: EntityRef | None = None, source: str = "user_edit") -> list[str]:  # fmt: skip
    """A memory that exists before the import (as if said in chat)."""
    c = Candidate(predicate=predicate, value=value, statement=statement,
                  about="user" if entity is None else "entity", entity=entity)  # fmt: skip
    return run(storage, lambda conn: service.apply_candidates(
        conn, [c], source=Source(source), explicit=True)).created  # type: ignore[arg-type]  # fmt: skip


def active(storage: StorageHandle) -> set[tuple[str, str, str]]:
    """(subject name or "user", predicate, value) of every current memory."""

    def read(c: Conn) -> set[tuple[str, str, str]]:
        out: set[tuple[str, str, str]] = set()
        for m in repo.list_memories(c, limit=10_000):
            who = "user"
            if m.subject_id is not None:
                e = repo.get_entity(c, m.subject_id)
                who = e.name if e is not None else "?"
            out.add((who, m.predicate, m.value))
        return out

    return run(storage, read)


def subject_of(storage: StorageHandle, value: str) -> str | None:
    """The stored entity id the current memory with this value is about."""
    ms = [
        m for m in run(storage, lambda c: repo.list_memories(c, limit=10_000)) if m.value == value
    ]
    assert len(ms) == 1, value
    return ms[0].subject_id


_TABLES = {
    "memories": "id, subject_id, predicate, value, status, supersedes_id, valid_to",
    "memory_entities": "id, name, relation, status",
    "memory_relationships": "id, source_id, type, target_id, status, supersedes_id, valid_to",
    "memory_evidence": "memory_id, source_type, source_ref",
    "memory_relationship_evidence": "relationship_id, source_type, source_ref",
    "memory_suppressions": "fingerprint, reason",
    "memory_entity_distinctions": "entity_a, entity_b",
    "memory_entity_aliases": "entity_id, alias_key",
}


def snapshot(storage: StorageHandle) -> dict[str, set[tuple[Any, ...]]]:
    """Everything the memory holds, row by row (what an undo must give back)."""

    def read(c: Conn) -> dict[str, set[tuple[Any, ...]]]:
        return {t: {tuple(r) for r in c.execute(f"SELECT {cols} FROM {t}").fetchall()}
                for t, cols in _TABLES.items()}  # fmt: skip

    return run(storage, read)


def relationships(storage: StorageHandle) -> set[tuple[str, str, str, str]]:
    """(source name, type, target name, status) of every relationship."""

    def read(c: Conn) -> set[tuple[str, str, str, str]]:
        rows = c.execute(
            "SELECT s.name, r.type, t.name, r.status FROM memory_relationships r"
            " JOIN memory_entities s ON s.id = r.source_id"
            " JOIN memory_entities t ON t.id = r.target_id"
        ).fetchall()
        return {(str(a), str(b), str(d), str(e)) for a, b, d, e in rows}

    return run(storage, read)


def stored_person(storage: StorageHandle, name: str, relation: str | None,
                  facts: dict[str, str] | None = None) -> str:  # fmt: skip
    """A person already in memory (as if learned earlier), with some facts about them."""
    from lazis.ids import utc_now_iso
    from lazis.storage.unit_of_work import UnitOfWork

    def make(c: Conn) -> str:
        with UnitOfWork(c, kind="memory", actor="user", summary="test") as uow:
            e = repo.insert_entity(c, kind="person", name=name, relation=relation,
                                   description=None, now=utc_now_iso())  # fmt: skip
            uow.record("memory_entities", e.id, "create", None)
        return e.id

    eid = run(storage, make)
    for pred, value in (facts or {}).items():
        who = f"{name} ({relation})" if relation else name
        remember(storage, pred, value, f"{who} — {pred}: {value}",
                 entity=EntityRef(name, "person", relation, ref_id=eid, planned=True))  # fmt: skip
    return eid


def distinct(storage: StorageHandle, a: str, b: str) -> bool:
    from lazis.memory import graphstore as gs

    return run(storage, lambda c: gs.are_distinct(c, a, b))


def facts_of(storage: StorageHandle, entity_id: str) -> set[tuple[str, str]]:
    return {(m.predicate, m.value)
            for m in run(storage, lambda c: repo.list_memories(c, limit=10_000))
            if m.subject_id == entity_id}  # fmt: skip
