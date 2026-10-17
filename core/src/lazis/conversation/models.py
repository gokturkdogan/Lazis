"""Conversation domain records (persistent chat history, not personal memory)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Role = Literal["user", "assistant", "system"]
MessageStatus = Literal["complete", "streaming", "cancelled", "interrupted", "failed"]
TokenSource = Literal["runtime", "estimate"]
Strategy = Literal["full", "summary_window", "window_only"]
SummaryStatus = Literal["active", "superseded", "invalidated"]


@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    title_source: Literal["auto", "user"]
    model: str
    status: Literal["active", "archived"]
    message_count: int
    last_seq: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Message:
    id: str
    conversation_id: str
    seq: int
    role: Role
    content: str
    context_note: str | None
    status: MessageStatus
    client_id: str | None
    reply_to: str | None
    model: str | None
    token_count: int | None
    token_source: TokenSource | None
    prompt_tokens: int | None
    output_tokens: int | None
    ttft_ms: float | None
    total_ms: float | None
    error_code: str | None
    created_at: str
    completed_at: str | None


@dataclass(frozen=True)
class ContextState:
    """How a conversation is currently presented to the model.

    * ``window_start_seq`` — first message sent verbatim; everything before it is covered by
      ``summary_id`` (``summary_window``) or explicitly left out (``window_only``).
    * ``anchor_seq`` / ``anchor_tokens`` — runtime-measured size of the prompt up to and
      including message ``anchor_seq`` for the current ``context_version``; budgets for the
      next turn add only what came after it.
    """

    conversation_id: str
    context_version: int
    prompt_version: str
    strategy: Strategy
    window_start_seq: int
    summary_id: str | None
    budget_tokens: int
    anchor_seq: int | None
    anchor_tokens: int | None
    prefix_hash: str | None
    last_prompt_tokens: int | None
    updated_at: str


@dataclass(frozen=True)
class Summary:
    id: str
    conversation_id: str
    version: int
    from_seq: int
    to_seq: int
    previous_id: str | None
    status: SummaryStatus
    content: dict[str, Any]
    rendered: str
    token_count: int
    token_source: TokenSource
    model: str
    prompt_version: str
    kept_items: int
    dropped_items: int
    created_at: str


# Statuses whose text may be shown to the model in later turns (with a marker for partial
# output). Failed and still-streaming replies never enter the context.
CONTEXT_STATUSES: frozenset[MessageStatus] = frozenset({"complete", "cancelled", "interrupted"})
