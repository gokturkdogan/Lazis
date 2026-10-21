"""API v1 schemas for the personal knowledge import (Phase 8, ADR-0019). Exported to OpenAPI →
TypeScript types.

Nothing here carries a file path: the UI reads the file the user picked and sends its bytes.
Every decision starts ``pending``; there is no "approve everything" request.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from lazis.api.memory_schemas import ID, _Schema  # pyright: ignore[reportPrivateUsage]

# The largest profile file is 1 MB (lazis.bootstrap.files.MAX_FILE_BYTES); base64 is 4/3 of it.
MAX_CONTENT_BASE64 = 1_400_000

BatchStatus = Literal["analyzing", "ready", "failed", "cancelled", "applied", "undone", "discarded"]
PersonDecision = Literal["pending", "create", "link", "unresolved", "reject"]
ItemDecision = Literal["pending", "approve", "reject", "hold"]
Resolution = Literal["keep_old", "update", "keep_both"]
Classification = Literal[
    "new", "exact_duplicate", "possible_duplicate", "conflict", "temporal_update",
    "ambiguous_entity", "insufficient_evidence", "excluded",
]  # fmt: skip


class BootstrapAnalyzeRequest(_Schema):
    file_name: str = Field(min_length=1, max_length=255)
    content_base64: str = Field(min_length=1, max_length=MAX_CONTENT_BASE64)


class BootstrapBatchModel(_Schema):
    id: str
    status: BatchStatus
    running: bool  # the model is reading sections right now
    file_name: str
    format: Literal["markdown", "text", "json"]
    size_bytes: int
    sections_total: int
    sections_done: int
    sections_failed: int
    model_calls: int
    error: str | None
    warnings: list[str]
    counts: dict[str, int]  # what the write did (applied/undone), from the transaction
    undo_counts: dict[str, int]
    created_at: str
    applied_at: str | None
    undone_at: str | None


class BootstrapHistoryResponse(_Schema):
    batches: list[BootstrapBatchModel]


class BootstrapOptionModel(_Schema):
    id: str
    label: str
    stored: bool  # a person already in memory (False: another person in this file)


class BootstrapPersonModel(_Schema):
    id: str
    name: str
    kind: str
    relation: str | None
    description: str | None
    match: Literal["new", "existing", "ambiguous"]
    options: list[BootstrapOptionModel]
    suggested_id: str | None  # only a suggestion: nothing is linked without a decision
    note: str | None
    decision: PersonDecision
    link_id: str | None
    section: str
    items: int


class BootstrapItemModel(_Schema):
    id: str
    kind: Literal["fact", "relationship"]
    category: str
    subject: str  # who it is about, as the user reads it
    subject_ref: str | None  # "user" or a proposed person id
    source_ref: str | None
    target_ref: str | None
    predicate: str | None
    predicate_label: str | None
    value: str
    statement: str
    time: str | None
    section: str
    excerpt: str | None
    line: int | None
    method: Literal["json", "gemma"]
    confidence: float  # shown, never a reason to write
    classification: Classification
    existing: list[str]
    note: str | None
    decision: ItemDecision
    resolution: Resolution | None
    edited_value: str | None
    blocked: str | None  # why an approved item cannot be written now
    result: str | None  # what the write did (None: not written yet)
    save_state: Literal["save_succeeded", "save_failed", "save_cancelled", "save_rejected",
                        "save_pending_approval"]  # fmt: skip


class BootstrapSummaryModel(_Schema):
    analyzed: int
    approved: int
    writable: int
    blocked: int
    rejected: int
    held: int
    pending: int
    excluded: int
    updates: int
    people_new: int
    people_linked: int
    people_unresolved: int
    people_rejected: int
    people_pending: int
    by_category: dict[str, int]


class BootstrapPreviewResponse(_Schema):
    batch: BootstrapBatchModel
    people: list[BootstrapPersonModel]
    items: list[BootstrapItemModel]
    summary: BootstrapSummaryModel


class BootstrapPersonDecision(_Schema):
    id: str = Field(pattern=ID)
    decision: PersonDecision
    link_id: str | None = Field(default=None, pattern=ID)


class BootstrapItemDecision(_Schema):
    id: str = Field(pattern=ID)
    decision: ItemDecision
    resolution: Resolution | None = None
    edited_value: str | None = Field(default=None, max_length=200)


class BootstrapDecisionsRequest(_Schema):
    people: list[BootstrapPersonDecision] = Field(
        default_factory=list[BootstrapPersonDecision], max_length=500
    )
    items: list[BootstrapItemDecision] = Field(
        default_factory=list[BootstrapItemDecision], max_length=2000
    )


class BootstrapApplyResponse(_Schema):
    batch: BootstrapBatchModel
    change_set_id: str


class BootstrapUndoStepModel(_Schema):
    table: Literal["memory", "relationship", "person"]
    target_id: str
    action: Literal["remove", "restore", "keep", "decide", "remove_evidence", "gone"]
    label: str
    reason: str


class BootstrapUndoPlanResponse(_Schema):
    import_id: str
    already_undone: bool
    steps: list[BootstrapUndoStepModel]
    counts: dict[str, int]


class BootstrapUndoRequest(_Schema):
    # Records the plan left to the user ("decide") that should be restored anyway.
    restore: list[str] = Field(default_factory=list[str], max_length=500)


class BootstrapUndoResponse(_Schema):
    batch: BootstrapBatchModel
    plan: BootstrapUndoPlanResponse
    change_set_id: str | None  # None: it was already undone, nothing changed
