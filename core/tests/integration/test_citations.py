"""The DOI guard in real turns (scripted model, real encrypted database; ADR-0022 §10): what is
shown is what is stored, a DOI with a source is kept, one without is not given as an
identifier. Synthetic data only."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from lazis.conversation import citations
from lazis.memory.commands import NOTICE_START
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle, driver
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.integration.test_people_guard import fact

FAKE = "10.1038/s41586-023-06305-x"


def run[T](storage: StorageHandle, fn: Callable[[driver.Connection], T]) -> T:
    return storage.db.run_sync(fn)


def turn(
    storage: StorageHandle, tmp_path: Path, reply: Callable[[ChatRequest], str], text: str
) -> tuple[str, str, str, dict[str, Any]]:
    """(shown, stored, the request's last user message, diagnostics)."""
    llm = ScriptedLLM(reply=reply)

    async def go() -> tuple[str, str, str, dict[str, Any]]:
        engine = make_engine(storage, llm, tmp_path)
        events, cid = await run_turn(engine, text)
        diag = dict(engine.last_turn or {})
        await engine.close()
        shown = "".join(e["text"] for e in events if e["type"] == "delta")
        stored = run(
            storage,
            lambda c: c.execute(
                "SELECT content FROM messages WHERE conversation_id = ? AND role = 'assistant'"
                " ORDER BY seq DESC LIMIT 1",
                (cid,),
            ).fetchone()[0],
        )
        return shown, stored, llm.chat_requests[-1].messages[-1].content, diag

    return asyncio.run(go())


def test_an_invented_doi_is_not_shown_and_not_stored(
    tmp_path: Path, storage: StorageHandle
) -> None:
    shown, stored, sent, diag = turn(
        storage, tmp_path,
        lambda r: f"2023'te Nature'da yayımlanan bir çalışma var.\n\n**DOI:** {FAKE}\n\nKolay gelsin.",
        "İklim değişikliği hakkında 2023'te yayımlanmış bir makalenin DOI numarasını yazar mısın?",
    )  # fmt: skip
    assert shown == stored
    assert FAKE not in stored and "(doğrulayamadığım için yazmıyorum)" in stored
    assert "2023'te Nature'da yayımlanan bir çalışma var." in stored and "Kolay gelsin." in stored
    assert stored.endswith(citations.UNSUPPORTED_NOTE)
    assert diag["dois_unverified"] == 1 and diag["dois_example"] == 0
    assert NOTICE_START in sent and "doğrulayamazsın" in sent  # the message speaks of a DOI


def test_the_users_own_doi_is_kept(tmp_path: Path, storage: StorageHandle) -> None:
    doi = "10.1093/nar/gkab1112"
    shown, stored, _, diag = turn(
        storage, tmp_path,
        lambda r: f"{doi.upper()} numaralı yayını doğrulayamıyorum ama konusunu konuşabiliriz.",
        f"Şu DOI'li makaleyi açıklar mısın: https://doi.org/{doi}",
    )  # fmt: skip
    assert shown == stored and doi.upper() in stored
    assert citations.UNSUPPORTED_NOTE not in stored and diag["dois_unverified"] == 0


def test_a_doi_in_a_memory_record_is_kept(tmp_path: Path, storage: StorageHandle) -> None:
    doi = "10.5555/tez.2024.0042"
    run(storage, lambda c: fact(c, None, "note", f"Tezimin ana kaynağının DOI'si {doi}"))
    shown, stored, _, diag = turn(
        storage, tmp_path,
        lambda r: f"Tezinizin ana kaynağının DOI'si {doi}.",
        "Tezimin ana kaynağı neydi?",
    )  # fmt: skip
    assert shown == stored == f"Tezinizin ana kaynağının DOI'si {doi}."
    assert diag["dois_unverified"] == 0


def test_an_example_doi_asked_for_is_kept_and_marked(
    tmp_path: Path, storage: StorageHandle
) -> None:
    shown, stored, _, diag = turn(
        storage, tmp_path,
        lambda r: "Bir DOI şöyle görünür: 10.1234/ornek.5678",
        "Kurgusal bir DOI örneği yazar mısın?",
    )  # fmt: skip
    assert shown == stored and "10.1234" not in stored and "10.5555/ornek.0001" in stored
    assert stored.endswith(citations.FICTION_NOTE)
    assert diag["dois_example"] == 1 and diag["dois_unverified"] == 0


def test_a_reply_without_a_doi_and_its_prompt_are_untouched(
    tmp_path: Path, storage: StorageHandle
) -> None:
    text = "Fotosentez, bitkilerin ışık enerjisini kimyasal enerjiye çevirmesidir."
    shown, stored, sent, diag = turn(storage, tmp_path, lambda r: text, "Fotosentez nedir?")
    assert shown == stored == text
    assert "doğrulayamazsın" not in sent and "DOI" not in sent
    assert diag["dois_unverified"] == 0 and diag["dois_example"] == 0
