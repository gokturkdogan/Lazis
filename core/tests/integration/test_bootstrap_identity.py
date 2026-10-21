"""Namesakes in an import (Phase 8, condition A): 60 scenarios — what is stored × what the file
says × what the user decides. A person in the file is never matched to a stored one by itself:
nothing about a person is written until the user creates it, links it, or leaves it unresolved
— and every fact lands on exactly the person the user chose. Wrong-person writes must be 0.
Synthetic data only."""

from __future__ import annotations

import itertools
from typing import Any

import pytest

from lazis.bootstrap import store
from lazis.memory import repository as repo
from lazis.memory import resolver
from lazis.storage import StorageHandle
from tests.bootstrap_support import (
    approve_all,
    distinct,
    do_apply,
    facts_of,
    items,
    people,
    run,
    start,
    stored_person,
)

STORED = {
    "none": [],
    "neighbor": [("komşusu", {"occupation": "mimar"})],
    "both": [("komşusu", {"occupation": "mimar"}), ("iş arkadaşı", {"occupation": "muhasebeci"})],
    "bare": [(None, {"occupation": "pilot"})],
}
FILE = {
    "neighbor": [("komşum", "satranç")],
    "colleague": [("iş arkadaşım", "yüzme")],
    "cousin": [("kuzenim", "dalış")],
    "bare": [(None, "kayak")],
    "two": [("komşum", "satranç"), ("iş arkadaşım", "yüzme")],
}
DECISIONS = ["none", "create", "link"]
SCENARIOS = list(itertools.product(STORED, FILE, DECISIONS))
assert len(SCENARIOS) == 60


def seed(storage: StorageHandle, stored: str) -> list[str]:
    ids = [stored_person(storage, "Ahmet", rel, facts) for rel, facts in STORED[stored]]
    if len(ids) == 2:
        from lazis.ids import utc_now_iso
        from lazis.memory import graphstore as gs

        run(storage, lambda c: gs.add_distinction(c, ids[0], ids[1], utc_now_iso()))
    return ids


def file_doc(kind: str) -> dict[str, Any]:
    ppl = [
        {"id": f"a{i}", "name": "Ahmet", **({"relation": rel} if rel else {}),
         "facts": {"interest": hobby}}
        for i, (rel, hobby) in enumerate(FILE[kind])
    ]  # fmt: skip
    return {"people": ppl}


@pytest.mark.parametrize(("stored", "kind", "decision"), SCENARIOS)
def test_a_person_is_written_only_where_the_user_put_it(
    storage: StorageHandle, stored: str, kind: str, decision: str
) -> None:
    ids = seed(storage, stored)
    before = {eid: facts_of(storage, eid) for eid in ids}
    iid = start(storage, file_doc(kind))
    ps = people(storage, iid)
    assert len(ps) == len(FILE[kind])

    # 1. Nothing is matched by itself: a suggestion at most, and only a compatible, unique one.
    for p in ps:
        assert p.decision == "pending" and p.entity_id is None and p.link_id is None
        if p.match == "existing":
            assert p.suggested_id in ids
            e = run(storage, lambda c, s=p.suggested_id: repo.get_entity(c, s))
            assert e is not None and resolver.relation_compatible(p.relation, e.relation)
            others = [x for x in ids if x != p.suggested_id]
            assert (
                all(
                    not resolver.relation_compatible(
                        p.relation,
                        run(storage, lambda c, x=x: repo.get_entity(c, x)).relation,  # type: ignore[union-attr]
                    )
                    for x in others
                )
                or p.relation is None
            )
        if len(ids) == 2 and p.relation is None:
            assert p.match == "ambiguous"  # a bare name next to two stored Ahmets
    assert run(storage, lambda c: store.summary(c, iid))["writable"] == 0

    # 2. The user's decision.
    chosen: dict[str, str | None] = {}  # proposed person → entity it must land on (None: nowhere)
    for i, p in enumerate(ps):
        if decision == "none":
            chosen[p.id] = None
            continue
        if decision == "create" or not ids:
            run(storage, lambda c, p=p: store.decide_person(c, iid, p.id, "create"))
            chosen[p.id] = "new"
            continue
        target = p.suggested_id or ids[min(i, len(ids) - 1)]
        run(storage, lambda c, p=p, t=target: store.decide_person(c, iid, p.id, "link", t))
        chosen[p.id] = target
    approve_all(storage, iid)
    r = do_apply(storage, iid)

    # 3. Where everything went.
    wrong = 0
    after = {p.id: p for p in people(storage, iid)}
    for p in ps:
        hobby = next(it.payload["value"] for it in items(storage, iid)
                     if it.subject_ref == p.id and it.kind == "fact")  # fmt: skip
        want = chosen[p.id]
        landed = [e.id for e in run(storage, lambda c: repo.list_entities(c, limit=1000))
                  if ("interest", hobby) in facts_of(storage, e.id)]  # fmt: skip
        if want is None:
            wrong += len(landed)
            assert after[p.id].entity_id is None
        elif want == "new":
            eid = after[p.id].entity_id
            assert eid is not None and eid not in ids
            wrong += sum(1 for x in landed if x != eid)
            assert landed == [eid]
            for sid in ids:  # the user said "someone else": remembered as different people
                assert distinct(storage, eid, sid)
        else:
            wrong += sum(1 for x in landed if x != want)
            assert landed == [want]
    assert wrong == 0
    # Stored people keep what they had (an interest may be added to a linked one).
    for eid in ids:
        assert before[eid] <= facts_of(storage, eid)
        added = facts_of(storage, eid) - before[eid]
        assert all(x[0] == "interest" for x in added)
        if decision != "link":
            assert not added
    if decision == "none":
        assert r.counts["written"] == 0 and r.counts["people_created"] == 0
        # approved, but the person is not settled: facts and relationships alike are held back
        assert r.counts["blocked"] == r.counts["approved"] >= len(ps)


