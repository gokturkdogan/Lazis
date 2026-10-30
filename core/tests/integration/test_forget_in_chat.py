"""Forgetting from chat finds the record the user means (Phase 9.1). The command answers are
real Gemma outputs from the Phase 9.1 stage A probe (where "Kahve bilgimi sil" and "Telefon
bilgimi unut" found nothing: the model left the forget fields empty). A wrong deletion is
worse than none: several possible records are asked about. Production engine, encrypted
database; synthetic data only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from lazis.memory import service
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.conversation_support import ScriptedLLM, make_engine
from tests.integration.test_memory_commands import answer, last_user
from tests.learning_support import state

# Real outputs (probe_stageA.json, 2026-10-30, gemma4:12b-it-qat).
KAHVE = (
    '{"action":"forget","items":[{"message":"m1","quote":"Kahve bilgimi sil.","entity":"kahve",'
    '"relation":"","predicate":"interest","value":"","statement":"Kullanıcı kahve ile ilgili '
    'bilgilerin silinmesini istedi.","change":true,"replaces":"::","certain":true,"sensitive":"", '
    '"importance":1}],"relations":[],"forget_scope":"fact","forget_entity":"","forget_relation":"",'
    '"forget_predicate":"","forget_value":"", "forget_other":"", "forget_type":""}'
)
KAHVE_KAYDI = (
    '{"action":"forget","items":[{"message":"m1","quote":"Kahve hakkındaki kaydını unut.",'
    '"entity":"kahve","relation":"","predicate":"likes","value":"filtre kahve","statement":"x",'
    '"change":true,"replaces":"::","certain":true,"sensitive":"", "importance":1}],"relations":[],'
    '"forget_scope":"fact","forget_entity":"","forget_relation":"","forget_predicate":"",'
    '"forget_value":"", "forget_other":"", "forget_type":""}'
)
TELEFON = (
    '{"action":"forget","items":[{"message":"m1","quote":"Telefon bilgimi unut.","entity":"phone",'
    '"relation":"","predicate":"phone","value":"Pixel 8","statement":"x","change":true,"replaces":"::",'
    '"certain":true,"sensitive":"", "importance":1}],"relations":[], "forget_scope":"fact",'
    '"forget_entity":"","forget_relation":"","forget_predicate":"","forget_value":"", '
    '"forget_other":"", "forget_type":""}'
)
ELIF = (
    '{"action":"forget","items":[],"relations":[],"forget_scope":"fact","forget_entity":"Elif",'
    '"forget_relation":"sibling","forget_predicate":"location","forget_value":"İzmir","forget_other":"", '
    '"forget_type":""}'
)
EMPTY = answer("forget", forget_scope="fact")


def seed(storage: StorageHandle, *facts: tuple[str, str, str, str]) -> None:
    """(predicate, value, statement, who) — who "" is the user."""
    for predicate, value, statement, who in facts:
        c = Candidate(predicate=predicate, value=value, statement=statement,
                      **({"about": "entity", "entity": EntityRef(who, "person")} if who else {}))  # fmt: skip
        storage.db.run_sync(lambda conn, c=c: service.apply_candidates(
            conn, [c], source=Source("import"), explicit=True))  # fmt: skip


def history(
    storage: StorageHandle, predicate: str, value: str, statement: str, who: str = ""
) -> None:
    seed(storage, (predicate, value, statement, who))
    s = state(storage)
    mid = next(f["id"] for f in s.facts if f["value"] == value)
    storage.db.run_sync(lambda c: c.execute(
        "UPDATE memories SET status = 'superseded' WHERE id = ?", (mid,)))  # fmt: skip


def say(tmp_path: Path, storage: StorageHandle, message: str, command: str) -> tuple[str, str]:
    llm = ScriptedLLM(command=lambda r: command)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> str:
        from tests.conversation_support import run_turn

        await run_turn(engine, message, None)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if engine.scheduler.background is None and not engine._learn and not engine.is_busy():  # pyright: ignore[reportPrivateUsage]
                break
        outcome = str((engine.last_turn or {}).get("memory_outcome") or "")
        await engine.close()
        return outcome

    outcome = asyncio.run(go())
    return outcome, last_user(llm.chat_requests[-1])


def values(storage: StorageHandle) -> set[tuple[str, str, str]]:
    return {(f["who"], f["predicate"], f["value"]) for f in state(storage).facts}


COFFEE = ("habit", "şekersiz kahve", "Kullanıcı kahveyi şekersiz içer.", "")
TEA = ("likes", "yeşil çay", "Kullanıcı yeşil çayı sever.", "")
PHONE = ("phone", "Pixel 8", "Kullanıcının telefonu Pixel 8.", "")
CITY = ("location", "İstanbul", "Kullanıcı İstanbul'da yaşıyor.", "")
ATLAS = ("employer", "Atlas", "Kullanıcı Atlas'ta çalışıyor.", "")


@pytest.mark.parametrize(
    ("message", "command", "gone"),
    [
        ("Kahve bilgimi sil.", KAHVE, COFFEE),
        ("Kahve tercihimle ilgili bilgiyi sil.", EMPTY, COFFEE),
        ("Kahve hakkındaki kaydını unut.", KAHVE_KAYDI, COFFEE),
        ("Telefon bilgimi unut.", TELEFON, PHONE),
        ("Telefon modelimi hafızandan kaldır.", EMPTY, PHONE),
        ("İstanbul'da yaşadığım bilgisini unut.", EMPTY, CITY),
        ("Çalıştığım yerle ilgili bilgiyi sil.", EMPTY, ATLAS),
    ],
)  # fmt: skip
def test_the_record_meant_is_found_and_only_it_is_deleted(
    tmp_path: Path, storage: StorageHandle, message: str, command: str, gone: tuple[str, ...]
) -> None:
    seed(storage, COFFEE, TEA, PHONE, CITY, ATLAS)
    outcome, notice = say(tmp_path, storage, message, command)
    assert outcome == "forgotten", notice
    left = values(storage)
    assert ("user", gone[0], gone[1]) not in left
    assert len(left) == 4  # nothing else


def test_the_old_workplace_only(tmp_path: Path, storage: StorageHandle) -> None:
    history(storage, "employer", "Kervan", "Kullanıcı Kervan'da çalışıyordu.")
    seed(storage, ATLAS)
    outcome, _ = say(tmp_path, storage, "Eski işyerimle ilgili bilgiyi sil.", EMPTY)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "employer", "Atlas")}


def test_the_current_workplace_only(tmp_path: Path, storage: StorageHandle) -> None:
    history(storage, "employer", "Kervan", "Kullanıcı Kervan'da çalışıyordu.")
    seed(storage, ATLAS)
    outcome, _ = say(tmp_path, storage, "Güncel işyeri bilgimi sil.", EMPTY)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "employer", "Kervan")}


def test_a_relatives_city_with_a_relation_the_model_made_up(
    tmp_path: Path, storage: StorageHandle
) -> None:
    seed(storage, ("location", "İzmir", "Elif İzmir'de yaşıyor.", "Elif"), CITY)
    outcome, _ = say(tmp_path, storage, "Elif'in nerede yaşadığını unut.", ELIF)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "location", "İstanbul")}


def test_several_records_on_one_topic_are_asked_about(
    tmp_path: Path, storage: StorageHandle
) -> None:
    seed(storage, COFFEE, ("likes", "filtre kahve", "Kullanıcı filtre kahveyi sever.", ""))
    outcome, notice = say(tmp_path, storage, "Kahve bilgimi sil.", KAHVE)
    assert outcome == "ambiguous"
    assert "şekersiz" in notice and "filtre kahve" in notice  # the options, to ask
    assert len(values(storage)) == 2  # nothing deleted on a guess


def test_all_of_them_when_the_user_says_so(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, COFFEE, ("likes", "filtre kahve", "Kullanıcı filtre kahveyi sever.", ""), PHONE)
    outcome, _ = say(tmp_path, storage, "Kahveyle ilgili tüm bilgileri sil.", EMPTY)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "phone", "Pixel 8")}


def test_one_of_them_named_more_closely(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, COFFEE, ("likes", "filtre kahve", "Kullanıcı filtre kahveyi sever.", ""))
    outcome, _ = say(tmp_path, storage, "Şekersiz kahve bilgimi sil.", EMPTY)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "likes", "filtre kahve")}


@pytest.mark.parametrize("message", ["Şu bilgiyi sil.", "Onu unut.", "Bunu hafızandan kaldır."])
def test_an_unclear_request_deletes_nothing(
    tmp_path: Path, storage: StorageHandle, message: str
) -> None:
    seed(storage, COFFEE, PHONE)
    outcome, _ = say(tmp_path, storage, message, EMPTY)
    assert outcome in ("not_found", "nothing", "ambiguous")
    assert len(values(storage)) == 2


def test_a_record_that_is_not_there(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, COFFEE, PHONE)
    outcome, notice = say(tmp_path, storage, "Araba bilgimi sil.", EMPTY)
    assert outcome == "not_found" and "eşleşen bir kayıt bulunamadı" in notice
    assert len(values(storage)) == 2


def test_what_was_deleted_is_not_learned_again(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, PHONE)
    learned = json.dumps({"items": [{"message": "m1", "quote": "Telefon bilgimi unut", "entity": "",
                                     "relation": "", "predicate": "phone", "value": "bilinmiyor",
                                     "statement": "x", "change": True, "replaces": "", "certain": True,
                                     "sensitive": "", "importance": 0.5}], "relations": []})  # fmt: skip
    llm = ScriptedLLM(command=lambda r: TELEFON, memory=lambda r: learned)
    engine = make_engine(storage, llm, tmp_path)

    async def go() -> Any:
        from tests.conversation_support import run_turn

        await run_turn(engine, "Telefon bilgimi unut.", None)
        for _ in range(300):
            await asyncio.sleep(0.01)
            if engine.scheduler.background is None and not engine._learn and not engine.is_busy():  # pyright: ignore[reportPrivateUsage]
                break
        await engine.close()

    asyncio.run(go())
    assert values(storage) == set()  # gone, and the request itself taught nothing ("bilinmiyor")
    assert llm.memory_requests == []


def test_someone_elses_thing_is_never_the_users(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, PHONE)
    outcome, _ = say(tmp_path, storage, "Elif'in telefonunu sil.", EMPTY)
    assert outcome == "not_found"  # no Elif: the user's phone stays
    assert values(storage) == {("user", "phone", "Pixel 8")}


def test_a_field_with_several_values_is_asked_about(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, ("contact", "0555 000 00 00", "Ahmet'in telefon numarası 0555 000 00 00.", "Ahmet"),
         ("contact", "ahmet@example.invalid", "Ahmet'in e-postası ahmet@example.invalid.", "Ahmet"))  # fmt: skip
    outcome, _ = say(tmp_path, storage, "Ahmet'in iletişim bilgisini sil.", EMPTY)
    assert outcome == "ambiguous"
    assert len(values(storage)) == 2


def test_a_friends_record_by_name(tmp_path: Path, storage: StorageHandle) -> None:
    seed(storage, ("location", "İzmir", "Elif İzmir'de yaşıyor.", "Elif"), CITY)
    outcome, _ = say(tmp_path, storage, "Elif'in yaşadığı şehir bilgisini sil.", EMPTY)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "location", "İstanbul")}


def test_a_thing_the_model_gave_as_a_person_is_the_users_topic(
    tmp_path: Path, storage: StorageHandle
) -> None:
    # Phase 9.1 run 1 (d18): forget_scope "entity", forget_entity "kahve".
    cmd = answer("forget", forget_scope="entity", forget_entity="kahve")
    seed(storage, COFFEE, PHONE)
    outcome, _ = say(tmp_path, storage, "Kahveyle ilgili tüm bilgileri sil.", cmd)
    assert outcome == "forgotten"
    assert values(storage) == {("user", "phone", "Pixel 8")}


def test_a_name_still_being_asked_about_is_not_guessed(
    tmp_path: Path, storage: StorageHandle
) -> None:
    # Phase 9.1 run 1 (d16): "Arkadaşım Ahmet mimar." stored; "Komşum Ahmet doktor." waiting for
    # "which Ahmet?" — "Ahmet'in mesleğini unut" deleted the stored one's job.
    from lazis.memory import repository as repo

    seed(storage, ("occupation", "mimar", "Ahmet mimar.", "Ahmet"))
    storage.db.run_sync(lambda c: repo.insert_inbox(
        c, type="ambiguous_entity", summary="Hangi Ahmet? — Ahmet doktor.",
        payload={"candidate": {"entity": {"name": "Ahmet"}}, "pending_names": ["ahmet"], "options": []},
        now="2026-10-30T00:00:00Z"))  # fmt: skip
    cmd = answer(
        "forget", forget_scope="topic", forget_entity="Ahmet", forget_predicate="occupation"
    )
    outcome, notice = say(tmp_path, storage, "Ahmet'in mesleğini unut.", cmd)
    assert outcome == "ambiguous" and "Hiçbir şey silinmedi" in notice
    assert "henüz kaydedilmedi" in notice  # the other Ahmet is not "in the records"
    assert values(storage) == {("Ahmet", "occupation", "mimar")}
