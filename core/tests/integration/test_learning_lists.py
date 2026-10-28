"""Lists in background learning, end to end (Phase 9, test group A, part 2): the model reads
part of a list, a focused second read fills in the rest; nothing outside the list gets in;
a count that differs from the names given is kept as the user's words; namesakes are not
merged. Scripted model, production engine, encrypted database; synthetic data only."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from lazis.storage import StorageHandle
from tests.learning_support import Brain, converse, item, rel

NAMES = [("Mehmet", "Ali"), ("Ayşe", "Fatma", "Zeynep"), ("Can", "Cem", "Ece", "Oya")]
TYPES = [("kardeşi", "sibling"), ("çocuğu", "child"), ("kuzeni", "cousin"),
         ("arkadaşı", "friend")]  # fmt: skip
WORD = {2: "iki", 3: "üç", 4: "dört"}
CASES = list(itertools.product(NAMES, TYPES, ("all", "none", "intruder")))
assert len(CASES) == 36


@pytest.mark.parametrize(("names", "kind", "reread"), CASES)
def test_a_partly_read_list_is_completed_from_the_users_words_only(
    tmp_path: Path, storage: StorageHandle, names: tuple[str, ...], kind: tuple[str, str],
    reread: str,
) -> None:  # fmt: skip
    listed = ", ".join(names[:-1]) + " ve " + names[-1]
    msg = f"Ahmet'in {WORD[len(names)]} {kind[0]} var: {listed}."
    q = msg.rstrip(".")
    first = [rel(q, "Ahmet", kind[1], names[0])]
    if reread == "all":
        second = [rel(q, "Ahmet", kind[1], n) for n in names[1:]]
    elif reread == "none":
        second = []
    else:  # the re-read also proposes someone who is not in the list, and the first again
        second = [rel(q, "Ahmet", kind[1], n) for n in names[1:]]
        second += [rel(q, "Ahmet", kind[1], "Hakan"), rel(q, "Ahmet", kind[1], names[0])]
    brain = Brain(answers={msg: ([], first)}, again={msg: ([], second)})
    s = converse(tmp_path, storage, [msg], brain)
    assert f"again:{msg}" in brain.reads  # one focused re-read of the list
    expected = set(names) if reread != "none" else {names[0]}
    got = {r["target"] for r in s.relationships if r["source"] == "Ahmet"}
    assert got == expected
    assert not s.named("Hakan")  # nobody outside the list
    assert len(s.named("Ahmet")) == 1  # one Ahmet, not one per relationship


def test_a_fully_read_list_is_not_read_again(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Ahmet'in iki kardeşi var: Mehmet ve Ali."
    q = msg.rstrip(".")
    brain = Brain(answers={msg: ([], [rel(q, "Ahmet", "sibling", "Mehmet"),
                                      rel(q, "Ahmet", "sibling", "Ali")])})  # fmt: skip
    s = converse(tmp_path, storage, [msg], brain)
    assert [r for r in brain.reads if r.startswith("again:")] == []
    assert s.rel("Ahmet", "sibling", "Mehmet") and s.rel("Ahmet", "sibling", "Ali")


@pytest.mark.parametrize("said", [3, 4, 5])
def test_more_people_said_than_named_is_kept_in_the_users_words(
    tmp_path: Path, storage: StorageHandle, said: int
) -> None:
    word = {3: "üç", 4: "dört", 5: "beş"}[said]
    msg = f"Ahmet'in {word} kardeşi var: Mehmet ve Ali."
    q = msg.rstrip(".")
    brain = Brain(answers={msg: ([], [rel(q, "Ahmet", "sibling", "Mehmet"),
                                      rel(q, "Ahmet", "sibling", "Ali")])})  # fmt: skip
    s = converse(tmp_path, storage, [msg], brain)
    siblings = {r["target"] for r in s.relationships if r["type"] == "sibling"}
    assert siblings == {"Mehmet", "Ali"}  # nobody invented for the third
    (note,) = [f for f in s.facts if f["predicate"] == "note"]
    assert note["who"] == "Ahmet" and note["value"] in msg
    assert str(said) in note["content"] and "2" in note["content"]


@pytest.mark.parametrize(
    ("msg", "predicate", "members", "past"),
    [
        ("İstanbul, Ankara ve İzmir'de yaşadım.", "location", ("İstanbul", "Ankara", "İzmir"), True),
        ("Python, Rust ve Go biliyorum.", "technology", ("Python", "Rust", "Go"), False),
        ("Satranç, yüzme ve dalış ile ilgileniyorum.", "interest", ("satranç", "yüzme", "dalış"),
         False),
        ("Türkçe, İngilizce ve Almanca konuşurum.", "language", ("Türkçe", "İngilizce", "Almanca"),
         False),
    ],
)  # fmt: skip
def test_value_lists_are_completed_and_keep_their_time(
    tmp_path: Path, storage: StorageHandle, msg: str, predicate: str, members: tuple[str, ...],
    past: bool,
) -> None:  # fmt: skip
    q = msg.rstrip(".")
    brain = Brain(answers={msg: ([item(q, predicate, members[0])], [])},
                  again={msg: ([item(q, predicate, m) for m in members[1:]], [])})  # fmt: skip
    s = converse(tmp_path, storage, [msg], brain)
    status = "superseded" if past else "active"
    assert s.values("user", predicate, status) == set(members)
    if past:  # "yaşadım": every one of them is history — none is today's city
        assert s.values("user", predicate, "active") == set()


def test_a_list_after_namesakes_goes_to_the_right_one(
    tmp_path: Path, storage: StorageHandle
) -> None:
    intro = "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."
    msg = "Komşum Ahmet'in kardeşleri Mehmet ve Ali."
    q = msg.rstrip(".")
    brain = Brain(
        answers={
            intro: ([], [rel("biri komşum", "", "neighbor", "Ahmet"),
                         rel("diğeri iş arkadaşım", "", "colleague", "Ahmet")]),
            msg: ([], [rel(q, "Ahmet", "sibling", "Mehmet")]),
        },
        again={msg: ([], [rel(q, "Ahmet", "sibling", "Ali")])},
    )  # fmt: skip
    s = converse(tmp_path, storage, [intro, msg], brain)
    ahmets = s.named("Ahmet")
    assert len(ahmets) == 2
    neighbour = next(a for a in ahmets if "komşu" in (a["relation"] or ""))
    siblings = [r for r in s.relationships if r["type"] == "sibling"]
    assert {r["target"] for r in siblings} == {"Mehmet", "Ali"}
    # Both on the neighbour — none on the colleague (wrong-person relationships: 0).
    assert {r["source_id"] for r in siblings} == {neighbour["id"]}
