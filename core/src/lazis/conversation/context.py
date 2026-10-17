"""Prompt assembly and token budgeting (ARCHITECTURE §6). Pure functions, no I/O.

Layout of every request for a conversation::

    [system] S0 policy · S1 persona · (S2 tools: none) · (S3 profile: none)
             · conversation summary (changes only on compaction) · omitted-range note
    [H]      verbatim messages from ``window_start_seq`` on (user turns carry their stored
             time note; partial replies carry a marker)
    [N]      the new user message

Within one ``context_version`` the history is append-only, so the runtime can reuse its
cached prefix. Token budgets start from the runtime's own count of the last prompt
(``anchor_tokens``) and estimate only what was added since; without an anchor the whole
prompt is estimated conservatively.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass

from lazis.conversation.models import CONTEXT_STATUSES, ContextState, Message, Summary
from lazis.conversation.prompts import (
    CANCELLED_MARKER,
    INTERRUPTED_MARKER,
    PROMPT_VERSION,
    S0_POLICY,
    S1_PERSONA,
    omitted_note,
)
from lazis.providers.llm.ports import ChatMessage

# Template tokens around one runtime-counted assistant reply (end-of-turn markers).
ASSISTANT_TEMPLATE_TOKENS = 4


@dataclass(frozen=True)
class TokenEstimator:
    """Conservative estimate for text the runtime has not counted yet."""

    chars_per_token: float = 2.2
    overhead_tokens: int = 8

    def text(self, text: str) -> int:
        return math.ceil(len(text) / self.chars_per_token)

    def message(self, text: str) -> int:
        return self.text(text) + self.overhead_tokens


@dataclass(frozen=True)
class Budget:
    num_ctx: int
    reserve_output: int
    safety: int
    compact_at: int

    @property
    def hard_limit(self) -> int:
        """Largest prompt (tokens) that still leaves room for the reply and the margin."""
        return self.num_ctx - self.reserve_output - self.safety

    @staticmethod
    def build(num_ctx: int, reserve_output: int, safety_fraction: float, compact_at: int) -> Budget:
        safety = math.ceil(num_ctx * safety_fraction)
        hard = num_ctx - reserve_output - safety
        return Budget(num_ctx, reserve_output, safety, min(compact_at, hard))


@dataclass(frozen=True)
class AssembledPrompt:
    messages: list[ChatMessage]
    system_text: str
    prefix_hash: str
    estimated_tokens: int
    anchored: bool
    included_seqs: tuple[int, ...]
    omitted: tuple[int, int] | None


def render_message(message: Message) -> ChatMessage | None:
    """The exact text a stored message contributes to later prompts (None = left out)."""
    if message.role == "user":
        text = (
            f"{message.context_note}\n{message.content}"
            if message.context_note
            else message.content
        )
        return ChatMessage("user", text)
    if message.role != "assistant" or message.status not in CONTEXT_STATUSES:
        return None
    if not message.content.strip():
        return None
    if message.status == "cancelled":
        return ChatMessage("assistant", f"{message.content}\n\n{CANCELLED_MARKER}")
    if message.status == "interrupted":
        return ChatMessage("assistant", f"{message.content}\n\n{INTERRUPTED_MARKER}")
    return ChatMessage("assistant", message.content)


def message_cost(message: Message, estimator: TokenEstimator) -> int:
    """Context cost of a message in tokens (0 when it is left out of the prompt)."""
    rendered = render_message(message)
    if rendered is None:
        return 0
    if message.token_count is not None:
        return message.token_count
    return estimator.message(rendered.content)


def omitted_range(state: ContextState, summary: Summary | None) -> tuple[int, int] | None:
    """Messages before the window that no summary covers (only after a fallback trim)."""
    covered = summary.to_seq if summary is not None else 0
    start, end = covered + 1, state.window_start_seq - 1
    return (start, end) if end >= start else None


def system_text(summary: Summary | None, omitted: tuple[int, int] | None) -> str:
    parts = [S0_POLICY, S1_PERSONA]
    if summary is not None:
        parts.append(summary.rendered)
    if omitted is not None:
        parts.append(omitted_note(*omitted))
    return "\n\n".join(parts)


def prefix_hash(model: str, num_ctx: int, system: str) -> str:
    digest = hashlib.sha256(f"{PROMPT_VERSION}\x00{model}\x00{num_ctx}\x00{system}".encode())
    return digest.hexdigest()


def assemble(
    *,
    state: ContextState,
    summary: Summary | None,
    window: Sequence[Message],
    model: str,
    num_ctx: int,
    estimator: TokenEstimator,
) -> AssembledPrompt:
    """Build the request messages for ``window`` (messages with seq ≥ window_start_seq, in
    order, already including the new user message and excluding the reply being generated).
    """
    omitted = omitted_range(state, summary)
    system = system_text(summary, omitted)
    phash = prefix_hash(model, num_ctx, system)
    chat = [ChatMessage("system", system)]
    included: list[int] = []
    for message in window:
        if message.seq < state.window_start_seq:
            continue
        rendered = render_message(message)
        if rendered is not None:
            chat.append(rendered)
            included.append(message.seq)

    anchored = (
        state.anchor_seq is not None
        and state.anchor_tokens is not None
        and state.prefix_hash == phash
        and state.anchor_seq >= state.window_start_seq - 1
    )
    if anchored:
        assert state.anchor_seq is not None and state.anchor_tokens is not None
        anchor_seq = state.anchor_seq
        estimated = state.anchor_tokens + sum(
            message_cost(m, estimator) for m in window if m.seq > anchor_seq
        )
    else:
        estimated = estimator.message(system) + sum(
            message_cost(m, estimator) for m in window if m.seq >= state.window_start_seq
        )
    return AssembledPrompt(
        messages=chat,
        system_text=system,
        prefix_hash=phash,
        estimated_tokens=estimated,
        anchored=anchored,
        included_seqs=tuple(included),
        omitted=omitted,
    )


def derived_user_tokens(
    *,
    state: ContextState,
    prompt_hash: str,
    window: Sequence[Message],
    user_seq: int,
    prompt_tokens: int,
    estimator: TokenEstimator,
) -> int | None:
    """Runtime-derived cost of the user message ``user_seq``: the measured prompt minus the
    anchored part and everything between. None when no valid anchor exists."""
    if (
        state.anchor_seq is None
        or state.anchor_tokens is None
        or state.prefix_hash != prompt_hash
        or state.anchor_seq >= user_seq
        or state.anchor_seq < state.window_start_seq - 1
    ):
        return None
    between = sum(message_cost(m, estimator) for m in window if state.anchor_seq < m.seq < user_seq)
    derived = prompt_tokens - state.anchor_tokens - between
    return derived if derived > 0 else None


def trim_to_fit(
    *,
    state: ContextState,
    summary: Summary | None,
    window: Sequence[Message],
    model: str,
    num_ctx: int,
    estimator: TokenEstimator,
    limit: int,
    keep_last: int,
) -> int | None:
    """Fallback when compaction is impossible: the smallest ``window_start_seq`` (dropping
    the oldest verbatim messages, never the last ``keep_last``) whose prompt fits ``limit``.
    The dropped range is announced to the model by the omitted-range note. None if even the
    last ``keep_last`` messages do not fit."""
    candidates = [m.seq for m in window if m.role == "user" and m.seq >= state.window_start_seq]
    protected: Sequence[Message] = window[-keep_last:] if keep_last > 0 else ()
    floor = protected[0].seq if protected else window[-1].seq
    for start in candidates:
        if start > floor:
            break
        trial = ContextState(
            conversation_id=state.conversation_id,
            context_version=state.context_version,
            prompt_version=state.prompt_version,
            strategy="window_only",
            window_start_seq=start,
            summary_id=state.summary_id,
            budget_tokens=state.budget_tokens,
            anchor_seq=None,
            anchor_tokens=None,
            prefix_hash=None,
            last_prompt_tokens=None,
            updated_at=state.updated_at,
        )
        built = assemble(
            state=trial,
            summary=summary,
            window=window,
            model=model,
            num_ctx=num_ctx,
            estimator=estimator,
        )
        if built.estimated_tokens <= limit:
            return start
    return None
