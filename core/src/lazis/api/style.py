"""Communication preferences API (Phase 10B, ADR-0022) — the infrastructure under the Phase
10D Settings screen "LAZIS'in seninle konuşma tarzı".

Every dimension shows its value and where it comes from: what the user said (``explicit``),
what LAZIS learned (``learned``) or LAZIS's own default. The user can set a value (it then
counts as said) or remove one (back to the default; old signals never bring it back). The
history explains every change. No message content is returned.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Path, Query
from pydantic import BaseModel, Field

from lazis.conversation import ConversationEngine
from lazis.errors import LazisError, MemoryRequestError

DimensionName = Literal["verbosity", "elaboration", "formality", "humor", "address", "honorific"]


class _EngineUnavailable(LazisError):
    code = "database_error"
    http_status = 503
    recoverable = True


class StyleDimensionModel(BaseModel):
    dimension: DimensionName
    value: str  # level "0"–"10" (0.0–1.0), "siz"/"sen", "1"/"0"
    source: Literal["explicit", "learned", "default"]
    description: str
    learnable: bool
    explicit_value: str | None
    learned_value: str | None
    updated_at: str | None


class StyleResponse(BaseModel):
    dimensions: list[StyleDimensionModel]


class StyleSetRequest(BaseModel):
    value: str = Field(pattern=r"^(10|[0-9]|siz|sen|0|1)$")


class StyleChangeModel(BaseModel):
    dimension: str | None
    source: Literal["explicit", "learned", "cleared", "user_edit", "refused"]
    old_value: str | None
    new_value: str | None
    message_id: str | None
    detail: dict[str, Any]
    created_at: str


class StyleHistoryResponse(BaseModel):
    changes: list[StyleChangeModel]


_VALID = {
    "address": {"siz", "sen"},
    "honorific": {"0", "1"},
}


def build_style_router(
    prefix: str, get_engine: Callable[[], ConversationEngine | None]
) -> APIRouter:
    router = APIRouter(prefix=f"{prefix}/style")

    def engine() -> ConversationEngine:
        e = get_engine()
        if e is None:
            raise _EngineUnavailable("conversation engine not available")
        return e

    @router.get("", response_model=StyleResponse)
    async def get_style() -> StyleResponse:  # pyright: ignore[reportUnusedFunction]
        return StyleResponse.model_validate(await engine().style())

    @router.put("/{dimension}", response_model=StyleResponse)
    async def set_style(  # pyright: ignore[reportUnusedFunction]
        dimension: Annotated[DimensionName, Path()], body: StyleSetRequest
    ) -> StyleResponse:
        allowed = _VALID.get(dimension)
        if (allowed is not None and body.value not in allowed) or (
            allowed is None and not body.value.isdigit()
        ):
            raise MemoryRequestError("value not valid for this dimension")
        return StyleResponse.model_validate(await engine().set_style(dimension, body.value))

    @router.delete("/{dimension}", response_model=StyleResponse)
    async def clear_style(  # pyright: ignore[reportUnusedFunction]
        dimension: Annotated[DimensionName, Path()],
    ) -> StyleResponse:
        return StyleResponse.model_validate(await engine().clear_style(dimension))

    @router.get("/history", response_model=StyleHistoryResponse)
    async def style_history(  # pyright: ignore[reportUnusedFunction]
        limit: Annotated[int, Query(ge=1, le=200)] = 50,
    ) -> StyleHistoryResponse:
        return StyleHistoryResponse.model_validate({"changes": await engine().style_history(limit)})

    return router
