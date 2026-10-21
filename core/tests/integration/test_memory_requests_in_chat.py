"""Explicit memory requests end to end (Phase 7.2): every supported phrasing really writes,
before the reply; other uses of "not" and "kaydet" write nothing."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lazis.memory import commands
from lazis.memory import repository as memory_repo
from lazis.storage import StorageHandle
from tests.integration.test_memory_commands import answer, item, last_user, run, saved

VEGETARIAN = answer("remember", items=[item("note", "vejetaryen", "Selin vejetaryen.",
                                            "Selin vejetaryen", entity="Selin")])  # fmt: skip

WITH_CONTENT = [
    "Şunu hafızana kaydet: Selin vejetaryen.", "Lütfen şunu not al: Selin vejetaryen.",
    "Şunu kaydet: Selin vejetaryen.", "Bu bilgiyi unutmanı istemiyorum: Selin vejetaryen.",
    "Bunu ileride hatırlamanı istiyorum: Selin vejetaryen.", "Not düş: Selin vejetaryen.",
    "Şunu bilmeni istiyorum, unutma: Selin vejetaryen.", "Not alır mısın: Selin vejetaryen.",
    "Aklında olsun, Selin vejetaryen.", "Kaydeder misin, Selin vejetaryen.",
]  # fmt: skip
BARE = ["Bunu unutma.", "Bunu not et.", "Aklında tut.", "Bunu hatırla.", "Bunu kaydet lütfen."]


@pytest.mark.parametrize("message", WITH_CONTENT)
def test_each_phrasing_saves(tmp_path: Path, storage: StorageHandle, message: str) -> None:
    llm, _ = run(storage, tmp_path, lambda r: VEGETARIAN, message)
    assert saved(storage) == ["Selin vejetaryen."]
    assert commands.REMEMBER_NOTE in llm.command_requests[0].messages[-1].content
    assert "Kaydedildi" in last_user(llm.chat_requests[0])


@pytest.mark.parametrize("message", BARE)
def test_a_bare_request_saves_the_previous_message(
    tmp_path: Path, storage: StorageHandle, message: str
) -> None:
    llm, _ = run(storage, tmp_path, lambda r: VEGETARIAN, "Selin vejetaryen.", message)
    assert saved(storage) == ["Selin vejetaryen."]
    instruction = llm.command_requests[0].messages[-1].content
    assert commands.REMEMBER_PREVIOUS_NOTE in instruction and "«Selin vejetaryen.»" in instruction
    jobs = storage.db.run_sync(lambda c: memory_repo.job_counts(c))
    assert jobs.get("skipped", 0) >= 1  # the previous message is not learned twice


@pytest.mark.parametrize(
    "message",
    ["Bana kısa bir toplantı notu hazırla.", "Not almak için hangi uygulamayı önerirsin?",
     "“Bunu not al” ifadesini İngilizceye çevir.", "Dosyayı kaydettim ama açılmıyor."],
)  # fmt: skip
def test_other_uses_never_reach_the_request_stage(
    tmp_path: Path, storage: StorageHandle, message: str
) -> None:
    llm, _ = run(storage, tmp_path, lambda r: VEGETARIAN, message)
    assert llm.command_requests == [] and saved(storage) == []


def test_the_model_can_say_it_is_not_a_request(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Kaydet butonuna bastım ama olmadı.")
    assert len(llm.command_requests) == 1 and saved(storage) == []
    note = last_user(llm.chat_requests[0])
    assert "Kaydedildi" not in note and "henüz hafızaya yazılmadı" in note  # an ordinary statement


def test_a_wrong_predicate_is_kept_as_a_note(tmp_path: Path, storage: StorageHandle) -> None:
    # Phase 7.1 real output: "Burak'ın düğünü haziranda" as predicate "device" — nothing was saved.
    cmd = answer("remember", items=[item("device", "haziran", "Burak'ın düğünü haziranda.",
                                         "Burak'ın düğünü haziranda", entity="Burak")])  # fmt: skip
    llm, _ = run(storage, tmp_path, lambda r: cmd, "Lütfen şunu not al: Burak'ın düğünü haziranda.")
    assert saved(storage) == ["Burak'ın düğünü haziranda."]
    assert "Kaydedildi" in last_user(llm.chat_requests[0])


def test_a_thing_is_not_written_as_the_users_birthday(
    tmp_path: Path, storage: StorageHandle
) -> None:
    cmd = answer("remember", items=[item("birthday", "mart", "Arabanın sigortası mart ayında bitiyor.",
                                         "arabanın sigortası mart ayında bitiyor", entity="araba sigortası")])  # fmt: skip
    run(storage, tmp_path, lambda r: cmd, "Bunu not et: arabanın sigortası mart ayında bitiyor.")
    mems = storage.db.run_sync(lambda c: memory_repo.list_memories(c))
    assert [(m.predicate, m.subject_id) for m in mems] == [("note", None)]


def test_a_sensitive_fact_asked_for_is_saved(tmp_path: Path, storage: StorageHandle) -> None:
    cmd = answer("remember", items=[item("health", "astım", "Kullanıcının astımı var.", "astım hastasıyım",
                                         sensitive="health")])  # fmt: skip
    run(storage, tmp_path, lambda r: cmd, "Bunu unutma: astım hastasıyım.")
    assert saved(storage) == ["Kullanıcının astımı var."]


def test_a_secret_is_never_saved_and_needs_no_model(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(storage, tmp_path, lambda r: VEGETARIAN, "Not al: banka şifrem 4471.")
    assert llm.command_requests == [] and saved(storage) == []
    assert "kaydedilmedi ve kaydedilmeyecek" in last_user(llm.chat_requests[0])


def test_a_broken_answer_is_reported_in_plain_words(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(storage, tmp_path, lambda r: "{bozuk", "Lütfen şunu not al: Selin vejetaryen.")
    assert saved(storage) == []
    assert "Bunu şu anda kaydedemedim efendim" in last_user(llm.chat_requests[0])


def test_nothing_to_save_asks_what_to_keep(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(storage, tmp_path, lambda r: answer("remember"), "Lütfen şunu not al.")
    assert saved(storage) == []
    assert "neyi kaydetmemi istediğini sorabilirsin" in last_user(llm.chat_requests[0])


def test_the_untrusted_model_writes_nothing(tmp_path: Path, storage: StorageHandle) -> None:
    from tests.integration.test_memory_commands import QWEN

    llm, _ = run(
        storage, tmp_path, lambda r: VEGETARIAN, "Lütfen şunu not al: Selin vejetaryen.", model=QWEN
    )
    assert saved(storage) == [] and llm.command_requests == []


def test_a_fact_learned_in_the_background_is_reported_as_kept(
    tmp_path: Path, storage: StorageHandle
) -> None:
    import json

    from tests.conversation_support import ScriptedLLM, make_engine
    from tests.integration.test_namesakes_in_chat import converse

    learned = json.dumps({"items": [item("birthday", "12 Mart", "Elif'in doğum günü 12 Mart.",
                                         "Elif'in doğum günü 12 Mart", entity="Elif")], "relations": []},
                         ensure_ascii=False)  # fmt: skip
    llm = ScriptedLLM(memory=lambda r: learned, command=lambda r: answer("remember"))
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        await converse(engine, "Elif'in doğum günü 12 Mart.", "Bunu unutma.")
        await engine.close()

    asyncio.run(go())
    assert saved(storage) == ["Elif'in doğum günü 12 Mart."]
    note = last_user(llm.chat_requests[1])
    assert "Kaydedildi" in note and "zaten kayıtlıydı" in note  # not "kaydedemedim"


def test_a_fact_stored_before_is_reported_as_kept(tmp_path: Path, storage: StorageHandle) -> None:
    from lazis.memory import service
    from lazis.memory.models import Candidate, EntityRef

    c = Candidate(predicate="birthday", value="12 Mart", statement="Elif'in doğum günü 12 Mart.",
                  about="entity", entity=EntityRef("Elif"))  # fmt: skip
    storage.db.run_sync(
        lambda conn: service.apply_candidates(
            conn, [c], source=service.Source("import"), explicit=True
        )
    )
    llm, _ = run(
        storage, tmp_path, lambda r: answer("remember"), "Bunu unutma: Elif'in doğum günü 12 Mart."
    )
    assert "zaten kayıtlıydı" in last_user(llm.chat_requests[0])
