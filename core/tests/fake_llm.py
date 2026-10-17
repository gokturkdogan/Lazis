"""In-memory LLMProvider for API and UI-contract tests (no runtime, no model)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from lazis.errors import LlmCancelledError, LlmError, LlmModelNotFoundError, LlmUnavailableError
from lazis.providers.llm.ports import (
    ChatRequest,
    Completion,
    GenerationDone,
    GenerationMetrics,
    LoadedModel,
    ModelInfo,
    RuntimeHealth,
    StreamEvent,
    TextDelta,
)

FAKE_MODEL = "fake-tr:1b"


class FakeLLM:
    def __init__(
        self,
        *,
        available: bool = True,
        reply: tuple[str, ...] = ("Merhaba", " efendim", "."),
        delay: float = 0.0,
        fail_with: LlmError | None = None,
    ) -> None:
        self.available = available
        self.reply = reply
        self.delay = delay
        self.fail_with = fail_with
        self.requests: list[ChatRequest] = []
        self._cancel: dict[str, asyncio.Event] = {}
        self.closed = False

    async def health(self) -> RuntimeHealth:
        if not self.available:
            return RuntimeHealth(False, "fake", error_code="llm_unavailable")
        return RuntimeHealth(True, "fake", version="0.0-test")

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        if not self.available:
            raise LlmUnavailableError("down")
        return [ModelInfo(FAKE_MODEL, "digest", 1, "fake", "1B", "Q4", "gguf")]

    async def loaded_models(self) -> list[LoadedModel]:
        return [LoadedModel(FAKE_MODEL, 2, 2, 8192, "later")]

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        if request.model != FAKE_MODEL:
            raise LlmModelNotFoundError("missing")
        cancel = self._cancel.setdefault(request.request_id, asyncio.Event())
        try:
            for i, piece in enumerate(self.reply):
                if cancel.is_set():
                    raise LlmCancelledError("cancelled")
                if self.fail_with is not None and i == 1:
                    raise self.fail_with
                await asyncio.sleep(self.delay)
                yield TextDelta(piece)
            yield GenerationDone(GenerationMetrics(ttft_ms=1.0, total_ms=2.0, output_tokens=3))
        finally:
            self._cancel.pop(request.request_id, None)

    async def generate(self, request: ChatRequest) -> Completion:
        raise NotImplementedError

    def cancel(self, request_id: str) -> bool:
        event = self._cancel.get(request_id)
        if event is None:
            return False
        event.set()
        return True

    async def load(self, model: str, *, num_ctx: int, keep_alive: str | None = None) -> float:
        return 0.0

    async def unload(self, model: str) -> None:
        return None

    async def aclose(self) -> None:
        self.closed = True
