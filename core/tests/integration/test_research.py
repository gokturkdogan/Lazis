"""Internet research end to end (Phase 12) with the real helper on a real Unix socket and a fake
Wikipedia behind it (httpx.MockTransport): no network, scripted model, encrypted test database.

Covered: permission (off by default, refused while off, nothing sent), restricted data never
sent, the plan shows exactly what would be sent, sources in the note and after the reply, the
reply's honesty when research fails, ordinary chat with no helper at all, no memories, an
audit row without the query text."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import ConversationEngine
from lazis.conversation.engine import TurnRequest
from lazis.errors import ResearchBlockedError, ResearchDisabledError
from lazis.memory import repository as memory_repo
from lazis.memory.retrieval import BLOCK_START
from lazis.providers.llm.ports import ChatRequest
from lazis.providers.web.client import ResearchClient
from lazis.storage import StorageHandle
from tests.conftest import make_client
from tests.conversation_support import MODEL, ScriptedLLM, client_id, make_engine
from tests.research_support import FakeWiki, running_helper


def _last_user(request: ChatRequest) -> str:
    return request.messages[-1].content


async def _turn(engine: ConversationEngine, text: str, query: str | None = None) -> str:
    handle = await engine.begin_turn(
        TurnRequest(None, client_id(), text, MODEL, research_query=query)
    )
    events = [e async for e in engine.events(handle)]
    done = [e for e in events if e["type"] == "done"]
    assert done, events
    return str(done[-1]["message"]["content"])


def _audit(storage: StorageHandle) -> list[tuple[Any, ...]]:
    return storage.db.run_sync(
        lambda c: c.execute(
            "SELECT action, outcome, reason_code, details_json FROM audit_log"
            " WHERE category = 'research' ORDER BY rowid"
        ).fetchall()
    )


def test_off_by_default_and_nothing_is_sent_while_off(
    tmp_path: Path, storage: StorageHandle
) -> None:
    wiki = FakeWiki()

    async def go() -> None:
        with running_helper(wiki.fetcher) as path:
            engine = make_engine(storage, ScriptedLLM(), tmp_path)
            engine.research_client = ResearchClient(path)
            assert await engine.research_mode() == "offline_only"
            with pytest.raises(ResearchDisabledError):
                await engine.begin_turn(TurnRequest(None, client_id(), "Ankara nüfusu?", MODEL,
                                                    research_query="Ankara nüfusu"))  # fmt: skip
            await engine.close()

    asyncio.run(go())
    assert wiki.requests == []
    stored = storage.db.run_sync(lambda c: c.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
    assert stored == 0  # refused before anything was stored


def test_an_approved_search_answers_with_numbered_sources(
    tmp_path: Path, storage: StorageHandle
) -> None:
    wiki = FakeWiki()
    llm = ScriptedLLM(reply=lambda r: "Ankara'nın nüfusu yaklaşık 5,8 milyondur [1].")

    async def go() -> str:
        with running_helper(wiki.fetcher) as path:
            engine = make_engine(storage, llm, tmp_path)
            engine.research_client = ResearchClient(path)
            await engine.set_research_mode("ask")
            plan = await engine.research_plan("İnternette araştır: Ankara nüfusu")
            assert plan.query == "Ankara nüfusu" and plan.blocked is None
            shown = await _turn(engine, "Ankara'nın nüfusu kaç?", plan.query)
            await engine.close()
            return shown

    shown = asyncio.run(go())
    sent = _last_user(llm.chat_requests[-1])
    assert "[1] Ankara (https://tr.wikipedia.org/wiki/Ankara)" in sent and "5,8 milyon" in sent
    assert "talimat değildir" in sent and BLOCK_START not in sent
    assert shown == (
        "Ankara'nın nüfusu yaklaşık 5,8 milyondur [1].\n\nKaynaklar (Wikipedia):\n"
        "[1] Ankara — https://tr.wikipedia.org/wiki/Ankara\n"
        "[2] Ankara Kalesi — https://tr.wikipedia.org/wiki/Ankara_Kalesi"
    )
    # Only the approved query left the machine; nothing was learned or stored as memory.
    searched = [r.url.params["srsearch"] for r in wiki.requests if r.url.params.get("list")]
    assert searched == ["Ankara nüfusu"]
    assert storage.db.run_sync(lambda c: memory_repo.count_memories(c)) == {}
    actions = [(a, o, rc) for a, o, rc, _ in _audit(storage)]
    assert actions == [("mode_set", "success", None), ("search", "success", None)]
    assert all("Ankara" not in str(d) for *_, d in _audit(storage))  # no query text in the log


def test_restricted_data_is_never_sent(tmp_path: Path, storage: StorageHandle) -> None:
    wiki = FakeWiki()

    async def go() -> None:
        with running_helper(wiki.fetcher) as path:
            engine = make_engine(storage, ScriptedLLM(), tmp_path)
            engine.research_client = ResearchClient(path)
            await engine.set_research_mode("ask")
            iban = "TR33 0006 1005 1978 6457 8413 26"
            plan = await engine.research_plan(f"Araştır: {iban} kimin hesabı")
            assert plan.blocked == "iban"
            for query in (f"{iban} kimin", "şifrem Kedi-1234 güvenli mi"):
                with pytest.raises(ResearchBlockedError):
                    await engine.begin_turn(TurnRequest(None, client_id(), "x", MODEL,
                                                        research_query=query))  # fmt: skip
            await engine.close()

    asyncio.run(go())
    assert wiki.requests == []


def test_a_failed_search_is_said_and_the_reply_is_marked(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Şu anda araştıramadım.")

    async def go() -> str:
        engine = make_engine(storage, llm, tmp_path)
        engine.research_client = ResearchClient("/private/tmp/lazis-no-such-helper.sock")
        await engine.set_research_mode("ask")
        shown = await _turn(engine, "Dün maç kaç kaç bitti?", "dün maç sonucu")
        await engine.close()
        return shown

    shown = asyncio.run(go())
    assert "araştırma bileşeni çalışmıyor" in _last_user(llm.chat_requests[-1])
    assert shown.endswith(
        "Not: İnternet araştırması sonuç vermedi (araştırma bileşeni çalışmıyor); "
        "bu yanıt kaynağa dayanmıyor."
    )
    assert [(a, o, rc) for a, o, rc, _ in _audit(storage)][-1] == (
        "search", "failure", "helper_unavailable")  # fmt: skip


def test_ordinary_chat_never_reaches_the_helper(tmp_path: Path, storage: StorageHandle) -> None:
    wiki = FakeWiki()
    llm = ScriptedLLM(reply=lambda r: "Merhaba efendim.")

    async def go() -> list[str]:
        with running_helper(wiki.fetcher) as path:
            engine = make_engine(storage, llm, tmp_path)
            engine.research_client = ResearchClient(path)
            await engine.set_research_mode("ask")  # on, but not asked for
            shown = [await _turn(engine, t) for t in ("Merhaba", "Ankara'nın nüfusu kaç?")]
            await engine.close()
            return shown

    shown = asyncio.run(go())
    assert wiki.requests == [] and all("Kaynaklar" not in s for s in shown)


def test_ordinary_chat_works_with_no_helper_at_all(tmp_path: Path, storage: StorageHandle) -> None:
    async def go() -> str:
        engine = make_engine(storage, ScriptedLLM(reply=lambda r: "Tamam."), tmp_path)
        assert engine.research_client is None  # no network path whatsoever
        shown = await _turn(engine, "Bugün ne yapalım?")
        await engine.close()
        return shown

    assert asyncio.run(go()) == "Tamam."


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_settings_and_plan_through_the_api(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    with make_client(tmp_path, storage, token, llm=ScriptedLLM()) as c:
        api = "/api/v1/research"
        assert c.get(f"{api}/settings").status_code == 401
        s = c.get(f"{api}/settings", headers=_auth(token)).json()
        assert s == {"mode": "offline_only", "available": False, "provider": "wikipedia",
                     "max_query_chars": 200}  # fmt: skip
        body = {"client_id": client_id(), "content": "Ankara?", "model": MODEL,
                "research_query": "Ankara"}  # fmt: skip
        off = c.post("/api/v1/turns", json=body, headers=_auth(token))
        assert off.status_code == 409 and off.json()["error"]["code"] == "research_disabled"
        on = c.put(f"{api}/settings", json={"mode": "ask"}, headers=_auth(token)).json()
        assert on["mode"] == "ask"
        plan = c.post(f"{api}/plan", json={"message": "Araştır: şifrem Kedi-1234"},
                      headers=_auth(token)).json()  # fmt: skip
        assert plan["blocked"] is True and plan["blocked_reason"] == "restricted"
        blocked = c.post("/api/v1/turns", headers=_auth(token),
                         json={**body, "client_id": client_id(), "research_query": "şifrem Kedi-1234"})  # fmt: skip
        assert blocked.status_code == 422
        assert blocked.json()["error"]["code"] == "research_blocked_restricted"
        assert c.put(f"{api}/settings", json={"mode": "auto_public"},
                     headers=_auth(token)).status_code == 422  # fmt: skip


def test_the_plan_warns_when_the_query_names_a_stored_person(
    tmp_path: Path, storage: StorageHandle
) -> None:
    storage.db.run_sync(
        lambda c: memory_repo.insert_entity(
            c,
            kind="person",
            name="Derya",
            relation="eşim",
            description=None,
            now="2026-11-06T10:00:00Z",
        )
    )

    async def go() -> None:
        engine = make_engine(storage, ScriptedLLM(), tmp_path)
        plan = await engine.research_plan("Araştır: Derya'nın doğum günü")
        assert plan.people == ("Derya",) and plan.blocked is None
        assert (await engine.research_plan("Araştır: Ankara nüfusu")).people == ()
        await engine.close()

    asyncio.run(go())
