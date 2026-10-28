"""Lists in the user's words (Phase 9, test group A, part 1): 120 generated scenarios — two to
four people, projects, cities, preferences, stated counts that match or not — plus the rules
around them: a list is found, a partly extracted list is a gap, a second read keeps only the
missing members, a count that differs from the names given is kept as the user's words and
nobody is invented. Pure, synthetic data only."""

from __future__ import annotations

import itertools

import pytest

from lazis.memory import lists, text
from lazis.memory.extraction import Extracted, ExtractedRel
from lazis.memory.models import Candidate, EntityRef, RelCandidate

PEOPLE = [("Mehmet", "Ali"), ("Ayşe", "Fatma", "Zeynep"), ("Can", "Cem", "Ece", "Oya"),
          ("Nehir", "Umut"), ("Tarık", "Asya", "Dila")]  # fmt: skip
NOUNS = [("kardeşi", "sibling"), ("çocuğu", "child"), ("arkadaşı", "friend"),
         ("kuzeni", "cousin")]  # fmt: skip
COUNT_WORDS = {2: "iki", 3: "üç", 4: "dört", 5: "beş"}
# (people, noun, count said: the real count, one more, or none)
CASES = [
    (ppl, noun, said)
    for ppl, noun in itertools.product(PEOPLE, NOUNS)
    for said in ("match", "more", "none")
]
assert len(CASES) == 60


def sentence(ppl: tuple[str, ...], noun: str, said: str) -> str:
    names = ", ".join(ppl[:-1]) + " ve " + ppl[-1]
    if said == "none":
        return f"Ahmet'in {noun[:-1]}leri {names}." if noun.endswith("i") else f"{names}."
    n = len(ppl) + (1 if said == "more" else 0)
    return f"Ahmet'in {COUNT_WORDS[n]} {noun} var: {names}."


def rel(mid: str, source: str | None, type_: str, target: str) -> ExtractedRel:
    return ExtractedRel(mid, RelCandidate(type=type_, target=EntityRef(target),
                                          source=None if source is None else EntityRef(source)))  # fmt: skip


@pytest.mark.parametrize(("ppl", "noun", "said"), CASES)
def test_a_list_and_its_count_are_found(ppl: tuple[str, ...], noun: tuple[str, str],
                                        said: str) -> None:  # fmt: skip
    msg = sentence(ppl, noun[0], said)
    found = lists.enumerations(msg)
    assert len(found) == 1, (msg, found)
    e = found[0]
    assert e.members == ppl
    if said == "none":
        assert e.count is None
    else:
        assert e.count == len(ppl) + (1 if said == "more" else 0)


@pytest.mark.parametrize(("ppl", "noun", "said"), CASES)
def test_a_partly_read_list_is_a_gap_and_a_second_read_keeps_only_the_missing(
    ppl: tuple[str, ...], noun: tuple[str, str], said: str
) -> None:
    msg = sentence(ppl, noun[0], said)
    first = [rel("M", "Ahmet", noun[1], ppl[0])]  # the model stopped after the first name
    (gap,) = lists.gaps({"M": msg}, [], first)
    assert gap.missing == ppl[1:]
    assert gap.found == (f"Ahmet → {noun[1]} → {ppl[0]}",)
    note = lists.completion_note(gap)
    assert all(p in note for p in ppl[1:]) and "YALNIZCA" in note
    # The second read: the missing members, plus things that must not get in — a name not in
    # the list, and the first member again.
    second = [rel("M", "Ahmet", noun[1], p) for p in ppl[1:]]
    second += [rel("M", "Ahmet", noun[1], "Hakan"), rel("M", "Ahmet", noun[1], ppl[0])]
    _, kept = lists.keep_only_missing(gap, [], second)
    assert {r.candidate.target.name for r in kept} == set(ppl[1:])
    # Count: only a count that differs from the names given is kept as the user's words.
    notes = lists.count_notes({"M": msg}, [*first, *kept])
    if said == "more":
        (n,) = notes
        assert n.candidate.entity is not None and n.candidate.entity.name == "Ahmet"
        assert n.candidate.value in msg  # the user's own words, nothing invented
        assert str(len(ppl) + 1) in n.candidate.statement and str(len(ppl)) in n.candidate.statement
    else:
        assert notes == []


