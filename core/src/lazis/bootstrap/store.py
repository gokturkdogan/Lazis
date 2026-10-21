"""The import draft in the encrypted database (Phase 8, ADR-0019; migration 0006_bootstrap).

An import (``import_batches``) has its sections while it is analysed, then its proposed people
(``import_people``) and items (``import_items``) with the user's decisions. Decisions never
default to "approve": every item starts ``pending``, every person ``pending``. A decision on a
person re-classifies the items that depend on it (what a fact is compared with changes).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from typing import Any, Literal, cast

from lazis.bootstrap import analyze, files
from lazis.bootstrap.proposals import (
    USER,
    Proposals,
    ProposedFact,
    ProposedPerson,
    ProposedRelation,
)
from lazis.ids import new_ulid, utc_now_iso
from lazis.memory import policy, service
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID
from lazis.memory.service import NotFound
from lazis.storage.driver import Connection

Status = Literal["analyzing", "ready", "failed", "cancelled", "applied", "undone", "discarded"]
PersonDecision = Literal["pending", "create", "link", "unresolved", "reject"]
ItemDecision = Literal["pending", "approve", "reject", "hold"]
Resolution = Literal["keep_old", "update", "keep_both"]
NEEDS_RESOLUTION = frozenset({"conflict", "temporal_update", "possible_duplicate"})


class DecisionError(ValueError):
    """``code``: why a decision cannot be taken (stable, for the UI)."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class Batch:
    id: str
    status: Status
    file_name: str
    format: str
    content_hash: str
    size_bytes: int
    sections_total: int
    sections_done: int
    sections_failed: int
    model: str | None
    model_calls: int
    error: str | None
    warnings: tuple[str, ...]
    counts: dict[str, Any]
    effects: dict[str, Any]
    apply_change_set_id: str | None
    undo_change_set_id: str | None
    created_at: str
    updated_at: str
    applied_at: str | None
    undone_at: str | None


_BATCH_COLS = ("id, status, file_name, format, content_hash, size_bytes, sections_total, "
               "sections_done, sections_failed, model, model_calls, error, warnings_json, "
               "counts_json, effects_json, apply_change_set_id, undo_change_set_id, created_at, "
               "updated_at, applied_at, undone_at")  # fmt: skip


def _batch(r: Any) -> Batch:
    return Batch(
        str(r[0]), cast(Status, r[1]), str(r[2]), str(r[3]), str(r[4]), int(r[5]), int(r[6]),
        int(r[7]), int(r[8]), r[9], int(r[10]), r[11], tuple(json.loads(r[12])),
        json.loads(r[13]), json.loads(r[14]), r[15], r[16], str(r[17]), str(r[18]), r[19], r[20],
    )  # fmt: skip


def get_batch(conn: Connection, import_id: str) -> Batch:
    row = conn.execute(f"SELECT {_BATCH_COLS} FROM import_batches WHERE id = ?",  # noqa: S608
                       (import_id,)).fetchone()  # fmt: skip
    if row is None:
        raise NotFound("import not found")
    return _batch(row)


def list_batches(conn: Connection, limit: int = 20) -> list[Batch]:
    rows = conn.execute(f"SELECT {_BATCH_COLS} FROM import_batches"  # noqa: S608
                        " WHERE status != 'discarded' ORDER BY created_at DESC LIMIT ?",
                        (limit,)).fetchall()  # fmt: skip
    return [_batch(r) for r in rows]


def create_batch(conn: Connection, f: files.ReadFile, *, model: str | None) -> str:
    """The import, with its sections (Markdown/text) waiting for the model."""
    iid = new_ulid()
    now = utc_now_iso()
    with _tx(conn):
        conn.execute(
            "INSERT INTO import_batches (id, status, file_name, format, content_hash, size_bytes,"
            " sections_total, model, warnings_json, created_at, updated_at)"
            " VALUES (?, 'analyzing', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (iid, f.name, f.format, f.content_hash, f.size_bytes, len(f.sections), model,
             json.dumps([f"satır {n}: redacted_secret" for n in f.redacted_lines]), now, now),
        )  # fmt: skip
        conn.executemany(
            "INSERT INTO import_sections (import_id, idx, heading, first_line, body, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            [(iid, s.idx, s.heading, s.first_line, json.dumps(
                {"body": s.body, "lines": list(s.line_numbers)}, ensure_ascii=False))
             for s in f.sections],
        )  # fmt: skip
    return iid


