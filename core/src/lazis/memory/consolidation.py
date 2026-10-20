"""A candidate against what is stored for the same subject and predicate (pure;
MEMORY_ARCHITECTURE P6.6).

* Same value (or a near-duplicate sentence) → **duplicate**: add evidence, no new row.
* Single-valued predicate with another current value:
  - the user signals a change ("artık", "taşındı", "değiştirdim"), or asked explicitly / edited
    → **supersede**: the old value stays as history ("eskiden"), the new one is current;
  - no change signal → **conflict**: ask the user; until then the old value is used with a
    staleness marker and the new one waits in the inbox.
* Multi-valued predicate → **create** (coexist), and with a change signal only the values the
  user said were replaced (``replaces``) are superseded — "artık Mac kullanıyorum" does not
  erase that the user also uses Linux.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import registry, text
from lazis.memory.models import Candidate, Memory

NEAR_DUPLICATE = 0.8


@dataclass(frozen=True)
class Plan:
    action: Literal["create", "duplicate", "supersede", "conflict"]
    target_ids: tuple[str, ...] = field(
        default_factory=tuple
    )  # duplicate / superseded / conflicting


def same_value(c: Candidate, m: Memory) -> bool:
    if text.fold(c.value).strip() == m.value_key:
        return True
    return (
        text.similarity(c.value, m.value) >= NEAR_DUPLICATE
        or text.similarity(c.statement, m.content) >= NEAR_DUPLICATE
    )


def plan(c: Candidate, current: Sequence[Memory], *, explicit: bool) -> Plan:
    active = [m for m in current if m.status == "active"]
    dupes = [m for m in active if same_value(c, m)]
    if dupes:
        return Plan("duplicate", (dupes[0].id,))
    pred = registry.get(c.predicate)
    if pred is None or not active:
        return Plan("create")
    if pred.cardinality == "single":
        if c.change or explicit:
            return Plan("supersede", tuple(m.id for m in active))
        return Plan("conflict", tuple(m.id for m in active))
    if c.change and c.replaces:
        replaced = [
            m
            for m in active
            if text.similarity(c.replaces, m.value) >= 0.5 or text.fold(c.replaces) in m.value_key
        ]
        if replaced:
            return Plan("supersede", tuple(m.id for m in replaced))
    return Plan("create")
