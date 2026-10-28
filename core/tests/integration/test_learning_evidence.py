"""Repetition as evidence (Phase 9, test group C): the same thing said again in other messages
is one record with more sources and a little more confidence (never certainty); the same
message read again is not a second confirmation; repeating a value never makes a different
one go away silently, and a correction beats any number of repetitions. Encrypted database,
synthetic data only."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from lazis.memory import repository as repo
from lazis.memory import service
from lazis.memory.models import ApplyReport, Candidate
from lazis.memory.service import REPEAT_CAP, REPEAT_STEP, Source
from lazis.storage import StorageHandle
from tests.learning_support import Brain, converse, item

FACTS = [("likes", "filtre kahve"), ("habit", "her sabah koşmak"), ("interest", "satranç"),
         ("work_preference", "sabah çalışmak"), ("location", "İzmir"), ("occupation", "mimar"),
         ("dislikes", "sıcak"), ("language", "Almanca"), ("skill", "gitar"),
         ("technology", "Rust")]  # fmt: skip


def say(storage: StorageHandle, predicate: str, value: str, message: str, *,
        change: bool = False, explicit: bool = False) -> ApplyReport:  # fmt: skip
    c = Candidate(predicate=predicate, value=value, statement=f"Kullanıcı — {value}.",
                  change=change, quote=value)  # fmt: skip
    return storage.db.run_sync(lambda conn: service.apply_candidates(
        conn, [c], source=Source("message", message), explicit=explicit))  # fmt: skip


def records(storage: StorageHandle, predicate: str) -> list[object]:
    return storage.db.run_sync(lambda c: [
        m for m in repo.list_memories(c, status=None, limit=1000) if m.predicate == predicate])  # fmt: skip


@pytest.mark.parametrize(("fact", "times"), list(itertools.product(FACTS, (2, 3, 5))))
def test_said_again_in_other_messages_is_one_record_with_more_sources(
    storage: StorageHandle, fact: tuple[str, str], times: int
) -> None:
    predicate, value = fact
    first = say(storage, predicate, value, "msg-1")
    base = storage.db.run_sync(lambda c: repo.get_memory(c, first.created[0])).confidence  # type: ignore[union-attr]
    for i in range(2, times + 1):
        r = say(storage, predicate, value, f"msg-{i}")
        assert r.created == [] and r.updated == first.created
    (m,) = records(storage, predicate)
    sources = storage.db.run_sync(lambda c: repo.independent_sources(c, first.created[0]))
    assert sources == times
    expected = min(REPEAT_CAP, round(base + REPEAT_STEP * (times - 1), 3))
    assert m.confidence == pytest.approx(expected)  # type: ignore[attr-defined]
    assert m.confidence < 1.0  # type: ignore[attr-defined]


@pytest.mark.parametrize("fact", FACTS)
def test_the_same_message_read_again_is_not_new_evidence(
    storage: StorageHandle, fact: tuple[str, str]
) -> None:
    predicate, value = fact
    first = say(storage, predicate, value, "msg-1")
    again = say(storage, predicate, value, "msg-1")  # a retried job, the same message
    assert again.created == [] and again.updated == [] and again.dropped == {"same_source": 1}
    assert storage.db.run_sync(lambda c: repo.independent_sources(c, first.created[0])) == 1


SINGLE = [("location", "İzmir", "Ankara"), ("occupation", "mimar", "avukat"),
          ("employer", "Kervan", "Pusula"), ("phone", "Pixel 8", "iPhone 15"),
          ("computer", "ThinkPad", "MacBook")]  # fmt: skip


@pytest.mark.parametrize(("predicate", "kept", "other"), SINGLE)
def test_repetition_never_silences_a_different_value(
    storage: StorageHandle, predicate: str, kept: str, other: str
) -> None:
    for i in range(4):
        say(storage, predicate, kept, f"msg-{i}")
    for i in range(4, 7):  # the other value said three times, with no word that it changed
        r = say(storage, predicate, other, f"msg-{i}")
        assert r.created == [] and len(r.inbox) == 1  # asked about, every time
    values = {m.value: m.status for m in records(storage, predicate)}  # type: ignore[attr-defined]
    assert values == {kept: "active"}


@pytest.mark.parametrize(("predicate", "kept", "other"), SINGLE)
def test_a_correction_beats_any_number_of_repetitions(
    storage: StorageHandle, predicate: str, kept: str, other: str
) -> None:
    for i in range(5):
        say(storage, predicate, kept, f"msg-{i}")
    r = say(storage, predicate, other, "msg-fix", change=True)  # "artık …"
    assert len(r.created) == 1 and len(r.superseded) == 1
    values = {m.value: m.status for m in records(storage, predicate)}  # type: ignore[attr-defined]
    assert values == {kept: "superseded", other: "active"}


def test_an_import_and_a_chat_message_are_independent_sources(storage: StorageHandle) -> None:
    c = Candidate(predicate="likes", value="filtre kahve", statement="Kullanıcı kahve sever.")
    first = storage.db.run_sync(lambda conn: service.apply_candidates(
        conn, [c], source=Source("import", "item-1"), explicit=True))  # fmt: skip
    say(storage, "likes", "filtre kahve", "msg-1")
    assert storage.db.run_sync(lambda conn: repo.independent_sources(conn, first.created[0])) == 2


def test_restated_in_other_words_reuses_the_stored_value_end_to_end(
    tmp_path: Path, storage: StorageHandle
) -> None:
    """The model sees the stored preference (a shared word) and writes the stored value; the
    second message becomes evidence, not a second record."""
    one, two = "Ben sabah çalışmayı seviyorum.", "En verimli olduğum saatler sabah."
    brain = Brain(answers={one: ([item(one.rstrip("."), "work_preference", "sabah çalışmak")], []),
                           two: ([item(two.rstrip("."), "work_preference", "sabah çalışmak")],
                                 [])})  # fmt: skip
    s = converse(tmp_path, storage, [one, two], brain)
    (f,) = [f for f in s.facts if f["predicate"] == "work_preference"]
    assert f["sources"] == 2
