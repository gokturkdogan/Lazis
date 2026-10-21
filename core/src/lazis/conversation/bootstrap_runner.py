"""The model side of a Markdown/text profile import (Phase 8, ADR-0019).

One task per import walks its pending sections; each section is one model call, run as a
background job in the shared runtime slot (``kind="import"``): a user turn preempts it (the
section stays pending and is tried again), so chatting never waits behind an import. The model
is the primary trusted one (Gemma; ADR-0015) on the standalone system prompt — no
conversation is in the prompt. A section whose answer is not valid JSON is recorded as failed
(the user can retry it explicitly). Cancelling stops the current call and deletes the draft.
After the last section the proposals are assembled and analysed (:mod:`lazis.bootstrap`).

Nothing here writes memory: analysis only fills the import's draft.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING

from lazis.bootstrap import extract, pipeline, store
from lazis.conversation import learning
from lazis.errors import LazisError, LlmCancelledError
from lazis.observability.logging import get_logger, log_event
from lazis.providers.llm.ports import ChatMessage, ChatRequest, GenerationDone, TextDelta

if TYPE_CHECKING:
    from lazis.conversation.engine import ConversationEngine

_log = get_logger("lazis.bootstrap")
SLOT_WAIT_S = 0.5
# A profile section is denser than a chat turn: every line can be a fact (~60 output tokens
# each). Learning's budget would cut a dense section off mid-JSON.
IMPORT_MAX_TOKENS = 2048


class BootstrapRunner:
    def __init__(self, engine: ConversationEngine) -> None:
        self._engine = engine
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancelled: set[str] = set()
        self._current: dict[str, str] = {}  # import id → the running request id

    def model(self) -> str | None:
        """The model an import may use: the primary one, and only if it is trusted to learn."""
        eng = self._engine
        model = eng._models.primary_model  # pyright: ignore[reportPrivateUsage]
        if model is None or not learning.is_trusted(eng._memory, model):  # pyright: ignore[reportPrivateUsage]
            return None
        return model

    def running_ids(self) -> frozenset[str]:
        return frozenset(i for i in self._tasks if self.running(i))

    def running(self, import_id: str) -> bool:
        t = self._tasks.get(import_id)
        return t is not None and not t.done()

    def start(self, import_id: str) -> None:
        if self.running(import_id):
            return
        self._cancelled.discard(import_id)
        self._tasks[import_id] = asyncio.get_running_loop().create_task(
            self._run(import_id), name=f"lazis-import-{import_id[-6:]}"
        )

    async def cancel(self, import_id: str) -> None:
        """Stop the analysis now: the current model call is cancelled, the draft deleted."""
        self._cancelled.add(import_id)
        rid = self._current.get(import_id)
        job = self._engine.scheduler.background
        if rid is not None and job is not None and job.request_id == rid:
            await self._engine.scheduler.cancel_background()
        t = self._tasks.get(import_id)
        if t is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.wait_for(asyncio.shield(t), timeout=10)
        await self._engine._q(lambda c: _cancel_draft(c, import_id))  # pyright: ignore[reportPrivateUsage]

    async def close(self) -> None:
        for iid in list(self._tasks):
            if self.running(iid):
                self._cancelled.add(iid)
                self._tasks[iid].cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._tasks[iid]

    async def _run(self, import_id: str) -> None:
        eng = self._engine
        q = eng._q  # pyright: ignore[reportPrivateUsage]
        model = self.model()
        if model is None:
            await q(lambda c: store.set_status(c, import_id, "failed", error="untrusted_model"))
            return
        try:
            while import_id not in self._cancelled:
                pending = await q(lambda c: store.sections(c, import_id))
                if not pending:
                    break
                section = pending[0]
                outcome = await self._one(import_id, model, section)
                if outcome == "busy":
                    await asyncio.sleep(SLOT_WAIT_S)
            if import_id in self._cancelled:
                return
            b = await q(lambda c: store.get_batch(c, import_id))
            if b.sections_done == 0:
                await q(lambda c: store.set_status(c, import_id, "failed", error="no_section_read"))
                return
            await q(lambda c: pipeline.finish_text(c, import_id))
            log_event(_log, logging.INFO, "bootstrap.analyzed", sections=b.sections_total,
                      failed=b.sections_failed, calls=b.model_calls)  # fmt: skip
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log_event(_log, logging.WARNING, "bootstrap.analysis_failed", error=type(exc).__name__)
            with contextlib.suppress(Exception):
                await q(lambda c: store.set_status(c, import_id, "failed", error="internal_error"))

    async def _one(self, import_id: str, model: str, section: object) -> str:
        """'done' | 'failed' | 'split' (read again in halves) | 'busy' (the slot is taken: try
        again) | 'preempted'."""
        eng = self._engine
        q = eng._q  # pyright: ignore[reportPrivateUsage]
        from lazis.bootstrap.files import Section

        assert isinstance(section, Section)
        result: dict[str, str] = {}

        async def work(job: object) -> bool:
            from lazis.conversation.scheduler import BackgroundJob

            assert isinstance(job, BackgroundJob)
            llm = eng._llm()  # pyright: ignore[reportPrivateUsage]
            await eng._require_model(llm, model)  # pyright: ignore[reportPrivateUsage]
            job.check()
            if model not in {m.name for m in await llm.loaded_models()}:
                await llm.load(model, num_ctx=eng.num_ctx, keep_alive=eng._models.keep_alive)  # pyright: ignore[reportPrivateUsage]
            job.check()
            request = ChatRequest(
                model=model,
                messages=[ChatMessage("system", learning.STANDALONE_SYSTEM),
                          ChatMessage("user", extract.instruction(section))],
                options=eng._options(max(eng._memory.extraction_max_tokens, IMPORT_MAX_TOKENS),  # pyright: ignore[reportPrivateUsage]
                                     temperature=0.0, seed=7, response_format=learning.SCHEMA),
                request_id=job.request_id,
            )  # fmt: skip
            self._current[import_id] = job.request_id
            eng.scheduler.cache = None
            raw = ""
            async for event in llm.stream(request):
                if isinstance(event, TextDelta) and event.kind == "content":
                    raw += event.text
                elif isinstance(event, GenerationDone) and event.metrics.done_reason == "length":
                    result["cut"] = "1"  # stopped at the output limit: the answer is not whole
            result["raw"] = raw
            return True

        job = eng.scheduler.start_background("import", None, work)
        if job is None:
            return "busy"
        try:
            assert job.task is not None
            ok = await job.task
        except LlmCancelledError:
            ok = False
        except LazisError:
            ok = False
            result["error"] = "llm"
        finally:
            self._current.pop(import_id, None)
        if import_id in self._cancelled:
            return "preempted"
        if not ok and "error" not in result:
            return "preempted"  # a user turn took the slot: the section stays pending
        raw = result.get("raw")
        whole = "cut" not in result
        valid = whole and raw is not None and extract.validate(raw, section) is not None
        # Never a partial answer counted as read: the section is read again in two halves.
        if (
            not valid
            and "error" not in result
            and await q(lambda c: store.split_section(c, import_id, section.idx))
        ):
            return "split"
        await q(lambda c: store.record_section(c, import_id, section.idx, raw if valid else None))
        return "done" if valid else "failed"


def _cancel_draft(conn: object, import_id: str) -> None:
    from lazis.storage.driver import Connection

    assert isinstance(conn, Connection)
    if store.set_status(conn, import_id, "cancelled", only_from=("analyzing", "ready", "failed")):
        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("DELETE FROM import_items WHERE import_id = ?", (import_id,))
            conn.execute("DELETE FROM import_people WHERE import_id = ?", (import_id,))
            store.forget_text(conn, import_id)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
