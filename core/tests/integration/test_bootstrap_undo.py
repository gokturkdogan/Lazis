"""Undoing an import (Phase 8, condition D). 24 profiles undone cleanly — the memory row by row
as it was before, the search index too — and 22 scenarios where something happened after the
import: a fact edited or confirmed in chat, a person used elsewhere, a value the import replaced,
a second import sharing a person, a memory deleted meanwhile, a repeated undo. Never
``DELETE … WHERE import_id``: what was there before and what was confirmed independently stays.
Synthetic data only."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from lazis.bootstrap import store, undo
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory import service
from lazis.memory.models import Candidate, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.bootstrap_support import (
    active,
    approve_all,
    create_all_people,
    decide,
    decide_person,
    distinct,
    do_apply,
    do_undo,
    item,
    items,
    people,
    plan,
    relationships,
    remember,
    run,
    snapshot,
    start,
    stored_person,
)

SECTIONS: dict[str, dict[str, Any]] = {
    "profile": {"profile": {"occupation": "veri analisti", "city": "İzmir"}},
    "people": {"people": [{"id": "e", "name": "Elif", "relation": "kuzenim",
                           "facts": {"occupation": "pilot", "interest": ["kayak"]}},
                          {"id": "a1", "name": "Ahmet", "relation": "komşum"},
                          {"id": "a2", "name": "Ahmet", "relation": "iş arkadaşım"}],
               "relationships": [{"from": "a1", "type": "sibling", "to": "e"}]},
    "projects": {"projects": [{"id": "p", "name": "Atlas", "status": "geliştiriliyor",
                               "technologies": ["Rust"]}]},
    "lists": {"preferences": ["filtre kahve"], "habits": ["sabah koşarım"],
              "goals": ["Japonca öğrenmek"], "facts": ["Bahçede iki kedi var."]},
}  # fmt: skip
PRIOR = ["none", "conflict_updated", "duplicate"]
PROFILES = [
    (combo, prior)
    for n in (1, 2, 4)
    for combo in itertools.combinations(SECTIONS, n)
    for prior in PRIOR
    if not (prior != "none" and "profile" not in combo)
]  # fmt: skip


def doc_of(combo: tuple[str, ...]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k in combo:
        for key, val in SECTIONS[k].items():
            out[key] = val
    return out


def fts_rows(storage: StorageHandle) -> int:
    return run(storage, lambda c: c.execute("SELECT COUNT(*) FROM memory_fts").fetchone()[0])


def apply_everything(storage: StorageHandle, doc: dict[str, Any], resolution: str = "update"
                     ) -> str:  # fmt: skip
    iid = start(storage, doc)
    create_all_people(storage, iid)
    approve_all(storage, iid, resolution=resolution)
    do_apply(storage, iid)
    return iid


@pytest.mark.parametrize(
    ("combo", "prior"), PROFILES, ids=lambda x: "+".join(x) if isinstance(x, tuple) else x
)
def test_an_undo_gives_back_exactly_the_memory_before(
    storage: StorageHandle, combo: tuple[str, ...], prior: str
) -> None:
    if prior == "conflict_updated":
        remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    elif prior == "duplicate":
        remember(storage, "location", "İzmir", "Kullanıcı İzmir'de yaşıyor.")
    before, fts = snapshot(storage), fts_rows(storage)
    iid = apply_everything(storage, doc_of(combo))
    assert snapshot(storage) != before
    p = plan(storage, iid)
    assert p.count("decide") == 0 and p.count("keep") == 0  # nothing happened since
    if prior == "conflict_updated":
        assert p.count("restore") == 1  # Ankara comes back
    if prior == "duplicate":
        assert p.count("remove_evidence") == 1  # İzmir stays, without the file's evidence
    done = do_undo(storage, iid)
    assert done.counts() == p.counts()
    assert snapshot(storage) == before and fts_rows(storage) == fts
    b = run(storage, lambda c: store.get_batch(c, iid))
    assert b.status == "undone" and b.undo_change_set_id and b.counts["undo"]["remove"] >= 1
    again = do_undo(storage, iid)  # a second undo changes nothing
    assert again.already_undone and snapshot(storage) == before


assert len(PROFILES) >= 20


def test_a_fact_edited_after_the_import_is_kept(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("profile",)))
    (m,) = [x for x in run(storage, lambda c: repo.list_memories(c)) if x.value == "veri analisti"]
    run(storage, lambda c: service.edit_memory(c, m.id, value="kıdemli veri analisti",
                                               content="Kullanıcı kıdemli veri analisti."))  # fmt: skip
    p = plan(storage, iid)
    assert [(s.action, s.reason) for s in p.steps if s.target_id == m.id] == [
        ("keep", "changed_later")
    ]
    do_undo(storage, iid)
    assert active(storage) == {("user", "occupation", "kıdemli veri analisti")}


def test_a_fact_confirmed_in_chat_stays_without_the_files_evidence(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("lists",)))
    remember(storage, "habit", "sabah koşarım", "Kullanıcı sabahları koşar.", source="message")
    p = plan(storage, iid)
    kept = [s for s in p.steps if s.action == "keep"]
    assert [s.reason for s in kept] == ["confirmed_elsewhere"]
    do_undo(storage, iid)
    assert active(storage) == {("user", "habit", "sabah koşarım")}
    ev = run(storage, lambda c: c.execute("SELECT source_type FROM memory_evidence").fetchall())
    assert [e[0] for e in ev] == ["message"]


def test_a_person_used_elsewhere_after_the_import_stays(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people",)))
    elif_ = next(p.entity_id for p in people(storage, iid) if p.name == "Elif")
    assert elif_ is not None
    remember(storage, "location", "Muğla", "Elif Muğla'da yaşıyor.",
             entity=EntityRef("Elif", "person", "kuzeni", ref_id=elif_, planned=True),
             source="message")  # fmt: skip
    p = plan(storage, iid)
    assert ("keep", "still_referred_to") in [(s.action, s.reason) for s in p.steps
                                             if s.target_id == elif_]  # fmt: skip
    do_undo(storage, iid)
    assert active(storage) == {("Elif", "location", "Muğla")}
    assert run(storage, lambda c: repo.get_entity(c, elif_)) is not None
    assert relationships(storage) == set()  # the import's relationships are gone


def test_a_person_given_a_new_alias_after_the_import_stays(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people",)))
    elif_ = next(p.entity_id for p in people(storage, iid) if p.name == "Elif")
    run(storage, lambda c: repo.add_alias(c, str(elif_), "Elo"))
    do_undo(storage, iid)
    ents = run(storage, lambda c: repo.list_entities(c, limit=100))
    assert [e.name for e in ents] == ["Elif"] and active(storage) == set()


def test_a_value_the_import_replaced_comes_back(storage: StorageHandle) -> None:
    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    iid = apply_everything(storage, {"profile": {"city": "İzmir"}})
    assert active(storage) == {("user", "location", "İzmir")}
    do_undo(storage, iid)
    assert active(storage) == {("user", "location", "Ankara")}


def test_a_replacement_kept_after_an_edit_does_not_bring_the_old_value_back(
    storage: StorageHandle,
) -> None:
    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    iid = apply_everything(storage, {"profile": {"city": "İzmir"}})
    (m,) = run(storage, lambda c: repo.list_memories(c))
    run(storage, lambda c: service.edit_memory(c, m.id, value="İzmir, Bornova",
                                               content="Kullanıcı Bornova'da yaşıyor."))  # fmt: skip
    p = plan(storage, iid)
    reasons = {(s.action, s.reason) for s in p.steps}
    assert ("keep", "changed_later") in reasons and ("decide", "replacement_kept") in reasons
    do_undo(storage, iid)
    assert active(storage) == {("user", "location", "İzmir, Bornova")}  # one current value


def test_the_user_can_choose_to_restore_a_record_left_to_them(storage: StorageHandle) -> None:
    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    iid = apply_everything(storage, {"profile": {"city": "İzmir"}})
    (m,) = run(storage, lambda c: repo.list_memories(c))
    old = next(x for x in run(storage, lambda c: repo.list_memories(c, status=None))
               if x.value == "Ankara")  # fmt: skip
    run(storage, lambda c: service.edit_memory(c, m.id, value="İzmir, Bornova",
                                               content="Kullanıcı Bornova'da yaşıyor."))  # fmt: skip
    run(storage, lambda c: service.forget_memories(c, [m.id]))  # and then forgets it
    p = plan(storage, iid)
    assert ("decide", "replacement_kept") not in {(s.action, s.reason) for s in p.steps}
    assert any(s.action == "gone" for s in p.steps)
    do_undo(storage, iid, restore=[old.id])
    assert active(storage) == {("user", "location", "Ankara")}


def test_a_decide_step_is_restored_only_when_chosen(storage: StorageHandle) -> None:
    eid = stored_person(storage, "Mehmet", None, {"location": "İstanbul"})
    iid = start(storage, {"people": [{"name": "Mehmet", "facts": {"location": "Ankara"}}]})
    decide_person(storage, iid, "Mehmet", "link", eid)
    it = item(storage, iid, "Ankara")
    decide(storage, iid, it.id, "approve", resolution="update")
    do_apply(storage, iid)
    old = next(x for x in run(storage, lambda c: repo.list_memories(c, status=None))
               if x.value == "İstanbul")  # fmt: skip
    # The user edits the old (now past) value after the import.
    run(storage, lambda c: service.edit_memory(c, old.id, value="İstanbul, Kadıköy",
                                               content="Mehmet Kadıköy'de yaşıyordu."))  # fmt: skip
    p = plan(storage, iid)
    steps = {(s.action, s.reason) for s in p.steps if s.target_id == old.id}
    assert steps == {("decide", "changed_later")}
    do_undo(storage, iid)  # not chosen: left as it is (past), the import's value removed
    st = {m.value: m.status for m in run(storage, lambda c: repo.list_memories(c, status=None))}
    assert st == {"İstanbul, Kadıköy": "superseded"}


def test_a_decide_step_chosen_for_restore_is_restored(storage: StorageHandle) -> None:
    eid = stored_person(storage, "Mehmet", None, {"location": "İstanbul"})
    iid = start(storage, {"people": [{"name": "Mehmet", "facts": {"location": "Ankara"}}]})
    decide_person(storage, iid, "Mehmet", "link", eid)
    decide(storage, iid, item(storage, iid, "Ankara").id, "approve", resolution="update")
    do_apply(storage, iid)
    old = next(x for x in run(storage, lambda c: repo.list_memories(c, status=None))
               if x.value == "İstanbul")  # fmt: skip
    run(storage, lambda c: service.edit_memory(c, old.id, value="İstanbul, Kadıköy",
                                               content="Mehmet Kadıköy'de yaşıyordu."))  # fmt: skip
    do_undo(storage, iid, restore=[old.id])
    assert active(storage) == {("Mehmet", "location", "İstanbul, Kadıköy")}
    b = run(storage, lambda c: store.get_batch(c, iid))
    assert b.counts["undo"]["restored_by_choice"] == 1


def test_evidence_added_to_an_existing_fact_is_removed(storage: StorageHandle) -> None:
    remember(storage, "location", "İzmir", "Kullanıcı İzmir'de yaşıyor.")
    before = snapshot(storage)
    iid = apply_everything(storage, {"profile": {"city": "İzmir"}})
    assert snapshot(storage)["memory_evidence"] != before["memory_evidence"]
    do_undo(storage, iid)
    assert snapshot(storage) == before


def test_a_relationship_confirmed_in_chat_stays(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people",)))
    ids = {p.relation: p.entity_id for p in people(storage, iid)}
    a1, e = ids["komşusu"], ids["kuzeni"]
    rc = RelCandidate(type="sibling", target=EntityRef("x"), source=None, quote="kardeşler",
                      statement="Ahmet ile Elif kardeş.", origin="stated")  # fmt: skip
    rep = rels.RelReport()
    from lazis.ids import utc_now_iso
    from lazis.storage.unit_of_work import UnitOfWork

    def confirm(c: Any) -> None:
        with UnitOfWork(c, kind="learning_run", actor="pipeline", summary="t") as uow:
            rels.apply_one(c, uow, rc, source=Source("message", "m1"), explicit=True, report=rep,
                           now=utc_now_iso(), forced_source=a1, forced_target=e)  # fmt: skip

    run(storage, confirm)
    do_undo(storage, iid)
    assert {(s, t, d) for s, t, d, st in relationships(storage) if st == "active"} == {
        ("Ahmet", "sibling", "Elif")}  # fmt: skip
    names = sorted(x.name for x in run(storage, lambda c: repo.list_entities(c, limit=100)))
    assert names == ["Ahmet", "Elif"]  # the two ends stay; the other Ahmet goes


def test_distinctions_and_rejections_the_import_made_are_undone(storage: StorageHandle) -> None:
    eid = stored_person(storage, "Ahmet", "komşusu", {"occupation": "mimar"})
    iid = start(storage, {"people": [{"name": "Ahmet", "relation": "iş arkadaşım",
                                      "facts": {"occupation": "avukat"}}],
                          "profile": {"occupation": "pilot"}})  # fmt: skip
    decide_person(storage, iid, "Ahmet", "create")
    decide(storage, iid, item(storage, iid, "avukat").id, "approve")
    decide(storage, iid, item(storage, iid, "pilot").id, "reject")
    do_apply(storage, iid)
    new = next(p.entity_id for p in people(storage, iid))
    assert new is not None and distinct(storage, eid, new)
    sup = run(storage, lambda c: c.execute("SELECT COUNT(*) FROM memory_suppressions WHERE reason"
                                           " = 'rejected'").fetchone()[0])  # fmt: skip
    assert sup == 1
    do_undo(storage, iid)
    assert run(storage, lambda c: c.execute("SELECT COUNT(*) FROM memory_entity_distinctions"
                                            ).fetchone()[0]) == 0  # fmt: skip
    assert run(storage, lambda c: c.execute("SELECT COUNT(*) FROM memory_suppressions"
                                            ).fetchone()[0]) == 0  # fmt: skip
    c2 = Candidate(predicate="occupation", value="pilot", statement="Kullanıcı pilot.")
    rep = run(storage, lambda c: service.apply_candidates(c, [c2], source=Source("message"),
                                                         explicit=True))  # fmt: skip
    assert rep.created  # learnable again


def test_two_imports_undo_independently(storage: StorageHandle) -> None:
    before = snapshot(storage)
    i1 = apply_everything(storage, doc_of(("lists",)))
    mid = snapshot(storage)
    i2 = apply_everything(storage, doc_of(("projects",)))
    do_undo(storage, i1)
    assert {p for _, p, _ in active(storage)} == {"project_status", "project_technology"}
    do_undo(storage, i2)
    assert snapshot(storage) == before
    assert mid != before


def test_a_person_shared_with_a_later_import_stays(storage: StorageHandle) -> None:
    i1 = apply_everything(storage, {"people": [{"name": "Elif", "relation": "kuzenim",
                                                "facts": {"occupation": "pilot"}}]})  # fmt: skip
    elif_ = next(p.entity_id for p in people(storage, i1))
    i2 = start(storage, {"people": [{"name": "Elif", "relation": "kuzenim",
                                     "facts": {"location": "Muğla"}}]})  # fmt: skip
    decide_person(storage, i2, "Elif", "link", elif_)
    approve_all(storage, i2)
    do_apply(storage, i2)
    do_undo(storage, i1)
    assert active(storage) == {("Elif", "location", "Muğla")}
    assert run(storage, lambda c: repo.get_entity(c, str(elif_))) is not None
    do_undo(storage, i2)
    assert active(storage) == set()


def test_undo_in_reverse_order_restores_everything(storage: StorageHandle) -> None:
    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    before = snapshot(storage)
    i1 = apply_everything(storage, {"profile": {"city": "İzmir"}})
    i2 = apply_everything(storage, {"profile": {"city": "Bursa"}})
    do_undo(storage, i2)
    assert active(storage) == {("user", "location", "İzmir")}
    do_undo(storage, i1)
    assert snapshot(storage) == before


def test_undo_out_of_order_leaves_the_later_value(storage: StorageHandle) -> None:
    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    i1 = apply_everything(storage, {"profile": {"city": "İzmir"}})
    apply_everything(storage, {"profile": {"city": "Bursa"}})
    p = plan(storage, i1)
    # İzmir was replaced by the second import: changed later, so it is the user's to decide.
    assert p.count("remove") == 0
    do_undo(storage, i1)
    assert active(storage) == {("user", "location", "Bursa")}


def test_a_memory_deleted_since_is_gone_not_an_error(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("lists",)))
    (m, *_) = run(storage, lambda c: repo.list_memories(c))
    run(storage, lambda c: service.forget_memories(c, [m.id]))
    p = plan(storage, iid)
    assert any(s.action == "gone" and s.target_id == m.id for s in p.steps)
    do_undo(storage, iid)
    assert active(storage) == set()


def test_undo_is_refused_before_apply(storage: StorageHandle) -> None:
    iid = start(storage, doc_of(("lists",)))
    with pytest.raises(undo.UndoRefused) as e:
        plan(storage, iid)
    assert e.value.code == "not_applied"
    with pytest.raises(undo.UndoRefused):
        do_undo(storage, iid)


def test_the_plan_writes_nothing(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people", "lists")))
    snap = snapshot(storage)
    for _ in range(3):
        plan(storage, iid)
    assert snapshot(storage) == snap


def test_the_graph_stays_consistent_after_undo(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people", "projects")))
    do_undo(storage, iid)

    def orphans(c: Any) -> int:
        q = [
            "SELECT COUNT(*) FROM memory_relationships r WHERE NOT EXISTS (SELECT 1 FROM"
            " memory_entities e WHERE e.id = r.source_id) OR NOT EXISTS (SELECT 1 FROM"
            " memory_entities e WHERE e.id = r.target_id)",
            "SELECT COUNT(*) FROM memories m WHERE m.subject_id IS NOT NULL AND NOT EXISTS"
            " (SELECT 1 FROM memory_entities e WHERE e.id = m.subject_id)",
            "SELECT COUNT(*) FROM memory_evidence v WHERE NOT EXISTS (SELECT 1 FROM memories m"
            " WHERE m.id = v.memory_id)",
            "SELECT COUNT(*) FROM memory_entity_aliases a WHERE NOT EXISTS (SELECT 1 FROM"
            " memory_entities e WHERE e.id = a.entity_id)",
        ]
        return sum(int(c.execute(x).fetchone()[0]) for x in q)

    assert run(storage, orphans) == 0
    assert run(storage, lambda c: gs.edges_from(c, "user", ("active",))) == []


def test_undo_runs_in_one_rollback_change_set(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("people", "lists")))
    do_undo(storage, iid)
    b = run(storage, lambda c: store.get_batch(c, iid))
    rows = run(storage, lambda c: c.execute(
        "SELECT kind, reverts_change_set_id FROM change_sets WHERE id = ?", (b.undo_change_set_id,)).fetchall())  # fmt: skip
    assert rows == [("rollback", b.apply_change_set_id)]


def test_items_of_an_undone_import_cannot_be_applied_again(storage: StorageHandle) -> None:
    iid = apply_everything(storage, doc_of(("lists",)))
    do_undo(storage, iid)
    from lazis.bootstrap import apply

    with pytest.raises(apply.ApplyRefused):
        do_apply(storage, iid)
    assert items(storage, iid)  # the record of what was imported stays (no content of the file)
