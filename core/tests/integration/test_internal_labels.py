"""Internal labels stay internal (Phase 7.2). The model once told the user "yalnızca 'HAFIZA
İŞLEMİ' bildirimi varsa kaydedebilirim": the label came from the persona's own rule. Now no
label is in the system prompt, the notes the system adds travel only with the current message
under a header that says they are invisible, and nothing of them is stored in the history.
(Whether the model repeats a note is measured with the real model: evals/runners/p72_*.)"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import repository
from lazis.memory import commands, retrieval, service
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.integration.test_memory_commands import answer, item

LABELS = ("HAFIZA İŞLEMİ", "KİŞİSEL HAFIZA", "SİSTEM NOTU", "===")
HEADERS = {commands.NOTICE_START, commands.NOTICE_END, retrieval.BLOCK_START, retrieval.BLOCK_END}

SCENARIOS = [
    # memory questions
    "Tariflerimi hatırlar mısın?", "Neleri hatırlayabiliyorsun?", "Hafızan nasıl çalışıyor?",
    "Benim hakkımda ne biliyorsun?", "Hafızanda ne var?",
    # past information
    "Kahvemi nasıl içiyordum?", "Komşum Ahmet ne iş yapıyordu?", "Atlas projesinde hangi dili kullanıyorum?",
    "Geçen ay sana ne anlatmıştım?",
    # save requests
    "Bunu unutma: Selin vejetaryen.", "Lütfen şunu not al: Murat'ın doğum günü 12 Haziran.",
    "Hafızana kaydet: kira her ayın beşinde.", "Bunu unutma.",
    # relationship questions
    "Ahmet benim neyim oluyor?", "Komşum kim?", "Ahmet'in kardeşi kim?",
    # recipes
    "Annemin mercimek çorbası tarifini kaydeder misin? Bir su bardağı mercimek, bir soğan.",
    "Mercimek çorbası tarifimi hatırlıyor musun?",
    # projects
    "Atlas projesinde backend'i Rust ile yazıyorum.", "Atlas projesi ne durumda?",
    # preferences
    "Kahveyi şekersiz içerim.", "Korku filmlerinden hoşlanmam.", "Bana kısa cevaplar ver.",
    # technical questions about LAZIS itself
    "Teknik olarak nasıl çalışıyorsun?", "Hangi modeli kullanıyorsun?", "Verilerim nerede saklanıyor?",
    # ordinary chat
    "Merhaba!", "Bugün çok yorgunum.", "Hafta sonu için öneri verir misin?", "Teşekkürler, iyi geceler.",
]  # fmt: skip


def seed(storage: StorageHandle) -> None:
    ahmet = EntityRef("Ahmet", relation="komşusu")
    cands = [
        Candidate(predicate="occupation", value="mimar", statement="Ahmet mimar.", about="entity", entity=ahmet),
        Candidate(predicate="likes", value="şekersiz kahve", statement="Kullanıcı kahveyi şekersiz içer."),
        Candidate(predicate="project_technology", value="Rust", statement="Atlas projesinde Rust kullanılıyor.",
                  about="entity", entity=EntityRef("Atlas", kind="project")),
    ]  # fmt: skip
    storage.db.run_sync(
        lambda c: service.apply_candidates(c, cands, source=Source("import"), explicit=True)
    )


def converse(storage: StorageHandle, tmp_path: Path, *texts: str) -> ScriptedLLM:
    save = answer("remember", items=[item("note", "vejetaryen", "Selin vejetaryen.", "Selin vejetaryen",
                                          entity="Selin")])  # fmt: skip
    llm = ScriptedLLM(
        command=lambda r: save if "Selin" in r.messages[-1].content else answer("none")
    )
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> None:
        cid: str | None = None
        for t in texts:
            _, cid = await run_turn(engine, t, cid)
        await engine.close()

    asyncio.run(go())
    return llm


@pytest.mark.parametrize("message", SCENARIOS)
def test_labels_never_reach_the_model_outside_the_current_note(
    tmp_path: Path, storage: StorageHandle, message: str
) -> None:
    seed(storage)
    llm = converse(storage, tmp_path, "Merhaba.", message)
    request = llm.chat_requests[-1]
    system = request.messages[0]
    assert system.role == "system"
    for label in LABELS:
        assert label not in system.content, label
    # History (earlier turns) carries no note and no label.
    for m in request.messages[1:-1]:
        assert not any(label in m.content for label in LABELS), m.content[:80]
    # The current message: only the known headers, and every note marked invisible.
    lines = [x for x in request.messages[-1].content.splitlines() if x.startswith("===")]
    assert set(lines) <= HEADERS
    if commands.NOTICE_START in request.messages[-1].content:
        assert "kullanıcıya görünmez" in commands.NOTICE_START


def test_stored_messages_hold_only_what_was_said(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage)
    converse(storage, tmp_path, "Bunu unutma: Selin vejetaryen.", "Komşum kim?")

    def read(c: Any) -> list[str]:
        convs = repository.list_conversations(c, limit=5)
        return [m.content for conv in convs for m in repository.messages_between(c, conv.id, 1)]

    for content in storage.db.run_sync(read):
        assert not any(label in content for label in LABELS)
