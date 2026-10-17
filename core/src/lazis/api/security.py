"""Local API protection (pure ASGI middleware).

Threat model (SECURITY_MODEL §5.2): binding to 127.0.0.1 is *not* authentication. Any local
process can connect to a loopback port, and a malicious web page in a browser can try
DNS-rebinding or cross-origin requests. Therefore every request must pass, in order:

1. rate limit and concurrency are bounded (token bucket + uvicorn ``limit_concurrency``)
2. Host header == the exact loopback authority we bound to (defeats DNS rebinding)
3. Origin, if present, is an allowed desktop origin (defeats browser-based CSRF)
4. ``Authorization: Bearer <per-launch token>`` compared in constant time
5. request bodies are capped

CORS preflights from allowed origins are answered without a token (browsers never attach
credentials to preflights); everything else requires the token. WebSocket connections are
refused outright until an authenticated WebSocket endpoint exists (P3).

Limits (SECURITY_MODEL §5.2): this authenticates the *desktop app*, not the user. Another
process running as the same macOS user cannot read the token from argv, environment, logs or
disk, but it can still use the port (rate-limited, 401 without the token) and, with enough
privileges (debugging rights, accessibility control of the window), act through the app.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from lazis.errors import (
    AuthError,
    HostNotAllowedError,
    LazisError,
    OriginNotAllowedError,
    RateLimitedError,
    RequestTooLargeError,
)
from lazis.i18n import message_for
from lazis.ids import new_ulid
from lazis.observability.logging import get_logger, log_event

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

_log = get_logger("api.security")

SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"cache-control", b"no-store"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"DENY"),
)


class TokenBucket:
    def __init__(self, rate: float, burst: int) -> None:
        self._rate = rate
        self._capacity = float(burst)
        self._tokens = float(burst)
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def allow(self) -> bool:
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._capacity, self._tokens + (now - self._updated) * self._rate)
            self._updated = now
            if self._tokens >= 1:
                self._tokens -= 1
                return True
            return False


def error_payload(code: str, recoverable: bool, request_id: str) -> bytes:
    body = {
        "error": {
            "code": code,
            "message": message_for(code),
            "recoverable": recoverable,
            "request_id": request_id,
        }
    }
    return json.dumps(body, ensure_ascii=False).encode("utf-8")


class LocalApiGuard:
    def __init__(
        self,
        app: ASGIApp,
        *,
        token_matches: Callable[[str], bool],
        allowed_host: Callable[[], str],
        allowed_origins: frozenset[str],
        max_request_bytes: int,
        bucket: TokenBucket,
        on_denied: Callable[[str], None] | None = None,
    ) -> None:
        self._app = app
        self._token_matches = token_matches
        self._allowed_host = allowed_host
        self._allowed_origins = allowed_origins
        self._max_bytes = max_request_bytes
        self._bucket = bucket
        self._on_denied = on_denied

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            # No WebSocket endpoint exists yet. Until one is added together with its own
            # authentication (P3), every upgrade is refused — never passed through unchecked.
            self._report(AuthError("websocket not available"), scope)
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":  # lifespan
            await self._app(scope, receive, send)
            return

        request_id = new_ulid()
        scope.setdefault("state", {})["request_id"] = request_id
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        origin = headers.get("origin")
        cors_origin = origin if origin in self._allowed_origins else None

        try:
            if not self._bucket.allow():
                raise RateLimitedError()
            if headers.get("host") != self._allowed_host():
                raise HostNotAllowedError()
            if origin is not None and cors_origin is None:
                raise OriginNotAllowedError()
            if scope["method"] == "OPTIONS":
                await self._preflight(send, cors_origin)
                return
            if not self._authorized(headers.get("authorization", "")):
                raise AuthError()
            content_length = headers.get("content-length")
            if content_length is not None and (
                not content_length.isdigit() or int(content_length) > self._max_bytes
            ):
                raise RequestTooLargeError()
        except LazisError as exc:
            self._report(exc, scope)
            await self._reject(send, exc, request_id, cors_origin)
            return

        await self._app(scope, self._limited_receive(receive), self._wrap_send(send, cors_origin))

    # ------------------------------------------------------------------------------------
    def _authorized(self, header: str) -> bool:
        scheme, _, token = header.partition(" ")
        return scheme.lower() == "bearer" and bool(token) and self._token_matches(token.strip())

    def _report(self, exc: LazisError, scope: Scope) -> None:
        log_event(
            _log,
            logging.WARNING,
            "api.request_denied",
            code=exc.code,
            method=scope.get("method"),
            path=scope.get("path"),
        )
        if self._on_denied is not None and isinstance(
            exc, AuthError | OriginNotAllowedError | HostNotAllowedError
        ):
            self._on_denied(exc.code)

    def _limited_receive(self, receive: Receive) -> Receive:
        received = 0
        limit = self._max_bytes

        async def _receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise RequestTooLargeError()
            return message

        return _receive

    def _cors_headers(self, origin: str | None) -> list[tuple[bytes, bytes]]:
        if origin is None:
            return []
        return [
            (b"access-control-allow-origin", origin.encode("latin-1")),
            (b"vary", b"Origin"),
        ]

    def _wrap_send(self, send: Send, origin: str | None) -> Send:
        extra = [*SECURITY_HEADERS, *self._cors_headers(origin)]

        async def _send(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [*message.get("headers", []), *extra]
            await send(message)

        return _send

    async def _preflight(self, send: Send, origin: str | None) -> None:
        headers = [
            *SECURITY_HEADERS,
            *self._cors_headers(origin),
            (b"access-control-allow-methods", b"GET, POST, PATCH, DELETE"),
            (b"access-control-allow-headers", b"authorization, content-type"),
            (b"access-control-max-age", b"600"),
        ]
        await send({"type": "http.response.start", "status": 204, "headers": headers})
        await send({"type": "http.response.body", "body": b""})

    async def _reject(
        self, send: Send, exc: LazisError, request_id: str, origin: str | None
    ) -> None:
        body = error_payload(exc.code, exc.recoverable, request_id)
        headers = [
            (b"content-type", b"application/json; charset=utf-8"),
            (b"content-length", str(len(body)).encode()),
            *SECURITY_HEADERS,
            *self._cors_headers(origin),
        ]
        await send({"type": "http.response.start", "status": exc.http_status, "headers": headers})
        await send({"type": "http.response.body", "body": body})
