"""Stdout handshake with the desktop shell (one JSON line, prefixed).

    LAZIS_READY {"protocol": 1, "port": 51234, "pid": 4242, ...}
    LAZIS_FATAL {"protocol": 1, "code": "database_key_invalid", "message": "..."}

Nothing secret is ever written to stdout. Logs go to files, not stdout.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from lazis.i18n import message_for

READY_PREFIX = "LAZIS_READY "
FATAL_PREFIX = "LAZIS_FATAL "
PROTOCOL = 1

EXIT_OK = 0
EXIT_FATAL = 3


def _emit(prefix: str, payload: dict[str, Any]) -> None:
    sys.stdout.write(
        prefix + json.dumps({"protocol": PROTOCOL, **payload}, ensure_ascii=False) + "\n"
    )
    sys.stdout.flush()


def emit_ready(**fields: Any) -> None:
    _emit(READY_PREFIX, fields)


def emit_fatal(code: str) -> None:
    _emit(FATAL_PREFIX, {"code": code, "message": message_for(code)})
