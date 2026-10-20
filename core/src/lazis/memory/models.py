"""Memory domain types (rows and candidates). Plain data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

EntityKind = Literal["person", "project", "organization", "place", "event", "group", "thing"]
Status = Literal["active", "superseded", "retracted"]
Origin = Literal["stated", "requested", "confirmed", "imported", "user_edit", "inferred"]
Sensitivity = Literal["normal", "personal", "sensitive"]
InboxType = Literal["ambiguous_entity", "conflict", "sensitive", "destructive", "import_batch"]
JobStatus = Literal["queued", "running", "done", "skipped", "deferred", "failed"]

# Sensitivity categories the extractor may report. "secret" is never stored anywhere.
SENSITIVE_CATEGORIES = ("health", "finance", "identity", "contact", "address", "intimate")


USER_ID = "user"  # the fixed id of the user's entity row (0005_graph)


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
    is_user: bool = False  # the user's own row: a relationship endpoint only (Phase 7)
    confidence: float = 0.85
    origin: str = "stated"


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


# ----- relationships (Phase 7) ------------------------------------------------------------
RelStatus = Literal["active", "ended", "planned", "unverified", "superseded", "retracted"]
RelOrigin = Literal["stated", "requested", "confirmed", "imported", "user_edit", "migrated"]
CURRENT: tuple[RelStatus, ...] = ("active", "planned", "unverified")


@dataclass(frozen=True)
class Relationship:
    """One stated relationship, stored once: (source, type, target). See memory.relations."""

    id: str
    source_id: str
    type: str
    target_id: str
    qualifier: str | None
    status: RelStatus
    origin: RelOrigin
    confidence: float
    sensitivity: Sensitivity
    sensitivity_category: str | None
    time_text: str | None
    valid_from: str | None
    valid_to: str | None
    supersedes_id: str | None
    conflict_state: Literal["none", "pending"]
    version: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class RelCandidate:
    """A relationship proposed by the extractor, a chat request, the UI or an import. ``source``
    None means the user. Nothing is written before both ends are resolved."""

    type: str
    target: EntityRef
    source: EntityRef | None = None
    qualifier: str | None = None
    quote: str | None = None
    statement: str = ""
    change: bool = False  # it changed in the real world ("artık", "taşındı")
    correction: bool = False  # an earlier statement was wrong ("yanlış söyledim", "aslında")
    negated: bool = False  # "Ahmet ile Mehmet kardeş değil"
    status: Literal["active", "ended", "planned"] = "active"
    certain: bool = True
    time_text: str | None = None
    origin: RelOrigin = "stated"
