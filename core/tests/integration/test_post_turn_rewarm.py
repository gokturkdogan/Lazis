"""Phase 5 performance fix: the runtime does not reuse the tokens it generated, so the turn
after a reply re-processes that reply (measured with Gemma: ~845 of 900 tokens, PHASE_5_REPORT
§G). The cache bookkeeping now records only the prompt part, and the reply is processed in
the background right after the turn. Synthetic data only."""

from __future__ import annotations

import asyncio
from pathlib import Path

from lazis.config.model import MemorySection
from lazis.conversation import TurnRequest
from lazis.conversation.scheduler import CacheKey, InferenceScheduler
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, client_id, make_engine, run_turn


def _cache_stage(events: list[dict[str, object]]) -> object:
    return next(e for e in events if e.get("stage") == "processing_context")["cache"]


async def _wait_background(engine: object) -> None:
    for _ in range(200):
        job = engine.scheduler.background  # type: ignore[attr-defined]
        pending = engine._pending  # type: ignore[attr-defined]
        if job is None and not pending:
            return
        if job is not None and job.task is not None:
            await job.task
        await asyncio.sleep(0.01)


def test_holds_through_a_message() -> None:
    s = InferenceScheduler(lambda _rid: False)
    s.cache = CacheKey(MODEL, 16384, "c1", "p", 5)
    assert s.holds(MODEL, 16384, "c1", "p")
    assert s.holds(MODEL, 16384, "c1", "p", through_seq=5)
    assert not s.holds(MODEL, 16384, "c1", "p", through_seq=6)  # the reply is not cached


def test_reply_is_processed_in_the_background_after_the_turn(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Uzun bir yanıt. " * 40)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[dict[str, object]]:
        _, cid = await run_turn(engine, "Merhaba")
        await _wait_background(engine)
        events, _ = await run_turn(engine, "Devam edelim", cid)
        await engine.close()
        return events

    events = asyncio.run(go())
    rewarm = llm.prewarm_requests
    assert rewarm, "no post-turn re-warm"
    # The re-warm prompt ends with the reply, so the next turn finds it cached.
    assert rewarm[0].messages[-1].role == "assistant"
    assert rewarm[0].messages[-1].content.startswith("Uzun bir yanıt.")
    assert _cache_stage(events) == "warm"


def test_without_the_rewarm_the_next_turn_is_honestly_cold(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM()
    # Background learning also processes the reply (it runs on the same prefix): off here.
    engine = make_engine(
        storage, llm, tmp_path, prewarm=False, memory=MemorySection(auto_extract=False)
    )

    async def go() -> list[dict[str, object]]:
        _, cid = await run_turn(engine, "Merhaba")
        await _wait_background(engine)
        events, _ = await run_turn(engine, "Devam edelim", cid)
        await engine.close()
        return events

    events = asyncio.run(go())
    assert not llm.prewarm_requests
    assert _cache_stage(events) == "cold"  # the reply must be processed: not reported warm


def test_a_turn_sent_during_the_rewarm_joins_it(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[dict[str, object]]:
        _, cid = await run_turn(engine, "Merhaba")
        llm.gate = asyncio.Event()  # hold the re-warm in flight
        for _ in range(200):
            if engine.scheduler.background is not None:
                break
            await asyncio.sleep(0.01)
        job = engine.scheduler.background
        assert job is not None and job.kind == "prewarm"
        handle = await engine.begin_turn(TurnRequest(cid, client_id(), "Hemen soruyorum", MODEL))
        await asyncio.sleep(0.05)
        llm.gate.set()
        events = [e async for e in engine.events(handle)]
        await engine.close()
        return events

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"
    assert len(llm.prewarm_requests) == 1  # joined, not cancelled and repeated
    assert _cache_stage(events) == "warm"
