"""Fewer repeated openings and closings (Phase 10D, smallest version).

The previous reply's opening (when the user only greets) and its closing question are named in a
note for the next reply, which is asked not to say them again. A local read of the history: no
model call, nothing stored, the system prompt unchanged. Proactive topics are handled apart: a
topic is offered at most once and never again after it is turned down (``continuity``).
"""

from __future__ import annotations

import re

from lazis.memory.commands import NOTICE_END, NOTICE_START

MAX_QUOTE = 120  # longer sentences are content, not a set phrase
_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")


def note(previous_reply: str, *, greeting: bool) -> str:
    """Empty unless there is a set phrase worth naming."""
    parts = [p.strip() for p in _SPLIT.split(previous_reply) if p.strip()]
    if not parts:
        return ""
    first, last = parts[0], parts[-1]
    lines: list[str] = []
    if greeting and len(first) <= MAX_QUOTE:
        lines.append(f"Önceki yanıtına «{first}» diye başladın; selamını aynı cümleyle kurma.")
    if last.endswith("?") and len(last) <= MAX_QUOTE and not (greeting and last == first):
        lines.append(f"Önceki yanıtını «{last}» diye bitirdin; aynı kapanış sorusunu tekrarlama.")
    if not lines:
        return ""
    return "\n".join([NOTICE_START, *lines, NOTICE_END])
