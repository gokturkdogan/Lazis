"""The personal knowledge import API (Phase 8, ADR-0019): ``/memory/bootstrap``.

    POST   /analyze             the file (name + bytes) → a draft; JSON is ready at once,
                                Markdown/text is read by the model in the background
    GET    ""                   earlier imports (no content)
    GET    /{id}                progress, or the preview: people, items, summary
    POST   /{id}/cancel         stop the analysis now; the draft is deleted
    POST   /{id}/retry          read the failed sections again (explicit, counted)
    POST   /{id}/decisions      decisions on people and items (never "approve everything")
    POST   /{id}/apply          write what was approved — one transaction
    GET    /{id}/undo-plan      what undoing would remove, restore, keep, leave to the user
    POST   /{id}/undo           undo, in one transaction (a second undo changes nothing)
    DELETE /{id}                discard a draft that was not written

No file path crosses the API: the UI reads the file the user picked and sends its bytes. The
file's text is never logged. Every reason a step is refused has its own error code
(``import_<reason>``).
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar, cast

from fastapi import APIRouter

from lazis.api.bootstrap_schemas import (
    BootstrapAnalyzeRequest,
    BootstrapApplyResponse,
    BootstrapBatchModel,
    BootstrapDecisionsRequest,
    BootstrapHistoryResponse,
    BootstrapItemModel,
    BootstrapOptionModel,
    BootstrapPersonModel,
    BootstrapPreviewResponse,
    BootstrapSummaryModel,
    BootstrapUndoPlanResponse,
    BootstrapUndoRequest,
    BootstrapUndoResponse,
    BootstrapUndoStepModel,
)
from lazis.bootstrap import apply as applying
from lazis.bootstrap import files, pipeline, profile, store, undo
from lazis.bootstrap.proposals import USER, label_of
from lazis.conversation import ConversationEngine
from lazis.errors import BootstrapRefusedError, LazisError, MemoryModelUntrustedError
from lazis.memory import relations
from lazis.storage.driver import Connection

T = TypeVar("T")
Q = Callable[[Callable[[Connection], T]], Awaitable[T]]
ANALYZE_PATH = "/memory/bootstrap/analyze"
# The analyse request carries the file: a larger body than other requests, still bounded.
MAX_ANALYZE_BODY = 1_450_000


class _Unavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


def _refusals[T](fn: Callable[[Connection], T]) -> Callable[[Connection], T]:
    """The import's own refusals become their API error (before the generic memory mapping)."""

    def run(c: Connection) -> T:
        try:
            return fn(c)
        except files.FileRejected as exc:
            raise BootstrapRefusedError(f"file_{exc.code}", status=422) from None
        except profile.ProfileError as exc:
            details: dict[str, int | str | list[str]] | None = None
            if exc.line is not None:
                details = {"line": exc.line, "column": exc.column or 0}
            raise BootstrapRefusedError(f"profile_{exc.code}", status=422,
                                        details=details) from None  # fmt: skip
        except store.DecisionError as exc:
            raise BootstrapRefusedError(exc.code) from None
        except applying.ApplyRefused as exc:
            raise BootstrapRefusedError(
                exc.code, details={"items": list(exc.items)} if exc.items else None
            ) from None
        except undo.UndoRefused as exc:
            raise BootstrapRefusedError(exc.code) from None

    return run


def read_file(name: str, data: bytes) -> files.ReadFile:
    try:
        return files.read(name, data)
    except files.FileRejected as exc:
        raise BootstrapRefusedError(f"file_{exc.code}", status=422) from None


def _int_map(d: object) -> dict[str, int]:
    if not isinstance(d, dict):
        return {}
    return {str(k): v for k, v in cast(dict[object, object], d).items() if isinstance(v, int)}


def batch_model(b: store.Batch, running: bool) -> BootstrapBatchModel:
    counts = _int_map(b.counts)
    undone: object = b.counts.get("undo")
    return BootstrapBatchModel(
        id=b.id,
        status=b.status,
        running=running,
        file_name=b.file_name,
        format=b.format,  # type: ignore[arg-type]
        size_bytes=b.size_bytes,
        sections_total=b.sections_total,
        sections_done=b.sections_done,
        sections_failed=b.sections_failed,
        model_calls=b.model_calls,
        error=b.error,
        warnings=list(b.warnings),
        counts=counts,
        undo_counts=_int_map(undone),
        created_at=b.created_at,
        applied_at=b.applied_at,
        undone_at=b.undone_at,
    )


def _ref_label(people: dict[str, store.Person], ref: str | None) -> str:
    if ref is None:
        return ""
    if ref == USER:
        return "Kullanıcı"
    p = people.get(ref)
    return p.label if p is not None else ref


