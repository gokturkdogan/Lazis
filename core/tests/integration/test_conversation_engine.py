"""Conversation engine against a real encrypted database and a scripted local model.

Multi-turn context, isolation, reopening, cancellation and partial replies, failures, crash
and shutdown recovery, duplicate submissions, compaction (sync and idle), the fallback trim,
pre-warming and a 300-turn soak. Synthetic data only.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.conversation import TurnRequest, repository
from lazis.conversation.prompts import CANCELLED_MARKER, INTERRUPTED_MARKER, S0_POLICY
from lazis.errors import (
    ConversationNotFoundError,
    LlmBusyError,
    LlmInvalidResponseError,
    LlmModelNotFoundError,
    LlmUnavailableError,
    MessageTooLongError,
    TurnDuplicateError,
)
from lazis.ids import utc_now_iso
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, open_storage
from tests.conversation_support import (
    MODEL,
    ScriptedLLM,
    client_id,
    make_engine,
    prompt_tokens,
    run_turn,
)


def kinds(events: list[dict[str, object]]) -> list[object]:
    return [e["type"] for e in events]


def stages(events: list[dict[str, object]]) -> list[object]:
    return [e["stage"] for e in events if e["type"] == "status"]


def rows(storage: StorageHandle, conversation_id: str) -> list[repository.Message]:
    return storage.db.run_sync(lambda c: repository.messages_between(c, conversation_id, 1))


def test_single_turn_is_persisted_with_metrics(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(reply=lambda r: "Merhaba, size nasıl yardımcı olabilirim?")
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[list[dict[str, object]], str]:
        out = await run_turn(engine, "Merhaba LAZIS")
        await engine.close()
        return out

    events, cid = asyncio.run(go())
    assert kinds(events)[0] == "start" and kinds(events)[-1] == "done"
    assert "processing_context" in stages(events)
    assert (
        "".join(str(e["text"]) for e in events if e["type"] == "delta")
        == "Merhaba, size nasıl yardımcı olabilirim?"
    )
    msgs = rows(storage, cid)
    assert [(m.seq, m.role, m.status) for m in msgs] == [
        (1, "user", "complete"),
        (2, "assistant", "complete"),
    ]
    assert msgs[1].content == "Merhaba, size nasıl yardımcı olabilirim?"
    assert msgs[1].prompt_tokens == prompt_tokens(llm.chat_requests[0])
    assert msgs[0].context_note == "[Mesaj zamanı: 17 Ekim 2026 Cumartesi 14:32]"
    conv = storage.db.run_sync(lambda c: repository.get_conversation(c, cid))
    assert conv is not None and conv.title == "Merhaba LAZIS" and conv.message_count == 2


def test_multi_turn_context_and_isolation(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[str, str]:
        _, a = await run_turn(engine, "Kız kardeşimin adı Ayşe.")
        _, b = await run_turn(engine, "Bugün hava çok güzel.")
        await run_turn(engine, "Kız kardeşimin adı neydi?", a)
        await engine.close()
        return a, b

    a, b = asyncio.run(go())
    third = llm.chat_requests[2]
    contents = [m.content for m in third.messages]
    assert any("Ayşe" in c for c in contents) and not any("hava" in c for c in contents)
    assert third.messages[0].role == "system" and third.messages[0].content.startswith(S0_POLICY)
    # Requests of one conversation are append-only: request 3 starts with request 1.
    first = llm.chat_requests[0]
    assert list(third.messages[: len(first.messages)]) == list(first.messages)
    assert len(rows(storage, a)) == 4 and len(rows(storage, b)) == 2


def test_reopen_after_restart_and_continue(
    tmp_path: Path, storage_section: StorageSection, key: SecretBytes
) -> None:
    llm = ScriptedLLM()
    first = open_storage(storage_section, key, app_version="test")
    engine = make_engine(first, llm, tmp_path)

    async def one() -> str:
        _, cid = await run_turn(engine, "Projenin adı Kuzey.")
        await engine.close()
        return cid

    cid = asyncio.run(one())
    first.db.close()

    second = open_storage(storage_section, key, app_version="test")
    try:
        engine2 = make_engine(second, llm, tmp_path)

        async def two() -> list[str]:
            items, _ = await engine2.list_conversations(limit=10)
            await run_turn(engine2, "Projenin adı neydi?", cid)
            await engine2.close()
            return [c.id for c in items]

        assert asyncio.run(two()) == [cid]
        assert any("Kuzey" in m.content for m in llm.chat_requests[-1].messages)
        assert [m.seq for m in rows(second, cid)] == [1, 2, 3, 4]
    finally:
        second.db.close()


def test_cancel_keeps_the_partial_reply_and_marks_it_in_later_context(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Uzun bir yanıt " * 40, chunk_size=4, delay=0.01)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[list[dict[str, object]], str]:
        handle = await engine.begin_turn(TurnRequest(None, "client-cancel-1", "Uzun anlat", MODEL))
        seen: list[dict[str, object]] = []
        async for event in engine.events(handle):
            seen.append(event)
            if event["type"] == "delta" and sum(1 for e in seen if e["type"] == "delta") == 5:
                assert engine.cancel_turn("client-cancel-1")
        llm.delay = 0.0
        await run_turn(engine, "Devam et", handle.conversation.id)
        await engine.close()
        return seen, handle.conversation.id

    events, cid = asyncio.run(go())
    assert kinds(events)[-1] == "cancelled"
    msgs = rows(storage, cid)
    assert msgs[1].status == "cancelled"
    assert 0 < len(msgs[1].content) < len("Uzun bir yanıt " * 40)
    later = llm.chat_requests[-1].messages
    assert any(m.role == "assistant" and m.content.endswith(CANCELLED_MARKER) for m in later)
    assert msgs[2].role == "user"  # the user could send right after cancelling


def test_failed_reply_is_stored_as_failed_and_left_out_of_context(
    tmp_path: Path, storage: StorageHandle
) -> None:
    from lazis.errors import LlmLoadFailedError

    llm = ScriptedLLM(reply=lambda r: "kısmi metin burada", fail_with=LlmLoadFailedError("x"))
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[list[dict[str, object]], str]:
        events, cid = await run_turn(engine, "Merhaba")
        llm.fail_with = None
        await run_turn(engine, "Tekrar deniyorum", cid)
        await engine.close()
        return events, cid

    events, cid = asyncio.run(go())
    assert events[-1]["type"] == "error" and events[-1]["code"] == "llm_load_failed"
    msgs = rows(storage, cid)
    assert msgs[1].status == "failed" and msgs[1].error_code == "llm_load_failed"
    assert not any(m.role == "assistant" for m in llm.chat_requests[-1].messages)


def test_runtime_down_and_missing_model_are_refused_before_storing(
    tmp_path: Path, storage: StorageHandle
) -> None:
    async def go() -> None:
        engine = make_engine(storage, None, tmp_path)
        with pytest.raises(LlmUnavailableError):
            await run_turn(engine, "Merhaba")
        engine2 = make_engine(storage, ScriptedLLM(installed=()), tmp_path)
        with pytest.raises(LlmModelNotFoundError):
            await run_turn(engine2, "Merhaba")
        items, _ = await engine2.list_conversations(limit=10)
        assert items == []
        await engine.close()
        await engine2.close()

    asyncio.run(go())


def test_shutdown_during_generation_marks_interrupted(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "yanıt " * 200, chunk_size=3, delay=0.01)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> str:
        handle = await engine.begin_turn(TurnRequest(None, client_id(), "Anlat", MODEL))
        async for event in engine.events(handle):
            if event["type"] == "delta":
                break
        await asyncio.sleep(0.05)
        await engine.close()
        return handle.conversation.id

    cid = asyncio.run(go())
    reply = rows(storage, cid)[1]
    assert reply.status in ("interrupted", "cancelled")
    assert reply.status != "complete" and reply.content


def test_crash_leftover_streaming_row_is_recovered_as_interrupted(
    tmp_path: Path, storage: StorageHandle
) -> None:
    now = utc_now_iso()

    def seed(conn: repository.Connection) -> str:
        with repository.transaction(conn):
            conv = repository.insert_conversation(conn, title="t", model=MODEL, now=now)
            user = repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="user",
                content="Soru",
                status="complete",
                now=now,
            )
            repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="assistant",
                content="",
                status="streaming",
                now=now,
                reply_to=user.id,
            )
            repository.update_partial(conn, repository.reply_for(conn, user.id).id, "Yarım kalan")  # type: ignore[union-attr]
        return conv.id

    cid = storage.db.run_sync(seed)
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        await engine.ensure_started()
        await run_turn(engine, "Devam", cid)
        await engine.close()

    asyncio.run(go())
    msgs = rows(storage, cid)
    assert msgs[1].status == "interrupted" and msgs[1].content == "Yarım kalan"
    assert engine.recovered_interrupted == 1
    later = llm.chat_requests[-1].messages
    assert any(m.content.endswith(INTERRUPTED_MARKER) for m in later)


def test_duplicate_submission_and_busy_are_refused(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(delay=0.01)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> str:
        handle = await engine.begin_turn(TurnRequest(None, "client-dup-0001", "Merhaba", MODEL))
        with pytest.raises(LlmBusyError):
            await engine.begin_turn(TurnRequest(None, client_id(), "İkinci", MODEL))
        [e async for e in engine.events(handle)]
        with pytest.raises(TurnDuplicateError):
            await engine.begin_turn(
                TurnRequest(handle.conversation.id, "client-dup-0001", "Merhaba", MODEL)
            )
        with pytest.raises(ConversationNotFoundError):
            await engine.begin_turn(
                TurnRequest("01JZZZZZZZZZZZZZZZZZZZZZZZ", client_id(), "x", MODEL)
            )
        with pytest.raises(MessageTooLongError):
            await engine.begin_turn(TurnRequest(None, client_id(), "x" * 16000, MODEL))
        await engine.close()
        return handle.conversation.id

    cid = asyncio.run(go())
    assert len(rows(storage, cid)) == 2


def long_reply(_req: object) -> str:
    return "Bu konuda ayrıntılı düşündüm ve şunları önerebilirim. " * 30


def test_over_budget_turn_compacts_first_and_keeps_originals(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=long_reply)
    # Small window so a handful of turns crosses the hard limit; no idle compaction.
    engine = make_engine(storage, llm, tmp_path, idle_compaction_delay_s=3600.0)
    engine.num_ctx = 4096
    from lazis.conversation.context import Budget

    engine.budget = Budget.build(4096, 512, 0.10, 4096)

    async def go() -> tuple[str, list[list[dict[str, object]]]]:
        all_events: list[list[dict[str, object]]] = []
        cid: str | None = None
        for i in range(8):
            events, cid = await run_turn(
                engine, f"Hedefim {i}: düzenli spor yapmak ve kitap okumak.", cid
            )
            all_events.append(events)
        await engine.close()
        assert cid is not None
        return cid, all_events

    cid, all_events = asyncio.run(go())
    assert any("compacting" in stages(e) for e in all_events)
    assert llm.summary_requests
    # Originals are untouched: 8 user + 8 assistant messages, all complete.
    msgs = rows(storage, cid)
    assert len(msgs) == 16 and all(m.status == "complete" for m in msgs)
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "summary_window" and ctx.window_start_seq > 1
    summaries = storage.db.run_sync(lambda c: repository.list_summaries(c, cid))
    assert summaries[-1].status == "active" and summaries[-1].to_seq == ctx.window_start_seq - 1
    # Every request stayed inside the window: prompt + reply reserve ≤ num_ctx.
    for req in llm.chat_requests:
        assert prompt_tokens(req) + 512 <= 4096
    last = llm.chat_requests[-1].messages[0].content
    assert "Konuşma özeti (#1–" in last


def test_idle_compaction_runs_in_background_then_prewarms(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=long_reply)
    engine = make_engine(
        storage,
        llm,
        tmp_path,
        compact_at_tokens=1500,
        keep_recent_tokens=256,
        summary_max_tokens=400,
    )

    async def go() -> str:
        cid: str | None = None
        for i in range(3):
            _, cid = await run_turn(engine, f"Not {i}: haftalık plan hazırlıyorum.", cid)
        assert cid is not None
        for _ in range(200):
            await asyncio.sleep(0.02)
            ctx = await engine.context_info(cid)
            if (
                ctx["strategy"] == "summary_window"
                and engine.scheduler.background is None
                and llm.prewarm_requests
            ):
                break
        await engine.close()
        return cid

    cid = asyncio.run(go())
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "summary_window"
    assert llm.summary_requests and llm.prewarm_requests
    assert len(rows(storage, cid)) == 6


def test_failed_compaction_falls_back_to_an_announced_trim(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=long_reply, summary_fails=True)
    engine = make_engine(storage, llm, tmp_path, idle_compaction_delay_s=3600.0)
    engine.num_ctx = 4096
    from lazis.conversation.context import Budget

    engine.budget = Budget.build(4096, 512, 0.10, 4096)

    async def go() -> tuple[str, list[list[dict[str, object]]]]:
        cid: str | None = None
        out: list[list[dict[str, object]]] = []
        for i in range(8):
            events, cid = await run_turn(engine, f"Mesaj {i}", cid)
            out.append(events)
        await engine.close()
        assert cid is not None
        return cid, out

    cid, all_events = asyncio.run(go())
    assert any("context_trimmed" in stages(e) for e in all_events)
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "window_only"
    system = llm.chat_requests[-1].messages[0].content
    assert "şu an bağlamda yok" in system
    for req in llm.chat_requests:
        assert prompt_tokens(req) + 512 <= 4096


def test_prewarm_warms_the_cache_and_the_next_turn_reports_warm(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> tuple[dict[str, object], list[dict[str, object]], dict[str, object]]:
        _, cid = await run_turn(engine, "Merhaba")
        engine.scheduler.cache = None  # e.g. another conversation used the runtime
        llm.loaded.clear()  # and the model was unloaded (keep_alive)
        first = await engine.prepare(cid, MODEL)
        assert (
            engine.scheduler.background is not None and engine.scheduler.background.task is not None
        )
        await engine.scheduler.background.task
        second = await engine.prepare(cid, MODEL)
        events, _ = await run_turn(engine, "Nasılsın?", cid)
        await engine.close()
        return first, events, second

    first, events, second = asyncio.run(go())
    assert first["state"] == "warming" and first["model_loaded"] is False
    assert second["state"] == "warm"
    assert llm.loads == [MODEL]
    status = [e for e in events if e["type"] == "status" and e["stage"] == "processing_context"]
    assert status and status[0]["cache"] == "warm"
    assert "loading_model" not in stages(events)


def test_turn_waits_for_a_running_prewarm_instead_of_cancelling_it(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        _, cid = await run_turn(engine, "Merhaba")
        engine.scheduler.cache = None
        llm.gate = asyncio.Event()
        state = await engine.prepare(cid, MODEL)
        assert state["state"] == "warming"
        handle = await engine.begin_turn(TurnRequest(cid, client_id(), "Devam", MODEL))
        await asyncio.sleep(0.05)
        llm.gate.set()
        events = [e async for e in engine.events(handle)]
        assert events[-1]["type"] == "done"
        await engine.close()

    asyncio.run(go())
    assert len(llm.prewarm_requests) == 1  # finished, not restarted


def test_turn_preempts_background_compaction(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM(reply=long_reply)
    engine = make_engine(
        storage,
        llm,
        tmp_path,
        compact_at_tokens=1500,
        keep_recent_tokens=256,
        summary_max_tokens=400,
    )

    async def go() -> str:
        cid: str | None = None
        for i in range(3):
            _, cid = await run_turn(engine, f"Not {i}", cid)
        assert cid is not None
        llm.gate = asyncio.Event()  # the next request (the compaction) blocks
        for _ in range(100):
            await asyncio.sleep(0.01)
            job = engine.scheduler.background
            if job is not None and job.kind == "compaction":
                break
        assert engine.scheduler.background is not None
        llm.gate.set()
        llm.gate = None
        events, _ = await run_turn(engine, "Acil bir soru", cid)
        assert events[-1]["type"] == "done"
        await engine.close()
        return cid

    cid = asyncio.run(go())
    assert rows(storage, cid)[-1].status == "complete"


def test_delete_removes_everything_and_unloads_cached_text(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=long_reply)
    engine = make_engine(
        storage,
        llm,
        tmp_path,
        compact_at_tokens=1500,
        keep_recent_tokens=256,
        summary_max_tokens=400,
    )

    async def go() -> tuple[str, str]:
        _, keep = await run_turn(engine, "Başka bir sohbet")
        cid: str | None = None
        for i in range(3):
            _, cid = await run_turn(engine, f"Silinecek {i}", cid)
        assert cid is not None
        for _ in range(200):
            await asyncio.sleep(0.02)
            if storage.db.run_sync(lambda c: repository.list_summaries(c, cid)):
                break
        await engine.delete(cid)
        with pytest.raises(ConversationNotFoundError):
            await engine.delete(cid)
        await engine.close()
        return cid, keep

    cid, keep = asyncio.run(go())
    counts = storage.db.run_sync(lambda c: repository.count_rows(c, cid))
    assert counts == {
        "conversations": 0,
        "messages": 0,
        "context_summaries": 0,
        "conversation_context": 0,
    }
    assert len(rows(storage, keep)) == 2
    audit = storage.db.run_sync(
        lambda c: c.execute(
            "SELECT target_refs, details_json FROM audit_log WHERE category='conversation'"
        ).fetchall()
    )
    assert len(audit) == 1 and cid in audit[0][0] and "Silinecek" not in str(audit)
    assert MODEL in llm.unloads


def test_rename_and_paging(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        cid: str | None = None
        for i in range(6):
            _, cid = await run_turn(engine, f"Mesaj {i}", cid)
        assert cid is not None
        conv = await engine.rename(cid, "  Haftalık   plan ")
        assert conv.title == "Haftalık plan" and conv.title_source == "user"
        page1, more1 = await engine.messages(cid, before_seq=None, limit=5)
        page2, more2 = await engine.messages(cid, before_seq=page1[0].seq, limit=5)
        assert [m.seq for m in page1] == [8, 9, 10, 11, 12] and more1
        assert [m.seq for m in page2] == [3, 4, 5, 6, 7] and more2
        _, cid2 = await run_turn(engine, "Yeni sohbet")
        items, _ = await engine.list_conversations(limit=10)
        assert [c.id for c in items] == [cid2, cid]
        await engine.close()

    asyncio.run(go())


def test_soak_300_turns_never_overflows_the_context(tmp_path: Path, storage: StorageHandle) -> None:
    """B8-style soak with the scripted model: 300 turns, compaction as needed, no errors."""
    llm = ScriptedLLM(reply=lambda r: "Anladım, not aldım. " * 12)
    engine = make_engine(storage, llm, tmp_path, idle_compaction_delay_s=3600.0)

    async def go() -> str:
        cid: str | None = None
        for i in range(300):
            events, cid = await run_turn(
                engine, f"Gün {i}: bugün {i % 7} saat çalıştım ve {i % 5} sayfa okudum.", cid
            )
            assert events[-1]["type"] == "done", events[-1]
        await engine.close()
        assert cid is not None
        return cid

    cid = asyncio.run(go())
    assert len(rows(storage, cid)) == 600
    hard = engine.budget.hard_limit
    for req in llm.chat_requests:
        assert prompt_tokens(req) <= hard
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "summary_window"
    summaries = storage.db.run_sync(lambda c: repository.list_summaries(c, cid))
    assert len(summaries) >= 2 and [s.status for s in summaries].count("active") == 1
    assert len(llm.chat_requests) == 300


def test_any_other_runtime_request_makes_the_next_turn_cold(
    tmp_path: Path, storage: StorageHandle
) -> None:
    """A compaction (here: failing) replaces the runtime's cached prefix; the engine must not
    keep claiming the conversation is warm."""
    llm = ScriptedLLM(reply=long_reply, summary_fails=True)
    engine = make_engine(
        storage,
        llm,
        tmp_path,
        compact_at_tokens=1500,
        keep_recent_tokens=256,
        summary_max_tokens=400,
    )

    async def go() -> list[dict[str, object]]:
        cid: str | None = None
        for i in range(3):
            _, cid = await run_turn(engine, f"Not {i}", cid)
        assert cid is not None
        for _ in range(200):
            await asyncio.sleep(0.02)
            if len(llm.summary_requests) >= 2 and engine.scheduler.background is None:
                break
        events, _ = await run_turn(engine, "Devam", cid)
        await engine.close()
        return events

    events = asyncio.run(go())
    assert llm.summary_requests
    status = next(e for e in events if e.get("stage") == "processing_context")
    assert status["cache"] == "cold"


def test_compact_now_summarizes_on_demand_and_keeps_originals(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=long_reply)
    engine = make_engine(
        storage, llm, tmp_path, idle_compaction_delay_s=3600.0, keep_recent_tokens=256
    )

    async def go() -> str:
        cid: str | None = None
        for i in range(4):
            _, cid = await run_turn(engine, f"Önemli not {i}", cid)
        assert cid is not None
        assert await engine.compact_now(cid) is True
        await engine.close()
        return cid

    cid = asyncio.run(go())
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "summary_window"
    assert len(rows(storage, cid)) == 8


def test_compaction_progress_is_kept_per_chunk(tmp_path: Path, storage: StorageHandle) -> None:
    """If a later chunk fails (or is preempted), the chunks already summarized stay folded."""
    llm = ScriptedLLM(reply=long_reply, summary_fail_from=1)
    engine = make_engine(
        storage,
        llm,
        tmp_path,
        idle_compaction_delay_s=3600.0,
        keep_recent_tokens=256,
        compaction_chunk_tokens=1024,
    )

    async def go() -> str:
        cid: str | None = None
        for i in range(6):
            _, cid = await run_turn(engine, f"Önemli not {i}", cid)
        assert cid is not None
        with pytest.raises(LlmInvalidResponseError):
            await engine.compact_now(cid)
        await engine.close()
        return cid

    cid = asyncio.run(go())
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    summaries = storage.db.run_sync(lambda c: repository.list_summaries(c, cid))
    assert len(llm.summary_requests) >= 2 and len(summaries) == 1
    assert ctx is not None and ctx.strategy == "summary_window"
    assert ctx.window_start_seq == summaries[0].to_seq + 1
    first_window = rows(storage, cid)[ctx.window_start_seq - 1]
    assert first_window.role == "user"  # the window still starts at a user turn


def test_prewarm_records_the_runtime_size_even_without_a_context_row(
    tmp_path: Path, storage: StorageHandle
) -> None:
    now = utc_now_iso()

    def seed(conn: repository.Connection) -> str:
        with repository.transaction(conn):
            conv = repository.insert_conversation(
                conn, title="içe aktarılmış", model=MODEL, now=now
            )
            repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="user",
                content="Merhaba",
                status="complete",
                now=now,
            )
            repository.insert_message(
                conn,
                conversation_id=conv.id,
                role="assistant",
                content="Merhaba!",
                status="complete",
                now=now,
            )
        return conv.id

    cid = storage.db.run_sync(seed)
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        await engine.prepare(cid, MODEL)
        job = engine.scheduler.background
        assert job is not None and job.task is not None
        await job.task
        await engine.close()

    asyncio.run(go())
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.anchor_seq == 2
    assert ctx.anchor_tokens == prompt_tokens(llm.prewarm_requests[0])


def test_compaction_works_for_a_conversation_without_a_context_row(
    tmp_path: Path, storage: StorageHandle
) -> None:
    now = utc_now_iso()

    def seed(conn: repository.Connection) -> str:
        with repository.transaction(conn):
            conv = repository.insert_conversation(
                conn, title="içe aktarılmış", model=MODEL, now=now
            )
            for i in range(10):
                role = "user" if i % 2 == 0 else "assistant"
                repository.insert_message(
                    conn,
                    conversation_id=conv.id,
                    role=role,
                    content=f"Mesaj {i}: " + "ayrıntı " * 60,
                    status="complete",
                    now=now,
                )
        return conv.id

    cid = storage.db.run_sync(seed)
    llm = ScriptedLLM()
    engine = make_engine(storage, llm, tmp_path, keep_recent_tokens=256)

    async def go() -> bool:
        done = await engine.compact_now(cid)
        await engine.close()
        return done

    assert asyncio.run(go()) is True
    ctx = storage.db.run_sync(lambda c: repository.get_context(c, cid))
    assert ctx is not None and ctx.strategy == "summary_window"
