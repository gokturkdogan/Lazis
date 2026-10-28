"""Memory quality checks (Phase 9): suggestions, never changes.

A read-only scan of what is stored, for the user to look at — in priority order, so the most
important doubt comes first and small things do not nag:

* ``conflict`` — two current values for one single-valued fact ("Mehmet'in yaşadığı şehirle
  ilgili iki farklı bilgi var. Hangisi güncel?"), or a conflict still waiting;
* ``duplicate`` — two current values that say nearly the same thing;
* ``stale`` — a fact that changes over time (city, work, phone…) not confirmed for a year;
* ``ambiguous_person`` — two people with one name that are neither told apart nor merged;
* ``no_evidence`` — a current fact without any source left (it cannot say where it came from);
* ``uncertain`` — a fact the user was unsure about ("galiba") or that was inferred.

Nothing here edits, merges or deletes: the user decides (edit, forget, "aynı kişi" / "farklı
kişiler", or hide the suggestion — :func:`dismiss`, remembered by a content-free fingerprint).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from lazis.memory import graphstore as gs
from lazis.memory import importance, registry, text
from lazis.memory import repository as repo
from lazis.memory.models import Entity, Memory
from lazis.storage.driver import Connection

Kind = Literal["conflict", "duplicate", "stale", "ambiguous_person", "no_evidence", "uncertain"]
_KIND_WEIGHT: dict[Kind, int] = {"conflict": 0, "ambiguous_person": 1, "duplicate": 2,
                                 "stale": 3, "uncertain": 4, "no_evidence": 5}  # fmt: skip
VOLATILE = frozenset({"location", "employer", "occupation", "phone", "computer",
                      "project_status", "address"})  # fmt: skip
STALE_AFTER_DAYS = 365
DUPLICATE_SIMILARITY = 0.6


@dataclass(frozen=True)
class Finding:
    id: str  # fingerprint (kind + ids, hashed)
    kind: Kind
    priority: int  # lower first
    subject: str  # who it is about, as the user reads it ("Kullanıcı", "Mehmet (kuzeni)")
    title: str
    memory_ids: tuple[str, ...] = ()
    entity_ids: tuple[str, ...] = ()
    values: tuple[str, ...] = field(default_factory=tuple)


def _fp(kind: str, ids: tuple[str, ...]) -> str:
    return hashlib.sha256(f"{kind}|{'|'.join(sorted(ids))}".encode()).hexdigest()[:32]


def _who(conn: Connection, subject_id: str | None, cache: dict[str, Entity | None]) -> str:
    if subject_id is None:
        return "Kullanıcı"
    if subject_id not in cache:
        cache[subject_id] = repo.get_entity(conn, subject_id)
    e = cache[subject_id]
    if e is None:
        return "?"
    return f"{e.name} ({e.relation})" if e.relation else e.name


def _tier_rank(m: Memory, sources: int) -> int:
    return importance.rank(importance.tier(
        predicate=m.predicate, importance=m.importance, origin=m.origin,
        sensitivity=m.sensitivity, about_user=m.subject_id is None, sources=sources,
    ))  # fmt: skip


def scan(conn: Connection, *, now: datetime | None = None, limit: int = 50) -> list[Finding]:
    now = now or datetime.now(UTC)
    dismissed = {str(r[0]) for r in conn.execute(
        "SELECT fingerprint FROM memory_quality_dismissed").fetchall()}  # fmt: skip
    active = repo.list_memories(conn, status="active", limit=20_000)
    cache: dict[str, Entity | None] = {}
    out: list[Finding] = []

    def add(kind: Kind, ms: list[Memory], title: str, *, entities: tuple[str, ...] = ()) -> None:
        ids = tuple(m.id for m in ms) + entities
        fid = _fp(kind, ids)
        if fid in dismissed:
            return
        rank = min((_tier_rank(m, 1) for m in ms), default=1)
        who = _who(conn, ms[0].subject_id, cache) if ms else ""
        priority = rank * 10 + _KIND_WEIGHT[kind]
        out.append(Finding(fid, kind, priority, who, title, tuple(m.id for m in ms), entities,
                           tuple(m.value for m in ms)))  # fmt: skip

    groups: dict[tuple[str | None, str], list[Memory]] = {}
    for m in active:
        groups.setdefault((m.subject_id, m.predicate), []).append(m)
    for (subject_id, pred), ms in groups.items():
        p = registry.get(pred)
        label = p.label if p else pred
        who = _who(conn, subject_id, cache)
        if p is not None and p.cardinality == "single" and len(ms) > 1:
            add("conflict", ms, f"{who} — {label}: birden fazla güncel değer var. Hangisi güncel?")
            continue
        if any(m.conflict_state == "pending" for m in ms):
            add("conflict", [m for m in ms if m.conflict_state == "pending"],
                f"{who} — {label}: yanıt bekleyen bir çelişki var.")  # fmt: skip
        if len(ms) > 1:
            seen: set[str] = set()
            for i, a in enumerate(ms):
                for b in ms[i + 1 :]:
                    if a.id in seen or b.id in seen:
                        continue
                    if text.similarity(a.value, b.value) >= DUPLICATE_SIMILARITY:
                        seen |= {a.id, b.id}
                        same = f"{who} — {label}: iki kayıt neredeyse aynı şeyi söylüyor."
                        add("duplicate", [a, b], same)
        if pred in VOLATILE:
            for m in ms:
                last = _last_confirmed(conn, m)
                if last is not None and now - last > timedelta(days=STALE_AFTER_DAYS):
                    add("stale", [m], f"{who} — {label}: bir yıldır doğrulanmadı. Hâlâ geçerli mi?")
    for m in active:
        if m.confidence < 0.6 or m.origin == "inferred":
            add("uncertain", [m], f"{_who(conn, m.subject_id, cache)}: emin olunmadan kaydedilmiş "
                                  "bir bilgi var. Doğru mu?")  # fmt: skip
        if repo.independent_sources(conn, m.id) == 0:
            add("no_evidence", [m], f"{_who(conn, m.subject_id, cache)}: kaynağı kalmamış bir "
                                    "bilgi var.")  # fmt: skip
    out += _namesakes(conn, dismissed)
    out.sort(key=lambda f: (f.priority, f.kind, f.subject))
    return out[:limit]


def _last_confirmed(conn: Connection, m: Memory) -> datetime | None:
    row = conn.execute("SELECT MAX(created_at) FROM memory_evidence WHERE memory_id = ?",
                       (m.id,)).fetchone()  # fmt: skip
    stamp = (row[0] if row and row[0] else None) or m.valid_from or m.created_at
    try:
        return datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return None


def _namesakes(conn: Connection, dismissed: set[str]) -> list[Finding]:
    out: list[Finding] = []
    people = [e for e in repo.list_entities(conn, kind="person", limit=10_000) if not e.is_user]
    by_name: dict[str, list[Entity]] = {}
    for e in people:
        by_name.setdefault(text.name_key(e.name), []).append(e)
    for group in by_name.values():
        if len(group) < 2:
            continue
        for i, a in enumerate(group):
            for b in group[i + 1 :]:
                if gs.are_distinct(conn, a.id, b.id):
                    continue
                if a.relation and b.relation and a.relation != b.relation:
                    continue  # known apart by what they are to the user
                fid = _fp("ambiguous_person", (a.id, b.id))
                if fid in dismissed:
                    continue
                out.append(Finding(fid, "ambiguous_person", 11, a.name,
                                   f"İki {a.name} kaydı var. Aynı kişi mi, farklı kişiler mi?",
                                   entity_ids=(a.id, b.id)))  # fmt: skip
    return out


def dismiss(conn: Connection, finding_id: str, kind: str, now: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO memory_quality_dismissed (fingerprint, kind, created_at)"
        " VALUES (?, ?, ?)",
        (finding_id, kind, now),
    )
