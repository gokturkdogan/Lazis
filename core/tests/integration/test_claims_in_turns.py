"""Truthful memory claims in real turns (Phase 7.1): what the user sees, what is stored and
what diagnostics say, with the production engine and a scripted model."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import repository
from lazis.memory import claims
from lazis.memory import repository as memory_repo
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, make_engine, run_turn
from tests.integration.test_memory_commands import answer, item

FORBIDDEN = ("not ettim", "not aldim", "kaydettim", "hafizama")


async def _turn(storage: StorageHandle, tmp_path: Path, message: str, reply: str, *,
                command: Callable[[ChatRequest], str] | None = None,
                chunk_size: int = 3) -> tuple[list[dict[str, Any]], dict[str, Any], str]:  # fmt: skip
    llm = ScriptedLLM(reply=lambda r: reply, chunk_size=chunk_size,
                      **({"command": command} if command else {}))  # fmt: skip
    engine = make_engine(storage, llm, tmp_path)
    events, cid = await run_turn(engine, message)
    last = dict(engine.last_turn or {})
    await engine.close()
    assert cid is not None
    stored = storage.db.run_sync(lambda c: repository.messages_between(c, cid, 1))[-1].content
    return events, last, stored


def shown_prefixes(events: list[dict[str, Any]]) -> list[str]:
    out, text = [], ""
    for e in events:
        if e["type"] == "delta":
            text += e["text"]
            out.append(text)
    return out


@pytest.mark.parametrize("chunk_size", [1, 2, 3, 5, 8, 64])
def test_a_statement_reply_never_shows_an_early_claim(
    tmp_path: Path, storage: StorageHandle, chunk_size: int
) -> None:
    reply = "Anlaşıldı efendim. Ahmet'in kardeşi Mehmet olduğunu not ettim; başka bir konu var mı?"
    events, last, stored = asyncio.run(
        _turn(storage, tmp_path, "Ahmet'in kardeşi Mehmet.", reply, chunk_size=chunk_size)
    )
    prefixes = shown_prefixes(events)
    for shown in prefixes:
        assert not any(f in claims.fold(shown) for f in FORBIDDEN), shown
    expected = "Anlaşıldı efendim. Ahmet'in kardeşi Mehmet olduğunu anladım; başka bir konu var mı?"
    done = next(e for e in events if e["type"] == "done")
    assert prefixes[-1] == expected == stored == done["message"]["content"]
    assert last["claim_state"] == "auto_learning_pending" and last["claims_rewritten"] == 1
    assert last["first_shown_ms"] is not None


def test_ordinary_replies_pass_through_unchanged(tmp_path: Path, storage: StorageHandle) -> None:
    reply = "Merhaba efendim, bugün size nasıl yardımcı olabilirim? Bir not defteri önerebilirim."
    events, last, stored = asyncio.run(_turn(storage, tmp_path, "Merhaba!", reply))
    assert shown_prefixes(events)[-1] == stored == reply
    assert last["claims_rewritten"] == 0


def test_a_saved_request_keeps_its_confirmation(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Bunu unutma: yarın saat 10'da dişçi randevum var."
    cmd = answer("remember", items=[item("plan", "dişçi randevusu", "Kullanıcının yarın saat 10'da dişçi randevusu var.",
                                         "yarın saat 10'da dişçi randevum var")])  # fmt: skip
    reply = "Kaydettim efendim. Yarın saat 10'da dişçi randevunuz var."
    events, last, stored = asyncio.run(_turn(storage, tmp_path, msg, reply, command=lambda r: cmd))
    assert stored == reply == shown_prefixes(events)[-1]
    assert last["claim_state"] == "save_succeeded" and last["claims_rewritten"] == 0
    assert storage.db.run_sync(lambda c: memory_repo.list_memories(c))  # it really was saved


def test_a_failed_request_cannot_claim_success(tmp_path: Path, storage: StorageHandle) -> None:
    msg = "Bunu unutma: yarın saat 10'da dişçi randevum var."
    reply = "Kaydettim efendim."
    events, last, stored = asyncio.run(
        _turn(storage, tmp_path, msg, reply, command=lambda r: "{bozuk")
    )
    assert stored == "Kaydedemedim efendim." == shown_prefixes(events)[-1]
    assert last["memory_outcome"] == "failed" and last["claim_state"] == "save_failed"
    assert storage.db.run_sync(lambda c: memory_repo.list_memories(c)) == []


def test_a_pending_deletion_is_not_reported_done(tmp_path: Path, storage: StorageHandle) -> None:
    from tests.integration.test_memory_commands import _seed_ahmet

    _seed_ahmet(storage)
    cmd = answer("forget", forget_scope="entity", forget_entity="Ahmet")
    reply = "Ahmet hakkındaki bilgileri hafızamdan sildim efendim."
    _events, last, stored = asyncio.run(
        _turn(storage, tmp_path, "Ahmet hakkındaki her şeyi unut.", reply, command=lambda r: cmd)
    )
    assert last["claim_state"] == "delete_pending"
    assert stored == "Ahmet hakkındaki bilgileri hafızamdan henüz silmedim efendim."


def test_cancelled_reply_stores_only_what_was_shown(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(reply=lambda r: "Anlaşıldı efendim, bunu not aldım ve " + "çok güzel " * 40,
                      chunk_size=2, delay=0.002)  # fmt: skip
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[str, str]:
        from lazis.conversation import TurnRequest

        handle = await engine.begin_turn(
            TurnRequest(None, "c-1", "Ahmet'in kardeşi Mehmet.", MODEL)
        )
        shown = ""
        async for e in engine.events(handle):
            if e["type"] == "delta":
                shown += e["text"]
                if len(shown) > 60:
                    engine.cancel_turn(handle.user.client_id)
        await engine.close()
        stored = storage.db.run_sync(lambda c: repository.get_message(c, handle.assistant.id))
        assert stored is not None
        return shown, stored.content

    shown, stored = asyncio.run(go())
    assert 60 < len(shown) < 300 and stored == shown  # really cut short (the full reply is 437)
    assert not any(f in claims.fold(shown) for f in FORBIDDEN)


def test_logs_carry_no_claim_words(
    tmp_path: Path, storage: StorageHandle, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    asyncio.run(_turn(storage, tmp_path, "Ahmet'in kardeşi Mehmet.", "Mehmet olduğunu not ettim."))
    logged = "\n".join(r.getMessage() + " " + json.dumps(getattr(r, "lazis_fields", {}), ensure_ascii=False)
                       for r in caplog.records)  # fmt: skip
    assert "memory.claims_rewritten" in logged
    assert "not ettim" not in logged and "Mehmet" not in logged
