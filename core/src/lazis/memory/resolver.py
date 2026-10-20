"""Which person or project a candidate is about (pure; MEMORY_ARCHITECTURE P6.5).

Merging two different people is worse than keeping two records for one person, so:

* no stored entity with that name → a new entity;
* exactly one → that entity, unless the relation the user states contradicts the stored one
  ("iş ortağım Ahmet" vs a stored "çocukluk arkadaşı Ahmet": maybe a different Ahmet → ask);
* two or more → only an entity the relation (or an explicit pick by the extractor that the
  relation confirms) identifies uniquely; otherwise ambiguous → ask, never pick one.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import text
from lazis.memory.models import Entity, EntityRef


@dataclass(frozen=True)
class Resolution:
    kind: Literal["existing", "new", "ambiguous"]
    entity_id: str | None = None
    options: tuple[str, ...] = field(default_factory=tuple)
    reason: str = ""


def relation_compatible(a: str | None, b: str | None) -> bool:
    """Unknown on either side is compatible; otherwise one must contain the other
    ("arkadaşım" ~ "çocukluk arkadaşı"), compared on folded word prefixes."""
    if not a or not b:
        return True
    wa = {text.stem_prefix(w) for w in text.words(a)} - {"benim"}
    wb = {text.stem_prefix(w) for w in text.words(b)} - {"benim"}
    if not wa or not wb:
        return True
    return _covered(wa, wb) or _covered(wb, wa)


def _same_word(x: str, y: str) -> bool:
    # Stems of one word in two inflections differ in length ("arkada" / "arkad").
    short, long_ = sorted((x, y), key=len)
    return short == long_ or (len(short) >= 4 and long_.startswith(short))


def _covered(small: set[str], big: set[str]) -> bool:
    return all(any(_same_word(s, b) for b in big) for s in small)


def _kinds_compatible(ref_kind: str, entity_kind: str) -> bool:
    if ref_kind == entity_kind:
        return True
    return {ref_kind, entity_kind} <= {"organization", "project", "thing"}


def resolve(ref: EntityRef, candidates: Sequence[Entity]) -> Resolution:
    pool = [e for e in candidates if e.status == "active" and _kinds_compatible(ref.kind, e.kind)]
    if not pool:
        return Resolution("new", reason="no_match")
    by_id = {e.id: e for e in pool}
    if ref.ref_id is not None and ref.ref_id in by_id:
        picked = by_id[ref.ref_id]
        if relation_compatible(ref.relation, picked.relation):
            if len(pool) == 1 or ref.relation:
                return Resolution("existing", picked.id, reason="picked")
            # Picked among namesakes without anything that tells them apart: not enough.
            return Resolution("ambiguous", options=tuple(by_id), reason="unsupported_pick")
    if len(pool) == 1:
        only = pool[0]
        if relation_compatible(ref.relation, only.relation):
            return Resolution("existing", only.id, reason="single_match")
        return Resolution("ambiguous", options=(only.id,), reason="relation_differs")
    if ref.relation:
        matching = [e for e in pool if e.relation and relation_compatible(ref.relation, e.relation)]
        if len(matching) == 1:
            return Resolution("existing", matching[0].id, reason="relation_identifies")
    return Resolution("ambiguous", options=tuple(by_id), reason="namesakes")
