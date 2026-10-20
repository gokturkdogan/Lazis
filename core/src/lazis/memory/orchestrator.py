"""Database-side steps of the memory pipeline (runs on the database thread).

The conversation engine owns the model call and the job queue's lifecycle; this module gives
it what the extraction instruction needs (entities mentioned in the target messages, the
user's current single-valued facts, forgotten topics) and applies validated items, one
change set per source message. It never sees the conversation tables.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from lazis.memory import registry, service, text
from lazis.memory import repository as repo
from lazis.memory.extraction import Extracted, Known, Target
from lazis.memory.models import ApplyReport, Candidate, Entity
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
    found: list[str] = []
    for alias_key, entity_id in repo.alias_index(conn):
        if entity_id not in found and text.mentions_name(words, alias_key):
            found.append(entity_id)
    entities = [e for e in (repo.get_entity(conn, i) for i in found) if e is not None]
    return entities[:limit]


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
            ),
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
