"""Startup secrets handed over by the desktop shell over stdin.

Protocol (one JSON line, then stdin stays open as the parent "lifeline"):

    {"version": 1, "session_token": "<64 hex>", "db_key": "<64 hex>"}

Secrets never travel through argv, environment variables or files. Python cannot guarantee
memory wiping; secrets are kept in a single place and their ``repr`` is redacted.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import select
import time
from dataclasses import dataclass, field

from lazis.errors import SecretsError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_MAX_LINE = 4096


@dataclass(frozen=True)
class SecretBytes:
    _value: bytes = field(repr=False)

    def reveal(self) -> bytes:
        return self._value

    def hex(self) -> str:
        return self._value.hex()

    def __repr__(self) -> str:
        return "SecretBytes(****)"

    __str__ = __repr__


@dataclass(frozen=True)
class StartupSecrets:
    session_token: str = field(repr=False)
    db_key: SecretBytes = field(repr=False)

    def __repr__(self) -> str:
        return "StartupSecrets(****)"

    def token_matches(self, candidate: str) -> bool:
        return hmac.compare_digest(self.session_token.encode(), candidate.encode())


def parse_secrets_line(line: bytes) -> StartupSecrets:
    try:
        payload = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise SecretsError("startup secrets line is not valid JSON") from None
    if not isinstance(payload, dict) or payload.get("version") != 1:  # pyright: ignore[reportUnknownMemberType]
        raise SecretsError("unsupported startup secrets protocol version")
    token = payload.get("session_token")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    key_hex = payload.get("db_key")  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    if not isinstance(token, str) or not _HEX64.match(token):
        raise SecretsError("session_token must be 64 lowercase hex characters")
    if not isinstance(key_hex, str) or not _HEX64.match(key_hex):
        raise SecretsError("db_key must be 64 lowercase hex characters")
    return StartupSecrets(session_token=token, db_key=SecretBytes(bytes.fromhex(key_hex)))


def read_secrets_from_fd(fd: int, timeout_seconds: float) -> StartupSecrets:
    """Read exactly one newline-terminated line from ``fd`` without over-reading."""
    deadline = time.monotonic() + timeout_seconds
    buffer = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise SecretsError("timed out waiting for startup secrets on stdin")
        ready, _, _ = select.select([fd], [], [], remaining)
        if not ready:
            continue
        chunk = os.read(fd, 1)  # byte-wise: the rest of stdin is the lifeline
        if not chunk:
            raise SecretsError("stdin closed before startup secrets were received")
        if chunk == b"\n":
            break
        buffer += chunk
        if len(buffer) > _MAX_LINE:
            raise SecretsError("startup secrets line too long")
    try:
        return parse_secrets_line(bytes(buffer))
    finally:
        buffer[:] = b"\x00" * len(buffer)
