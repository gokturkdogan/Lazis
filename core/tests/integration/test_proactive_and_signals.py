"""Phase 10A: the gate for what LAZIS brings up unasked, and independent preference signals —
on a real encrypted database (the synthetic graph: two Ahmets, Mehmet, Zeynep)."""

from __future__ import annotations

from lazis.conversation import repository as conv_repo
from lazis.ids import utc_now_iso
from lazis.memory import proactive, relationships, service, signals
from lazis.memory import repository as repo
from lazis.storage import StorageHandle, driver
from lazis.storage.unit_of_work import UnitOfWork
from tests.graph_support import World, run
from tests.integration.test_people_guard import fact


def _set(c: driver.Connection, mid: str, column: str, value: object) -> None:
    conn_sql = f"UPDATE memories SET {column} = ? WHERE id = ?"
    c.execute(conn_sql, (value, mid))


# ----- the gate -----------------------------------------------------------------------------
def test_what_may_be_brought_up(storage: StorageHandle, world: World) -> None:
    ids = run(storage, lambda c: {
        "ok": fact(c, None, "goal", "maraton koşmak"),
        "forgotten": fact(c, None, "employer", "Kervan Lojistik"),
        "topic": fact(c, world["mehmet"], "occupation", "öğretmen"),
        "conflict": fact(c, None, "location", "İzmir"),
        "uncertain": fact(c, None, "hobby", "satranç"),
        "sensitive": fact(c, None, "health", "astım"),
        "old": fact(c, None, "pet", "kedi"),
    })  # fmt: skip

    def change(c: driver.Connection) -> None:
        service.forget_memories(c, [ids["forgotten"]])
        service.forget_topic(c, world["mehmet"], "occupation")
        _set(c, ids["conflict"], "conflict_state", "pending")
        _set(c, ids["uncertain"], "confidence", 0.4)
        _set(c, ids["sensitive"], "sensitivity", "sensitive")
        _set(c, ids["old"], "status", "superseded")

    run(storage, change)
    gate = run(storage, proactive.load)

    def verdicts(c: driver.Connection) -> dict[str, str | None]:
        out: dict[str, str | None] = {}
        for k, mid in ids.items():
            m = repo.get_memory(c, mid)
            out[k] = "deleted" if m is None else gate.memory(m)
        return out

    assert run(storage, verdicts) == {
        "ok": None, "forgotten": "deleted", "topic": "deleted", "conflict": "conflict",
        "uncertain": "uncertain", "sensitive": "sensitive", "old": "not_active",
    }  # fmt: skip


def test_a_value_forgotten_and_learned_again_unasked_is_still_refused(
    storage: StorageHandle, world: World
) -> None:
    # Background learning never re-learns it (suppressed); if a record with that value comes
    # back another way (a new predicate), the value mark still keeps it out of follow-ups.
    first = run(storage, lambda c: fact(c, None, "employer", "Kervan Lojistik"))
    run(storage, lambda c: service.forget_memories(c, [first]))
    again = run(storage, lambda c: fact(c, None, "note", "Kervan Lojistik"))
    gate = run(storage, proactive.load)
    m = run(storage, lambda c: repo.get_memory(c, again))
    assert m is not None and gate.memory(m) == "forgotten"


def test_relationships_through_the_gate(storage: StorageHandle, world: World) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["zeynep"]))
    gate = run(storage, proactive.load)
    rels = run(storage, lambda c: relationships.gs.relationships_of(c, world["mehmet"]))
    usable = proactive.usable_relationships(gate, rels)
    assert {r.type for r in usable} >= {"sibling", "spouse"}
    assert "ex_spouse" in {r.type for r in rels}  # stored (active), usable too
    sensitive = run(storage, lambda c: relationships.gs.relationships_of(c, world["selin"]))
    assert all(gate.relationship(r) == "sensitive" for r in sensitive)
    ended = run(storage, lambda c: relationships.gs.relationships_of(c, world["can"]))
    assert all(gate.relationship(r) == "not_active" for r in ended)


def test_namesakes_need_a_label_and_summaries_are_cleaned(
    storage: StorageHandle, world: World
) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    gate = run(storage, proactive.load)
    assert gate.needs_label(world["ahmet"]) and gate.needs_label(world["ahmet2"])
    assert not gate.needs_label(world["mehmet"])
    summary = (
        "Kullanıcı hafta sonu İzmir'e gidecek. Ahmet emekli oldu. Çocukluk arkadaşı Ahmet "
        "yeni bir işe başladı. Mehmet, Ahmet'in kuzeniydi. Kullanıcı maraton için çalışıyor."
    )
    clean, dropped = gate.clean_text(summary)
    assert clean == (
        "Kullanıcı hafta sonu İzmir'e gidecek. Çocukluk arkadaşı Ahmet yeni bir işe başladı. "
        "Kullanıcı maraton için çalışıyor."
    )
    assert dropped == 2
    # A summary is a list (Phase 10A real run g1): every line is kept or dropped, none lost.
    listed = (
        "Kullanıcının belirttiği hedefler:\n- Gelecek yıl maraton koşmak. [#3]\n"
        "Adı geçen kişiler:\n- Ahmet: Komşu [#5]\n- Mehmet: Ahmet'in kuzeni [#9]\n- Defne: Kız [#11]"
    )
    clean, dropped = gate.clean_text(listed)
    assert clean == (
        "Kullanıcının belirttiği hedefler:\n- Gelecek yıl maraton koşmak. [#3]\n"
        "Adı geçen kişiler:\n- Defne: Kız [#11]"
    )
    assert dropped == 2