def test_two_namesakes_in_one_file_never_become_one(storage: StorageHandle) -> None:
    iid = start(storage, file_doc("two"))
    for p in people(storage, iid):
        run(storage, lambda c, p=p: store.decide_person(c, iid, p.id, "create"))
    approve_all(storage, iid)
    do_apply(storage, iid)
    ents = [
        e for e in run(storage, lambda c: repo.list_entities(c, limit=100)) if e.name == "Ahmet"
    ]
    assert len(ents) == 2 and distinct(storage, ents[0].id, ents[1].id)
    assert {frozenset(facts_of(storage, e.id)) for e in ents} == {
        frozenset({("interest", "satranç")}), frozenset({("interest", "yüzme")})}  # fmt: skip


def test_a_bare_reference_to_namesakes_in_the_file_is_not_guessed(storage: StorageHandle) -> None:
    doc = {"people": [{"id": "a1", "name": "Ahmet", "relation": "komşum"},
                      {"id": "a2", "name": "Ahmet", "relation": "iş arkadaşım"}],
           "facts": [{"about": "Ahmet", "predicate": "occupation", "value": "pilot"}]}  # fmt: skip
    iid = start(storage, doc)
    assert [it for it in items(storage, iid) if it.payload.get("value") == "pilot"] == []
    b = run(storage, lambda c: store.get_batch(c, iid))
    assert any("ambiguous_reference" in w for w in b.warnings)


def test_unresolved_and_rejected_people_write_nothing(storage: StorageHandle) -> None:
    ids = seed(storage, "both")
    iid = start(storage, file_doc("two"))
    a, b = people(storage, iid)
    run(storage, lambda c: store.decide_person(c, iid, a.id, "unresolved"))
    run(storage, lambda c: store.decide_person(c, iid, b.id, "reject"))
    for it in items(storage, iid):
        assert it.classification == "ambiguous_entity"
    approve_all(storage, iid)
    r = do_apply(storage, iid)
    assert r.counts["written"] == 0 and r.counts["blocked"] == r.counts["approved"] == 4
    assert facts_of(storage, ids[0]) == {("occupation", "mimar")}
    assert facts_of(storage, ids[1]) == {("occupation", "muhasebeci")}


def test_linking_to_a_missing_or_the_user_entity_is_refused(storage: StorageHandle) -> None:
    iid = start(storage, file_doc("neighbor"))
    (p,) = people(storage, iid)
    for bad in ("01J0000000000000000000000X", "user", p.id):
        with pytest.raises(store.DecisionError):
            run(storage, lambda c, bad=bad: store.decide_person(c, iid, p.id, "link", bad))
    with pytest.raises(store.DecisionError):
        run(storage, lambda c: store.decide_person(c, iid, p.id, "link", None))


def test_the_same_person_said_twice_can_be_linked_inside_the_file(storage: StorageHandle) -> None:
    doc = {"people": [{"id": "e1", "name": "Elif", "relation": "kuzenim",
                       "facts": {"occupation": "pilot"}},
                      {"id": "e2", "name": "Elif", "facts": {"location": "Muğla"}}]}  # fmt: skip
    iid = start(storage, doc)
    a, b = people(storage, iid)
    run(storage, lambda c: store.decide_person(c, iid, a.id, "create"))
    run(storage, lambda c: store.decide_person(c, iid, b.id, "link", a.id))
    approve_all(storage, iid)
    r = do_apply(storage, iid)
    assert r.counts["people_created"] == 1 and r.counts["written"] >= 2
    eid = people(storage, iid)[0].entity_id
    assert eid is not None
    assert {("occupation", "pilot"), ("location", "Muğla")} <= facts_of(storage, eid)
