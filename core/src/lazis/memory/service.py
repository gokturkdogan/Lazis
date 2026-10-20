"""The memory orchestrator: every knowledge write goes through here, in one transaction per
batch (``UnitOfWork`` = one change set, with per-row history; MEMORY_ARCHITECTURE P6.2).

Pipeline per candidate: policy (secret / instruction / durability / sensitivity) → subject
resolution (user, or a person/project via the resolver) → suppression (forgotten or rejected
knowledge is not re-learned automatically) → consolidation (duplicate / supersede / conflict /
create) → write (row + evidence + FTS + history). Anything that needs the user's decision goes
to the inbox instead of becoming knowledge.

Functions here are synchronous and run on the database thread (``Database.run_sync``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any, Literal

from lazis.ids import utc_now_iso
from lazis.memory import consolidation, policy, registry, resolver, text
from lazis.memory import repository as repo
from lazis.memory.models import ApplyReport, Candidate, Entity, EntityRef, InboxItem, Memory
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import Actor, UnitOfWork


@dataclass(frozen=True)
class Source:
    type: Literal["message", "import", "user_edit", "confirmation"]
    ref: str | None = None  # message id
    conversation_id: str | None = None


class NotFound(LookupError):
    pass


# ----- candidates <-> JSON (inbox payloads) ------------------------------------------------
def candidate_to_json(c: Candidate) -> dict[str, Any]:
    data = asdict(c)
    data["keywords"] = list(c.keywords)
    return data


def candidate_from_json(data: dict[str, Any]) -> Candidate:
    ent = data.get("entity")
    return Candidate(
        predicate=str(data["predicate"]),
        value=str(data["value"]),
        statement=str(data["statement"]),
        about=data.get("about", "user"),
        entity=None
        if not ent
        else EntityRef(
            ent["name"], ent.get("kind", "person"), ent.get("relation"), ent.get("ref_id")
        ),
        quote=data.get("quote"),
        event_time=data.get("event_time"),
        change=bool(data.get("change", False)),
        replaces=data.get("replaces"),
        certain=bool(data.get("certain", True)),
        sensitivity_category=data.get("sensitivity_category"),
        importance=float(data.get("importance", 0.5)),
        durable=bool(data.get("durable", True)),
        keywords=tuple(data.get("keywords", ())),
        origin=data.get("origin", "stated"),
    )


def entity_label(e: Entity) -> str:
    return f"{e.name} ({e.relation})" if e.relation else e.name


# ----- apply ---------------------------------------------------------------------------------
def apply_candidates(
    conn: Connection,
    candidates: list[Candidate],
    *,
    source: Source,
    explicit: bool,
    actor: Actor = "pipeline",
    kind: str = "learning_run",
) -> ApplyReport:
    report = ApplyReport()
    if not candidates:
        return report
    now = utc_now_iso()
    with UnitOfWork(
        conn, kind=kind, actor=actor, summary=f"{len(candidates)} aday", source_ref=source.ref
    ) as uow:
        for c in candidates:
            apply_one(conn, uow, c, source=source, explicit=explicit, report=report, now=now)
        write_audit(
            conn,
            category="memory",
            action=kind,
            outcome="success",
            actor=actor,
            change_set_id=uow.change_set_id,
            details={k: v for k, v in report.counts().items()},
        )
    return report


def _subject_for(
    conn: Connection,
    uow: UnitOfWork,
    c: Candidate,
    *,
    source: Source,
    report: ApplyReport,
    now: str,
) -> tuple[Literal["ok", "ambiguous", "drop"], str | None]:
    if c.about == "user":
        return "ok", None
    ref = c.entity
    if ref is None or not text.name_key(ref.name):
        report.drop("no_entity")
        return "drop", None
    key = text.name_key(ref.name)
    candidates = repo.find_entities(conn, key)
    res = resolver.resolve(ref, candidates)
    if res.kind == "existing" and not ref.relation and _pending_namesake(conn, key):
        # Another person with this name may exist (an open "which Ahmet?" question): without
        # a relation in this message, attaching to the stored one would be a guess.
        res = resolver.Resolution("ambiguous", options=tuple(e.id for e in candidates),
                                  reason="pending_namesake")  # fmt: skip
    from lazis.memory import relationships

    if res.kind == "existing":
        assert res.entity_id is not None
        if ref.relation:
            # The user's own words for how they know them → the typed user relationship
            # (only when the words map exactly to the vocabulary; else just the label).
            relationships.ensure_user_relation(
                conn, uow, res.entity_id, ref.relation, now=now,
                source_type=source.type, source_ref=source.ref, quote=c.quote,
            )  # fmt: skip
        return "ok", res.entity_id
    if res.kind == "new":
        ent = repo.insert_entity(
            conn, kind=ref.kind, name=ref.name, relation=ref.relation, description=None, now=now
        )
        uow.record("memory_entities", ent.id, "create", None)
        report.entities_created.append(ent.id)
        if ref.relation:
            relationships.ensure_user_relation(
                conn, uow, ent.id, ref.relation, now=now,
                source_type=source.type, source_ref=source.ref, quote=c.quote,
            )  # fmt: skip
        return "ok", ent.id
    options = [repo.get_entity(conn, oid) for oid in res.options]
    payload = {
        "candidate": candidate_to_json(c),
        "options": [{"id": o.id, "label": entity_label(o)} for o in options if o is not None],
        "reason": res.reason,
    }
    iid = repo.insert_inbox(
        conn,
        type="ambiguous_entity",
        summary=f"Hangi {ref.name}? — {c.statement}",
        payload=payload,
        now=now,
        conversation_id=source.conversation_id,
        source_message_id=source.ref,
    )
    report.inbox.append(iid)
    return "ambiguous", None


def _pending_namesake(conn: Connection, key: str) -> bool:
    for item in repo.list_inbox(conn, status="open", types=("ambiguous_entity",)):
        if key in item.payload.get("pending_names", []):
            return True
        cand: dict[str, Any] = item.payload.get("candidate", {})
        ent: dict[str, Any] = cand.get("entity") or {}
        if text.name_key(str(ent.get("name", ""))) == key:
            return True
    return False


def _fingerprints(conn: Connection, subject_id: str | None, c: Candidate) -> list[str]:
    return [
        repo.fingerprint(conn, subject_id, c.predicate, text.fold(c.value).strip()),
        repo.fingerprint(conn, subject_id, c.predicate, "*"),
    ]


def apply_one(
    conn: Connection,
    uow: UnitOfWork,
    c: Candidate,
    *,
    source: Source,
    explicit: bool,
    report: ApplyReport,
    now: str,
    forced_subject: tuple[str | None] | None = None,
    force: Literal["create", "supersede"] | None = None,
) -> None:
    decision = policy.decide(c, explicit=explicit)
    if decision.outcome == "drop":
        report.drop(decision.reason)
        return
    if forced_subject is not None:
        subject_id = forced_subject[0]
    else:
        status, subject_id = _subject_for(conn, uow, c, source=source, report=report, now=now)
        if status != "ok":
            return
    # Forgotten or rejected before: never re-learned (or re-offered) unless asked again.
    fps = _fingerprints(conn, subject_id, c)
    if explicit:
        repo.remove_suppressions(conn, fps)
    elif repo.is_suppressed(conn, fps):
        report.drop("suppressed")
        return
    if decision.outcome == "inbox_sensitive":
        iid = repo.insert_inbox(
            conn,
            type="sensitive",
            summary=c.statement,
            payload={
                "candidate": candidate_to_json(c),
                "subject_id": subject_id,
                "category": decision.category,
            },
            now=now,
            conversation_id=source.conversation_id,
            source_message_id=source.ref,
        )
        report.inbox.append(iid)
        return
    current = repo.consolidation_candidates(
        conn, subject_id, c.predicate, value=c.value, replaces=c.replaces
    )
    plan = consolidation.plan(c, current, explicit=explicit)
    if force == "create":
        plan = consolidation.Plan("create")
    elif force == "supersede":
        plan = consolidation.Plan("supersede", tuple(m.id for m in current))
    if plan.action == "duplicate":
        target = plan.target_ids[0]
        repo.add_evidence(
            conn, target, source_type=source.type, source_ref=source.ref, quote=c.quote, now=now
        )
        repo.touch(conn, target, now, confidence=decision.confidence)
        report.updated.append(target)
        _settle_ambiguity(conn, subject_id, c, now)
        return
    if plan.action == "conflict":
        iid = repo.insert_inbox(
            conn,
            type="conflict",
            summary=c.statement,
            payload={
                "candidate": candidate_to_json(c),
                "subject_id": subject_id,
                "existing": list(plan.target_ids),
            },
            now=now,
            conversation_id=source.conversation_id,
            source_message_id=source.ref,
        )
        for mid in plan.target_ids:
            repo.set_conflict(conn, mid, "pending", now)
        report.inbox.append(iid)
        return
    supersedes: str | None = None
    if plan.action == "supersede":
        for mid in plan.target_ids:
            old = repo.get_memory(conn, mid)
            if old is None:
                continue
            before = uow.snapshot("memories", mid)
            repo.set_status(conn, old, "superseded", now, valid_to=now)
            repo.set_conflict(conn, mid, "none", now)
            uow.record("memories", mid, "update", before)
            report.superseded.append(mid)
            supersedes = supersedes or mid
    pred = registry.get(c.predicate)
    assert pred is not None
    m = repo.insert_memory(
        conn,
        kind=pred.kind,
        subject_id=subject_id,
        predicate=c.predicate,
        value=c.value.strip(),
        content=c.statement.strip(),
        keywords=" ".join(c.keywords),
        status="active",
        origin=c.origin,
        confidence=decision.confidence,
        importance=max(0.0, min(1.0, c.importance)),
        sensitivity=decision.sensitivity,
        sensitivity_category=decision.category,
        event_time=c.event_time,
        valid_from=now,
        supersedes_id=supersedes,
        change_set_id=uow.change_set_id,
        now=now,
    )
    repo.add_evidence(
        conn, m.id, source_type=source.type, source_ref=source.ref, quote=c.quote, now=now
    )
    uow.record("memories", m.id, "create", None)
    report.created.append(m.id)
    _settle_ambiguity(conn, subject_id, c, now)


def _settle_ambiguity(conn: Connection, subject_id: str | None, c: Candidate, now: str) -> None:
    """A "which Ahmet?" question is answered once the same fact is saved for one of the
    options (the user named the relation later, or chose in the UI)."""
    if subject_id is None:
        return
    key = text.fold(c.value).strip()
    for item in repo.list_inbox(conn, status="open", types=("ambiguous_entity",)):
        cand = item.payload.get("candidate", {})
        options = {str(o.get("id")) for o in item.payload.get("options", [])}
        if (
            subject_id in options
            and cand.get("predicate") == c.predicate
            and (
                text.fold(str(cand.get("value", ""))).strip() == key
                or text.similarity(str(cand.get("value", "")), c.value) >= 0.6
            )
        ):
            repo.resolve_inbox(conn, item.id, status="resolved", resolution=subject_id, now=now)


# ----- inbox decisions -----------------------------------------------------------------------
def resolve_inbox(conn: Connection, item_id: str, choice: str) -> ApplyReport:
    """Apply the user's decision on an inbox item. ``choice`` depends on the type:
    ambiguous_entity: an option id or 'new' · conflict: 'new' | 'old' | 'both' ·
    sensitive: 'approve' | 'reject' · any: 'dismiss'."""
    item = repo.get_inbox(conn, item_id)
    if item is None or item.status != "open":
        raise NotFound("inbox item not found")
    if item.payload.get("target") == "relationship":
        from lazis.memory import relationships

        rel_report = relationships.resolve_item(conn, item_id, choice)
        return ApplyReport(
            created=rel_report.created, updated=rel_report.updated,
            superseded=rel_report.superseded + rel_report.ended, inbox=rel_report.inbox,
            entities_created=rel_report.entities_created, dropped=rel_report.dropped,
        )  # fmt: skip
    now = utc_now_iso()
    report = ApplyReport()
    src = Source("confirmation", item.source_message_id, item.conversation_id)
    if choice == "dismiss":
        with UnitOfWork(conn, kind="review_action", actor="user", summary="1 karar") as _:
            repo.resolve_inbox(conn, item.id, status="dismissed", resolution="dismiss", now=now)
            if item.type == "conflict":
                for mid in item.payload.get("existing", []):
                    repo.set_conflict(conn, mid, "none", now)
        return report
    if item.type == "destructive" and item.payload.get("action") == "merge":
        if choice not in ("approve", "reject"):
            raise ValueError("invalid choice")
        if choice == "approve":
            merge_entities(conn, str(item.payload["keep"]), str(item.payload["merge"]))
        repo.resolve_inbox(conn, item.id, status="resolved" if choice == "approve" else
                           "dismissed", resolution=choice, now=now)  # fmt: skip
        return report
    if item.type == "destructive":
        raise ValueError("destructive confirmations are resolved through forget")
    c = candidate_from_json(item.payload["candidate"])
    with UnitOfWork(
        conn, kind="review_action", actor="user", summary="1 karar", source_ref=item.id
    ) as uow:
        if item.type == "ambiguous_entity":
            valid = {o["id"] for o in item.payload.get("options", [])}
            if choice == "new":
                assert c.entity is not None
                ent = repo.insert_entity(
                    conn,
                    kind=c.entity.kind,
                    name=c.entity.name,
                    relation=c.entity.relation,
                    description=None,
                    now=now,
                )
                uow.record("memory_entities", ent.id, "create", None)
                report.entities_created.append(ent.id)
                subject = ent.id
            elif choice in valid:
                subject = choice
            else:
                raise ValueError("invalid choice")
            apply_one(
                conn,
                uow,
                c,
                source=src,
                explicit=True,
                report=report,
                now=now,
                forced_subject=(subject,),
            )
        elif item.type == "conflict":
            subject = item.payload.get("subject_id")
            if choice == "new":
                apply_one(
                    conn,
                    uow,
                    c,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_subject=(subject,),
                    force="supersede",
                )
            elif choice == "both":
                apply_one(
                    conn,
                    uow,
                    c,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_subject=(subject,),
                    force="create",
                )
            elif choice == "old":
                repo.add_suppression(
                    conn,
                    fp=_fingerprints(conn, subject, c)[0],
                    subject_id=subject,
                    predicate=None,
                    reason="rejected",
                    now=now,
                )
            else:
                raise ValueError("invalid choice")
            for mid in item.payload.get("existing", []):
                repo.set_conflict(conn, mid, "none", now)
        elif item.type == "sensitive":
            subject = item.payload.get("subject_id")
            if choice == "approve":
                c2 = replace(c, origin="confirmed")
                apply_one(
                    conn,
                    uow,
                    c2,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_subject=(subject,),
                )
            elif choice == "reject":
                repo.add_suppression(
                    conn,
                    fp=_fingerprints(conn, subject, c)[0],
                    subject_id=subject,
                    predicate=None,
                    reason="rejected",
                    now=now,
                )
            else:
                raise ValueError("invalid choice")
        repo.resolve_inbox(conn, item.id, status="resolved", resolution=choice, now=now)
    return report


# ----- forgetting ----------------------------------------------------------------------------
@dataclass(frozen=True)
class ForgetResult:
    memories: int
    entities: int


def _skip_older_jobs(conn: Connection, now: str) -> None:
    """Queued extraction for messages written before a forget must not re-learn it."""
    conn.execute(
        "UPDATE memory_jobs SET status = 'skipped', last_error = 'forgotten_before_processing',"
        " updated_at = ?"
        " WHERE status IN ('queued', 'deferred') AND created_at <= ?",
        (now, now),
    )


def _forget(
    conn: Connection,
    memories: list[Memory],
    *,
    topic: tuple[str | None, str] | None,
    entities: list[str],
    actor: Actor,
    summary: str,
) -> ForgetResult:
    now = utc_now_iso()
    with UnitOfWork(conn, kind="deletion", actor=actor, summary=summary) as uow:
        for m in memories:
            repo.add_suppression(
                conn,
                fp=repo.fingerprint(conn, m.subject_id, m.predicate, m.value_key),
                subject_id=m.subject_id,
                predicate=None,
                reason="forgotten",
                now=now,
            )
            repo.delete_memory(conn, m)
        if topic is not None:
            sid, pred = topic
            repo.add_suppression(
                conn,
                fp=repo.fingerprint(conn, sid, pred, "*"),
                subject_id=sid,
                predicate=pred,
                reason="forgotten",
                now=now,
            )
        from lazis.memory import relationships

        for eid in entities:
            relationships.delete_for_entity(conn, uow, eid)
            repo.delete_entity(conn, eid)
            repo.purge_history(conn, "memory_entities", eid)
            conn.execute("DELETE FROM memory_inbox WHERE payload_json LIKE ?", (f'%"{eid}"%',))
        _skip_older_jobs(conn, now)
        write_audit(
            conn,
            category="memory",
            action="forget",
            outcome="success",
            actor=actor,
            change_set_id=uow.change_set_id,
            details={"memories": len(memories), "entities": len(entities)},
        )
    repo.optimize_index(conn)
    return ForgetResult(len(memories), len(entities))


def forget_memories(
    conn: Connection, memory_ids: list[str], *, actor: Actor = "user"
) -> ForgetResult:
    found = [m for m in (repo.get_memory(conn, i) for i in memory_ids) if m is not None]
    return _forget(
        conn, found, topic=None, entities=[], actor=actor, summary=f"{len(found)} hafıza silindi"
    )


def forget_topic(
    conn: Connection, subject_id: str | None, predicate: str, *, actor: Actor = "user"
) -> ForgetResult:
    """Everything (current and past values) for one subject and predicate, e.g.
    "Ahmet'in mesleğini unut"."""
    found = repo.memories_for_subject(
        conn, subject_id, predicate=predicate, statuses=("active", "superseded", "retracted")
    )
    return _forget(
        conn,
        found,
        topic=(subject_id, predicate),
        entities=[],
        actor=actor,
        summary=f"{len(found)} hafıza silindi",
    )


def forget_entity(conn: Connection, entity_id: str, *, actor: Actor = "user") -> ForgetResult:
    ent = repo.get_entity(conn, entity_id)
    if ent is None or ent.is_user:
        raise NotFound("entity not found")
    found = repo.memories_for_subject(
        conn, entity_id, statuses=("active", "superseded", "retracted")
    )
    res = _forget(
        conn, found, topic=None, entities=[entity_id], actor=actor, summary="1 kişi/proje silindi"
    )
    return ForgetResult(res.memories, res.entities)


# ----- edits ---------------------------------------------------------------------------------
def edit_memory(conn: Connection, memory_id: str, *, value: str, content: str) -> Memory:
    m = repo.get_memory(conn, memory_id)
    if m is None:
        raise NotFound("memory not found")
    if policy.secret_kind(f"{value} {content}") or policy.instruction_like(f"{value} {content}"):
        raise ValueError("content not allowed in memory")
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 hafıza düzenlendi") as uow:
        before = uow.snapshot("memories", m.id)
        repo.update_memory_text(
            conn,
            m,
            value=value,
            content=content,
            keywords=None,
            now=now,
            origin="user_edit",
            confidence=1.0,
        )
        repo.add_evidence(conn, m.id, source_type="user_edit", source_ref=None, quote=None, now=now)
        repo.set_conflict(conn, m.id, "none", now)
        uow.record("memories", m.id, "update", before)
    updated = repo.get_memory(conn, m.id)
    assert updated is not None
    return updated


def merge_entities(conn: Connection, keep_id: str, merge_id: str) -> Entity:
    """The user says two records are one person/project: move everything to ``keep_id``."""
    from lazis.memory import graphstore, relationships

    keep, other = repo.get_entity(conn, keep_id), repo.get_entity(conn, merge_id)
    if keep is None or other is None or keep.id == other.id or keep.is_user or other.is_user:
        raise NotFound("entity not found")
    if graphstore.are_distinct(conn, keep.id, other.id):
        raise ValueError("these were marked as different people")
    now = utc_now_iso()
    with UnitOfWork(conn, kind="merge", actor="user", summary="2 kayıt birleştirildi") as uow:
        moved = relationships.move_on_merge(conn, uow, keep.id, other.id, now)
        for alias in (other.name, *other.aliases):
            repo.add_alias(conn, keep.id, alias)
        if not keep.relation and other.relation:
            repo.update_entity(conn, keep.id, now=now, relation=other.relation)
        for m in repo.memories_for_subject(
            conn, other.id, statuses=("active", "superseded", "retracted")
        ):
            before = uow.snapshot("memories", m.id)
            dupes = [
                x
                for x in repo.memories_for_subject(
                    conn, keep.id, predicate=m.predicate, statuses=(m.status,)
                )
                if x.value_key == m.value_key
            ]
            if dupes:
                repo.move_evidence(conn, m.id, dupes[0].id)
                repo.delete_memory(conn, m)
                uow.record("memories", m.id, "delete", before)
            else:
                repo.move_subject(conn, m.id, keep.id, now)
                uow.record("memories", m.id, "update", before)
        before_e = uow.snapshot("memory_entities", other.id)
        repo.mark_merged(conn, other.id, keep.id, now)
        uow.record("memory_entities", other.id, "update", before_e)
        repo.reindex_subject(conn, keep.id)
        write_audit(
            conn,
            category="memory",
            action="merge",
            outcome="success",
            actor="user",
            change_set_id=uow.change_set_id,
            target_refs=[keep.id, other.id],
            details={k: v for k, v in moved.items()},
        )
    merged = repo.get_entity(conn, keep.id)
    assert merged is not None
    return merged


def split_entity(
    conn: Connection,
    entity_id: str,
    memory_ids: list[str],
    *,
    name: str,
    relation: str | None,
    relationship_ids: list[str] | None = None,
) -> Entity:
    """The user says some facts belong to a different person: move them (and the relationships
    the user assigned) to a new record; the two are then marked as different people."""
    from lazis.memory import relationships

    ent = repo.get_entity(conn, entity_id)
    if ent is None or ent.is_user:
        raise NotFound("entity not found")
    now = utc_now_iso()
    with UnitOfWork(
        conn, kind="split", actor="user", summary=f"{len(memory_ids)} hafıza ayrıldı"
    ) as uow:
        new = repo.insert_entity(
            conn, kind=ent.kind, name=name, relation=relation, description=None, now=now
        )
        uow.record("memory_entities", new.id, "create", None)
        for mid in memory_ids:
            m = repo.get_memory(conn, mid)
            if m is None or m.subject_id != entity_id:
                raise ValueError("memory does not belong to the entity")
            before = uow.snapshot("memories", mid)
            repo.move_subject(conn, mid, new.id, now)
            uow.record("memories", mid, "update", before)
        relationships.move_on_split(conn, uow, entity_id, new.id, relationship_ids or [], now)
        write_audit(
            conn,
            category="memory",
            action="split",
            outcome="success",
            actor="user",
            change_set_id=uow.change_set_id,
            target_refs=[entity_id, new.id],
        )
    return new


def update_entity(
    conn: Connection,
    entity_id: str,
    *,
    name: str | None,
    relation: str | None,
    description: str | None,
) -> Entity:
    ent = repo.get_entity(conn, entity_id)
    if ent is None:
        raise NotFound("entity not found")
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 kişi/proje düzenlendi") as uow:
        before = uow.snapshot("memory_entities", entity_id)
        repo.update_entity(
            conn, entity_id, now=now, name=name, relation=relation, description=description
        )
        uow.record("memory_entities", entity_id, "update", before)
    updated = repo.get_entity(conn, entity_id)
    assert updated is not None
    return updated


def inbox_open(conn: Connection) -> list[InboxItem]:
    return repo.list_inbox(conn, status="open")


def add_memory(
    conn: Connection,
    *,
    predicate: str,
    value: str,
    statement: str,
    entity_id: str | None = None,
    new_entity: EntityRef | None = None,
) -> ApplyReport:
    """A record the user adds in the memory screen (about themselves, an existing entity, or
    a new person/project). Same checks as everything else: secrets and instruction-like text
    are refused, a single-valued fact replaces the current one (kept as history)."""
    pred = registry.get(predicate)
    if pred is None or not value.strip():
        raise ValueError("unknown predicate or empty value")
    label = "Kullanıcı"
    if entity_id is not None:
        ent = repo.get_entity(conn, entity_id)
        if ent is None:
            raise NotFound("entity not found")
        label = entity_label(ent)
    elif new_entity is not None:
        label = (
            f"{new_entity.name} ({new_entity.relation})" if new_entity.relation else new_entity.name
        )
    c = Candidate(
        predicate=predicate,
        value=value.strip(),
        statement=statement.strip() or f"{label} — {pred.label}: {value.strip()}",
        about="entity" if (entity_id or new_entity) else "user",
        entity=new_entity,
        origin="user_edit",
    )
    decision = policy.decide(c, explicit=True)
    if decision.outcome == "drop":
        raise ValueError(f"not allowed in memory: {decision.reason}")
    report = ApplyReport()
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 hafıza eklendi") as uow:
        subject = entity_id
        if new_entity is not None and entity_id is None:
            ent = repo.insert_entity(
                conn,
                kind=new_entity.kind,
                name=new_entity.name,
                relation=new_entity.relation,
                description=None,
                now=now,
            )
            uow.record("memory_entities", ent.id, "create", None)
            report.entities_created.append(ent.id)
            subject = ent.id
        apply_one(conn, uow, c, source=Source("user_edit"), explicit=True, report=report, now=now,
                  forced_subject=(subject,))  # fmt: skip
    return report


def record_detail(conn: Connection, memory_id: str) -> tuple[Memory, list[Any], list[Memory]]:
    """A record, its evidence, and the values it replaced (newest first)."""
    m = repo.get_memory(conn, memory_id)
    if m is None:
        raise NotFound("memory not found")
    previous: list[Memory] = []
    cursor = m.supersedes_id
    while cursor is not None and len(previous) < 20:
        old = repo.get_memory(conn, cursor)
        if old is None:
            break
        previous.append(old)
        cursor = old.supersedes_id
    return m, repo.evidence_for(conn, m.id), previous