# ----- signals ------------------------------------------------------------------------------
def _session(c: driver.Connection) -> str:
    now = utc_now_iso()
    conv_repo.archive_active_session(c)
    return conv_repo.insert_conversation(c, title="t", model="m", now=now).id


def _said(c: driver.Connection, cid: str, content: str) -> str:
    return conv_repo.insert_message(
        c, conversation_id=cid, role="user", content=content, status="complete", now=utc_now_iso()
    ).id


def _backs(c: driver.Connection, mid: str, message_id: str) -> None:
    repo.add_evidence(
        c, mid, source_type="message", source_ref=message_id, quote=None, now=utc_now_iso()
    )


def test_records_are_not_signals(storage: StorageHandle) -> None:
    def seed(c: driver.Connection) -> dict[str, list[str]]:
        # Three differently worded records; m1 backs two of them (one message, two records).
        a, b, d = (fact(c, None, "communication_preference", v)
                   for v in ("kısa yanıt", "net yanıt", "kısa olsun"))  # fmt: skip
        with conv_repo.transaction(c):
            s1 = _session(c)
            m1 = _said(c, s1, "Kısa ve net yanıtları severim.")
            m2 = _said(c, s1, "Uzun açıklamalardan hoşlanmam, kısa olsun.")
            _backs(c, a, m1)
            _backs(c, b, m1)
            _backs(c, d, m2)
        return {"short": [a, b, d]}

    by_key = run(storage, seed)
    found = run(storage, lambda c: signals.from_records(c, by_key))
    t = signals.tally(found)["short"]
    assert (t.messages, t.sessions) == (2, 1) and not t.enough


def test_three_statements_in_two_sessions_are_enough(storage: StorageHandle) -> None:
    def seed(c: driver.Connection) -> dict[str, list[str]]:
        one = fact(c, None, "communication_preference", "kısa yanıt")
        with conv_repo.transaction(c):
            s1 = _session(c)
            m1 = _said(c, s1, "Kısa yanıtları severim.")
            m2 = _said(c, s1, "Lütfen kısa tut.")
            s2 = _session(c)
            m3 = _said(c, s2, "Kısa olsun yeter.")
            again = _said(c, s2, "Kısa yanıtları severim.")  # the same words: one statement
            for m in (m1, m2, m3, again):
                _backs(c, one, m)
        return {"short": [one]}

    by_key = run(storage, seed)
    t = signals.tally(run(storage, lambda c: signals.from_records(c, by_key)))["short"]
    assert (t.messages, t.sessions) == (3, 2) and t.enough


def test_what_never_counts(storage: StorageHandle) -> None:
    def seed(c: driver.Connection) -> dict[str, list[str]]:
        edited = fact(c, None, "communication_preference", "kısa yanıt")  # user_edit only
        echoed = fact(c, None, "communication_preference", "kısa cevap")
        gone = fact(c, None, "communication_preference", "kısa olsun")
        with conv_repo.transaction(c):
            s1 = _session(c)
            m1 = _said(c, s1, "Kısa yanıtları severim.")
            reply = conv_repo.insert_message(
                c, conversation_id=s1, role="assistant", content="Kısa yanıt vereyim mi?",
                status="complete", now=utc_now_iso(),
            ).id  # fmt: skip
            _backs(c, echoed, reply)  # LAZIS's own words
            repo.add_evidence(c, echoed, source_type="confirmation", source_ref=m1, quote=None,
                              now=utc_now_iso())  # fmt: skip
            _backs(c, gone, m1)
        return {"short": [edited, echoed, gone]}

    by_key = run(storage, seed)
    run(storage, lambda c: service.forget_memories(c, [by_key["short"][2]]))
    assert signals.tally(run(storage, lambda c: signals.from_records(c, by_key))) == {}


# ----- forgetting the workplace forgets its relationship too ----------------------------------
def _workplace(c: driver.Connection, name: str) -> tuple[str, str]:
    now = utc_now_iso()
    mid = fact(c, None, "employer", name)
    with UnitOfWork(c, kind="user_edit", actor="user", summary="seed"):
        org = repo.insert_entity(c, kind="organization", name=name, relation=None,
                                 description=None, now=now)  # fmt: skip
    relationships.add_relationship(c, source_id="user", type="works_at", target_id=org.id)
    return mid, org.id


def test_forgetting_the_workplace_forgets_the_relationship(storage: StorageHandle) -> None:
    # Phase 10A real run g1: "Çalıştığım yeri unut" left user → works_at → Kervan Lojistik.
    run(storage, lambda c: _workplace(c, "Kervan Lojistik"))
    run(storage, lambda c: service.forget_topic(c, None, "employer"))
    rels = run(storage, lambda c: relationships.gs.relationships_of(c, "user"))
    assert [r for r in rels if r.type == "works_at"] == []
    assert run(storage, lambda c: repo.find_entities(c, "kervan lojistik")) == []
    gate = run(storage, proactive.load)
    assert gate.index.speaks_of("Kervan Lojistik'te çalışıyorsunuz.") == "value"


def test_forgetting_one_workplace_keeps_the_other(storage: StorageHandle) -> None:
    old, _ = run(storage, lambda c: _workplace(c, "Kervan Lojistik"))
    run(storage, lambda c: _workplace(c, "Atlas Yazılım"))
    run(storage, lambda c: service.forget_memories(c, [old]))
    rels = run(storage, lambda c: relationships.gs.relationships_of(c, "user"))
    names = {run(storage, lambda c, r=r: repo.get_entity(c, r.target_id)).name  # type: ignore[union-attr]
             for r in rels if r.type == "works_at"}  # fmt: skip
    assert names == {"Atlas Yazılım"}
