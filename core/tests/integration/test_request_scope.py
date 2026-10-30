"""An explicit memory request owns what it asks for (Phase 9.1): when it is not carried out —
failed, refused, nothing found, cancelled, waiting, blocked — background learning does not
write the same thing afterwards, whatever the order the two run in. The rest of the message is
learned as usual. Scripted model (it proposes whatever the text it is shown says), production
engine, encrypted database; synthetic data only."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import TurnRequest, learning
from lazis.conversation.scheduler import BackgroundJob
from lazis.memory import commands
from lazis.memory import repository as repo
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.providers.llm.ports import ChatRequest, StreamEvent
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, client_id, is_command, make_engine
from tests.conversation_support import run_turn as one_turn
from tests.integration.test_memory_commands import QWEN, answer, item, last_user
from tests.learning_support import state

_TARGET = re.compile(r"^\[(m\d+)\] «(.*)»$", re.M | re.S)

# What the scripted model reads in a text and proposes (the quote is the user's words).
FACTS = {
    "Atlas": ("Atlas şirketinde çalıştığımı", "employer", "Atlas", "Kullanıcı Atlas'ta çalışıyor."),
    "yeşil": ("en sevdiğim renk yeşil", "likes", "yeşil renk", "Kullanıcının sevdiği renk yeşil."),
    "Selin": ("köpeğimin veterineri Dr. Selin", "note", "köpeğinin veterineri Dr. Selin",
              "Kullanıcının köpeğinin veterineri Dr. Selin."),
}  # fmt: skip


def _items_for(body: str, tag: str = "m1") -> list[dict[str, Any]]:
    out = []
    for key, (quote, predicate, value, statement) in FACTS.items():
        if key in body:
            out.append({**item(predicate, value, statement, quote), "message": tag})
    return out


def sees(request: ChatRequest) -> str:
    """Background extraction: every fact the shown messages contain."""
    content = request.messages[-1].content.split("İncelenecek kullanıcı mesajları:")[-1]
    items = [i for tag, body in _TARGET.findall(content) for i in _items_for(body, tag)]
    return json.dumps({"items": items, "relations": []}, ensure_ascii=False)


def obeys(request: ChatRequest) -> str:
    """The command step carried out as asked: the facts of the request's message."""
    body = request.messages[-1].content.split("Kullanıcının son mesajı:")[-1]
    found = _TARGET.findall(body) or _TARGET.findall(request.messages[-1].content)
    return answer("remember", items=_items_for(found[-1][1] if found else ""))


def facts(storage: StorageHandle) -> list[tuple[str, str, str]]:
    return sorted((f["predicate"], f["value"], f["status"]) for f in state(storage).facts)


async def settle(engine: Any) -> None:
    for _ in range(600):
        await asyncio.sleep(0.01)
        if engine.scheduler.background is None and not engine._learn and not engine.is_busy():  # pyright: ignore[reportPrivateUsage]
            return


def talk(tmp_path: Path, storage: StorageHandle, turns: list[str], *, command: Any = obeys,
         model: str = MODEL, llm: ScriptedLLM | None = None) -> tuple[ScriptedLLM, list[str]]:  # fmt: skip
    llm = llm or ScriptedLLM(memory=sees, command=command, installed=(MODEL, QWEN),
                             loaded={MODEL, QWEN})  # fmt: skip
    engine = make_engine(storage, llm, tmp_path)
    outcomes: list[str] = []

    async def go() -> None:
        cid = None
        for t in turns:
            m = model if not t.startswith("@") else t[1 : t.index(" ")]
            text = t if not t.startswith("@") else t[t.index(" ") + 1 :]
            _, cid = await one_turn(engine, text, cid, model=m)
            outcomes.append(str((engine.last_turn or {}).get("memory_outcome") or ""))
            await settle(engine)
        for _ in range(3):
            await settle(engine)
        await engine.close()

    asyncio.run(go())
    return llm, outcomes


