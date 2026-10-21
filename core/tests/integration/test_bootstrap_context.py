"""Condition E (Phase 8): a person whose identity is not settled is never used as context.
After an import with two Ahmets, "Ahmet'in kardeşi kim?" brings neither Ahmet's facts or
relationships — the namesakes are listed so the assistant asks which one; "Komşum Ahmet'in
mesleği" brings only the neighbour's. Synthetic data only."""

from __future__ import annotations

import pytest

from lazis.memory import retrieval
from lazis.storage import StorageHandle
from tests.bootstrap_support import approve_all, create_all_people, do_apply, run, start

DOC = {
    "people": [
        {"id": "ak", "name": "Ahmet", "relation": "komşum", "facts": {"occupation": "mimar"}},
        {"id": "ai", "name": "Ahmet", "relation": "iş arkadaşım",
         "facts": {"occupation": "muhasebeci"}},
        {"id": "e", "name": "Elif", "facts": {"occupation": "pilot"}},
        {"id": "z", "name": "Zeynep", "facts": {"occupation": "avukat"}},
    ],
    "relationships": [{"from": "ak", "type": "sibling", "to": "e"},
                      {"from": "ai", "type": "sibling", "to": "z"}],
    "profile": {"occupation": "veri analisti"},
}  # fmt: skip


@pytest.fixture
def two_ahmets(storage: StorageHandle) -> StorageHandle:
    iid = start(storage, DOC)
    create_all_people(storage, iid)
    approve_all(storage, iid)
    r = do_apply(storage, iid)
    assert r.counts["people_created"] == 4
    return storage


def recall(storage: StorageHandle, query: str, previous: str = "") -> retrieval.Recall:
    return run(storage, lambda c: retrieval.recall(c, query, previous=previous, budget_chars=3000))


def text_of(r: retrieval.Recall) -> str:
    return " | ".join([*(i.memory.content for i in r.items), *r.answer,
                       *(x for v in r.relations.values() for x in v)])  # fmt: skip


@pytest.mark.parametrize(
    "query",
    [
        "Ahmet'in kardeşi kim?",
        "Ahmet ne iş yapıyor?",
        "Ahmet'in mesleği neydi?",
        "Ahmet hakkında ne biliyorsun?",
        "Ahmet'e ne hediye alsam?",
    ],
)
def test_a_bare_name_with_namesakes_brings_neither(two_ahmets: StorageHandle, query: str) -> None:
    r = recall(two_ahmets, query)
    got = text_of(r)
    for leaked in ("mimar", "muhasebeci", "Elif", "Zeynep"):
        assert leaked not in got, (query, got)
    names = dict(r.ambiguous)
    assert "Ahmet" in names and len(names["Ahmet"]) == 2  # so the assistant asks which one


@pytest.mark.parametrize(
    ("query", "want", "never"),
    [
        ("Komşum Ahmet'in mesleği ne?", "mimar", "muhasebeci"),
        ("İş arkadaşım Ahmet ne iş yapıyor?", "muhasebeci", "mimar"),
        ("Ahmet, komşum olan, ne iş yapıyor?", "mimar", "muhasebeci"),
    ],
)
def test_relation_words_settle_which_one(
    two_ahmets: StorageHandle, query: str, want: str, never: str
) -> None:
    got = text_of(recall(two_ahmets, query))
    assert want in got and never not in got, got


def test_a_follow_up_without_the_name_does_not_pick_one(two_ahmets: StorageHandle) -> None:
    r = recall(two_ahmets, "Peki kardeşi ne iş yapıyor?", previous="Ahmet'i hatırlıyor musun?")
    got = text_of(r)
    for leaked in ("mimar", "muhasebeci", "pilot", "avukat"):
        assert leaked not in got, got


def test_unrelated_questions_still_get_the_users_facts(two_ahmets: StorageHandle) -> None:
    got = text_of(recall(two_ahmets, "Mesleğim ne?"))
    assert "veri analisti" in got


def test_a_single_unambiguous_person_is_still_recalled(two_ahmets: StorageHandle) -> None:
    got = text_of(recall(two_ahmets, "Elif ne iş yapıyor?"))
    assert "pilot" in got
