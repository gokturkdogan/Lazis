"""Writing an import: only what the user approved, all or nothing (Phase 8, ADR-0019).

One change set (kind ``import``, source = the import id), one transaction:

1. a final check — every approved item is classified again against the memory as it is now;
   if one became a conflict (the user said something else in chat meanwhile), nothing is
   written and the preview is shown again;
2. people the user chose to create; people linked to stored ones;
3. approved facts whose subject is settled — with the conflict choice (keep the old: nothing
   written; update: the old becomes history; keep both);
4. approved relationships whose two ends are settled;
5. rejected facts about a known subject get a ``rejected`` suppression (not relearned);
6. the batch becomes ``applied`` in the same transaction (a second apply is refused).

Every number reported comes from what the transaction wrote, item by item.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from lazis.bootstrap import analyze, store
from lazis.bootstrap.proposals import USER, label_of
from lazis.ids import utc_now_iso
from lazis.memory import graphstore as gs
from lazis.memory import relations, relationships, service, text
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID, ApplyReport, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import UnitOfWork


class ApplyRefused(ValueError):
    """``code``: already_applied | not_ready | memory_changed; ``items``: the ids concerned."""

    def __init__(self, code: str, items: tuple[str, ...] = ()) -> None:
        super().__init__(code)
        self.code = code
        self.items = items


@dataclass
class ApplyResult:
    import_id: str
    change_set_id: str
    counts: dict[str, int] = field(default_factory=dict[str, int])


def _final_check(conn: Connection, import_id: str) -> None:
    """Approved items are compared with the memory again; a new conflict stops the write."""
    before = {it.id: it.classification for it in store.items(conn, import_id)}
    conn.execute("BEGIN IMMEDIATE")
    try:
        store.reclassify(conn, import_id)
        after = store.items(conn, import_id)
    finally:
        conn.execute("ROLLBACK")  # the check itself changes nothing
    changed = tuple(
        it.id for it in after
        if it.decision == "approve" and before.get(it.id) != it.classification
        and it.classification in (*store.NEEDS_RESOLUTION, "excluded", "ambiguous_entity")
    )  # fmt: skip
    if changed:
        raise ApplyRefused("memory_changed", changed)


def apply(conn: Connection, import_id: str) -> ApplyResult:
    b = store.get_batch(conn, import_id)
    if b.status == "applied":
        raise ApplyRefused("already_applied")
    if b.status != "ready":
        raise ApplyRefused("not_ready")
    _final_check(conn, import_id)
    try:
        return _apply(conn, import_id)
    except ApplyRefused:
        raise
    except Exception:
        # Rolled back: nothing was written. The draft stays as it was; trying again is the
        # user's explicit choice. The failure is recorded, never reported as success.
        store.set_status(conn, import_id, "ready", error="apply_failed", only_from=("ready",))
        write_audit(conn, category="memory", action="bootstrap_import", outcome="failure",
                    actor="user", details={"import_id": import_id})  # fmt: skip
        raise


def _apply(conn: Connection, import_id: str) -> ApplyResult:
    people = store.people(conn, import_id)
    its = store.items(conn, import_id)
    now = utc_now_iso()
    counts = {"analyzed": len(its), "approved": 0, "written": 0, "updated": 0, "evidence_added": 0,
              "kept_old": 0, "held": 0, "rejected": 0, "pending": 0, "blocked": 0, "failed": 0,
              "excluded": 0, "people_created": 0, "people_linked": 0}  # fmt: skip
    effects: dict[str, Any] = {"distinctions": [], "suppressions": []}
    with UnitOfWork(conn, kind="import", actor="user", summary="kişisel bilgi aktarımı",
                    source_ref=import_id) as uow:  # fmt: skip
        if (
            conn.execute(
                "UPDATE import_batches SET status = 'applied', error = NULL, applied_at = ?,"
                " updated_at = ?, apply_change_set_id = ? WHERE id = ? AND status = 'ready'",
                (now, now, uow.change_set_id, import_id),
            ).rowcount
            != 1
        ):
            raise ApplyRefused("already_applied")

        # -- people
        entity_of: dict[str, str] = {}
        for p in people:
            if p.decision == "create":
                label = None if relations.sensitive_label(p.relation) else p.relation
                ent = repo.insert_entity(conn, kind=p.kind, name=p.name, relation=label,
                                         description=p.description, now=now)  # fmt: skip
                uow.record("memory_entities", ent.id, "create", None)
                entity_of[p.id] = ent.id
                counts["people_created"] += 1
        for p in people:
            if p.decision == "link":
                state, eid = store.target_entity(conn, import_id, p.id)
                if state == "stored" and eid is not None:
                    entity_of[p.id] = eid
                    counts["people_linked"] += 1
                elif state == "new" and p.link_id in entity_of:
                    entity_of[p.id] = entity_of[p.link_id]
        for p in people:
            if p.id in entity_of:
                conn.execute("UPDATE import_people SET entity_id = ? WHERE id = ?",
                             (entity_of[p.id], p.id))  # fmt: skip
        # Namesakes the file kept apart are different people from now on.
        settled = [(p, entity_of[p.id]) for p in people if p.id in entity_of]
        for i, (p, a) in enumerate(settled):
            for q, c in settled[i + 1 :]:
                if (
                    a != c
                    and text.name_key(p.name) == text.name_key(q.name)
                    and not gs.are_distinct(conn, a, c)
                ):
                    gs.add_distinction(conn, a, c, now)
                    effects["distinctions"].append(sorted((a, c)))
        # A person the user created although stored namesakes were shown is not one of them.
        for p in people:
            if p.decision != "create" or p.id not in entity_of:
                continue
            shown: list[str] = [o["id"] for o in p.options if o.get("kind") != "import"]
            if p.suggested_id and p.suggested_id not in shown:
                shown.append(p.suggested_id)
            for oid in shown:
                other = repo.get_entity(conn, oid)
                a = entity_of[p.id]
                if (
                    other is not None
                    and other.status == "active"
                    and text.name_key(other.name) == text.name_key(p.name)
                    and not gs.are_distinct(conn, a, other.id)
                ):
                    gs.add_distinction(conn, a, other.id, now)
                    effects["distinctions"].append(sorted((a, other.id)))

        def settled_ref(ref: str | None) -> str | None:
            if ref == USER:
                return USER_ID
            return entity_of.get(ref or "")

        # -- facts, then relationships (their ends may be people created above)
        for it in its:
            result, ids = "", []
            if it.classification == "excluded":
                counts["excluded"] += 1
                result = "excluded"
            elif it.decision == "reject":
                counts["rejected"] += 1
                result = "rejected"
                if it.kind == "fact":
                    sid = settled_ref(it.subject_ref)
                    if sid is not None or it.subject_ref == USER:
                        subject = None if it.subject_ref == USER else sid
                        f = it.fact()
                        value_key = text.fold(it.edited_value or f.value).strip()
                        fp = repo.fingerprint(conn, subject, f.predicate, value_key)
                        if not repo.is_suppressed(conn, [fp]):
                            repo.add_suppression(conn, fp=fp, subject_id=subject, predicate=None,
                                                 reason="rejected", now=now)  # fmt: skip
                            effects["suppressions"].append(fp)
            elif it.decision == "hold":
                counts["held"] += 1
                result = "held"
            elif it.decision == "pending":
                counts["pending"] += 1
                result = "pending"
            else:
                counts["approved"] += 1
                ends = [settled_ref(r) for r in it.refs()]
                if any(e is None for e in ends) or (
                    it.classification in store.NEEDS_RESOLUTION and it.resolution is None
                ):
                    counts["blocked"] += 1
                    result = "blocked"
                elif it.resolution == "keep_old":
                    counts["kept_old"] += 1
                    result = "kept_old"
                elif it.kind == "fact":
                    result, ids = _write_fact(conn, uow, it, settled_ref, people, now, counts)
                else:
                    result, ids = _write_relation(conn, uow, it, settled_ref, now, counts)
            conn.execute(
                "UPDATE import_items SET result = ?, result_ids_json = ?, updated_at = ?"
                " WHERE id = ?",
                (result, json.dumps(ids), now, it.id),
            )
        store.forget_text(conn, import_id)
        conn.execute(
            "UPDATE import_batches SET counts_json = ?, effects_json = ? WHERE id = ?",
            (json.dumps(counts), json.dumps(effects), import_id),
        )
        write_audit(conn, category="memory", action="bootstrap_import", outcome="success",
                    actor="user", change_set_id=uow.change_set_id,
                    details={k: v for k, v in counts.items()})  # fmt: skip
        cs = uow.change_set_id
    return ApplyResult(import_id, cs, counts)


def _subject_ref(it: store.Item, settled_ref: Any, people: list[store.Person]) -> EntityRef | None:
    if it.subject_ref == USER:
        return None
    eid = settled_ref(it.subject_ref)
    p = next(p for p in people if p.id == it.subject_ref)
    return EntityRef(p.name, p.kind, p.relation, ref_id=eid, planned=True)  # type: ignore[arg-type]


def _write_fact(
    conn: Connection,
    uow: UnitOfWork,
    it: store.Item,
    settled_ref: Any,
    people: list[store.Person],
    now: str,
    counts: dict[str, int],
) -> tuple[str, list[str]]:
    f = it.fact()
    ref = _subject_ref(it, settled_ref, people)
    value = it.edited_value or f.value
    statement = f.statement
    if it.edited_value:
        who = "Kullanıcı" if ref is None else (f"{ref.name} ({ref.relation})" if ref.relation
                                              else ref.name)  # fmt: skip
        statement = f"{who} — {label_of(f.predicate)}: {value}"
    c = analyze.candidate(f, value=value, entity=ref, statement=statement)
    force = {"update": "supersede", "keep_both": "create"}.get(it.resolution or "")
    report = ApplyReport()
    service.apply_one(conn, uow, c, source=Source("import", it.id), explicit=True, report=report,
                      now=now, forced_subject=(None if ref is None else ref.ref_id,),
                      force=force)  # type: ignore[arg-type]  # fmt: skip
    if report.created:
        counts["written"] += 1
        if report.superseded:
            counts["updated"] += 1
        return ("updated" if report.superseded else "written"), [*report.created]
    if report.updated:
        counts["evidence_added"] += 1
        return "evidence_added", [*report.updated]
    if report.inbox:
        counts["failed"] += 1
        return "inbox", []
    counts["failed"] += 1
    return "failed:" + ",".join(sorted(report.dropped)) if report.dropped else "failed", []


def _write_relation(conn: Connection, uow: UnitOfWork, it: store.Item, settled_ref: Any,
                    now: str, counts: dict[str, int]) -> tuple[str, list[str]]:  # fmt: skip
    r = it.relation()
    src, tgt = settled_ref(it.source_ref), settled_ref(it.target_ref)
    rc = RelCandidate(
        type=r.type, target=EntityRef("x"), source=None, quote=it.excerpt,
        statement=r.statement, change=r.change or it.resolution == "update",
        correction=r.correction, negated=r.negated, status=r.status, certain=r.certain,
        time_text=r.time, origin="imported",
    )  # fmt: skip
    force = {"update": "replace", "keep_both": "coexist"}.get(it.resolution or "")
    rep = relationships.RelReport()
    relationships.apply_one(conn, uow, rc, source=Source("import", it.id), explicit=True,
                            report=rep, now=now, forced_source=src, forced_target=tgt,
                            force=force)  # type: ignore[arg-type]  # fmt: skip
    written = [*rep.created]
    if written:
        counts["written"] += 1
        if rep.superseded or rep.ended or rep.retracted:
            counts["updated"] += 1
        return ("updated" if rep.superseded or rep.ended or rep.retracted else "written"), written
    if rep.updated:
        counts["evidence_added"] += 1
        return "evidence_added", [*rep.updated]
    if rep.retracted:
        counts["updated"] += 1
        return "updated", [*rep.retracted]
    counts["failed"] += 1
    return ("failed:" + ",".join(sorted(rep.dropped)) if rep.dropped else
            "inbox" if rep.inbox else "failed"), []  # fmt: skip
