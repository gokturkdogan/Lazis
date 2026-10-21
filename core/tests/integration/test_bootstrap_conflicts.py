"""Conflicts with what is stored (Phase 8, condition C): 48 single-valued facts × (the file
says it changed / it does not) × (keep the old, update, keep both, decide later), plus
duplicates, a person's facts, relationships, and memory that changes between the preview and
the write. Existing memory is never changed silently. Synthetic data only."""

from __future__ import annotations

import itertools

import pytest

from lazis.bootstrap import apply, store
from lazis.memory import repository as repo
from lazis.storage import StorageHandle
from tests.bootstrap_support import (
    active,
    decide,
    decide_person,
    do_apply,
    facts_of,
    item,
    items,
    relationships,
    remember,
    run,
    start,
    stored_person,
)

CASES = {  # predicate: (stored, file)
    "location": ("Ankara", "İzmir"),
    "occupation": ("öğretmen", "veri analisti"),
    "employer": ("Kervan Lojistik", "Pusula Yazılım"),
    "phone": ("Pixel 6", "iPhone 15"),
    "computer": ("ThinkPad X1", "MacBook Air"),
    "birthday": ("3 Mart", "4 Mart"),
}
MODES = ["plain", "timed"]
CHOICES = ["keep_old", "update", "keep_both", "hold"]
SCENARIOS = list(itertools.product(CASES, MODES, CHOICES))
assert len(SCENARIOS) == 48


def statuses(storage: StorageHandle, predicate: str) -> dict[str, str]:
    ms = run(storage, lambda c: repo.list_memories(c, status=None, limit=1000))
    return {m.value: m.status for m in ms if m.predicate == predicate and m.subject_id is None}


@pytest.mark.parametrize(("predicate", "mode", "choice"), SCENARIOS)
def test_a_conflict_is_the_users_to_resolve(
    storage: StorageHandle, predicate: str, mode: str, choice: str
) -> None:
    old, new = CASES[predicate]
    remember(storage, predicate, old, f"Kullanıcı — {predicate}: {old}")
    entry = {"about": "user", "predicate": predicate, "value": new}
    if mode == "timed":
        entry["since"] = "2025"
    iid = start(storage, {"facts": [entry]})
    it = item(storage, iid, new)
    assert it.classification == ("temporal_update" if mode == "timed" else "conflict")
    assert it.existing == (old,)
    with pytest.raises(store.DecisionError) as e:  # "approve" alone is not enough
        decide(storage, iid, it.id, "approve")
    assert e.value.code == "needs_resolution"
    if choice == "hold":
        decide(storage, iid, it.id, "hold")
    else:
        decide(storage, iid, it.id, "approve", resolution=choice)
    r = do_apply(storage, iid)
    st = statuses(storage, predicate)
    if choice == "keep_old":
        assert st == {old: "active"} and r.counts["kept_old"] == 1 and r.counts["written"] == 0
    elif choice == "update":
        assert st == {old: "superseded", new: "active"} and r.counts["updated"] == 1
    elif choice == "keep_both":
        assert st == {old: "active", new: "active"} and r.counts["written"] == 1
        assert r.counts["updated"] == 0
    else:
        assert st == {old: "active"} and r.counts["held"] == 1 and r.counts["written"] == 0


def test_an_exact_duplicate_only_adds_the_file_as_evidence(storage: StorageHandle) -> None:
    remember(storage, "location", "İzmir", "Kullanıcı İzmir'de yaşıyor.")
    before = active(storage)
    iid = start(storage, {"profile": {"city": "İzmir"}})
    it = item(storage, iid, "İzmir")
    assert it.classification == "exact_duplicate"
    decide(storage, iid, it.id, "approve")
    r = do_apply(storage, iid)
    assert r.counts["evidence_added"] == 1 and r.counts["written"] == 0
    assert active(storage) == before
    (m,) = run(storage, lambda c: repo.list_memories(c, limit=10))
    ev = run(storage, lambda c: c.execute("SELECT source_type FROM memory_evidence WHERE"
                                          " memory_id = ?", (m.id,)).fetchall())  # fmt: skip
    assert sorted(x[0] for x in ev) == ["import", "user_edit"]


def test_a_multi_valued_fact_is_new_not_a_conflict(storage: StorageHandle) -> None:
    remember(storage, "interest", "satranç", "Kullanıcı satranç oynamayı seviyor.")
    iid = start(storage, {"profile": {"interests": ["yüzme"]}})
    assert item(storage, iid, "yüzme").classification == "new"


@pytest.mark.parametrize("choice", CHOICES)
def test_a_linked_persons_fact_conflicts_with_its_stored_value(
    storage: StorageHandle, choice: str
) -> None:
    eid = stored_person(storage, "Ahmet", "komşusu", {"occupation": "mimar"})
    iid = start(storage, {"people": [{"name": "Ahmet", "relation": "komşum",
                                      "facts": {"occupation": "pilot"}}]})  # fmt: skip
    it = item(storage, iid, "pilot")
    # Before the person is linked it is compared with the suggestion, never written.
    decide_person(storage, iid, "Ahmet", "link", eid)
    it = item(storage, iid, "pilot")
    assert it.classification == "conflict" and it.existing == ("mimar",)
    if choice == "hold":
        decide(storage, iid, it.id, "hold")
    else:
        decide(storage, iid, it.id, "approve", resolution=choice)
    do_apply(storage, iid)
    got = facts_of(storage, eid)
    want = {"keep_old": {("occupation", "mimar")}, "hold": {("occupation", "mimar")},
            "update": {("occupation", "pilot")},
            "keep_both": {("occupation", "mimar"), ("occupation", "pilot")}}[choice]  # fmt: skip
    assert got == want


