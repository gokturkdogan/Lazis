"""The import pipeline's database steps (Phase 8, ADR-0019). The model calls (Markdown/text)
are the engine's (:meth:`ConversationEngine.bootstrap_analyze`); everything else is here.

    JSON:           read → start_json (parse, analyse, save; status 'ready')
    Markdown/text:  read → create_batch (sections) → engine: one model call per section
                    (record_section) → finish_text (validate, assemble people, analyse, save)
"""

from __future__ import annotations

import json

from lazis.bootstrap import analyze, extract, files, profile, store
from lazis.bootstrap.proposals import USER, Proposals
from lazis.memory import text
from lazis.storage.driver import Connection


def mark(subject_label: str, predicate: str, value: str) -> str:
    """A fact's identity across imports of the same file (rejections are shown again)."""
    return f"{text.fold(subject_label)}|{predicate}|{text.fold(value).strip()}"


def _label(proposals: Proposals, ref: str) -> str:
    return "user" if ref == USER else analyze.subject_label(proposals, ref)


def rejected_before(conn: Connection, content_hash: str) -> frozenset[str]:
    """Facts rejected in earlier imports of the same file."""
    rows = conn.execute(
        "SELECT i.payload_json, p.name, p.relation, p.description FROM import_items i"
        " JOIN import_batches b ON b.id = i.import_id"
        " LEFT JOIN import_people p ON p.id = i.subject_ref"
        " WHERE b.content_hash = ? AND i.decision = 'reject' AND i.kind = 'fact'",
        (content_hash,),
    ).fetchall()
    out: set[str] = set()
    for payload, name, relation, desc in rows:
        d = json.loads(str(payload))
        who = "user" if name is None else (f"{name} ({relation or desc})" if relation or desc
                                           else str(name))  # fmt: skip
        out.add(mark(who, str(d["predicate"]), str(d["value"])))
    return frozenset(out)


def _save(conn: Connection, import_id: str, proposals: Proposals, content_hash: str) -> None:
    analysis = analyze.analyze(conn, proposals)
    before = rejected_before(conn, content_hash)
    marks = frozenset(
        store.fact_mark(f) for f in proposals.facts
        if mark(_label(proposals, f.subject), f.predicate, f.value) in before
    )  # fmt: skip
    store.save_proposals(conn, import_id, proposals, analysis, rejected_before=marks)


def start_json(conn: Connection, f: files.ReadFile) -> str:
    proposals = profile.parse(f.text)  # ProfileError before anything is stored
    import_id = store.create_batch(conn, f, model=None)
    _save(conn, import_id, proposals, f.content_hash)
    return import_id


def finish_text(conn: Connection, import_id: str) -> None:
    """All sections are analysed (or failed): validate the answers, assemble the people across
    the file, compare with the memory, and store the proposals for the user."""
    b = store.get_batch(conn, import_id)
    results: list[extract.SectionResult] = []
    dropped: dict[str, int] = {}
    for section, raw in store.section_results(conn, import_id):
        r = extract.validate(raw, section)
        if r is None:  # stored answers were valid when recorded; be safe anyway
            continue
        results.append(r)
        for k, v in r.dropped.items():
            dropped[k] = dropped.get(k, 0) + v
    proposals = extract.assemble(results)
    proposals.warnings += [f"dropped: {k} × {v}" for k, v in sorted(dropped.items())]
    if b.sections_failed:
        proposals.warnings.append(f"sections_failed: {b.sections_failed}")
    _save(conn, import_id, proposals, b.content_hash)


def discard(conn: Connection, import_id: str) -> None:
    """A draft the user does not want: its proposals and text are deleted."""
    b = store.get_batch(conn, import_id)
    if b.status == "applied":
        raise store.DecisionError("applied")  # undo it instead
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM import_items WHERE import_id = ?", (import_id,))
        conn.execute("DELETE FROM import_people WHERE import_id = ?", (import_id,))
        store.forget_text(conn, import_id)
        conn.execute("UPDATE import_batches SET status = 'discarded' WHERE id = ?", (import_id,))
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
