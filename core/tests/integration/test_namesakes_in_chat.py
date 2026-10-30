"""Namesakes end to end (Phase 7.2): the production engine, a scripted model, and the database
state after every step — never only the reply. A fact about an ambiguous name is written to
nobody until the user says which one; then to exactly that one."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from lazis.memory import commands, text
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, make_engine, run_turn
from tests.integration.test_graph_chat import rel
from tests.integration.test_memory_commands import answer, item

TWO = "İki Ahmet tanıyorum: biri komşum, diğeri iş arkadaşım."
TWO_RELS = [
    rel("biri komşum", "", "neighbor", "Ahmet"),
    rel("diğeri iş arkadaşım", "", "colleague", "Ahmet"),
]
BIRTHDAY = answer("remember", items=[item("birthday", "5 Mayıs", "Ahmet'in doğum günü 5 Mayıs.",
                                          "Ahmet'in doğum günü 5 Mayıs", entity="Ahmet")])  # fmt: skip


def extraction(by_text: Mapping[str, tuple[list[dict[str, Any]], list[dict[str, Any]]]]) -> Callable[[ChatRequest], str]:  # fmt: skip
    """The background extraction answer for the first message text found in the request."""

    def reply(r: ChatRequest) -> str:
        prompt = r.messages[-1].content
        for key, (items, rels) in by_text.items():
            if key in prompt:
                return json.dumps({"items": items, "relations": rels}, ensure_ascii=False)
        return '{"items": [], "relations": []}'

    return reply


def commanded(by_text: Mapping[str, str]) -> Callable[[ChatRequest], str]:
    def reply(r: ChatRequest) -> str:
        prompt = r.messages[-1].content
        for key, out in by_text.items():
            if key in prompt:
                return out
        return answer("none")

    return reply


async def converse(engine: Any, *texts: str) -> tuple[list[list[dict[str, Any]]], str]:
    out: list[list[dict[str, Any]]] = []
    cid: str | None = None
    for t in texts:
        events, cid = await run_turn(engine, t, cid)
        out.append(events)
        for _ in range(400):  # background learning settles before the next message
            await asyncio.sleep(0.01)
            if engine.scheduler.background is None and not engine._learn and not engine.is_busy():
                break
    assert cid is not None
    return out, cid


def chat(storage: StorageHandle, tmp_path: Path, *texts: str,
         memory: Callable[[ChatRequest], str] | None = None,
         command: Callable[[ChatRequest], str] | None = None) -> tuple[ScriptedLLM, list[list[dict[str, Any]]]]:  # fmt: skip
    llm = ScriptedLLM(
        **({"memory": memory} if memory else {}), **({"command": command} if command else {})
    )
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[list[dict[str, Any]]]:
        events, _ = await converse(engine, *texts)
        await engine.close()
        return events

    return llm, asyncio.run(go())


def people(storage: StorageHandle, name: str = "Ahmet") -> list[tuple[str, str | None, str | None]]:
    def read(c: Any) -> list[tuple[str, str | None, str | None]]:
        return [
            (e.id, e.relation, e.description) for e in repo.find_entities(c, text.name_key(name))
        ]

    return storage.db.run_sync(read)


def facts_of(storage: StorageHandle, entity_id: str) -> list[tuple[str, str]]:
    return storage.db.run_sync(
        lambda c: [(m.predicate, m.value) for m in repo.memories_for_subject(c, entity_id)]
    )


def label_of(storage: StorageHandle, relation: str, name: str = "Ahmet") -> str:
    return next(i for i, r, _ in people(storage, name) if r == relation)


def open_questions(storage: StorageHandle) -> int:
    return len(
        storage.db.run_sync(
            lambda c: repo.list_inbox(c, status="open", types=("ambiguous_entity",))
        )
    )


def outcome_notice(llm: ScriptedLLM, n: int) -> str:
    return llm.chat_requests[n].messages[-1].content


# ----- one message, several people ------------------------------------------------------------
def test_two_namesakes_in_one_message_are_two_people(
    tmp_path: Path, storage: StorageHandle
) -> None:
    chat(storage, tmp_path, TWO, memory=extraction({TWO: ([], TWO_RELS)}))
    found = people(storage)
    assert sorted(r or "" for _, r, _ in found) == ["iş arkadaşı", "komşusu"]
    a, b = (i for i, _, _ in found)
    assert storage.db.run_sync(lambda c: gs.are_distinct(c, a, b))
    assert open_questions(storage) == 0


def test_the_one_the_model_left_out_is_still_created(
    tmp_path: Path, storage: StorageHandle
) -> None:
    chat(storage, tmp_path, TWO, memory=extraction({TWO: ([], TWO_RELS[:1])}))
    assert sorted(r or "" for _, r, _ in people(storage)) == ["iş arkadaşı", "komşusu"]


def test_the_users_words_suffice_when_the_model_returns_nothing(
    tmp_path: Path, storage: StorageHandle
) -> None:
    chat(storage, tmp_path, TWO)
    assert len(people(storage)) == 2


def test_three_namesakes(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Üç Ayşe var hayatımda: kuzenim, komşum ve iş arkadaşım."
    rels = [rel("kuzenim", "", "cousin", "Ayşe"), rel("komşum", "", "neighbor", "Ayşe"),
            rel("iş arkadaşım", "", "colleague", "Ayşe")]  # fmt: skip
    chat(storage, tmp_path, msg, memory=extraction({msg: ([], rels)}))
    assert sorted(r or "" for _, r, _ in people(storage, "Ayşe")) == [
        "iş arkadaşı",
        "komşusu",
        "kuzeni",
    ]


def test_occupations_tell_them_apart(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "İki Mehmet tanıyorum, biri öğretmen, diğeri mühendis."
    items = [item("occupation", "öğretmen", "Bir Mehmet öğretmen.", "biri öğretmen", entity="Mehmet"),
             item("occupation", "mühendis", "Diğer Mehmet mühendis.", "diğeri mühendis", entity="Mehmet")]  # fmt: skip
    chat(storage, tmp_path, msg, memory=extraction({msg: (items, [])}))
    found = people(storage, "Mehmet")
    assert len(found) == 2
    assert sorted(v for i, _, _ in found for _, v in facts_of(storage, i)) == [
        "mühendis",
        "öğretmen",
    ]
    assert all(len(facts_of(storage, i)) == 1 for i, _, _ in found)  # one job each, no conflict


def test_one_person_with_two_roles_stays_one(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Ahmet hem komşum hem iş arkadaşım."
    rels = [rel(msg, "", "neighbor", "Ahmet"), rel(msg, "", "colleague", "Ahmet")]
    chat(storage, tmp_path, msg, memory=extraction({msg: ([], rels)}))
    found = people(storage)
    assert len(found) == 1 and open_questions(storage) == 0
    types = storage.db.run_sync(
        lambda c: sorted(r.type for r in gs.relationships_of(c, found[0][0]))
    )
    assert types == ["colleague", "neighbor"]


def test_different_names_are_not_namesakes(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Ahmet ve Mehmet benim iş arkadaşlarım."
    rels = [rel(msg, "", "colleague", "Ahmet"), rel(msg, "", "colleague", "Mehmet")]
    chat(storage, tmp_path, msg, memory=extraction({msg: ([], rels)}))
    assert len(people(storage)) == 1 and len(people(storage, "Mehmet")) == 1


def test_a_stored_neighbour_is_reused_not_duplicated(
    tmp_path: Path, storage: StorageHandle
) -> None:
    first = "Komşum Ahmet çok yardımsever."
    chat(storage, tmp_path, first, TWO, memory=extraction({
        first: ([], [rel("Komşum Ahmet", "", "neighbor", "Ahmet")]), TWO: ([], TWO_RELS)}))  # fmt: skip
    assert sorted(r or "" for _, r, _ in people(storage)) == ["iş arkadaşı", "komşusu"]


# ----- an explicit save while the name is ambiguous ---------------------------------------------
def test_an_ambiguous_save_writes_nothing_and_asks(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.",
                  memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))
    notice = outcome_notice(llm, 1)
    assert "hangisinin kastedildiği belirsiz" in notice
    assert "Ahmet (komşusu)" in notice and "Ahmet (iş arkadaşı)" in notice
    assert open_questions(storage) == 1


@pytest.mark.parametrize(
    ("reply", "meant"),
    [("Komşum olan.", "komşusu"), ("Komşum.", "komşusu"), ("İş arkadaşım olan Ahmet.", "iş arkadaşı"),
     ("iş arkadaşım", "iş arkadaşı"), ("Komşum olanı kastettim.", "komşusu")],
)  # fmt: skip
def test_the_answer_saves_to_that_one(
    tmp_path: Path, storage: StorageHandle, reply: str, meant: str
) -> None:
    llm, _ = chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.", reply,
                  memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    right = label_of(storage, meant)
    other = next(i for i, _, _ in people(storage) if i != right)
    assert facts_of(storage, right) == [("birthday", "5 Mayıs")]
    assert facts_of(storage, other) == []
    assert open_questions(storage) == 0
    assert "Kaydedildi" in outcome_notice(llm, 2)
    assert llm.command_requests[-1] is llm.command_requests[0]  # the answer needed no model call


def test_cancelling_writes_nothing(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.", "Vazgeç.",
                  memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))
    assert open_questions(storage) == 0 and "iptal edildi" in outcome_notice(llm, 2)


def test_a_wrong_pick_is_moved(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.", "Komşum olan.",
                  "Hayır, iş arkadaşım olan.",
                  memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    assert facts_of(storage, label_of(storage, "iş arkadaşı")) == [("birthday", "5 Mayıs")]
    assert facts_of(storage, label_of(storage, "komşusu")) == []
    assert "kaldırıldı" in outcome_notice(llm, 3)


def test_a_new_statement_is_not_taken_for_an_answer(tmp_path: Path, storage: StorageHandle) -> None:
    chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.",
         "Komşum Ahmet yarın bize akşam yemeğine gelecek.",
         memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    assert all(("birthday", "5 Mayıs") not in facts_of(storage, i) for i, _, _ in people(storage))
    assert open_questions(storage) == 1


def test_an_old_question_is_not_answered_in_chat(
    tmp_path: Path, storage: StorageHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(commands, "QUESTION_MAX_AGE_S", -1)
    chat(storage, tmp_path, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.", "Komşum olan.",
         memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY}))  # fmt: skip
    assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))
    assert open_questions(storage) == 1  # still in the memory screen


def test_after_a_restart_nothing_is_guessed_and_the_answer_still_works(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory = extraction({TWO: ([], TWO_RELS)})
    command = commanded({"5 Mayıs": BIRTHDAY})
    llm = ScriptedLLM(memory=memory, command=command)

    async def go() -> None:
        engine = make_engine(storage, llm, tmp_path)
        _, cid = await converse(engine, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.")
        await engine.close()  # what quitting the app does
        assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))
        engine = make_engine(storage, llm, tmp_path)
        await engine.ensure_started()
        await run_turn(engine, "Komşum olan.", cid)
        await engine.close()

    asyncio.run(go())
    assert facts_of(storage, label_of(storage, "komşusu")) == [("birthday", "5 Mayıs")]
    assert facts_of(storage, label_of(storage, "iş arkadaşı")) == []


def test_an_answer_in_another_conversation_is_not_used(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(
        memory=extraction({TWO: ([], TWO_RELS)}), command=commanded({"5 Mayıs": BIRTHDAY})
    )

    async def go() -> None:
        engine = make_engine(storage, llm, tmp_path)
        await converse(engine, TWO, "Ahmet'in doğum günü 5 Mayıs, bunu unutma.")
        session = await engine.start_new_session(MODEL)
        await run_turn(engine, "Komşum olan.", session.id)
        await engine.close()

    asyncio.run(go())
    assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))


def test_three_options_and_an_answer(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Üç Ayşe var hayatımda: kuzenim, komşum ve iş arkadaşım."
    save = answer("remember", items=[item("birthday", "1 Ocak", "Ayşe'nin doğum günü 1 Ocak.",
                                          "Ayşe'nin doğum günü 1 Ocak", entity="Ayşe")])  # fmt: skip
    llm, _ = chat(storage, tmp_path, msg, "Bunu unutma: Ayşe'nin doğum günü 1 Ocak.", "Kuzenim olan.",
                  command=commanded({"1 Ocak": save}))  # fmt: skip
    assert "Ayşe (kuzeni)" in outcome_notice(llm, 1) and "Ayşe (komşusu)" in outcome_notice(llm, 1)
    assert facts_of(storage, label_of(storage, "kuzeni", "Ayşe")) == [("birthday", "1 Ocak")]
    assert sum(len(facts_of(storage, i)) for i, _, _ in people(storage, "Ayşe")) == 1


def test_an_answer_by_occupation(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "İki Mehmet tanıyorum, biri öğretmen, diğeri mühendis."
    items = [item("occupation", "öğretmen", "Bir Mehmet öğretmen.", "biri öğretmen", entity="Mehmet"),
             item("occupation", "mühendis", "Diğer Mehmet mühendis.", "diğeri mühendis", entity="Mehmet")]  # fmt: skip
    save = answer("remember", items=[item("birthday", "3 Nisan", "Mehmet'in doğum günü 3 Nisan.",
                                          "Mehmet'in doğum günü 3 Nisan", entity="Mehmet")])  # fmt: skip
    chat(storage, tmp_path, msg, "Bunu unutma: Mehmet'in doğum günü 3 Nisan.", "Mühendis olan Mehmet.",
         memory=extraction({msg: (items, [])}), command=commanded({"3 Nisan": save}))  # fmt: skip
    eng = next(
        i
        for i, _, _ in people(storage, "Mehmet")
        if ("occupation", "mühendis") in facts_of(storage, i)
    )
    assert ("birthday", "3 Nisan") in facts_of(storage, eng)
    assert (
        sum(
            ("birthday", "3 Nisan") in facts_of(storage, i) for i, _, _ in people(storage, "Mehmet")
        )
        == 1
    )


def test_one_known_murat_is_saved_directly(tmp_path: Path, storage: StorageHandle) -> None:
    save = answer("remember", items=[item("birthday", "12 Haziran", "Murat'ın doğum günü 12 Haziran.",
                                          "Murat'ın doğum günü 12 Haziran", entity="Murat")])  # fmt: skip
    llm, _ = chat(storage, tmp_path, "Lütfen şunu not al: Murat'ın doğum günü 12 Haziran.",
                  command=commanded({"12 Haziran": save}))  # fmt: skip
    ((mid, _, _),) = people(storage, "Murat")
    assert facts_of(storage, mid) == [("birthday", "12 Haziran")]
    assert "Kaydedildi" in outcome_notice(llm, 0)


def test_a_statement_about_one_of_two_is_held_not_guessed(
    tmp_path: Path, storage: StorageHandle
) -> None:
    later = "Ahmet'in kızı geçen hafta doğdu."
    born = item("event", "kızı doğdu", "Ahmet'in kızı geçen hafta doğdu.", "Ahmet'in kızı geçen hafta doğdu",
                entity="Ahmet")  # fmt: skip
    chat(
        storage, tmp_path, TWO, later, memory=extraction({TWO: ([], TWO_RELS), later: ([born], [])})
    )
    assert all(facts_of(storage, i) == [] for i, _, _ in people(storage))
    assert open_questions(storage) == 1


def test_namesakes_the_user_told_apart_are_never_merged(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm, _ = chat(
        storage, tmp_path, TWO, "Bu iki Ahmet aynı kişi.", memory=extraction({TWO: ([], TWO_RELS)})
    )
    assert len(people(storage)) == 2
    assert "farklı kişiler olarak işaretlendi" in outcome_notice(llm, 1)


# ----- what is said of each namesake (Phase 9.1) -----------------------------------------------
JOBS = "İki Ahmet tanıyorum. Biri komşum, mimar. Diğeri iş arkadaşım, muhasebeci."
_GIVEN = {"right": ("komşu", "iş arkadaşı"), "none": ("", ""), "wrong": ("iş arkadaşı", "komşu")}


@pytest.mark.parametrize("field", ["occupation", "note", "family"])
@pytest.mark.parametrize(
    ("relations", "quotes"),
    [("right", "own"), ("none", "own"), ("wrong", "own"), ("wrong", "whole")],
)
def test_each_namesakes_job_goes_to_the_one_named_or_to_none(
    tmp_path: Path, storage: StorageHandle, field: str, relations: str, quotes: str
) -> None:
    # Phase 8 bootstrap n02: "mimar" was read as the second person and both jobs went to one
    # Ahmet. Whatever field or relation words the model gives, a job is written to the Ahmet
    # the user's words name, or to nobody.
    first, second = _GIVEN[relations]
    q1, q2 = (
        ("Biri komşum, mimar", "Diğeri iş arkadaşım, muhasebeci")
        if quotes == "own"
        else (JOBS, JOBS)
    )
    items = [item(field, "mimar", "Ahmet mimar.", q1, entity="Ahmet", relation=first),
             item(field, "muhasebeci", "Ahmet muhasebeci.", q2, entity="Ahmet", relation=second)]  # fmt: skip
    chat(storage, tmp_path, JOBS, memory=extraction({JOBS: (items, TWO_RELS)}))
    found = people(storage)
    assert sorted(r or "" for _, r, _ in found) == ["iş arkadaşı", "komşusu"]  # two, not three
    jobs = {r: sorted(v for _, v in facts_of(storage, i)) for i, r, _ in found}
    assert set(jobs["komşusu"]) <= {"mimar"} and set(jobs["iş arkadaşı"]) <= {"muhasebeci"}
    if (relations, quotes) != ("wrong", "whole"):  # the quote names the slot
        assert jobs == {"komşusu": ["mimar"], "iş arkadaşı": ["muhasebeci"]}
    else:  # only the model's relation words and the value, disagreeing
        assert jobs == {"komşusu": [], "iş arkadaşı": []}
        assert open_questions(storage) == 2  # "which Ahmet?" for each, nothing guessed


@pytest.mark.parametrize(
    ("msg", "name", "said", "field"),
    [
        ("Üç Ayşe var. Biri kuzenim, doktor. Biri komşum, öğretmen. Diğeri iş arkadaşım, avukat.",
         "Ayşe", [("Biri kuzenim, doktor", "doktor", "kuzeni"),
                  ("Biri komşum, öğretmen", "öğretmen", "komşusu"),
                  ("Diğeri iş arkadaşım, avukat", "avukat", "iş arkadaşı")], "occupation"),
        ("İki Ahmet var. Biri komşum, İzmir'de yaşıyor. Diğeri iş arkadaşım, Ankara'da yaşıyor.",
         "Ahmet", [("Biri komşum, İzmir'de yaşıyor", "İzmir", "komşusu"),
                   ("Diğeri iş arkadaşım, Ankara'da yaşıyor", "Ankara", "iş arkadaşı")], "location"),
    ],
)  # fmt: skip
def test_three_namesakes_and_cities_each_to_their_own(
    tmp_path: Path, storage: StorageHandle, msg: str, name: str,
    said: list[tuple[str, str, str]], field: str,
) -> None:  # fmt: skip
    items = [item(field, v, f"{name} {v}.", q, entity=name) for q, v, _ in said]
    chat(storage, tmp_path, msg, memory=extraction({msg: (items, [])}))
    found = people(storage, name)
    assert len(found) == len(said)
    got = {r: [v for _, v in facts_of(storage, i)] for i, r, _ in found}
    assert got == {label: [v] for _, v, label in said}
