"""API v1 schemas for personal memory (Phase 6). Exported to OpenAPI → TypeScript types."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ID = r"^[0-9A-Za-z_-]{1,64}$"


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class MemorySubjectModel(_Schema):
    id: str
    kind: Literal["person", "project", "organization", "place", "thing"]
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


class MemoryEvidenceModel(_Schema):
    source_type: Literal["message", "import", "user_edit", "confirmation"]
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
    kind: Literal["person", "project", "organization", "place", "thing"]
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
    kind: Literal["person", "project", "organization", "place", "thing"] = "person"


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
