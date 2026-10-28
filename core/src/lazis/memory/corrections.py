""" "Hayır, Ahmet değil Mehmet demek istedim." — the user corrects what they just said (Phase 9).

Deterministic, no model call: the words name what was wrong and what is right. What was
learned from the user's last messages in this conversation (the evidence says which records
those are) is corrected:

* the wrong word is **who it was about** → those records move to the person meant (the one
  stored with that name, or a new one; the user is asked when several share it). A person
  the wrong message created and nothing else uses is simply renamed;
* the wrong word is **a value** ("Hayır, Ankara değil İzmir") → the value is corrected.

Everything goes through one change set (the history keeps what it was). When those messages
have not been learned from yet, the correction waits for them (:func:`rename_refs`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, replace

from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory import text
from lazis.memory.extraction import Extracted, ExtractedRel
from lazis.memory.models import EntityRef
from lazis.storage.driver import Connection
from lazis.storage.unit_of_work import UnitOfWork

_WORD = r"[\wçğıöşüÇĞİÖŞÜ]+(?:['’][\wçğıöşü]+)?"
_CAP = r"[A-ZÇĞİÖŞÜ][\wçğıöşü]+(?:['’][\wçğıöşü]+)?"
# A second word only when it is a name too ("Ali Can"), never "demek" of "demek istedim".
_FIX = re.compile(
    rf"(?:^|[.!?]\s*)(?P<cue>(?i:(?:(?:hayır|yok|pardon|özür dilerim|aslında|yanlış oldu|"
    rf"yanlış söyledim)[,\s]*)+))?(?P<wrong>{_WORD}(?:\s{_CAP})?)\s+(?i:değil(?:di)?)[,\s]+"
    rf"(?P<right>{_WORD}(?:\s{_CAP})?)"
    rf"(?P<tail>\s+(?i:demek istedim|olacak(?:tı)?|dedim|kastettim|diyecektim))?"
)
MAX_AGE_S = 30 * 60
LOOKBACK = 2  # user messages before the correction


@dataclass(frozen=True)
class Fix:
    wrong: str
    right: str

    @property
    def wrong_key(self) -> str:
        return text.name_key(self.wrong)

    @property
    def right_key(self) -> str:
        return text.name_key(self.right)


def parse(message: str) -> Fix | None:
    """Only a correction in so many words: a cue ("Hayır, …") or an ending ("… demek
    istedim") — "Ahmet değil Mehmet geldi" is a statement, not a correction."""
    m = _FIX.search(message.strip())
    if m is None or not (m.group("cue") or m.group("tail")):
        return None
    wrong = re.split(r"['’]", m.group("wrong"), maxsplit=1)[0].strip()
    right = re.split(r"['’]", m.group("right"), maxsplit=1)[0].strip()
    if not wrong or not right or text.name_key(wrong) == text.name_key(right):
        return None
    return Fix(wrong, right)


@dataclass
class Result:
    kind: str  # "corrected" | "ambiguous" | "pending" | "nothing"
    lines: list[str]
    message_ids: tuple[str, ...] = ()
    options: tuple[str, ...] = ()


def recent_user_messages(conn: Connection, conversation_id: str, message_id: str) -> list[str]:
    row = conn.execute(
        "SELECT seq, created_at FROM messages WHERE id = ?", (message_id,)
    ).fetchone()
    if row is None:
        return []
    rows = conn.execute(
        "SELECT id FROM messages WHERE conversation_id = ? AND role = 'user' AND seq < ?"
        " AND julianday(?) - julianday(created_at) <= ? ORDER BY seq DESC LIMIT ?",
        (conversation_id, int(row[0]), str(row[1]), MAX_AGE_S / 86400, LOOKBACK),
    ).fetchall()
    return [str(r[0]) for r in rows]


def _learned_from(conn: Connection, message_ids: Sequence[str]) -> tuple[list[str], list[str]]:
    marks = ",".join("?" * len(message_ids))
    mems = [str(r[0]) for r in conn.execute(
        f"SELECT DISTINCT memory_id FROM memory_evidence WHERE source_type = 'message'"  # noqa: S608
        f" AND source_ref IN ({marks})", tuple(message_ids)).fetchall()]  # fmt: skip
    rels = [str(r[0]) for r in conn.execute(
        f"SELECT DISTINCT relationship_id FROM memory_relationship_evidence"  # noqa: S608
        f" WHERE source_type = 'message' AND source_ref IN ({marks})",
        tuple(message_ids)).fetchall()]  # fmt: skip
    return mems, rels


def _pending(conn: Connection, message_ids: Sequence[str]) -> list[str]:
    marks = ",".join("?" * len(message_ids))
    rows = conn.execute(
        f"SELECT user_message_id FROM memory_jobs WHERE user_message_id IN ({marks})"  # noqa: S608
        " AND status IN ('queued', 'deferred', 'running')",
        tuple(message_ids),
    ).fetchall()
    return [str(r[0]) for r in rows]


def apply(conn: Connection, conversation_id: str, message_id: str, fix: Fix, now: str) -> Result:
    ids = recent_user_messages(conn, conversation_id, message_id)
    if not ids:
        return Result("nothing", [])
    mem_ids, rel_ids = _learned_from(conn, ids)
    mems = [m for m in (repo.get_memory(conn, i) for i in mem_ids) if m is not None]
    rels = [r for r in (gs.get_relationship(conn, i) for i in rel_ids) if r is not None]
    subjects = {m.subject_id for m in mems if m.subject_id} | {
        e for r in rels for e in (r.source_id, r.target_id)
    }
    wrong_people = [
        e for e in (repo.get_entity(conn, s) for s in subjects if s)
        if e is not None and not e.is_user and text.name_key(e.name) == fix.wrong_key
    ]  # fmt: skip
    if wrong_people:
        return _move(conn, ids, wrong_people[0], fix, mems, rels, now)
    wrong_values = [
        m for m in mems
        if m.status == "active" and fix.wrong_key and fix.wrong_key in text.name_key(m.value)
    ]  # fmt: skip
    if wrong_values:
        return _revalue(conn, ids, wrong_values, fix, now)
    waiting = _pending(conn, ids)
    if waiting:
        return Result("pending", [], tuple(waiting))
    return Result("nothing", [])


def _move(conn: Connection, ids: Sequence[str], wrong: object, fix: Fix,
          mems: Sequence[object], rels: Sequence[object], now: str) -> Result:  # fmt: skip
    from lazis.memory.models import Entity, Memory, Relationship

    assert isinstance(wrong, Entity)
    mine = [m for m in mems if isinstance(m, Memory) and m.subject_id == wrong.id]
    my_rels = [r for r in rels if isinstance(r, Relationship)
               and wrong.id in (r.source_id, r.target_id)]  # fmt: skip
    candidates = [e for e in repo.list_entities(conn, limit=10_000)
                  if text.name_key(e.name) == fix.right_key and not e.is_user
                  and e.id != wrong.id]  # fmt: skip
    if len(candidates) > 1:
        return Result("ambiguous", [], tuple(ids),
                      tuple(f"{e.name} ({e.relation})" if e.relation else e.name
                            for e in candidates))  # fmt: skip
    only_here = _only_from(conn, wrong.id, ids)
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="kişi düzeltildi") as uow:
        if not candidates and only_here:
            # The wrong person exists only because of the message being corrected: rename it.
            before = uow.snapshot("memory_entities", wrong.id)
            repo.update_entity(conn, wrong.id, now=now, name=fix.right, relation=wrong.relation,
                               description=wrong.description)  # fmt: skip
            uow.record("memory_entities", wrong.id, "update", before)
            for m in mine:
                repo.reindex_memory(conn, m.id)
            return Result("corrected", [f"{fix.wrong} → {fix.right} (kişi adı)"], tuple(ids))
        if candidates:
            right_id = candidates[0].id
        else:
            ent = repo.insert_entity(conn, kind=wrong.kind, name=fix.right, relation=wrong.relation,
                                     description=None, now=now)  # fmt: skip
            uow.record("memory_entities", ent.id, "create", None)
            right_id = ent.id
        for m in mine:
            before = uow.snapshot("memories", m.id)
            repo.move_subject(conn, m.id, right_id, now)
            uow.record("memories", m.id, "update", before)
        for r in my_rels:
            before = uow.snapshot("memory_relationships", r.id)
            src = right_id if r.source_id == wrong.id else r.source_id
            tgt = right_id if r.target_id == wrong.id else r.target_id
            gs.repoint(conn, r.id, source_id=src, target_id=tgt, now=now)
            uow.record("memory_relationships", r.id, "update", before)
    n = len(mine) + len(my_rels)
    return Result("corrected", [f"{fix.wrong} → {fix.right} ({n} kayıt)"], tuple(ids))