class _tx:
    """A plain transaction for draft rows (they are not memory: no change set)."""

    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def __enter__(self) -> None:
        self.conn.execute("BEGIN IMMEDIATE")

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.conn.execute("COMMIT" if exc_type is None else "ROLLBACK")


def sections(conn: Connection, import_id: str, *, statuses: tuple[str, ...] = ("pending",)
             ) -> list[files.Section]:  # fmt: skip
    marks = ",".join("?" * len(statuses))
    rows = conn.execute(
        f"SELECT idx, heading, first_line, body FROM import_sections WHERE import_id = ?"  # noqa: S608
        f" AND status IN ({marks}) AND body IS NOT NULL ORDER BY idx",
        (import_id, *statuses),
    ).fetchall()
    out: list[files.Section] = []
    for idx, heading, first, body in rows:
        b = json.loads(str(body))
        out.append(files.Section(int(idx), str(heading), int(first), str(b["body"]),
                                 tuple(int(x) for x in b["lines"])))  # fmt: skip
    return out


def section_results(conn: Connection, import_id: str) -> list[tuple[files.Section, str]]:
    rows = conn.execute(
        "SELECT idx, heading, first_line, body, result_json FROM import_sections"
        " WHERE import_id = ? AND status = 'done' AND body IS NOT NULL ORDER BY idx",
        (import_id,),
    ).fetchall()
    out: list[tuple[files.Section, str]] = []
    for idx, heading, first, body, raw in rows:
        b = json.loads(str(body))
        sec = files.Section(int(idx), str(heading), int(first), str(b["body"]),
                            tuple(int(x) for x in b["lines"]))  # fmt: skip
        out.append((sec, str(raw or "")))
    return out


def record_section(conn: Connection, import_id: str, idx: int, raw: str | None) -> None:
    """One section analysed (``raw``: the model's answer) or failed (``raw`` None)."""
    ok = raw is not None
    with _tx(conn):
        conn.execute(
            "UPDATE import_sections SET status = ?, result_json = ?, attempts = attempts + 1"
            " WHERE import_id = ? AND idx = ?",
            ("done" if ok else "failed", raw, import_id, idx),
        )
        _recount(conn, import_id)


def split_section(conn: Connection, import_id: str, idx: int) -> bool:
    """A section the model could not answer in full (cut off at its output limit, or not
    JSON) is read again as two halves: this one keeps the first half, a new one the second.
    The heading line stays at the top of both (lines under a person's heading are about that
    person). The attempt is counted and the split is listed in the warnings. False when the
    section has fewer than two lines of text: then it has failed."""
    row = conn.execute(
        "SELECT heading, body FROM import_sections WHERE import_id = ? AND idx = ?",
        (import_id, idx),
    ).fetchone()
    if row is None or row[1] is None:
        return False
    b = json.loads(str(row[1]))
    pairs = list(zip(b["lines"], str(b["body"]).split("\n"), strict=False))
    head = pairs[:1] if pairs and pairs[0][1].lstrip().startswith("#") else []
    content = pairs[len(head) :]
    if len(content) < 2:
        return False
    half = len(content) // 2
    parts = [head + content[:half], head + content[half:]]

    def body(part: list[tuple[int, str]]) -> str:
        return json.dumps({"body": "\n".join(t for _, t in part), "lines": [n for n, _ in part]},
                          ensure_ascii=False)  # fmt: skip

    with _tx(conn):
        conn.execute(
            "UPDATE import_sections SET body = ?, first_line = ?, status = 'pending',"
            " result_json = NULL, attempts = attempts + 1 WHERE import_id = ? AND idx = ?",
            (body(parts[0]), parts[0][0][0], import_id, idx),
        )
        (top,) = conn.execute("SELECT MAX(idx) FROM import_sections WHERE import_id = ?",
                              (import_id,)).fetchone()  # fmt: skip
        conn.execute(
            "INSERT INTO import_sections (import_id, idx, heading, first_line, body, status)"
            " VALUES (?, ?, ?, ?, ?, 'pending')",
            (import_id, int(top) + 1, row[0], parts[1][0][0], body(parts[1])),
        )
        warning = f"section_split: satır {content[0][0]}–{content[-1][0]}"
        old = get_batch(conn, import_id).warnings
        conn.execute(
            "UPDATE import_batches SET sections_total = sections_total + 1, warnings_json = ?"
            " WHERE id = ?",
            (json.dumps([*old, warning][:200]), import_id),
        )
        _recount(conn, import_id)
    return True