VALUES = [
    ("İstanbul, Ankara ve İzmir'de yaşadım.", "location", ("İstanbul", "Ankara", "İzmir")),
    ("Python, Rust ve Go biliyorum.", "technology", ("Python", "Rust", "Go")),
    ("Satranç, yüzme ve dalış ile ilgileniyorum.", "interest", ("Satranç", "yüzme", "dalış")),
    ("Kahve ve çay severim.", "likes", ("Kahve", "çay")),
    ("Türkçe, İngilizce ve Almanca konuşurum.", "language", ("Türkçe", "İngilizce", "Almanca")),
    ("İki projem var: LAZIS ve LINEUP.", "project_description", ("LAZIS", "LINEUP")),
    ("Gitar, keman ve piyano çalarım.", "skill", ("Gitar", "keman", "piyano")),
    ("Bursa ve Eskişehir'de çalıştım.", "location", ("Bursa", "Eskişehir")),
    ("Elma, armut ve kiraz severim.", "likes", ("Elma", "armut", "kiraz")),
    ("Vue, React ve Svelte kullandım.", "technology", ("Vue", "React", "Svelte")),
]


@pytest.mark.parametrize(("msg", "predicate", "members"), VALUES)
def test_value_lists_partly_read_are_gaps(msg: str, predicate: str,
                                          members: tuple[str, ...]) -> None:  # fmt: skip
    (e,) = lists.enumerations(msg)
    assert e.members == members
    first = [Extracted("M", Candidate(predicate=predicate, value=members[0], statement="x"))]
    (gap,) = lists.gaps({"M": msg}, first, [])
    assert gap.missing == members[1:]
    more = [Extracted("M", Candidate(predicate=predicate, value=m, statement="x"))
            for m in [*members[1:], "Paris"]]  # fmt: skip
    kept, _ = lists.keep_only_missing(gap, more, [])
    assert [k.candidate.value for k in kept] == list(members[1:])


@pytest.mark.parametrize(
    "msg",
    [
        "Bugün Ahmet ile buluştum.",  # one name
        "Hem komşum hem iş arkadaşım.",
        "Ahmet mimar.",
        "Sıcaktan hiç hoşlanmam, serin havaları tercih ederim.",
        "Yarın Ankara'ya gideceğim.",
    ],
)
def test_no_list_no_gap(msg: str) -> None:
    assert lists.enumerations(msg) == [] or all(
        len(e.members) >= 2 for e in lists.enumerations(msg)
    )
    assert lists.gaps({"M": msg}, [], [rel("M", None, "friend", "Ahmet")]) == []


def test_a_fully_read_list_is_no_gap() -> None:
    msg = "Ahmet'in iki kardeşi var: Mehmet ve Ali."
    both = [rel("M", "Ahmet", "sibling", "Mehmet"), rel("M", "Ahmet", "sibling", "Ali")]
    assert lists.gaps({"M": msg}, [], both) == []


def test_a_list_nothing_was_read_from_is_no_gap() -> None:
    """Nothing extracted about any member: the list may not be about anything to keep."""
    assert lists.gaps({"M": "Ahmet ve Mehmet geldi."}, [], []) == []


def test_namesakes_in_a_list_are_not_merged_into_one_key() -> None:
    msg = "Mehmet, Ali ve Mehmet geldi."
    assert lists.enumerations(msg) == []  # repeated name: not a list of distinct people


def test_keys_are_folded() -> None:
    (e,) = lists.enumerations("İzmir, Çanakkale ve Şile'de yaşadım.")
    assert e.keys == tuple(text.name_key(x) for x in ("İzmir", "Çanakkale", "Şile"))
