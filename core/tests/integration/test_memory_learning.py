"""Background learning in the conversation engine: durable jobs, extraction on the cached
prefix, preemption by turns, trusted models only, retries, restart recovery, and that
nothing the model proposes is written unchecked. Scripted model, synthetic data only."""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lazis.config.model import MemorySection
from lazis.conversation import ConversationEngine, TurnRequest
from lazis.memory import repository as memory_repo
from lazis.memory.models import Memory
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conversation_support import MODEL, ScriptedLLM, client_id, make_engine, run_turn

QWEN = "qwen3.5:9b-q4_K_M"
_TARGET = re.compile(r"^\[(m\d+)\] «(.*)»$", re.M)


def extractor(
    rules: dict[str, Callable[[str, str], dict[str, Any]]],
) -> Callable[[ChatRequest], str]:
    """A fake model: for each quoted target that contains a rule's keyword, the rule's item."""

    def run(request: ChatRequest) -> str:
        items: list[dict[str, Any]] = []
        for tag, body in _TARGET.findall(request.messages[-1].content):
            items += [make(tag, body) for key, make in rules.items() if key in body]
        return json.dumps({"items": items}, ensure_ascii=False)

    return run


def fact(
    predicate: str, value: str, statement: str, quote: str, **kw: Any
) -> Callable[[str, str], dict[str, Any]]:
    def make(tag: str, _body: str) -> dict[str, Any]:
        base: dict[str, Any] = {
            "message": tag, "quote": quote, "entity": "", "relation": "", "predicate": predicate,
            "value": value, "statement": statement, "change": False, "replaces": "",
            "certain": True, "sensitive": "", "importance": 0.7,
        }  # fmt: skip
        base.update(kw)
        return base

    return make


CITY = {"İzmir": fact("location", "İzmir", "Kullanıcı İzmir'de yaşıyor.", "İzmir'de yaşıyorum")}


async def settle(engine: ConversationEngine, *, until: Callable[[], bool] | None = None) -> None:
    """Let the maintenance loop run until nothing is pending (or ``until`` holds)."""
    for _ in range(400):
        await asyncio.sleep(0.01)
        idle = engine.scheduler.background is None and not engine._learn and not engine.is_busy()  # pyright: ignore[reportPrivateUsage]
        if until() if until else idle:
            return


def memories(storage: StorageHandle) -> list[Memory]:
    return storage.db.run_sync(lambda c: memory_repo.list_memories(c))


def jobs(storage: StorageHandle) -> dict[str, int]:
    return storage.db.run_sync(memory_repo.job_counts)