def _recount(conn: Connection, import_id: str) -> None:
    done, failed = conn.execute(
        "SELECT SUM(status = 'done'), SUM(status = 'failed') FROM import_sections"
        " WHERE import_id = ?",
        (import_id,),
    ).fetchone()
    conn.execute(
        "UPDATE import_batches SET sections_done = ?, sections_failed = ?, model_calls ="
        " (SELECT COALESCE(SUM(attempts), 0) FROM import_sections WHERE import_id = ?),"
        " updated_at = ? WHERE id = ?",
        (int(done or 0), int(failed or 0), import_id, utc_now_iso(), import_id),
    )


def retry_failed(conn: Connection, import_id: str) -> int:
    """Failed sections go back to pending (an explicit, counted retry); an analysis that
    stopped (the app closed) carries on with the sections it had not read. The proposals are
    built again afterwards: decisions taken on the earlier ones are not kept."""
    b = get_batch(conn, import_id)
    if b.status not in ("ready", "failed") or b.model is None:
        raise DecisionError("not_retryable")
    (open_sections,) = conn.execute(
        "SELECT COUNT(*) FROM import_sections WHERE import_id = ? AND status IN ('failed',"
        " 'pending')", (import_id,)).fetchone()  # fmt: skip
    if not open_sections:
        raise DecisionError("not_retryable")
    with _tx(conn):
        n = conn.execute(
            "UPDATE import_sections SET status = 'pending'"
            " WHERE import_id = ? AND status = 'failed'",
            (import_id,),
        ).rowcount
        conn.execute("UPDATE import_batches SET status = 'analyzing', error = NULL, updated_at = ?"
                     " WHERE id = ?",
                     (utc_now_iso(), import_id))  # fmt: skip
        _recount(conn, import_id)
    return int(n)


def set_status(conn: Connection, import_id: str, status: Status, *, error: str | None = None,
               only_from: tuple[Status, ...] | None = None) -> bool:  # fmt: skip
    sql = "UPDATE import_batches SET status = ?, error = ?, updated_at = ? WHERE id = ?"
    args: list[Any] = [status, error, utc_now_iso(), import_id]
    if only_from:
        sql += f" AND status IN ({','.join('?' * len(only_from))})"
        args += list(only_from)
    with _tx(conn):
        return conn.execute(sql, args).rowcount == 1


def forget_text(conn: Connection, import_id: str) -> None:
    """The section text and model answers are no longer needed (applied, discarded,
    cancelled): deleted, not just hidden."""
    conn.execute(
        "UPDATE import_sections SET body = NULL, result_json = NULL WHERE import_id = ?",
        (import_id,),
    )


