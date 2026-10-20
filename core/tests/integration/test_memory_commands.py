"""Explicit memory requests in chat: carried out before the reply, which gets a notice of
what really happened. Remember, refuse secrets, forget a topic, confirm before forgetting a
person, untrusted models, not-a-request, failures. Scripted model, synthetic data only."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import ConversationEngine
from lazis.memory import commands, retrieval, service
from lazis.memory import repository as memory_repo
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, make_engine, run_turn

QWEN = "qwen3.5:9b-q4_K_M"


@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Bunu unutma: yarın saat 10'da dişçi randevum var.", "remember"),
        ("Bunu hafızana kaydet lütfen.", "remember"),
        ("Aklında tut, kızımın okulu 8:30'da başlıyor.", "remember"),
        ("Ahmet'in mesleğini unut.", "forget"),
        ("Bunu hafızandan sil.", "forget"),
        ("Yanlış hatırlıyorsun, 48 GB RAM var.", "correct"),
        ("Hakkımda ne biliyorsun?", "recall"),
        ("Benim hakkımda neler hatırlıyorsun?", "recall"),
        ("Şifremi unuttum, ne yapmalıyım?", None),  # not a request to LAZIS
        ("Hiçbir şeyi unutmadım.", None),
        ("Günaydın!", None),
    ],
)
def test_cue_detection(message: str, intent: str | None) -> None:
    assert commands.detect(message) == intent


def test_confirmation_cues_only_while_a_confirmation_is_pending() -> None:
    assert commands.detect("Evet, sil.", pending_confirmation=True) == "confirm"
    assert commands.detect("Hayır, vazgeçtim.", pending_confirmation=True) == "decline"
    assert commands.detect("Evet, sil.") == "forget"  # liberal cue; the model decides


def answer(action: str, **kw: Any) -> str:
    base: dict[str, Any] = {"action": action, "items": [], "forget_scope": "", "forget_entity": "",
                            "forget_relation": "", "forget_predicate": "", "forget_value": ""}  # fmt: skip
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def item(predicate: str, value: str, statement: str, quote: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"message": "m1", "quote": quote, "entity": "", "relation": "",
                            "predicate": predicate, "value": value, "statement": statement,
                            "change": False, "replaces": "", "certain": True, "sensitive": "",
                            "importance": 0.8}  # fmt: skip
    base.update(kw)
    return base


def last_user(request: ChatRequest) -> str:
    return request.messages[-1].content


async def turns(
    engine: ConversationEngine, *texts: str, model: str = MODEL
) -> list[list[dict[str, Any]]]:
    out: list[list[dict[str, Any]]] = []
    cid: str | None = None
    for t in texts:
        events, cid = await run_turn(engine, t, cid, model=model)
        out.append(events)
        for _ in range(300):  # let post-turn background work settle
            if engine.scheduler.background is None and not engine.is_busy():
                break
            await asyncio.sleep(0.01)
    await engine.close()
    return out


def run(storage: StorageHandle, tmp_path: Path, command: Callable[[ChatRequest], str], *texts: str,
        model: str = MODEL) -> tuple[ScriptedLLM, list[list[dict[str, Any]]]]:  # fmt: skip
    llm = ScriptedLLM(command=command, installed=(MODEL, QWEN), loaded={MODEL, QWEN})
    engine = make_engine(storage, llm, tmp_path)
    return llm, asyncio.run(turns(engine, *texts, model=model))


def saved(storage: StorageHandle) -> list[str]:
    return [m.content for m in storage.db.run_sync(lambda c: memory_repo.list_memories(c))]


def test_remember_is_written_before_the_reply_claims_it(
    tmp_path: Path, storage: StorageHandle
) -> None:
    msg = "Bunu unutma: yarın saat 10'da dişçi randevum var."
    cmd = answer("remember", items=[item("plan", "dişçi randevusu", "Kullanıcının yarın saat 10'da dişçi randevusu var.",
                                         "yarın saat 10'da dişçi randevum var")])  # fmt: skip
    llm, events = run(storage, tmp_path, lambda r: cmd, msg)
    assert saved(storage) == ["Kullanıcının yarın saat 10'da dişçi randevusu var."]
    assert any(e.get("stage") == "memory" for e in events[0] if e["type"] == "status")
    reply_prompt = last_user(llm.chat_requests[0])
    assert reply_prompt.startswith(commands.NOTICE_START)
    assert (
        "Kaydedildi (veritabanına yazıldı):\n- Kullanıcının yarın saat 10'da dişçi randevusu var."
        in reply_prompt
    )
    assert reply_prompt.endswith(msg)
    # The request itself runs on the cached prefix, and its message is not learned twice.
    assert llm.command_requests[0].messages[:-1] == llm.chat_requests[0].messages[:-1]
    job = storage.db.run_sync(lambda c: memory_repo.job_counts(c))
    assert job == {"skipped": 1}


def test_secrets_are_refused_with_the_reason(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Wifi şifremi kaydet: Kedi1234Gizli"
    cmd = answer(
        "remember",
        items=[
            item(
                "note",
                "wifi şifresi",
                "Wifi şifresi Kedi1234Gizli",
                "şifremi kaydet: Kedi1234Gizli",
            )
        ],
    )
    llm, _ = run(storage, tmp_path, lambda r: cmd, msg)
    assert saved(storage) == []
    notice = last_user(llm.chat_requests[0])
    assert "Kaydedilmedi:" in notice and "genel hafızada tutulmaz" in notice
    assert "kaydettim deme" in notice


def _seed_ahmet(storage: StorageHandle) -> str:
    c = Candidate(predicate="occupation", value="yazılımcı", statement="Ahmet yazılımcı.", about="entity",
                  entity=EntityRef("Ahmet", relation="çocukluk arkadaşı"))  # fmt: skip
    i = Candidate(predicate="interest", value="satranç", statement="Ahmet satranç oynar.", about="entity",
                  entity=EntityRef("Ahmet", relation="çocukluk arkadaşı"))  # fmt: skip
    r = storage.db.run_sync(
        lambda conn: service.apply_candidates(conn, [c, i], source=Source("import"), explicit=True)
    )
    return r.entities_created[0]


def test_forgetting_a_topic_happens_before_the_reply(
    tmp_path: Path, storage: StorageHandle
) -> None:
    _seed_ahmet(storage)
    cmd = answer(
        "forget", forget_scope="topic", forget_entity="Ahmet", forget_predicate="occupation"
    )
    llm, _ = run(
        storage, tmp_path, lambda r: cmd, "Ahmet'in mesleğini unut.", "Ahmet ne iş yapıyordu?"
    )
    assert saved(storage) == ["Ahmet satranç oynar."]
    notice = last_user(llm.chat_requests[0])
    assert "Silindi" in notice and "Ahmet (çocukluk arkadaşı) — meslek" in notice
    assert "geçmiş mesajların bu işlemle silinmediğini" in notice
    # In the same session: the forgotten topic is announced, the value is gone.
    later = last_user(llm.chat_requests[1])
    assert "yazılımcı" not in later and "Ahmet — meslek" in later and retrieval.BLOCK_START in later


def test_forgetting_a_person_waits_for_confirmation(tmp_path: Path, storage: StorageHandle) -> None:
    _seed_ahmet(storage)
    cmd = answer("forget", forget_scope="entity", forget_entity="Ahmet")
    llm, _ = run(storage, tmp_path, lambda r: cmd, "Ahmet hakkındaki her şeyi unut.", "Evet, sil.")
    first, second = (last_user(r) for r in llm.chat_requests)
    assert "Henüz silinmedi — kullanıcının onayı gerekiyor:" in first and "2 kayıt" in first
    assert "Silindi" in second and "Ahmet (çocukluk arkadaşı) hakkındaki 2 kayıt" in second
    assert len(llm.command_requests) == 1  # "Evet" needs no model call
    assert saved(storage) == []
    assert storage.db.run_sync(lambda c: memory_repo.find_entities(c, "ahmet")) == []


def test_declining_keeps_everything(tmp_path: Path, storage: StorageHandle) -> None:
    _seed_ahmet(storage)
    cmd = answer("forget", forget_scope="entity", forget_entity="Ahmet")
    llm, _ = run(storage, tmp_path, lambda r: cmd, "Ahmet'i tamamen unut.", "Hayır, vazgeçtim.")
    assert "Silme iptal edildi" in last_user(llm.chat_requests[1])
    assert len(saved(storage)) == 2


def test_untrusted_models_never_write(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(
        storage,
        tmp_path,
        lambda r: answer("none"),
        "Bunu kaydet: kahveyi şekersiz içerim.",
        model=QWEN,
    )
    assert llm.command_requests == [] and saved(storage) == []
    assert "yedek model hafızaya yazamaz" in last_user(llm.chat_requests[0])


def test_not_a_request_adds_nothing(tmp_path: Path, storage: StorageHandle) -> None:
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Şu dosyadaki boş satırları sil.")
    assert len(llm.command_requests) == 1
    assert commands.NOTICE_START not in last_user(llm.chat_requests[0])


def test_a_failed_request_is_reported_not_claimed(tmp_path: Path, storage: StorageHandle) -> None:
    llm, events = run(
        storage, tmp_path, lambda r: "bu JSON değil", "Bunu unutma: anahtarlar çekmecede."
    )
    assert events[0][-1]["type"] == "done"  # the reply still comes
    notice = last_user(llm.chat_requests[0])
    assert "teknik bir hata nedeniyle yapılamadı" in notice and saved(storage) == []


def test_what_do_you_know_needs_no_model_call(tmp_path: Path, storage: StorageHandle) -> None:
    _seed_ahmet(storage)
    c = Candidate(predicate="location", value="İzmir", statement="Kullanıcı İzmir'de yaşıyor.")
    storage.db.run_sync(
        lambda conn: service.apply_candidates(conn, [c], source=Source("import"), explicit=True)
    )
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Hakkımda ne biliyorsun?")
    assert llm.command_requests == []
    note = last_user(llm.chat_requests[0])
    assert (
        "Kullanıcı İzmir'de yaşıyor." in note
        and "Kayıtlı kişi ve projeler: Ahmet (çocukluk arkadaşı)" in note
    )
