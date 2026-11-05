"""Phase 10C, first version: one fixed question about the user's own topic, on a greeting after a long
gap. Real turns on the production engine with a scripted model, and a real database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from lazis.conversation import continuity
from lazis.conversation import repository as conv_repo
from lazis.ids import utc_now_iso
from lazis.memory import repository as repo
from lazis.memory import service
from lazis.storage import StorageHandle, driver
from lazis.storage.unit_of_work import UnitOfWork
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.integration.test_claims_in_turns import shown_prefixes

HELLO = "Merhaba efendim, size nasıl yardımcı olabilirim?"
OFFER = "«Python öğrenmek» konusuna devam etmek ister misiniz?"


def memory(
    storage: StorageHandle,
    *,
    predicate: str = "goal",
    value: str = "Python öğrenmek",
    quote: str | None = "Python öğrenmek istiyorum.",
    subject_id: str | None = None,
    origin: str = "stated",
    confidence: float = 0.85,
    importance: float = 0.7,
    sensitivity: str = "normal",
    days_old: int = 2,
    event_time: str | None = None,
) -> str:
    def write(c: driver.Connection) -> str:
        now = (datetime.now(UTC) - timedelta(days=days_old)).isoformat()
        with UnitOfWork(c, kind="user_edit", actor="user", summary="seed") as uow:
            m = repo.insert_memory(
                c, kind="fact", subject_id=subject_id, predicate=predicate, value=value, content=value, keywords="",
                status="active", origin=origin, confidence=confidence, importance=importance, sensitivity=sensitivity,  # type: ignore[arg-type]
                sensitivity_category=None, event_time=event_time, valid_from=None, supersedes_id=None,
                change_set_id=uow.change_set_id, now=now,
            )  # fmt: skip
            if quote is not None:
                repo.add_evidence(
                    c, m.id, source_type="user_edit", source_ref=None, quote=quote, now=now
                )
        return m.id

    return storage.db.run_sync(write)


def age_messages(storage: StorageHandle, hours: float) -> None:
    then = (datetime.now(UTC) - timedelta(hours=hours)).isoformat()
    storage.db.run_sync(lambda c: c.execute("UPDATE messages SET created_at = ?", (then,)))


async def turn(
    storage: StorageHandle,
    tmp_path: Path,
    message: str,
    *,
    cid: str | None = None,
    reply: str = HELLO,
    on: bool = True,
) -> tuple[list[dict[str, Any]], str, str, ScriptedLLM]:
    llm = ScriptedLLM(reply=lambda r: reply, chunk_size=4)
    engine = make_engine(storage, llm, tmp_path, continuity_followups=on)
    events, conv = await run_turn(engine, message, cid)
    await engine.close()
    stored = storage.db.run_sync(lambda c: conv_repo.messages_between(c, conv, 1))[-1].content
    return events, conv, stored, llm


def earlier_message_then_gap(storage: StorageHandle, tmp_path: Path, hours: float = 7) -> str:
    _, cid, _, _ = asyncio.run(turn(storage, tmp_path, "Bugün hava güzel."))
    age_messages(storage, hours)
    return cid


def greet(storage: StorageHandle, tmp_path: Path, cid: str, message: str = "Merhaba") -> str:
    return asyncio.run(turn(storage, tmp_path, message, cid=cid))[2]


# ----- when ---------------------------------------------------------------------------------------
def test_after_six_hours_a_greeting_gets_one_short_question(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == f"{HELLO}\n\n{OFFER}"


def test_before_six_hours_nothing_is_offered(tmp_path: Path, storage: StorageHandle) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path, hours=5.9)
    assert greet(storage, tmp_path, cid) == HELLO


def test_a_normal_message_after_six_hours_is_not_interrupted(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid, "Selam, bütçem ne kadardı?") == HELLO


def test_the_very_first_message_has_nothing_to_come_back_to(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(storage)
    assert asyncio.run(turn(storage, tmp_path, "Merhaba"))[2] == HELLO


def test_it_is_off_unless_turned_on(tmp_path: Path, storage: StorageHandle) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert asyncio.run(turn(storage, tmp_path, "Merhaba", cid=cid, on=False))[2] == HELLO


# ----- what ---------------------------------------------------------------------------------------
def test_no_safe_topic_gives_a_plain_greeting(tmp_path: Path, storage: StorageHandle) -> None:
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


@pytest.mark.parametrize(
    "kw",
    [
        {"predicate": "plan", "value": "Bursa'ya taşınmak"},
        {"predicate": "health", "value": "kilo vermek"},
        {"predicate": "finance", "value": "araba almak"},
        {"predicate": "birthday", "value": "doğum günü"},
        {"value": "20 bin TL biriktirmek"},
        {"value": "Mayısta sınava girmek"},
        {"value": "yarın toplantı yapmak"},
        {"value": "çok uzun bir hedefin çok uzun bir anlatımı olan cümlesi burada"},
        {"value": "annemle tatil yapmak"},
        {"quote": "Galiba Python öğrenmek istiyorum."},
        {"quote": "Belki Python öğrenirim, henüz kesin değil."},
        {"quote": "Eskiden Python öğrenmek istiyordum."},
        {"quote": "Seneye Python öğreneceğim."},
        {"quote": None},
        {"confidence": 0.55},
        {"origin": "inferred"},
        {"origin": "imported"},
        {"sensitivity": "sensitive"},
        {"sensitivity": "personal"},
        {"days_old": 31},
        {"event_time": "2026-12-01"},
    ],
    ids=lambda kw: str(next(iter(kw.values())))[:24],
)
def test_nothing_doubtful_old_dated_or_private_is_offered(
    tmp_path: Path, storage: StorageHandle, kw: dict[str, Any]
) -> None:
    memory(storage, **kw)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


def test_someone_elses_goal_is_not_offered(tmp_path: Path, storage: StorageHandle) -> None:
    now = utc_now_iso()

    def person(c: driver.Connection) -> str:
        with UnitOfWork(c, kind="import", actor="system", summary="seed"):
            return repo.insert_entity(
                c, kind="person", name="Mehmet", relation="friend", description=None, now=now
            ).id

    memory(storage, subject_id=storage.db.run_sync(person))
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


def test_a_topic_naming_a_stored_person_is_not_offered(
    tmp_path: Path, storage: StorageHandle
) -> None:
    now = utc_now_iso()

    def person(c: driver.Connection) -> None:
        with UnitOfWork(c, kind="import", actor="system", summary="seed"):
            e = repo.insert_entity(
                c, kind="person", name="Mehmet", relation="friend", description=None, now=now
            )
            repo.add_alias(c, e.id, "Mehmet")

    storage.db.run_sync(person)
    memory(storage, value="Mehmet ile iş kurmak")
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


def test_a_superseded_topic_is_not_offered(tmp_path: Path, storage: StorageHandle) -> None:
    mid = memory(storage)
    storage.db.run_sync(
        lambda c: c.execute("UPDATE memories SET status = 'superseded' WHERE id = ?", (mid,))
    )
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


def test_a_forgotten_topic_is_not_offered(tmp_path: Path, storage: StorageHandle) -> None:
    mid = memory(storage)
    storage.db.run_sync(lambda c: service.forget_memories(c, [mid]))
    cid = earlier_message_then_gap(storage, tmp_path)
    assert greet(storage, tmp_path, cid) == HELLO


def test_a_topic_forgotten_after_it_was_chosen_once_stays_out(
    tmp_path: Path, storage: StorageHandle
) -> None:
    keep = memory(
        storage,
        value="satranç",
        predicate="interest",
        quote="Satranca ilgi duyuyorum.",
        importance=0.1,
    )
    mid = memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert OFFER in greet(storage, tmp_path, cid)
    storage.db.run_sync(lambda c: service.forget_memories(c, [mid]))
    age_messages(storage, 7)
    assert "satranç" in greet(storage, tmp_path, cid)
    assert keep


def test_only_one_topic_and_the_most_important_first(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(
        storage,
        value="satranç",
        predicate="interest",
        quote="Satranca ilgi duyuyorum.",
        importance=0.3,
    )
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    out = greet(storage, tmp_path, cid)
    assert out.count("konusuna devam") == 1 and OFFER in out


# ----- afterwards ---------------------------------------------------------------------------------
def test_the_same_topic_is_not_offered_again(tmp_path: Path, storage: StorageHandle) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert OFFER in greet(storage, tmp_path, cid)
    age_messages(storage, 7)
    assert greet(storage, tmp_path, cid) == HELLO


def test_turning_it_down_leaves_a_normal_reply_and_it_does_not_come_back(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert OFFER in greet(storage, tmp_path, cid)
    refusal = asyncio.run(
        turn(storage, tmp_path, "Hayır, istemiyorum.", cid=cid, reply="Tabii efendim.")
    )
    assert refusal[2] == "Tabii efendim."
    age_messages(storage, 7)
    assert greet(storage, tmp_path, cid) == HELLO


def test_it_survives_closing_and_opening_the_app(tmp_path: Path, storage: StorageHandle) -> None:
    """Each turn here is a new engine on the same database, as after a restart."""
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    assert OFFER in greet(storage, tmp_path, cid)
    assert storage.db.run_sync(continuity._offered)  # kept in the database, not in the engine
    age_messages(storage, 24)
    assert greet(storage, tmp_path, cid) == HELLO


def test_the_user_can_go_on_with_it_since_the_model_sees_what_was_asked(
    tmp_path: Path, storage: StorageHandle
) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    greet(storage, tmp_path, cid)
    _, _, stored, llm = asyncio.run(
        turn(storage, tmp_path, "Evet, devam edelim.", cid=cid, reply="Elbette efendim.")
    )
    assert stored == "Elbette efendim."
    assert any(OFFER in m.content for m in llm.chat_requests[-1].messages if m.role == "assistant")


def test_it_keeps_ids_and_no_text(tmp_path: Path, storage: StorageHandle) -> None:
    mid = memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)
    greet(storage, tmp_path, cid)
    row = storage.db.run_sync(
        lambda c: c.execute(
            "SELECT value FROM app_meta WHERE key = 'continuity_offered'"
        ).fetchone()
    )
    assert mid in row[0] and "Python" not in row[0]


# ----- what it costs, and what it does not touch ----------------------------------------------------
def test_no_model_call_is_added_and_the_prompt_does_not_change(
    tmp_path: Path, storage: StorageHandle
) -> None:
    cid = earlier_message_then_gap(storage, tmp_path)
    plain = asyncio.run(turn(storage, tmp_path, "Merhaba", cid=cid, on=False))[3]
    age_messages(storage, 7)
    memory(storage)
    with_topic = asyncio.run(turn(storage, tmp_path, "Merhaba", cid=cid))
    assert OFFER in with_topic[2]
    assert len(with_topic[3].chat_requests) == len(plain.chat_requests) == 1
    system = with_topic[3].chat_requests[0].messages[0].content
    assert "konusuna devam" not in system and "Python" not in system


@pytest.mark.parametrize("chunk", [1, 3, 64])
def test_streamed_shown_and_stored_are_the_same_text(
    tmp_path: Path, storage: StorageHandle, chunk: int
) -> None:
    memory(storage)
    cid = earlier_message_then_gap(storage, tmp_path)

    async def go() -> tuple[list[dict[str, Any]], str]:
        llm = ScriptedLLM(reply=lambda r: HELLO, chunk_size=chunk)
        engine = make_engine(storage, llm, tmp_path, continuity_followups=True)
        events, conv = await run_turn(engine, "Merhaba", cid)
        await engine.close()
        return events, storage.db.run_sync(lambda c: conv_repo.messages_between(c, conv, 1))[
            -1
        ].content

    events, stored = asyncio.run(go())
    done = next(e for e in events if e["type"] == "done")["message"]["content"]
    assert shown_prefixes(events)[-1] == stored == done == f"{HELLO}\n\n{OFFER}"


# ----- greeting -----------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "text",
    ["Merhaba", "selam!", "Günaydın", "İyi akşamlar", "Selam LAZIS", "Merhaba, nasılsın?", "hey"],
)
def test_a_greeting(text: str) -> None:
    assert continuity.is_greeting(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Selam, bütçem ne kadardı?",
        "Merhaba, yarın toplantım var",
        "Nasılsın?",
        "Ne haber",
        "Python öğrenmek istiyorum",
        "Selam selam selam selam selam selam",
    ],
)
def test_not_only_a_greeting(text: str) -> None:
    assert not continuity.is_greeting(text)


def test_sen_is_respected() -> None:
    assert (
        continuity.sentence("Python öğrenmek", address="sen")
        == "«Python öğrenmek» konusuna devam etmek ister misin?"
    )