ATLAS = "Atlas şirketinde çalıştığımı hafızana kaydet."


# 1. A request carried out is written once (not again by learning).
def test_a_successful_request_is_written_once(tmp_path: Path, storage: StorageHandle) -> None:
    _, out = talk(tmp_path, storage, [ATLAS])
    assert out == ["saved"]
    assert facts(storage) == [("employer", "Atlas", "active")]
    assert storage.db.run_sync(repo.job_counts) == {"skipped": 1}


# 2. Failed (the model's answer is unusable): nothing written, now or later.
@pytest.mark.parametrize("broken", ["bu JSON değil", '{"action": "remember", "items": [', "{}"])
def test_a_failed_request_is_not_learned_later(
    tmp_path: Path, storage: StorageHandle, broken: str
) -> None:
    _, out = talk(tmp_path, storage, [ATLAS], command=lambda r: broken)
    assert out[0] in ("failed", "none")
    assert facts(storage) == []


# 3. Refused (the quote is not in the message): not learned later either.
def test_a_refused_request_is_not_learned_later(tmp_path: Path, storage: StorageHandle) -> None:
    refused = answer("remember", items=[item("employer", "Atlas", "x", "metinde olmayan alıntı")])
    _, out = talk(tmp_path, storage, [ATLAS], command=lambda r: refused)
    assert out == ["refused"]
    assert facts(storage) == []


# 3b. Nothing understood: the user is asked what to keep; learning does not decide for them.
def test_nothing_found_is_not_learned_later(tmp_path: Path, storage: StorageHandle) -> None:
    _, out = talk(tmp_path, storage, [ATLAS], command=lambda r: answer("remember"))
    assert out == ["nothing"]
    assert facts(storage) == []


# 4. Cancelled: the user stops the turn while the request is being read.
def test_a_request_the_user_stops_is_not_learned(tmp_path: Path, storage: StorageHandle) -> None:
    class Held(ScriptedLLM):
        hold: asyncio.Event | None = None

        async def stream(self, request: ChatRequest) -> AsyncIterator[StreamEvent]:
            if is_command(request) and self.hold is not None:
                self.requests.append(request)
                cancel = self._cancel.setdefault(request.request_id, asyncio.Event())
                await cancel.wait()
                from lazis.errors import LlmCancelledError

                raise LlmCancelledError("cancelled")
            async for ev in super().stream(request):
                yield ev

    llm = Held(memory=sees, command=obeys)
    llm.hold = asyncio.Event()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        handle = await engine.begin_turn(TurnRequest(None, client_id(), ATLAS, MODEL))
        drain = asyncio.ensure_future(_drain(engine, handle))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if llm.command_requests:
                break
        assert engine.cancel_turn(handle.user.client_id)
        await drain
        for _ in range(3):
            await settle(engine)
        await engine.close()

    asyncio.run(go())
    assert facts(storage) == []


async def _drain(engine: Any, handle: Any) -> list[dict[str, Any]]:
    return [e async for e in engine.events(handle)]


# 4b. A waiting "which one?" save called off ("Vazgeç") is never written afterwards.
def test_a_cancelled_waiting_save_is_not_written(tmp_path: Path, storage: StorageHandle) -> None:
    for name, rel in (("Ahmet", "komşum"), ("Ahmet", "iş arkadaşım")):
        storage.db.run_sync(lambda c, n=name, r=rel: _person(c, n, r))
    said = "Bunu unutma: Ahmet'in doğum günü 5 Mayıs."
    birthday = answer("remember", items=[item("birthday", "5 Mayıs", "Ahmet'in doğum günü 5 Mayıs.",
                                              "Ahmet'in doğum günü 5 Mayıs", entity="Ahmet")])  # fmt: skip
    llm = ScriptedLLM(memory=lambda r: json.dumps({"items": [{**json.loads(birthday)["items"][0]}],
                                                   "relations": []}, ensure_ascii=False),
                      command=lambda r: birthday)  # fmt: skip
    _, out = talk(tmp_path, storage, [said, "Vazgeç, kaydetme."], llm=llm)
    assert out == ["ambiguous", "cancelled"]
    assert [f for f in facts(storage) if f[0] == "birthday"] == []


