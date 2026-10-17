"""SQL for the conversation tables (0002_conversations). Runs inside the database thread.

Every function takes the open connection; multi-statement writes are wrapped by the caller in
:func:`transaction`. Nothing here logs message content.
"""

from __future__ import annotations

import json
from collections.abc import Generator, Sequence
from contextlib import contextmanager
from typing import Any, cast

from lazis.conversation.models import (
    ContextState,
    Conversation,
    Message,
    MessageStatus,
    Role,
    Strategy,
    Summary,
    TokenSource,
)
from lazis.errors import DatabaseBusyError, MessageSaveError
from lazis.ids import new_ulid
from lazis.storage.driver import Connection, DatabaseError, OperationalError

_CONVERSATION_COLS = (
    "id, title, title_source, model, status, message_count, last_seq, created_at, updated_at"
)
_MESSAGE_COLS = (
    "id, conversation_id, seq, role, content, context_note, status, client_id, reply_to, model,"
    " token_count, token_source, prompt_tokens, output_tokens, ttft_ms, total_ms, error_code,"
    " created_at, completed_at"
)
_CONTEXT_COLS = (
    "conversation_id, context_version, prompt_version, strategy, window_start_seq, summary_id,"
    " budget_tokens, anchor_seq, anchor_tokens, prefix_hash, last_prompt_tokens, updated_at"
)
_SUMMARY_COLS = (
    "id, conversation_id, version, from_seq, to_seq, previous_id, status, content_json, rendered,"
    " token_count, token_source, model, prompt_version, kept_items, dropped_items, created_at"
)


def is_busy(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, OperationalError) and ("locked" in text or "busy" in text)


@contextmanager
def transaction(conn: Connection) -> Generator[None]:
    """BEGIN IMMEDIATE … COMMIT, rolled back on any error. Driver errors become stable codes."""
    try:
        conn.execute("BEGIN IMMEDIATE")
    except DatabaseError as exc:
        raise (DatabaseBusyError if is_busy(exc) else MessageSaveError)("begin failed") from None
    try:
        yield
        conn.execute("COMMIT")
    except BaseException as exc:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        if isinstance(exc, DatabaseError):
            raise (DatabaseBusyError if is_busy(exc) else MessageSaveError)(
                f"write failed ({exc.__class__.__name__})"
            ) from None
        raise


# ----- row mapping ---------------------------------------------------------------------
def _conversation(row: Sequence[Any]) -> Conversation:
    return Conversation(
        id=str(row[0]),
        title=str(row[1]),
        title_source=cast(Any, str(row[2])),
        model=str(row[3]),
        status=cast(Any, str(row[4])),
        message_count=int(row[5]),
        last_seq=int(row[6]),
        created_at=str(row[7]),
        updated_at=str(row[8]),
    )


def _opt_int(value: Any) -> int | None:
    return None if value is None else int(value)


def _opt_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _message(row: Sequence[Any]) -> Message:
    return Message(
        id=str(row[0]),
        conversation_id=str(row[1]),
        seq=int(row[2]),
        role=cast(Role, str(row[3])),
        content=str(row[4]),
        context_note=_opt_str(row[5]),
        status=cast(MessageStatus, str(row[6])),
        client_id=_opt_str(row[7]),
        reply_to=_opt_str(row[8]),
        model=_opt_str(row[9]),
        token_count=_opt_int(row[10]),
        token_source=cast("TokenSource | None", _opt_str(row[11])),
        prompt_tokens=_opt_int(row[12]),
        output_tokens=_opt_int(row[13]),
        ttft_ms=_opt_float(row[14]),
        total_ms=_opt_float(row[15]),
        error_code=_opt_str(row[16]),
        created_at=str(row[17]),
        completed_at=_opt_str(row[18]),
    )


def _context(row: Sequence[Any]) -> ContextState:
    return ContextState(
        conversation_id=str(row[0]),
        context_version=int(row[1]),
        prompt_version=str(row[2]),
        strategy=cast(Strategy, str(row[3])),
        window_start_seq=int(row[4]),
        summary_id=_opt_str(row[5]),
        budget_tokens=int(row[6]),
        anchor_seq=_opt_int(row[7]),
        anchor_tokens=_opt_int(row[8]),
        prefix_hash=_opt_str(row[9]),
        last_prompt_tokens=_opt_int(row[10]),
        updated_at=str(row[11]),
    )


