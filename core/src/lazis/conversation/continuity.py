"""A topic of the user's own, offered once, on a greeting after a long gap (Phase 10C, first
version).

After at least :data:`MIN_GAP` of silence, when the user only says hello, the reply may end with
one fixed short question about one topic. If nothing is safe to offer, the reply is a plain
greeting.

The model writes none of it, so it cannot make a claim or a promise, and no model call is added:
this is a local read on a greeting, after the reply. Everything goes through the reply guards, so
what is shown is what is stored. Nothing is scheduled, sent or done for the user.

Only the user's own goals and interests qualify, as they said them and recently. Never a plan, a
date, an amount, health, or anyone else: a stale or doubtful follow-up is worse than none. A topic
is offered once, whether taken up, turned down or ignored, so no reply has to be understood. Only
ids are kept, in ``app_meta``, and no text. What the user asks to forget stops being offered
through the gate in :mod:`lazis.memory.proactive`.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from lazis.memory import proactive, relations, temporal, text
from lazis.memory import repository as repo
from lazis.memory.claims import fold
from lazis.memory.models import Memory
from lazis.storage.driver import Connection

MIN_GAP = timedelta(hours=6)
MAX_AGE = timedelta(days=30)  # older than this, it may no longer be current
MIN_CONFIDENCE = 0.8
MAX_CHARS = 40
MAX_WORDS = 5
_PREDICATES = ("goal", "interest")
_ORIGINS = frozenset({"stated", "requested", "user_edit", "confirmed"})
_META_KEY = "continuity_offered"
_MAX_KEPT = 500
_GREETING = re.compile(
    r"(?:merhaba|merhabalar|selam|selamlar|slm|gunaydin|tunaydin|iyi (?:sabahlar|gunler|aksamlar)|"
    r"hey|nasilsin|naber|ne haber|lazis|efendim)"
)
_HELLO = re.compile(r"merhaba|selam|slm|gunaydin|tunaydin|iyi (?:sabahlar|gunler|aksamlar)|hey")
# The user's own doubt, in the words kept as evidence: a stored certainty is not enough (REL-001).
_DOUBT = re.compile(
    r"\b(?:galiba|belki|sanirim|muhtemel\w*|kesin degil|belli degil|emin degil\w*|olabilir|"
    r"ihtimal\w*|henuz|acaba|dusunuyor\w*)\b"
)
# In a topic itself: a date, an amount or a time makes it a plan or a figure.
_NOT_A_TOPIC = re.compile(
    r"\d|\b(?:ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik|"
    r"pazartesi|sali|carsamba|persembe|cuma|cumartesi|pazar|yarin|bugun|haftaya)\w*|"
    r"\b(?:tl|lira|euro|dolar|bin|milyon)\b"
)


def is_greeting(message: str) -> bool:
    """Only a hello: "Selam, bütçem neydi?" is a question and "Günaydın" is a greeting."""
    f = " ".join(re.findall(r"\w+", fold(message)))
    if not f or len(f.split()) > 5 or _HELLO.search(f) is None:
        return False
    return not _GREETING.sub(" ", f).strip()


def sentence(value: str, *, address: str = "siz") -> str:
    ask = "ister misin" if address == "sen" else "ister misiniz"
    return f"«{value}» konusuna devam etmek {ask}?"


def _at(iso: str) -> datetime | None:
    try:
        moment = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)


def long_gap(conn: Connection, *, message_id: str, now: str) -> bool:
    """The user's last message before this one, in any session, is at least MIN_GAP old. No
    earlier message means nothing to come back to."""
    row = conn.execute(
        "SELECT created_at FROM messages WHERE role = 'user' AND id != ?"
        " ORDER BY created_at DESC LIMIT 1",
        (message_id,),
    ).fetchone()
    moment, last = _at(now), _at(str(row[0])) if row is not None else None
    return moment is not None and last is not None and moment - last >= MIN_GAP


def _offered(conn: Connection) -> list[str]:
    row = conn.execute("SELECT value FROM app_meta WHERE key = ?", (_META_KEY,)).fetchone()
    if row is None:
        return []
    try:
        ids: Any = json.loads(str(row[0]))
    except ValueError:
        return []
    if not isinstance(ids, list):
        return []
    return [str(i) for i in ids]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def mark_offered(conn: Connection, memory_id: str) -> None:
    ids = [*_offered(conn), memory_id][-_MAX_KEPT:]
    conn.execute(
        "INSERT INTO app_meta (key, value) VALUES (?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (_META_KEY, json.dumps(ids)),
    )


def _names_someone(conn: Connection, value: str) -> bool:
    """A relative or a stored person in the topic makes it about someone else too."""
    words = text.words(value)
    if relations.types_in(words):
        return True
    keys = text.candidate_keys(words)
    return any(k in keys and text.mentions_name(words, k) for k, _ in repo.alias_index(conn))


def _safe_topic(value: str) -> bool:
    words = text.words(value)
    return (
        0 < len(words) <= MAX_WORDS
        and len(value) <= MAX_CHARS
        and "\n" not in value
        and not re.search(r"[\"“”«»`]", value)
        and _NOT_A_TOPIC.search(fold(value)) is None
    )


def _usable(conn: Connection, m: Memory, *, now: datetime) -> bool:
    updated = _at(m.updated_at)
    if (
        m.subject_id is not None
        or m.sensitivity != "normal"
        or m.origin not in _ORIGINS
        or m.confidence < MIN_CONFIDENCE
        or m.event_time is not None
        or m.valid_to is not None
        or updated is None
        or now - updated > MAX_AGE
        or not _safe_topic(m.value)
        or _names_someone(conn, m.value)
    ):
        return False
    quotes = [e.quote for e in repo.evidence_for(conn, m.id) if e.quote]
    # Its source must be there, in the user's words, certain, and about the present.
    return bool(quotes) and all(
        _DOUBT.search(fold(q)) is None and temporal.tense(q) == "current" for q in quotes
    )


def choose(conn: Connection, *, now: str) -> Memory | None:
    """The topic to offer, or None. The most important, then the newest."""
    moment = _at(now)
    if moment is None:
        return None
    gate = proactive.load(conn)
    done = set(_offered(conn))
    found = [
        m
        for p in _PREDICATES
        for m in repo.memories_for_subject(conn, None, predicate=p)
        if m.id not in done and gate.memory(m) is None and _usable(conn, m, now=moment)
    ]
    found.sort(key=lambda m: (m.importance, m.updated_at), reverse=True)
    return found[0] if found else None
