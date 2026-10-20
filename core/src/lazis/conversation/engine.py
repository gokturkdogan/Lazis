"""Conversation engine: persistent multi-turn chat with managed context (Phase 3).

Turn lifecycle (one turn at a time; the runtime has one slot):

1. ``begin_turn`` validates the request and stores the user message and an empty
   ``streaming`` assistant row in one transaction (a retried client id is refused).
2. A turn task assembles the context (compacting or, as a last resort, visibly trimming it
   when over budget), loads the model if needed and streams the reply. Partial text is
   persisted every ``flush_interval_s`` so a crash loses at most that much.
3. The reply row is closed exactly once as ``complete``, ``cancelled``, ``interrupted``
   (backend shutdown) or ``failed``; the runtime's token counts update the context anchor.
4. Replies still ``streaming`` at startup (crash) are marked ``interrupted``.

Privacy: message text is never logged or put into error messages; logs carry ids, counts and
durations only. Conversation history is not personal memory and nothing is learned from it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any

from lazis.config.model import Settings
from lazis.conversation import compaction, learning, repository
from lazis.conversation.context import (
    ASSISTANT_TEMPLATE_TOKENS,
    AssembledPrompt,
    Budget,
    TokenEstimator,
    assemble,
    derived_user_tokens,
    message_cost,
    trim_to_fit,
)
from lazis.conversation.models import (
    Channel,
    ContextState,
    Conversation,
    Message,
    MessageStatus,
    Summary,
    TokenSource,
)
from lazis.conversation.prompts import (
    PROMPT_VERSION,
    SUMMARY_INSTRUCTIONS,
    SUMMARY_PROMPT_VERSION,
    SUMMARY_SCHEMA,
    time_note,
)
from lazis.conversation.scheduler import BackgroundJob, CacheKey, InferenceScheduler
from lazis.errors import (
    ContextBuildError,
    ConversationNotFoundError,
    DatabaseBusyError,
    LazisError,
    LlmBusyError,
    LlmCancelledError,
    LlmError,
    LlmInvalidResponseError,
    LlmModelNotFoundError,
    LlmUnavailableError,
    MemoryModelUntrustedError,
    MessageTooLongError,
    SessionNotActiveError,
    StorageError,
    TurnDuplicateError,
)
from lazis.i18n import message_for
from lazis.ids import new_ulid, utc_now_iso
from lazis.memory import commands, extraction, importer, retrieval
from lazis.memory import repository as memory_repo
from lazis.memory.models import Candidate
from lazis.observability.logging import get_logger, log_event
from lazis.personality import CommunicationPreferences
from lazis.providers.llm.ports import (
    ChatMessage,
    ChatRequest,
    GenerationDone,
    GenerationMetrics,
    GenerationOptions,
    LLMProvider,
    TextDelta,
)
from lazis.storage.database import Database
from lazis.storage.driver import Connection, DatabaseError
from lazis.storage.repositories import write_audit

_log = get_logger("conversation")

Event = dict[str, Any]


@dataclass(frozen=True)
class TurnRequest:
    """``conversation_id`` None means "the active session" (created on the very first turn).
    A given id must be the active session; closed sessions never receive messages."""

    conversation_id: str | None
    client_id: str
    content: str
    model: str
    channel: Channel = "text"


@dataclass
class TurnHandle:
    conversation: Conversation
    user: Message
    assistant: Message
    created: bool
    request_id: str
    queue: asyncio.Queue[Event | None] = field(
        default_factory=lambda: asyncio.Queue[Event | None]()
    )
    task: asyncio.Task[None] | None = None
    stage: str = "queued"
    accepted_monotonic: float = field(default_factory=time.monotonic)
    active_request_id: str | None = None
    cancel_requested: bool = False
    shutdown: bool = False
    # Recall for this turn (ids and sizes only; the note itself is never stored).
    memory_ids: list[str] = field(default_factory=list[str])
    memory_note_floor: int = 0  # a lower bound of the note's tokens (see `_with_memory`)
    memory_ms: float | None = None
    # An explicit memory request in this message ("bunu unutma", "Ahmet'i unut"), if any.
    memory_intent: str | None = None
    memory_outcome: str | None = None
    memory_request_ms: float | None = None

    def check(self) -> None:
        if self.cancel_requested:
            raise LlmCancelledError("cancelled before generation")


# ----- views (plain JSON-ready dicts for the API layer) --------------------------------
def conversation_view(c: Conversation) -> dict[str, Any]:
    return {
        "id": c.id,
        "title": c.title,
        "title_source": c.title_source,
        "model": c.model,
        "status": c.status,
        "message_count": c.message_count,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
    }


def message_view(m: Message) -> dict[str, Any]:
    return {
        "id": m.id,
        "conversation_id": m.conversation_id,
        "seq": m.seq,
        "role": m.role,
        "content": m.content,
        "status": m.status,
        "client_id": m.client_id,
        "reply_to": m.reply_to,
        "model": m.model,
        "error_code": m.error_code,
        "created_at": m.created_at,
        "completed_at": m.completed_at,
        "timeline_seq": m.timeline_seq,
        "channel": m.channel,
        "metrics": None
        if m.role != "assistant" or m.status == "streaming"
        else {
            "ttft_ms": m.ttft_ms,
            "total_ms": m.total_ms,
            "prompt_tokens": m.prompt_tokens,
            "output_tokens": m.output_tokens,
        },
    }


def auto_title(text: str, limit: int) -> str:
    line = " ".join(text.split())
    if len(line) <= limit:
        return line
    cut = line[: limit - 1]
    space = cut.rfind(" ")
    if space >= limit // 2:
        cut = cut[:space]
    return cut.rstrip(" ,.;:") + "…"


def initial_context(conversation_id: str, budget: int, now: str) -> ContextState:
    return ContextState(
        conversation_id=conversation_id,
        context_version=1,
        prompt_version=PROMPT_VERSION,
        strategy="full",
        window_start_seq=1,
        summary_id=None,
        budget_tokens=budget,
        anchor_seq=None,
        anchor_tokens=None,
        prefix_hash=None,
        last_prompt_tokens=None,
        updated_at=now,
    )


@dataclass(frozen=True)
class Loaded:
    state: ContextState
    summary: Summary | None
    window: list[Message]


class ConversationEngine:
    def __init__(
        self,
        *,
        db: Database,
        get_llm: Callable[[], LLMProvider | None],
        settings: Settings,
        now_local: Callable[[], datetime] | None = None,
    ) -> None:
        self._db = db
        self._get_llm = get_llm
        self._cfg = settings.conversation
        self._models = settings.models
        self.num_ctx = settings.models.context_tokens(self._cfg.context_profile)
        self.preferences = CommunicationPreferences(
            verbosity=settings.personality.verbosity, humor=settings.personality.humor
        )
        self.budget = Budget.build(
            self.num_ctx,
            settings.models.max_output_tokens,
            self._cfg.safety_fraction,
            self._cfg.compact_at_tokens,
        )
        self.estimator = TokenEstimator(
            self._cfg.estimate_chars_per_token, self._cfg.estimate_overhead_tokens
        )
        self._now_local = now_local or (lambda: datetime.now().astimezone())
        self.scheduler = InferenceScheduler(self._cancel_runtime)
        self._turn: TurnHandle | None = None
        self._reserved = False
        self._pending: dict[str, float] = {}
        # Conversations whose last reply should be processed into the runtime's cache
        # (model to use), see the post-turn re-warm in `_run_due`.
        self._rewarm: dict[str, str] = {}
        # Conversations with queued memory jobs, processed after the re-warm (`_learn_now`).
        self._learn: set[str] = set()
        self._memory = settings.memory
        self.learner = learning.Learner(
            cfg=settings.memory,
            q=self._q,
            scheduler=self.scheduler,
            estimator=self.estimator,
            num_ctx=self.num_ctx,
            safety=self.budget.safety,
            options=self._options,
            keep_alive=settings.models.keep_alive,
        )
        self._focused: str | None = None
        self._wake = asyncio.Event()
        self._maintenance: asyncio.Task[None] | None = None
        self._started = False
        self._start_lock = asyncio.Lock()
        self._closing = False
        self.recovered_interrupted = 0
        # Diagnostics only: numbers and states, never message content.
        self.prewarm_status: dict[str, Any] = {"state": "idle"}
        self.last_turn: dict[str, Any] | None = None

    # ----- lifecycle -------------------------------------------------------------------
    async def ensure_started(self) -> None:
        if self._started:
            return
        async with self._start_lock:
            if self._started:
                return
            now = utc_now_iso()
            self.recovered_interrupted = await self._q(
                lambda c: repository.mark_streaming_interrupted(c, now)
            )
            if self.recovered_interrupted:
                log_event(
                    _log,
                    logging.WARNING,
                    "conversation.interrupted_replies_recovered",
                    count=self.recovered_interrupted,
                )

            def recover_jobs(conn: Connection) -> tuple[int, list[str]]:
                with repository.transaction(conn):
                    n = memory_repo.recover_running_jobs(conn, now)
                return n, memory_repo.conversations_with_jobs(conn, ("queued", "deferred"))

            recovered_jobs, waiting = await self._q(recover_jobs)
            if recovered_jobs:
                log_event(_log, logging.WARNING, "memory.jobs_recovered", count=recovered_jobs)
            for cid in waiting:
                self._learn.add(cid)
                self._pending.setdefault(cid, time.monotonic() + self._cfg.idle_compaction_delay_s)
            self._maintenance = asyncio.get_running_loop().create_task(
                self._maintain(), name="lazis-conversation-maintenance"
            )
            self._started = True

    async def close(self) -> None:
        self._closing = True
        turn = self._turn
        if turn is not None and turn.task is not None:
            turn.shutdown = True
            self._request_cancel(turn)
            try:
                await asyncio.wait_for(asyncio.shield(turn.task), timeout=5)
            except (TimeoutError, asyncio.CancelledError, Exception):
                turn.task.cancel()
        await self.scheduler.cancel_background()
        if self._maintenance is not None:
            self._maintenance.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._maintenance

    # ----- helpers ---------------------------------------------------------------------
    async def _q[T](self, fn: Callable[[Connection], T]) -> T:
        try:
            return await self._db.run(fn)
        except LazisError:
            raise
        except DatabaseError as exc:
            if repository.is_busy(exc):
                raise DatabaseBusyError("database busy") from None
            raise StorageError(f"database error ({exc.__class__.__name__})") from None

    def _llm(self) -> LLMProvider:
        llm = self._get_llm()
        if llm is None:
            raise LlmUnavailableError("no local inference provider configured")
        return llm

    def _cancel_runtime(self, request_id: str) -> bool:
        llm = self._get_llm()
        return bool(llm and llm.cancel(request_id))

    def _options(self, max_tokens: int, **kw: Any) -> GenerationOptions:
        return GenerationOptions(
            num_ctx=self.num_ctx,
            max_tokens=max_tokens,
            think=False,
            keep_alive=self._models.keep_alive,
            **kw,
        )

    async def _require_model(self, llm: LLMProvider, model: str) -> None:
        installed = {m.name for m in await llm.list_models()}
        if model not in installed:
            installed = {m.name for m in await llm.list_models(refresh=True)}
        if model not in installed:
            raise LlmModelNotFoundError("model is not installed locally")

    async def _load(self, conversation_id: str) -> Loaded:
        def read(conn: Connection) -> Loaded:
            state = repository.get_context(conn, conversation_id)
            if state is None:
                state = initial_context(conversation_id, self.budget.hard_limit, utc_now_iso())
            summary = repository.get_summary(conn, state.summary_id) if state.summary_id else None
            window = [
                m
                for m in repository.messages_between(conn, conversation_id, state.window_start_seq)
                if m.status != "streaming"
            ]
            return Loaded(state, summary, window)

        return await self._q(read)

    def _assemble(
        self, loaded: Loaded, model: str, extra: list[Message] | None = None
    ) -> AssembledPrompt:
        window = loaded.window + (extra or [])
        return assemble(
            state=loaded.state,
            summary=loaded.summary,
            window=window,
            model=model,
            num_ctx=self.num_ctx,
            estimator=self.estimator,
            preferences=self.preferences,
        )

    # ----- conversations ---------------------------------------------------------------
    async def list_conversations(
        self, *, limit: int, cursor: str | None = None
    ) -> tuple[list[Conversation], str | None]:
        await self.ensure_started()
        before: tuple[str, str] | None = None
        if cursor:
            updated, _, cid = cursor.partition("~")
            if not updated or not cid:
                raise ConversationNotFoundError("bad cursor")
            before = (updated, cid)
        items = await self._q(
            lambda c: repository.list_conversations(c, limit=limit + 1, before=before)
        )
        next_cursor = None
        if len(items) > limit:
            items = items[:limit]
            last = items[-1]
            next_cursor = f"{last.updated_at}~{last.id}"
        return items, next_cursor

    async def get_conversation(self, conversation_id: str) -> Conversation:
        await self.ensure_started()
        found = await self._q(lambda c: repository.get_conversation(c, conversation_id))
        if found is None:
            raise ConversationNotFoundError("conversation not found")
        return found

    async def context_info(self, conversation_id: str) -> dict[str, Any]:
        conv = await self.get_conversation(conversation_id)
        loaded = await self._load(conversation_id)
        built = self._assemble(loaded, conv.model)
        s = loaded.summary
        job = self.scheduler.background
        return {
            "strategy": loaded.state.strategy,
            "context_version": loaded.state.context_version,
            "window_start_seq": loaded.state.window_start_seq,
            "estimated_tokens": built.estimated_tokens,
            "anchored": built.anchored,
            "omitted": list(built.omitted) if built.omitted else None,
            "summary": None
            if s is None
            else {
                "version": s.version,
                "to_seq": s.to_seq,
                "kept_items": s.kept_items,
                "dropped_items": s.dropped_items,
                "created_at": s.created_at,
            },
            "num_ctx": self.num_ctx,
            "hard_limit": self.budget.hard_limit,
            "compact_at": self.budget.compact_at,
            "cache": "warm"
            if self.scheduler.holds(
                conv.model,
                self.num_ctx,
                conversation_id,
                built.prefix_hash,
                through_seq=loaded.window[-1].seq if loaded.window else 0,
            )
            else "cold",
            "background": None
            if job is None or job.conversation_id != conversation_id
            else job.kind,
        }

    async def messages(
        self, conversation_id: str, *, before_seq: int | None, limit: int
    ) -> tuple[list[Message], bool]:
        await self.get_conversation(conversation_id)
        rows = await self._q(
            lambda c: repository.page_messages(
                c, conversation_id, limit=limit + 1, before_seq=before_seq
            )
        )
        has_more = len(rows) > limit
        return (rows[1:] if has_more else rows), has_more

    async def delete(self, conversation_id: str) -> dict[str, int]:
        """Delete a conversation with its messages, context state and summaries.

        Stops a reply being generated for it first. Afterwards the WAL is checkpointed and
        truncated, and if the runtime's prompt cache held this conversation the model is
        unloaded so its cached text leaves the runtime's memory. Older encrypted backups
        still contain it until they rotate (documented; not something we can undo here).
        """
        await self.ensure_started()
        turn = self._turn
        if turn is not None and turn.conversation.id == conversation_id and turn.task is not None:
            self._request_cancel(turn)
            try:
                await asyncio.wait_for(asyncio.shield(turn.task), timeout=10)
            except (TimeoutError, asyncio.CancelledError):
                turn.task.cancel()
        job = self.scheduler.background
        if job is not None and job.conversation_id == conversation_id:
            await self.scheduler.cancel_background()

        def write(conn: Connection) -> tuple[int, int] | None:
            with repository.transaction(conn):
                removed = repository.delete_conversation(conn, conversation_id)
                if removed is not None:
                    write_audit(
                        conn,
                        category="conversation",
                        action="deleted",
                        outcome="success",
                        actor="user",
                        target_refs=[conversation_id],
                        details={"messages": removed[0], "summaries": removed[1]},
                    )
            if removed is not None:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return removed

        removed = await self._q(write)
        if removed is None:
            raise ConversationNotFoundError("conversation not found")
        self._pending.pop(conversation_id, None)
        if self._focused == conversation_id:
            self._focused = None
        cache = self.scheduler.cache
        if cache is not None and cache.conversation_id == conversation_id:
            self.scheduler.cache = None
            llm = self._get_llm()
            if llm is not None:
                try:
                    await llm.unload(cache.model)
                except LlmError:
                    log_event(_log, logging.WARNING, "conversation.unload_after_delete_failed")
        log_event(
            _log,
            logging.INFO,
            "conversation.deleted",
            conversation_id=conversation_id,
            messages=removed[0],
            summaries=removed[1],
        )
        return {"messages": removed[0], "summaries": removed[1]}

    # ----- the assistant: one timeline, hidden technical sessions (ADR-0011) -------------
    async def active_session(self) -> Conversation | None:
        await self.ensure_started()
        return await self._q(repository.get_active_session)

    async def assistant_state(self) -> dict[str, Any]:
        """What the single assistant view needs: the active session's context state and where
        it starts in the timeline (older messages are not in the model's context)."""
        session = await self.active_session()
        total, first = await self._q(
            lambda c: repository.timeline_stats(c, None if session is None else session.id)
        )
        return {
            "session": None if session is None else conversation_view(session),
            "context": None if session is None else await self.context_info(session.id),
            "timeline_messages": total,
            "active_from_timeline_seq": first,
        }

    async def timeline(
        self, *, before_timeline_seq: int | None, limit: int
    ) -> tuple[list[Message], bool]:
        await self.ensure_started()
        rows = await self._q(
            lambda c: repository.timeline_page(
                c, limit=limit + 1, before_timeline_seq=before_timeline_seq
            )
        )
        has_more = len(rows) > limit
        return (rows[1:] if has_more else rows), has_more

    async def start_new_session(self, model: str) -> Conversation:
        """Close the active session and open a new, empty one. Nothing calls this
        automatically in Phase 3: there is no technical need yet (ADR-0011 §3). The closed
        session stays in the timeline but is not in the new session's context; continuity
        across sessions is the job of the personal memory system (P6), not of copied
        summaries (their citations point into the old session)."""
        await self.ensure_started()
        if self.is_busy():
            raise LlmBusyError("a reply is being generated")
        now = utc_now_iso()

        def write(conn: Connection) -> Conversation:
            with repository.transaction(conn):
                repository.archive_active_session(conn)
                session = repository.insert_conversation(conn, title="LAZIS", model=model, now=now)
                repository.save_context(
                    conn, initial_context(session.id, self.budget.hard_limit, now)
                )
                return session

        session = await self._q(write)
        self._focused = session.id
        log_event(_log, logging.INFO, "session.started", session_id=session.id)
        return session

    async def reset_context(self, conversation_id: str) -> None:
        """Invalidate all summaries and send the full history again (rebuilt on demand)."""
        await self.get_conversation(conversation_id)
        if self._turn is not None and self._turn.conversation.id == conversation_id:
            raise LlmBusyError("a reply is being generated for this conversation")

        def write(conn: Connection) -> None:
            with repository.transaction(conn):
                repository.invalidate_summaries(conn, conversation_id)
                old = repository.get_context(conn, conversation_id)
                fresh = initial_context(conversation_id, self.budget.hard_limit, utc_now_iso())
                if old is not None:
                    fresh = replace(fresh, context_version=old.context_version + 1)
                repository.save_context(conn, fresh)

        await self._q(write)
        self._schedule_check(conversation_id, now=True)

    # ----- turns -----------------------------------------------------------------------
    @property
    def active_turn(self) -> TurnHandle | None:
        return self._turn

    def is_busy(self) -> bool:
        return self._turn is not None or self._reserved

    async def begin_turn(self, req: TurnRequest) -> TurnHandle:
        await self.ensure_started()
        if self.is_busy():
            raise LlmBusyError("another reply is being generated")
        self._reserved = True
        try:
            return await self._begin(req)
        finally:
            self._reserved = False

    async def _begin(self, req: TurnRequest) -> TurnHandle:
        llm = self._llm()
        content = req.content.strip()
        if self.estimator.message(content) > self.budget.hard_limit // 2:
            raise MessageTooLongError("message exceeds half of the context budget")
        await self._require_model(llm, req.model)
        now = utc_now_iso()
        note = time_note(self._now_local())
        title = auto_title(content, self._cfg.title_max_chars)
        budget = self.budget.hard_limit

        def write(conn: Connection) -> tuple[Conversation, Message, Message, bool]:
            with repository.transaction(conn):
                if repository.find_by_client_id(conn, req.client_id) is not None:
                    raise TurnDuplicateError("message already submitted")
                active = repository.get_active_session(conn)
                if req.conversation_id is not None and (
                    active is None or active.id != req.conversation_id
                ):
                    if repository.get_conversation(conn, req.conversation_id) is None:
                        raise ConversationNotFoundError("conversation not found")
                    raise SessionNotActiveError("only the active session receives messages")
                created = active is None
                if active is None:
                    conv = repository.insert_conversation(
                        conn, title=title, model=req.model, now=now
                    )
                else:
                    conv = active
                state = repository.get_context(conn, conv.id)
                if state is None:
                    repository.save_context(conn, initial_context(conv.id, budget, now))
                elif conv.model != req.model:
                    # Token anchors are runtime- (model-) specific.
                    repository.save_context(
                        conn,
                        replace(
                            state,
                            context_version=state.context_version + 1,
                            anchor_seq=None,
                            anchor_tokens=None,
                            prefix_hash=None,
                            updated_at=now,
                        ),
                    )
                if conv.model != req.model:
                    repository.set_conversation_model(conn, conv.id, req.model)
                user = repository.insert_message(
                    conn,
                    conversation_id=conv.id,
                    role="user",
                    content=content,
                    status="complete",
                    now=now,
                    context_note=note,
                    client_id=req.client_id,
                    model=req.model,
                    channel=req.channel,
                )
                learning.enqueue(
                    conn,
                    self._memory,
                    message_id=user.id,
                    conversation_id=conv.id,
                    model=req.model,
                    now=now,
                )
                assistant = repository.insert_message(
                    conn,
                    conversation_id=conv.id,
                    role="assistant",
                    content="",
                    status="streaming",
                    now=now,
                    reply_to=user.id,
                    model=req.model,
                )
                fresh = repository.get_conversation(conn, conv.id)
                assert fresh is not None
                return fresh, user, assistant, created

        conv, user, assistant, created = await self._q(write)
        handle = TurnHandle(conv, user, assistant, created, request_id=f"turn-{assistant.id}")
        self._turn = handle
        self._focused = conv.id
        self._pending.pop(conv.id, None)
        handle.task = asyncio.get_running_loop().create_task(
            self._run_turn(handle, llm), name="lazis-turn"
        )
        log_event(
            _log,
            logging.INFO,
            "turn.accepted",
            conversation_id=conv.id,
            seq=user.seq,
            created=created,
            model=req.model,
        )
        return handle

    async def events(self, handle: TurnHandle) -> AsyncIterator[Event]:
        """The turn's events for one HTTP stream. If the client goes away, the generation is
        cancelled (the partial reply is kept as ``cancelled``)."""
        finished = False
        try:
            while True:
                event = await handle.queue.get()
                if event is None:
                    finished = True
                    return
                yield event
        finally:
            if not finished and handle.task is not None and not handle.task.done():
                self._request_cancel(handle)

    def cancel_turn(self, client_id: str) -> bool:
        turn = self._turn
        if turn is None or turn.user.client_id != client_id:
            return False
        self._request_cancel(turn)
        return True

    def _request_cancel(self, turn: TurnHandle) -> None:
        turn.cancel_requested = True
        if turn.active_request_id is not None:
            self._cancel_runtime(turn.active_request_id)

    async def _emit(self, handle: TurnHandle, event: Event) -> None:
        await handle.queue.put(event)

    async def _stage(self, handle: TurnHandle, stage: str, **extra: Any) -> None:
        handle.stage = stage
        await self._emit(handle, {"type": "status", "stage": stage, **extra})

    async def _run_turn(self, handle: TurnHandle, llm: LLMProvider) -> None:
        conv, user, assistant = handle.conversation, handle.user, handle.assistant
        model = user.model or conv.model
        parts: list[str] = []
        flushed = 0
        last_flush = time.monotonic()
        metrics: GenerationMetrics | None = None
        built: AssembledPrompt | None = None
        loaded: Loaded | None = None
        sent_at: float | None = None
        first_at: float | None = None
        try:
            await self._emit(
                handle,
                {
                    "type": "start",
                    "conversation": conversation_view(conv),
                    "created": handle.created,
                    "user_message": message_view(user),
                    "assistant_message": message_view(assistant),
                },
            )

            def joins(job: BackgroundJob) -> bool:
                return job.conversation_id in (conv.id, None) and (
                    job.target is not None and job.target.model == model
                )

            await self._stage(handle, "waiting")
            async with self.scheduler.foreground(join=joins):
                handle.check()
                loaded = await self._load(conv.id)
                built = self._assemble(loaded, model)
                if built.estimated_tokens > self.budget.hard_limit:
                    loaded, built = await self._fit_for_turn(handle, llm, model, loaded, built)
                notice = await self._memory_request(handle, llm, model, loaded, built)
                handle.check()
                built = await self._with_memory(handle, loaded, built, notice)
                handle.check()
                if model not in {m.name for m in await llm.loaded_models()}:
                    await self._stage(handle, "loading_model", model=model)
                    await llm.load(model, num_ctx=self.num_ctx, keep_alive=self._models.keep_alive)
                handle.check()
                prior = [m.seq for m in loaded.window if m.seq < user.seq]
                warm = self.scheduler.holds(
                    model,
                    self.num_ctx,
                    conv.id,
                    built.prefix_hash,
                    through_seq=max(prior) if prior else 0,
                )
                await self._stage(
                    handle,
                    "processing_context",
                    context_tokens=built.estimated_tokens,
                    cache="warm" if warm else "cold",
                )
                handle.active_request_id = handle.request_id
                # Whatever the runtime cached before is replaced by this request; it becomes
                # this conversation's prefix only once the request completes (below).
                self.scheduler.cache = None
                request = ChatRequest(
                    model=model,
                    messages=built.messages,
                    options=self._options(self._models.max_output_tokens),
                    request_id=handle.request_id,
                )
                log_event(
                    _log,
                    logging.INFO,
                    "turn.started",
                    conversation_id=conv.id,
                    seq=user.seq,
                    estimated_tokens=built.estimated_tokens,
                    anchored=built.anchored,
                    cache_expected="warm" if warm else "cold",
                    context_version=loaded.state.context_version,
                )
                sent_at = time.monotonic()
                async for event in llm.stream(request):
                    if isinstance(event, TextDelta):
                        if event.kind != "content" or not event.text:
                            continue
                        if not parts:
                            handle.stage = "generating"
                            first_at = time.monotonic()
                        parts.append(event.text)
                        await self._emit(handle, {"type": "delta", "text": event.text})
                        size = sum(len(p) for p in parts)
                        now_m = time.monotonic()
                        if (
                            now_m - last_flush >= self._cfg.flush_interval_s
                            or size - flushed >= self._cfg.flush_chars
                        ):
                            text = "".join(parts)
                            await self._q(
                                lambda c, t=text: repository.update_partial(c, assistant.id, t)
                            )
                            flushed, last_flush = size, now_m
                    else:
                        metrics = event.metrics
                text = "".join(parts)
                if metrics is None:
                    raise LlmInvalidResponseError("stream ended without completion")
                if not text.strip():
                    raise LlmInvalidResponseError("empty reply")
                final = await self._complete(handle, loaded, built, text, metrics)
                # The runtime does not reuse the tokens it generated: the next request
                # re-processes the reply (measured with Gemma, PHASE_5_REPORT §G). The cache
                # holds the prompt only, up to the user message; the post-turn re-warm
                # (below) processes the reply in the background.
                self.scheduler.cache = CacheKey(
                    model, self.num_ctx, conv.id, built.prefix_hash, user.seq
                )
            await self._emit(
                handle,
                {
                    "type": "done",
                    "message": message_view(final),
                    "context": {
                        "estimated_tokens": built.estimated_tokens,
                        "prompt_tokens": metrics.prompt_tokens,
                        "strategy": loaded.state.strategy,
                    },
                },
            )
            log_event(
                _log,
                logging.INFO,
                "turn.completed",
                conversation_id=conv.id,
                seq=final.seq,
                prompt_tokens=metrics.prompt_tokens,
                estimated_tokens=built.estimated_tokens,
                output_tokens=metrics.output_tokens,
                ttft_ms=None if metrics.ttft_ms is None else round(metrics.ttft_ms, 1),
                total_ms=round(metrics.total_ms, 1),
            )
            self._rewarm[conv.id] = model
            self._learn.add(conv.id)
            self._schedule_check(conv.id, now=True)
        except LlmCancelledError:
            status: MessageStatus = "interrupted" if handle.shutdown else "cancelled"
            final = await self._close_reply(handle, status, "".join(parts), None)
            if built is not None and parts:
                self.scheduler.cache = CacheKey(
                    model, self.num_ctx, conv.id, built.prefix_hash, user.seq
                )
                if not handle.shutdown:
                    self._rewarm[conv.id] = model
            if not handle.shutdown:
                self._learn.add(conv.id)
                self._schedule_check(conv.id, now=True)
            await self._emit(
                handle,
                {"type": "cancelled", "message": None if final is None else message_view(final)},
            )
            log_event(_log, logging.INFO, f"turn.{status}", conversation_id=conv.id)
        except asyncio.CancelledError:
            await self._close_reply(handle, "interrupted", "".join(parts), "interrupted")
            raise
        except LazisError as exc:
            final = await self._close_reply(handle, "failed", "".join(parts), exc.code)
            await self._emit(
                handle,
                {
                    "type": "error",
                    "code": exc.code,
                    "message": message_for(exc.code),
                    "assistant_message": None if final is None else message_view(final),
                },
            )
            log_event(_log, logging.WARNING, "turn.failed", conversation_id=conv.id, code=exc.code)
            # The user message is stored; it can still be learned from (retried, delayed).
            self._learn.add(conv.id)
            self._schedule_check(conv.id)
        except Exception as exc:
            final = await self._close_reply(handle, "failed", "".join(parts), "internal_error")
            await self._emit(
                handle,
                {
                    "type": "error",
                    "code": "internal_error",
                    "message": message_for("internal_error"),
                    "assistant_message": None if final is None else message_view(final),
                },
            )
            _log.error(
                "turn.unexpected_error",
                extra={"lazis_fields": {"conversation_id": conv.id, "error": type(exc).__name__}},
            )
        finally:
            handle.active_request_id = None
            self._record_last_turn(handle, metrics, sent_at, first_at, len(parts) > 0)
            if self._turn is handle:
                self._turn = None
            await handle.queue.put(None)

    def _record_last_turn(
        self,
        handle: TurnHandle,
        metrics: GenerationMetrics | None,
        sent_at: float | None,
        first_at: float | None,
        produced: bool,
    ) -> None:
        """Numbers for the diagnostics panel. No content, ids only of the session."""
        now = time.monotonic()
        accepted = handle.accepted_monotonic

        def ms(a: float | None, b: float | None) -> float | None:
            return None if a is None or b is None else round((b - a) * 1000, 1)

        status = "completed" if metrics is not None and produced else "failed"
        if handle.cancel_requested:
            status = "cancelled"
        self.last_turn = {
            "at": utc_now_iso(),
            "outcome": status,
            "failed_stage": handle.stage if status == "failed" else None,
            "ttft_ms": ms(accepted, first_at),
            "total_ms": ms(accepted, now),
            "context_prep_ms": ms(accepted, sent_at),
            "runtime_ttft_ms": None
            if metrics is None or metrics.ttft_ms is None
            else round(metrics.ttft_ms, 1),
            "prompt_tokens": None if metrics is None else metrics.prompt_tokens,
            "output_tokens": None if metrics is None else metrics.output_tokens,
            "decode_tps": None
            if metrics is None or metrics.decode_tps is None
            else round(metrics.decode_tps, 1),
            "memory_items": len(handle.memory_ids),
            "memory_ms": handle.memory_ms,
            "memory_request": handle.memory_intent,
            "memory_outcome": handle.memory_outcome,
            "memory_request_ms": handle.memory_request_ms,
        }

    async def _with_memory(
        self, handle: TurnHandle, loaded: Loaded, built: AssembledPrompt, notice: str = ""
    ) -> AssembledPrompt:
        """Put the relevant memories (and the outcome of a memory request) in front of the new
        user message, for this request only. Recall is a local database read (milliseconds);
        it never blocks or fails a reply."""
        overview = handle.memory_intent == "recall"
        budget = self._memory.context_budget_tokens * (2 if overview else 1)
        if budget <= 0 and not notice:
            return built
        user = handle.user
        previous = next(
            (m.content for m in reversed(loaded.window) if m.role == "user" and m.seq < user.seq),
            "",
        )
        chars = int(budget * self.estimator.chars_per_token)
        started = time.monotonic()
        try:
            found = await self._q(
                lambda c: retrieval.recall(
                    c, user.content, previous=previous, budget_chars=chars, overview=overview
                )
            )
        except Exception as exc:
            log_event(_log, logging.WARNING, "memory.recall_failed", error=type(exc).__name__)
            found = retrieval.Recall()
        handle.memory_ms = round((time.monotonic() - started) * 1000, 1)
        note = "\n\n".join(x for x in (notice, retrieval.render(found)) if x)
        if not note or built.messages[-1].role != "user":
            return built
        cost = self.estimator.text(note) + 2
        if built.estimated_tokens + cost > self.budget.hard_limit:
            log_event(_log, logging.INFO, "memory.recall_skipped", reason="context_full")
            return built
        handle.memory_ids = found.memory_ids
        handle.memory_note_floor = (len(note) + 2) // 4
        last = built.messages[-1]
        return replace(
            built,
            messages=[*built.messages[:-1], ChatMessage("user", f"{note}\n\n{last.content}")],
            estimated_tokens=built.estimated_tokens + cost,
        )

    async def _memory_request(
        self,
        handle: TurnHandle,
        llm: LLMProvider,
        model: str,
        loaded: Loaded,
        built: AssembledPrompt,
    ) -> str:
        """An explicit memory request is carried out before the reply, so the reply can only
        claim what really happened (the HAFIZA İŞLEMİ notice). Ordinary messages stop at the
        cue check (no model call)."""
        user, conv = handle.user, handle.conversation
        pending = await self._q(lambda c: commands.pending_confirmation(c, conv.id))
        intent = commands.detect(user.content, pending_confirmation=pending is not None)
        if intent is None:
            return ""
        handle.memory_intent = intent
        if intent == "recall":
            return ""  # only a wider recall, no model call
        await self._stage(handle, "memory")
        started = time.monotonic()
        outcome: commands.Outcome | None
        if not learning.is_trusted(self._memory, model):
            outcome = commands.Outcome("untrusted_model")
        else:
            try:
                if intent == "confirm" and pending is not None:
                    outcome = await self._q(lambda c: commands.confirm(c, pending))
                elif intent == "decline" and pending is not None:
                    outcome = await self._q(lambda c: commands.decline(c, pending))
                else:
                    outcome = await self._run_memory_command(handle, llm, model, loaded, built)
            except LlmCancelledError:
                raise
            except LazisError as exc:
                log_event(_log, logging.WARNING, "memory.request_failed", code=exc.code)
                outcome = commands.Outcome("failed")
        handle.memory_request_ms = round((time.monotonic() - started) * 1000, 1)
        if outcome is None:  # the model judged it not to be a memory request
            handle.memory_outcome = "none"
            return ""
        handle.memory_outcome = outcome.kind
        if outcome.kind not in ("untrusted_model", "failed"):
            # Handled here: the background job must not process the same request again.
            await self._q(lambda c: commands.skip_job(c, user.id))
        log_event(
            _log,
            logging.INFO,
            "memory.request",
            conversation_id=conv.id,
            intent=intent,
            outcome=outcome.kind,
            duration_ms=handle.memory_request_ms,
            **outcome.counts,
        )
        return outcome.notice()

    async def _run_memory_command(
        self,
        handle: TurnHandle,
        llm: LLMProvider,
        model: str,
        loaded: Loaded,
        built: AssembledPrompt,
    ) -> commands.Outcome | None:
        user, conv = handle.user, handle.conversation
        # On the cached prefix (everything before this message), plus one instruction.
        rid = f"{handle.request_id}-memory"
        request = ChatRequest(
            model=model,
            messages=[
                *built.messages[:-1],
                ChatMessage("user", commands.instruction(user.content)),
            ],
            options=self._options(400, temperature=0.0, seed=7, response_format=commands.schema()),
            request_id=rid,
        )
        handle.active_request_id = rid
        raw = ""
        self.scheduler.cache = None
        try:
            async for event in llm.stream(request):
                if isinstance(event, TextDelta) and event.kind == "content":
                    raw += event.text
        finally:
            handle.active_request_id = None
        prior = [m.seq for m in loaded.window if m.seq < user.seq]
        self.scheduler.cache = CacheKey(
            model, self.num_ctx, conv.id, built.prefix_hash, max(prior) if prior else 0
        )
        cmd = commands.parse(raw)
        if cmd is None:
            raise LlmInvalidResponseError("memory request was not valid JSON")
        if cmd.action == "none":
            return None
        if cmd.action in ("remember", "correct"):
            return await self._q(
                lambda c: commands.apply_items(
                    c, cmd, message_id=user.id, message=user.content, conversation_id=conv.id
                )
            )
        recent = [m.id for m in loaded.window if m.role == "user" and m.seq < user.seq][-1:]
        return await self._q(
            lambda c: commands.forget(
                c, cmd, conversation_id=conv.id, recent_user_message_ids=recent
            )
        )

    async def _fit_for_turn(
        self,
        handle: TurnHandle,
        llm: LLMProvider,
        model: str,
        loaded: Loaded,
        built: AssembledPrompt,
    ) -> tuple[Loaded, AssembledPrompt]:
        """Over the hard limit: compact now (visible status); if that is impossible, drop the
        oldest verbatim messages and say so to the model and the user. Never silent."""
        await self._stage(handle, "compacting", context_tokens=built.estimated_tokens)
        try:
            await self._compact(
                handle.conversation.id,
                llm,
                model,
                check=handle.check,
                set_request=lambda rid: setattr(handle, "active_request_id", rid),
            )
        except LlmCancelledError:
            raise
        except LazisError as exc:
            log_event(
                _log,
                logging.WARNING,
                "compaction.failed",
                conversation_id=handle.conversation.id,
                code=exc.code,
                mode="sync",
            )
        handle.active_request_id = None
        loaded = await self._load(handle.conversation.id)
        built = self._assemble(loaded, model)
        if built.estimated_tokens <= self.budget.hard_limit:
            return loaded, built
        start = trim_to_fit(
            state=loaded.state,
            summary=loaded.summary,
            window=loaded.window,
            model=model,
            num_ctx=self.num_ctx,
            estimator=self.estimator,
            limit=self.budget.hard_limit,
            keep_last=1,
            preferences=self.preferences,
        )
        if start is None:
            raise ContextBuildError("the newest message does not fit the context")
        state = replace(
            loaded.state,
            context_version=loaded.state.context_version + 1,
            strategy="window_only",
            window_start_seq=start,
            anchor_seq=None,
            anchor_tokens=None,
            prefix_hash=None,
            updated_at=utc_now_iso(),
        )
        await self._q(lambda c: self._save_context_tx(c, state))
        loaded = await self._load(handle.conversation.id)
        built = self._assemble(loaded, model)
        await self._stage(
            handle,
            "context_trimmed",
            omitted=list(built.omitted) if built.omitted else None,
        )
        log_event(
            _log,
            logging.WARNING,
            "context.trimmed",
            conversation_id=handle.conversation.id,
            window_start_seq=start,
        )
        return loaded, built

    @staticmethod
    def _save_context_tx(conn: Connection, state: ContextState) -> None:
        with repository.transaction(conn):
            repository.save_context(conn, state)

    async def _complete(
        self,
        handle: TurnHandle,
        loaded: Loaded,
        built: AssembledPrompt,
        text: str,
        metrics: GenerationMetrics,
    ) -> Message:
        user, assistant = handle.user, handle.assistant
        prompt_tokens = metrics.prompt_tokens
        # What later prompts will contain of this one: without the memory note (it is not
        # stored). Subtracting a lower bound of its tokens keeps the anchor conservative.
        history_tokens = (
            None if prompt_tokens is None else max(prompt_tokens - handle.memory_note_floor, 1)
        )
        user_cost = None
        if history_tokens is not None:
            user_cost = derived_user_tokens(
                state=loaded.state,
                prompt_hash=built.prefix_hash,
                window=loaded.window,
                user_seq=user.seq,
                prompt_tokens=history_tokens,
                estimator=self.estimator,
            )
        reply_source: TokenSource
        if metrics.output_tokens is not None:
            reply_cost, reply_source = metrics.output_tokens + ASSISTANT_TEMPLATE_TOKENS, "runtime"
        else:
            reply_cost, reply_source = self.estimator.message(text), "estimate"
        now = utc_now_iso()

        def write(conn: Connection) -> Message:
            with repository.transaction(conn):
                repository.finalize_message(
                    conn,
                    assistant.id,
                    status="complete",
                    content=text,
                    now=now,
                    token_count=reply_cost,
                    token_source=reply_source,
                    prompt_tokens=prompt_tokens,
                    output_tokens=metrics.output_tokens,
                    ttft_ms=metrics.ttft_ms,
                    total_ms=metrics.total_ms,
                )
                if user_cost is not None:
                    repository.set_token_count(conn, user.id, user_cost, "runtime")
                else:
                    repository.set_token_count(
                        conn, user.id, message_cost(user, self.estimator), "estimate"
                    )
                current = repository.get_context(conn, user.conversation_id)
                if current is not None and current.context_version == loaded.state.context_version:
                    repository.save_context(
                        conn,
                        replace(
                            current,
                            anchor_seq=user.seq if prompt_tokens is not None else None,
                            anchor_tokens=history_tokens,
                            prefix_hash=built.prefix_hash,
                            last_prompt_tokens=prompt_tokens,
                            updated_at=now,
                        ),
                    )
                repository.touch_conversation(conn, user.conversation_id, now)
                if handle.memory_ids:
                    memory_repo.record_recall(conn, handle.memory_ids, now)
                final = repository.get_message(conn, assistant.id)
                assert final is not None
                return final

        return await self._q(write)

    async def _close_reply(
        self, handle: TurnHandle, status: MessageStatus, text: str, error_code: str | None
    ) -> Message | None:
        """Close the reply row once (cancelled / interrupted / failed). Never raises."""
        assistant = handle.assistant
        now = utc_now_iso()
        cost = self.estimator.message(text) if text.strip() else 0

        def write(conn: Connection) -> Message | None:
            with repository.transaction(conn):
                repository.finalize_message(
                    conn,
                    assistant.id,
                    status=status,
                    content=text,
                    now=now,
                    token_count=cost,
                    token_source="estimate",  # noqa: S106 - not a secret
                    error_code=error_code,
                )
                if handle.user.token_count is None:
                    repository.set_token_count(
                        conn,
                        handle.user.id,
                        message_cost(handle.user, self.estimator),
                        "estimate",
                    )
                repository.touch_conversation(conn, assistant.conversation_id, now)
            return repository.get_message(conn, assistant.id)

        try:
            return await self._q(write)
        except Exception:
            log_event(
                _log, logging.ERROR, "turn.close_failed", conversation_id=handle.conversation.id
            )
            return None

    # ----- compaction ------------------------------------------------------------------
    async def _compact(
        self,
        conversation_id: str,
        llm: LLMProvider,
        model: str,
        *,
        check: Callable[[], None],
        set_request: Callable[[str], None],
    ) -> bool:
        """Fold older messages into the summary. Returns False when there is nothing to do."""
        started = time.monotonic()
        loaded = await self._load(conversation_id)
        plan = compaction.plan_split(
            loaded.window,
            estimator=self.estimator,
            keep_recent_tokens=self._cfg.keep_recent_tokens,
            keep_recent_messages=self._cfg.keep_recent_messages,
        )
        if plan is None:
            return False
        tokens_before = self._assemble(loaded, model).estimated_tokens
        previous: dict[str, Any] | None = loaded.summary.content if loaded.summary else None
        overhead = self.estimator.message(SUMMARY_INSTRUCTIONS)
        prev_tokens = self.estimator.text(str(previous)) if previous else 0
        room = (
            self.num_ctx
            - self._cfg.summary_max_tokens
            - overhead
            - self.budget.safety
            - max(prev_tokens, self._cfg.summary_max_tokens)
        )
        # Small chunks, each persisted on its own: a turn that preempts the compaction loses
        # at most the chunk in flight, and the next attempt continues from there.
        chunks = compaction.chunk_messages(
            plan.to_compact,
            estimator=self.estimator,
            max_tokens=max(min(room, self._cfg.compaction_chunk_tokens), 1024),
        )
        summary: Summary | None = loaded.summary
        version = loaded.state.context_version
        kept = dropped = 0
        for index, chunk in enumerate(chunks):
            next_start = chunks[index + 1][0].seq if index + 1 < len(chunks) else plan.split_seq
            raw: dict[str, Any] | None = None
            for _attempt in range(2):
                check()
                rid = f"compact-{new_ulid()}"
                set_request(rid)
                request = ChatRequest(
                    model=model,
                    messages=compaction.build_messages(previous, chunk),
                    options=self._options(
                        self._cfg.summary_max_tokens,
                        temperature=0.1,
                        seed=7,
                        response_format=SUMMARY_SCHEMA,
                    ),
                    request_id=rid,
                )
                text = ""
                self.scheduler.cache = None  # the summary prompt replaces the cached prefix
                async for event in llm.stream(request):
                    if isinstance(event, TextDelta) and event.kind == "content":
                        text += event.text
                raw = compaction.parse_summary(text)
                if raw is not None:
                    break
            if raw is None:
                raise LlmInvalidResponseError("summary was not valid JSON")
            seqs = compaction.cited_seqs(raw)
            lookup = {
                m.seq: m
                for m in await self._q(
                    lambda c, s=seqs: repository.messages_by_seq(c, conversation_id, s)
                )
            }
            verified = compaction.verify_and_render(raw, lookup, from_seq=1, to_seq=next_start - 1)
            kept, dropped = verified.kept, dropped + verified.dropped
            previous = verified.content
            check()
            summary = await self._persist_summary(
                conversation_id,
                expected_version=version,
                previous=summary,
                content=verified.content,
                rendered=verified.rendered,
                to_seq=next_start - 1,
                window_start=next_start,
                kept=kept,
                dropped=dropped,
                model=model,
            )
            version += 1
        assert summary is not None
        after = self._assemble(await self._load(conversation_id), model).estimated_tokens
        log_event(
            _log,
            logging.INFO,
            "compaction.completed",
            conversation_id=conversation_id,
            summary_version=summary.version,
            to_seq=summary.to_seq,
            chunks=len(chunks),
            kept_items=kept,
            dropped_items=dropped,
            tokens_before=tokens_before,
            tokens_after=after,
            duration_ms=round((time.monotonic() - started) * 1000),
        )
        return True

    async def _persist_summary(
        self,
        conversation_id: str,
        *,
        expected_version: int,
        previous: Summary | None,
        content: dict[str, Any],
        rendered: str,
        to_seq: int,
        window_start: int,
        kept: int,
        dropped: int,
        model: str,
    ) -> Summary:
        now = utc_now_iso()

        def write(conn: Connection) -> Summary:
            with repository.transaction(conn):
                current = repository.get_context(conn, conversation_id)
                if current is None and expected_version == 1:
                    # No context row yet (e.g. an imported conversation): start one.
                    current = initial_context(conversation_id, self.budget.hard_limit, now)
                if current is None or current.context_version != expected_version:
                    raise LlmCancelledError("context changed during compaction")
                summary = repository.insert_summary(
                    conn,
                    conversation_id=conversation_id,
                    from_seq=1,
                    to_seq=to_seq,
                    previous_id=previous.id if previous else None,
                    content=content,
                    rendered=rendered,
                    token_count=self.estimator.text(rendered),
                    token_source="estimate",  # noqa: S106 - not a secret
                    model=model,
                    prompt_version=SUMMARY_PROMPT_VERSION,
                    kept_items=kept,
                    dropped_items=dropped,
                    now=now,
                )
                repository.save_context(
                    conn,
                    replace(
                        current,
                        context_version=current.context_version + 1,
                        strategy="summary_window",
                        window_start_seq=window_start,
                        summary_id=summary.id,
                        anchor_seq=None,
                        anchor_tokens=None,
                        prefix_hash=None,
                        updated_at=now,
                    ),
                )
                return summary

        return await self._q(write)

    async def compact_now(self, conversation_id: str) -> bool:
        """Compact a conversation immediately in the foreground slot (waits for it). Returns
        False when there is nothing old enough to summarize."""
        conv = await self.get_conversation(conversation_id)
        if self.is_busy():
            raise LlmBusyError("a reply is being generated")
        llm = self._llm()
        rid: dict[str, str] = {}
        async with self.scheduler.foreground():
            return await self._compact(
                conversation_id,
                llm,
                conv.model,
                check=lambda: None,
                set_request=lambda r: rid.update(id=r),
            )

    def _schedule_check(self, conversation_id: str, *, now: bool = False) -> None:
        delay = 0.0 if now else self._cfg.idle_compaction_delay_s
        self._pending[conversation_id] = time.monotonic() + delay
        self._wake.set()

    async def _needs_compaction(self, conversation_id: str) -> bool:
        try:
            conv = await self.get_conversation(conversation_id)
        except ConversationNotFoundError:
            return False
        built = self._assemble(await self._load(conversation_id), conv.model)
        return built.estimated_tokens >= self.budget.compact_at

    async def _maintain(self) -> None:
        while not self._closing:
            timeout: float | None = None
            if self._pending:
                timeout = max(0.05, min(self._pending.values()) - time.monotonic())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout)
            self._wake.clear()
            try:
                await self._run_due()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log_event(_log, logging.WARNING, "maintenance.error", error=type(exc).__name__)
                await asyncio.sleep(1)

    async def _run_due(self) -> None:
        now = time.monotonic()
        for conversation_id, due in sorted(self._pending.items(), key=lambda kv: kv[1]):
            if due > now:
                continue
            if self.is_busy() or self.scheduler.background is not None:
                self._pending[conversation_id] = now + 0.5
                continue
            if not await self._needs_compaction(conversation_id):
                self._pending.pop(conversation_id, None)
                rewarm_model = self._rewarm.pop(conversation_id, None)
                if rewarm_model is not None and self._cfg.prewarm:
                    # Process the reply now, while the user reads it, instead of at the start
                    # of the next turn (a turn sent meanwhile joins this pre-warm).
                    await self.prepare(conversation_id, rewarm_model)
                    await self._settle_background()
                if conversation_id in self._learn:
                    await self._learn_now(conversation_id)
                continue
            idle = self.scheduler.idle_for()
            if idle < self._cfg.idle_compaction_delay_s:
                self._pending[conversation_id] = now + (self._cfg.idle_compaction_delay_s - idle)
                continue
            llm = self._get_llm()
            if llm is None:
                self._pending[conversation_id] = now + 60.0
                continue
            conv = await self.get_conversation(conversation_id)

            async def work(
                job: BackgroundJob,
                cid: str = conversation_id,
                model: str = conv.model,
                provider: LLMProvider = llm,
            ) -> bool:
                def set_request(rid: str) -> None:
                    job.request_id = rid

                return await self._compact(
                    cid, provider, model, check=job.check, set_request=set_request
                )

            job = self.scheduler.start_background("compaction", conversation_id, work)
            if job is None or job.task is None:
                self._pending[conversation_id] = now + 2.0
                continue
            try:
                done = await asyncio.shield(job.task)
            except LazisError as exc:
                log_event(
                    _log,
                    logging.WARNING,
                    "compaction.failed",
                    conversation_id=conversation_id,
                    code=exc.code,
                    mode="idle",
                )
                self._pending[conversation_id] = time.monotonic() + 300.0
                continue
            if done:
                self._pending.pop(conversation_id, None)
                if self._focused == conversation_id and self._cfg.prewarm:
                    await self.prepare(conversation_id, conv.model)
                if conversation_id in self._learn:
                    self._pending[conversation_id] = time.monotonic()
            else:
                # Preempted by a turn (it re-schedules itself after the turn) or nothing to do.
                self._pending.pop(conversation_id, None)

    async def _settle_background(self) -> None:
        """Wait for the running background job (a turn may join or preempt it meanwhile)."""
        job = self.scheduler.background
        if job is not None and job.task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await asyncio.shield(job.task)

    # ----- learning ----------------------------------------------------------------------
    async def _learn_now(self, conversation_id: str) -> None:
        """Process this conversation's queued memory jobs in the background slot, on the
        prefix the re-warm just cached. Never waits for or delays a turn."""
        now = time.monotonic()
        if self.is_busy() or self.scheduler.background is not None:
            self._pending[conversation_id] = now + 0.5
            return
        llm = self._get_llm()
        if llm is None:
            self._pending[conversation_id] = now + 60.0
            return
        try:
            conv = await self.get_conversation(conversation_id)
        except ConversationNotFoundError:
            self._learn.discard(conversation_id)
            return
        model = conv.model
        if not learning.is_trusted(self._memory, model):
            # Deferred until a trusted model answers in this conversation again.
            self._learn.discard(conversation_id)
            return
        jobs = await self._q(lambda c: learning.pending(c, self._memory, conversation_id))
        if not jobs:
            self._learn.discard(conversation_id)
            return
        loaded = await self._load(conversation_id)
        targets = {j.user_message_id for j in jobs}
        recent = [m.content for m in loaded.window if m.role == "user" and m.id not in targets]
        prompt = learning.Prompt(
            self._assemble(loaded, model),
            loaded.window[-1].seq if loaded.window else 0,
            tuple(recent[-3:]),
        )

        async def work(job: BackgroundJob) -> bool:
            return await self.learner.run(
                job,
                llm=llm,
                model=model,
                conversation_id=conversation_id,
                jobs=jobs,
                prompt=prompt,
            )

        target = self.learner.target_key(model, conversation_id, prompt)
        started = self.scheduler.start_background("memory", conversation_id, work, target=target)
        if started is None or started.task is None:
            self._pending[conversation_id] = now + 0.5
            return
        ok = False
        with contextlib.suppress(asyncio.CancelledError, Exception):
            ok = await asyncio.shield(started.task)
        remaining = await self._q(lambda c: learning.pending(c, self._memory, conversation_id))
        if not remaining:
            self._learn.discard(conversation_id)
        elif ok:
            self._pending[conversation_id] = time.monotonic()  # the next batch
        elif self.learner.status.get("state") == "failed":
            self._pending[conversation_id] = time.monotonic() + 60.0
        else:  # preempted by a turn: that turn schedules the next attempt itself
            self._pending[conversation_id] = time.monotonic() + 2.0

    async def import_text_candidates(self, content: str) -> list[Candidate]:
        """Starting-profile import from plain text: the extraction model reads it in chunks
        (a user action: it takes the runtime slot like a turn). Only a trusted model."""
        await self.ensure_started()
        model = self._models.primary_model
        if model is None or not learning.is_trusted(self._memory, model):
            raise MemoryModelUntrustedError("text import needs a trusted model")
        llm = self._llm()
        await self._require_model(llm, model)
        out: list[Candidate] = []
        async with self.scheduler.foreground():
            if model not in {m.name for m in await llm.loaded_models()}:
                await llm.load(model, num_ctx=self.num_ctx, keep_alive=self._models.keep_alive)
            for i, chunk in enumerate(importer.chunk_text(content)):
                target = extraction.Target("m1", f"import-{i}", chunk)
                request = ChatRequest(
                    model=model,
                    messages=[
                        ChatMessage("system", learning.STANDALONE_SYSTEM),
                        ChatMessage("user", extraction.build_instruction([target])),
                    ],
                    options=self._options(
                        self._memory.extraction_max_tokens,
                        temperature=0.0,
                        seed=7,
                        response_format=learning.SCHEMA,
                    ),
                    request_id=f"import-{new_ulid()}",
                )
                self.scheduler.cache = None
                raw = ""
                async for event in llm.stream(request):
                    if isinstance(event, TextDelta) and event.kind == "content":
                        raw += event.text
                items = extraction.parse(raw)
                if items is None:
                    raise LlmInvalidResponseError("import extraction was not valid JSON")
                for e in extraction.validate(items, [target]).accepted:
                    out.append(replace(e.candidate, origin="imported", quote=None))
        return out

    # ----- pre-warming -----------------------------------------------------------------
    async def prepare(self, conversation_id: str | None, model: str) -> dict[str, Any]:
        """Warm the runtime's prompt cache for the conversation the user is looking at, so
        the first reply after opening it (or after a model unload) does not pay the full
        prefill. Returns at once; the work runs in the background slot."""
        await self.ensure_started()
        self._focused = conversation_id
        llm = self._get_llm()
        if llm is None:
            return {"state": "unavailable"}
        if not self._cfg.prewarm:
            return {"state": "disabled"}
        if self.is_busy():
            return {"state": "busy"}
        try:
            await self._require_model(llm, model)
            loaded_names = {m.name for m in await llm.loaded_models()}
        except LlmModelNotFoundError:
            return {"state": "model_missing"}
        except LlmError:
            return {"state": "unavailable"}
        if conversation_id is not None:
            conv = await self.get_conversation(conversation_id)
            loaded = await self._load(conv.id)
        else:
            now = utc_now_iso()
            loaded = Loaded(initial_context("new", self.budget.hard_limit, now), None, [])
        built = self._assemble(loaded, model)
        model_loaded = model in loaded_names
        info: dict[str, Any] = {
            "model_loaded": model_loaded,
            "context_tokens": built.estimated_tokens,
        }
        last_seq = loaded.window[-1].seq if loaded.window else 0
        if model_loaded and self.scheduler.holds(
            model, self.num_ctx, conversation_id, built.prefix_hash, through_seq=last_seq
        ):
            return {"state": "warm", **info}
        job = self.scheduler.background
        if job is not None:
            if job.kind == "prewarm" and job.conversation_id == conversation_id:
                return {"state": "warming", **info}
            if job.kind == "compaction" and job.conversation_id == conversation_id:
                return {"state": "compacting", **info}
            await self.scheduler.cancel_background()
        target = CacheKey(model, self.num_ctx, conversation_id, built.prefix_hash, last_seq)
        version = loaded.state.context_version

        scope = "context" if last_seq > 0 else "model_only"

        async def work(job: BackgroundJob) -> bool:
            try:
                return await warm(job)
            except LlmCancelledError:
                self.prewarm_status = {"state": "cancelled", "scope": scope, "at": utc_now_iso()}
                raise
            except LlmError as exc:
                self.prewarm_status = {
                    "state": "failed",
                    "scope": scope,
                    "code": exc.code,
                    "at": utc_now_iso(),
                }
                log_event(_log, logging.WARNING, "prewarm.failed", code=exc.code)
                return False

        async def warm(job: BackgroundJob) -> bool:
            started = time.monotonic()
            if model not in {m.name for m in await llm.loaded_models()}:
                job.check()
                await llm.load(model, num_ctx=self.num_ctx, keep_alive=self._models.keep_alive)
            job.check()
            request = ChatRequest(
                model=model,
                messages=built.messages,
                options=self._options(1),
                request_id=job.request_id,
            )
            self.scheduler.cache = None
            metrics: GenerationMetrics | None = None
            async for event in llm.stream(request):
                if isinstance(event, GenerationDone):
                    metrics = event.metrics
            self.scheduler.cache = target
            if conversation_id is not None and metrics is not None and metrics.prompt_tokens:
                tokens = metrics.prompt_tokens
                cid = conversation_id

                def write(conn: Connection) -> None:
                    with repository.transaction(conn):
                        current = repository.get_context(conn, cid)
                        if current is None and version == 1:
                            # A conversation without a context row yet (e.g. imported):
                            # start one, so the measured size is not lost.
                            current = initial_context(cid, self.budget.hard_limit, utc_now_iso())
                        if current is not None and current.context_version == version:
                            repository.save_context(
                                conn,
                                replace(
                                    current,
                                    anchor_seq=last_seq,
                                    anchor_tokens=tokens,
                                    prefix_hash=built.prefix_hash,
                                    updated_at=utc_now_iso(),
                                ),
                            )

                await self._q(write)
            duration = round((time.monotonic() - started) * 1000)
            self.prewarm_status = {
                "state": "done",
                "scope": scope,
                "at": utc_now_iso(),
                "duration_ms": duration,
                "prompt_tokens": None if metrics is None else metrics.prompt_tokens,
            }
            log_event(
                _log,
                logging.INFO,
                "prewarm.completed",
                conversation_id=conversation_id,
                scope=scope,
                prompt_tokens=None if metrics is None else metrics.prompt_tokens,
                duration_ms=duration,
            )
            return True

        started_job = self.scheduler.start_background(
            "prewarm", conversation_id, work, target=target
        )
        if started_job is not None:
            self.prewarm_status = {"state": "running", "scope": scope, "at": utc_now_iso()}
        return {"state": "warming" if started_job is not None else "busy", **info}

    async def diagnostics(self) -> dict[str, Any]:
        """Technical state for the diagnostics panel: model, runtime, last turn, pre-warm and
        cache. Contains no message text."""
        await self.ensure_started()
        llm = self._get_llm()
        runtime: dict[str, Any] = {
            "available": False,
            "version": None,
            "error_code": "llm_unavailable",
        }
        loaded_model: dict[str, Any] | None = None
        installed: list[str] = []
        if llm is not None:
            health = await llm.health()
            runtime = {
                "available": health.available,
                "version": health.version,
                "error_code": health.error_code,
            }
            if health.available:
                try:
                    installed = [m.name for m in await llm.list_models()]
                    loaded = await llm.loaded_models()
                    if loaded:
                        first = loaded[0]
                        loaded_model = {
                            "name": first.name,
                            "size_bytes": first.size_bytes,
                            "context_length": first.context_length,
                            "expires_at": first.expires_at,
                        }
                except LlmError as exc:
                    runtime["error_code"] = exc.code
        session = await self._q(repository.get_active_session)
        active_model = session.model if session is not None else self._models.primary_model
        cache_ok = False
        if session is not None and active_model is not None:
            built = self._assemble(await self._load(session.id), active_model)
            loaded_s = await self._load(session.id)
            built = self._assemble(loaded_s, active_model)
            cache_ok = self.scheduler.holds(
                active_model,
                self.num_ctx,
                session.id,
                built.prefix_hash,
                through_seq=loaded_s.window[-1].seq if loaded_s.window else 0,
            )
        job = self.scheduler.background

        def memory_counts(conn: Connection) -> dict[str, Any]:
            return {
                "jobs": memory_repo.job_counts(conn),
                "memories": memory_repo.count_memories(conn),
                "inbox_open": len(memory_repo.list_inbox(conn, status="open")),
            }

        memory = {
            "auto_extract": self._memory.auto_extract,
            "trusted_models": list(self._memory.trusted_models),
            "learning": self.learner.status,
            **(await self._q(memory_counts)),
        }
        return {
            "runtime": runtime,
            "model": {
                "primary": self._models.primary_model,
                "fallback": self._models.fallback_model,
                "active": active_model,
                "active_installed": active_model in installed if active_model else False,
                "fallback_installed": self._models.fallback_model in installed
                if self._models.fallback_model
                else False,
                "automatic_fallback": False,
                "loaded": loaded_model,
                "keep_alive": self._models.keep_alive,
                "num_ctx": self.num_ctx,
            },
            "last_turn": self.last_turn,
            "prewarm": self.prewarm_status,
            # True only while nothing else has used the runtime since the last request for
            # this session; the runtime itself cannot confirm it (no cache introspection).
            "cache_expected_warm": cache_ok,
            "background": None if job is None else job.kind,
            "turn_active": self._turn is not None,
            "memory": memory,
        }

    def activity(self) -> dict[str, Any]:
        turn = self._turn
        job = self.scheduler.background
        cache = self.scheduler.cache
        return {
            "turn": None
            if turn is None
            else {
                "conversation_id": turn.conversation.id,
                "client_id": turn.user.client_id,
                "stage": turn.stage,
            },
            "background": None
            if job is None
            else {"kind": job.kind, "conversation_id": job.conversation_id},
            "cached_conversation_id": None if cache is None else cache.conversation_id,
            "pending_compaction": sorted(self._pending),
        }