def _only_from(conn: Connection, entity_id: str, ids: Sequence[str]) -> bool:
    """Everything known about the person came from these messages."""
    marks = ",".join("?" * len(ids))
    other = conn.execute(
        f"SELECT COUNT(*) FROM memories m JOIN memory_evidence v ON v.memory_id = m.id"  # noqa: S608
        f" WHERE m.subject_id = ? AND NOT (v.source_type = 'message' AND v.source_ref IN"
        f" ({marks}))", (entity_id, *ids)).fetchone()[0]  # fmt: skip
    other_rels = conn.execute(
        f"SELECT COUNT(*) FROM memory_relationships r JOIN memory_relationship_evidence v"  # noqa: S608
        f" ON v.relationship_id = r.id WHERE (r.source_id = ? OR r.target_id = ?) AND NOT"
        f" (v.source_type = 'message' AND v.source_ref IN ({marks}))",
        (entity_id, entity_id, *ids)).fetchone()[0]  # fmt: skip
    return int(other) == 0 and int(other_rels) == 0


def _revalue(conn: Connection, ids: Sequence[str], wrong: Sequence[object], fix: Fix,
             now: str) -> Result:  # fmt: skip
    from lazis.memory.models import Memory

    lines: list[str] = []
    with UnitOfWork(conn, kind="user_edit", actor="user", summary="değer düzeltildi") as uow:
        for m in wrong:
            assert isinstance(m, Memory)
            value = _swap(m.value, fix)
            content = _swap(m.content, fix)
            before = uow.snapshot("memories", m.id)
            repo.update_memory_text(conn, m, value=value, content=content, keywords=None,
                                    now=now, origin="user_edit", confidence=1.0)  # fmt: skip
            repo.add_evidence(conn, m.id, source_type="user_edit", source_ref=None,
                              quote=f"{fix.wrong} değil {fix.right}", now=now)  # fmt: skip
            uow.record("memories", m.id, "update", before)
            lines.append(f"{m.value} → {value}")
    return Result("corrected", lines, tuple(ids))


