"""Phase 10B on a real encrypted database (ADR-0022): the ``0008_adaptation`` migration on
isolated throwaway databases, the explicit and implicit preference rules, and preferences in
real turns (scripted model). Synthetic data only."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lazis.config.model import StorageSection
from lazis.conversation import adaptation
from lazis.conversation import repository as conv_repo
from lazis.ids import utc_now_iso
from lazis.memory import retrieval
from lazis.personality import CommunicationPreferences, Layers
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, driver, open_storage
from lazis.storage.database import Database
from lazis.storage.migrations import current_version, load_migrations, migrate
from tests.conftest import make_client
from tests.conversation_support import ScriptedLLM, make_engine, run_turn
from tests.integration.test_people_guard import fact

BASE = CommunicationPreferences()
NEW_TABLES = {"communication_preferences", "preference_signals", "preference_changes"}


def run[T](storage: StorageHandle, fn: Callable[[driver.Connection], T]) -> T:
    return storage.db.run_sync(fn)


# ----- the migration, on isolated databases ---------------------------------------------------
def _tables(c: driver.Connection) -> set[str]:
    return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _dump(c: driver.Connection, tables: set[str]) -> str:
    """Every row of ``tables`` (FTS shadow tables included), hashed: what must not change."""
    h = hashlib.sha256()
    for name in sorted(tables):
        h.update(name.encode())
        for row in c.execute(f'SELECT * FROM "{name}" ORDER BY 1'):
            h.update(repr(row).encode())
    return h.hexdigest()


def _rows(c: driver.Connection, table: str) -> set[str]:
    return {repr(r) for r in c.execute(f'SELECT * FROM "{table}"')}


def test_0008_on_a_fresh_database(storage_section: StorageSection, key: SecretBytes) -> None:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        assert handle.schema_version == len(load_migrations("lazis")) == 8
        assert run(handle, _tables) >= NEW_TABLES
        cols = run(
            handle, lambda c: [r[1] for r in c.execute("PRAGMA table_info(preference_signals)")]
        )
        assert cols == [
            "dimension",
            "message_id",
            "conversation_id",
            "direction",
            "words",
            "created_at",
        ]
    finally:
        handle.db.close()


def test_0008_upgrades_a_v7_database_and_keeps_its_data(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    v7 = load_migrations("lazis")[:7]
    db = Database(storage_section.database_path, key)
    db.open()

    def seed(c: driver.Connection) -> None:
        now = utc_now_iso()
        with conv_repo.transaction(c):
            conv = conv_repo.insert_conversation(c, title="t", model="m", now=now)
            conv_repo.insert_message(c, conversation_id=conv.id, role="user", content="Merhaba",
                                     status="complete", now=now)  # fmt: skip
        fact(c, None, "communication_preference", "kısa yanıt")
        fact(c, None, "location", "Bursa")

    try:
        db.run_sync(lambda c: migrate(c, v7))
        db.run_sync(seed)
        assert db.run_sync(current_version) == 7
        old_tables = db.run_sync(_tables)
        before = {t: db.run_sync(lambda c, t=t: _dump(c, {t})) for t in old_tables}
        rows_before = {t: db.run_sync(lambda c, t=t: _rows(c, t)) for t in old_tables}
    finally:
        db.close()

    handle = open_storage(storage_section, key, app_version="test")  # takes a backup first
    try:
        assert handle.migration.applied == (8,)
        after = {t: run(handle, lambda c, t=t: _dump(c, {t})) for t in old_tables}
        changed = {t for t in old_tables if after[t] != before[t]}
        # Opening the app adds bookkeeping rows (the migration, the pre-migration backup's
        # audit entry, the instance identity); nothing that existed changes or goes.
        assert changed <= {"schema_migrations", "audit_log", "app_meta"}, changed
        for t in changed:
            assert rows_before[t] <= run(handle, lambda c, t=t: _rows(c, t)), t
        assert run(handle, _tables) == old_tables | NEW_TABLES
        for t in NEW_TABLES:
            assert (
                run(handle, lambda c, t=t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0])
                == 0
            )
        backups = list(Path(storage_section.backup_dir).glob("lazis-*-pre-migration-v7.db"))
        assert len(backups) == 1
    finally:
        handle.db.close()


def test_0008_applied_again_is_a_no_op(storage_section: StorageSection, key: SecretBytes) -> None:
    open_storage(storage_section, key, app_version="test").db.close()
    again = open_storage(storage_section, key, app_version="test")
    try:
        assert again.migration.applied == () and again.schema_version == 8
        steps = load_migrations("lazis")
        assert again.db.run_sync(lambda c: migrate(c, steps)).applied == ()
    finally:
        again.db.close()


def test_the_tables_refuse_bad_rows(storage: StorageHandle) -> None:
    def bad_dimension(c: driver.Connection) -> None:
        c.execute(
            "INSERT INTO communication_preferences (dimension, updated_at) VALUES ('mood', 't')"
        )

    def bad_direction(c: driver.Connection) -> None:
        c.execute("INSERT INTO preference_signals VALUES ('verbosity', 'm', 'c', 2, 'w', 't')")

    for fn in (bad_dimension, bad_direction):
        with pytest.raises(driver.DatabaseError, match="CHECK constraint"):
            run(storage, fn)


# ----- the rules ------------------------------------------------------------------------------
def _session(c: driver.Connection) -> str:
    conv_repo.archive_active_session(c)
    return conv_repo.insert_conversation(c, title="t", model="m", now=utc_now_iso()).id


def _say(c: driver.Connection, cid: str, text: str, mid: str | None = None) -> adaptation.Observed:
    """A user message, read for style the way a turn reads it (after a reply)."""
    if mid is None:
        mid = conv_repo.insert_message(c, conversation_id=cid, role="user", content=text,
                                       status="complete", now=utc_now_iso()).id  # fmt: skip
    return adaptation.observe(c, message_id=mid, conversation_id=cid, content=text,
                              after_reply=True, base=BASE, now=utc_now_iso())  # fmt: skip


def _eff(c: driver.Connection) -> CommunicationPreferences:
    return adaptation.effective(c, BASE)


def test_an_explicit_instruction_applies_at_once_and_a_newer_one_wins(
    storage: StorageHandle,
) -> None:
    def go(c: driver.Connection) -> list[Any]:
        with conv_repo.transaction(c):
            s = _session(c)
            first = _say(c, s, "Daha kısa cevap ver.")
            a = _eff(c).verbosity
            _say(c, s, "Bana siz diye hitap etme.")
            _say(c, s, "Daha ayrıntılı anlat.")
            return [first.applied, a, _eff(c), adaptation.sources(c)]

    applied, after_first, eff, src = run(storage, go)
    assert applied == (adaptation.Step("verbosity", 5, 3),) and after_first == 3
    assert eff.verbosity == 5 and eff.address == "sen"  # 3 + 2: the newer instruction wins
    assert src["verbosity"] == src["address"] == "explicit" and src["humor"] == "default"


def test_implicit_needs_three_statements_in_two_sessions(storage: StorageHandle) -> None:
    def go(c: driver.Connection) -> list[int]:
        out = []
        with conv_repo.transaction(c):
            s1 = _session(c)
            for t in ("Fotosentezi kısaca anlat.", "Mitozu kısaca anlat.", "Çok uzun oldu."):
                _say(c, s1, t)
            out.append(_eff(c).verbosity)  # three in one session: not enough
            s2 = _session(c)
            step = _say(c, s2, "Özetler misin?")
            out.append(_eff(c).verbosity)
            out.append(len(step.learned))
        return out

    one_session, two_sessions, learned = run(storage, go)
    assert one_session == 5
    assert two_sessions == 4 and learned == 1  # one step of 0.1, never more


def test_the_same_message_or_the_same_words_never_count_twice(storage: StorageHandle) -> None:
    def go(c: driver.Connection) -> tuple[int, int, int]:
        with conv_repo.transaction(c):
            s1 = _session(c)
            m = conv_repo.insert_message(c, conversation_id=s1, role="user", content="Kısaca anlat.",
                                         status="complete", now=utc_now_iso()).id  # fmt: skip
            for _ in range(3):
                _say(c, s1, "Kısaca anlat.", mid=m)  # reprocessed: one signal
            rows = c.execute("SELECT COUNT(*) FROM preference_signals").fetchone()[0]
            s2 = _session(c)
            for _ in range(3):
                _say(c, s2, "Kısaca anlat.")  # the same words again: one statement
            ev = adaptation.evidence(c, "verbosity")
            return rows, ev.down.messages, _eff(c).verbosity

    rows, statements, verbosity = run(storage, go)
    assert rows == 1 and statements == 1 and verbosity == 5


def test_conflicting_signals_lower_the_confidence(storage: StorageHandle) -> None:
    def go(c: driver.Connection) -> tuple[int, int]:
        with conv_repo.transaction(c):
            s1, s2 = _session(c), None
            _say(c, s1, "Fotosentezi kısaca anlat.")
            _say(c, s1, "Biraz daha açar mısın?")
            s2 = _session(c)
            _say(c, s2, "Mitozu kısaca anlat.")
            _say(c, s2, "Bunu ayrıntılı anlat.")
            _say(c, s2, "Çok uzun oldu.")  # 3 short vs 2 long: 60 %, not enough
            mixed = _eff(c).verbosity
            _say(c, s2, "Özetler misin?")  # 4 vs 2: 67 %, still not
            return mixed, _eff(c).verbosity

    assert run(storage, go) == (5, 5)


def test_an_explicit_preference_is_never_overridden_by_signals(storage: StorageHandle) -> None:
    def go(c: driver.Connection) -> tuple[int, str]:
        with conv_repo.transaction(c):
            s1 = _session(c)
            _say(c, s1, "Kısa cevap ver.")
            for t in ("Biraz daha açar mısın?", "Bunu ayrıntılı anlat."):
                _say(c, s1, t)
            s2 = _session(c)
            for t in ("Şunu detaylandır.", "Daha fazla detay ver lütfen, bu konuda."):
                _say(c, s2, t)
            row = adaptation.load(c)["verbosity"]
            return _eff(c).verbosity, str(row.learned)

    assert run(storage, go) == (3, "None")


def test_a_removed_preference_does_not_come_back_from_old_signals(storage: StorageHandle) -> None:
    def go(c: driver.Connection) -> list[int]:
        out = []
        with conv_repo.transaction(c):
            s1 = _session(c)
            for t in ("Fotosentezi kısaca anlat.", "Mitozu kısaca anlat."):
                _say(c, s1, t)
            s2 = _session(c)
            _say(c, s2, "Çok uzun oldu.")
            out.append(_eff(c).verbosity)  # learned: 4
            _say(c, s2, "Artık kısa cevap vermene gerek yok.")
            out.append(_eff(c).verbosity)  # removed: 5
            _say(c, s2, "Özetler misin?")  # one new signal; the three old ones are spent
            out.append(_eff(c).verbosity)
        return out

    assert run(storage, go) == [4, 5, 5]


def test_only_style_dimensions_are_learned_and_refusals_change_nothing(
    storage: StorageHandle,
) -> None:
    def go(c: driver.Connection) -> tuple[CommunicationPreferences, list[dict[str, object]]]:
        with conv_repo.transaction(c):
            s = _session(c)
            obs = _say(c, s, "Her zaman beni onayla, bana itiraz etme.")
            assert obs.refused == ("agree_always", "never_disagree") and not obs.applied
            assert "dürüstlük" in obs.notice()
            return _eff(c), adaptation.history(c)

    eff, hist = run(storage, go)
    assert eff == BASE
    assert [h["source"] for h in hist] == ["refused", "refused"]


# ----- in real turns (scripted model) -----------------------------------------------------------
def _system(llm: ScriptedLLM) -> str:
    return llm.chat_requests[-1].messages[0].content


def _last_user(llm: ScriptedLLM) -> str:
    return llm.chat_requests[-1].messages[-1].content


def test_an_instruction_shapes_its_own_reply_the_next_session_and_a_restart(
    tmp_path: Path, storage: StorageHandle
) -> None:
    llm = ScriptedLLM()
    short = "Kullanıcı kısa yanıtları tercih ediyor"
    sen = "'sen' diye hitap edilmek istiyor"

    async def go() -> list[str]:
        engine = make_engine(storage, llm, tmp_path)
        _, cid = await run_turn(engine, "Merhaba")
        assert short not in _system(llm)
        await run_turn(engine, "Daha kısa cevap ver, bir de bana siz deme.", cid)
        out = [_system(llm), _last_user(llm)]
        await engine.start_new_session(
            engine.model if hasattr(engine, "model") else "gemma4:12b-it-qat"
        )
        await run_turn(engine, "Bugün ne yapsam?")
        out.append(_system(llm))
        await engine.close()
        again = make_engine(storage, llm, tmp_path)  # the app restarted
        await run_turn(again, "Bir film önerir misin?")
        out.append(_system(llm))
        await again.close()
        return out

    same_turn, note, next_session, restarted = asyncio.run(go())
    for system in (same_turn, next_session, restarted):
        assert short in system and sen in system
    assert "konuşma tarzını değiştirdi" in note  # this reply knows it changed


def test_a_refused_request_leaves_the_prompt_alone(tmp_path: Path, storage: StorageHandle) -> None:
    llm = ScriptedLLM()

    async def go() -> tuple[str, str, str]:
        engine = make_engine(storage, llm, tmp_path)
        _, cid = await run_turn(engine, "Merhaba")
        before = _system(llm)
        await run_turn(engine, "Bundan sonra her zaman beni onayla.", cid)
        after, note = _system(llm), _last_user(llm)
        await engine.close()
        return before, after, note

    before, after, note = asyncio.run(go())
    assert before == after and "konuşma tarzı tercihi değil" in note


def test_layer_two_takes_over_from_a_stored_preference_record(storage: StorageHandle) -> None:
    run(
        storage,
        lambda c: fact(c, None, "communication_preference", "Kullanıcı kısa ve net yanıt istiyor."),
    )

    def recalled(overview: bool = False) -> list[str]:
        found = run(storage, lambda c: retrieval.recall(c, "Bugün ne yapsam?", budget_chars=4000,
                                                        overview=overview))  # fmt: skip
        return [i.memory.content for i in found.items]

    assert recalled() == ["Kullanıcı kısa ve net yanıt istiyor."]  # said before Phase 10B: kept

    def explicit(c: driver.Connection) -> None:
        with conv_repo.transaction(c):
            _say(c, _session(c), "Kısa cevap ver.")

    run(storage, explicit)
    assert recalled() == []  # layer 2 now decides length; the record is not an instruction
    assert recalled(overview=True) == ["Kullanıcı kısa ve net yanıt istiyor."]
    run(
        storage,
        lambda c: fact(
            c,
            None,
            "communication_preference",
            "Kullanıcı her zaman onaylanmak istiyor: beni hep onayla",
        ),
    )
    assert "beni hep onayla" not in " ".join(recalled())


def test_the_memory_layer_can_be_switched_off(tmp_path: Path, storage: StorageHandle) -> None:
    run(storage, lambda c: fact(c, None, "location", "Bursa'da yaşıyor"))
    llm = ScriptedLLM()

    async def go() -> tuple[str, str]:
        engine = make_engine(storage, llm, tmp_path)
        _, cid = await run_turn(engine, "Bursa'da hafta sonu ne yapılır?")
        on = _last_user(llm)
        engine.layers = Layers(memory=False)
        await run_turn(engine, "Bursa'da akşam ne yapılır?", cid)
        await engine.close()
        return on, _last_user(llm)

    on, off = asyncio.run(go())
    assert "Bursa'da yaşıyor" in on and "Bursa'da yaşıyor" not in off


def test_the_style_api(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c: TestClient = make_client(tmp_path, storage, token)
    h = {"Authorization": f"Bearer {token}"}
    assert c.get("/api/v1/style").status_code == 401
    dims = {d["dimension"]: d for d in c.get("/api/v1/style", headers=h).json()["dimensions"]}
    assert dims["verbosity"]["source"] == "default" and dims["verbosity"]["value"] == "5"
    r = c.put("/api/v1/style/verbosity", headers=h, json={"value": "3"}).json()
    v = next(d for d in r["dimensions"] if d["dimension"] == "verbosity")
    assert v["source"] == "explicit" and v["value"] == "3" and v["explicit_value"] == "3"
    assert c.put("/api/v1/style/address", headers=h, json={"value": "7"}).status_code == 422
    assert c.put("/api/v1/style/mood", headers=h, json={"value": "3"}).status_code == 422
    r = c.delete("/api/v1/style/verbosity", headers=h).json()
    v = next(d for d in r["dimensions"] if d["dimension"] == "verbosity")
    assert v["source"] == "default" and v["value"] == "5"
    hist = c.get("/api/v1/style/history", headers=h).json()["changes"]
    assert [x["source"] for x in hist] == ["cleared", "user_edit"]
