"""What LAZIS may bring up on its own (Phase 10A, ADR-0021).

Proactive follow-ups and the relationship brief (Phase 10C) speak without being asked, so a
mistake there is LAZIS's alone. They read memory, relationships and conversation summaries
through this one gate, which refuses:

* **forgotten** — the record, its topic or its value was forgotten (a record learned again
  only by an explicit request has no mark); a summary sentence that speaks of a forgotten
  relationship or value (:mod:`forgotten`: summaries keep the words);
* **rejected** — the user turned the record down before (import or inbox);
* **not active** — superseded, retracted, ended relationships;
* **conflict** — a different value waits for the user's answer;
* **uncertain** — below :data:`MIN_CONFIDENCE` (recall marks it "kesin değil"; never the sole
  basis for raising something);
* **sensitive** — health, money, intimate relationships: never raised unasked;
* **inferred** — a memory LAZIS concluded, not the user's words (derived relationships are
  computed, never stored).

A person who shares a name with another stored person, or has an open "which one?" question,
**needs a label** wherever LAZIS names them ("komşunuz Ahmet"); a summary sentence that names
such a person without any of their labels is dropped (:meth:`Gate.clean_text`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import forgotten, relations, service, text, unsettled
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory.models import CURRENT, Memory, Relationship
from lazis.storage.driver import Connection

Reason = Literal[
    "forgotten", "rejected", "not_active", "conflict", "uncertain", "sensitive", "inferred"
]
MIN_CONFIDENCE = 0.6
_SENTENCE = re.compile(r"[^.!?]+(?:[.!?]+|$)")


@dataclass(frozen=True)
class Gate:
    index: forgotten.Index = field(default_factory=forgotten.Index)
    rejected: frozenset[str] = frozenset()
    labeled: tuple[unsettled.Unsettled, ...] = ()  # people who need a label when named

    @property
    def needs_label_ids(self) -> frozenset[str]:
        return frozenset(c.entity_id for u in self.labeled for c in u.candidates)

    def needs_label(self, entity_id: str) -> bool:
        return entity_id in self.needs_label_ids

    def memory(self, m: Memory) -> Reason | None:
        if m.status != "active":
            return "not_active"
        key = self.index.key
        fps = {
            repo.value_fingerprint_with(key, m.subject_id, m.value_key),
            repo.fingerprint_with(key, m.subject_id, m.predicate, m.value_key),
            repo.fingerprint_with(key, m.subject_id, m.predicate, "*"),
        }
        if fps & self.index.fps:
            return "forgotten"
        if fps & self.rejected:
            return "rejected"
        if m.origin == "inferred":
            return "inferred"
        return _common(m.conflict_state, m.confidence, m.sensitivity)

    def relationship(self, r: Relationship) -> Reason | None:
        if r.status not in CURRENT:
            return "not_active"
        key = self.index.key
        fps = {
            gs.rel_fingerprint_with(key, r.source_id, r.type, r.target_id),
            gs.pair_fingerprint_with(key, r.source_id, r.target_id),
        }
        if fps & self.index.fps:
            return "forgotten"
        if fps & self.rejected:
            return "rejected"
        return _common(r.conflict_state, r.confidence, r.sensitivity)

    def clean_text(self, body: str) -> tuple[str, int]:
        """The sentences of a summary LAZIS may reuse unasked (line by line: summaries are
        lists), and how many were dropped."""
        lines: list[str] = []
        dropped = 0
        for line in body.splitlines():
            kept: list[str] = []
            for m in _SENTENCE.finditer(line):
                sentence = m.group(0)
                if not sentence.strip():
                    continue
                if self.index.speaks_of(sentence) is not None or self._unlabeled(sentence):
                    dropped += 1
                    continue
                kept.append(sentence.strip())
            if kept:
                lines.append(" ".join(kept))
        return "\n".join(lines), dropped

    def _unlabeled(self, sentence: str) -> bool:
        words = text.words(sentence)
        types = {t for t, _ in relations.types_in(words)}
        return any(
            text.mentions_name(words, u.key)
            and not any(c.label_types & types for c in u.candidates)
            for u in self.labeled
        )


def _common(conflict: str, confidence: float, sensitivity: str) -> Reason | None:
    if conflict == "pending":
        return "conflict"
    if confidence < MIN_CONFIDENCE:
        return "uncertain"
    if sensitivity == "sensitive":
        return "sensitive"
    return None


def load(conn: Connection) -> Gate:
    index = forgotten.load(conn)
    if index.empty:
        index = forgotten.Index(key=repo.fingerprint_key(conn))
    rows = conn.execute(
        "SELECT fingerprint FROM memory_suppressions WHERE reason = 'rejected'"
    ).fetchall()
    rejected = frozenset(str(r[0]) for r in rows)
    keys = {
        str(r[0])
        for r in conn.execute(
            "SELECT name_key FROM memory_entities WHERE status = 'active' AND is_user = 0"
            " GROUP BY name_key HAVING COUNT(*) > 1"
        ).fetchall()
    } | service.pending_namesake_keys(conn)
    ids = [e.id for k in sorted(keys) for e in repo.find_entities(conn, k)]
    return Gate(index, rejected, unsettled.load(conn, ids))


def usable_memories(gate: Gate, memories: Iterable[Memory]) -> list[Memory]:
    return [m for m in memories if gate.memory(m) is None]


def usable_relationships(gate: Gate, rels: Iterable[Relationship]) -> list[Relationship]:
    return [r for r in rels if gate.relationship(r) is None]
