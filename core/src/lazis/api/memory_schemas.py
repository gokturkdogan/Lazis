"""API v1 schemas for personal memory (Phase 6). Exported to OpenAPI → TypeScript types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ID = r"^[0-9A-Za-z_-]{1,64}$"


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MemorySubjectModel(_Schema):
    id: str
    kind: Literal["person", "project", "organization", "place", "event", "group", "thing"]
    name: str
    relation: str | None


class MemoryRecordModel(_Schema):
    id: str
    kind: str
    predicate: str
    predicate_label: str
    subject: MemorySubjectModel | None  # None: about the user
    value: str
    content: str
    status: Literal["active", "superseded", "retracted"]
    origin: Literal["stated", "requested", "confirmed", "imported", "user_edit", "inferred"]
    confidence: float
    importance: float
    sensitivity: Literal["normal", "personal", "sensitive"]
    sensitivity_category: str | None
    conflict_state: Literal["none", "pending"]
    event_time: str | None
    valid_from: str | None
    valid_to: str | None
    supersedes_id: str | None
    recall_count: int
    created_at: str
    updated_at: str
    # Phase 9: how much it matters (computed, never a reason to write) and how many different
    # messages / imports / edits back it.
    tier: Literal["critical_personal", "high", "medium", "low", "ephemeral"] = "medium"
    sources: int = 0


class MemoryEvidenceModel(_Schema):
    source_type: Literal["message", "import", "user_edit", "confirmation", "migration"]
    source_ref: str | None
    quote: str | None
    created_at: str


class MemoryListResponse(_Schema):
    records: list[MemoryRecordModel]
    has_more: bool


class MemoryRecordDetailResponse(_Schema):
    record: MemoryRecordModel
    evidence: list[MemoryEvidenceModel]
    previous: list[MemoryRecordModel]  # values this one replaced, newest first


class MemoryEntityModel(_Schema):
    id: str
    kind: Literal["person", "project", "organization", "place", "event", "group", "thing"]
    name: str
    relation: str | None
    description: str | None
    aliases: list[str]
    records: int
    updated_at: str


class MemoryEntityListResponse(_Schema):
    entities: list[MemoryEntityModel]


class MemoryEntityDetailResponse(_Schema):
    entity: MemoryEntityModel
    records: list[MemoryRecordModel]


class InboxOptionModel(_Schema):
    id: str
    label: str


class MemoryInboxItemModel(_Schema):
    """A decision waiting for the user. ``proposal`` is the fact in question (no raw payload)."""

    id: str
    type: Literal["ambiguous_entity", "conflict", "sensitive", "destructive", "import_batch"]
    summary: str
    created_at: str
    predicate_label: str | None
    value: str | None
    subject: str | None
    options: list[InboxOptionModel]  # ambiguous_entity
    existing: list[str]  # conflict: the current value(s)
    category: str | None  # sensitive
    about: Literal["memory", "relationship", "merge"] = "memory"
    relationship: str | None = None  # the relationship in question ("Mehmet: Ahmet'in kardeşi")


class MemoryInboxResponse(_Schema):
    items: list[MemoryInboxItemModel]


class MemoryOverviewResponse(_Schema):
    memories: dict[str, int]
    entities: int
    inbox_open: int
    jobs: dict[str, int]
    auto_extract: bool
    trusted_models: list[str]


class PredicateModel(_Schema):
    key: str
    label: str
    kind: str
    cardinality: Literal["single", "multi"]
    sensitivity: Literal["normal", "personal", "sensitive"]
    subjects: list[str]


class PredicateListResponse(_Schema):
    predicates: list[PredicateModel]


class NewEntityModel(_Schema):
    name: str = Field(min_length=1, max_length=80)
    relation: str | None = Field(default=None, max_length=80)
    kind: Literal["person", "project", "organization", "place", "event", "group", "thing"] = (
        "person"
    )


class MemoryCreateRequest(_Schema):
    predicate: str = Field(pattern=r"^[a-z_]{1,40}$")
    value: str = Field(min_length=1, max_length=200)
    statement: str = Field(default="", max_length=300)
    entity_id: str | None = Field(default=None, pattern=ID)
    new_entity: NewEntityModel | None = None


class MemoryEditRequest(_Schema):
    value: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=300)


class EntityEditRequest(_Schema):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    relation: str | None = Field(default=None, max_length=80)
    description: str | None = Field(default=None, max_length=300)


class EntityMergeRequest(_Schema):
    other_id: str = Field(pattern=ID)


class EntitySplitRequest(_Schema):
    memory_ids: list[str] = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=80)
    relation: str | None = Field(default=None, max_length=80)


class InboxResolveRequest(_Schema):
    choice: str = Field(pattern=r"^(new|old|both|approve|reject|dismiss|[0-9A-Za-z_-]{10,64})$")


class ApplyResultResponse(_Schema):
    created: int
    updated: int
    superseded: int
    inbox: int
    entities_created: int
    dropped: dict[str, int]


class ForgetResultResponse(_Schema):
    memories: int
    entities: int


class ImportPreviewRequest(_Schema):
    format: Literal["json", "text"]
    content: str = Field(min_length=1, max_length=60_000)


class ImportItemModel(_Schema):
    index: int
    status: Literal["new", "duplicate", "update", "conflict", "ambiguous", "excluded"]
    subject: str
    predicate: str
    predicate_label: str
    value: str
    statement: str
    reason: str | None
    sensitive: bool
    options: list[InboxOptionModel]
    existing: list[str]


class ImportPreviewResponse(_Schema):
    batch_id: str
    items: list[ImportItemModel]
    errors: list[str]


class ImportApplyRequest(_Schema):
    # index (as a string: JSON object keys) → "apply" | option id | "new" | "replace" | "both"
    selections: dict[str, str] = Field(max_length=500)


# ----- relationship graph (Phase 7) ----------------------------------------------------------
RelStatusLiteral = Literal["active", "ended", "planned", "unverified", "superseded", "retracted"]


class RelationshipTypeModel(_Schema):
    key: str
    label: str  # what the target is to the source ("kardeşi", "çalıştığı yer")
    inverse_label: str  # what the source is to the target ("" for a one-way type)
    category: Literal["family", "social", "work", "organization", "project", "place", "event"]
    symmetric: bool
    sensitivity: Literal["normal", "personal", "sensitive"]
    source_kinds: list[str]
    target_kinds: list[str]


class RelationshipTypeListResponse(_Schema):
    types: list[RelationshipTypeModel]


class RelationshipModel(_Schema):
    """One stored relationship, plus how it reads from the entity it was requested for."""

    id: str
    source: MemorySubjectModel
    type: str
    type_label: str
    target: MemorySubjectModel
    text: str  # as stored: "Mehmet: Ahmet'in kardeşi"
    reading: str | None  # from the requested entity's side (None: only one direction)
    other: MemorySubjectModel | None  # the far end, seen from the requested entity
    status: RelStatusLiteral
    origin: Literal["stated", "requested", "confirmed", "user_edit", "migrated", "inferred"]
    confidence: float
    sensitivity: Literal["normal", "personal", "sensitive"]
    time_text: str | None
    qualifier: str | None
    valid_from: str | None
    valid_to: str | None
    conflict_state: Literal["none", "pending"]
    created_at: str
    updated_at: str


class RelationshipListResponse(_Schema):
    relationships: list[RelationshipModel]


class RelationshipDetailResponse(_Schema):
    relationship: RelationshipModel
    evidence: list[MemoryEvidenceModel]
    previous: list[RelationshipModel]  # the claims this one replaced, newest first


class RelationshipCreateRequest(_Schema):
    source_id: str = Field(pattern=ID)
    type: str = Field(pattern=r"^[a-z_]{1,40}$")
    target_id: str = Field(pattern=ID)
    status: Literal["active", "ended", "planned"] = "active"
    time_text: str | None = Field(default=None, max_length=80)
    qualifier: str | None = Field(default=None, max_length=80)


class RelationshipEditRequest(_Schema):
    type: str = Field(pattern=r"^[a-z_]{1,40}$")
    status: Literal["active", "ended", "planned"]
    time_text: str | None = Field(default=None, max_length=80)
    qualifier: str | None = Field(default=None, max_length=80)


class RelationshipWriteResponse(_Schema):
    created: int
    updated: int
    ended: int
    superseded: int
    inbox: int  # waiting for a decision (e.g. a conflicting kinship)
    dropped: dict[str, int]


class GraphNodeModel(_Schema):
    id: str
    name: str
    kind: str
    is_user: bool
    depth: int


class GraphEdgeModel(_Schema):
    id: str
    source_id: str
    target_id: str
    type: str
    label: str
    status: RelStatusLiteral


class GraphNeighbourhoodResponse(_Schema):
    nodes: list[GraphNodeModel]
    edges: list[GraphEdgeModel]
    truncated: bool


class GraphPathModel(_Schema):
    steps: list[str]  # one line per relationship, from the first entity towards the second
    relationship_ids: list[str]


class GraphPathsResponse(_Schema):
    paths: list[GraphPathModel]


# ----- quality checks (Phase 9) ---------------------------------------------------------------
class QualityFindingModel(_Schema):
    id: str
    kind: Literal["conflict", "duplicate", "stale", "ambiguous_person", "no_evidence", "uncertain"]
    priority: int
    subject: str
    title: str
    memory_ids: list[str]
    entity_ids: list[str]
    values: list[str]


class QualityResponse(_Schema):
    findings: list[QualityFindingModel]


class QualityDismissRequest(_Schema):
    kind: Literal["conflict", "duplicate", "stale", "ambiguous_person", "no_evidence", "uncertain"]
