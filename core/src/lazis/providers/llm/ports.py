"""Runtime-neutral contract for local text generation.

The conversation layer (P3) and the API depend on these types only, never on a runtime's
wire format. Ollama is the first implementation (:mod:`lazis.providers.llm.ollama`); an MLX or
OpenAI-compatible server can be added behind the same protocol.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class GenerationOptions:
    num_ctx: int = 8192
    max_tokens: int = 1024
    temperature: float | None = None  # None: the model's own default
    top_p: float | None = None
    top_k: int | None = None
    presence_penalty: float | None = None
    seed: int | None = None
    think: bool = False  # reasoning traces off by default (latency, voice)
    keep_alive: str | None = None  # e.g. "10m"; None: runtime default
    # Constrain the output: "json" (any JSON) or a JSON Schema object. None: free text.
    response_format: Literal["json"] | Mapping[str, Any] | None = None


@dataclass(frozen=True)
class ChatRequest:
    model: str
    messages: Sequence[ChatMessage]
    options: GenerationOptions = field(default_factory=GenerationOptions)
    request_id: str = ""


@dataclass(frozen=True)
class GenerationMetrics:
    """Times in milliseconds. ``ttft_ms`` = request start → first visible content token."""

    ttft_ms: float | None
    total_ms: float
    load_ms: float | None = None
    prompt_tokens: int | None = None
    prompt_ms: float | None = None
    output_tokens: int | None = None
    output_ms: float | None = None
    done_reason: str | None = None

    @property
    def prefill_tps(self) -> float | None:
        if self.prompt_tokens and self.prompt_ms:
            return self.prompt_tokens / (self.prompt_ms / 1000)
        return None

    @property
    def decode_tps(self) -> float | None:
        if self.output_tokens and self.output_ms:
            return self.output_tokens / (self.output_ms / 1000)
        return None


@dataclass(frozen=True)
class TextDelta:
    text: str
    kind: Literal["content", "thinking"] = "content"


@dataclass(frozen=True)
class GenerationDone:
    metrics: GenerationMetrics


StreamEvent = TextDelta | GenerationDone


@dataclass(frozen=True)
class Completion:
    text: str
    thinking: str
    metrics: GenerationMetrics


@dataclass(frozen=True)
class ModelInfo:
    name: str
    digest: str
    size_bytes: int
    family: str = ""
    parameter_size: str = ""
    quantization: str = ""
    format: str = ""


@dataclass(frozen=True)
class LoadedModel:
    name: str
    size_bytes: int
    vram_bytes: int
    context_length: int | None
    expires_at: str


@dataclass(frozen=True)
class RuntimeHealth:
    available: bool
    runtime: str
    version: str | None = None
    error_code: str | None = None


class LLMProvider(Protocol):
    """Errors are raised as :class:`lazis.errors.LlmError` subclasses (stable codes)."""

    async def health(self) -> RuntimeHealth: ...

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]: ...

    async def loaded_models(self) -> list[LoadedModel]: ...

    def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]: ...

    async def generate(self, request: ChatRequest) -> Completion: ...

    def cancel(self, request_id: str) -> bool: ...

    async def load(self, model: str, *, num_ctx: int, keep_alive: str | None = None) -> float: ...

    async def unload(self, model: str) -> None: ...

    async def aclose(self) -> None: ...