# ----- proposals ---------------------------------------------------------------------------
def save_proposals(
    conn: Connection,
    import_id: str,
    proposals: Proposals,
    analysis: analyze.Analysis,
    *,
    rejected_before: frozenset[str] = frozenset(),
) -> None:
    """The analysed proposals replace any earlier ones (a re-analysis after a retry)."""
    now = utc_now_iso()
    with _tx(conn):
        conn.execute("DELETE FROM import_items WHERE import_id = ?", (import_id,))
        conn.execute("DELETE FROM import_people WHERE import_id = ?", (import_id,))
        ids: dict[str, str] = {}
        for seq, p in enumerate(proposals.people):
            pid = new_ulid()
            ids[p.key] = pid
            m = analysis.matches[p.key]
            options = [dict(o) for o in m.options]
            conn.execute(
                "INSERT INTO import_people (id, import_id, seq, name, kind, relation, description,"
                " match, options_json, suggested_id, note, source_section, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, import_id, seq, p.name, p.kind, p.relation, p.description, m.match,
                 json.dumps(options, ensure_ascii=False), m.suggested_id, m.note, p.section, now,
                 now),
            )  # fmt: skip
        # File-local person keys in options become import person ids.
        for p in proposals.people:
            m = analysis.matches[p.key]
            options = [
                {**o, "id": ids.get(o["id"], o["id"])} if o.get("kind") == "import" else dict(o)
                for o in m.options
            ]
            conn.execute("UPDATE import_people SET options_json = ? WHERE id = ?",
                         (json.dumps(options, ensure_ascii=False), ids[p.key]))  # fmt: skip
        seq = 0
        for f, v in zip(proposals.facts, analysis.facts, strict=True):
            if v.classification == "excluded" and v.note == "secret":
                # A secret in a JSON value: the draft and the preview never hold it.
                f = replace(f, value=files.REDACTED, statement=files.REDACTED, excerpt=None)
            payload = asdict(f)
            fp = fact_mark(f)
            note = v.note or ("rejected_before" if fp in rejected_before else None)
            conn.execute(
                "INSERT INTO import_items (id, import_id, seq, kind, category, payload_json,"
                " subject_ref, source_section, source_excerpt, source_line, method, confidence,"
                " classification, existing_json, note, created_at, updated_at)"
                " VALUES (?, ?, ?, 'fact', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (new_ulid(), import_id, seq, f.category, json.dumps(payload, ensure_ascii=False),
                 USER if f.subject == USER else ids[f.subject], f.section, f.excerpt, f.line,
                 f.method, f.confidence, v.classification,
                 json.dumps(list(v.existing), ensure_ascii=False), note, now, now),
            )  # fmt: skip
            seq += 1
        for r, v in zip(proposals.relations, analysis.relations, strict=True):
            payload = asdict(r)
            conn.execute(
                "INSERT INTO import_items (id, import_id, seq, kind, category, payload_json,"
                " source_ref, target_ref, source_section, source_excerpt, source_line, method,"
                " confidence, classification, existing_json, note, created_at, updated_at)"
                " VALUES (?, ?, ?, 'relationship', 'relationship', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                " ?, ?, ?)",
                (new_ulid(), import_id, seq, json.dumps(payload, ensure_ascii=False),
                 USER if r.source == USER else ids[r.source],
                 USER if r.target == USER else ids[r.target], r.section, r.excerpt, r.line,
                 r.method, r.confidence, v.classification,
                 json.dumps(list(v.existing), ensure_ascii=False), v.note, now, now),
            )  # fmt: skip
            seq += 1
        conn.execute(
            "UPDATE import_batches SET status = 'ready', warnings_json = ?, updated_at = ?"
            " WHERE id = ?",
            (json.dumps(list(dict.fromkeys([*get_batch(conn, import_id).warnings,
                                            *proposals.warnings]))[:200]), now, import_id),
        )  # fmt: skip


def fact_mark(f: ProposedFact) -> str:
    """What identifies a fact across imports of the same file (subject words, predicate,
    value) — used to show earlier rejections."""
    from lazis.memory import text

    return f"{f.subject}|{f.predicate}|{text.fold(f.value).strip()}"


# ----- reading ------------------------------------------------------------------------------
@dataclass(frozen=True)
class Person:
    id: str
    seq: int
    name: str
    kind: str
    relation: str | None
    description: str | None
    match: str
    options: tuple[dict[str, str], ...]
    suggested_id: str | None
    note: str | None
    decision: PersonDecision
    link_id: str | None
    entity_id: str | None
    section: str

    @property
    def label(self) -> str:
        extra = self.relation or self.description
        return f"{self.name} ({extra})" if extra else self.name


