"""The memory API (Phase 6): view, search, add, edit, forget, people/projects, pending
decisions, starting-profile import.

Every write goes through ``lazis.memory.service`` (the same checks as learning from chat:
secrets and instruction-like text are refused, history is kept, forgetting purges the index
and history content). Deleting a person/project requires ``confirm=true`` — the UI asks
first. Responses never include raw inbox payloads or evidence beyond the stored quote.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, TypeVar, cast

from fastapi import APIRouter, Query

from lazis.api.bootstrap import register_bootstrap_routes
from lazis.api.graph import register_graph_routes
from lazis.api.memory_schemas import (
    ApplyResultResponse,
    EntityEditRequest,
    EntityMergeRequest,
    EntitySplitRequest,
    ForgetResultResponse,
    ImportApplyRequest,
    ImportItemModel,
    ImportPreviewRequest,
    ImportPreviewResponse,
    InboxOptionModel,
    InboxResolveRequest,
    MemoryCreateRequest,
    MemoryEditRequest,
    MemoryEntityDetailResponse,
    MemoryEntityListResponse,
    MemoryEntityModel,
    MemoryEvidenceModel,
    MemoryInboxItemModel,
    MemoryInboxResponse,
    MemoryListResponse,
    MemoryOverviewResponse,
    MemoryRecordDetailResponse,
    MemoryRecordModel,
    MemorySubjectModel,
    PredicateListResponse,
    PredicateModel,
)
from lazis.conversation import ConversationEngine
from lazis.errors import LazisError, MemoryNotFoundError, MemoryRequestError, StorageError
from lazis.memory import importer, registry, service
from lazis.memory import repository as repo
from lazis.memory.models import ApplyReport, Entity, EntityRef, InboxItem, Memory
from lazis.memory.service import NotFound
from lazis.storage.database import Database
from lazis.storage.driver import Connection, DatabaseError

T = TypeVar("T")


class _MemoryUnavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


def _subject(conn: Connection, subject_id: str | None) -> MemorySubjectModel | None:
    if subject_id is None:
        return None
    e = repo.get_entity(conn, subject_id)
    if e is None:
        return None
    return MemorySubjectModel(id=e.id, kind=e.kind, name=e.name, relation=e.relation)


def record_model(conn: Connection, m: Memory) -> MemoryRecordModel:
    p = registry.get(m.predicate)
    return MemoryRecordModel(
        id=m.id,
        kind=m.kind,
        predicate=m.predicate,
        predicate_label=p.label if p else m.predicate,
        subject=_subject(conn, m.subject_id),
        value=m.value,
        content=m.content,
        status=m.status,
        origin=m.origin,
        confidence=m.confidence,
        importance=m.importance,
        sensitivity=m.sensitivity,
        sensitivity_category=m.sensitivity_category,
        conflict_state=m.conflict_state,
        event_time=m.event_time,
        valid_from=m.valid_from,
        valid_to=m.valid_to,
        supersedes_id=m.supersedes_id,
        recall_count=m.recall_count,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


def entity_model(conn: Connection, e: Entity) -> MemoryEntityModel:
    count = len(repo.memories_for_subject(conn, e.id))
    return MemoryEntityModel(
        id=e.id,
        kind=e.kind,
        name=e.name,
        relation=e.relation,
        description=e.description,
        aliases=[a for a in e.aliases if a != e.name],
        records=count,
        updated_at=e.updated_at,
    )


def _str_or_none(v: object) -> str | None:
    return v if isinstance(v, str) else None


def inbox_model(item: InboxItem) -> MemoryInboxItemModel:
    payload: dict[str, Any] = item.payload
    raw = payload.get("candidate") if item.type != "import_batch" else None
    cand: dict[str, Any] = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    p = registry.get(str(cand.get("predicate", "")))
    raw_ent = cand.get("entity")
    ent: dict[str, Any] = cast(dict[str, Any], raw_ent) if isinstance(raw_ent, dict) else {}
    subject: str | None = None
    if cand:
        subject = "Kullanıcı"
        name = _str_or_none(ent.get("name"))
        if cand.get("about") == "entity" and name:
            relation = _str_or_none(ent.get("relation"))
            subject = f"{name} ({relation})" if relation else name
    raw_options = payload.get("options")
    options = cast(list[dict[str, Any]], raw_options) if isinstance(raw_options, list) else []
    if payload.get("target") == "relationship":
        rel_raw = payload.get("relation")
        rel: dict[str, Any] = cast(dict[str, Any], rel_raw) if isinstance(rel_raw, dict) else {}
        labels = payload.get("existing_labels")
        return MemoryInboxItemModel(
            id=item.id,
            type=item.type,
            summary=item.summary,
            created_at=item.created_at,
            predicate_label="İlişki",
            value=None,
            subject=None,
            options=[
                InboxOptionModel(id=str(o.get("id")), label=str(o.get("label"))) for o in options
            ],
            existing=[str(x) for x in cast(list[Any], labels)] if isinstance(labels, list) else [],
            category=_str_or_none(payload.get("category")),
            about="relationship",
            relationship=_str_or_none(rel.get("statement")) or item.summary,
        )
    if item.type == "destructive" and payload.get("action") == "merge":
        return MemoryInboxItemModel(
            id=item.id,
            type=item.type,
            summary=item.summary,
            created_at=item.created_at,
            predicate_label=None,
            value=None,
            subject=None,
            options=[],
            existing=[],
            category=None,
            about="merge",
        )
    return MemoryInboxItemModel(
        id=item.id,
        type=item.type,
        summary=item.summary,
        created_at=item.created_at,
        predicate_label=p.label if p else None,
        value=_str_or_none(cand.get("value")),
        subject=subject,
        options=[InboxOptionModel(id=str(o.get("id")), label=str(o.get("label"))) for o in options],
        existing=[],
        category=_str_or_none(payload.get("category")),
    )


def apply_result(r: ApplyReport) -> ApplyResultResponse:
    return ApplyResultResponse(
        created=len(r.created),
        updated=len(r.updated),
        superseded=len(r.superseded),
        inbox=len(r.inbox),
        entities_created=len(r.entities_created),
        dropped=dict(r.dropped),
    )


def build_memory_router(
    prefix: str,
    get_db: Callable[[], Database | None],
    get_engine: Callable[[], ConversationEngine | None],
) -> APIRouter:
    router = APIRouter(prefix=f"{prefix}/memory")

    async def q(fn: Callable[[Connection], T]) -> T:
        db = get_db()
        if db is None:
            raise _MemoryUnavailable("storage not available")
        try:
            return await db.run(fn)
        except LazisError:
            raise
        except NotFound:
            raise MemoryNotFoundError("memory item not found") from None
        except (ValueError, KeyError):
            raise MemoryRequestError("memory request not possible") from None
        except DatabaseError as exc:
            raise StorageError(f"database error ({exc.__class__.__name__})") from None

    register_graph_routes(router, q)
    register_bootstrap_routes(router, q, get_engine)

    # ----- overview and vocabulary -----------------------------------------------------
    @router.get("/overview", response_model=MemoryOverviewResponse)
    async def overview() -> MemoryOverviewResponse:  # pyright: ignore[reportUnusedFunction]
        engine = get_engine()

        def read(c: Connection) -> MemoryOverviewResponse:
            return MemoryOverviewResponse(
                memories=repo.count_memories(c),
                entities=len(repo.list_entities(c, limit=10_000)),
                inbox_open=len([i for i in repo.list_inbox(c) if i.type != "import_batch"]),
                jobs=repo.job_counts(c),
                auto_extract=engine.learner.cfg.auto_extract if engine else False,
                trusted_models=list(engine.learner.cfg.trusted_models) if engine else [],
            )

        return await q(read)

    @router.get("/predicates", response_model=PredicateListResponse)
    async def predicates() -> PredicateListResponse:  # pyright: ignore[reportUnusedFunction]
        return PredicateListResponse(
            predicates=[
                PredicateModel(
                    key=p.key,
                    label=p.label,
                    kind=p.kind,
                    cardinality=p.cardinality,
                    sensitivity=p.sensitivity,
                    subjects=list(p.subjects),
                )
                for p in registry.PREDICATES.values()
            ]
        )

    # ----- records ---------------------------------------------------------------------
    @router.get("/records", response_model=MemoryListResponse)
    async def list_records(  # pyright: ignore[reportUnusedFunction]
        q_: Annotated[str | None, Query(alias="q", max_length=200)] = None,
        kind: Annotated[str | None, Query(pattern=r"^[a-z_]{1,20}$")] = None,
        subject_id: Annotated[str | None, Query(max_length=64)] = None,
        user_only: bool = False,
        status: Annotated[str, Query(pattern=r"^(active|superseded|all)$")] = "active",
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
    ) -> MemoryListResponse:
        def read(c: Connection) -> MemoryListResponse:
            rows = repo.list_memories(
                c,
                kind=kind,
                subject_id=subject_id,
                user_only=user_only,
                status=None if status == "all" else status,
                query=q_,
                limit=limit + 1,
                offset=offset,
            )
            return MemoryListResponse(
                records=[record_model(c, m) for m in rows[:limit]], has_more=len(rows) > limit
            )

        return await q(read)

    @router.post("/records", response_model=ApplyResultResponse)
    async def add_record(body: MemoryCreateRequest) -> ApplyResultResponse:  # pyright: ignore[reportUnusedFunction]
        new = None
        if body.new_entity is not None:
            new = EntityRef(body.new_entity.name, body.new_entity.kind, body.new_entity.relation)
        report = await q(
            lambda c: service.add_memory(
                c,
                predicate=body.predicate,
                value=body.value,
                statement=body.statement,
                entity_id=body.entity_id,
                new_entity=new,
            )
        )
        return apply_result(report)

    @router.get("/records/{memory_id}", response_model=MemoryRecordDetailResponse)
    async def record_detail(memory_id: str) -> MemoryRecordDetailResponse:  # pyright: ignore[reportUnusedFunction]
        def read(c: Connection) -> MemoryRecordDetailResponse:
            m, evidence, previous = service.record_detail(c, memory_id)
            return MemoryRecordDetailResponse(
                record=record_model(c, m),
                evidence=[
                    MemoryEvidenceModel(
                        source_type=e.source_type,
                        source_ref=e.source_ref,
                        quote=e.quote,
                        created_at=e.created_at,
                    )
                    for e in evidence
                ],
                previous=[record_model(c, p) for p in previous],
            )

        return await q(read)

    @router.patch("/records/{memory_id}", response_model=MemoryRecordModel)
    async def edit_record(memory_id: str, body: MemoryEditRequest) -> MemoryRecordModel:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> MemoryRecordModel:
            m = service.edit_memory(c, memory_id, value=body.value, content=body.statement)
            return record_model(c, m)

        return await q(write)

    @router.delete("/records/{memory_id}", response_model=ForgetResultResponse)
    async def forget_record(memory_id: str) -> ForgetResultResponse:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> ForgetResultResponse:
            if repo.get_memory(c, memory_id) is None:
                raise NotFound("memory not found")
            r = service.forget_memories(c, [memory_id])
            return ForgetResultResponse(memories=r.memories, entities=r.entities)

        return await q(write)

    # ----- people and projects ---------------------------------------------------------
    @router.get("/entities", response_model=MemoryEntityListResponse)
    async def list_entities(  # pyright: ignore[reportUnusedFunction]
        kind: Annotated[
            str | None, Query(pattern=r"^(person|project|organization|place|event|group|thing)$")
        ] = None,
        q_: Annotated[str | None, Query(alias="q", max_length=80)] = None,
    ) -> MemoryEntityListResponse:
        def read(c: Connection) -> MemoryEntityListResponse:
            rows = repo.list_entities(c, kind=kind, query=q_, limit=500)
            return MemoryEntityListResponse(entities=[entity_model(c, e) for e in rows])

        return await q(read)

    @router.get("/entities/{entity_id}", response_model=MemoryEntityDetailResponse)
    async def entity_detail(entity_id: str) -> MemoryEntityDetailResponse:  # pyright: ignore[reportUnusedFunction]
        def read(c: Connection) -> MemoryEntityDetailResponse:
            e = repo.get_entity(c, entity_id)
            if e is None or e.status != "active":
                raise NotFound("entity not found")
            rows = repo.memories_for_subject(c, e.id, statuses=("active", "superseded"))
            return MemoryEntityDetailResponse(
                entity=entity_model(c, e), records=[record_model(c, m) for m in rows]
            )

        return await q(read)

    @router.patch("/entities/{entity_id}", response_model=MemoryEntityModel)
    async def edit_entity(entity_id: str, body: EntityEditRequest) -> MemoryEntityModel:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> MemoryEntityModel:
            e = service.update_entity(
                c, entity_id, name=body.name, relation=body.relation, description=body.description
            )
            return entity_model(c, e)

        return await q(write)

    @router.post("/entities/{entity_id}/merge", response_model=MemoryEntityModel)
    async def merge_entity(entity_id: str, body: EntityMergeRequest) -> MemoryEntityModel:  # pyright: ignore[reportUnusedFunction]
        return await q(
            lambda c: entity_model(c, service.merge_entities(c, entity_id, body.other_id))
        )

    @router.post("/entities/{entity_id}/split", response_model=MemoryEntityModel)
    async def split_entity(entity_id: str, body: EntitySplitRequest) -> MemoryEntityModel:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> MemoryEntityModel:
            e = service.split_entity(
                c, entity_id, body.memory_ids, name=body.name, relation=body.relation
            )
            return entity_model(c, e)

        return await q(write)

    @router.delete("/entities/{entity_id}", response_model=ForgetResultResponse)
    async def forget_entity(entity_id: str, confirm: bool = False) -> ForgetResultResponse:  # pyright: ignore[reportUnusedFunction]
        if not confirm:
            raise MemoryRequestError("deleting a person or project needs confirm=true")
        r = await q(lambda c: service.forget_entity(c, entity_id))
        return ForgetResultResponse(memories=r.memories, entities=r.entities)

    # ----- pending decisions -----------------------------------------------------------
    @router.get("/inbox", response_model=MemoryInboxResponse)
    async def inbox() -> MemoryInboxResponse:  # pyright: ignore[reportUnusedFunction]
        def read(c: Connection) -> MemoryInboxResponse:
            items: list[MemoryInboxItemModel] = []
            for it in repo.list_inbox(c):
                if it.type == "import_batch":
                    continue
                model = inbox_model(it)
                if it.type == "conflict" and model.about == "memory":
                    old = [repo.get_memory(c, i) for i in it.payload.get("existing", [])]
                    model = model.model_copy(update={"existing": [m.value for m in old if m]})
                items.append(model)
            return MemoryInboxResponse(items=items)

        return await q(read)

    @router.post("/inbox/{item_id}/resolve", response_model=ApplyResultResponse)
    async def resolve(item_id: str, body: InboxResolveRequest) -> ApplyResultResponse:  # pyright: ignore[reportUnusedFunction]
        def write(c: Connection) -> ApplyResultResponse:
            item = repo.get_inbox(c, item_id)
            if item is not None and item.type == "destructive" and body.choice == "approve":
                from lazis.memory import commands

                commands.confirm(c, item_id)
                return apply_result(ApplyReport())
            return apply_result(service.resolve_inbox(c, item_id, body.choice))

        return await q(write)

    # ----- starting-profile import -----------------------------------------------------
    def _preview(
        batch_id: str, items: list[importer.PreviewItem], errors: list[str]
    ) -> ImportPreviewResponse:
        return ImportPreviewResponse(
            batch_id=batch_id,
            items=[
                ImportItemModel(
                    index=it.index,
                    status=it.status,
                    subject=it.subject,
                    predicate=it.candidate.predicate,
                    predicate_label=str(it.view()["predicate_label"]),
                    value=it.candidate.value,
                    statement=it.candidate.statement,
                    reason=it.reason,
                    sensitive=it.sensitive,
                    options=[InboxOptionModel(id=o["id"], label=o["label"]) for o in it.options],
                    existing=it.existing,
                )
                for it in items
            ],
            errors=errors,
        )

    @router.post("/import/preview", response_model=ImportPreviewResponse)
    async def import_preview(body: ImportPreviewRequest) -> ImportPreviewResponse:  # pyright: ignore[reportUnusedFunction]
        errors: list[str] = []
        if body.format == "json":
            try:
                candidates, errors = importer.parse_json(body.content)
            except importer.ImportFormatError:
                raise MemoryRequestError("import file is not in the expected format") from None
        else:
            engine = get_engine()
            if engine is None:
                raise _MemoryUnavailable("engine not available")
            candidates = await engine.import_text_candidates(body.content)
        source = body.format
        batch_id, items = await q(lambda c: importer.create_batch(c, candidates, source=source))
        return _preview(batch_id, items, errors)

    @router.get("/import/{batch_id}", response_model=ImportPreviewResponse)
    async def import_batch(batch_id: str) -> ImportPreviewResponse:  # pyright: ignore[reportUnusedFunction]
        items = await q(lambda c: importer.batch_preview(c, batch_id))
        return _preview(batch_id, items, [])

    @router.post("/import/{batch_id}/apply", response_model=ApplyResultResponse)
    async def import_apply(batch_id: str, body: ImportApplyRequest) -> ApplyResultResponse:  # pyright: ignore[reportUnusedFunction]
        try:
            selections = {int(k): v for k, v in body.selections.items()}
        except ValueError:
            raise MemoryRequestError("selection keys must be item indexes") from None
        return apply_result(await q(lambda c: importer.apply_batch(c, batch_id, selections)))

    @router.delete("/import/{batch_id}", response_model=ForgetResultResponse)
    async def import_discard(batch_id: str) -> ForgetResultResponse:  # pyright: ignore[reportUnusedFunction]
        await q(lambda c: importer.discard_batch(c, batch_id))
        return ForgetResultResponse(memories=0, entities=0)

    return router
