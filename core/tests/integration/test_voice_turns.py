"""Spoken messages (Phase 13): an ordinary turn on the "voice" channel that never writes,
corrects or deletes memory, and changes no stored preference. Scripted model, test database."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lazis.config.model import MemorySection
from lazis.conversation import ConversationEngine
from lazis.conversation.engine import VOICE_MEMORY_NOTICE, TurnRequest
from lazis.memory import repository as memory_repo
from lazis.storage import StorageHandle
from tests.conftest import make_client
from tests.conversation_support import MODEL, ScriptedLLM, client_id, make_engine


async def _say(engine: ConversationEngine, text: str) -> str:
    handle = await engine.begin_turn(TurnRequest(None, client_id(), text, MODEL, channel="voice"))
    events = [e async for e in engine.events(handle)]
    return str([e for e in events if e["type"] == "done"][-1]["message"]["content"])


def test_a_spoken_memory_request_changes_nothing(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(reply=lambda r: "Sesli mesajla kaydedemiyorum; yazarak isteyebilirsiniz.")

    async def go() -> None:
        # Even with automatic learning forced on for the test, nothing is learned from speech.
        engine = make_engine(storage, llm, tmp_path, memory=MemorySection(auto_extract=True))
        await _say(engine, "Bunu hatırla: Kahveyi şekersiz içerim.")
        await _say(engine, "Derya'yı unut.")
        await engine.close()

    asyncio.run(go())
    assert llm.command_requests == []  # no memory command reached the model
    assert storage.db.run_sync(lambda c: memory_repo.count_memories(c)) == {}
    sent = llm.chat_requests[0].messages[-1].content
    assert sent.startswith(VOICE_MEMORY_NOTICE)
    channels = storage.db.run_sync(
        lambda c: [str(r[0]) for r in c.execute("SELECT channel FROM messages WHERE role='user'")]
    )
    assert channels == ["voice", "voice"]


def test_a_spoken_style_instruction_is_not_stored(tmp_path: Path, storage: StorageHandle) -> None:
    async def go() -> tuple[str, str]:
        engine = make_engine(storage, ScriptedLLM(), tmp_path)
        before = {d["dimension"]: d["value"] for d in (await engine.style())["dimensions"]}
        await _say(engine, "Bundan sonra hep çok kısa cevap ver.")
        after = {d["dimension"]: d["value"] for d in (await engine.style())["dimensions"]}
        await engine.close()
        return before["verbosity"], after["verbosity"]

    before, after = asyncio.run(go())
    assert before == after


def test_an_ordinary_spoken_message_is_answered_as_usual(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Bugün hava güzel görünüyor.")

    async def go() -> str:
        engine = make_engine(storage, llm, tmp_path)
        shown = await _say(engine, "Bugün hava nasıl?")
        await engine.close()
        return shown

    assert asyncio.run(go()) == "Bugün hava güzel görünüyor."
    assert not llm.chat_requests[-1].messages[-1].content.startswith(VOICE_MEMORY_NOTICE)


def test_the_api_accepts_the_voice_channel_only(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    auth = {"Authorization": f"Bearer {token}"}
    with make_client(tmp_path, storage, token, llm=ScriptedLLM()) as c:
        body = {"client_id": client_id(), "content": "Merhaba", "model": MODEL, "channel": "voice"}
        assert c.post("/api/v1/turns", json=body, headers=auth).status_code == 200
        bad = {**body, "client_id": client_id(), "channel": "telepathy"}
        assert c.post("/api/v1/turns", json=bad, headers=auth).status_code == 422


def test_a_spoken_request_cannot_be_answered_as_if_it_was_done(
    tmp_path: Path, storage: StorageHandle
) -> None:
    """Phase 15C (REL-004): a spoken memory request changes nothing, so the reply may not say
    it did, whatever the model writes. Shown and stored text are the same."""
    replies = iter(["Kaydettim efendim, artık biliyorum.", "Tamam efendim, Derya'yı unuttum."])
    llm = ScriptedLLM(reply=lambda r: next(replies))

    async def go() -> list[str]:
        engine = make_engine(storage, llm, tmp_path)
        shown = [await _say(engine, "Bunu hatırla: Kahveyi şekersiz içerim."),
                 await _say(engine, "Derya'yı unut.")]  # fmt: skip
        await engine.close()
        return shown

    saved, forgot = asyncio.run(go())
    assert "Kaydettim" not in saved and "unuttum" not in forgot.lower()
    stored = storage.db.run_sync(
        lambda c: [str(r[0]) for r in c.execute(
            "SELECT content FROM messages WHERE role='assistant' ORDER BY seq")]
    )  # fmt: skip
    assert stored == [saved, forgot]
    assert storage.db.run_sync(lambda c: memory_repo.count_memories(c)) == {}