def _summary(row: Sequence[Any]) -> Summary:
    content: Any = json.loads(str(row[7]))
    return Summary(
        id=str(row[0]),
        conversation_id=str(row[1]),
        version=int(row[2]),
        from_seq=int(row[3]),
        to_seq=int(row[4]),
        previous_id=_opt_str(row[5]),
        status=cast(Any, str(row[6])),
        content=cast(dict[str, Any], content) if isinstance(content, dict) else {},
        rendered=str(row[8]),
        token_count=int(row[9]),
        token_source=cast(TokenSource, str(row[10])),
        model=str(row[11]),
        prompt_version=str(row[12]),
        kept_items=int(row[13]),
        dropped_items=int(row[14]),
        created_at=str(row[15]),
    )


# ----- conversations -------------------------------------------------------------------
def insert_conversation(
    conn: Connection, *, title: str, model: str, now: str, conversation_id: str | None = None
) -> Conversation:
    cid = conversation_id or new_ulid()
    conn.execute(
        f"INSERT INTO conversations ({_CONVERSATION_COLS}) VALUES (?, ?, 'auto', ?, 'active',"  # noqa: S608
        " 0, 0, ?, ?)",
        (cid, title, model, now, now),
    )
    found = get_conversation(conn, cid)
    assert found is not None
    return found


def get_conversation(conn: Connection, conversation_id: str) -> Conversation | None:
    row = conn.execute(
        f"SELECT {_CONVERSATION_COLS} FROM conversations WHERE id = ?",  # noqa: S608
        (conversation_id,),
    ).fetchone()
    return None if row is None else _conversation(row)


def list_conversations(
    conn: Connection, *, limit: int, before: tuple[str, str] | None = None
) -> list[Conversation]:
    """Most recently updated first. ``before`` is a keyset cursor ``(updated_at, id)``."""
    if before is None:
        rows = conn.execute(
            f"SELECT {_CONVERSATION_COLS} FROM conversations"  # noqa: S608
            " ORDER BY updated_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT {_CONVERSATION_COLS} FROM conversations"  # noqa: S608
            " WHERE (updated_at, id) < (?, ?) ORDER BY updated_at DESC, id DESC LIMIT ?",
            (before[0], before[1], limit),
        ).fetchall()
    return [_conversation(r) for r in rows]


def rename_conversation(conn: Connection, conversation_id: str, title: str, now: str) -> bool:
    cursor = conn.execute(
        "UPDATE conversations SET title = ?, title_source = 'user', updated_at = ? WHERE id = ?",
        (title, now, conversation_id),
    )
    return cursor.rowcount == 1


def set_conversation_model(conn: Connection, conversation_id: str, model: str) -> None:
    conn.execute("UPDATE conversations SET model = ? WHERE id = ?", (model, conversation_id))


def touch_conversation(conn: Connection, conversation_id: str, now: str) -> None:
    conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))


def delete_conversation(conn: Connection, conversation_id: str) -> tuple[int, int] | None:
    """Delete a conversation and (by cascade) its messages, context state and summaries.

    Returns ``(messages, summaries)`` removed, or ``None`` if it did not exist.
    """
    if get_conversation(conn, conversation_id) is None:
        return None
    messages = int(
        conn.execute(
            "SELECT COUNT(*) FROM messages WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
    )
    summaries = int(
        conn.execute(
            "SELECT COUNT(*) FROM context_summaries WHERE conversation_id = ?", (conversation_id,)
        ).fetchone()[0]
    )
    # conversation_context.summary_id → context_summaries is SET NULL; delete the context
    # row first so the cascade order does not matter.
    conn.execute("DELETE FROM conversation_context WHERE conversation_id = ?", (conversation_id,))
    conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return messages, summaries


def count_rows(conn: Connection, conversation_id: str) -> dict[str, int]:
    """Row counts left for a conversation in every conversation table (deletion tests)."""
    out: dict[str, int] = {}
    for table, column in (
        ("conversations", "id"),
        ("messages", "conversation_id"),
        ("context_summaries", "conversation_id"),
        ("conversation_context", "conversation_id"),
    ):
        out[table] = int(
            conn.execute(
                f"SELECT COUNT(*) FROM {table} WHERE {column} = ?",  # noqa: S608
                (conversation_id,),
            ).fetchone()[0]
        )
    return out


# ----- messages ------------------------------------------------------------------------
def insert_message(
    conn: Connection,
    *,
    conversation_id: str,
    role: Role,
    content: str,
    status: MessageStatus,
    now: str,
    context_note: str | None = None,
    client_id: str | None = None,
    reply_to: str | None = None,
    model: str | None = None,
    token_count: int | None = None,
    token_source: TokenSource | None = None,
) -> Message:
    """Append a message with the next ``seq`` (call inside a transaction)."""
    row = conn.execute(
        "UPDATE conversations SET last_seq = last_seq + 1, message_count = message_count + 1,"
        " updated_at = ? WHERE id = ? RETURNING last_seq",
        (now, conversation_id),
    ).fetchone()
    if row is None:
        raise MessageSaveError("conversation does not exist")
    seq = int(row[0])
    mid = new_ulid()
    conn.execute(
        f"INSERT INTO messages ({_MESSAGE_COLS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"  # noqa: S608
        " NULL, NULL, NULL, NULL, NULL, ?, ?)",
        (
            mid,
            conversation_id,
            seq,
            role,
            content,
            context_note,
            status,
            client_id,
            reply_to,
            model,
            token_count,
            token_source,
            now,
            now if status != "streaming" else None,
        ),
    )
    found = get_message(conn, mid)
    assert found is not None
    return found


def get_message(conn: Connection, message_id: str) -> Message | None:
    row = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE id = ?",  # noqa: S608
        (message_id,),
    ).fetchone()
    return None if row is None else _message(row)


