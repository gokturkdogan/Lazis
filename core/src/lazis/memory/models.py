"""Memory domain types (rows and candidates). Plain data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EntityKind = Literal["person", "project", "organization", "place", "thing"]
Status = Literal["active", "superseded", "retracted"]
Origin = Literal["stated", "requested", "confirmed", "imported", "user_edit", "inferred"]
Sensitivity = Literal["normal", "personal", "sensitive"]
InboxType = Literal["ambiguous_entity", "conflict", "sensitive", "destructive", "import_batch"]
JobStatus = Literal["queued", "running", "done", "skipped", "deferred", "failed"]

# Sensitivity categories the extractor may report. "secret" is never stored anywhere.
SENSITIVE_CATEGORIES = ("health", "finance", "identity", "contact", "address", "intimate")


@dataclass(frozen=True)
class Entity:
    id: str
    kind: EntityKind
    name: str
    name_key: str
    relation: str | None
    relation_key: str | None
    description: str | None
    status: Literal["active", "merged"]
    merged_into: str | None
    created_at: str
    updated_at: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class Memory:
    id: str
    rowid: int
    kind: str
    subject_id: str | None
    predicate: str
    value: str
    value_key: str
    content: str
    keywords: str
    status: Status
    origin: Origin
    confidence: float
    importance: float
    sensitivity: Sensitivity
    sensitivity_category: str | None
    event_time: str | None
    valid_from: str | None
    valid_to: str | None
    supersedes_id: str | None
    conflict_state: Literal["none", "pending"]
    recall_count: int
    created_at: str
    updated_at: str
    version: int


@dataclass(frozen=True)
class Evidence:
    id: str
    memory_id: str
    source_type: Literal["message", "import", "user_edit", "confirmation"]
    source_ref: str | None
    quote: str | None
    created_at: str


@dataclass(frozen=True)
class InboxItem:
    id: str
    type: InboxType
    status: Literal["open", "resolved", "dismissed"]
    summary: str
    payload: dict[str, Any]
    conversation_id: str | None
    source_message_id: str | None
    created_at: str
    resolved_at: str | None
    resolution: str | None


@dataclass(frozen=True)
class Job:
    id: str
    user_message_id: str
    conversation_id: str
    model: str
    status: JobStatus
    attempts: int
    last_error: str | None
    created_at: str


@dataclass(frozen=True)
class EntityRef:
    """How a candidate names a person/project: the extractor's view, before resolution."""

    name: str
    kind: EntityKind = "person"
    relation: str | None = None
    ref_id: str | None = None  # an id the extractor picked from the candidates it was shown


@dataclass(frozen=True)
class Candidate:
    """A fact proposed by extraction, an explicit command, an edit or an import."""

    predicate: str
    value: str
    statement: str
    about: Literal["user", "entity"] = "user"
    entity: EntityRef | None = None
    quote: str | None = None
    event_time: str | None = None
    change: bool = False  # the user says the previous value is no longer true
    replaces: str | None = None  # for multi-valued predicates: which old value is replaced
    certain: bool = True
    sensitivity_category: str | None = None
    importance: float = 0.5
    durable: bool = True
    keywords: tuple[str, ...] = ()
    origin: Origin = "stated"


@dataclass
class ApplyReport:
    """What applying a batch of candidates did (counts and ids; no content)."""

    created: list[str] = field(default_factory=list[str])
    updated: list[str] = field(default_factory=list[str])  # evidence added to an existing memory
    superseded: list[str] = field(default_factory=list[str])
    inbox: list[str] = field(default_factory=list[str])
    entities_created: list[str] = field(default_factory=list[str])
    dropped: dict[str, int] = field(default_factory=dict[str, int])

    def drop(self, reason: str) -> None:
        self.dropped[reason] = self.dropped.get(reason, 0) + 1

    @property
    def changed(self) -> bool:
        return bool(self.created or self.updated or self.superseded or self.entities_created)

    def counts(self) -> dict[str, int]:
        return {
            "created": len(self.created),
            "updated": len(self.updated),
            "superseded": len(self.superseded),
            "inbox": len(self.inbox),
            "entities_created": len(self.entities_created),
            **{f"dropped_{k}": v for k, v in self.dropped.items()},
        }
