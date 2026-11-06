"""Internet research API (Phase 12): the user's permission, and the query preview.

* ``GET /research/settings``: whether research is allowed (``offline_only`` by default or
  ``ask``) and whether the research helper is available.
* ``PUT /research/settings``: the user turns it on or off (recorded in the audit log).
* ``POST /research/plan``: what would be sent for a message, before anything is sent: the exact
  query, restricted data that blocks it, stored people it names. Nothing leaves the machine.

The search itself is an ordinary turn with ``research_query`` (``POST /turns``), sent only after
the user approved the query shown by the plan.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lazis.conversation import ConversationEngine
from lazis.errors import LazisError
from lazis.research import MAX_QUERY_CHARS

ModeName = Literal["offline_only", "ask"]


class _EngineUnavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


class ResearchSettingsModel(BaseModel):
    mode: ModeName
    available: bool  # the research helper was started (by the desktop shell)
    provider: Literal["wikipedia"] = "wikipedia"
    max_query_chars: int = MAX_QUERY_CHARS


class ResearchSettingsRequest(BaseModel):
    mode: ModeName


class ResearchPlanRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)


class ResearchPlanModel(BaseModel):
    query: str
    blocked: bool
    blocked_reason: Literal["restricted"] | None
    people: list[str]  # stored people the query names: the user is warned before sending
    mode: ModeName


def build_research_router(
    prefix: str, get_engine: Callable[[], ConversationEngine | None]
) -> APIRouter:
    router = APIRouter(prefix=f"{prefix}/research")

    def engine() -> ConversationEngine:
        e = get_engine()
        if e is None:
            raise _EngineUnavailable("conversation engine not available")
        return e

    @router.get("/settings", response_model=ResearchSettingsModel)
    async def get_settings() -> ResearchSettingsModel:  # pyright: ignore[reportUnusedFunction]
        e = engine()
        return ResearchSettingsModel(
            mode=await e.research_mode(), available=e.research_client is not None
        )

    @router.put("/settings", response_model=ResearchSettingsModel)
    async def put_settings(  # pyright: ignore[reportUnusedFunction]
        body: ResearchSettingsRequest,
    ) -> ResearchSettingsModel:
        e = engine()
        return ResearchSettingsModel(
            mode=await e.set_research_mode(body.mode), available=e.research_client is not None
        )

    @router.post("/plan", response_model=ResearchPlanModel)
    async def plan(body: ResearchPlanRequest) -> ResearchPlanModel:  # pyright: ignore[reportUnusedFunction]
        e = engine()
        p = await e.research_plan(body.message)
        return ResearchPlanModel(
            query=p.query,
            blocked=p.blocked is not None,
            blocked_reason="restricted" if p.blocked is not None else None,
            people=list(p.people),
            mode=await e.research_mode(),
        )

    return router
