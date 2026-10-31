"""The people guard in real turns (Phase 10A): the production engine, the synthetic graph (two
Ahmets; the childhood friend's sibling Mehmet) and a scripted model — what the user sees while
it streams, what is stored, and the diagnostics count."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import people, repository
from lazis.memory import relationships
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.graph_support import World, run
from tests.integration.test_claims_in_turns import shown_prefixes


async def _turn(
    storage: StorageHandle, tmp_path: Path, message: str, reply: str, chunk_size: int
) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    engine = make_engine(
        storage, ScriptedLLM(reply=lambda r: reply, chunk_size=chunk_size), tmp_path
    )
    events, cid = await run_turn(engine, message)
    last = dict(engine.last_turn or {})
    await engine.close()
    stored = storage.db.run_sync(lambda c: repository.messages_between(c, cid, 1))[-1].content
    return events, last, stored


@pytest.mark.parametrize("chunk_size", [1, 3, 8, 64])
def test_an_answer_about_an_unsettled_ahmet(
    tmp_path: Path, storage: StorageHandle, world: World, chunk_size: int
) -> None:
    reply = ("Ahmet'in kardeşi Mehmet'tir. Ancak sistemde iki Ahmet var; çocukluk arkadaşınız "
             "olan mı, iş ortağınız olan mı?")  # fmt: skip
    events, last, stored = asyncio.run(
        _turn(storage, tmp_path, "Ahmet'in kardeşi kim?", reply, chunk_size)
    )
    prefixes = shown_prefixes(events)
    assert all("Mehmet" not in p for p in prefixes)
    done = next(e for e in events if e["type"] == "done")["message"]["content"]
    expected = "Sistemde iki Ahmet var; çocukluk arkadaşınız olan mı, iş ortağınız olan mı?"
    assert prefixes[-1] == stored == done == expected
    assert last["people_sentences_removed"] == 1


def test_a_settled_question_is_answered(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    reply = "Çocukluk arkadaşınız Ahmet'in kardeşi Mehmet'tir efendim."
    events, last, stored = asyncio.run(
        _turn(storage, tmp_path, "Çocukluk arkadaşım Ahmet'in kardeşi kim?", reply, 3)
    )
    assert shown_prefixes(events)[-1] == stored == reply
    assert last["people_sentences_removed"] == 0


@pytest.mark.parametrize("chunk_size", [1, 5, 64])
def test_a_forgotten_relationship_from_the_history(
    tmp_path: Path, storage: StorageHandle, world: World, chunk_size: int
) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    events, last, stored = asyncio.run(
        _turn(
            storage,
            tmp_path,
            "Mehmet, Ahmet'in neyi oluyor?",
            "Mehmet, Ahmet'in kuzeniydi.",
            chunk_size,
        )
    )
    prefixes = shown_prefixes(events)
    assert all("kuzen" not in p for p in prefixes)
    assert prefixes[-1] == stored == people.NO_RECORD
    assert last["people_sentences_removed"] == 1


def test_a_turn_with_nothing_to_check_streams_as_before(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    run(storage, lambda c: relationships.forget_pair(c, world["ahmet"], world["mehmet"]))
    reply = "Güzel bir gün geçirmenizi dilerim efendim. Yürüyüş iyi gelebilir."
    events, last, stored = asyncio.run(_turn(storage, tmp_path, "Bugün hava güzel.", reply, 3))
    prefixes = shown_prefixes(events)
    assert prefixes[-1] == stored == reply
    # Released as it came, not a sentence at a time.
    assert len(prefixes) > 3 and prefixes[0] != "Güzel bir gün geçirmenizi dilerim efendim."
    assert last["people_sentences_removed"] == 0
