"""Ollama implementation of :class:`~lazis.providers.llm.ports.LLMProvider`.

Security properties (SECURITY_MODEL §5.3, PHASE_2_REPORT §H):

* Talks only to the configured loopback endpoint (the OS sandbox allows only 127.0.0.1:11434).
* Calls only an allowlist of read/inference endpoints. Model management endpoints that make
  Ollama reach the internet or change the model store (``pull``, ``push``, ``create``,
  ``copy``, ``delete``, ``blobs``) are not reachable through this class — Ollama must not
  become a proxy for the sandboxed backend.
* Uses only models that are installed locally; cloud models (``*cloud*``, remote entries) and
  registry-qualified names (``host/ns/model``) are refused before any request is sent.
* Never logs prompts or generated text — only model names, token counts and durations.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Mapping
from typing import Any, cast

import httpx

from lazis.errors import (
    LlmCancelledError,
    LlmError,
    LlmInvalidResponseError,
    LlmLoadFailedError,
    LlmModelNotAllowedError,
    LlmModelNotFoundError,
    LlmOutOfMemoryError,
    LlmTimeoutError,
    LlmUnavailableError,
)
from lazis.observability.logging import get_logger, log_event
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

_log = get_logger("providers.ollama")

# (method, path) pairs this client may call. Everything else is refused in _request().
ALLOWED_ENDPOINTS = frozenset(
    {
        ("GET", "/api/version"),
        ("GET", "/api/tags"),
        ("GET", "/api/ps"),
        ("POST", "/api/show"),
        ("POST", "/api/chat"),
    }
)
# name[:tag] — the name is lowercase (Ollama normalizes it); tags may contain capitals (q4_K_M).
_MODEL_NAME = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,79})?$")
_MAX_LINE = 1 << 20  # one NDJSON line from Ollama; anything larger is not a valid response
_MODELS_TTL_S = 5.0


def check_model_name(name: str) -> str:
    """Refuse names that could reach a remote registry or a cloud model."""
    if not _MODEL_NAME.match(name) or "cloud" in name.lower():
        raise LlmModelNotAllowedError("model name refused")
    return name


def _ns_to_ms(value: object) -> float | None:
    return value / 1_000_000 if isinstance(value, int | float) else None


def _int_or_none(value: object) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _classify(status: int, message: str) -> LlmError:
    text = message.lower()
    if status == 404 or "not found" in text:
        return LlmModelNotFoundError("model not found")
    if "memory" in text and any(w in text for w in ("requires more", "out of", "insufficient")):
        return LlmOutOfMemoryError("not enough memory for the model")
    if "error loading model" in text or "runner process has terminated" in text:
        return LlmLoadFailedError("model failed to load")
    return LlmError(f"runtime error (HTTP {status})")


class OllamaProvider:
    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:11434",
        *,
        connect_timeout: float = 2.0,
        first_token_timeout: float = 180.0,  # includes a cold model load
        idle_timeout: float = 60.0,
        max_duration: float = 600.0,
        request_timeout: float = 60.0,  # non-streaming calls (status, tags, show, load)
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._connect_timeout = connect_timeout
        self._client = httpx.AsyncClient(
            base_url=endpoint,
            timeout=httpx.Timeout(
                connect=connect_timeout, read=request_timeout, write=10.0, pool=5.0
            ),
            transport=transport,
            trust_env=False,  # never pick up proxy settings from the environment
            follow_redirects=False,
        )
        self._first_token_timeout = first_token_timeout
        self._idle_timeout = idle_timeout
        self._max_duration = max_duration
        self._cancel: dict[str, asyncio.Event] = {}
        self._models: tuple[float, list[ModelInfo]] | None = None
        self._capabilities: dict[str, frozenset[str]] = {}

    # ----- plumbing ----------------------------------------------------------------------
    async def _request(
        self, method: str, path: str, body: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        if (method, path) not in ALLOWED_ENDPOINTS:
            raise LlmError(f"endpoint not allowed: {method} {path}")
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.ConnectError:
            raise LlmUnavailableError("ollama is not reachable") from None
        except httpx.TimeoutException:
            raise LlmTimeoutError("ollama did not answer in time") from None
        except httpx.HTTPError as exc:
            raise LlmError(f"transport error ({type(exc).__name__})") from None
        if response.status_code >= 400:
            raise _classify(response.status_code, _error_text(response.content))
        try:
            data: object = response.json()
        except ValueError:
            raise LlmInvalidResponseError("response is not JSON") from None
        if not isinstance(data, dict):
            raise LlmInvalidResponseError("response is not a JSON object")
        return cast("dict[str, Any]", data)

    # ----- discovery ---------------------------------------------------------------------
    async def health(self) -> RuntimeHealth:
        try:
            data = await self._request("GET", "/api/version")
        except LlmError as exc:
            return RuntimeHealth(available=False, runtime="ollama", error_code=exc.code)
        version = data.get("version")
        if not isinstance(version, str):
            return RuntimeHealth(False, "ollama", error_code="llm_invalid_response")
        return RuntimeHealth(available=True, runtime="ollama", version=version)

    async def list_models(self, *, refresh: bool = False) -> list[ModelInfo]:
        now = time.monotonic()
        if not refresh and self._models and now - self._models[0] < _MODELS_TTL_S:
            return self._models[1]
        data = await self._request("GET", "/api/tags")
        raw = data.get("models")
        if not isinstance(raw, list):
            raise LlmInvalidResponseError("unexpected /api/tags shape")
        models: list[ModelInfo] = []
        for entry in cast("list[object]", raw):
            if not isinstance(entry, dict):
                continue
            item = cast("dict[str, Any]", entry)
            name = item.get("name") or item.get("model")
            if not isinstance(name, str) or "remote_host" in item or "remote_model" in item:
                continue  # cloud/remote entries are never offered
            try:
                check_model_name(name)
            except LlmModelNotAllowedError:
                continue
            details = _as_dict(item.get("details"))
            models.append(
                ModelInfo(
                    name=name,
                    digest=str(item.get("digest", "")),
                    size_bytes=int(item.get("size", 0) or 0),
                    family=str(details.get("family", "")),
                    parameter_size=str(details.get("parameter_size", "")),
                    quantization=str(details.get("quantization_level", "")),
                    format=str(details.get("format", "")),
                )
            )
        models.sort(key=lambda m: m.name)
        self._models = (now, models)
        return models

    async def loaded_models(self) -> list[LoadedModel]:
        data = await self._request("GET", "/api/ps")
        raw = data.get("models")
        if not isinstance(raw, list):
            raise LlmInvalidResponseError("unexpected /api/ps shape")
        loaded: list[LoadedModel] = []
        for entry in cast("list[object]", raw):
            if isinstance(entry, dict):
                item = cast("dict[str, Any]", entry)
                loaded.append(
                    LoadedModel(
                        name=str(item.get("name", "")),
                        size_bytes=int(item.get("size", 0) or 0),
                        vram_bytes=int(item.get("size_vram", 0) or 0),
                        context_length=_int_or_none(item.get("context_length")),
                        expires_at=str(item.get("expires_at", "")),
                    )
                )
        return loaded

    async def capabilities(self, model: str) -> frozenset[str]:
        if model not in self._capabilities:
            data = await self._request("POST", "/api/show", {"model": model})
            caps = data.get("capabilities")
            values = cast("list[object]", caps) if isinstance(caps, list) else []
            self._capabilities[model] = frozenset(str(c) for c in values)
        return self._capabilities[model]

    async def _require_installed(self, model: str) -> None:
        check_model_name(model)
        names = {m.name for m in await self.list_models()}
        if model not in names:
            names = {m.name for m in await self.list_models(refresh=True)}
        if model not in names:
            raise LlmModelNotFoundError("model is not installed locally")

    # ----- lifecycle ---------------------------------------------------------------------
    async def load(self, model: str, *, num_ctx: int, keep_alive: str | None = None) -> float:
        """Load ``model`` with ``num_ctx``; returns the runtime's reported load time in ms."""
        await self._require_installed(model)
        body: dict[str, Any] = {
            "model": model,
            "messages": [],
            "stream": False,
            "options": {"num_ctx": num_ctx},
        }
        if keep_alive is not None:
            body["keep_alive"] = keep_alive
        data = await self._request("POST", "/api/chat", body)
        return _ns_to_ms(data.get("load_duration")) or 0.0

    async def unload(self, model: str) -> None:
        check_model_name(model)
        await self._request("POST", "/api/chat", {"model": model, "messages": [], "keep_alive": 0})

    # ----- generation --------------------------------------------------------------------
    def cancel(self, request_id: str) -> bool:
        event = self._cancel.get(request_id)
        if event is None:
            return False
        event.set()
        return True

    async def _body(self, request: ChatRequest) -> dict[str, Any]:
        opts = request.options
        options: dict[str, Any] = {"num_ctx": opts.num_ctx, "num_predict": opts.max_tokens}
        for key, value in (
            ("temperature", opts.temperature),
            ("top_p", opts.top_p),
            ("top_k", opts.top_k),
            ("presence_penalty", opts.presence_penalty),
            ("seed", opts.seed),
        ):
            if value is not None:
                options[key] = value
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": True,
            "options": options,
        }
        if "thinking" in await self.capabilities(request.model):
            body["think"] = opts.think
        if opts.keep_alive is not None:
            body["keep_alive"] = opts.keep_alive
        if opts.response_format is not None:
            body["format"] = (
                opts.response_format
                if isinstance(opts.response_format, str)
                else dict(opts.response_format)
            )
        return body

    async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
        await self._require_installed(request.model)
        body = await self._body(request)
        cancel = asyncio.Event()
        if request.request_id:
            self._cancel[request.request_id] = cancel
        started = time.monotonic()
        first_content: float | None = None
        outcome = "error"
        out_tokens: int | None = None
        try:
            async with asyncio.timeout(self._max_duration):
                try:
                    # No transport read timeout while streaming: a long prompt can take minutes
                    # before the first byte. The first-token / idle / total limits apply instead.
                    stream_timeout = httpx.Timeout(
                        connect=self._connect_timeout, read=None, write=10.0, pool=5.0
                    )
                    async with self._client.stream(
                        "POST", "/api/chat", json=body, timeout=stream_timeout
                    ) as response:
                        if response.status_code >= 400:
                            raise _classify(
                                response.status_code, _error_text(await response.aread())
                            )
                        lines = response.aiter_lines()
                        while True:
                            wait = (
                                self._idle_timeout if first_content else self._first_token_timeout
                            )
                            line = await _next_line(lines, cancel, wait)
                            if line is None:
                                raise LlmInvalidResponseError("stream ended without done")
                            if not line.strip():
                                continue
                            if len(line) > _MAX_LINE:
                                raise LlmInvalidResponseError("oversized stream line")
                            chunk = _parse_chunk(line)
                            if "error" in chunk:
                                raise _classify(500, str(chunk["error"]))
                            message = chunk.get("message")
                            if isinstance(message, dict):
                                msg = cast("dict[str, Any]", message)
                                thinking = msg.get("thinking")
                                if isinstance(thinking, str) and thinking:
                                    yield TextDelta(thinking, kind="thinking")
                                content = msg.get("content")
                                if isinstance(content, str) and content:
                                    if first_content is None:
                                        first_content = time.monotonic()
                                    yield TextDelta(content)
                            if chunk.get("done") is True:
                                metrics = GenerationMetrics(
                                    ttft_ms=(first_content - started) * 1000
                                    if first_content
                                    else None,
                                    total_ms=(time.monotonic() - started) * 1000,
                                    load_ms=_ns_to_ms(chunk.get("load_duration")),
                                    prompt_tokens=_int_or_none(chunk.get("prompt_eval_count")),
                                    prompt_ms=_ns_to_ms(chunk.get("prompt_eval_duration")),
                                    output_tokens=_int_or_none(chunk.get("eval_count")),
                                    output_ms=_ns_to_ms(chunk.get("eval_duration")),
                                    done_reason=str(chunk.get("done_reason") or "") or None,
                                )
                                out_tokens = metrics.output_tokens
                                outcome = "completed"
                                yield GenerationDone(metrics)
                                return
                except httpx.ConnectError:
                    raise LlmUnavailableError("ollama is not reachable") from None
                except httpx.TimeoutException:
                    raise LlmTimeoutError("ollama did not answer in time") from None
                except httpx.HTTPError as exc:
                    raise LlmError(f"transport error ({type(exc).__name__})") from None
        except TimeoutError:
            outcome = "timeout"
            raise LlmTimeoutError("generation exceeded the maximum duration") from None
        except LlmCancelledError:
            outcome = "cancelled"
            raise
        except LlmError as exc:
            outcome = exc.code
            raise
        except (asyncio.CancelledError, GeneratorExit):
            outcome = "aborted"  # the consumer went away; closing the stream stops Ollama
            raise
        finally:
            if request.request_id:
                self._cancel.pop(request.request_id, None)
            # Metrics only — never prompt or response text.
            log_event(
                _log,
                logging.INFO,
                "llm.generation",
                model=request.model,
                outcome=outcome,
                messages=len(request.messages),
                output_tokens=out_tokens,
                ms=round((time.monotonic() - started) * 1000),
            )

    async def generate(self, request: ChatRequest) -> Completion:
        text: list[str] = []
        thinking: list[str] = []
        metrics: GenerationMetrics | None = None
        async for event in self.stream(request):
            if isinstance(event, TextDelta):
                (thinking if event.kind == "thinking" else text).append(event.text)
            else:
                metrics = event.metrics
        if metrics is None:
            raise LlmInvalidResponseError("no completion metrics")
        return Completion(text="".join(text), thinking="".join(thinking), metrics=metrics)

    async def aclose(self) -> None:
        await self._client.aclose()


