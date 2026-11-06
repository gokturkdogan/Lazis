"""The research helper process: ``python -I -B -m lazis.providers.web.helper --socket PATH``.

Started by the desktop shell under ``sandbox/egress.sb`` (Phase 12, ADR-0009). It listens on one
Unix socket (mode 0600) and answers one JSON request per connection:

* ``{"op": "ping"}`` → ``{"ok": true}``
* ``{"op": "research", "query": "..."}`` → ``{"ok": true, "pages": [{title, url, lang, text}]}``
  or ``{"ok": false, "code": "<reason>"}``

It holds no secrets, reads no files of the user and writes nothing but its socket; it never
logs a query or page text. It stops when its stdin closes (the shell's lifeline).
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import sys
import threading
from collections.abc import Callable, Sequence
from typing import Any

from lazis.providers.web import guard, wikipedia

READY = "LAZIS_EGRESS_READY"
MAX_REQUEST_BYTES = 8192
MAX_QUERY_CHARS = 300


def handle(request: Any, fetcher_factory: Callable[[], wikipedia.Fetcher]) -> dict[str, Any]:
    if not isinstance(request, dict):
        return {"ok": False, "code": "bad_request"}
    op = request.get("op")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if op == "ping":
        return {"ok": True}
    if op != "research":
        return {"ok": False, "code": "bad_request"}
    query = request.get("query")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY_CHARS:
        return {"ok": False, "code": "bad_request"}
    try:
        pages = wikipedia.research(query.strip(), fetcher_factory())
    except guard.EgressRefused as exc:
        return {"ok": False, "code": exc.code}
    except PermissionError:
        return {"ok": False, "code": "refused"}
    except Exception:
        return {"ok": False, "code": "network"}
    return {
        "ok": True,
        "pages": [{"title": p.title, "url": p.url, "lang": p.lang, "text": p.text} for p in pages],
    }


def _read_line(conn: socket.socket) -> bytes:
    data = bytearray()
    while b"\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > MAX_REQUEST_BYTES:
            raise ValueError("request too large")
    return bytes(data).split(b"\n", 1)[0]


def _serve_one(conn: socket.socket, fetcher_factory: Callable[[], wikipedia.Fetcher]) -> None:
    with conn:
        conn.settimeout(30)
        try:
            request = json.loads(_read_line(conn))
        except (ValueError, OSError):
            reply: dict[str, Any] = {"ok": False, "code": "bad_request"}
        else:
            reply = handle(request, fetcher_factory)
        with contextlib.suppress(OSError):
            conn.sendall(json.dumps(reply, ensure_ascii=False).encode() + b"\n")


def serve(
    path: str,
    *,
    fetcher_factory: Callable[[], wikipedia.Fetcher] = wikipedia.Fetcher,
    stop: threading.Event | None = None,
    ready: Callable[[], None] = lambda: None,
) -> None:
    """Listen on ``path`` until ``stop`` is set. One request at a time: research is rare."""
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    old = os.umask(0o177)
    try:
        server.bind(path)
    finally:
        os.umask(old)
    server.listen(4)
    server.settimeout(0.5)
    ready()
    try:
        while stop is None or not stop.is_set():
            try:
                conn, _ = server.accept()
            except TimeoutError:
                continue
            _serve_one(conn, fetcher_factory)
    finally:
        server.close()
        with contextlib.suppress(FileNotFoundError):
            os.unlink(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="lazis-egress")
    parser.add_argument("--socket", required=True)
    args = parser.parse_args(argv)
    guard.install()
    stop = threading.Event()

    def lifeline() -> None:
        with contextlib.suppress(OSError):
            while sys.stdin.buffer.read(4096):
                pass
        stop.set()

    threading.Thread(target=lifeline, name="egress-lifeline", daemon=True).start()
    serve(args.socket, stop=stop, ready=lambda: print(READY, flush=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
