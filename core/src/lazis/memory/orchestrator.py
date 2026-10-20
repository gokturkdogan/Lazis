"""Database-side steps of the memory pipeline (runs on the database thread).

The conversation engine owns the model call and the job queue's lifecycle; this module gives
it what the extraction instruction needs (entities mentioned in the target messages, the
user's current single-valued facts, forgotten topics) and applies validated items, one
change set per source message. It never sees the conversation tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lazis.memory import graphstore as gs
from lazis.memory import registry, relations, service, text
from lazis.memory import repository as repo
from lazis.memory.extraction import Extracted, ExtractedRel, Known, Target
from lazis.memory.models import CURRENT, ApplyReport, Candidate, Entity, RelCandidate
from lazis.memory.relationships import RelReport, apply_relations
from lazis.memory.service import Source
from lazis.storage.driver import Connection

MAX_KNOWN = 8
MAX_FACTS_PER_ENTITY = 6
MAX_USER_FACTS = 12


MAX_QUESTIONS = 3


@dataclass(frozen=True)
class ExtractionContext:
    known: tuple[Known, ...] = ()
    user_facts: tuple[str, ...] = ()
    forgotten: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()  # open "which Ahmet?" items of this conversation


def _fact(predicate: str, value: str) -> str:
    p = registry.get(predicate)
    return f"{p.label if p else predicate}: {value}"


def mentioned_entities(conn: Connection, texts: Sequence[str], *, limit: int) -> list[Entity]:
    """Active entities whose name or alias occurs in the texts (suffix-tolerant), in order of
    first mention."""
    words = text.words(" ".join(texts))
    if not words:
        return []
    # Only the keys that could occur in these words are looked up (indexed): the cost no
    # longer grows with the number of stored people.
    hits = repo.aliases_matching(conn, text.candidate_keys(words))
    first: dict[str, int] = {}
    for key, ids in hits.items():
        if not text.mentions_name(words, key):
            continue
        at = _first_position(words, key)
        for eid in ids:
            first[eid] = min(first.get(eid, at), at)
    found = sorted(first, key=lambda eid: first[eid])
    entities = [e for e in (repo.get_entity(conn, i) for i in found[: limit * 2]) if e is not None]
    return entities[:limit]


def _first_position(words: Sequence[str], key: str) -> int:
    parts = key.split()
    for i in range(len(words) - len(parts) + 1):
        if words[i : i + len(parts) - 1] == parts[:-1] and words[i + len(parts) - 1].startswith(
            parts[-1]
        ):
            return i
    return len(words)


def extraction_context(
    conn: Connection, targets: Sequence[Target], *, conversation_id: str | None = None
) -> ExtractionContext:
    entities = mentioned_entities(conn, [t.text for t in targets], limit=MAX_KNOWN)
    questions: list[str] = []
    if conversation_id is not None:
        # An answer to "which Ahmet?" usually does not name him again ("çocukluk arkadaşım
        # olan"): the open question and its options are context for the model.
        for item in repo.list_inbox(conn, status="open", types=("ambiguous_entity",)):
            if item.conversation_id != conversation_id or len(questions) >= MAX_QUESTIONS:
                continue
            labels = [str(o.get("label", "")) for o in item.payload.get("options", [])]
            statement = str(item.payload.get("candidate", {}).get("statement", ""))
            questions.append(f"«{statement}» — hangisi? Seçenekler: {', '.join(labels)}")
            for o in item.payload.get("options", []):
                e = repo.get_entity(conn, str(o.get("id")))
                if e is not None and e.id not in {x.id for x in entities}:
                    entities.append(e)
    known = tuple(
        Known(
            e,
            tuple(
                _fact(m.predicate, m.value)
                for m in repo.memories_for_subject(conn, e.id)[:MAX_FACTS_PER_ENTITY]
                if m.sensitivity != "sensitive"
            )
            + _relation_facts(conn, e),
        )
        for e in entities
    )
    user_facts = tuple(
        _fact(m.predicate, m.value)
        for m in repo.memories_for_subject(conn, None)
        if (p := registry.get(m.predicate)) is not None
        and p.cardinality == "single"
        and m.sensitivity != "sensitive"
    )[:MAX_USER_FACTS]
    names = {e.id: e.name for e in entities}
    forgotten = tuple(
        f"{'Kullanıcı' if sid is None else names.get(sid, '?')} — "
        f"{p.label if (p := registry.get(pred)) else pred}"
        for sid, pred in repo.suppressed_topics(conn, [None, *names])
    )
    return ExtractionContext(known, user_facts, forgotten, tuple(questions))


def _relation_facts(conn: Connection, e: Entity) -> tuple[str, ...]:
    """Current, non-sensitive relationships of a known entity, as the model will read them."""
    out: list[str] = []
    for r in gs.relationships_of(conn, e.id, statuses=CURRENT)[:MAX_FACTS_PER_ENTITY]:
        if r.sensitivity == "sensitive":
            continue
        s, t = repo.get_entity(conn, r.source_id), repo.get_entity(conn, r.target_id)
        if s is not None and t is not None:
            out.append(relations.describe(s.name, r.type, t.name))
    return tuple(out)


def apply_relation_extraction(
    conn: Connection, accepted: Sequence[ExtractedRel], *, conversation_id: str
) -> dict[str, RelReport]:
    """Relationships from validated extraction, one change set per source message."""
    groups: dict[str, list[RelCandidate]] = {}
    for item in accepted:
        groups.setdefault(item.message_id, []).append(item.candidate)
    return {
        message_id: apply_relations(
            conn, cands, source=Source("message", message_id, conversation_id), explicit=False
        )
        for message_id, cands in groups.items()
    }


def apply_extraction(
    conn: Connection, accepted: Sequence[Extracted], *, conversation_id: str
) -> dict[str, ApplyReport]:
    """Apply validated items, grouped by the message they came from (each group is one
    change set whose source is that message). Returns the report per message id."""
    groups: dict[str, list[Candidate]] = {}
    for item in accepted:
        groups.setdefault(item.message_id, []).append(item.candidate)
    return {
        message_id: service.apply_candidates(
            conn,
            candidates,
            source=Source("message", message_id, conversation_id),
            explicit=False,
        )
        for message_id, candidates in groups.items()
    }