def find_by_client_id(conn: Connection, client_id: str) -> Message | None:
    row = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE client_id = ?",  # noqa: S608
        (client_id,),
    ).fetchone()
    return None if row is None else _message(row)


def reply_for(conn: Connection, user_message_id: str) -> Message | None:
    row = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE reply_to = ? ORDER BY seq LIMIT 1",  # noqa: S608
        (user_message_id,),
    ).fetchone()
    return None if row is None else _message(row)


def update_partial(conn: Connection, message_id: str, content: str) -> None:
    """Persist streamed text so far (the row stays ``streaming``)."""
    conn.execute(
        "UPDATE messages SET content = ? WHERE id = ? AND status = 'streaming'",
        (content, message_id),
    )


def finalize_message(
    conn: Connection,
    message_id: str,
    *,
    status: MessageStatus,
    content: str,
    now: str,
    token_count: int | None = None,
    token_source: TokenSource | None = None,
    prompt_tokens: int | None = None,
    output_tokens: int | None = None,
    ttft_ms: float | None = None,
    total_ms: float | None = None,
    error_code: str | None = None,
) -> bool:
    """Close a ``streaming`` row exactly once (later calls are no-ops and return False)."""
    cursor = conn.execute(
        "UPDATE messages SET status = ?, content = ?, token_count = ?, token_source = ?,"
        " prompt_tokens = ?, output_tokens = ?, ttft_ms = ?, total_ms = ?, error_code = ?,"
        " completed_at = ? WHERE id = ? AND status = 'streaming'",
        (
            status,
            content,
            token_count,
            token_source,
            prompt_tokens,
            output_tokens,
            ttft_ms,
            total_ms,
            error_code,
            now,
            message_id,
        ),
    )
    return cursor.rowcount == 1


def set_token_count(conn: Connection, message_id: str, count: int, source: TokenSource) -> None:
    conn.execute(
        "UPDATE messages SET token_count = ?, token_source = ? WHERE id = ?",
        (count, source, message_id),
    )


def page_messages(
    conn: Connection, conversation_id: str, *, limit: int, before_seq: int | None = None
) -> list[Message]:
    """A page of the newest messages (older than ``before_seq``), returned in ``seq`` order."""
    bound = before_seq if before_seq is not None else 2**62
    rows = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE conversation_id = ? AND seq < ?"  # noqa: S608
        " ORDER BY seq DESC LIMIT ?",
        (conversation_id, bound, limit),
    ).fetchall()
    return [_message(r) for r in reversed(rows)]


def messages_between(
    conn: Connection, conversation_id: str, from_seq: int, to_seq: int | None = None
) -> list[Message]:
    upper = to_seq if to_seq is not None else 2**62
    rows = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE conversation_id = ?"  # noqa: S608
        " AND seq >= ? AND seq <= ? ORDER BY seq",
        (conversation_id, from_seq, upper),
    ).fetchall()
    return [_message(r) for r in rows]


