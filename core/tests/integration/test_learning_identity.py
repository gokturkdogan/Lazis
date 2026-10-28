"""Identity safety with the Phase 9 learning (test group D): 60 scenarios — 4 names × 3 setups
(two namesakes stated in a message, two stored, one stored) × 5 messages (a list of siblings
with relation words for each namesake, a bare name, a past/current change, a birthday).
Everything lands on exactly the person the user's words name, or on nobody (a question) —
wrong-person facts and wrong-person relationships: 0. Scripted model, production engine,
encrypted database; synthetic data only."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from lazis.storage import StorageHandle
from tests.bootstrap_support import stored_person
from tests.learning_support import Brain, converse, item, rel

NAMES = {"Ahmet": "Ahmet'in", "Elif": "Elif'in", "Can": "Can'ın", "Zeynep": "Zeynep'in"}
SETUPS = ["stated_two", "stored_two", "stored_one"]
MESSAGES = ["neighbour_list", "colleague_list", "bare_list", "neighbour_moved", "bare_birthday"]
CASES = list(itertools.product(NAMES, SETUPS, MESSAGES))
assert len(CASES) == 60


def build(name: str, kind: str) -> tuple[str, Brain, list[str]]:
    gen = NAMES[name]
    if kind == "neighbour_list":
        msg = f"Komşum {gen} kardeşleri Mehmet ve Ali."
        ans = ([], [rel(msg.rstrip("."), name, "sibling", "Mehmet")])
        again = ([], [rel(msg.rstrip("."), name, "sibling", "Ali")])
        return msg, Brain(answers={msg: ans}, again={msg: again}), ["Mehmet", "Ali"]
    if kind == "colleague_list":
        msg = f"İş arkadaşım {gen} kardeşleri Cem ve Ece."
        ans = ([], [rel(msg.rstrip("."), name, "sibling", "Cem"),
                    rel(msg.rstrip("."), name, "sibling", "Ece")])  # fmt: skip
        return msg, Brain(answers={msg: ans}), ["Cem", "Ece"]
    if kind == "bare_list":
        msg = f"{gen} kardeşleri Oya ve Umut."
        ans = ([], [rel(msg.rstrip("."), name, "sibling", "Oya"),
                    rel(msg.rstrip("."), name, "sibling", "Umut")])  # fmt: skip
        return msg, Brain(answers={msg: ans}), ["Oya", "Umut"]
    if kind == "neighbour_moved":
        msg = f"Komşum {name} eskiden Bursa'da yaşıyordu, artık İzmir'de yaşıyor."
        ans = ([item(f"Komşum {name} eskiden Bursa'da yaşıyordu", "location", "Bursa",
                     entity=name, relation="komşum"),
                item("artık İzmir'de yaşıyor", "location", "İzmir", entity=name,
                     relation="komşum", change=True)], [])  # fmt: skip
        return msg, Brain(answers={msg: ans}), []
    msg = f"{gen} doğum günü 3 Mart."
    ans = ([item(msg.rstrip("."), "birthday", "3 Mart", entity=name)], [])
    return msg, Brain(answers={msg: ans}), []


def expected(setup: str, kind: str) -> str | None:
    """Which namesake it must land on: 'neighbour', 'colleague', or None (nobody: asked)."""
    if kind in ("neighbour_list", "neighbour_moved"):
        return "neighbour"
    if kind == "colleague_list":
        return None if setup == "stored_one" else "colleague"
    # A bare name: the only one, or nobody when there are two.
    return "neighbour" if setup == "stored_one" else None


@pytest.mark.parametrize(("name", "setup", "kind"), CASES)
def test_everything_lands_on_the_person_the_words_name(
    tmp_path: Path, storage: StorageHandle, name: str, setup: str, kind: str
) -> None:
    msg, brain, members = build(name, kind)
    turns = [msg]
    if setup == "stated_two":
        intro = f"İki {name} tanıyorum: biri komşum, diğeri iş arkadaşım."
        brain.answers[intro] = ([], [rel("biri komşum", "", "neighbor", name),
                                     rel("diğeri iş arkadaşım", "", "colleague", name)])  # fmt: skip
        turns.insert(0, intro)
    elif setup == "stored_two":
        stored_person(storage, name, "komşusu", {"interest": "satranç"})
        stored_person(storage, name, "iş arkadaşı", {"interest": "yüzme"})
        from lazis.ids import utc_now_iso
        from lazis.memory import graphstore as gs
        from lazis.memory import repository as repo

        ids = [e.id for e in storage.db.run_sync(lambda c: repo.list_entities(c)) if e.name == name]
        storage.db.run_sync(lambda c: gs.add_distinction(c, ids[0], ids[1], utc_now_iso()))
    else:
        stored_person(storage, name, "komşusu", {"interest": "satranç"})
    s = converse(tmp_path, storage, turns, brain)
    people = s.named(name)
    neighbour = next((p["id"] for p in people if "komşu" in (p["relation"] or "")), None)
    colleague = next((p["id"] for p in people if "iş arkadaş" in (p["relation"] or "")), None)
    want = {"neighbour": neighbour, "colleague": colleague, None: None}[expected(setup, kind)]
    namesake_ids = {p["id"] for p in people}
    # What this message taught about any person of this name:
    rels_here = [r for r in s.relationships if r["type"] == "sibling"
                 and (r["source_id"] in namesake_ids or r["target_id"] in namesake_ids)]  # fmt: skip
    facts_here = [f for f in s.facts if f["subject_id"] in namesake_ids
                  and f["predicate"] in ("location", "birthday")]  # fmt: skip
    wrong_rels = [r for r in rels_here if want is None or r["source_id"] != want]
    wrong_facts = [f for f in facts_here if want is None or f["subject_id"] != want]
    assert wrong_rels == [] and wrong_facts == []  # wrong person / wrong relationship: 0
    if want is not None and members:
        assert {r["target"] for r in rels_here} == set(members)
    if want is not None and kind == "neighbour_moved":
        assert {f["value"]: f["status"] for f in facts_here} == {"Bursa": "superseded",
                                                                 "İzmir": "active"}  # fmt: skip
    if want is not None and kind == "bare_birthday":
        assert [f["value"] for f in facts_here] == ["3 Mart"]
    if want is None and kind in ("bare_list", "bare_birthday"):
        assert any(i["type"] == "ambiguous_entity" for i in s.inbox)  # asked, not guessed