def test_creating_the_person_instead_turns_the_conflict_into_new(storage: StorageHandle) -> None:
    stored_person(storage, "Ahmet", "komşusu", {"occupation": "mimar"})
    iid = start(storage, {"people": [{"name": "Ahmet", "relation": "komşum",
                                      "facts": {"occupation": "pilot"}}]})  # fmt: skip
    decide_person(storage, iid, "Ahmet", "create")
    assert item(storage, iid, "pilot").classification == "new"


def test_a_resolution_is_dropped_when_the_conflict_goes_away(storage: StorageHandle) -> None:
    eid = stored_person(storage, "Ahmet", "komşusu", {"occupation": "mimar"})
    iid = start(storage, {"people": [{"name": "Ahmet", "relation": "komşum",
                                      "facts": {"occupation": "pilot"}}]})  # fmt: skip
    decide_person(storage, iid, "Ahmet", "link", eid)
    it = item(storage, iid, "pilot")
    decide(storage, iid, it.id, "approve", resolution="update")
    decide_person(storage, iid, "Ahmet", "create")
    it = item(storage, iid, "pilot")
    assert it.classification == "new" and it.resolution is None and it.decision == "approve"


def test_a_change_in_memory_after_the_preview_stops_the_write(storage: StorageHandle) -> None:
    iid = start(storage, {"profile": {"city": "İzmir"}})
    it = item(storage, iid, "İzmir")
    assert it.classification == "new"
    decide(storage, iid, it.id, "approve")
    remember(storage, "location", "Bursa", "Kullanıcı Bursa'ya taşındı.")  # said in chat meanwhile
    with pytest.raises(apply.ApplyRefused) as e:
        do_apply(storage, iid)
    assert e.value.code == "memory_changed" and e.value.items == (it.id,)
    assert run(storage, lambda c: store.get_batch(c, iid)).status == "ready"
    assert ("user", "location", "Bursa") in active(storage)
    assert ("user", "location", "İzmir") not in active(storage)
    run(storage, lambda c: store.refresh(c, iid))
    it = item(storage, iid, "İzmir")
    assert it.classification == "conflict" and it.existing == ("Bursa",)
    assert run(storage, lambda c: store.blocked(c, iid, it)) == "needs_resolution"


def test_relationship_already_stored_is_a_duplicate(storage: StorageHandle) -> None:
    iid = start(storage, {"people": [{"id": "e", "name": "Elif", "relation": "kuzenim"}]})
    decide_person(storage, iid, "Elif", "create")
    for it in items(storage, iid):
        decide(storage, iid, it.id, "approve")
    do_apply(storage, iid)
    eid = run(storage, lambda c: [e.id for e in repo.list_entities(c) if e.name == "Elif"])[0]
    iid2 = start(storage, {"people": [{"id": "e", "name": "Elif", "relation": "kuzenim"}]})
    decide_person(storage, iid2, "Elif", "link", eid)
    (rel,) = [it for it in items(storage, iid2) if it.kind == "relationship"]
    assert rel.classification == "exact_duplicate"


@pytest.mark.parametrize("choice", ["update", "keep_both", "keep_old"])
def test_a_second_spouse_is_a_conflict_not_a_silent_replacement(
    storage: StorageHandle, choice: str
) -> None:
    iid = start(storage, {"people": [{"id": "d", "name": "Deniz", "relation": "eşim"}]})
    decide_person(storage, iid, "Deniz", "create")
    for it in items(storage, iid):
        decide(storage, iid, it.id, "approve")
    do_apply(storage, iid)
    iid2 = start(storage, {"people": [{"id": "s", "name": "Selin", "relation": "eşim"}]})
    decide_person(storage, iid2, "Selin", "create")
    (rel,) = [it for it in items(storage, iid2) if it.kind == "relationship"]
    assert rel.classification == "conflict" and rel.existing
    with pytest.raises(store.DecisionError):
        decide(storage, iid2, rel.id, "approve")
    decide(storage, iid2, rel.id, "approve", resolution=choice)
    for it in items(storage, iid2):
        if it.id != rel.id:
            decide(storage, iid2, it.id, "approve")
    do_apply(storage, iid2)
    spouses = {(t, st) for s_, ty, t, st in relationships(storage) if ty == "spouse"}
    want = {"update": {("Deniz", "superseded"), ("Selin", "active")},  # the old one is history
            "keep_both": {("Deniz", "active"), ("Selin", "active")},
            "keep_old": {("Deniz", "active")}}[choice]  # fmt: skip
    assert spouses == want