def messages_by_seq(conn: Connection, conversation_id: str, seqs: Sequence[int]) -> list[Message]:
    if not seqs:
        return []
    unique = sorted(set(seqs))
    marks = ", ".join("?" for _ in unique)
    rows = conn.execute(
        f"SELECT {_MESSAGE_COLS} FROM messages WHERE conversation_id = ?"  # noqa: S608
        f" AND seq IN ({marks}) ORDER BY seq",
        (conversation_id, *unique),
    ).fetchall()
    return [_message(r) for r in rows]


def mark_streaming_interrupted(conn: Connection, now: str) -> int:
    """Startup recovery: replies left ``streaming`` by a crash become ``interrupted``."""
    cursor = conn.execute(
        "UPDATE messages SET status = 'interrupted', error_code = 'interrupted',"
        " completed_at = ? WHERE status = 'streaming'",
        (now,),
    )
    return int(cursor.rowcount)


# ----- context state -------------------------------------------------------------------
def get_context(conn: Connection, conversation_id: str) -> ContextState | None:
    row = conn.execute(
        f"SELECT {_CONTEXT_COLS} FROM conversation_context WHERE conversation_id = ?",  # noqa: S608
        (conversation_id,),
    ).fetchone()
    return None if row is None else _context(row)


def save_context(conn: Connection, state: ContextState) -> None:
    conn.execute(
        f"INSERT INTO conversation_context ({_CONTEXT_COLS}) VALUES"  # noqa: S608
        " (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(conversation_id) DO UPDATE SET"
        " context_version = excluded.context_version, prompt_version = excluded.prompt_version,"
        " strategy = excluded.strategy, window_start_seq = excluded.window_start_seq,"
        " summary_id = excluded.summary_id, budget_tokens = excluded.budget_tokens,"
        " anchor_seq = excluded.anchor_seq, anchor_tokens = excluded.anchor_tokens,"
        " prefix_hash = excluded.prefix_hash, last_prompt_tokens = excluded.last_prompt_tokens,"
        " updated_at = excluded.updated_at",
        (
            state.conversation_id,
            state.context_version,
            state.prompt_version,
            state.strategy,
            state.window_start_seq,
            state.summary_id,
            state.budget_tokens,
            state.anchor_seq,
            state.anchor_tokens,
            state.prefix_hash,
            state.last_prompt_tokens,
            state.updated_at,
        ),
    )


# ----- summaries -----------------------------------------------------------------------
def insert_summary(
    conn: Connection,
    *,
    conversation_id: str,
    from_seq: int,
    to_seq: int,
    previous_id: str | None,
    content: dict[str, Any],
    rendered: str,
    token_count: int,
    token_source: TokenSource,
    model: str,
    prompt_version: str,
    kept_items: int,
    dropped_items: int,
    now: str,
) -> Summary:
    version = int(
        conn.execute(
            "SELECT COALESCE(MAX(version), 0) + 1 FROM context_summaries WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
    )
    sid = new_ulid()
    conn.execute(
        "UPDATE context_summaries SET status = 'superseded'"
        " WHERE conversation_id = ? AND status = 'active'",
        (conversation_id,),
    )
    conn.execute(
        f"INSERT INTO context_summaries ({_SUMMARY_COLS}) VALUES"  # noqa: S608
        " (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            sid,
            conversation_id,
            version,
            from_seq,
            to_seq,
            previous_id,
            json.dumps(content, ensure_ascii=False, sort_keys=True),
            rendered,
            token_count,
            token_source,
            model,
            prompt_version,
            kept_items,
            dropped_items,
            now,
        ),
    )
    found = get_summary(conn, sid)
    assert found is not None
    return found


def get_summary(conn: Connection, summary_id: str) -> Summary | None:
    row = conn.execute(
        f"SELECT {_SUMMARY_COLS} FROM context_summaries WHERE id = ?",  # noqa: S608
        (summary_id,),
    ).fetchone()
    return None if row is None else _summary(row)


def list_summaries(conn: Connection, conversation_id: str) -> list[Summary]:
    rows = conn.execute(
        f"SELECT {_SUMMARY_COLS} FROM context_summaries WHERE conversation_id = ?"  # noqa: S608
        " ORDER BY version",
        (conversation_id,),
    ).fetchall()
    return [_summary(r) for r in rows]


def invalidate_summaries(conn: Connection, conversation_id: str) -> int:
    cursor = conn.execute(
        "UPDATE context_summaries SET status = 'invalidated'"
        " WHERE conversation_id = ? AND status != 'invalidated'",
        (conversation_id,),
    )
    return int(cursor.rowcount)