def _as_dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _error_text(raw: bytes) -> str:
    try:
        data: object = json.loads(raw)
    except ValueError:
        return raw[:200].decode("utf-8", "replace")
    error = _as_dict(data).get("error")
    return error[:500] if isinstance(error, str) else ""


def _parse_chunk(line: str) -> dict[str, Any]:
    try:
        data = json.loads(line)
    except ValueError:
        raise LlmInvalidResponseError("stream line is not JSON") from None
    if not isinstance(data, dict):
        raise LlmInvalidResponseError("stream line is not an object")
    return cast("dict[str, Any]", data)


async def _next_line(
    lines: AsyncIterator[str], cancel: asyncio.Event, limit_s: float
) -> str | None:
    """Next stream line, or raise on cancellation / timeout. ``None`` at end of stream."""
    if cancel.is_set():
        raise LlmCancelledError("cancelled")
    nxt: asyncio.Future[str] = asyncio.ensure_future(anext(lines))
    stop = asyncio.ensure_future(cancel.wait())
    try:
        done, _ = await asyncio.wait(
            {nxt, stop}, timeout=limit_s, return_when=asyncio.FIRST_COMPLETED
        )
    finally:
        stop.cancel()
    if nxt not in done:
        nxt.cancel()
        if stop in done or cancel.is_set():
            raise LlmCancelledError("cancelled")
        raise LlmTimeoutError("no output from the model in time")
    try:
        return nxt.result()
    except StopAsyncIteration:
        return None
