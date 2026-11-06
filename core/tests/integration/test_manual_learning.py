"""What lasts is written only on the user's explicit request (the owner's decision, 2026-11-05)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from lazis.config.model import MemorySection
from lazis.memory import commands
from lazis.memory import repository as repo
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine, run_turn

OFF = MemorySection(auto_extract=False)


def test_the_product_default_is_off() -> None:
    assert MemorySection().auto_extract is False


@pytest.mark.parametrize(
    "message",
    [
        "Bunu hatırla: Derya vegan.",
        "Hafızana kaydet: Kahveyi şekersiz içerim.",
        "Şunu öğren: Mehmet benim kardeşim.",
        "Bunu unutma: Kısa cevaplardan hoşlanıyorum.",
    ],
)
def test_the_explicit_requests_are_seen_with_no_model_call(message: str) -> None:
    assert commands.detect(message) == "remember"


@pytest.mark.parametrize(
    "message", ["Eşim Derya vegan.", "Kahveyi şekersiz içerim.", "Bugün hava güzel."]
)
def test_an_ordinary_message_is_no_request(message: str) -> None:
    assert commands.detect(message) is None


def test_an_ordinary_message_queues_nothing_and_calls_no_learning_model(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Anladım efendim.")

    async def go() -> None:
        engine = make_engine(storage, llm, tmp_path, memory=OFF)
        await run_turn(engine, "Eşim Derya vegan.")
        await engine.close()

    asyncio.run(go())
    assert storage.db.run_sync(lambda c: repo.count_memories(c)) == {}
    assert (
        storage.db.run_sync(lambda c: c.execute("SELECT COUNT(*) FROM memory_jobs").fetchone()[0])
        == 0
    )
    assert llm.requests and all(r.options.response_format is None for r in llm.requests)
