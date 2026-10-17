"""Second line of defense against secrets in logs.

The first line is simply never logging secrets. This module additionally scrubs every log
record for (a) secrets registered at runtime (session token, database key) and (b) generic
secret-shaped patterns (long hex strings, bearer tokens, recovery codes).
"""

from __future__ import annotations

import re
import threading

REDACTED = "[REDACTED]"

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\b[0-9a-fA-F]{48,}\b"),
    re.compile(r"(?i)\bLZR1(?:[-\s]?[0-9A-Z]{3,5}){6,}\b"),
    re.compile(r"(?i)x'[0-9a-f]{32,}'"),
)


class SecretRegistry:
    """Thread-safe set of exact secret strings that must never appear in output."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._secrets: tuple[str, ...] = ()

    def register(self, value: str) -> None:
        if len(value) < 8:  # too short to scrub safely; real secrets here are 64 hex chars
            return
        with self._lock:
            if value not in self._secrets:
                # Longest first so overlapping secrets are fully removed.
                self._secrets = tuple(sorted((*self._secrets, value), key=len, reverse=True))

    def scrub(self, text: str) -> str:
        for secret in self._secrets:
            if secret in text:
                text = text.replace(secret, REDACTED)
        for pattern in _PATTERNS:
            text = pattern.sub(REDACTED, text)
        return text