def _person(c: Any, name: str, relation: str) -> None:
    from lazis.memory import service

    service.apply_candidates(
        c,
        [Candidate(predicate="note", value=f"{name} {relation}", statement=f"{name} {relation}.",
                   about="entity", entity=EntityRef(name, "person", relation))],
        source=Source("import"), explicit=True,
    )  # fmt: skip


# 5. Waiting for an answer ("which Ahmet?"): nothing is written early.
def test_a_waiting_save_is_not_written_early(tmp_path: Path, storage: StorageHandle) -> None:
    for name, rel in (("Ahmet", "komşum"), ("Ahmet", "iş arkadaşım")):
        storage.db.run_sync(lambda c, n=name, r=rel: _person(c, n, r))
    said = "Bunu unutma: Ahmet'in doğum günü 5 Mayıs."
    birthday = answer("remember", items=[item("birthday", "5 Mayıs", "Ahmet'in doğum günü 5 Mayıs.",
                                              "Ahmet'in doğum günü 5 Mayıs", entity="Ahmet")])  # fmt: skip
    llm = ScriptedLLM(memory=lambda r: json.dumps({"items": json.loads(birthday)["items"],
                                                   "relations": []}, ensure_ascii=False),
                      command=lambda r: birthday)  # fmt: skip
    _, out = talk(tmp_path, storage, [said], llm=llm)
    assert out == ["ambiguous"]
    assert [f for f in facts(storage) if f[0] == "birthday"] == []


# 6. Blocked: the fallback model may not write; when the main model is back, the waiting job
# does not write what the blocked request asked for.
def test_a_blocked_request_is_not_learned_later(tmp_path: Path, storage: StorageHandle) -> None:
    _, out = talk(tmp_path, storage, [f"@{QWEN} {ATLAS}", "Merhaba, nasılsın?"])
    assert out[0] == "untrusted_model"
    assert facts(storage) == []


# 6b. An unclear forget target deletes nothing, and the forget message teaches nothing.
def test_an_unclear_forget_teaches_nothing(tmp_path: Path, storage: StorageHandle) -> None:
    for relation in ("komşu", "iş arkadaşı"):
        storage.db.run_sync(lambda c, r=relation: repo.insert_entity(
            c, kind="person", name="Ahmet", relation=r, description=None,
            now="2026-10-20T00:00:00Z"))  # fmt: skip
    before = facts(storage)
    forget = answer("forget", forget_scope="topic", forget_entity="Ahmet", forget_predicate="note")
    _, out = talk(tmp_path, storage, ["Ahmet hakkındaki notu sil."], command=lambda r: forget)
    assert out == ["ambiguous"]
    assert facts(storage) == before


