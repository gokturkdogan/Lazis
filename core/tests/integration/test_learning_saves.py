"""Save safety with the Phase 9 learning (test group F): an explicit request and the same thing
said naturally obey the same rules and end in the same record; a rejected or forgotten fact is
not learned again from a later message; a failed explicit save is never reported as saved; a
cancelled "which one?" save is not written later. Scripted model, production engine, encrypted
database; synthetic data only."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lazis.memory import repository as repo
from lazis.memory import service
from lazis.memory.models import Candidate
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.integration.test_memory_commands import answer
from tests.learning_support import Brain, item, state

# (predicate, value, entity, the user's words)
FACTS = [
    ("birthday", "12 Mayıs", "Ayşe", "Ayşe'nin doğum günü 12 Mayıs"),
    ("occupation", "mimar", "Elif", "Elif mimar"),
    ("location", "İzmir", "", "İzmir'de yaşıyorum"),
    ("likes", "filtre kahve", "", "Filtre kahveyi severim"),
    ("habit", "her sabah koşmak", "", "Her sabah koşarım"),
    ("employer", "Pusula Yazılım", "", "Pusula Yazılım'da çalışıyorum"),
    ("interest", "satranç", "Can", "Can satranç oynar"),
    ("goal", "maraton koşmak", "", "Maraton koşmak istiyorum"),
    ("language", "Almanca", "", "Almanca konuşurum"),
    ("skill", "gitar", "Oya", "Oya gitar çalar"),
]


def run(tmp_path: Path, storage: StorageHandle, turns: list[str], *, brain: Brain | None = None,
        command: Any = None) -> tuple[ScriptedLLM, list[str]]:  # fmt: skip
    llm = ScriptedLLM(memory=brain or Brain(), **({"command": command} if command else {}))
    engine = make_engine(storage, llm, tmp_path)
    outcomes: list[str] = []

    async def go() -> None:
        cid = None
        for t in turns:
            _, cid = await run_turn(engine, t, cid)
            outcomes.append(str((engine.last_turn or {}).get("memory_outcome") or ""))
            for _ in range(400):
                await asyncio.sleep(0.01)
                if (
                    engine.scheduler.background is None
                    and not engine._learn
                    and not engine.is_busy()
                ):  # pyright: ignore[reportPrivateUsage]
                    break
        await engine.close()

    asyncio.run(go())
    return llm, outcomes


def record(storage: StorageHandle, predicate: str) -> list[tuple[str, str]]:
    s = state(storage)
    return sorted((f["who"], f["value"]) for f in s.facts
                  if f["predicate"] == predicate and f["status"] == "active")  # fmt: skip


@pytest.mark.parametrize(("predicate", "value", "entity", "words"), FACTS)
@pytest.mark.parametrize("path", ["explicit", "natural"])
def test_explicit_and_natural_end_in_the_same_record(
    tmp_path: Path, storage: StorageHandle, predicate: str, value: str, entity: str, words: str,
    path: str,
) -> None:  # fmt: skip
    it = item(words, predicate, value, entity=entity, statement=f"{words}.")
    if path == "explicit":
        msg = f"LAZIS, bunu unutma: {words}."
        _, outcomes = run(tmp_path, storage, [msg],
                          command=lambda r: answer("remember", items=[it]))  # fmt: skip
        assert outcomes == ["saved"]
    else:
        msg = f"{words}."
        run(tmp_path, storage, [msg], brain=Brain(answers={msg: ([it], [])}))
    assert record(storage, predicate) == [(entity or "user", value)]


@pytest.mark.parametrize(("predicate", "value", "entity", "words"), FACTS[:5])
def test_said_naturally_after_an_explicit_save_is_evidence_not_a_copy(
    tmp_path: Path, storage: StorageHandle, predicate: str, value: str, entity: str, words: str
) -> None:
    it = item(words, predicate, value, entity=entity, statement=f"{words}.")
    explicit, natural = f"LAZIS, bunu unutma: {words}.", f"{words}, demiştim."
    run(tmp_path, storage, [explicit, natural],
        brain=Brain(answers={natural: ([{**it, "quote": words}], [])}),
        command=lambda r: answer("remember", items=[it]))  # fmt: skip
    s = state(storage)
    (f,) = [f for f in s.facts if f["predicate"] == predicate]
    assert f["sources"] == 2  # the explicit request and the later message, one record


SENSITIVE = [("health", "astım", "Astımım var"), ("health", "migren", "Migrenim var"),
             ("finance", "kredi borcu", "Kredi borcum var"),
             ("health", "laktoz intoleransı", "Laktoz intoleransım var"),
             ("finance", "birikim hesabı", "Birikim hesabım var")]  # fmt: skip


@pytest.mark.parametrize(("predicate", "value", "words"), SENSITIVE)
def test_a_rejected_fact_is_not_learned_again(tmp_path: Path, storage: StorageHandle,
                                              predicate: str, value: str, words: str) -> None:  # fmt: skip
    c = Candidate(predicate=predicate, value=value, statement=f"{words}.", quote=words)
    rep = storage.db.run_sync(lambda conn: service.apply_candidates(
        conn, [c], source=Source("message", "m-first"), explicit=False))  # fmt: skip
    (iid,) = rep.inbox  # sensitive: the user decides
    storage.db.run_sync(lambda conn: service.resolve_inbox(conn, iid, "reject"))
    later = f"{words}, bunu da bil."
    run(tmp_path, storage, [later], brain=Brain(answers={later: ([item(words, predicate, value)],
                                                                 [])}))  # fmt: skip
    assert record(storage, predicate) == []  # SAVE_REJECTED stays rejected


@pytest.mark.parametrize(("predicate", "value", "entity", "words"), FACTS[:5])
def test_a_forgotten_fact_is_not_learned_again(
    tmp_path: Path, storage: StorageHandle, predicate: str, value: str, entity: str, words: str
) -> None:
    first = f"{words}."
    it = item(words, predicate, value, entity=entity)
    run(tmp_path, storage, [first], brain=Brain(answers={first: ([it], [])}))
    ids = [f["id"] for f in state(storage).facts if f["predicate"] == predicate]
    storage.db.run_sync(lambda c: service.forget_memories(c, ids))
    later = f"{words}, hatırlarsın."
    run(tmp_path, storage, [later], brain=Brain(answers={later: ([{**it, "quote": words}], [])}))
    assert record(storage, predicate) == []


@pytest.mark.parametrize(
    "broken",
    ["bu JSON değil", '{"action": "remember", "items": [', '{"action": "uçur"}', "", "{}"],
)
def test_a_failed_explicit_save_is_never_reported_as_saved(
    tmp_path: Path, storage: StorageHandle, broken: str
) -> None:
    _, outcomes = run(tmp_path, storage, ["LAZIS, bunu unutma: Ayşe'nin doğum günü 12 Mayıs."],
                      command=lambda r: broken)  # fmt: skip
    assert outcomes[0] != "saved"
    assert outcomes[0] in ("failed", "none", "nothing", "")


@pytest.mark.parametrize("cancel", ["Vazgeç.", "Vazgeç, kaydetme.", "İptal.", "Hayır, vazgeç.",
                                    "Vazgeçtim."])  # fmt: skip
def test_a_cancelled_which_one_save_is_not_written_later(
    tmp_path: Path, storage: StorageHandle, cancel: str
) -> None:
    intro = "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."
    said = "Ahmet'in doğum günü 5 Mayıs."
    brain = Brain(answers={
        intro: ([], [{"message": "m1", "quote": "biri komşum", "source": "", "source_relation": "",
                      "type": "neighbor", "target": "Ahmet", "target_relation": "",
                      "statement": "x", "negated": False, "correction": False, "change": False,
                      "status": "active", "time": "", "certain": True},
                     {"message": "m1", "quote": "diğeri iş arkadaşım", "source": "",
                      "source_relation": "", "type": "colleague", "target": "Ahmet",
                      "target_relation": "", "statement": "x", "negated": False,
                      "correction": False, "change": False, "status": "active", "time": "",
                      "certain": True}]),
        said: ([item(said.rstrip("."), "birthday", "5 Mayıs", entity="Ahmet")], []),
    })  # fmt: skip
    run(tmp_path, storage, [intro, said, cancel], brain=brain)
    assert record(storage, "birthday") == []  # SAVE_CANCELLED: never written afterwards
    open_q = storage.db.run_sync(lambda c: repo.list_inbox(c, status="open"))
    waiting = [i for i in open_q if i.type == "ambiguous_entity"
               and i.payload.get("candidate", {}).get("predicate") == "birthday"]  # fmt: skip
    assert waiting == []  # the question was called off, not left to be answered later
