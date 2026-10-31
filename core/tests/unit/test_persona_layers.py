"""PER-07 (Phase 10B, ADR-0022): the five persona layers — safety, core personality, user
preferences, situational style, memory — can each be switched off on their own, the rendered
order is fixed, and the text matches the snapshots exactly.

Snapshots live in ``tests/snapshots/persona``. After an intended wording change, regenerate
with ``LAZIS_UPDATE_SNAPSHOTS=1 uv run pytest tests/unit/test_persona_layers.py`` and read
the diff before committing it.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from lazis.conversation.prompts import CONVERSATION_RULES
from lazis.personality import ALL_LAYERS, CommunicationPreferences, ContextBlock, Layers
from lazis.personality import preferences as prefs
from lazis.personality.persona import (
    BEHAVIOR_RULES,
    CORE_IDENTITY,
    CORE_STYLE,
    SITUATIONAL,
    identity_text,
    render_block,
    render_system,
)

SNAPSHOTS = Path(__file__).resolve().parents[1] / "snapshots" / "persona"
MODEL = "gemma4:12b-it-qat"
DEFAULT = CommunicationPreferences()
BLOCKS = (ContextBlock("Konuşma özeti", "Kullanıcı maraton için çalışıyor."),)
PREFERRED = CommunicationPreferences(
    verbosity=2, elaboration=3, formality=3, humor=0, address="sen", honorific=False
)
OFF = {
    "safety": Layers(safety=False),
    "core": Layers(core=False),
    "preferences": Layers(preferences=False),
    "situational": Layers(situational=False),
    "memory": Layers(memory=False),
}


def _render(p: CommunicationPreferences = DEFAULT, layers: Layers = ALL_LAYERS) -> str:
    return render_system(p, conversation_rules=CONVERSATION_RULES, model=MODEL, blocks=BLOCKS,
                         layers=layers)  # fmt: skip


CASES: dict[str, str] = {
    "default": _render(),
    "preferred": _render(PREFERRED),
    "all_off": _render(PREFERRED, Layers(False, False, False, False, False)),
    **{f"{name}_off": _render(PREFERRED, layers) for name, layers in OFF.items()},
}


@pytest.mark.parametrize("name", sorted(CASES))
def test_rendered_prompt_matches_its_snapshot(name: str) -> None:
    path = SNAPSHOTS / f"{name}.txt"
    if os.environ.get("LAZIS_UPDATE_SNAPSHOTS") == "1":
        path.write_text(CASES[name], encoding="utf-8")
    assert path.exists(), f"missing snapshot {path.name}"
    assert CASES[name] == path.read_text(encoding="utf-8")


def _parts(p: CommunicationPreferences) -> dict[str, list[str]]:
    """Every layer's own text, by layer."""
    return {
        "safety": [BEHAVIOR_RULES],
        "core": [identity_text(MODEL), CORE_STYLE],
        "situational": [SITUATIONAL],
        "preferences": prefs.lines(p),
        "memory": [render_block(b) for b in BLOCKS],
    }


@pytest.mark.parametrize("off", sorted(OFF))
def test_each_layer_switches_off_alone(off: str) -> None:
    text = _render(PREFERRED, OFF[off])
    for layer, pieces in _parts(PREFERRED).items():
        for piece in pieces:
            assert (piece in text) is (layer != off), (layer, piece[:40])
    assert CONVERSATION_RULES in text  # the engine's rules are not a persona layer


def test_switching_a_layer_off_removes_only_its_text() -> None:
    full = _render(PREFERRED)
    for name, layers in OFF.items():
        reduced = _render(PREFERRED, layers)
        rest = full
        for piece in _parts(PREFERRED)[name]:
            rest = rest.replace(piece, "")
        assert [ln for ln in reduced.splitlines() if ln] == [
            ln for ln in rest.splitlines() if ln
        ], name


def test_the_order_is_fixed() -> None:
    text = _render(PREFERRED)
    order = [text.index(x) for x in (CORE_IDENTITY, BEHAVIOR_RULES, CORE_STYLE, SITUATIONAL,
                                     prefs.lines(PREFERRED)[0], CONVERSATION_RULES,
                                     render_block(BLOCKS[0]))]  # fmt: skip
    assert order == sorted(order)
    assert prefs.lines(PREFERRED) == [
        ln for ln in text.splitlines() if ln in prefs.lines(PREFERRED)
    ]


def test_rendering_is_deterministic() -> None:
    assert _render(PREFERRED) == _render(replace(PREFERRED))
    assert _render() == _render(CommunicationPreferences.from_settings())


def test_the_default_prompt_is_persona_v3() -> None:
    # Byte for byte the Phase 5–10A text: no preference set, nothing changes for anyone.
    assert CASES["default"] == (SNAPSHOTS / "default.txt").read_text(encoding="utf-8")
    assert prefs.lines(CommunicationPreferences()) == [prefs.HUMOR_DEFAULT]


def test_no_preference_touches_the_safety_layer_or_identity() -> None:
    extremes = [
        CommunicationPreferences(verbosity=v, elaboration=e, formality=f, humor=h, address=a,
                                 honorific=o)
        for v in (0, 10) for e in (0, 10) for f in (0, 10) for h in (0, 10)
        for a in ("siz", "sen") for o in (True, False)
    ]  # fmt: skip
    for p in extremes:
        text = _render(p)
        assert text.count(BEHAVIOR_RULES) == 1 and text.count(CORE_IDENTITY) == 1
        assert text.index(BEHAVIOR_RULES) < text.index(SITUATIONAL)
        for line in prefs.lines(p):
            for forbidden in ("uydur", "onayla", "ilke", "güvenlik", "kimliğ", "LAZIS"):
                assert forbidden not in line, (forbidden, line)
    # Shorter replies still carry the important warning (PER-12).
    assert "uyarı" in prefs.lines(CommunicationPreferences(verbosity=1))[1]
    assert "uyarı" in prefs.lines(CommunicationPreferences(elaboration=1))[1]