def _swap(s: str, fix: Fix) -> str:
    pattern = re.compile(re.escape(fix.wrong), re.IGNORECASE)
    out, n = pattern.subn(fix.right, s)
    if n:
        return out
    # The folded form differs ("Ankara'da" in the sentence, "ankara" in the key): word level.
    words = s.split()
    for i, w in enumerate(words):
        if text.name_key(w) == fix.wrong_key:
            words[i] = fix.right + w[len(re.split(r"['’]", w)[0]) :]
    return " ".join(words)


def rename_refs(facts: Sequence[Extracted], rels: Sequence[ExtractedRel], message_id: str,
                fix: Fix) -> tuple[list[Extracted], list[ExtractedRel]]:  # fmt: skip
    """A correction that arrived before its message was learned from: applied to what the
    model extracted from that message, before anything is written."""

    def swap(ref: EntityRef | None) -> EntityRef | None:
        if ref is not None and text.name_key(ref.name) == fix.wrong_key:
            return EntityRef(fix.right, ref.kind, ref.relation)
        return ref

    out_f = [
        replace(f, candidate=replace(f.candidate, entity=swap(f.candidate.entity)))
        if f.message_id == message_id else f
        for f in facts
    ]  # fmt: skip
    out_r = [
        replace(r, candidate=replace(r.candidate, source=swap(r.candidate.source),
                                     target=swap(r.candidate.target) or r.candidate.target))
        if r.message_id == message_id else r
        for r in rels
    ]  # fmt: skip
    return out_f, out_r


def to_json(fix: Fix) -> str:
    return json.dumps({"wrong": fix.wrong, "right": fix.right}, ensure_ascii=False)
