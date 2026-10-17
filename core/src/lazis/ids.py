"""ULID generation (sortable, locally generated identifiers) and UTC timestamps."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid(now_ms: int | None = None) -> str:
    """Return a 26-character ULID: 48-bit millisecond timestamp + 80 random bits."""
    ts = int(time.time() * 1000) if now_ms is None else now_ms
    value = (ts << 80) | secrets.randbits(80)
    chars: list[str] = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(chars))


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