@dataclass(frozen=True)
class Item:
    id: str
    seq: int
    kind: Literal["fact", "relationship"]
    category: str
    payload: dict[str, Any]
    subject_ref: str | None
    source_ref: str | None
    target_ref: str | None
    section: str
    excerpt: str | None
    line: int | None
    method: str
    confidence: float
    classification: str
    existing: tuple[str, ...]
    note: str | None
    decision: ItemDecision
    resolution: Resolution | None
    edited_value: str | None
    result: str | None
    result_ids: tuple[str, ...]

    def fact(self) -> ProposedFact:
        return ProposedFact(**self.payload)

    def relation(self) -> ProposedRelation:
        return ProposedRelation(**self.payload)

    def refs(self) -> tuple[str, ...]:
        return tuple(r for r in (self.subject_ref, self.source_ref, self.target_ref)
                     if r is not None and r != USER)  # fmt: skip


def people(conn: Connection, import_id: str) -> list[Person]:
    rows = conn.execute(
        "SELECT id, seq, name, kind, relation, description, match, options_json, suggested_id,"
        " note, decision, link_id, entity_id, source_section FROM import_people"
        " WHERE import_id = ? ORDER BY seq",
        (import_id,),
    ).fetchall()
    return [Person(str(r[0]), int(r[1]), str(r[2]), str(r[3]), r[4], r[5], str(r[6]),
                   tuple(json.loads(r[7])), r[8], r[9], cast(PersonDecision, r[10]), r[11], r[12],
                   str(r[13])) for r in rows]  # fmt: skip


def items(conn: Connection, import_id: str) -> list[Item]:
    rows = conn.execute(
        "SELECT id, seq, kind, category, payload_json, subject_ref, source_ref, target_ref,"
        " source_section, source_excerpt, source_line, method, confidence, classification,"
        " existing_json, note, decision, resolution, edited_value, result, result_ids_json"
        " FROM import_items WHERE import_id = ? ORDER BY seq",
        (import_id,),
    ).fetchall()
    return [Item(str(r[0]), int(r[1]), r[2], str(r[3]), json.loads(r[4]), r[5], r[6], r[7],
                 str(r[8]), r[9], r[10], str(r[11]), float(r[12]), str(r[13]),
                 tuple(json.loads(r[14])), r[15], r[16], r[17], r[18], r[19],
                 tuple(json.loads(r[20]))) for r in rows]  # fmt: skip


# ----- decisions ----------------------------------------------------------------------------
def _editable(conn: Connection, import_id: str) -> Batch:
    b = get_batch(conn, import_id)
    if b.status != "ready":
        raise DecisionError("not_editable")
    return b


def target_entity(conn: Connection, import_id: str, person_id: str,
                  _seen: frozenset[str] = frozenset()) -> tuple[str, str | None]:  # fmt: skip
    """('new' | 'stored' | 'unsettled', stored entity id) a proposed person currently stands
    for, following links to other proposed people (no cycles)."""
    by_id = {p.id: p for p in people(conn, import_id)}
    p = by_id.get(person_id)
    if p is None or person_id in _seen:
        return "unsettled", None
    if p.decision == "create":
        return "new", None
    if p.decision == "link" and p.link_id:
        if p.link_id in by_id:
            return target_entity(conn, import_id, p.link_id, _seen | {person_id})
        e = repo.get_entity(conn, p.link_id)
        return ("stored", e.id) if e is not None and e.status == "active" else ("unsettled", None)
    return "unsettled", None


def _compare_with(conn: Connection, import_id: str, person_id: str) -> tuple[str | None, bool]:
    """What a person's items are compared with: the decision when there is one, the analysis's
    match otherwise (a suggestion is compared with, but never applied without a decision)."""
    state, eid = target_entity(conn, import_id, person_id)
    if state == "new":
        return analyze.NEW, False
    if state == "stored":
        return eid, False
    p = next(x for x in people(conn, import_id) if x.id == person_id)
    if p.decision in ("unresolved", "reject"):
        return None, True
    if p.match == "existing":
        return p.suggested_id, False
    if p.match == "new":
        return analyze.NEW, False
    return None, True


