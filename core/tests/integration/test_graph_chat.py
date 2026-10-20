"""Relationships in chat: relationship questions answered from the graph in the memory block,
relationships of named people in recall, explicit relationship requests (remember, deny,
correct, forget), "same person" / "different people". Scripted model, synthetic people."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from lazis.memory import commands, graph, retrieval
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID
from lazis.storage import StorageHandle
from tests.graph_support import World
from tests.integration.test_memory_commands import last_user, run


def recall_block(storage: StorageHandle, message: str, **kw: Any) -> str:
    found = storage.db.run_sync(
        lambda c: retrieval.recall(c, message, budget_chars=kw.pop("budget", 6000), **kw)
    )
    return retrieval.render(found)


# ----- recall -------------------------------------------------------------------------------
def test_a_relationship_question_brings_the_computed_answer(
    storage: StorageHandle, world: World
) -> None:
    block = recall_block(storage, "Çocukluk arkadaşımın kardeşinin eşi kim?")
    assert "İlişki sorusu (kayıtlı ilişkilerden hesaplandı" in block
    assert "- Cevap: Elif" in block
    assert "- Dayanak: Ahmet: kullanıcının çocukluk arkadaşı → Mehmet: Ahmet'in kardeşi" in block


def test_no_record_is_said_not_guessed(storage: StorageHandle, world: World) -> None:
    block = recall_block(storage, "Kuzenimin eşi kim?")
    assert "kullanıcının kuzeni kişisel hafızada kayıtlı değil. Tahmin etme." in block


def test_ambiguous_start_asks(storage: StorageHandle, world: World) -> None:
    block = recall_block(storage, "Ahmet'in kardeşi kim?")
    assert "Hafızada birden fazla «Ahmet» var" in block and "Mehmet" not in block


def test_named_people_bring_their_relationships(storage: StorageHandle, world: World) -> None:
    block = recall_block(storage, "Mehmet yarın bize gelecek.")
    assert "Mehmet:\n" in block
    assert "- İlişki: Ahmet: Mehmet'in kardeşi" in block
    assert "Selin" not in block  # sensitive, and not asked


def test_unknown_names_in_general_questions_add_nothing(
    storage: StorageHandle, world: World
) -> None:
    assert recall_block(storage, "Google'ın patronu kim?") == ""
    assert "«Burak» adlı bir kayıt yok" in recall_block(storage, "Burak'ın kardeşi kim?")


def test_overview_lists_the_users_relationships(storage: StorageHandle, world: World) -> None:
    block = recall_block(storage, "Hakkımda ne biliyorsun?", overview=True)
    assert "- İlişki: Ahmet: kullanıcının çocukluk arkadaşı" in block
    assert "- İlişki: Ayşe: kullanıcının annesi" in block


def test_relation_lines_respect_the_budget(storage: StorageHandle, world: World) -> None:
    assert recall_block(storage, "Mehmet yarın gelecek.", budget=20) == ""


# ----- cues ---------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("message", "intent"),
    [
        ("Ahmet benim kuzenim değil.", "correct"),
        ("Ahmet ile Mehmet kardeş değil.", "correct"),
        ("Elif ile Mehmet evli değil.", "correct"),
        ("Bu iki Ahmet aynı kişi.", "same"),
        ("Ahmet ile Memo aynı kişi aslında.", "same"),
        ("Bu iki Ahmet aynı kişi mi?", None),
        ("Bunlar farklı kişiler.", "different"),
        ("İki Ahmet aynı kişi değil.", "different"),
        ("Kardeşim değil miydi o?", None),
        ("Mehmet'in kardeşi kim?", None),
    ],
)
def test_relationship_cues(message: str, intent: str | None) -> None:
    assert commands.detect(message) == intent


# ----- explicit requests --------------------------------------------------------------------
def answer(action: str, **kw: Any) -> str:
    base: dict[str, Any] = {"action": action, "items": [], "relations": [], "forget_scope": "",
                            "forget_entity": "", "forget_relation": "", "forget_predicate": "",
                            "forget_value": "", "forget_other": "", "forget_type": ""}  # fmt: skip
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


def rel(quote: str, source: str, type_: str, target: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"message": "m1", "quote": quote, "source": source,
                            "source_relation": "", "source_kind": "person", "type": type_,
                            "target": target, "target_relation": "", "target_kind": "person",
                            "negated": False, "correction": False, "change": False,
                            "status": "active", "certain": True, "time": "", "statement": ""}  # fmt: skip
    base.update(kw)
    return base


def relationships(storage: StorageHandle) -> list[tuple[str, str, str, str]]:
    def read(c: Any) -> list[tuple[str, str, str, str]]:
        out: list[tuple[str, str, str, str]] = []
        for r in gs.list_relationships(c, limit=500):
            s, t = repo.get_entity(c, r.source_id), repo.get_entity(c, r.target_id)
            out.append((s.name if s else "?", r.type, t.name if t else "?", r.status))
        return sorted(out)

    return storage.db.run_sync(read)


def test_remembering_a_relationship_says_what_was_written(
    tmp_path: Path, storage: StorageHandle
) -> None:
    msg = "Bunu kaydet: Ahmet'in kardeşi Mehmet."
    cmd = answer(
        "remember", relations=[rel("Ahmet'in kardeşi Mehmet", "Ahmet", "sibling", "Mehmet")]
    )
    llm, _ = run(storage, tmp_path, lambda r: cmd, msg)
    assert relationships(storage) == [("Ahmet", "sibling", "Mehmet", "active")]
    prompt = last_user(llm.chat_requests[0])
    assert "Kaydedildi (veritabanına yazıldı):\n- Mehmet: Ahmet'in kardeşi" in prompt
    assert "İlişki türleri (type):" in llm.command_requests[0].messages[-1].content


def test_denying_a_relationship_retracts_it(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    msg = "Ahmet ile Zeynep kuzen değil."
    cmd = answer("correct", relations=[rel("Ahmet ile Zeynep kuzen değil", "Ahmet", "cousin",
                                           "Zeynep", source_relation="çocukluk arkadaşı",
                                           negated=True)])  # fmt: skip
    llm, _ = run(storage, tmp_path, lambda r: cmd, msg)
    assert ("Ahmet", "cousin", "Zeynep", "retracted") in relationships(storage)
    prompt = last_user(llm.chat_requests[0])
    assert "artık geçerli değil (geri alındı): Zeynep: Ahmet'in kuzeni" in prompt


def test_correcting_a_relationship_keeps_the_old_one_as_history(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    msg = "Yanlış hatırlıyorsun, Zeynep çocukluk arkadaşım değil, iş arkadaşım."
    cmd = answer("correct", relations=[
        rel("Zeynep çocukluk arkadaşım değil", "", "childhood_friend", "Zeynep", negated=True),
        rel("iş arkadaşım", "", "colleague", "Zeynep", correction=True),
    ])  # fmt: skip
    llm, _ = run(storage, tmp_path, lambda r: cmd, msg)
    assert ("Kullanıcı", "colleague", "Zeynep", "active") in relationships(storage)
    assert "Düzeltildi" in last_user(llm.chat_requests[0])


def test_forgetting_a_relationship(tmp_path: Path, storage: StorageHandle, world: World) -> None:
    msg = "Elif ile Mehmet arasındaki ilişkiyi unut."
    cmd = answer("forget", forget_scope="relation", forget_entity="Elif", forget_other="Mehmet")
    llm, _ = run(storage, tmp_path, lambda r: cmd, msg)
    assert not [r for r in relationships(storage) if {r[0], r[2]} == {"Elif", "Mehmet"}]
    assert "Silindi" in last_user(llm.chat_requests[0])
    # …and it is not learned again from the same pair.
    pair = storage.db.run_sync(lambda c: gs.pair_fingerprint(c, world["elif"], world["mehmet"]))
    assert storage.db.run_sync(lambda c: repo.is_suppressed(c, [pair]))


def test_forgetting_one_type_keeps_the_others(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    cmd = answer("forget", forget_scope="relation", forget_entity="Mehmet", forget_other="Kervan Lojistik",
                 forget_type="works_at")  # fmt: skip
    run(storage, tmp_path, lambda r: cmd, "Mehmet'in Kervan Lojistik'te çalıştığını unut.")
    assert ("Mehmet", "works_at", "Kervan Lojistik", "active") not in relationships(storage)
    assert ("Mehmet", "works_on", "Pusula", "active") in relationships(storage)


# ----- identity -----------------------------------------------------------------------------
def test_different_people_are_kept_apart(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Bu iki Ahmet farklı kişiler.")
    assert llm.command_requests == []  # deterministic
    assert storage.db.run_sync(lambda c: gs.are_distinct(c, world["ahmet"], world["ahmet2"]))
    assert "farklı kişiler; bir daha karıştırılmayacak" in last_user(llm.chat_requests[0])


def test_same_person_merges_after_confirmation(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Bu iki Ahmet aynı kişi.", "Evet.")
    first, second = (last_user(r) for r in llm.chat_requests)
    assert "Henüz silinmedi — kullanıcının onayı gerekiyor:" in first
    assert "Ahmet (çocukluk arkadaşı) ile Ahmet (iş ortağı) birleştirilecek" in first
    assert "Birleştirildi" in second
    left = storage.db.run_sync(lambda c: repo.find_entities(c, "ahmet"))
    assert [e.id for e in left] == [world["ahmet"]]
    types = {
        r.type
        for r in storage.db.run_sync(lambda c: gs.relationships_between(c, USER_ID, world["ahmet"]))
    }
    assert types == {"childhood_friend", "business_partner"}


def test_same_person_is_refused_after_a_distinction(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    run(storage, tmp_path, lambda r: answer("none"), "Bu iki Ahmet farklı kişiler.")
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), "Bu iki Ahmet aynı kişi.")
    assert "Kaydedilmedi:" in last_user(llm.chat_requests[0])
    assert len(storage.db.run_sync(lambda c: repo.find_entities(c, "ahmet"))) == 2


def test_merge_can_be_declined(tmp_path: Path, storage: StorageHandle, world: World) -> None:
    run(storage, tmp_path, lambda r: answer("none"), "Bu iki Ahmet aynı kişi.", "Hayır, vazgeç.")
    assert len(storage.db.run_sync(lambda c: repo.find_entities(c, "ahmet"))) == 2


def test_graph_names_in_a_message(storage: StorageHandle, world: World) -> None:
    found = storage.db.run_sync(lambda c: graph.message_names(c, "Ahmet ile Mehmet aynı kişi"))
    assert found == [(world["ahmet"], world["ahmet2"]), (world["mehmet"],)]


def test_a_relationship_question_in_a_real_turn(
    tmp_path: Path, storage: StorageHandle, world: World
) -> None:
    msg = "Çocukluk arkadaşımın kardeşinin eşi kim?"
    llm, _ = run(storage, tmp_path, lambda r: answer("none"), msg)
    prompt = last_user(llm.chat_requests[0])
    assert prompt.startswith(retrieval.BLOCK_START) and prompt.endswith(msg)
    assert "- Cevap: Elif" in prompt
    assert commands.NOTICE_START not in prompt  # a question: no memory operation, no notice
    assert llm.command_requests == []
