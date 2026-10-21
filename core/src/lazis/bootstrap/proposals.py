"""What an import proposes, before anything is decided (Phase 8, ADR-0019).

A file — JSON mapped deterministically, or Markdown/text read by the model — becomes
:class:`Proposals`: proposed people (each one person, namesakes kept apart), proposed facts
about the user or a proposed person, and proposed relationships between them. Every item keeps
where it came from (section, the user's own words, line, method). Nothing here touches the
database; :mod:`lazis.bootstrap.analyze` compares proposals with the memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from lazis.memory import registry

Method = Literal["json", "gemma"]
USER = "user"

CATEGORIES = ("profile", "person", "relationship", "project", "preference", "habit", "goal",
              "event", "fact")  # fmt: skip
_BY_PREDICATE = {
    "preferred_name": "profile", "occupation": "profile", "employer": "profile",
    "location": "profile", "birthday": "profile", "computer": "profile", "phone": "profile",
    "device": "profile", "operating_system": "profile", "technology": "profile",
    "skill": "profile", "language": "profile", "address": "profile", "contact": "profile",
    "interest": "preference", "likes": "preference", "dislikes": "preference",
    "communication_preference": "preference", "work_preference": "preference",
    "habit": "habit", "goal": "goal", "plan": "goal", "event": "event", "decision": "event",
}  # fmt: skip


def category_for(predicate: str, subject_is_user: bool, subject_kind: str = "person") -> str:
    if predicate.startswith("project_") or subject_kind == "project":
        return "project"
    cat = _BY_PREDICATE.get(predicate, "fact")
    if not subject_is_user and cat == "profile":
        return "person"
    return cat


@dataclass
class ProposedPerson:
    key: str  # import-local key: a JSON id, or "p1", "p2", …
    name: str
    kind: str = "person"
    relation: str | None = None  # the user's words for them, third person ("komşusu")
    description: str | None = None
    aliases: tuple[str, ...] = ()
    section: str = ""
    excerpt: str | None = None


@dataclass
class ProposedFact:
    subject: str  # USER or a person key
    predicate: str
    value: str
    statement: str
    method: Method
    category: str = "fact"
    change: bool = False  # the file says it changed ("artık", "taşındı")
    replaces: str | None = None
    time: str | None = None  # "2023'ten beri", "geçen yaz", a date
    certain: bool = True
    sensitive: str | None = None
    importance: float = 0.6
    section: str = ""
    excerpt: str | None = None  # the user's own words this came from
    line: int | None = None

    @property
    def confidence(self) -> float:
        if self.method == "json":
            return 1.0
        return 0.8 if self.certain else 0.5


@dataclass
class ProposedRelation:
    source: str  # USER or a person key
    type: str  # a relationship type key (lazis.memory.relations)
    target: str
    method: Method
    status: Literal["active", "ended", "planned"] = "active"
    change: bool = False
    correction: bool = False
    negated: bool = False
    time: str | None = None
    certain: bool = True
    statement: str = ""
    section: str = ""
    excerpt: str | None = None
    line: int | None = None

    @property
    def confidence(self) -> float:
        if self.method == "json":
            return 1.0
        return 0.8 if self.certain else 0.5


@dataclass
class Proposals:
    people: list[ProposedPerson] = field(default_factory=list[ProposedPerson])
    facts: list[ProposedFact] = field(default_factory=list[ProposedFact])
    relations: list[ProposedRelation] = field(default_factory=list[ProposedRelation])
    warnings: list[str] = field(default_factory=list[str])  # where and what, never values

    def person(self, key: str) -> ProposedPerson | None:
        return next((p for p in self.people if p.key == key), None)


def label_of(predicate: str) -> str:
    p = registry.get(predicate)
    return p.label if p else predicate