def reclassify(conn: Connection, import_id: str, person_ids: set[str] | None = None) -> None:
    for it in items(conn, import_id):
        refs = set(it.refs())
        if person_ids is not None and not (refs & person_ids):
            continue
        if it.kind == "fact":
            f = it.fact()
            sid, amb = (None, False) if it.subject_ref == USER else _compare_with(
                conn, import_id, cast(str, it.subject_ref))  # fmt: skip
            v = analyze.classify_fact(conn, f, sid, ambiguous=amb, value=it.edited_value)
        else:
            r = it.relation()
            ends: list[str | None] = []
            amb = False
            for ref in (it.source_ref, it.target_ref):
                if ref == USER:
                    ends.append(USER_ID)
                    continue
                sid, a = _compare_with(conn, import_id, cast(str, ref))
                amb = amb or a
                ends.append(sid)
            v = analyze.classify_relation(conn, r, ends[0], ends[1], ambiguous=amb)
        keep_note = it.note if it.note in ("in_file", "rejected_before") else v.note
        conn.execute(
            "UPDATE import_items SET classification = ?, existing_json = ?, note = ?,"
            " resolution = CASE WHEN ? THEN resolution ELSE NULL END, updated_at = ? WHERE id = ?",
            (v.classification, json.dumps(list(v.existing), ensure_ascii=False), keep_note,
             v.classification in NEEDS_RESOLUTION, utc_now_iso(), it.id),
        )  # fmt: skip


def refresh(conn: Connection, import_id: str) -> None:
    """Compare every item with the memory as it is now (it may have changed since)."""
    with _tx(conn):
        reclassify(conn, import_id)


def decide_person(conn: Connection, import_id: str, person_id: str, decision: PersonDecision,
                  link_id: str | None = None) -> None:  # fmt: skip
    _editable(conn, import_id)
    ps = {p.id: p for p in people(conn, import_id)}
    p = ps.get(person_id)
    if p is None:
        raise NotFound("person not found")
    if decision == "link":
        if not link_id or link_id == person_id:
            raise DecisionError("link_needs_target")
        if link_id in ps:
            pass  # another proposed person (the same person said twice)
        else:
            e = repo.get_entity(conn, link_id)
            if e is None or e.status != "active" or e.is_user:
                raise DecisionError("link_target_missing")
    with _tx(conn):
        conn.execute(
            "UPDATE import_people SET decision = ?, link_id = ?, updated_at = ? WHERE id = ?",
            (decision, link_id if decision == "link" else None, utc_now_iso(), person_id),
        )
        # Everything that depends on this person (or on people linked to it) is compared again.
        affected = {person_id} | {x.id for x in ps.values() if x.link_id == person_id}
        reclassify(conn, import_id, affected)


def decide_item(
    conn: Connection,
    import_id: str,
    item_id: str,
    decision: ItemDecision,
    *,
    resolution: Resolution | None = None,
    edited_value: str | None = None,
) -> None:
    _editable(conn, import_id)
    it = next((x for x in items(conn, import_id) if x.id == item_id), None)
    if it is None:
        raise NotFound("item not found")
    value = edited_value.strip()[:200] if edited_value is not None else None
    if decision == "approve":
        if it.classification == "excluded":
            raise DecisionError("excluded")
        if it.classification in NEEDS_RESOLUTION and resolution is None:
            raise DecisionError("needs_resolution")
    if value is not None:
        if it.kind != "fact" or not value:
            raise DecisionError("not_editable_value")
        if policy.secret_kind(value) or analyze.directive(value):
            raise DecisionError("edited_value_refused")
    with _tx(conn):
        conn.execute(
            "UPDATE import_items SET decision = ?, resolution = ?, edited_value = COALESCE(?,"
            " edited_value), updated_at = ? WHERE id = ?",
            (decision, resolution if it.classification in NEEDS_RESOLUTION else None, value,
             utc_now_iso(), item_id),
        )  # fmt: skip
        if value is not None:
            _reclassify_one(conn, import_id, item_id)


