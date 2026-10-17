"""Provider and chat API against a fake Ollama server over real loopback HTTP (no model).

Proves what mocks cannot: cancelling a generation closes the TCP stream so the runtime stops
working, a runtime that dies mid-answer is reported, and a closed port fails fast.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from lazis.errors import LlmCancelledError, LlmError, LlmUnavailableError
from lazis.providers.llm.ollama import OllamaProvider
from lazis.providers.llm.ports import ChatMessage, ChatRequest, GenerationOptions, TextDelta
from lazis.storage import StorageHandle
from tests.conftest import make_client

MODEL = "fake-tr:1b"


class FakeOllama:
    def __init__(self) -> None:
        self.app = FastAPI()
        self.disconnected = threading.Event()
        self.tokens_sent = 0
        self.mode = "normal"  # normal | die
        self.first_delay = 0.0
        app = self.app

        @app.get("/api/version")
        async def version() -> dict[str, str]:  # pyright: ignore[reportUnusedFunction]
            return {"version": "0.0-fake"}

        @app.get("/api/tags")
        async def tags() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return {"models": [{"name": MODEL, "digest": "d", "size": 1, "details": {}}]}

        @app.post("/api/show")
        async def show() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return {"capabilities": ["completion"]}

        @app.get("/api/ps")
        async def ps() -> dict[str, Any]:  # pyright: ignore[reportUnusedFunction]
            return {"models": []}

        @app.post("/api/chat")
        async def chat(request: Request) -> Any:  # pyright: ignore[reportUnusedFunction]
            body = await request.json()
            if body["model"] != MODEL:
                return JSONResponse(
                    {"error": f"model '{body['model']}' not found"}, status_code=404
                )

            async def stream() -> AsyncIterator[bytes]:
                try:
                    await asyncio.sleep(self.first_delay)  # a long prompt being processed
                    for i in range(200):
                        if self.mode == "die" and i == 3:
                            raise RuntimeError("runner crashed")  # connection drops mid-answer
                        self.tokens_sent += 1
                        line = {
                            "message": {"role": "assistant", "content": f"t{i} "},
                            "done": False,
                        }
                        yield (json.dumps(line) + "\n").encode()
                        await asyncio.sleep(0.02)
                    yield (
                        json.dumps({"done": True, "eval_count": 200, "eval_duration": 1}) + "\n"
                    ).encode()
                except asyncio.CancelledError:
                    self.disconnected.set()
                    raise

            return StreamingResponse(stream(), media_type="application/x-ndjson")


@pytest.fixture
def fake() -> Iterator[tuple[FakeOllama, str]]:
    server_impl = FakeOllama()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    config = uvicorn.Config(server_impl.app, log_config=None, lifespan="off")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    yield server_impl, f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(5)


def _req(request_id: str = "r-1") -> ChatRequest:
    return ChatRequest(
        MODEL, [ChatMessage("user", "Merhaba")], GenerationOptions(num_ctx=4096), request_id
    )


def test_cancel_closes_the_stream_and_the_runtime_stops(fake: tuple[FakeOllama, str]) -> None:
    server, url = fake

    async def run() -> int:
        provider = OllamaProvider(url)
        seen = 0
        with pytest.raises(LlmCancelledError):
            async for event in provider.stream(_req()):
                if isinstance(event, TextDelta):
                    seen += 1
                    if seen == 5:
                        provider.cancel("r-1")
        await provider.aclose()
        return seen

    seen = asyncio.run(run())
    assert seen == 5
    assert server.disconnected.wait(3), "runtime kept generating after cancel"
    sent_at_cancel = server.tokens_sent
    time.sleep(0.3)
    assert server.tokens_sent - sent_at_cancel <= 1  # no further work


def test_runtime_dying_mid_answer_is_an_error(fake: tuple[FakeOllama, str]) -> None:
    server, url = fake
    server.mode = "die"

    async def run() -> None:
        provider = OllamaProvider(url)
        with pytest.raises(LlmError):
            async for _ in provider.stream(_req()):
                pass
        await provider.aclose()

    asyncio.run(run())


def test_closed_port_fails_fast() -> None:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing listens here now

    async def run() -> None:
        provider = OllamaProvider(f"http://127.0.0.1:{port}")
        assert (await provider.health()).error_code == "llm_unavailable"
        t0 = time.monotonic()
        with pytest.raises(LlmUnavailableError):
            async for _ in provider.stream(_req()):
                pass
        assert time.monotonic() - t0 < 3
        await provider.aclose()

    asyncio.run(run())


def test_chat_api_streams_from_the_runtime_over_http(
    fake: tuple[FakeOllama, str], tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    _, url = fake
    client = make_client(tmp_path, storage, token, llm=OllamaProvider(url))
    body = {
        "model": MODEL,
        "request_id": "req-http-01",
        "messages": [{"role": "user", "content": "Merhaba"}],
    }
    response = client.post(
        "/api/v1/chat/stream", json=body, headers={"Authorization": f"Bearer {token}"}
    )
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]["type"] == "start" and events[-1]["type"] == "done"
    assert len([e for e in events if e["type"] == "delta"]) == 200
    missing = client.post(
        "/api/v1/chat/stream",
        json={**body, "model": "other:1b"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert missing.status_code == 404


def test_slow_first_token_is_not_cut_by_the_http_read_timeout(fake: tuple[FakeOllama, str]) -> None:
    """Regression: a 12K-token prompt on a 14B model took > 60 s before the first byte and the
    transport read timeout (meant for short calls) aborted it."""
    server, url = fake
    server.first_delay = 1.5

    async def run() -> int:
        provider = OllamaProvider(url, request_timeout=0.5, first_token_timeout=10)
        n = 0
        async for event in provider.stream(_req("r-slow")):
            if isinstance(event, TextDelta):
                n += 1
        await provider.aclose()
        return n

    assert asyncio.run(run()) == 200