def item_model(c: Connection, b: store.Batch, it: store.Item,
               people: dict[str, store.Person]) -> BootstrapItemModel:  # fmt: skip
    import_id = b.id
    if it.kind == "fact":
        f = it.fact()
        subject, predicate, plabel = _ref_label(people, it.subject_ref), f.predicate, None
        plabel = label_of(f.predicate)
        value, statement, time = f.value, f.statement, f.time
    else:
        r = it.relation()
        t = relations.TYPES.get(r.type)
        subject, predicate = _ref_label(people, it.source_ref), r.type
        plabel = t.label if t is not None else r.type
        value, statement, time = _ref_label(people, it.target_ref), r.statement, r.time
    return BootstrapItemModel(
        id=it.id,
        kind=it.kind,
        category=it.category,
        subject=subject,
        subject_ref=it.subject_ref,
        source_ref=it.source_ref,
        target_ref=it.target_ref,
        predicate=predicate,
        predicate_label=plabel,
        value=value,
        statement=statement,
        time=time,
        section=it.section,
        excerpt=it.excerpt,
        line=it.line,
        method=it.method,  # type: ignore[arg-type]
        confidence=round(it.confidence, 2),
        classification=it.classification,  # type: ignore[arg-type]
        existing=list(it.existing),
        note=it.note,
        decision=it.decision,
        resolution=it.resolution,
        edited_value=it.edited_value,
        blocked=store.blocked(c, import_id, it) if it.decision == "approve" else None,
        result=it.result,
        save_state=store.save_state(b.status, it),
    )


def person_model(p: store.Person, items: int) -> BootstrapPersonModel:
    return BootstrapPersonModel(
        id=p.id,
        name=p.name,
        kind=p.kind,
        relation=p.relation,
        description=p.description,
        match=p.match,  # type: ignore[arg-type]
        options=[
            BootstrapOptionModel(id=o["id"], label=o["label"], stored=o.get("kind") != "import")
            for o in p.options
        ],
        suggested_id=p.suggested_id,
        note=p.note,
        decision=p.decision,
        link_id=p.link_id,
        section=p.section,
        items=items,
    )


def _summary(s: dict[str, Any]) -> BootstrapSummaryModel:
    return BootstrapSummaryModel(**{k: s[k] for k in BootstrapSummaryModel.model_fields})


_STEP_TABLE = {"memories": "memory", "memory_relationships": "relationship",
               "memory_entities": "person"}  # fmt: skip


def plan_model(p: undo.Plan) -> BootstrapUndoPlanResponse:
    return BootstrapUndoPlanResponse(
        import_id=p.import_id,
        already_undone=p.already_undone,
        steps=[
            BootstrapUndoStepModel(
                table=_STEP_TABLE[s.table],  # type: ignore[arg-type]
                target_id=s.target_id,
                action=s.action,
                label=s.label,
                reason=s.reason,
            )
            for s in p.steps
        ],
        counts=p.counts(),
    )


def decode_content(body: BootstrapAnalyzeRequest) -> bytes:
    try:
        return base64.b64decode(body.content_base64, validate=True)
    except (binascii.Error, ValueError):
        raise BootstrapRefusedError("file_encoding", status=422) from None


