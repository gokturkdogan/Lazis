"""Prompt assembly, prefix stability and token budgeting (pure functions, synthetic data)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from lazis.conversation.context import (
    Budget,
    TokenEstimator,
    assemble,
    derived_user_tokens,
    message_cost,
    render_message,
    system_text,
    trim_to_fit,
)
from lazis.conversation.engine import auto_title, initial_context
from lazis.conversation.models import ContextState, Message, Summary
from lazis.conversation.prompts import (
    CANCELLED_MARKER,
    INTERRUPTED_MARKER,
    S0_POLICY,
    S1_PERSONA,
    time_note,
)

EST = TokenEstimator(2.2, 8)
MODEL = "gemma4:12b-it-qat"


def msg(seq: int, role: str, content: str, status: str = "complete", **kw: object) -> Message:
    base = Message(
        id=f"m{seq:04d}",
        conversation_id="c1",
        seq=seq,
        role=role,  # type: ignore[arg-type]
        content=content,
        context_note="[Mesaj zamanı: 17 Ekim 2026 Cumartesi 14:32]" if role == "user" else None,
        status=status,  # type: ignore[arg-type]
        client_id=None,
        reply_to=None,
        model=MODEL,
        token_count=None,
        token_source=None,
        prompt_tokens=None,
        output_tokens=None,
        ttft_ms=None,
        total_ms=None,
        error_code=None,
        created_at="2026-10-17T11:32:00.000Z",
        completed_at=None,
        timeline_seq=seq,
    )
    return replace(base, **kw)  # type: ignore[arg-type]


def state(**kw: object) -> ContextState:
    return replace(initial_context("c1", 13722, "2026-10-17T11:32:00.000Z"), **kw)  # type: ignore[arg-type]


def build(window: list[Message], st: ContextState | None = None, summary: Summary | None = None):
    return assemble(
        state=st or state(),
        summary=summary,
        window=window,
        model=MODEL,
        num_ctx=16384,
        estimator=EST,
    )


def test_layout_is_system_then_history_with_stored_time_notes() -> None:
    window = [
        msg(1, "user", "Merhaba"),
        msg(2, "assistant", "Merhaba efendim."),
        msg(3, "user", "Nasılsın?"),
    ]
    built = build(window)
    roles = [m.role for m in built.messages]
    assert roles == ["system", "user", "assistant", "user"]
    assert (
        built.messages[0].content.startswith(S0_POLICY) and S1_PERSONA in built.messages[0].content
    )
    assert built.messages[1].content == "[Mesaj zamanı: 17 Ekim 2026 Cumartesi 14:32]\nMerhaba"
    assert built.included_seqs == (1, 2, 3)


def test_prefix_and_history_are_append_only_across_turns() -> None:
    """The next request starts with every message of the previous one, byte for byte."""
    turn1 = [
        msg(1, "user", "Bir plan yapalım."),
    ]
    turn2 = [*turn1, msg(2, "assistant", "Olur."), msg(3, "user", "Pazartesi başlayalım.")]
    a, b = build(turn1), build(turn2)
    assert a.prefix_hash == b.prefix_hash
    assert b.messages[: len(a.messages)] == a.messages
    # Deterministic: the same input renders the same prompt.
    assert build(turn2).messages == b.messages


def test_prefix_changes_only_with_summary_model_or_window_note() -> None:
    window = [msg(1, "user", "a")]
    base = build(window).prefix_hash
    assert (
        assemble(
            state=state(),
            summary=None,
            window=window,
            model="qwen3.5:9b-q4_K_M",
            num_ctx=16384,
            estimator=EST,
        ).prefix_hash
        != base
    )
    assert (
        assemble(
            state=state(), summary=None, window=window, model=MODEL, num_ctx=32768, estimator=EST
        ).prefix_hash
        != base
    )
    trimmed = state(window_start_seq=5, strategy="window_only")
    assert build([msg(5, "user", "x")], trimmed).prefix_hash != base


def test_partial_and_failed_replies_follow_the_context_rule() -> None:
    cancelled = render_message(msg(2, "assistant", "Yarım yanıt", "cancelled"))
    interrupted = render_message(msg(2, "assistant", "Yarım", "interrupted"))
    assert cancelled is not None and cancelled.content.endswith(CANCELLED_MARKER)
    assert interrupted is not None and interrupted.content.endswith(INTERRUPTED_MARKER)
    assert render_message(msg(2, "assistant", "Hatalı", "failed")) is None
    assert render_message(msg(2, "assistant", "", "cancelled")) is None
    assert render_message(msg(2, "assistant", "x", "streaming")) is None


def test_estimate_uses_runtime_anchor_and_adds_only_new_messages() -> None:
    window = [
        msg(1, "user", "a" * 300),
        msg(2, "assistant", "b" * 300, token_count=104),
        msg(3, "user", "c" * 30),
    ]
    st0 = state()
    unanchored = build(window, st0)
    assert not unanchored.anchored
    anchored_state = state(anchor_seq=1, anchor_tokens=500, prefix_hash=unanchored.prefix_hash)
    anchored = build(window, anchored_state)
    assert anchored.anchored
    assert anchored.estimated_tokens == 500 + 104 + message_cost(window[2], EST)
    # A different prefix (e.g. after compaction) invalidates the anchor.
    stale = state(anchor_seq=1, anchor_tokens=500, prefix_hash="other")
    assert not build(window, stale).anchored


def test_estimator_is_conservative_for_turkish() -> None:
    sample = (
        "Yarın sabah annemle birlikte Kadıköy'deki pazara gitmeyi düşünüyorum; erken mi çıkalım?"
    )
    # Measured on Gemma 4 12B: 2.5–3.8 characters per token for Turkish text.
    assert EST.text(sample) >= len(sample) / 2.5


def test_runtime_derived_user_tokens() -> None:
    window = [msg(1, "user", "a"), msg(2, "assistant", "b", token_count=20), msg(3, "user", "c")]
    phash = build(window).prefix_hash
    st = state(anchor_seq=1, anchor_tokens=400, prefix_hash=phash)
    assert (
        derived_user_tokens(
            state=st, prompt_hash=phash, window=window, user_seq=3, prompt_tokens=450, estimator=EST
        )
        == 30
    )
    assert (
        derived_user_tokens(
            state=st, prompt_hash="x", window=window, user_seq=3, prompt_tokens=450, estimator=EST
        )
        is None
    )
    assert (
        derived_user_tokens(
            state=state(),
            prompt_hash=phash,
            window=window,
            user_seq=3,
            prompt_tokens=450,
            estimator=EST,
        )
        is None
    )


def test_budget_reserves_reply_and_safety_margin() -> None:
    b = Budget.build(16384, 1024, 0.10, 6144)
    assert b.hard_limit == 16384 - 1024 - 1639
    assert b.compact_at == 6144
    assert (
        Budget.build(4096, 1024, 0.1, 6144).compact_at
        == Budget.build(4096, 1024, 0.1, 6144).hard_limit
    )


def test_trim_keeps_the_newest_message_and_announces_the_gap() -> None:
    window = [msg(i, "user" if i % 2 else "assistant", "x" * 2000) for i in range(1, 21)]
    start = trim_to_fit(
        state=state(),
        summary=None,
        window=window,
        model=MODEL,
        num_ctx=16384,
        estimator=EST,
        limit=5000,
        keep_last=1,
    )
    assert start is not None and start > 1 and window[start - 1].role == "user"
    trimmed = build(window, state(window_start_seq=start, strategy="window_only"))
    assert trimmed.omitted == (1, start - 1)
    assert f"#1–#{start - 1}" in trimmed.system_text and trimmed.estimated_tokens <= 5000
    assert (
        trim_to_fit(
            state=state(),
            summary=None,
            window=[msg(1, "user", "x" * 40000)],
            model=MODEL,
            num_ctx=16384,
            estimator=EST,
            limit=5000,
            keep_last=1,
        )
        is None
    )


def test_summary_goes_into_the_system_block() -> None:
    summary = Summary(
        "s1",
        "c1",
        1,
        1,
        10,
        None,
        "active",
        {},
        "Konuşma özeti (#1–#10 …)",
        10,
        "estimate",
        MODEL,
        "s3-v1",
        0,
        0,
        "t",
    )
    text = system_text(summary, None)
    assert text.endswith("Konuşma özeti (#1–#10 …)")
    st = state(window_start_seq=11, summary_id="s1", strategy="summary_window")
    assert build([msg(11, "user", "devam")], st, summary).omitted is None


def test_time_note_is_turkish_and_explicit() -> None:
    assert time_note(datetime(2026, 10, 17, 9, 5)) == "[Mesaj zamanı: 17 Ekim 2026 Cumartesi 09:05]"
    assert time_note(datetime(2026, 3, 2, 23, 59)) == "[Mesaj zamanı: 2 Mart 2026 Pazartesi 23:59]"


def test_auto_title() -> None:
    assert auto_title("  Merhaba\n dünya  ", 60) == "Merhaba dünya"
    long = auto_title("Yarın sabah annemle birlikte Kadıköy'deki pazara gitmeyi düşünüyorum", 40)
    assert len(long) <= 40 and long.endswith("…")
