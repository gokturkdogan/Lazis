"""Test support for the conversation engine: a scripted local-model fake and builders.

``ScriptedLLM`` behaves like the runtime as far as the engine can observe it: streamed
deltas, a final metrics event with ``prompt_tokens`` / ``output_tokens`` (counted by a fixed
"tokenizer" of 3 characters per token plus 4 template tokens per message, so the engine's
conservative 2.2-chars estimate is checked against a different, known truth), cancellation,
model loading, and schema-constrained summary output. Synthetic data only.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lazis.config.model import (
    AppSection,
    ConversationSection,
    LoggingSection,
    Settings,
    StorageSection,
)
from lazis.conversation import ConversationEngine, TurnRequest
from lazis.errors import LlmCancelledError, LlmError
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
from lazis.storage import StorageHandle

MODEL = "gemma4:12b-it-qat"
FIXED_NOW = datetime(2026, 10, 17, 14, 32, tzinfo=UTC)

_LINE = re.compile(r"^#(\d+) (KULLANICI|LAZIS)[^:]*: (.*)$")


def true_tokens(text: str) -> int:
    return math.ceil(len(text) / 3.0)


def prompt_tokens(request: ChatRequest) -> int:
    return sum(true_tokens(m.content) + 4 for m in request.messages) + 3


def default_summary(request: ChatRequest) -> str:
    """A faithful summary: one goal per user line, quoting its first words."""
    goals: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for line in request.messages[-1].content.splitlines():
        match = _LINE.match(line)
        if not match:
            continue
        seq, who, text = int(match.group(1)), match.group(2), match.group(3)
        quote = " ".join(text.split()[:6])
        item = {"text": text[:120], "refs": [seq], "quote": quote, "certain": True}
        if who == "KULLANICI":
            goals.append({**item, "source": "user"})
        else:
            notes.append({**item, "source": "assistant"})
    body = {
        "goals": goals,
        "topics": [],
        "decisions": [],
        "open_questions": [],
        "constraints": [],
        "people": [],
        "instructions": [],
        "assistant_notes": notes[-3:],
    }
    return json.dumps(body, ensure_ascii=False)


@dataclass
class ScriptedLLM:
    reply: Callable[[ChatRequest], str] = lambda r: "Tamam efendim, anladım."
    summary: Callable[[ChatRequest], str] = default_summary
    chunk_size: int = 6
    delay: float = 0.0
    fail_with: LlmError | None = None
    fail_after_chunks: int = 1
    summary_fails: bool = False
    available: bool = True
    installed: tuple[str, ...] = (MODEL,)
    loaded: set[str] = field(default_factory=lambda: {MODEL})
    requests: list[ChatRequest] = field(default_factory=lambda: [])
    loads: list[str] = field(default_factory=lambda: [])
    unloads: list[str] = field(default_factory=lambda: [])
    gate: asyncio.Event | None = None
    _cancel: dict[str, asyncio.Event] = field(default_factory=lambda: {})

    @property
    def chat_requests(self) -> list[ChatRequest]:
        return [
            r
            for r in self.requests
            if r.options.response_format is None and r.options.max_tokens > 1
        ]

    @property
    def summary_requests(self) -> list[ChatRequest]:
        return [r for r in self.requests if r.options.response_format is not None]

    @property
    def prewarm_requests(self) -> list[ChatRequest]:
        return [r for r in self.requests if r.options.max_tokens == 1]

    async def health(self) -> RuntimeHealth:
        if not self.available:
            return RuntimeHealth(False, "fake", error_code="llm_unavailable")
        return RuntimeHealth(True, "fake", version="0.0-test")

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        return [ModelInfo(n, "digest", 1, "fake", "12B", "Q4", "gguf") for n in self.installed]

    async def loaded_models(self) -> list[LoadedModel]:
        return [LoadedModel(n, 2, 2, 16384, "later") for n in sorted(self.loaded)]

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        self.requests.append(request)
        cancel = self._cancel.setdefault(request.request_id, asyncio.Event())
        try:
            if request.options.response_format is not None:
                text = "bu JSON değil" if self.summary_fails else self.summary(request)
            elif request.options.max_tokens == 1:
                text = "."
            else:
                text = self.reply(request)
            if self.gate is not None:
                await self.gate.wait()
            pieces = [text[i : i + self.chunk_size] for i in range(0, len(text), self.chunk_size)]
            for i, piece in enumerate(pieces):
                if cancel.is_set():
                    raise LlmCancelledError("cancelled")
                if self.fail_with is not None and i == self.fail_after_chunks:
                    raise self.fail_with
                await asyncio.sleep(self.delay)
                if cancel.is_set():
                    raise LlmCancelledError("cancelled")
                yield TextDelta(piece)
            yield GenerationDone(
                GenerationMetrics(
                    ttft_ms=1.0,
                    total_ms=2.0,
                    prompt_tokens=prompt_tokens(request),
                    output_tokens=true_tokens(text),
                )
            )
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
        self.loads.append(model)
        self.loaded.add(model)
        return 1.0

    async def unload(self, model: str) -> None:
        self.unloads.append(model)
        self.loaded.discard(model)

    async def aclose(self) -> None:
        return None


def settings_for(tmp_path: Path, **conversation: Any) -> Settings:
    defaults: dict[str, Any] = {"idle_compaction_delay_s": 0.0, "flush_interval_s": 0.01}
    defaults.update(conversation)
    return Settings(
        app=AppSection(environment="test"),
        storage=StorageSection(data_dir=tmp_path / "data"),
        logging=LoggingSection(directory=tmp_path / "logs"),
        conversation=ConversationSection(**defaults),
    )


def make_engine(
    storage: StorageHandle, llm: ScriptedLLM | None, tmp_path: Path, **conversation: Any
) -> ConversationEngine:
    return ConversationEngine(
        db=storage.db,
        get_llm=lambda: llm,
        settings=settings_for(tmp_path, **conversation),
        now_local=lambda: FIXED_NOW,
    )


_counter = iter(range(1, 10**9))


def client_id() -> str:
    return f"client-{next(_counter):08d}"


async def run_turn(
    engine: ConversationEngine, text: str, conversation_id: str | None = None, model: str = MODEL
) -> tuple[list[dict[str, Any]], str]:
    """Submit one turn and drain its events. Returns (events, conversation_id)."""
    handle = await engine.begin_turn(TurnRequest(conversation_id, client_id(), text, model))
    events = [e async for e in engine.events(handle)]
    return events, handle.conversation.id