# 7. A database error while writing the request: reported, and not written later.
def test_a_database_error_is_not_learned_later(
    tmp_path: Path, storage: StorageHandle, monkeypatch: pytest.MonkeyPatch
) -> None:
    from lazis.errors import DatabaseBusyError

    real = commands.service.apply_candidates
    calls = {"n": 0}

    def once(*a: Any, **k: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 1:
            raise DatabaseBusyError("database busy")
        return real(*a, **k)

    monkeypatch.setattr(commands.service, "apply_candidates", once)
    _, out = talk(tmp_path, storage, [ATLAS])
    assert out == ["failed"]
    assert facts(storage) == []


# 8. Learning that runs before the request is settled (any order): it cannot write it either.
def test_learning_before_the_request_settles_cannot_write_it(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(memory=sees, command=lambda r: "bu JSON değil")
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        _, cid = await one_turn(engine, "Merhaba.", None)
        await settle(engine)
        # The user message and its job exist (as the turn writes them); learning reads it now.
        msg = await engine._q(lambda c: _insert_user(c, cid, ATLAS))  # pyright: ignore[reportPrivateUsage]
        await _learn_directly(engine, cid)
        assert facts(storage) == []  # nothing yet, whatever the request will do
        _ = msg
        await engine.close()

    asyncio.run(go())
    assert facts(storage) == []


def _insert_user(c: Any, cid: str, text: str) -> str:
    from lazis.conversation import repository as conv_repo
    from lazis.ids import utc_now_iso

    now = utc_now_iso()
    with conv_repo.transaction(c):
        m = conv_repo.insert_message(c, conversation_id=cid, role="user", content=text,
                                     status="complete", now=now, model=MODEL)  # fmt: skip
        repo.enqueue_job(c, user_message_id=m.id, conversation_id=cid, model=MODEL,
                         status="queued", now=now)  # fmt: skip
    return m.id


async def _learn_directly(engine: Any, cid: str) -> None:
    jobs = await engine._q(lambda c: learning.pending(c, engine._memory, cid))
    loaded = await engine._load(cid)
    prompt = learning.Prompt(engine._assemble(loaded, MODEL), loaded.window[-1].seq, ())
    job = BackgroundJob("memory", cid, "bg-test", None, 0.0)
    await engine.learner.run(job, llm=engine._get_llm(), model=MODEL, conversation_id=cid,
                             jobs=jobs, prompt=prompt)  # fmt: skip


# 9. Two things in one message: the failed request's part is not learned, the rest is.
def test_only_the_requested_part_is_held_back(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Atlas şirketinde çalıştığımı kaydet. Ayrıca en sevdiğim renk yeşil."
    _, out = talk(tmp_path, storage, [msg], command=lambda r: "bu JSON değil")
    assert out == ["failed"]
    assert facts(storage) == [("likes", "yeşil renk", "active")]


def test_a_message_without_a_request_is_learned_whole(
    tmp_path: Path, storage: StorageHandle
) -> None:
    msg = "Atlas şirketinde çalıştığımı biliyorsun. Ayrıca en sevdiğim renk yeşil."
    talk(tmp_path, storage, [msg])
    assert facts(storage) == [("employer", "Atlas", "active"), ("likes", "yeşil renk", "active")]


# 9b. "Bunu unutma." about the previous message, failed: the previous message is not learned.
def test_a_failed_bare_request_holds_back_the_previous_message(
    tmp_path: Path, storage: StorageHandle
) -> None:
    from lazis.config.model import MemorySection

    gate = asyncio.Event()
    llm = ScriptedLLM(memory=sees, command=lambda r: "bu JSON değil", memory_gate=gate)
    engine = make_engine(storage, llm, tmp_path, memory=MemorySection())

    async def go() -> None:
        _, cid = await one_turn(engine, "Köpeğimin veterineri Dr. Selin.", None)
        await asyncio.sleep(0.05)  # learning of it is held (gate)
        await one_turn(engine, "Bunu unutma.", cid)
        gate.set()
        for _ in range(3):
            await settle(engine)
        await engine.close()

    asyncio.run(go())
    assert facts(storage) == []


# 10. "Az önce kaydettin mi?" after a failed save: the database says no, and so is the reply told.
def test_did_you_save_it_is_answered_from_the_database(
    tmp_path: Path, storage: StorageHandle
) -> None:
    said = "Bunu unutma: köpeğimin veterineri Dr. Selin."
    llm, out = talk(tmp_path, storage, [said, "Az önce kaydettin mi?"],
                    command=lambda r: "bu JSON değil")  # fmt: skip
    assert out[0] == "failed" and facts(storage) == []
    note = last_user(llm.chat_requests[-1])
    assert commands.NOTICE_START in note and "hafızaya yazılmadı" in note


def test_did_you_save_it_names_what_was_saved(tmp_path: Path, storage: StorageHandle) -> None:
    said = "Bunu unutma: köpeğimin veterineri Dr. Selin."
    llm, out = talk(tmp_path, storage, [said, "Az önce kaydettin mi?"])
    assert out[0] == "saved"
    note = last_user(llm.chat_requests[-1])
    assert "Kullanıcının köpeğinin veterineri Dr. Selin." in note


def test_did_you_save_it_before_learning_ran_says_not_yet(
    tmp_path: Path, storage: StorageHandle
) -> None:
    gate = asyncio.Event()  # learning of the statement is held
    llm = ScriptedLLM(memory=sees, memory_gate=gate)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        _, cid = await one_turn(engine, "Köpeğimin veterineri Dr. Selin.", None)
        await asyncio.sleep(0.05)
        await one_turn(engine, "Az önce kaydettin mi?", cid)
        gate.set()
        for _ in range(3):
            await settle(engine)
        await engine.close()

    asyncio.run(go())
    assert "henüz hafızaya yazılmadı" in last_user(llm.chat_requests[-1])


def test_a_failed_bare_request_about_a_known_fact_is_not_a_failure(
    tmp_path: Path, storage: StorageHandle
) -> None:
    # The statement was learned first; the request's own step then failed: the memory holds it,
    # so "kaydedemedim" would be false.
    llm, out = talk(tmp_path, storage, ["Köpeğimin veterineri Dr. Selin.", "Bunu unutma."],
                    command=lambda r: "bu JSON değil")  # fmt: skip
    assert out[1] == "saved"
    assert "zaten kayıtlıydı" in last_user(llm.chat_requests[-1])
    assert facts(storage) == [("note", "köpeğinin veterineri Dr. Selin", "active")]


# Real command answers (Phase 9.1 run 1 probe, three of three alike).
A01 = ('{"action": "remember", "items": [{"message": "m1", "quote": "Atlas şirketinde çalıştığımı", '
       '"entity": "Atlas", "relation": "works_at", "predicate": "employer", "value": "Atlas", '
       '"statement": "Kullanıcı Atlas şirketinde çalışıyor.", "change": false, "replaces": "", '
       '"certain": true, "sensitive": "", "importance": 0.9}], "relations": []}')  # fmt: skip
A13 = ('{"action":"correct","items":[{"message":"m1","quote":"Atlas\'tayım","entity":"location",'
       '"relation":"lives_in","predicate":"location","value":"Atlas","statement":"Kullanıcı şu an '
       'Atlas\'ta bulunuyor.","change":true,"replaces":"Kervan","certain":true,"sensitive":"finance",'
       '"importance":1}],"relations":[], "forget_scope": "last", "forget_entity": "", '
       '"forget_relation": "", "forget_predicate": "", "forget_value": "", "forget_other": "", '
       '"forget_type": ""}')  # fmt: skip


def test_the_users_workplace_named_as_its_own_subject_is_saved(
    tmp_path: Path, storage: StorageHandle
) -> None:
    _, out = talk(tmp_path, storage, [ATLAS], command=lambda r: A01)
    assert out == ["saved"]
    assert facts(storage) == [("employer", "Atlas", "active")]


def test_a_correction_lands_in_the_field_it_corrects(
    tmp_path: Path, storage: StorageHandle
) -> None:
    from lazis.memory import service

    storage.db.run_sync(lambda c: service.apply_candidates(
        c, [Candidate(predicate="employer", value="Kervan", statement="Kullanıcı Kervan'da çalışıyor.")],
        source=Source("import"), explicit=True))  # fmt: skip
    _, out = talk(
        tmp_path, storage, ["Kervan bilgisini düzelt: Atlas'tayım."], command=lambda r: A13
    )
    assert out == ["corrected"]
    assert facts(storage) == [("employer", "Atlas", "active"), ("employer", "Kervan", "superseded")]
