"""Starting-profile import (MEMORY_ARCHITECTURE §12): JSON or plain text, always previewed;
nothing is written until the user applies the items they selected.

JSON format (every part optional; values are strings or lists of strings)::

    {
      "user":     {"occupation": "yazılım geliştirici", "technology": ["Python", "Rust"]},
      "people":   [{"name": "Ahmet", "relation": "çocukluk arkadaşı",
                    "aliases": ["Ahmo"], "facts": {"occupation": "yazılımcı"}}],
      "projects": [{"name": "Pusula", "facts": {"project_description": "bütçe uygulaması"}}]
    }

Keys of ``facts`` / ``user`` are predicate keys (``GET /memory/predicates``). Plain text goes
through the extraction model (the engine runs it) and arrives here as candidates.

The preview is a dry run of the same checks a conversation goes through — policy (secrets are
excluded, sensitive items flagged), entity resolution (namesakes need a choice), consolidation
(duplicates, updates, conflicts) — stored as one ``import_batch`` inbox item.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from lazis.ids import utc_now_iso
from lazis.memory import consolidation, policy, registry, resolver, service, text
from lazis.memory import repository as repo
from lazis.memory.models import ApplyReport, Candidate, EntityRef
from lazis.memory.service import NotFound, Source
from lazis.storage.driver import Connection
from lazis.storage.repositories import write_audit
from lazis.storage.unit_of_work import UnitOfWork

MAX_ITEMS = 500
Status = Literal["new", "duplicate", "update", "conflict", "ambiguous", "excluded"]


class ImportFormatError(ValueError):
    pass


@dataclass
class PreviewItem:
    index: int
    candidate: Candidate
    status: Status
    subject: str  # "Kullanıcı" or the entity label
    reason: str | None = None  # excluded: why
    sensitive: bool = False
    options: list[dict[str, str]] = field(default_factory=list[dict[str, str]])  # ambiguous
    existing: list[str] = field(default_factory=list[str])  # duplicate / update / conflict

    def view(self) -> dict[str, Any]:
        c = self.candidate
        p = registry.get(c.predicate)
        return {
            "index": self.index,
            "status": self.status,
            "subject": self.subject,
            "predicate": c.predicate,
            "predicate_label": p.label if p else c.predicate,
            "value": c.value,
            "statement": c.statement,
            "reason": self.reason,
            "sensitive": self.sensitive,
            "options": self.options,
            "existing": self.existing,
        }


# ----- parsing --------------------------------------------------------------------------
def _values(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw.strip()] if raw.strip() else []
    if isinstance(raw, list):
        return [
            str(v).strip()
            for v in cast(list[Any], raw)
            if isinstance(v, str | int | float) and str(v).strip()
        ]
    return []


def statement_for(subject: str, predicate: str, value: str) -> str:
    p = registry.get(predicate)
    return f"{subject} — {p.label if p else predicate}: {value}"


def _facts(
    facts: Any, *, subject: str, ref: EntityRef | None, errors: list[str]
) -> list[Candidate]:
    out: list[Candidate] = []
    if not isinstance(facts, dict):
        return out
    for key, raw in cast(dict[str, Any], facts).items():
        if registry.get(key) is None:
            errors.append(f"bilinmeyen alan: {key}")
            continue
        for v in _values(raw):
            out.append(
                Candidate(
                    predicate=key,
                    value=v[:200],
                    statement=statement_for(subject, key, v[:200]),
                    about="entity" if ref else "user",
                    entity=ref,
                    origin="imported",
                )
            )
    return out


def parse_json(content: str) -> tuple[list[Candidate], list[str]]:
    try:
        data = json.loads(content)
    except ValueError:
        raise ImportFormatError("not valid JSON") from None
    if not isinstance(data, dict):
        raise ImportFormatError("top level must be an object")
    d = cast(dict[str, Any], data)
    errors: list[str] = []
    out = _facts(d.get("user"), subject="Kullanıcı", ref=None, errors=errors)
    for group, kind in (("people", "person"), ("projects", "project")):
        entries = d.get(group)
        if not isinstance(entries, list):
            continue
        for entry in cast(list[Any], entries):
            if not isinstance(entry, dict):
                continue
            e = cast(dict[str, Any], entry)
            name = str(e.get("name", "")).strip()[:80]
            if not text.name_key(name):
                errors.append(f"{group}: adı olmayan kayıt atlandı")
                continue
            relation = str(e.get("relation", "")).strip()[:80] or None
            ref = EntityRef(name, cast(Any, kind), relation)
            label = f"{name} ({relation})" if relation else name
            out += _facts(e.get("facts"), subject=label, ref=ref, errors=errors)
    if len(out) > MAX_ITEMS:
        raise ImportFormatError(f"too many items (max {MAX_ITEMS})")
    return out, errors


MAX_TEXT_CHARS = 8000
CHUNK_CHARS = 1400


def chunk_text(content: str) -> list[str]:
    """Paragraph-aligned chunks of at most ``CHUNK_CHARS`` (a longer paragraph is cut)."""
    content = content.strip()[:MAX_TEXT_CHARS]
    chunks: list[str] = []
    current = ""
    for para in (p.strip() for p in content.split("\n")):
        if not para:
            continue
        while len(para) > CHUNK_CHARS:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(para[:CHUNK_CHARS])
            para = para[CHUNK_CHARS:]
        if current and len(current) + len(para) + 1 > CHUNK_CHARS:
            chunks.append(current)
            current = ""
        current = f"{current}\n{para}" if current else para
    if current:
        chunks.append(current)
    return chunks


# ----- preview (dry run) ----------------------------------------------------------------
_STATUS: dict[str, Status] = {
    "create": "new",
    "duplicate": "duplicate",
    "supersede": "update",
    "conflict": "conflict",
}


def preview(conn: Connection, candidates: Sequence[Candidate]) -> list[PreviewItem]:
    items: list[PreviewItem] = []
    for i, c in enumerate(candidates):
        subject = "Kullanıcı"
        if c.entity is not None:
            subject = (
                f"{c.entity.name} ({c.entity.relation})" if c.entity.relation else c.entity.name
            )
        d = policy.decide(c, explicit=True)
        if d.outcome == "drop":
            items.append(PreviewItem(i, c, "excluded", subject, reason=d.reason))
            continue
        sensitive = d.sensitivity == "sensitive"
        subject_id: str | None = None
        if c.entity is not None:
            found = repo.find_entities(conn, text.name_key(c.entity.name))
            res = resolver.resolve(c.entity, found)
            if res.kind == "ambiguous":
                opts = [repo.get_entity(conn, o) for o in res.options]
                items.append(PreviewItem(i, c, "ambiguous", subject, sensitive=sensitive, options=[
                    {"id": o.id, "label": service.entity_label(o)} for o in opts if o is not None
                ]))  # fmt: skip
                continue
            if res.kind == "new":
                items.append(PreviewItem(i, c, "new", subject, sensitive=sensitive))
                continue
            subject_id = res.entity_id
        current = repo.memories_for_subject(conn, subject_id, predicate=c.predicate)
        plan = consolidation.plan(c, current, explicit=False)
        existing = [m.value for m in current if m.id in plan.target_ids]
        status = _STATUS[plan.action]
        items.append(PreviewItem(i, c, status, subject, sensitive=sensitive, existing=existing))
    return items


def create_batch(
    conn: Connection, candidates: Sequence[Candidate], *, source: Literal["json", "text"]
) -> tuple[str, list[PreviewItem]]:
    items = preview(conn, candidates)
    counts: dict[str, int] = {}
    for it in items:
        counts[it.status] = counts.get(it.status, 0) + 1
    with UnitOfWork(conn, kind="import", actor="user", summary="içe aktarma önizlemesi") as _:
        batch_id = repo.insert_inbox(
            conn,
            type="import_batch",
            summary=f"İçe aktarma önizlemesi: {len(items)} öğe",
            payload={
                "source": source,
                "candidates": [service.candidate_to_json(c) for c in candidates],
                "counts": counts,
            },
            now=utc_now_iso(),
        )
    return batch_id, items


def batch_preview(conn: Connection, batch_id: str) -> list[PreviewItem]:
    """The preview again, against the current memory (it may have changed meanwhile)."""
    item = repo.get_inbox(conn, batch_id)
    if item is None or item.type != "import_batch" or item.status != "open":
        raise NotFound("import batch not found")
    return preview(conn, [service.candidate_from_json(c) for c in item.payload["candidates"]])


# ----- apply ----------------------------------------------------------------------------
def apply_batch(conn: Connection, batch_id: str, selections: dict[int, str]) -> ApplyReport:
    """Write the selected items. ``selections``: index → "apply", or for an ambiguous item an
    option id / "new", or for a conflict "replace" / "both". Unselected items are dropped."""
    items = batch_preview(conn, batch_id)
    by_index = {it.index: it for it in items}
    report = ApplyReport()
    now = utc_now_iso()
    src = Source("import", batch_id)
    summary = f"{len(selections)} öğe içe aktarıldı"
    with UnitOfWork(
        conn, kind="import", actor="import", summary=summary, source_ref=batch_id
    ) as uow:
        for index, choice in sorted(selections.items()):
            it = by_index.get(index)
            if it is None:
                continue
            if it.status == "excluded":
                report.drop(it.reason or "excluded")
                continue
            c = it.candidate
            forced: tuple[str | None] | None = None
            force: Literal["create", "supersede"] | None = None
            if it.status == "ambiguous":
                if choice == "new":
                    assert c.entity is not None
                    ent = repo.insert_entity(
                        conn,
                        kind=c.entity.kind,
                        name=c.entity.name,
                        relation=c.entity.relation,
                        description=None,
                        now=now,
                    )
                    uow.record("memory_entities", ent.id, "create", None)
                    report.entities_created.append(ent.id)
                    forced = (ent.id,)
                elif choice in {o["id"] for o in it.options}:
                    forced = (choice,)
                else:
                    raise ValueError("ambiguous item needs a choice")
            elif it.status == "conflict":
                if choice not in ("replace", "both"):
                    raise ValueError("conflict item needs replace or both")
                force = "supersede" if choice == "replace" else "create"
            elif choice != "apply":
                raise ValueError("invalid choice")
            if force is not None:
                # The subject is resolved exactly as in the preview (an existing one).
                subject_id = None
                if c.entity is not None:
                    found = repo.find_entities(conn, text.name_key(c.entity.name))
                    subject_id = resolver.resolve(c.entity, found).entity_id
                forced = (subject_id,)
            service.apply_one(conn, uow, c, source=src, explicit=True, report=report, now=now,
                              forced_subject=forced, force=force)  # fmt: skip
        repo.resolve_inbox(conn, batch_id, status="resolved", resolution="applied", now=now)
        write_audit(
            conn,
            category="memory",
            action="import",
            outcome="success",
            actor="user",
            change_set_id=uow.change_set_id,
            details={k: v for k, v in report.counts().items()},
        )
    return report


def discard_batch(conn: Connection, batch_id: str) -> None:
    item = repo.get_inbox(conn, batch_id)
    if item is None or item.type != "import_batch":
        raise NotFound("import batch not found")
    # The batch holds the imported text's facts: delete it, do not just mark it.
    with UnitOfWork(conn, kind="deletion", actor="user", summary="içe aktarma iptal edildi") as _:
        repo.delete_inbox(conn, batch_id)
