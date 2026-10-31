"""Independent evidence for a learned preference (Phase 10A, ADR-0021; read by Phase 10B).

A learned communication preference needs at least three consistent signals in at least two
sessions (PERSONALITY_ENGINE §3). Records are not signals: the same preference said in other
words becomes two or three records (Phase 9, learning r01), one message can yield two records,
an explicit save and background learning read the same message, and a retry reads it again.
Counting records would turn one statement into "three signals". So a signal is counted from
its **source**, never from the records:

* one per user message, however many records (of this preference) it backs;
* the same words in another message (folded) are the same statement: counted once;
* only the user's own messages: an import (one statement in a file), an edit in the memory
  screen and a confirmation of LAZIS's own suggestion ("Evet") are not implicit signals;
* only active records whose value was not forgotten or rejected.

Which records belong to one preference is the caller's key (Phase 10B: the style dimension
and direction, such as ``verbosity:short`` — never the free text of the record).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

from lazis.memory import repository as repo
from lazis.memory import text
from lazis.storage.driver import Connection

MIN_SIGNALS = 3
MIN_SESSIONS = 2


@dataclass(frozen=True)
class Signal:
    key: str  # what is preferred ("verbosity:short")
    message_id: str
    session_id: str  # the conversation the message belongs to
    words: str  # the message, folded (two messages with the same words are one statement)


@dataclass(frozen=True)
class Tally:
    messages: int
    sessions: int

    @property
    def enough(self) -> bool:
        return self.messages >= MIN_SIGNALS and self.sessions >= MIN_SESSIONS


def tally(signals: Iterable[Signal]) -> dict[str, Tally]:
    statements: dict[str, set[str]] = {}
    sessions: dict[str, set[str]] = {}
    seen: dict[str, set[str]] = {}
    for s in signals:
        if s.message_id in seen.setdefault(s.key, set()):
            continue
        seen[s.key].add(s.message_id)
        statements.setdefault(s.key, set()).add(s.words or s.message_id)
        sessions.setdefault(s.key, set()).add(s.session_id)
    return {k: Tally(len(statements[k]), len(sessions[k])) for k in statements}


def from_records(conn: Connection, by_key: Mapping[str, Sequence[str]]) -> list[Signal]:
    """The signals behind the records of each preference key (memory ids)."""
    key = repo.fingerprint_key(conn)
    forgotten = repo.forgotten_fingerprints(conn)
    rejected = frozenset(
        str(r[0])
        for r in conn.execute(
            "SELECT fingerprint FROM memory_suppressions WHERE reason = 'rejected'"
        ).fetchall()
    )
    out: list[Signal] = []
    for pref, ids in by_key.items():
        for mid in dict.fromkeys(ids):
            m = repo.get_memory(conn, mid)
            if m is None or m.status != "active":
                continue
            fps = {
                repo.fingerprint_with(key, m.subject_id, m.predicate, m.value_key),
                repo.fingerprint_with(key, m.subject_id, m.predicate, "*"),
            }
            if fps & (forgotten | rejected):
                continue
            for ev in repo.evidence_for(conn, mid):
                if ev.source_type != "message" or ev.source_ref is None:
                    continue
                row = conn.execute(
                    "SELECT conversation_id, role, content FROM messages WHERE id = ?",
                    (ev.source_ref,),
                ).fetchone()
                if row is None or row[1] != "user":
                    continue
                words = " ".join(text.words(str(row[2])))
                out.append(Signal(pref, ev.source_ref, str(row[0]), words))
    return out