def test_a_turn_is_learned_from_on_the_cached_prefix(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(memory=extractor(CITY))
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> dict[str, Any]:
        await run_turn(engine, "Merhaba, ben İzmir'de yaşıyorum.")
        await settle(engine)
        diag = await engine.diagnostics()
        await engine.close()
        return diag

    diag = asyncio.run(go())
    assert [m.value for m in memories(storage)] == ["İzmir"]
    assert jobs(storage) == {"done": 1}
    # Extraction = the re-warmed prompt (system, user, reply) + one instruction at the end.
    warm, extract = llm.prewarm_requests[-1], llm.memory_requests[-1]
    assert extract.messages[:-1] == warm.messages
    assert (
        extract.messages[-1].role == "user"
        and "[m1] «Merhaba, ben İzmir'de" in extract.messages[-1].content
    )
    assert extract.options.temperature == 0.0
    assert diag["memory"]["learning"]["created"] == 1 and diag["memory"]["memories"] == {
        "active": 1
    }
    assert diag["cache_expected_warm"] is True  # the instruction does not displace the prefix


def test_a_turn_preempts_learning_and_it_resumes(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(memory=extractor(CITY))
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> list[dict[str, object]]:
        gate = llm.memory_gate = asyncio.Event()  # hold the extraction in flight
        _, cid = await run_turn(engine, "Ben İzmir'de yaşıyorum.")
        await settle(engine, until=lambda: bool(llm.memory_requests))
        job = engine.scheduler.background
        assert job is not None and job.kind == "memory"
        handle = await engine.begin_turn(TurnRequest(cid, client_id(), "Hava nasıl?", MODEL))
        events = [e async for e in engine.events(handle)]  # not delayed by the held extraction
        assert storage.db.run_sync(memory_repo.job_counts) == {"queued": 2}  # back in the queue
        gate.set()
        await settle(engine)
        await engine.close()
        return events

    events = asyncio.run(go())
    assert events[-1]["type"] == "done"
    assert [m.value for m in memories(storage)] == ["İzmir"]  # retried after the turn, once
    assert jobs(storage) == {"done": 2}


def test_untrusted_models_never_write_and_their_turns_wait(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(memory=extractor(CITY), installed=(MODEL, QWEN), loaded={MODEL, QWEN})
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        _, cid = await run_turn(engine, "Ben İzmir'de yaşıyorum.", model=QWEN)
        await settle(engine)
        assert llm.memory_requests == [] and jobs(storage) == {"deferred": 1}
        await run_turn(engine, "Peki, teşekkürler.", cid, model=MODEL)
        await settle(engine)
        await engine.close()

    asyncio.run(go())
    assert len(llm.memory_requests) == 1  # both messages in one request, run by the trusted model
    assert "[m2]" in llm.memory_requests[0].messages[-1].content
    assert [m.value for m in memories(storage)] == ["İzmir"] and jobs(storage) == {"done": 2}


def test_unchecked_proposals_are_never_written(tmp_path: Path, storage: StorageHandle) -> None:
    rules = {
        # A fact the user did not say (it quotes LAZIS's reply).
        "Merhaba": fact("occupation", "doktor", "Kullanıcı doktor.", "Tamam efendim, anladım"),
        # A secret the user shared.
        "şifrem": fact(
            "note", "wifi şifresi", "Ev wifi şifresi Kedi1234Gizli", "şifrem Kedi1234Gizli"
        ),
        # A real, quoted fact.
        "Rust": fact("skill", "Rust", "Kullanıcı Rust biliyor.", "Rust biliyorum"),
    }
    llm = ScriptedLLM(memory=extractor(rules))
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> dict[str, Any]:
        await run_turn(engine, "Merhaba! Rust biliyorum, bu arada wifi şifrem Kedi1234Gizli.")
        await settle(engine)
        diag = await engine.diagnostics()
        await engine.close()
        return diag

    diag = asyncio.run(go())
    assert [m.value for m in memories(storage)] == ["Rust"]
    learning = diag["memory"]["learning"]
    assert (learning["proposed"], learning["accepted"], learning["created"]) == (3, 2, 1)
    assert learning["rejected"] == {"quote_not_found": 1}
    log = (tmp_path / "logs").rglob("*")
    assert all(b"Kedi1234Gizli" not in p.read_bytes() for p in log if p.is_file())


def test_invalid_output_is_retried_then_reported(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(memory=lambda r: "bu JSON değil")
    engine = make_engine(storage, llm, tmp_path, memory=MemorySection(max_attempts=2))

    async def go() -> dict[str, Any]:
        _, cid = await run_turn(engine, "Ben İzmir'de yaşıyorum.")
        await settle(engine, until=lambda: engine.learner.status.get("state") == "failed")
        engine._pending[cid] = 0.0  # pyright: ignore[reportPrivateUsage]  # skip the 60 s back-off
        engine._wake.set()  # pyright: ignore[reportPrivateUsage]
        await settle(engine, until=lambda: jobs(storage) == {"failed": 1})
        diag = await engine.diagnostics()
        await engine.close()
        return diag

    diag = asyncio.run(go())
    assert len(llm.memory_requests) == 2 and jobs(storage) == {"failed": 1}
    assert diag["memory"]["learning"]["code"] == "llm_invalid_response"
    assert memories(storage) == []


def test_jobs_survive_a_restart(tmp_path: Path, storage: StorageHandle) -> None:
    quiet = ScriptedLLM(memory_gate=asyncio.Event())  # learning never gets to finish
    first = make_engine(storage, quiet, tmp_path)

    async def crash() -> None:
        await run_turn(first, "Ben İzmir'de yaşıyorum.")
        # Simulate a crash mid-extraction: the job is left 'running', nothing was learned.
        storage.db.run_sync(lambda c: c.execute("UPDATE memory_jobs SET status = 'running'"))
        first._closing = True  # pyright: ignore[reportPrivateUsage]
        await first.close()

    asyncio.run(crash())
    assert jobs(storage) == {"running": 1}

    llm = ScriptedLLM(memory=extractor(CITY))
    second = make_engine(storage, llm, tmp_path)

    async def restart() -> None:
        await second.ensure_started()
        await settle(second, until=lambda: jobs(storage) == {"done": 1})
        await second.close()

    asyncio.run(restart())
    assert [m.value for m in memories(storage)] == ["İzmir"]
    # One job per message: a recovered job is processed once, never duplicated.
    assert (
        storage.db.run_sync(lambda c: c.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0])
        == 1
    )


def test_learning_can_be_switched_off(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(memory=extractor(CITY))
    engine = make_engine(storage, llm, tmp_path, memory=MemorySection(auto_extract=False))

    async def go() -> None:
        await run_turn(engine, "Ben İzmir'de yaşıyorum.")
        await settle(engine)
        await engine.close()

    asyncio.run(go())
    assert llm.memory_requests == [] and jobs(storage) == {} and memories(storage) == []


def test_learning_waits_for_the_user_to_be_idle(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(memory=extractor(CITY))
    engine = make_engine(storage, llm, tmp_path, memory=MemorySection(learn_after_idle_s=0.6))

    async def go() -> tuple[int, int]:
        await run_turn(engine, "Ben İzmir'de yaşıyorum.")
        await asyncio.sleep(0.3)
        early = len(llm.memory_requests)  # not yet: the user may still be typing
        await settle(
            engine, until=lambda: bool(llm.memory_requests) and engine.scheduler.background is None
        )
        await engine.close()
        return early, len(llm.memory_requests)

    early, later = asyncio.run(go())
    assert (early, later) == (0, 1)
    assert [m.value for m in memories(storage)] == ["İzmir"]
