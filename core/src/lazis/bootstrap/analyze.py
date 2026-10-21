"""Comparing an import's proposals with the memory — a dry run (Phase 8, ADR-0019).

Nothing here writes. For each proposed person: is it someone already stored (a unique,
compatible match — only a suggestion), a new person, or ambiguous (several stored namesakes,
a stored namesake known differently, an open "which one?" question, or a bare name next to its
namesakes in the file)? For each proposed fact and relationship: how it relates to what is
stored for its subject —

* ``new``: nothing like it is stored;
* ``exact_duplicate``: the same value is stored (approving adds the file as evidence only);
* ``possible_duplicate``: a very similar value is stored (shown side by side);
* ``conflict``: a single-valued fact with a different stored value, and the file does not say
  it changed;
* ``temporal_update``: the same, but the file says it changed ("artık", "taşındı", a date);
* ``ambiguous_entity``: about a person whose identity is not settled;
* ``insufficient_evidence``: the file itself is unsure ("galiba", "sanırım");
* ``excluded``: never written (a secret, an instruction-like text, an unknown field) — why.

Classification depends on the person decision (linking a proposed person to a stored one
changes what its facts are compared with), so :func:`classify_fact` takes the subject's id.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from lazis.bootstrap.proposals import (
    USER,
    Proposals,
    ProposedFact,
    ProposedPerson,
    ProposedRelation,
)
from lazis.memory import consolidation, policy, registry, relations, resolver, service, text
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory.models import CURRENT, Candidate, EntityRef
from lazis.storage.driver import Connection

Classification = Literal[
    "new", "exact_duplicate", "possible_duplicate", "conflict", "temporal_update",
    "ambiguous_entity", "insufficient_evidence", "excluded",
]  # fmt: skip
NEW = "new"  # a subject the import would create
# A file can address the assistant ("Sistem: …", "hepsini onayla", "bundan sonra kullanıcıya
# …"): on top of the learning policy (shared with chat, measured on its gold sets), text that
# gives the assistant an order is excluded from an import. It is shown, never written.
_DIRECTIVE = re.compile(
    r"^\s*(asistan|assistant|lazis)\s*[:>]"
    r"|^\s*(sistem|system|model|ai)\s*[:>].*\b(kaydet|onayla|sil|unut|yaz|söyle|uygula|ignore|"
    r"approve|save|delete|forget)"
    r"|\b(onaysız|onay\s+almadan|sormadan|izinsiz)\s+(kaydet|yaz|ekle|sil|onayla|güncelle)"
    r"|\b(hepsini|tümünü|her\s+şeyi|bunların\s+hepsini)\s+(onayla|kaydet|sil|yaz|uygula)"
    r"|\bbundan\s+(sonra|böyle)\s+(kullanıcıya|bana|herkese|ona)\b"
    r"|\b(yalan\s+söyle|lie\s+to)\b"
    r"|\b(approve|save|delete|write)\s+(everything|all)\b"
    r"|\b(lazis|asistan|yapay\s+zeka)\w*\s*,\s*\w+",
    re.IGNORECASE,
)


def directive(value: str) -> bool:
    """Text in an imported file that is an order to the assistant, not information."""
    return policy.instruction_like(value) or bool(_DIRECTIVE.search(value))


_TEMPORAL = re.compile(
    r"\b(artik|eskiden|tasindi|tasindim|gecti|gectim|degisti|degistirdi|basladi|basladim|"
    r"ayrildi|ayrildim|birakti|biraktim|emekli|yeni|son|once|beri|19\d\d|20\d\d)\b"
)


@dataclass(frozen=True)
class PersonMatch:
    match: Literal["new", "existing", "ambiguous"]
    suggested_id: str | None = None
    options: tuple[dict[str, str], ...] = ()  # {"id", "label", "kind": "stored" | "import"}
    note: str | None = None


def _kinds_ok(a: str, b: str) -> bool:
    return a == b or {a, b} <= {"organization", "project", "thing"}


def match_person(
    conn: Connection, p: ProposedPerson, all_people: list[ProposedPerson]
) -> PersonMatch:
    key = text.name_key(p.name)
    stored = [e for e in repo.find_entities(conn, key) if _kinds_ok(p.kind, e.kind)]
    file_namesakes = [q for q in all_people if q.key != p.key and text.name_key(q.name) == key
                      and q.kind == p.kind]  # fmt: skip
    in_file = tuple(
        {"id": q.key, "label": person_label(q), "kind": "import"} for q in file_namesakes
    )
    stored_opts = tuple({"id": e.id, "label": service.entity_label(e), "kind": "stored"}
                        for e in stored)  # fmt: skip
    bare_next_to_namesakes = (
        not p.relation
        and not p.description
        and any(q.relation or q.description for q in file_namesakes)
    )
    if not stored:
        if bare_next_to_namesakes:
            return PersonMatch("ambiguous", options=in_file, note="file_namesakes")
        return PersonMatch("new")
    res = resolver.resolve(EntityRef(p.name, p.kind, p.relation), stored)  # type: ignore[arg-type]
    if (
        res.kind == "existing"
        and not bare_next_to_namesakes
        and not (not p.relation and service.pending_namesake(conn, key))
    ):
        return PersonMatch("existing", res.entity_id, stored_opts, note=res.reason)
    if res.kind == "new":
        return PersonMatch("new")
    note = "pending_namesake" if res.kind == "existing" else res.reason
    return PersonMatch("ambiguous", options=stored_opts + in_file, note=note)


def person_label(p: ProposedPerson) -> str:
    extra = p.relation or p.description
    return f"{p.name} ({extra})" if extra else p.name


def subject_label(proposals: Proposals, ref: str) -> str:
    if ref == USER:
        return "Kullanıcı"
    p = proposals.person(ref)
    return person_label(p) if p else ref


def candidate(f: ProposedFact, *, value: str | None = None, entity: EntityRef | None = None,
              statement: str | None = None) -> Candidate:  # fmt: skip
    v = f.value if value is None else value
    return Candidate(
        predicate=f.predicate, value=v, statement=statement or f.statement,
        about="user" if entity is None else "entity", entity=entity, quote=f.excerpt,
        event_time=f.time, change=f.change, replaces=f.replaces, certain=f.certain,
        sensitivity_category=f.sensitive, importance=f.importance, origin="imported",
    )  # fmt: skip


@dataclass(frozen=True)
class Verdict:
    classification: Classification
    existing: tuple[str, ...] = ()  # stored values it repeats or contradicts
    note: str | None = None  # excluded: why · possible_duplicate: the similar value


def _temporal(f: ProposedFact) -> bool:
    return bool(f.change or f.time or _TEMPORAL.search(" ".join(text.words(f.excerpt or ""))))


def classify_fact(conn: Connection, f: ProposedFact, subject_id: str | None,
                  *, ambiguous: bool = False, value: str | None = None) -> Verdict:  # fmt: skip
    """``subject_id``: None = the user, :data:`NEW` = a person the import creates, else the
    stored entity it is compared with. ``ambiguous``: the subject is not settled."""
    c = candidate(f, value=value)
    d = policy.decide(c, explicit=True)
    if d.outcome == "drop":
        return Verdict("excluded", note=d.reason)
    if directive(c.value) or directive(f.excerpt or ""):
        return Verdict("excluded", note="instruction_like")
    if ambiguous:
        return Verdict("ambiguous_entity")
    if subject_id == NEW:
        return Verdict("new" if f.certain else "insufficient_evidence")
    current = repo.consolidation_candidates(
        conn, subject_id, c.predicate, value=c.value, replaces=c.replaces
    )
    active = [m for m in current if m.status == "active"]
    exact = [m for m in active if text.fold(c.value).strip() == m.value_key]
    if exact:
        return Verdict("exact_duplicate", (exact[0].value,))
    plan = consolidation.plan(c, current, explicit=False)
    if plan.action == "duplicate":
        same = next((m for m in active if m.id in plan.target_ids), None)
        return Verdict(
            "possible_duplicate", (same.value,) if same else (), same.value if same else None
        )
    if plan.action in ("supersede", "conflict"):
        olds = tuple(m.value for m in active if m.id in plan.target_ids)
        return Verdict("temporal_update" if _temporal(f) else "conflict", olds)
    return Verdict("new" if f.certain else "insufficient_evidence")


def classify_relation(conn: Connection, r: ProposedRelation, src_id: str | None,
                      tgt_id: str | None, *, ambiguous: bool = False) -> Verdict:  # fmt: skip
    """Ends: a stored entity id, the user (``models.USER_ID``), :data:`NEW`, or None (not
    settled)."""
    joined = " ".join(x for x in (r.statement, r.excerpt or "") if x)
    if policy.secret_kind(joined):
        return Verdict("excluded", note="secret")
    if directive(joined):
        return Verdict("excluded", note="instruction_like")
    t = relations.TYPES.get(r.type)
    if t is None:
        return Verdict("excluded", note="unknown_type")
    if ambiguous or src_id is None or tgt_id is None:
        return Verdict("ambiguous_entity")
    from lazis.memory import relationships as rels

    temporal = r.change or r.status == "ended" or bool(r.time)
    if NEW in (src_id, tgt_id):
        # A new person can still clash with what is stored: a second spouse, another mother.
        stored = src_id if src_id != NEW else (tgt_id if t.symmetric else None)
        if t.single and stored not in (None, NEW):
            rivals = [x for x in gs.edges_from(conn, str(stored), CURRENT) if x.type == r.type]
            if rivals:
                olds = tuple(rels.statement_for(conn, x.source_id, x.type, x.target_id)
                             for x in rivals)  # fmt: skip
                return Verdict("temporal_update" if temporal else "conflict", olds)
        return Verdict("new" if r.certain else "insufficient_evidence")

    between = gs.relationships_between(conn, src_id, tgt_id, statuses=CURRENT)
    same = [x for x in between if rels._equivalent(x, src_id, r.type, tgt_id)]  # pyright: ignore[reportPrivateUsage]
    if same and not (r.negated or r.correction or r.status == "ended"):
        return Verdict("exact_duplicate", (rels.statement_for(conn, same[0].source_id, same[0].type,
                                                              same[0].target_id),))  # fmt: skip
    rivals = [x for x in between if x not in same and rels._same_group(x.type, r.type)]  # pyright: ignore[reportPrivateUsage]
    if t.single:
        rivals += [x for x in gs.edges_from(conn, src_id, CURRENT)
                   if x.type == r.type and x.target_id != tgt_id]  # fmt: skip
    if same or rivals or r.negated or r.correction:
        olds = tuple(
            rels.statement_for(conn, x.source_id, x.type, x.target_id) for x in [*same, *rivals]
        )
        return Verdict("temporal_update" if temporal else "conflict", olds)
    return Verdict("new" if r.certain else "insufficient_evidence")


@dataclass
class Analysis:
    matches: dict[str, PersonMatch] = field(default_factory=dict[str, PersonMatch])
    facts: list[Verdict] = field(default_factory=list[Verdict])
    relations: list[Verdict] = field(default_factory=list[Verdict])


def subject_for(match: PersonMatch | None) -> tuple[str | None, bool]:
    """(id to compare with, ambiguous) for a proposed person's current match."""
    if match is None:
        return None, False
    if match.match == "existing":
        return match.suggested_id, False
    if match.match == "new":
        return NEW, False
    return None, True


