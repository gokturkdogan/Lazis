"""OllamaProvider against a scripted fake transport (no network, no model)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest

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
from lazis.providers.llm.ollama import ALLOWED_ENDPOINTS, OllamaProvider, check_model_name
from lazis.providers.llm.ports import (
    ChatMessage,
    ChatRequest,
    GenerationDone,
    GenerationOptions,
    TextDelta,
)

MODEL = "qwen3.5:9b-q4_K_M"
TAGS = {
    "models": [
        {
            "name": MODEL,
            "digest": "56671c2ab938",
            "size": 6_600_000_000,
            "details": {
                "family": "qwen35",
                "parameter_size": "9.0B",
                "quantization_level": "Q4_K_M",
                "format": "gguf",
            },
        },
        {"name": "gemma4:31b-cloud", "digest": "x", "size": 0, "remote_host": "https://ollama.com"},
        {"name": "remote-thing:latest", "digest": "y", "size": 0, "remote_model": "x"},
        {"name": "evil.example.com/ns/model:tag", "digest": "z", "size": 1},
    ]
}


class SlowStream(httpx.AsyncByteStream):
    def __init__(self, lines: list[str], delay: float = 0.0, first_delay: float = 0.0) -> None:
        self.lines, self.delay, self.first_delay = lines, delay, first_delay
        self.closed = False

    async def __aiter__(self) -> AsyncIterator[bytes]:
        await asyncio.sleep(self.first_delay)
        for line in self.lines:
            yield (line + "\n").encode()
            await asyncio.sleep(self.delay)

    async def aclose(self) -> None:
        self.closed = True


def chunk(content: str = "", *, thinking: str = "", done: bool = False, **extra: Any) -> str:
    body: dict[str, Any] = {"message": {"role": "assistant", "content": content}, "done": done}
    if thinking:
        body["message"]["thinking"] = thinking
    body.update(extra)
    return json.dumps(body)


DONE = chunk(
    done=True,
    done_reason="stop",
    total_duration=2_000_000_000,
    load_duration=500_000_000,
    prompt_eval_count=40,
    prompt_eval_duration=100_000_000,
    eval_count=3,
    eval_duration=100_000_000,
)


def make_provider(
    chat: Callable[[dict[str, Any]], httpx.Response] | None = None,
    calls: list[tuple[str, str]] | None = None,
    **kwargs: Any,
) -> OllamaProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": "0.40.4"})
        if path == "/api/tags":
            return httpx.Response(200, json=TAGS)
        if path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "thinking"]})
        if path == "/api/ps":
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "name": MODEL,
                            "size": 8_000_000_000,
                            "size_vram": 8_000_000_000,
                            "context_length": 8192,
                            "expires_at": "2026-10-17T10:00:00Z",
                        }
                    ]
                },
            )
        if path == "/api/chat" and chat is not None:
            return chat(json.loads(request.content or b"{}"))
        return httpx.Response(404, json={"error": "not found"})

    return OllamaProvider(transport=httpx.MockTransport(handler), **kwargs)


def request(**options: Any) -> ChatRequest:
    return ChatRequest(
        model=MODEL,
        messages=[ChatMessage("user", "Merhaba")],
        options=GenerationOptions(**options),
        request_id="r1",
    )


async def collect(provider: OllamaProvider, req: ChatRequest) -> list[object]:
    return [event async for event in provider.stream(req)]


def test_health_and_discovery_filter_cloud_and_registry_models() -> None:
    async def run() -> None:
        provider = make_provider()
        health = await provider.health()
        assert health.available and health.version == "0.40.4"
        models = await provider.list_models()
        assert [m.name for m in models] == [MODEL]
        assert models[0].quantization == "Q4_K_M" and models[0].digest == "56671c2ab938"
        loaded = await provider.loaded_models()
        assert loaded[0].context_length == 8192
        await provider.aclose()

    asyncio.run(run())


def test_unreachable_runtime_is_reported_not_raised_by_health() -> None:
    async def run() -> None:
        def refuse(_r: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused")

        provider = OllamaProvider(transport=httpx.MockTransport(refuse))
        health = await provider.health()
        assert not health.available and health.error_code == "llm_unavailable"
        with pytest.raises(LlmUnavailableError):
            await provider.list_models()

    asyncio.run(run())


def test_streaming_yields_deltas_thinking_and_metrics() -> None:
    sent: list[dict[str, Any]] = []

    def chat(body: dict[str, Any]) -> httpx.Response:
        sent.append(body)
        lines = [chunk(thinking="düşünüyor"), chunk("Merhaba"), chunk(" efendim"), DONE]
        return httpx.Response(200, stream=SlowStream(lines))

    async def run() -> None:
        provider = make_provider(chat)
        events = await collect(provider, request(num_ctx=4096, max_tokens=64, temperature=0.7))
        deltas = [e for e in events if isinstance(e, TextDelta)]
        assert [(d.kind, d.text) for d in deltas] == [
            ("thinking", "düşünüyor"),
            ("content", "Merhaba"),
            ("content", " efendim"),
        ]
        done = events[-1]
        assert isinstance(done, GenerationDone)
        m = done.metrics
        assert m.prompt_tokens == 40 and m.output_tokens == 3 and m.load_ms == 500
        assert m.decode_tps == pytest.approx(30.0) and m.prefill_tps == pytest.approx(400.0)
        assert m.ttft_ms is not None and m.ttft_ms >= 0
        body = sent[0]
        assert body["options"] == {"num_ctx": 4096, "num_predict": 64, "temperature": 0.7}
        assert body["think"] is False and body["stream"] is True

    asyncio.run(run())


def test_generate_collects_text() -> None:
    def chat(_b: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream([chunk("Mer"), chunk("haba"), DONE]))

    async def run() -> None:
        completion = await make_provider(chat).generate(request())
        assert completion.text == "Merhaba" and completion.metrics.output_tokens == 3

    asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "message", "error"),
    [
        (404, "model 'x' not found", LlmModelNotFoundError),
        (500, "model requires more system memory (12 GiB) than is available", LlmOutOfMemoryError),
        (500, "llama runner process has terminated: signal: killed", LlmLoadFailedError),
        (500, "something else", LlmError),
    ],
)
def test_runtime_errors_map_to_stable_codes(
    status: int, message: str, error: type[LlmError]
) -> None:
    def chat(_b: dict[str, Any]) -> httpx.Response:
        return httpx.Response(status, json={"error": message})

    async def run() -> None:
        with pytest.raises(error):
            await collect(make_provider(chat), request())

    asyncio.run(run())


def test_error_inside_the_stream_is_raised() -> None:
    def chat(_b: dict[str, Any]) -> httpx.Response:
        lines = [chunk("Mer"), json.dumps({"error": "out of memory: insufficient memory"})]
        return httpx.Response(200, stream=SlowStream(lines))

    async def run() -> None:
        with pytest.raises(LlmOutOfMemoryError):
            await collect(make_provider(chat), request())

    asyncio.run(run())


@pytest.mark.parametrize(
    "lines",
    [["not json"], ['["a list"]'], [chunk("yarım")]],  # garbage, wrong type, no done
)
def test_invalid_stream_is_rejected(lines: list[str]) -> None:
    def chat(_b: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, stream=SlowStream(lines))

    async def run() -> None:
        with pytest.raises(LlmInvalidResponseError):
            await collect(make_provider(chat), request())

    asyncio.run(run())


def test_cancellation_stops_the_stream_and_closes_the_connection() -> None:
    stream = SlowStream([chunk(f"t{i}") for i in range(200)] + [DONE], delay=0.02)

    def chat(_b: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def run() -> None:
        provider = make_provider(chat)
        received: list[str] = []
        with pytest.raises(LlmCancelledError):
            async for event in provider.stream(request()):
                if isinstance(event, TextDelta):
                    received.append(event.text)
                    if len(received) == 3:
                        assert provider.cancel("r1")
        assert len(received) == 3
        assert stream.closed
        assert not provider.cancel("r1")  # registry cleaned up

    asyncio.run(run())


def test_cancellation_while_the_model_is_still_loading() -> None:
    stream = SlowStream([chunk("geç"), DONE], first_delay=5.0)

    def chat(_b: dict[str, Any]) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    async def run() -> None:
        provider = make_provider(chat)

        async def cancel_soon() -> None:
            await asyncio.sleep(0.1)
            provider.cancel("r1")

        canceller = asyncio.create_task(cancel_soon())
        with pytest.raises(LlmCancelledError):
            await asyncio.wait_for(collect(provider, request()), timeout=2)
        await canceller

    asyncio.run(run())


def test_first_token_and_idle_timeouts() -> None:
    async def run() -> None:
        slow_start = make_provider(
            lambda _b: httpx.Response(200, stream=SlowStream([DONE], first_delay=2)),
            first_token_timeout=0.1,
        )
        with pytest.raises(LlmTimeoutError):
            await collect(slow_start, request())
        stalls = make_provider(
            lambda _b: httpx.Response(200, stream=SlowStream([chunk("a"), DONE], delay=2)),
            idle_timeout=0.1,
        )
        with pytest.raises(LlmTimeoutError):
            await collect(stalls, request())

    asyncio.run(run())


@pytest.mark.parametrize(
    "name",
    [
        "gemma4:cloud",
        "gemma4:31b-cloud",
        "registry.example.com/library/qwen3:8b",
        "user/model:latest",
        "../etc",
        "Qwen3:8B",
        "",
        "a" * 200,
    ],
)
def test_cloud_registry_and_malformed_model_names_are_refused(name: str) -> None:
    calls: list[tuple[str, str]] = []

    async def run() -> None:
        provider = make_provider(lambda _b: httpx.Response(500), calls=calls)
        with pytest.raises(LlmModelNotAllowedError):
            await collect(provider, ChatRequest(model=name, messages=[]))
        with pytest.raises(LlmModelNotAllowedError):
            await provider.load(name, num_ctx=4096)

    asyncio.run(run())
    assert ("POST", "/api/chat") not in calls  # refused before any request


def test_uninstalled_model_is_refused_without_pulling() -> None:
    calls: list[tuple[str, str]] = []

    async def run() -> None:
        provider = make_provider(lambda _b: httpx.Response(500), calls=calls)
        with pytest.raises(LlmModelNotFoundError):
            await collect(provider, ChatRequest(model="qwen3:8b-q4_K_M", messages=[]))

    asyncio.run(run())
    assert ("POST", "/api/chat") not in calls


def test_only_allowlisted_endpoints_can_be_called() -> None:
    assert ("POST", "/api/pull") not in ALLOWED_ENDPOINTS
    paths = {path for _, path in ALLOWED_ENDPOINTS}
    for forbidden in ("/api/pull", "/api/push", "/api/create", "/api/copy", "/api/delete"):
        assert forbidden not in paths

    async def run() -> None:
        provider = make_provider()
        with pytest.raises(LlmError, match="not allowed"):
            await provider._request("POST", "/api/pull", {"model": "x"})  # pyright: ignore[reportPrivateUsage]

    asyncio.run(run())
    assert check_model_name(MODEL) == MODEL


def test_load_and_unload_use_the_chat_endpoint() -> None:
    bodies: list[dict[str, Any]] = []

    def chat(body: dict[str, Any]) -> httpx.Response:
        bodies.append(body)
        return httpx.Response(200, json={"done": True, "load_duration": 1_500_000_000})

    async def run() -> None:
        provider = make_provider(chat)
        assert await provider.load(MODEL, num_ctx=8192, keep_alive="10m") == 1500
        await provider.unload(MODEL)

    asyncio.run(run())
    assert bodies[0]["options"] == {"num_ctx": 8192} and bodies[0]["keep_alive"] == "10m"
    assert bodies[1]["keep_alive"] == 0 and bodies[1]["messages"] == []
