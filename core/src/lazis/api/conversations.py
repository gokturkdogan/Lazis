"""The assistant API (Phase 3, ADR-0011): one timeline, turns, cancel, pre-warming.

The user talks to one assistant. Technical sessions exist only inside the engine: turns go to
the active session, the timeline spans all sessions. There is deliberately **no** endpoint to
list, rename, switch or delete sessions or conversations: nothing reachable over the API can
delete history. The API layer only maps HTTP to the conversation engine. Streams are NDJSON
over the authenticated HTTP API (WebSocket upgrades stay refused):

``start`` → ``status``… → ``delta``… → ``done`` | ``cancelled`` | ``error``

Message content never appears in logs or in error messages.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from lazis.api.schemas import (
    ActivityResponse,
    AssistantStateResponse,
    DiagnosticsResponse,
    MessageModel,
    PrepareRequest,
    PrepareResponse,
    TimelinePageResponse,
    TurnCancelRequest,
    TurnCancelResponse,
    TurnSubmitRequest,
)
from lazis.conversation import ConversationEngine, TurnRequest
from lazis.conversation.engine import message_view
from lazis.errors import LazisError


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

    @router.get("/assistant", response_model=AssistantStateResponse)
    async def assistant_state() -> AssistantStateResponse:  # pyright: ignore[reportUnusedFunction]
        return AssistantStateResponse(**await engine().assistant_state())

    @router.get("/timeline", response_model=TimelinePageResponse)
    async def timeline(  # pyright: ignore[reportUnusedFunction]
        before: Annotated[int | None, Query(ge=1)] = None,
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> TimelinePageResponse:
        rows, has_more = await engine().timeline(before_timeline_seq=before, limit=limit)
        return TimelinePageResponse(
            messages=[MessageModel(**message_view(m)) for m in rows], has_more=has_more
        )

    @router.post("/turns")
    async def submit_turn(body: TurnSubmitRequest) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        eng = engine()
        # Validation, persistence of the user message and every refusal (busy, duplicate,
        # missing model, runtime down) happen before the stream starts, so they arrive as
        # proper HTTP errors.
        handle = await eng.begin_turn(
            TurnRequest(
                conversation_id=None,
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
        eng = engine()
        session = await eng.active_session()
        result = await eng.prepare(None if session is None else session.id, body.model)
        return PrepareResponse(**result)

    @router.get("/diagnostics", response_model=DiagnosticsResponse)
    async def diagnostics() -> DiagnosticsResponse:  # pyright: ignore[reportUnusedFunction]
        return DiagnosticsResponse(**await engine().diagnostics())

    @router.get("/chat/activity", response_model=ActivityResponse)
    async def activity() -> ActivityResponse:  # pyright: ignore[reportUnusedFunction]
        return ActivityResponse(**engine().activity())

    return router