def analyze(conn: Connection, proposals: Proposals) -> Analysis:
    from lazis.memory.models import USER_ID

    out = Analysis()
    for p in proposals.people:
        out.matches[p.key] = match_person(conn, p, proposals.people)
    seen: set[tuple[str, str, str]] = set()
    for f in proposals.facts:
        mark = (f.subject, f.predicate, text.fold(f.value).strip())
        if f.subject == USER:
            v = classify_fact(conn, f, None)
        else:
            sid, amb = subject_for(out.matches.get(f.subject))
            v = classify_fact(conn, f, sid, ambiguous=amb)
        if mark in seen and v.classification not in ("excluded", "ambiguous_entity"):
            v = Verdict("exact_duplicate", (f.value,), "in_file")  # said twice in the file
        seen.add(mark)
        out.facts.append(v)
    for r in proposals.relations:
        ends: list[str | None] = []
        amb = False
        for ref in (r.source, r.target):
            if ref == USER:
                ends.append(USER_ID)
                continue
            sid, a = subject_for(out.matches.get(ref))
            amb = amb or a
            ends.append(sid)
        out.relations.append(classify_relation(conn, r, ends[0], ends[1], ambiguous=amb))
    return out


def predicate_known(key: str) -> bool:
    return registry.get(key) is not None