def _reclassify_one(conn: Connection, import_id: str, item_id: str) -> None:
    it = next(x for x in items(conn, import_id) if x.id == item_id)
    sid, amb = (None, False) if it.subject_ref == USER else _compare_with(
        conn, import_id, cast(str, it.subject_ref))  # fmt: skip
    v = analyze.classify_fact(conn, it.fact(), sid, ambiguous=amb, value=it.edited_value)
    conn.execute(
        "UPDATE import_items SET classification = ?, existing_json = ? WHERE id = ?",
        (v.classification, json.dumps(list(v.existing), ensure_ascii=False), item_id),
    )


# ----- what the user sees before writing ----------------------------------------------------
def blocked(conn: Connection, import_id: str, it: Item) -> str | None:
    """Why an approved item cannot be written (None: it can)."""
    if it.classification == "excluded":
        return "excluded"
    for ref in it.refs():
        state, _ = target_entity(conn, import_id, ref)
        if state == "unsettled":
            return "person_not_decided"
    if it.classification in NEEDS_RESOLUTION and it.resolution is None:
        return "needs_resolution"
    return None


def summary(conn: Connection, import_id: str) -> dict[str, Any]:
    """The final confirmation: what writing would do — counted from the decisions, nothing
    written yet."""
    its = items(conn, import_id)
    ps = people(conn, import_id)
    out: dict[str, Any] = {
        "analyzed": len(its), "approved": 0, "writable": 0, "blocked": 0, "rejected": 0,
        "held": 0, "pending": 0, "excluded": 0, "people_new": 0, "people_linked": 0,
        "people_unresolved": 0, "people_rejected": 0, "people_pending": 0, "by_category": {},
        "updates": 0,
    }  # fmt: skip
    for p in ps:
        key = {"create": "people_new", "link": "people_linked", "unresolved": "people_unresolved",
               "reject": "people_rejected", "pending": "people_pending"}[p.decision]  # fmt: skip
        out[key] += 1
    for it in its:
        if it.classification == "excluded":
            out["excluded"] += 1
            continue
        if it.decision == "approve":
            out["approved"] += 1
            if blocked(conn, import_id, it) is None:
                out["writable"] += 1
                cat = out["by_category"]
                cat[it.category] = cat.get(it.category, 0) + 1
                if it.classification in NEEDS_RESOLUTION and it.resolution in (
                    "update",
                    "keep_both",
                ):
                    out["updates"] += 1
            else:
                out["blocked"] += 1
        elif it.decision == "reject":
            out["rejected"] += 1
        elif it.decision == "hold":
            out["held"] += 1
        else:
            out["pending"] += 1
    return out


SaveState = Literal["save_succeeded", "save_failed", "save_cancelled", "save_rejected",
                   "save_pending_approval"]  # fmt: skip
_SUCCEEDED = frozenset({"written", "updated", "evidence_added"})
_REJECTED = frozenset({"rejected", "kept_old", "excluded"})


def save_state(batch_status: str, it: Item) -> SaveState:
    """What happened to an item, from what was really written (never from the decision)."""
    if batch_status in ("cancelled", "discarded"):
        return "save_cancelled"
    if it.result is None:  # not written yet: whatever was decided, it waits for "apply"
        return "save_rejected" if it.classification == "excluded" else "save_pending_approval"
    if it.result in _SUCCEEDED:
        return "save_succeeded"
    if it.result in _REJECTED:
        return "save_rejected"
    if it.result in ("held", "pending", "blocked"):
        return "save_pending_approval"
    return "save_failed"  # failed, refused by the memory rules, sent to the inbox


def person_by_id(conn: Connection, import_id: str, person_id: str) -> Person | None:
    return next((p for p in people(conn, import_id) if p.id == person_id), None)


def proposed_person(p: Person) -> ProposedPerson:
    return ProposedPerson(p.id, p.name, p.kind, p.relation, p.description, (), p.section)


def entity_label(conn: Connection, entity_id: str) -> str:
    e = repo.get_entity(conn, entity_id)
    return service.entity_label(e) if e is not None else entity_id
