"""Local model status and the ephemeral Phase 2 chat (streamed NDJSON).

Privacy: nothing here is stored. The conversation lives in the desktop UI's memory and is sent
with each request; the backend forwards it to the local runtime and forgets it. Prompts and
responses are never logged (the provider logs counts and durations only). Clients cannot set a
system prompt. The full conversation engine with persistence arrives in P3.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from lazis.api.schemas import (
    ChatCancelRequest,
    ChatCancelResponse,
    ChatStreamRequest,
    LlmStatusResponse,
    LoadedModelModel,
    ModelInfoModel,
    ModelListResponse,
    RuntimeStatusModel,
)
from lazis.config.model import Settings
from lazis.errors import LlmBusyError, LlmError, LlmModelNotFoundError, LlmUnavailableError
from lazis.i18n import message_for
from lazis.observability.logging import get_logger, log_event
from lazis.providers.llm.ports import (
    ChatMessage,
    ChatRequest,
    GenerationMetrics,
    GenerationOptions,
    LLMProvider,
    TextDelta,
)

_log = get_logger("api.chat")

# Temporary Phase 2 instructions (no personality engine yet — that is P5). Kept minimal and
# fixed so the preview chat behaves predictably; it carries no knowledge about the owner.
PHASE2_SYSTEM_PROMPT = (
    "Sen LAZIS'sin: kullanıcının bilgisayarında yerel olarak çalışan, Türkçe konuşan kişisel "
    "bir yapay zekâ asistanısın. Doğal, sıcak ve saygılı bir Türkçeyle, gereksiz uzatmadan "
    "yanıt ver. Kullanıcıya doğal düştüğü yerlerde 'efendim' diye hitap edebilirsin; bunu her "
    "cümlede ya da her yanıtta tekrarlama. Bilmediğin bir şeyi uydurma; emin değilsen bunu "
    "açıkça söyle. Bu, kayıt tutulmayan geçici bir deneme sohbetidir ve kullanıcı hakkında "
    "önceden bir bilgin yok."
)


def metrics_payload(m: GenerationMetrics) -> dict[str, Any]:
    def r(v: float | None) -> float | None:
        return None if v is None else round(v, 1)

    return {
        "ttft_ms": r(m.ttft_ms),
        "total_ms": r(m.total_ms),
        "load_ms": r(m.load_ms),
        "prompt_tokens": m.prompt_tokens,
        "output_tokens": m.output_tokens,
        "prefill_tps": r(m.prefill_tps),
        "decode_tps": r(m.decode_tps),
        "done_reason": m.done_reason,
    }


def _line(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")


def build_chat_router(
    prefix: str, settings: Settings, get_llm: Callable[[], LLMProvider | None]
) -> APIRouter:
    router = APIRouter(prefix=prefix)
    active: dict[str, str] = {}  # at most one generation at a time (single user, one model)

    def provider() -> LLMProvider:
        llm = get_llm()
        if llm is None:
            raise LlmUnavailableError("no local inference provider configured")
        return llm

    @router.get("/llm/status", response_model=LlmStatusResponse)
    async def llm_status() -> LlmStatusResponse:  # pyright: ignore[reportUnusedFunction]
        llm = provider()
        health = await llm.health()
        loaded = await llm.loaded_models() if health.available else []
        return LlmStatusResponse(
            runtime=RuntimeStatusModel(
                available=health.available,
                runtime=health.runtime,
                version=health.version,
                error_code=health.error_code,
            ),
            loaded=[
                LoadedModelModel(
                    name=m.name,
                    size_bytes=m.size_bytes,
                    vram_bytes=m.vram_bytes,
                    context_length=m.context_length,
                    expires_at=m.expires_at,
                )
                for m in loaded
            ],
            primary_model=settings.models.primary_model,
            cloud_inference="disabled",
        )

    @router.get("/llm/models", response_model=ModelListResponse)
    async def llm_models() -> ModelListResponse:  # pyright: ignore[reportUnusedFunction]
        models = await provider().list_models()
        return ModelListResponse(
            models=[
                ModelInfoModel(
                    name=m.name,
                    digest=m.digest,
                    size_bytes=m.size_bytes,
                    family=m.family,
                    parameter_size=m.parameter_size,
                    quantization=m.quantization,
                    format=m.format,
                )
                for m in models
            ]
        )

    @router.post("/chat/stream")
    async def chat_stream(body: ChatStreamRequest) -> StreamingResponse:  # pyright: ignore[reportUnusedFunction]
        llm = provider()
        if active:
            raise LlmBusyError("another generation is running")
        # Fail with a proper HTTP status before streaming starts: runtime down, model missing,
        # cloud/foreign model names.
        installed = {m.name for m in await llm.list_models()}
        if body.model not in installed:
            installed = {m.name for m in await llm.list_models(refresh=True)}
        if body.model not in installed:
            raise LlmModelNotFoundError("model is not installed locally")
        models = settings.models
        request = ChatRequest(
            model=body.model,
            request_id=body.request_id,
            messages=[
                ChatMessage("system", PHASE2_SYSTEM_PROMPT),
                *(ChatMessage(t.role, t.content) for t in body.messages),
            ],
            options=GenerationOptions(
                num_ctx=models.context_tokens(body.options.context),
                max_tokens=body.options.max_tokens or models.max_output_tokens,
                temperature=body.options.temperature,
                think=False,
                keep_alive=models.keep_alive,
            ),
        )

        async def events() -> AsyncIterator[bytes]:
            if active:
                yield _line(
                    {"type": "error", "code": "llm_busy", "message": message_for("llm_busy")}
                )
                return
            active["request_id"] = body.request_id
            try:
                yield _line({"type": "start", "request_id": body.request_id, "model": body.model})
                async for event in llm.stream(request):
                    if isinstance(event, TextDelta):
                        if event.kind == "content":
                            yield _line({"type": "delta", "text": event.text})
                    else:
                        yield _line({"type": "done", "metrics": metrics_payload(event.metrics)})
            except LlmError as exc:
                yield _line({"type": "error", "code": exc.code, "message": message_for(exc.code)})
            finally:
                active.pop("request_id", None)

        log_event(
            _log, logging.INFO, "chat.stream_started", model=body.model, turns=len(body.messages)
        )
        # The API guard adds no-store / nosniff / CORS headers to every response.
        return StreamingResponse(events(), media_type="application/x-ndjson")

    @router.post("/chat/cancel", response_model=ChatCancelResponse)
    async def chat_cancel(body: ChatCancelRequest) -> ChatCancelResponse:  # pyright: ignore[reportUnusedFunction]
        llm = get_llm()
        return ChatCancelResponse(cancelled=bool(llm and llm.cancel(body.request_id)))

    return router
