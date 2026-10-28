"""Conflicts and corrections (Phase 9, test group E): a different value without words that say
it changed is asked about, not written over; with such words it updates (the old one stays as
history); "Hayır, X değil Y (demek istedim)" corrects who it was about or the value — also
when the message was not learned from yet — and asks when Y could be several people.
Scripted model, production engine, encrypted database; synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazis.memory import corrections
from lazis.storage import StorageHandle
from tests.learning_support import Brain, converse, item, rel

# (who, predicate, old, new) — "who" "" is the user
CHANGES = [("", "location", "Ankara", "İzmir"), ("", "occupation", "öğretmen", "mimar"),
           ("", "employer", "Kervan", "Pusula"), ("", "phone", "Pixel 8", "iPhone 15"),
           ("", "computer", "ThinkPad", "MacBook"), ("Mehmet", "location", "Ankara", "İstanbul"),
           ("Mehmet", "occupation", "avukat", "hakim"), ("Elif", "location", "Bursa", "Muğla"),
           ("Elif", "employer", "Atlas", "Martı"), ("Can", "occupation", "pilot", "eğitmen")]  # fmt: skip
MARKERS = ["artık", "taşındı", "geçti", "2025'ten beri", "aslında"]


def _sentence(who: str, value: str, marker: str = "") -> str:
    subject = who or "Ben"
    return f"{subject} {marker + ' ' if marker else ''}{value} ile ilgili bilgi.".replace("  ", " ")


@pytest.mark.parametrize(("who", "predicate", "old", "new"), CHANGES)
def test_a_different_value_without_change_words_is_asked_about(
    tmp_path: Path, storage: StorageHandle, who: str, predicate: str, old: str, new: str
) -> None:
    one, two = _sentence(who, old), _sentence(who, new)
    brain = Brain(answers={
        one: ([item(one.rstrip("."), predicate, old, entity=who)], []),
        # The model says "it changed", but the words do not: it is a conflict, not an update.
        two: ([item(two.rstrip("."), predicate, new, entity=who, change=True)], []),
    })  # fmt: skip
    s = converse(tmp_path, storage, [one, two], brain)
    subject = who or "user"
    assert s.values(subject, predicate) == {old}  # not written over
    assert any(i["type"] == "conflict" for i in s.inbox)  # the user is asked


@pytest.mark.parametrize(("who", "predicate", "old", "new"), CHANGES)
@pytest.mark.parametrize("marker", MARKERS[:3])
def test_words_that_say_it_changed_update_and_keep_the_old_as_history(
    tmp_path: Path, storage: StorageHandle, who: str, predicate: str, old: str, new: str,
    marker: str,
) -> None:  # fmt: skip
    one, two = _sentence(who, old), _sentence(who, new, marker)
    brain = Brain(answers={
        one: ([item(one.rstrip("."), predicate, old, entity=who)], []),
        two: ([item(two.rstrip("."), predicate, new, entity=who, change=True)], []),
    })  # fmt: skip
    s = converse(tmp_path, storage, [one, two], brain)
    subject = who or "user"
    assert s.values(subject, predicate) == {new}
    assert s.values(subject, predicate, "superseded") == {old}
    assert not any(i["type"] == "conflict" for i in s.inbox)


PEOPLE = [("Ahmet", "Mehmet"), ("Ayşe", "Fatma"), ("Can", "Cem"), ("Elif", "Ece")]


@pytest.mark.parametrize(("wrong", "right"), PEOPLE)
@pytest.mark.parametrize("ending", ["demek istedim", "olacak", ""])
def test_who_it_was_about_is_corrected(tmp_path: Path, storage: StorageHandle, wrong: str,
                                       right: str, ending: str) -> None:  # fmt: skip
    said = f"{wrong}'in doğum günü 3 Mart."
    fix = f"Hayır, {wrong} değil {right} {ending}".strip() + "."
    brain = Brain(answers={said: ([item(said.rstrip("."), "birthday", "3 Mart", entity=wrong)],
                                  [])})  # fmt: skip
    replies: list[str] = []
    s = converse(tmp_path, storage, [said, fix], brain, replies=replies)
    assert s.values(right, "birthday") == {"3 Mart"}
    assert s.values(wrong, "birthday") == set() and not s.named(wrong)
    assert replies[-1] == "corrected"  # the reply is told what really happened


@pytest.mark.parametrize(("wrong", "right"), PEOPLE)
def test_a_correction_before_the_message_was_learned_from_waits_for_it(
    tmp_path: Path, storage: StorageHandle, wrong: str, right: str
) -> None:
    said = f"{wrong}'in doğum günü 3 Mart."
    fix = f"Hayır, {wrong} değil {right} demek istedim."
    brain = Brain(answers={said: ([item(said.rstrip("."), "birthday", "3 Mart", entity=wrong)],
                                  [])})  # fmt: skip
    s = converse(tmp_path, storage, [said, fix], brain, learn_between=False)
    assert s.values(right, "birthday") == {"3 Mart"}
    assert s.values(wrong, "birthday") == set()


def test_a_person_known_from_before_keeps_the_rest_only_the_new_fact_moves(
    tmp_path: Path, storage: StorageHandle
) -> None:
    known = "Ahmet mimar."
    said = "Ahmet'in doğum günü 3 Mart."
    fix = "Hayır, Ahmet değil Mehmet demek istedim."
    brain = Brain(answers={
        known: ([item("Ahmet mimar", "occupation", "mimar", entity="Ahmet")], []),
        said: ([item(said.rstrip("."), "birthday", "3 Mart", entity="Ahmet")], []),
    })  # fmt: skip
    s = converse(tmp_path, storage, [known, said, fix], brain)
    assert s.values("Ahmet", "occupation") == {"mimar"}  # earlier knowledge is untouched
    assert s.values("Ahmet", "birthday") == set()
    assert s.values("Mehmet", "birthday") == {"3 Mart"}


def test_a_correction_to_someone_with_namesakes_asks_which(
    tmp_path: Path, storage: StorageHandle
) -> None:
    intro = "İki Mehmet tanıyorum: biri komşum, diğeri iş arkadaşım."
    said = "Ahmet'in doğum günü 3 Mart."
    fix = "Hayır, Ahmet değil Mehmet demek istedim."
    brain = Brain(answers={
        intro: ([], [rel("biri komşum", "", "neighbor", "Mehmet"),
                     rel("diğeri iş arkadaşım", "", "colleague", "Mehmet")]),
        said: ([item(said.rstrip("."), "birthday", "3 Mart", entity="Ahmet")], []),
    })  # fmt: skip
    replies: list[str] = []
    s = converse(tmp_path, storage, [intro, said, fix], brain, replies=replies)
    assert len(s.named("Mehmet")) == 2
    assert replies[-1] == "ambiguous"  # which Mehmet?
    assert all("birthday" not in {f["predicate"] for f in s.facts if f["who"] == "Mehmet"}
               for _ in [0])  # fmt: skip
    assert s.values("Ahmet", "birthday") == {"3 Mart"}  # nothing moved by guessing


VALUES = [("location", "Ankara", "İzmir", "İzmir'de yaşıyorum.", "Ankara'da yaşıyorum."),
          ("occupation", "öğretmen", "mühendis", "", "Öğretmenim."),
          ("likes", "çay", "kahve", "", "Çay severim."),
          ("employer", "Kervan", "Pusula", "", "Kervan'da çalışıyorum.")]  # fmt: skip


@pytest.mark.parametrize(("predicate", "wrong", "right", "_", "said"), VALUES)
def test_a_value_is_corrected(tmp_path: Path, storage: StorageHandle, predicate: str,
                              wrong: str, right: str, _: str, said: str) -> None:  # fmt: skip
    fix = f"Pardon, {wrong} değil {right}."
    brain = Brain(answers={said: ([item(said.rstrip("."), predicate, wrong)], [])})
    replies: list[str] = []
    s = converse(tmp_path, storage, [said, fix], brain, replies=replies)
    assert s.values("user", predicate) == {right}
    assert replies[-1] == "corrected"


def test_a_correction_never_reaches_older_messages(tmp_path: Path, storage: StorageHandle) -> None:
    old = "Ahmet'in doğum günü 3 Mart."
    filler = ["Bugün hava güzel.", "Akşam ne yesem?"]
    fix = "Hayır, Ahmet değil Mehmet demek istedim."
    brain = Brain(answers={old: ([item(old.rstrip("."), "birthday", "3 Mart", entity="Ahmet")],
                                 [])})  # fmt: skip
    s = converse(tmp_path, storage, [old, *filler, fix], brain)
    assert s.values("Ahmet", "birthday") == {"3 Mart"}  # three messages back: not "just said"
    assert not s.named("Mehmet")


@pytest.mark.parametrize(
    ("message", "fix"),
    [
        ("Hayır, Ahmet değil Mehmet demek istedim.", ("Ahmet", "Mehmet")),
        ("Pardon, Ankara değil İzmir.", ("Ankara", "İzmir")),
        ("Yok yok, Ali değil Veli olacak.", ("Ali", "Veli")),
        ("Aslında Ahmet'in değil Mehmet'in doğum günü.", ("Ahmet", "Mehmet")),
        ("Hayır, Ali Can değil Ali Rıza.", ("Ali Can", "Ali Rıza")),
        ("Hayır, öğretmen değil mühendis.", ("öğretmen", "mühendis")),
        ("Ahmet değil Mehmet geldi.", None),
        ("Mehmet değil, bence Ali haklı.", None),
        ("Hayır.", None),
        ("Hayır, Ahmet değil Ahmet.", None),
    ],
)
def test_only_corrections_in_so_many_words_are_corrections(
    message: str, fix: tuple[str, str] | None
) -> None:
    got = corrections.parse(message)
    assert (None if got is None else (got.wrong, got.right)) == fix


def test_a_correction_to_a_name_still_being_placed_asks_which(
    tmp_path: Path, storage: StorageHandle
) -> None:
    """One Mehmet stored, another one waiting for "Hangi Mehmet?": not a guess either."""
    a, b = "Komşum Mehmet mimar.", "İş arkadaşım Mehmet avukat."
    said = "Ahmet'in doğum günü 3 Mart."
    fix = "Hayır, Ahmet değil Mehmet demek istedim."
    brain = Brain(answers={
        a: ([item("Komşum Mehmet mimar", "occupation", "mimar", entity="Mehmet",
                  relation="komşum")], []),
        b: ([item("İş arkadaşım Mehmet avukat", "occupation", "avukat", entity="Mehmet",
                  relation="iş arkadaşım")], []),
        said: ([item(said.rstrip("."), "birthday", "3 Mart", entity="Ahmet")], []),
    })  # fmt: skip
    replies: list[str] = []
    s = converse(tmp_path, storage, [a, b, said, fix], brain, replies=replies)
    assert replies[-1] == "ambiguous"
    assert s.values("Ahmet", "birthday") == {"3 Mart"}
