"""Real backend process (under the real OS sandbox) + real Ollama + a real model.

Opt-in: ``make test-ollama`` (needs Ollama on 127.0.0.1:11434 and an installed model; the
model can be chosen with LAZIS_TEST_MODEL). Excluded from ``make check`` so the default suite
stays deterministic and offline.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import time
from pathlib import Path

import httpx
import pytest

from tests.conftest import REPO_ROOT
from tests.process_helpers import Backend, start_backend

pytestmark = pytest.mark.ollama
PROFILE = REPO_ROOT / "apps/desktop/src-tauri/sandbox/backend.sb"


def _model() -> str:
    try:
        tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=2).json()["models"]
    except (httpx.HTTPError, KeyError):
        pytest.skip("Ollama is not running on 127.0.0.1:11434")
    names = [m["name"] for m in tags]
    wanted = os.environ.get("LAZIS_TEST_MODEL") or (names[0] if names else "")
    if wanted not in names:
        pytest.skip(f"model {wanted!r} is not installed")
    return wanted


def _backend(tmp_path: Path) -> Backend:
    prefix = ["/usr/bin/sandbox-exec", "-f", str(PROFILE)] if sys.platform == "darwin" else []
    backend = start_backend(tmp_path, prefix=prefix, extra_args=["--require-os-sandbox"])
    assert backend.fatal is None, backend.outputs()
    return backend


def _stream_request(backend: Backend, model: str, text: str, request_id: str) -> httpx.Request:
    body = {
        "model": model,
        "request_id": request_id,
        "messages": [{"role": "user", "content": text}],
        "options": {"context": "short", "max_tokens": 600},
    }
    return httpx.Request(
        "POST",
        f"http://127.0.0.1:{backend.port}/api/v1/chat/stream",
        json=body,
        headers={"Authorization": f"Bearer {backend.token}"},
    )


def test_sandboxed_backend_streams_turkish_from_the_local_model(tmp_path: Path) -> None:
    model = _model()
    backend = _backend(tmp_path)
    try:
        status = backend.get("/api/v1/llm/status").json()
        assert status["runtime"]["available"] is True and status["cloud_inference"] == "disabled"
        with httpx.Client(timeout=300) as client:
            response = client.send(
                _stream_request(
                    backend, model, "Türkiye'nin başkenti neresidir? Tek kelime.", "live-0001"
                ),
                stream=True,
            )
            events = [json.loads(line) for line in response.iter_lines() if line]
        assert events[0]["type"] == "start" and events[-1]["type"] == "done", events[-1]
        text = "".join(e["text"] for e in events if e["type"] == "delta")
        assert "ankara" in text.lower()
        assert events[-1]["metrics"]["output_tokens"] > 0
        assert backend.close_lifeline() == 0
        log = (backend.log_dir / "core.log").read_text()
        assert (
            "Türkiye'nin başkenti" not in log and "Ankara" not in log
        )  # nothing of the chat logged
    finally:
        if backend.proc.poll() is None:
            backend.proc.kill()


def test_client_disconnect_stops_the_generation(tmp_path: Path) -> None:
    model = _model()
    backend = _backend(tmp_path)
    try:
        with httpx.Client(timeout=300) as client:
            response = client.send(
                _stream_request(
                    backend, model, "İstanbul'un tarihini çok uzun anlat.", "live-0002"
                ),
                stream=True,
            )
            deltas = 0
            for line in response.iter_lines():
                if line and json.loads(line)["type"] == "delta":
                    deltas += 1
                    if deltas == 10:
                        break
            response.close()  # the UI's AbortController does the same
        # The backend frees the generation slot quickly: a new request is accepted, not 409.
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with httpx.Client(timeout=300) as client:
                r = client.send(
                    _stream_request(backend, model, "Merhaba", "live-0003"), stream=True
                )
                first = next(json.loads(line) for line in r.iter_lines() if line)
                r.close()
            if first.get("code") != "llm_busy":
                break
            time.sleep(0.3)
        assert first["type"] == "start", first
        assert backend.close_lifeline() == 0
        log = (backend.log_dir / "core.log").read_text()
        outcomes = [
            json.loads(line).get("outcome") for line in log.splitlines() if "llm.generation" in line
        ]
        assert "aborted" in outcomes or "cancelled" in outcomes, outcomes
    finally:
        if backend.proc.poll() is None:
            backend.proc.kill()


def test_shutdown_during_generation_is_clean(tmp_path: Path) -> None:
    model = _model()
    backend = _backend(tmp_path)
    try:
        sock = socket.create_connection(("127.0.0.1", backend.port))
        req = _stream_request(backend, model, "Bana çok uzun bir masal anlat.", "live-0004")
        head = f"POST {req.url.raw_path.decode()} HTTP/1.1\r\nHost: 127.0.0.1:{backend.port}\r\n"
        head += f"Authorization: Bearer {backend.token}\r\nContent-Type: application/json\r\n"
        head += f"Content-Length: {len(req.content)}\r\nConnection: close\r\n\r\n"
        sock.sendall(head.encode() + req.content)
        sock.settimeout(120)
        received = b""
        while received.count(b'"delta"') < 5:
            chunk = sock.recv(4096)
            assert chunk, "stream ended early"
            received += chunk
        t0 = time.monotonic()
        assert backend.close_lifeline(timeout=20) == 0  # graceful exit while generating
        assert time.monotonic() - t0 < 15
        sock.close()
        log = (backend.log_dir / "core.log").read_text()
        assert "storage.closed" in log and "app.stopped" in log
    finally:
        if backend.proc.poll() is None:
            backend.proc.kill()