def register_bootstrap_routes(
    router: APIRouter, q: Q[Any], get_engine: Callable[[], ConversationEngine | None]
) -> None:
    def engine() -> ConversationEngine:
        e = get_engine()
        if e is None:
            raise _Unavailable("engine not available")
        return e

    def running(import_id: str) -> bool:
        e = get_engine()
        return e is not None and e.bootstrap.running(import_id)

    async def batch(import_id: str) -> BootstrapBatchModel:
        b = await q(lambda c: store.get_batch(c, import_id))
        return batch_model(b, running(import_id))

    async def preview(import_id: str) -> BootstrapPreviewResponse:
        def read(c: Connection) -> BootstrapPreviewResponse:
            b = store.get_batch(c, import_id)
            ps = store.people(c, import_id)
            its = store.items(c, import_id)
            by_id = {p.id: p for p in ps}
            uses: dict[str, int] = {}
            for it in its:
                for r in set(it.refs()):
                    uses[r] = uses.get(r, 0) + 1
            return BootstrapPreviewResponse(
                batch=batch_model(b, running(import_id)),
                people=[person_model(p, uses.get(p.id, 0)) for p in ps],
                items=[item_model(c, b, it, by_id) for it in its],
                summary=_summary(store.summary(c, import_id)),
            )

        return await q(read)

    @router.post("/bootstrap/analyze", response_model=BootstrapBatchModel)
    async def analyze(body: BootstrapAnalyzeRequest) -> BootstrapBatchModel:  # pyright: ignore[reportUnusedFunction]
        f = read_file(body.file_name, decode_content(body))
        if f.format == "json":
            iid = await q(_refusals(lambda c: pipeline.start_json(c, f)))
            return await batch(iid)
        e = engine()
        model = e.bootstrap.model()
        if model is None:
            raise MemoryModelUntrustedError("the primary model is not trusted to learn")
        iid = await q(lambda c: store.create_batch(c, f, model=model))
        e.bootstrap.start(iid)
        return await batch(iid)

    @router.get("/bootstrap", response_model=BootstrapHistoryResponse)
    async def history() -> BootstrapHistoryResponse:  # pyright: ignore[reportUnusedFunction]
        bs = await q(lambda c: store.list_batches(c, limit=50))
        return BootstrapHistoryResponse(batches=[batch_model(b, running(b.id)) for b in bs])

    @router.get("/bootstrap/{import_id}", response_model=BootstrapPreviewResponse)
    async def get_import(import_id: str) -> BootstrapPreviewResponse:  # pyright: ignore[reportUnusedFunction]
        return await preview(import_id)

    @router.post("/bootstrap/{import_id}/cancel", response_model=BootstrapBatchModel)
    async def cancel(import_id: str) -> BootstrapBatchModel:  # pyright: ignore[reportUnusedFunction]
        b = await q(lambda c: store.get_batch(c, import_id))
        if b.status not in ("analyzing", "ready", "failed"):
            raise BootstrapRefusedError("not_cancellable")
        await engine().bootstrap.cancel(import_id)
        return await batch(import_id)

    @router.post("/bootstrap/{import_id}/retry", response_model=BootstrapBatchModel)
    async def retry(import_id: str) -> BootstrapBatchModel:  # pyright: ignore[reportUnusedFunction]
        e = engine()
        if e.bootstrap.running(import_id):
            raise BootstrapRefusedError("not_retryable")
        if e.bootstrap.model() is None:
            raise MemoryModelUntrustedError("the primary model is not trusted to learn")
        await q(_refusals(lambda c: store.retry_failed(c, import_id)))
        e.bootstrap.start(import_id)
        return await batch(import_id)

    @router.post("/bootstrap/{import_id}/decisions", response_model=BootstrapPreviewResponse)
    async def decide(import_id: str, body: BootstrapDecisionsRequest) -> BootstrapPreviewResponse:  # pyright: ignore[reportUnusedFunction]
        def run(c: Connection) -> None:
            # People first: what an item is compared with depends on them.
            for p in body.people:
                store.decide_person(c, import_id, p.id, p.decision, p.link_id)
            for it in body.items:
                store.decide_item(c, import_id, it.id, it.decision, resolution=it.resolution,
                                  edited_value=it.edited_value)  # fmt: skip

        await q(_refusals(run))
        return await preview(import_id)

    @router.post("/bootstrap/{import_id}/apply", response_model=BootstrapApplyResponse)
    async def apply(import_id: str) -> BootstrapApplyResponse:  # pyright: ignore[reportUnusedFunction]
        def run(c: Connection) -> applying.ApplyResult:
            try:
                return applying.apply(c, import_id)
            except applying.ApplyRefused as exc:
                if exc.code == "memory_changed":
                    store.refresh(c, import_id)  # the preview shows what changed
                raise

        r = await q(_refusals(run))
        return BootstrapApplyResponse(batch=await batch(import_id), change_set_id=r.change_set_id)

    @router.get("/bootstrap/{import_id}/undo-plan", response_model=BootstrapUndoPlanResponse)
    async def undo_plan(import_id: str) -> BootstrapUndoPlanResponse:  # pyright: ignore[reportUnusedFunction]
        return plan_model(await q(_refusals(lambda c: undo.plan(c, import_id))))

    @router.post("/bootstrap/{import_id}/undo", response_model=BootstrapUndoResponse)
    async def do_undo(import_id: str, body: BootstrapUndoRequest) -> BootstrapUndoResponse:  # pyright: ignore[reportUnusedFunction]
        chosen = frozenset(body.restore)
        p, cs = await q(_refusals(lambda c: undo.undo(c, import_id, restore=chosen)))
        return BootstrapUndoResponse(batch=await batch(import_id), plan=plan_model(p),
                                     change_set_id=cs)  # fmt: skip

    @router.delete("/bootstrap/{import_id}", response_model=BootstrapBatchModel)
    async def discard(import_id: str) -> BootstrapBatchModel:  # pyright: ignore[reportUnusedFunction]
        if running(import_id):
            raise BootstrapRefusedError("still_running")
        await q(_refusals(lambda c: pipeline.discard(c, import_id)))
        return await batch(import_id)
