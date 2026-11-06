"""Fewer repeated openings and closings (Phase 10D): a note, no model call."""

from __future__ import annotations

from lazis.conversation import repetition
from lazis.memory import commands


def test_a_greeting_names_the_previous_opening() -> None:
    note = repetition.note("Merhaba efendim, size nasıl yardımcı olabilirim?", greeting=True)
    assert note.startswith(commands.NOTICE_START)
    assert note.count("«Merhaba efendim, size nasıl yardımcı olabilirim?»") == 1


def test_a_closing_question_is_named() -> None:
    note = repetition.note("Bütçeniz 20 bin TL.\nBaşka bir konuda yardımcı olabilir miyim?",
                           greeting=False)  # fmt: skip
    assert "«Başka bir konuda yardımcı olabilir miyim?»" in note
    assert "Bütçeniz" not in note


def test_nothing_to_name() -> None:
    assert repetition.note("", greeting=True) == ""
    assert repetition.note("Bütçeniz 20 bin TL.", greeting=False) == ""
    assert repetition.note("Uzun bir soru " + "x" * 200 + "?", greeting=False) == ""
