"""Persistent conversations (Phase 3): list, open, page, rename, delete, turns, pre-warming.

The API layer only maps HTTP to the conversation engine; all rules (persistence, context
budget, compaction, cancellation) live in :mod:`lazis.conversation`. Streams are NDJSON over
the existing authenticated HTTP API (the backend still refuses WebSocket upgrades):

``start`` → ``status``… → ``delta``… → ``done`` | ``cancelled`` | ``error``

Message content never appears in logs or in error messages.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Path, Query
from fastapi.responses import StreamingResponse

from lazis.api.schemas import (
    ULID_PATTERN,
    ActivityResponse,
    ContextInfoModel,
    ConversationDetailResponse,
    ConversationListResponse,
    ConversationModel,
    DeleteConversationResponse,
    MessageModel,
    MessagePageResponse,
    PrepareRequest,
    PrepareResponse,
    RenameConversationRequest,
    TurnCancelRequest,
    TurnCancelResponse,
    TurnSubmitRequest,
)
from lazis.conversation import ConversationEngine, TurnRequest
from lazis.conversation.engine import conversation_view, message_view
from lazis.errors import LazisError

ConversationId = Annotated[str, Path(pattern=ULID_PATTERN)]


class _EngineUnavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


def _line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def build_conversation_router(
    prefix: str, get_engine: Callable[[], ConversationEngine | None]
) -> APIRouter:
    router = APIRouter(prefix=prefix)

    def engine() -> ConversationEngine:
        found = get_engine()
        if found is None:
            raise _EngineUnavailable("conversation engine not available")
        return found

    @router.get("/conversations", response_model=ConversationListResponse)
    async def list_conversations(  # pyright: ignore[reportUnusedFunction]
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
        cursor: Annotated[str | None, Query(max_length=128)] = None,
    ) -> ConversationListResponse:
        items, next_cursor = await engine().list_conversations(limit=limit, cursor=cursor)
        return ConversationListResponse(
            conversations=[ConversationModel(**conversation_view(c)) for c in items],
            next_cursor=next_cursor,
        )

    @router.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
    async def get_conversation(conversation_id: ConversationId) -> ConversationDetailResponse:  # pyright: ignore[reportUnusedFunction]
        eng = engine()
        conv = await eng.get_conversation(conversation_id)
        info = await eng.context_info(conversation_id)
        return ConversationDetailResponse(
            conversation=ConversationModel(**conversation_view(conv)),
            context=ContextInfoModel(**info),
        )

    @router.get("/conversations/{conversation_id}/messages", response_model=MessagePageResponse)
    async def list_messages(  # pyright: ignore[reportUnusedFunction]
        conversation_id: ConversationId,
        before_seq: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> MessagePageResponse:
        rows, has_more = await engine().messages(
            conversation_id, before_seq=before_seq, limit=limit
        )
        return MessagePageResponse(
            messages=[MessageModel(**message_view(m)) for m in rows], has_more=has_more
        )

    @router.patch("/conversations/{conversation_id}", response_model=ConversationModel)
    async def rename_conversation(  # pyright: ignore[reportUnusedFunction]
        conversation_id: ConversationId, body: RenameConversationRequest
    ) -> ConversationModel:
        conv = await engine().rename(conversation_id, body.title)
        return ConversationModel(**conversation_view(conv))

    @router.delete("/conversations/{conversation_id}", response_model=DeleteConversationResponse)
    async def delete_conversation(  # pyright: ignore[reportUnusedFunction]
        conversation_id: ConversationId,
    ) -> DeleteConversationResponse:
        removed = await engine().delete(conversation_id)
        return DeleteConversationResponse(deleted=True, **removed)

    @router.post(
        "/conversations/{conversation_id}/context/reset", response_model=ConversationDetailResponse
    )
    async def reset_context(conversation_id: ConversationId) -> ConversationDetailResponse:  # pyright: ignore[reportUnusedFunction]
        eng = engine()
        await eng.reset_context(conversation_id)
        conv = await eng.get_conversation(conversation_id)
        return ConversationDetailResponse(
            conversation=ConversationModel(**conversation_view(conv)),
            context=ContextInfoModel(**await eng.context_info(conversation_id)),
        )

    @router.post("/turns")
    async def submit_turn(body: TurnSubmitRequest) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        eng = engine()
        # Validation, persistence of the user message and every refusal (busy, duplicate,
        # unknown conversation, missing model) happen before the stream starts, so they
        # arrive as proper HTTP errors.
        handle = await eng.begin_turn(
            TurnRequest(
                conversation_id=body.conversation_id,
                client_id=body.client_id,
                content=body.content,
                model=body.model,
            )
        )

        async def events() -> AsyncIterator[bytes]:
            async for event in eng.events(handle):
                yield _line(event)

        return StreamingResponse(events(), media_type="application/x-ndjson")

    @router.post("/turns/cancel", response_model=TurnCancelResponse)
    async def cancel_turn(body: TurnCancelRequest) -> TurnCancelResponse:  # pyright: ignore[reportUnusedFunction]
        return TurnCancelResponse(cancelled=engine().cancel_turn(body.client_id))

    @router.post("/chat/prepare", response_model=PrepareResponse)
    async def prepare(body: PrepareRequest) -> PrepareResponse:  # pyright: ignore[reportUnusedFunction]
        result = await engine().prepare(body.conversation_id, body.model)
        return PrepareResponse(**result)

    @router.get("/chat/activity", response_model=ActivityResponse)
    async def activity() -> ActivityResponse:  # pyright: ignore[reportUnusedFunction]
        return ActivityResponse(**engine().activity())

    return router
