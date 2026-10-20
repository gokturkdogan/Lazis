"""Writing relationships (MEMORY_ARCHITECTURE P7.3–P7.6): both ends resolved, policy, then
duplicate / change / correction / conflict handling, one change set per batch.

Rules, in the order they apply:

1. **Both ends are resolved with the Phase 6 identity rules.** Name plus the user's own relation
   words; a pending "which Ahmet?" question blocks guessing. If either end is ambiguous,
   nothing is written: one inbox question carries the whole relationship until the user
   answers.
2. Type and endpoint kinds must fit the vocabulary; secrets and instruction-like text never
   enter; a sensitive type waits for approval unless the user asked explicitly.
3. A forgotten or rejected relationship (or pair) is not learned again unless asked
   explicitly.
4. Against what is stored between the two:
   - same relationship (also read from the other end) → evidence only;
   - "kardeş değil" (negated) → the stored one is retracted, and the claim is suppressed;
   - a correction ("yanlış söyledim", "aslında") → the conflicting ones are superseded;
   - a real-world change ("artık") → the previous one has ended (kept as history);
   - a kinship type that excludes the stored one, or a second value of a single type, with no
     signal → a conflict question;
   - otherwise coexisting (friend and colleague; two employers; two projects).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Literal, cast

from lazis.ids import utc_now_iso
from lazis.memory import graphstore as gs
from lazis.memory import policy, relations, resolver, service, text
from lazis.memory import repository as repo
from lazis.memory.models import (
    CURRENT,
    USER_ID,
    Entity,
    EntityRef,
    Relationship,
    RelCandidate,
)
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import Actor, UnitOfWork

_SELF = frozenset({"kullanici", "ben", "beni", "benim", "kendim"})


@dataclass
class RelReport:
    created: list[str] = field(default_factory=list[str])
    updated: list[str] = field(default_factory=list[str])  # evidence added / status refreshed
    ended: list[str] = field(default_factory=list[str])
    superseded: list[str] = field(default_factory=list[str])
    retracted: list[str] = field(default_factory=list[str])
    inbox: list[str] = field(default_factory=list[str])
    entities_created: list[str] = field(default_factory=list[str])
    dropped: dict[str, int] = field(default_factory=dict[str, int])

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    def counts(self) -> dict[str, int]:
        return {
            "relations_created": len(self.created),
            "relations_updated": len(self.updated),
            "relations_ended": len(self.ended),
            "relations_superseded": len(self.superseded),
            "relations_retracted": len(self.retracted),
            "relations_inbox": len(self.inbox),
            "entities_created": len(self.entities_created),
            **{f"relations_dropped_{k}": v for k, v in self.dropped.items()},
        }


# ----- JSON (inbox payloads) --------------------------------------------------------------
def _ref_json(ref: EntityRef | None) -> dict[str, Any] | None:
    return None if ref is None else asdict(ref)


def _ref_from(data: Any) -> EntityRef | None:
    if not isinstance(data, dict):
        return None
    d = cast(dict[str, Any], data)
    if not d.get("name"):
        return None
    return EntityRef(str(d["name"]), d.get("kind", "person"), d.get("relation"), d.get("ref_id"))


def candidate_to_json(c: RelCandidate) -> dict[str, Any]:
    data = asdict(c)
    data["source"] = _ref_json(c.source)
    data["target"] = _ref_json(c.target)
    return data


def candidate_from_json(data: dict[str, Any]) -> RelCandidate:
    target = _ref_from(data.get("target"))
    assert target is not None
    return RelCandidate(
        type=str(data["type"]),
        target=target,
        source=_ref_from(data.get("source")),
        qualifier=data.get("qualifier"),
        quote=data.get("quote"),
        statement=str(data.get("statement", "")),
        change=bool(data.get("change")),
        correction=bool(data.get("correction")),
        negated=bool(data.get("negated")),
        status=data.get("status", "active"),
        certain=bool(data.get("certain", True)),
        time_text=data.get("time_text"),
        origin=data.get("origin", "stated"),
    )


def label(e: Entity) -> str:
    if e.is_user:
        return "Kullanıcı"
    return service.entity_label(e)


def statement_for(conn: Connection, source_id: str, type_key: str, target_id: str) -> str:
    s, t = repo.get_entity(conn, source_id), repo.get_entity(conn, target_id)
    return relations.describe(s.name if s else "?", type_key, t.name if t else "?")


# ----- endpoint resolution ----------------------------------------------------------------
@dataclass(frozen=True)
class _End:
    state: Literal["ok", "ambiguous", "drop"]
    entity_id: str | None = None
    options: tuple[str, ...] = ()
    reason: str = ""


def _resolve_end(
    conn: Connection,
    uow: UnitOfWork,
    ref: EntityRef | None,
    *,
    kinds: Sequence[str],
    report: RelReport,
    now: str,
    forced: str | None = None,
    sync_source: tuple[str | None, str | None] = (None, None),
) -> _End:
    if forced is not None:
        if forced == "new":
            assert ref is not None
            return _End("ok", _create_entity(conn, uow, ref, kinds=kinds, report=report, now=now))
        return _End("ok", forced) if repo.get_entity(conn, forced) is not None else _End("drop")
    if ref is None:
        return _End("ok", USER_ID)
    key = text.name_key(ref.name)
    if not key:
        return _End("drop", reason="no_entity")
    if key in _SELF:
        return _End("ok", USER_ID)
    named = repo.find_entities(conn, key)
    candidates = [e for e in named if e.kind in kinds or not kinds]
    if named and not candidates:
        return _End("drop", reason="kind_mismatch")  # "Ahmet" is a person, not a company
    if kinds and ref.kind not in kinds and not candidates:
        return _End("drop", reason="kind_mismatch")
    res = resolver.resolve(ref, candidates)
    if (
        res.kind == "existing" and not ref.relation and service._pending_namesake(conn, key)  # pyright: ignore[reportPrivateUsage]
    ):
        res = resolver.Resolution(
            "ambiguous", options=tuple(e.id for e in candidates), reason="pending_namesake"
        )
    if res.kind == "existing":
        assert res.entity_id is not None
        if ref.relation:
            ensure_user_relation(
                conn,
                uow,
                res.entity_id,
                ref.relation,
                report=report,
                now=now,
                source_type=sync_source[0],
                source_ref=sync_source[1],
            )
        return _End("ok", res.entity_id)
    if res.kind == "new":
        eid = _create_entity(conn, uow, ref, kinds=kinds, report=report, now=now)
        if ref.relation:
            ensure_user_relation(
                conn,
                uow,
                eid,
                ref.relation,
                report=report,
                now=now,
                source_type=sync_source[0],
                source_ref=sync_source[1],
            )
        return _End("ok", eid)
    return _End("ambiguous", options=res.options, reason=res.reason)


def _create_entity(
    conn: Connection,
    uow: UnitOfWork,
    ref: EntityRef,
    *,
    kinds: Sequence[str],
    report: RelReport,
    now: str,
) -> str:
    kind = ref.kind if (not kinds or ref.kind in kinds) else kinds[0]
    ent = repo.insert_entity(
        conn, kind=kind, name=ref.name, relation=ref.relation, description=None, now=now
    )
    uow.record("memory_entities", ent.id, "create", None)
    report.entities_created.append(ent.id)
    return ent.id


def ensure_user_relation(
    conn: Connection,
    uow: UnitOfWork,
    entity_id: str,
    relation_words: str,
    *,
    report: RelReport | None = None,
    now: str,
    source_type: str | None = None,
    source_ref: str | None = None,
    quote: str | None = None,
) -> str | None:
    """The user's own words about how they know someone ("çocukluk arkadaşım") → the typed
    user relationship, when the words map exactly to the vocabulary. Otherwise only the label
    stays (nothing is guessed)."""
    key = relations.lexicon(relation_words)
    ent = repo.get_entity(conn, entity_id)
    if ent is None or ent.is_user:
        return None
    if not ent.relation:
        before = uow.snapshot("memory_entities", ent.id)
        repo.update_entity(conn, ent.id, now=now, relation=relation_words)
        uow.record("memory_entities", ent.id, "update", before)
    if key is None:
        return None
    t = relations.TYPES[key]
    if not relations.kinds_ok(t, "person", ent.kind):
        return None
    for rel in gs.relationships_between(conn, USER_ID, entity_id, statuses=CURRENT):
        if _equivalent(rel, USER_ID, key, entity_id):
            return rel.id
    if gs.relationships_between(conn, USER_ID, entity_id, statuses=CURRENT) and t.exclusive:
        return None  # another kinship to the user is stored: not overwritten silently
    rel = gs.insert_relationship(
        conn,
        source_id=USER_ID,
        type=key,
        target_id=entity_id,
        qualifier=None,
        status="active",
        origin="stated",
        confidence=0.9,
        sensitivity=t.sensitivity,
        sensitivity_category=t.sensitivity_category,
        time_text=None,
        supersedes_id=None,
        change_set_id=uow.change_set_id,
        now=now,
    )
    gs.add_evidence(
        conn,
        rel.id,
        source_type=source_type or "message",
        source_ref=source_ref,
        quote=quote or relation_words,
        now=now,
    )
    uow.record("memory_relationships", rel.id, "create", None)
    if report is not None:
        report.created.append(rel.id)
    return rel.id


# ----- equivalence and conflicts ------------------------------------------------------------
def _equivalent(rel: Relationship, source_id: str, key: str, target_id: str) -> bool:
    """The same claim, possibly stated from the other end (mother ↔ child, sibling ↔ sibling)."""
    if rel.source_id == source_id and rel.target_id == target_id:
        return (
            rel.type == key
            or key in relations.answers(rel.type)
            or rel.type in relations.answers(key)
        )
    if rel.source_id == target_id and rel.target_id == source_id:
        back = relations.reading_from_target(rel.type)
        return back is not None and (
            back == key or key in relations.answers(back) or back in relations.answers(key)
        )
    return False


def _same_group(a: str, b: str) -> bool:
    ta, tb = relations.TYPES.get(a), relations.TYPES.get(b)
    return bool(ta and tb and ta.exclusive and ta.exclusive == tb.exclusive)


# ----- applying -----------------------------------------------------------------------------
def apply_relations(
    conn: Connection,
    candidates: Sequence[RelCandidate],
    *,
    source: service.Source,
    explicit: bool,
    actor: Actor = "pipeline",
    kind: str = "learning_run",
) -> RelReport:
    report = RelReport()
    if not candidates:
        return report
    now = utc_now_iso()
    with UnitOfWork(
        conn,
        kind=kind,
        actor=actor,
        summary=f"{len(candidates)} ilişki adayı",
        source_ref=source.ref,
    ) as uow:
        for c in candidates:
            apply_one(conn, uow, c, source=source, explicit=explicit, report=report, now=now)
        write_audit(
            conn,
            category="memory",
            action=f"{kind}_relations",
            outcome="success",
            actor=actor,
            change_set_id=uow.change_set_id,
            details={k: v for k, v in report.counts().items()},
        )
    return report


def _narrow_to_holder(conn: Connection, type_key: str, src: _End, tgt: _End) -> tuple[_End, _End]:
    """The one namesake on the ambiguous end that holds this relationship with the other end
    (unchanged when none or several do)."""
    amb, other = (src, tgt) if src.state == "ambiguous" else (tgt, src)
    if other.state != "ok" or other.entity_id is None:
        return src, tgt
    holders = [
        o
        for o in amb.options
        if any(
            _equivalent(r, *((o, type_key, other.entity_id) if amb is src else
                             (other.entity_id, type_key, o)))
            for r in gs.relationships_between(conn, o, other.entity_id, statuses=CURRENT)
        )
    ]  # fmt: skip
    if len(holders) != 1:
        return src, tgt
    chosen = _End("ok", holders[0])
    return (chosen, tgt) if amb is src else (src, chosen)


def apply_one(
    conn: Connection,
    uow: UnitOfWork,
    c: RelCandidate,
    *,
    source: service.Source,
    explicit: bool,
    report: RelReport,
    now: str,
    forced_source: str | None = None,
    forced_target: str | None = None,
    force: Literal["replace", "coexist"] | None = None,
) -> None:
    t = relations.get(c.type)
    if t is None:
        report.drop("unknown_type")
        return
    joined = " ".join(x for x in (c.statement, c.quote or "", c.qualifier or "") if x)
    if policy.secret_kind(joined):
        report.drop("secret")
        return
    if policy.instruction_like(joined):
        report.drop("instruction_like")
        return
    sync = (source.type, source.ref)
    src = _resolve_end(
        conn,
        uow,
        c.source,
        kinds=t.source_kinds,
        report=report,
        now=now,
        forced=forced_source,
        sync_source=sync,
    )
    tgt = _resolve_end(
        conn,
        uow,
        c.target,
        kinds=t.target_kinds,
        report=report,
        now=now,
        forced=forced_target,
        sync_source=sync,
    )
    if src.state == "drop" or tgt.state == "drop":
        report.drop(src.reason or tgt.reason or "no_entity")
        return
    if (c.negated or c.change) and (src.state == "ambiguous") != (tgt.state == "ambiguous"):
        # Denying or ending a relationship can only be about a namesake who has it.
        src, tgt = _narrow_to_holder(conn, c.type, src, tgt)
    if src.state == "ambiguous" or tgt.state == "ambiguous":
        _ask_which(conn, c, src, tgt, source=source, report=report, now=now)
        return
    assert src.entity_id is not None and tgt.entity_id is not None
    a, b = src.entity_id, tgt.entity_id
    if a == b:
        report.drop("self")
        return
    se, te = repo.get_entity(conn, a), repo.get_entity(conn, b)
    if se is None or te is None or not relations.kinds_ok(t, se.kind, te.kind):
        report.drop("kind_mismatch")
        return

    fps = [gs.rel_fingerprint(conn, a, c.type, b), gs.pair_fingerprint(conn, a, b)]
    back = relations.reading_from_target(c.type)
    if back is not None and back != c.type:
        fps.append(gs.rel_fingerprint(conn, b, back, a))
    if explicit:
        repo.remove_suppressions(conn, fps)
    elif repo.is_suppressed(conn, fps):
        report.drop("suppressed")
        return

    between = gs.relationships_between(conn, a, b, statuses=CURRENT)
    same = [r for r in between if _equivalent(r, a, c.type, b)]

    if c.negated:
        for r in same:
            before = uow.snapshot("memory_relationships", r.id)
            gs.set_status(conn, r.id, "retracted", now, ended=True)
            uow.record("memory_relationships", r.id, "update", before)
            report.retracted.append(r.id)
        gs.suppress(conn, fps[0], "rejected", now)
        return

    if t.sensitivity == "sensitive" and not explicit and force is None:
        iid = repo.insert_inbox(
            conn,
            type="sensitive",
            summary=c.statement or statement_for(conn, a, c.type, b),
            payload={
                "target": "relationship",
                "relation": candidate_to_json(c),
                "ends": [a, b],
                "category": t.sensitivity_category,
            },
            now=now,
            conversation_id=source.conversation_id,
            source_message_id=source.ref,
        )
        report.inbox.append(iid)
        return

    status = "unverified" if not c.certain else c.status
    if same and not c.correction:
        r = same[0]
        gs.add_evidence(
            conn, r.id, source_type=source.type, source_ref=source.ref, quote=c.quote, now=now
        )
        if status in ("ended", "active") and r.status != status:
            before = uow.snapshot("memory_relationships", r.id)
            gs.set_status(conn, r.id, status, now, ended=status == "ended")
            uow.record("memory_relationships", r.id, "update", before)
        report.updated.append(r.id)
        return

    # What the new statement replaces.
    group_rivals = [r for r in between if r not in same and _same_group(r.type, c.type)]
    single_rivals: list[Relationship] = []
    if t.single or t.category in ("organization", "place"):
        single_rivals = [
            r for r in gs.edges_from(conn, a, CURRENT) if r.type == c.type and r.target_id != b
        ]
    if c.correction or force == "replace":
        _close(conn, uow, [*same, *group_rivals, *single_rivals], "superseded", report, now)
    elif c.change:
        _close(conn, uow, [*group_rivals, *single_rivals], "ended", report, now)
    elif force == "coexist":
        pass
    elif group_rivals or (t.single and single_rivals):
        if explicit:
            _close(conn, uow, [*group_rivals, *single_rivals], "ended", report, now)
        else:
            _ask_conflict(
                conn,
                c,
                a,
                b,
                [*group_rivals, *single_rivals],
                source=source,
                report=report,
                now=now,
            )
            return

    rivals = [*same, *group_rivals, *single_rivals]
    replaced_id = rivals[0].id if (rivals and (c.correction or force == "replace")) else None
    rel = gs.insert_relationship(
        conn,
        source_id=a,
        type=c.type,
        target_id=b,
        qualifier=c.qualifier,
        status=status,
        origin=c.origin,
        confidence=_confidence(c, explicit),
        sensitivity=t.sensitivity,
        sensitivity_category=t.sensitivity_category,
        time_text=c.time_text,
        supersedes_id=replaced_id,
        change_set_id=uow.change_set_id,
        now=now,
    )
    gs.add_evidence(
        conn, rel.id, source_type=source.type, source_ref=source.ref, quote=c.quote, now=now
    )
    uow.record("memory_relationships", rel.id, "create", None)
    report.created.append(rel.id)
    if a == USER_ID and not te.relation:
        before = uow.snapshot("memory_entities", b)
        repo.update_entity(conn, b, now=now, relation=t.label)
        uow.record("memory_entities", b, "update", before)
    _settle_questions(conn, c, a, b, now)


def _confidence(c: RelCandidate, explicit: bool) -> float:
    base = {
        "requested": 0.95,
        "confirmed": 1.0,
        "user_edit": 1.0,
        "imported": 0.9,
        "migrated": 0.85,
    }.get(c.origin, 0.85)
    if explicit:
        base = max(base, 0.95)
    return min(base, 0.55) if not c.certain else base


def _close(
    conn: Connection,
    uow: UnitOfWork,
    rels: Sequence[Relationship],
    status: str,
    report: RelReport,
    now: str,
) -> None:
    seen: set[str] = set()
    for r in rels:
        if r.id in seen:
            continue
        seen.add(r.id)
        before = uow.snapshot("memory_relationships", r.id)
        gs.set_status(conn, r.id, status, now, ended=True)
        gs.set_conflict(conn, r.id, "none", now)
        uow.record("memory_relationships", r.id, "update", before)
        (report.superseded if status == "superseded" else report.ended).append(r.id)


def _names(c: RelCandidate) -> list[str]:
    return [text.name_key(r.name) for r in (c.source, c.target) if r is not None]


def _ask_which(
    conn: Connection,
    c: RelCandidate,
    src: _End,
    tgt: _End,
    *,
    source: service.Source,
    report: RelReport,
    now: str,
) -> None:
    end = "source" if src.state == "ambiguous" else "target"
    amb = src if end == "source" else tgt
    ref = c.source if end == "source" else c.target
    assert ref is not None
    opts = [repo.get_entity(conn, o) for o in amb.options]
    statement = c.statement or f"{ref.name} — {relations.TYPES[c.type].label}"
    iid = repo.insert_inbox(
        conn,
        type="ambiguous_entity",
        summary=f"Hangi {ref.name}? — {statement}",
        payload={
            "target": "relationship",
            "relation": candidate_to_json(c),
            "end": end,
            "known_source": src.entity_id,
            "known_target": tgt.entity_id,
            "options": [{"id": o.id, "label": label(o)} for o in opts if o is not None],
            "pending_names": _names(c),
            "reason": amb.reason,
            # Phase 6 readers (open questions in recall and extraction) read "candidate".
            "candidate": {"statement": statement, "entity": {"name": ref.name}},
        },
        now=now,
        conversation_id=source.conversation_id,
        source_message_id=source.ref,
    )
    report.inbox.append(iid)


def _ask_conflict(
    conn: Connection,
    c: RelCandidate,
    a: str,
    b: str,
    rivals: Sequence[Relationship],
    *,
    source: service.Source,
    report: RelReport,
    now: str,
) -> None:
    for r in rivals:
        gs.set_conflict(conn, r.id, "pending", now)
    new = c.statement or statement_for(conn, a, c.type, b)
    iid = repo.insert_inbox(
        conn,
        type="conflict",
        summary=new,
        payload={
            "target": "relationship",
            "relation": candidate_to_json(c),
            "ends": [a, b],
            "existing_relations": [r.id for r in rivals],
            "existing_labels": [
                statement_for(conn, r.source_id, r.type, r.target_id) for r in rivals
            ],
        },
        now=now,
        conversation_id=source.conversation_id,
        source_message_id=source.ref,
    )
    report.inbox.append(iid)


def _settle_questions(conn: Connection, c: RelCandidate, a: str, b: str, now: str) -> None:
    """A "which Ahmet?" question about this relationship closes once it is written for one of
    the options."""
    for item in repo.list_inbox(conn, status="open", types=("ambiguous_entity",)):
        if item.payload.get("target") != "relationship":
            continue
        rel = item.payload.get("relation", {})
        options = {str(o.get("id")) for o in item.payload.get("options", [])}
        if rel.get("type") == c.type and (a in options or b in options):
            repo.resolve_inbox(conn, item.id, status="resolved", resolution="auto", now=now)


# ----- inbox decisions ------------------------------------------------------------------------
def resolve_item(conn: Connection, item_id: str, choice: str) -> RelReport:
    item = repo.get_inbox(conn, item_id)
    if item is None or item.status != "open":
        raise service.NotFound("inbox item not found")
    c = candidate_from_json(item.payload["relation"])
    report = RelReport()
    now = utc_now_iso()
    src = service.Source("confirmation", item.source_message_id, item.conversation_id)
    with UnitOfWork(
        conn, kind="review_action", actor="user", summary="1 ilişki kararı", source_ref=item.id
    ) as uow:
        if choice == "dismiss":
            for rid in item.payload.get("existing_relations", []):
                gs.set_conflict(conn, rid, "none", now)
        elif item.type == "ambiguous_entity":
            valid = {o["id"] for o in item.payload.get("options", [])}
            if choice != "new" and choice not in valid:
                raise ValueError("invalid choice")
            end = item.payload.get("end")
            fs = choice if end == "source" else item.payload.get("known_source")
            ft = choice if end == "target" else item.payload.get("known_target")
            if choice == "new" and end == "source" and c.source is not None:
                # "Başka biri": a new person, distinct from every option.
                apply_one(
                    conn,
                    uow,
                    c,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_source="new",
                    forced_target=ft,
                )
            else:
                apply_one(
                    conn,
                    uow,
                    c,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_source=fs,
                    forced_target=ft,
                )
            new_ids = report.entities_created
            for o in valid:
                for n in new_ids:
                    gs.add_distinction(conn, o, n, now)
        elif item.type == "conflict":
            rivals = list(item.payload.get("existing_relations", []))
            if choice == "new":
                a, b = item.payload["ends"]
                apply_one(
                    conn,
                    uow,
                    replace(c, correction=True),
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_source=a,
                    forced_target=b,
                )
            elif choice == "both":
                a, b = item.payload["ends"]
                apply_one(
                    conn,
                    uow,
                    c,
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_source=a,
                    forced_target=b,
                    force="coexist",
                )
            elif choice == "old":
                a, b = item.payload["ends"]
                gs.suppress(conn, gs.rel_fingerprint(conn, a, c.type, b), "rejected", now)
            else:
                raise ValueError("invalid choice")
            for rid in rivals:
                gs.set_conflict(conn, rid, "none", now)
        elif item.type == "sensitive":
            a, b = item.payload["ends"]
            if choice == "approve":
                apply_one(
                    conn,
                    uow,
                    replace(c, origin="confirmed"),
                    source=src,
                    explicit=True,
                    report=report,
                    now=now,
                    forced_source=a,
                    forced_target=b,
                )
            elif choice == "reject":
                gs.suppress(conn, gs.rel_fingerprint(conn, a, c.type, b), "rejected", now)
            else:
                raise ValueError("invalid choice")
        else:
            raise ValueError("not a relationship decision")
        repo.resolve_inbox(
            conn,
            item.id,
            status="dismissed" if choice == "dismiss" else "resolved",
            resolution=choice,
            now=now,
        )
    return report


# ----- user edits -----------------------------------------------------------------------------
def add_relationship(
    conn: Connection,
    *,
    source_id: str,
    type: str,
    target_id: str,
    qualifier: str | None = None,
    status: Literal["active", "ended", "planned"] = "active",
    time_text: str | None = None,
) -> RelReport:
    """A relationship the user adds in the memory screen between two known entities."""
    s, t = repo.get_entity(conn, source_id), repo.get_entity(conn, target_id)
    if s is None or t is None:
        raise service.NotFound("entity not found")
    c = RelCandidate(
        type=type,
        target=EntityRef(t.name, t.kind),
        qualifier=qualifier,
        status=status,
        time_text=time_text,
        origin="user_edit",
        statement=statement_for(conn, source_id, type, target_id),
    )
    if relations.get(type) is None:
        raise ValueError("unknown relationship type")
    report = RelReport()
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 ilişki eklendi") as uow:
        apply_one(
            conn,
            uow,
            c,
            source=service.Source("user_edit"),
            explicit=True,
            report=report,
            now=now,
            forced_source=source_id,
            forced_target=target_id,
        )
    if report.dropped:
        raise ValueError(f"relationship not allowed: {','.join(report.dropped)}")
    return report


def edit_relationship(
    conn: Connection,
    rel_id: str,
    *,
    type: str,
    qualifier: str | None,
    status: Literal["active", "ended", "planned"],
    time_text: str | None,
) -> Relationship:
    rel = gs.get_relationship(conn, rel_id)
    if rel is None:
        raise service.NotFound("relationship not found")
    t = relations.get(type)
    s, tg = repo.get_entity(conn, rel.source_id), repo.get_entity(conn, rel.target_id)
    if t is None or s is None or tg is None or not relations.kinds_ok(t, s.kind, tg.kind):
        raise ValueError("relationship type does not fit")
    joined = f"{qualifier or ''} {time_text or ''}"
    if policy.secret_kind(joined) or policy.instruction_like(joined):
        raise ValueError("content not allowed")
    now = utc_now_iso()
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="1 ilişki düzenlendi") as uow:
        before = uow.snapshot("memory_relationships", rel.id)
        gs.update_relationship(
            conn,
            rel.id,
            type=type,
            qualifier=qualifier,
            status=status,
            time_text=time_text,
            origin="user_edit",
            now=now,
        )
        gs.add_evidence(conn, rel.id, source_type="user_edit", source_ref=None, quote=None, now=now)
        uow.record("memory_relationships", rel.id, "update", before)
    updated = gs.get_relationship(conn, rel.id)
    assert updated is not None
    return updated


# ----- forgetting -----------------------------------------------------------------------------
@dataclass(frozen=True)
class RelForget:
    relationships: int


def forget_relationships(
    conn: Connection,
    rel_ids: Sequence[str],
    *,
    actor: Actor = "user",
    pair: tuple[str, str] | None = None,
) -> RelForget:
    """Rows, evidence, history content, related open questions; a keyed suppression so the
    relationship (or, for a pair, any relationship between the two) is not learned again."""
    now = utc_now_iso()
    rels = [r for r in (gs.get_relationship(conn, i) for i in rel_ids) if r is not None]
    with UnitOfWork(
        conn, kind="deletion", actor=actor, summary=f"{len(rels)} ilişki silindi"
    ) as uow:
        for r in rels:
            gs.suppress(
                conn, gs.rel_fingerprint(conn, r.source_id, r.type, r.target_id), "forgotten", now
            )
            gs.delete_relationship(conn, r.id)
        if pair is not None:
            gs.suppress(conn, gs.pair_fingerprint(conn, *pair), "forgotten", now)
            for item in repo.list_inbox(conn, status="open"):
                ends = set(item.payload.get("ends", [])) | {
                    item.payload.get("known_source"),
                    item.payload.get("known_target"),
                }
                if item.payload.get("target") == "relationship" and set(pair) <= ends:
                    repo.delete_inbox(conn, item.id)
        service._skip_older_jobs(conn, now)  # pyright: ignore[reportPrivateUsage]
        write_audit(
            conn,
            category="memory",
            action="forget_relations",
            outcome="success",
            actor=actor,
            change_set_id=uow.change_set_id,
            details={"relationships": len(rels)},
        )
    return RelForget(len(rels))


def forget_pair(conn: Connection, a: str, b: str, *, actor: Actor = "user") -> RelForget:
    rels = gs.relationships_between(conn, a, b)
    return forget_relationships(conn, [r.id for r in rels], actor=actor, pair=(a, b))


# ----- merge / split support (called inside service's change set) -----------------------------
def move_on_merge(
    conn: Connection, uow: UnitOfWork, keep: str, other: str, now: str
) -> dict[str, int]:
    """Every relationship of ``other`` now belongs to ``keep``; relationships between the two
    become self-loops and are removed (reported); duplicates are folded (evidence kept)."""
    loops = moved = folded = 0
    for r in gs.relationships_of(conn, other):
        before = uow.snapshot("memory_relationships", r.id)
        if {r.source_id, r.target_id} == {keep, other}:
            gs.delete_relationship(conn, r.id)
            uow.record("memory_relationships", r.id, "delete", before)
            loops += 1
            continue
        s = keep if r.source_id == other else r.source_id
        t = keep if r.target_id == other else r.target_id
        gs.repoint(conn, r.id, source_id=s, target_id=t, now=now)
        uow.record("memory_relationships", r.id, "update", before)
        moved += 1
    seen: list[Relationship] = []
    for r in gs.relationships_of(conn, keep):
        twin = next(
            (
                x
                for x in seen
                if x.status == r.status and _equivalent(x, r.source_id, r.type, r.target_id)
            ),
            None,
        )
        if twin is None:
            seen.append(r)
            continue
        before = uow.snapshot("memory_relationships", r.id)
        gs.move_evidence(conn, r.id, twin.id)
        gs.delete_relationship(conn, r.id)
        uow.record("memory_relationships", r.id, "delete", before)
        folded += 1
    return {"relations_moved": moved, "relations_folded": folded, "self_loops_removed": loops}


def move_on_split(
    conn: Connection, uow: UnitOfWork, entity_id: str, new_id: str, rel_ids: Sequence[str], now: str
) -> int:
    """The relationships the user assigned to the new entity move; nothing else does."""
    n = 0
    for rid in rel_ids:
        r = gs.get_relationship(conn, rid)
        if r is None or entity_id not in (r.source_id, r.target_id):
            raise ValueError("relationship does not belong to the entity")
        before = uow.snapshot("memory_relationships", r.id)
        gs.repoint(
            conn,
            r.id,
            source_id=new_id if r.source_id == entity_id else r.source_id,
            target_id=new_id if r.target_id == entity_id else r.target_id,
            now=now,
        )
        uow.record("memory_relationships", r.id, "update", before)
        n += 1
    gs.add_distinction(conn, entity_id, new_id, now)
    return n


def delete_for_entity(conn: Connection, uow: UnitOfWork, entity_id: str) -> int:
    """Forgetting a person: their relationships go (history content too); the other people's
    own facts stay."""
    n = 0
    for r in gs.relationships_of(conn, entity_id):
        gs.delete_relationship(conn, r.id)
        n += 1
    return n


# ----- the one-time, deterministic upgrade of Phase 6 relation labels -------------------------
BACKFILL_KEY = "graph_backfill_v1"


def backfill_user_relations(conn: Connection) -> dict[str, int] | None:
    """Phase 6 stored the user's relation to a person as a label ("çocukluk arkadaşı"). Labels
    that map exactly to the vocabulary become typed user relationships, once, in one change
    set (origin ``migrated``); every other label stays a label. Old chats are not scanned.
    Returns the counts, or None when it already ran."""
    if conn.execute("SELECT 1 FROM app_meta WHERE key = ?", (BACKFILL_KEY,)).fetchone():
        return None
    now = utc_now_iso()
    rows = conn.execute(
        "SELECT id, relation FROM memory_entities WHERE status = 'active' AND is_user = 0"
        " AND relation IS NOT NULL AND relation != ''"
    ).fetchall()
    counts = {"labels": len(rows), "converted": 0, "kept_as_label": 0}
    with UnitOfWork(conn, kind="migration", actor="system", summary="ilişki etiketleri") as uow:
        for eid, rel_text in rows:
            rid = ensure_user_relation(
                conn,
                uow,
                str(eid),
                str(rel_text),
                now=now,
                source_type="migration",
                quote=str(rel_text),
            )
            if rid is not None:
                conn.execute(
                    "UPDATE memory_relationships SET origin = 'migrated' WHERE id = ?"
                    " AND change_set_id = ?",
                    (rid, uow.change_set_id),
                )
                counts["converted"] += 1
            else:
                counts["kept_as_label"] += 1
        import json

        conn.execute(
            "INSERT INTO app_meta (key, value) VALUES (?, ?)",
            (BACKFILL_KEY, json.dumps({**counts, "at": now})),
        )
    return counts
