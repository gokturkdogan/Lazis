"""One runtime slot, shared by every LAZIS inference request.

The local runtime keeps one cached prompt prefix per loaded model and runs one request at a
time. All of LAZIS's model traffic (turns, pre-warming, compaction, the Phase 2 preview
chat) goes through this scheduler, which also lets it know which conversation the runtime's
cache currently holds.

* Foreground work (a user turn) always wins: a running background job is cancelled — unless
  it is pre-warming exactly the prefix the turn needs, in which case the turn waits for it
  (the prefill is not wasted, it is the turn's own).
* Background work never queues behind the foreground; it is skipped and retried later.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Literal

from lazis.errors import LlmCancelledError
from lazis.ids import new_ulid

JobKind = Literal["prewarm", "compaction"]


@dataclass(frozen=True)
class CacheKey:
    """What the runtime's prompt cache holds after the last LAZIS request."""

    model: str
    num_ctx: int
    conversation_id: str | None
    prefix_hash: str
    last_seq: int


@dataclass
class BackgroundJob:
    kind: JobKind
    conversation_id: str | None
    request_id: str
    target: CacheKey | None
    started_monotonic: float
    cancelled: bool = False
    task: asyncio.Task[bool] | None = None

    def check(self) -> None:
        """Called by the work before each runtime call: a cancel can arrive before the
        stream exists, when the provider has nothing to cancel yet."""
        if self.cancelled:
            raise LlmCancelledError("background job preempted")


class InferenceScheduler:
    def __init__(self, cancel: Callable[[str], bool]) -> None:
        self._cancel = cancel
        self._lock = asyncio.Lock()
        self._background: BackgroundJob | None = None
        self._foreground_waiting = 0
        self.cache: CacheKey | None = None
        self.last_foreground_monotonic = 0.0
        self.foreground_active = False

    # ----- state -----------------------------------------------------------------------
    @property
    def background(self) -> BackgroundJob | None:
        return self._background

    def idle_for(self) -> float:
        if self.foreground_active:
            return 0.0
        return time.monotonic() - self.last_foreground_monotonic

    def holds(
        self,
        model: str,
        num_ctx: int,
        conversation_id: str | None,
        prefix: str,
        *,
        through_seq: int | None = None,
    ) -> bool:
        """True if the runtime's cache should hold this conversation's current prefix (the
        history only grows within one prefix, so the cached part is reusable) — and, when
        ``through_seq`` is given, every message up to that one."""
        c = self.cache
        # A pre-warm of an empty session (system prompt only) measurably did not speed up
        # the first turn (PHASE_3_REPORT §13.D): never report that as a warm conversation.
        return (
            c is not None
            and c.last_seq > 0
            and c.model == model
            and c.num_ctx == num_ctx
            and c.conversation_id == conversation_id
            and c.prefix_hash == prefix
            and (through_seq is None or c.last_seq >= through_seq)
        )

    # ----- foreground ------------------------------------------------------------------
    @asynccontextmanager
    async def foreground(
        self, *, join: Callable[[BackgroundJob], bool] | None = None
    ) -> AsyncGenerator[bool]:
        """Acquire the slot for a user turn. A running pre-warm accepted by ``join`` is awaited
        (its prefill is the turn's own); any other background job is preempted. Yields True
        if it waited for a pre-warm."""
        self._foreground_waiting += 1
        joined = False
        try:
            job = self._background
            if job is not None:
                if job.kind == "prewarm" and join is not None and join(job):
                    joined = True
                    if job.task is not None:
                        await asyncio.shield(job.task)
                else:
                    self._preempt(job)
            await self._lock.acquire()
        finally:
            self._foreground_waiting -= 1
        self.foreground_active = True
        try:
            yield joined
        finally:
            self.foreground_active = False
            self.last_foreground_monotonic = time.monotonic()
            self._lock.release()

    # ----- background ------------------------------------------------------------------
    def start_background(
        self,
        kind: JobKind,
        conversation_id: str | None,
        work: Callable[[BackgroundJob], Awaitable[bool]],
        *,
        target: CacheKey | None = None,
    ) -> BackgroundJob | None:
        """Run ``work(job)`` in the slot if it is free right now; else return None."""
        if self._lock.locked() or self._foreground_waiting or self._background is not None:
            return None
        job = BackgroundJob(kind, conversation_id, f"bg-{new_ulid()}", target, time.monotonic())

        async def runner() -> bool:
            async with self._lock:
                try:
                    job.check()
                    return await work(job)
                except LlmCancelledError:
                    return False
                finally:
                    self._background = None

        self._background = job
        job.task = asyncio.get_running_loop().create_task(runner(), name=f"lazis-{kind}")
        return job

    def _preempt(self, job: BackgroundJob) -> None:
        job.cancelled = True
        self._cancel(job.request_id)

    async def cancel_background(self) -> None:
        job = self._background
        if job is None:
            return
        self._preempt(job)
        if job.task is None:
            return
        try:
            await asyncio.wait_for(asyncio.shield(job.task), timeout=5)
        except (TimeoutError, asyncio.CancelledError, Exception):
            job.task.cancel()
