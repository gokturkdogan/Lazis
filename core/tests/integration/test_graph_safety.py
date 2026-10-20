"""Phase 7 safety: migration on a new install and on a corrupted v4 database, integrity after
the upgrade, the label upgrade at engine start, forgetting without multi-hop leaks, sensitive
relationships, and no relationship content in logs. Synthetic data only."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from lazis.config.model import StorageSection
from lazis.errors import DatabaseCorruptError, DatabaseKeyError
from lazis.memory import graph, retrieval, service
from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID
from lazis.security.secrets import SecretBytes
from lazis.storage import StorageHandle, driver, open_storage
from lazis.storage.migrations import load_migrations
from tests.conversation_support import ScriptedLLM, make_engine
from tests.graph_support import World
from tests.integration.test_graph_store import _v4_with_memory


# ----- migration --------------------------------------------------------------------------
def test_a_new_install_has_the_graph_and_one_user(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    handle = open_storage(storage_section, key, app_version="p7")
    try:
        assert handle.schema_version == len(load_migrations("lazis"))
        users = handle.db.run_sync(
            lambda c: c.execute("SELECT id, name FROM memory_entities WHERE is_user = 1").fetchall()
        )
        assert [tuple(u) for u in users] == [(USER_ID, "Kullanıcı")]
        assert (
            handle.db.run_sync(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"
        )
        assert handle.db.run_sync(lambda c: c.execute("PRAGMA foreign_key_check").fetchall()) == []
        assert handle.db.run_sync(rels.backfill_user_relations) == {
            "labels": 0, "converted": 0, "kept_as_label": 0}  # fmt: skip
        with pytest.raises(driver.DatabaseError):  # one user row only
            handle.db.run_sync(lambda c: c.execute(
                "INSERT INTO memory_entities (id, kind, name, name_key, status, created_at,"
                " updated_at, is_user) VALUES ('x', 'person', 'X', 'x', 'active', '', '', 1)"))  # fmt: skip
        with pytest.raises(driver.DatabaseError):  # no self-relationship
            handle.db.run_sync(lambda c: c.execute(
                "INSERT INTO memory_relationships (id, source_id, type, target_id, status, origin,"
                " confidence, sensitivity, conflict_state, version, created_at, updated_at)"
                " VALUES ('r', 'user', 'friend', 'user', 'active', 'stated', 1, 'normal', 'none',"
                " 1, '', '')"))  # fmt: skip
    finally:
        handle.db.close()


def test_the_upgrade_passes_the_integrity_check(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _v4_with_memory(storage_section, key)
    up = open_storage(storage_section, key, app_version="p7")
    try:
        assert up.db.run_sync(lambda c: c.execute("PRAGMA integrity_check").fetchone()[0]) == "ok"
        tables = up.db.run_sync(
            lambda c: {r[0] for r in c.execute("SELECT name FROM sqlite_master")}
        )
        assert {
            "memory_relationships",
            "memory_relationship_evidence",
            "memory_entity_distinctions",
        } <= tables
        assert "memory_entities_new" not in tables
    finally:
        up.db.close()


def test_a_corrupted_v4_database_is_refused_not_migrated(
    storage_section: StorageSection, key: SecretBytes
) -> None:
    _v4_with_memory(storage_section, key)
    path = storage_section.database_path
    data = bytearray(path.read_bytes())
    for offset in range(4096, min(len(data), 4096 + 4096)):
        data[offset] ^= 0xFF
    path.write_bytes(bytes(data))
    before = path.read_bytes()
    with pytest.raises((DatabaseCorruptError, DatabaseKeyError)):
        open_storage(storage_section, key, app_version="p7")
    assert path.read_bytes() == before  # neither repaired nor half-migrated


# ----- forgetting and privacy ---------------------------------------------------------------
def test_a_forgotten_link_breaks_every_multi_hop_answer(
    storage: StorageHandle, world: World
) -> None:
    run = storage.db.run_sync
    run(lambda c: rels.forget_pair(c, world["ahmet"], world["mehmet"]))
    chain = run(lambda c: graph.ask(c, "Çocukluk arkadaşımın kardeşinin eşi kim?"))
    assert chain is not None and chain.status == "none"
    assert "Mehmet" not in " ".join(chain.lines) and "Elif" not in " ".join(chain.lines)
    assert run(lambda c: graph.paths_between(c, USER_ID, world["elif"])) == []
    block = retrieval.render(
        run(lambda c: retrieval.recall(c, "Elif'i nereden tanıyorum?", budget_chars=4000))
    )
    assert "Ahmet" not in block  # no path through the forgotten link
    nodes, _, _ = run(lambda c: graph.neighbourhood(c, USER_ID, depth=2))
    assert world["mehmet"] not in nodes


def test_a_forgotten_person_is_gone_from_paths_maps_and_recall(
    storage: StorageHandle, world: World
) -> None:
    run = storage.db.run_sync
    run(lambda c: service.forget_entity(c, world["ahmet"]))
    assert run(lambda c: gs.relationships_of(c, world["ahmet"])) == []
    nodes, edges, _ = run(lambda c: graph.neighbourhood(c, USER_ID, depth=2))
    assert world["ahmet"] not in nodes and all(
        world["ahmet"] not in (e.source_id, e.target_id) for e in edges
    )
    block = retrieval.render(
        run(lambda c: retrieval.recall(c, "Zeynep'i nereden tanıyorum?", budget_chars=4000))
    )
    assert "Ahmet" not in block and "kayıtlı bir bağlantı yok" in block


def test_sensitive_relationships_never_leak_through_other_questions(
    storage: StorageHandle, world: World
) -> None:
    run = storage.db.run_sync
    for q in ("Selin'i nereden tanıyorum?", "Selin kim?", "Ahmet ile Selin arasında ne var?",
              "Çocukluk arkadaşım Ahmet'in kimlerle bağlantısı var?", "Zeynep'in kimlerle bağlantısı var?"):  # fmt: skip
        block = retrieval.render(run(lambda c, q=q: retrieval.recall(c, q, budget_chars=4000)))
        assert "sevgili" not in block, q
    nodes, _, _ = run(lambda c: graph.neighbourhood(c, world["ahmet"], depth=2))
    assert world["selin"] not in nodes
    asked = run(lambda c: graph.ask(c, "Çocukluk arkadaşım Ahmet'in sevgilisi kim?"))
    assert asked is not None and asked.results == (world["selin"],)


def test_forgotten_relationship_text_is_gone_from_history(
    storage: StorageHandle, world: World
) -> None:
    run = storage.db.run_sync
    rid = run(lambda c: gs.relationships_between(c, world["mehmet"], world["elif"]))[0].id
    run(lambda c: rels.edit_relationship(c, rid, type="spouse", qualifier="GİZLİ-NOT-77",
                                         status="active", time_text=None))  # fmt: skip
    run(lambda c: rels.forget_relationships(c, [rid]))

    from tests.integration.test_graph_store import dump

    assert "GİZLİ-NOT-77" not in dump(storage)


def test_no_relationship_content_in_logs(
    tmp_path: Path, storage: StorageHandle, world: World, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    from tests.integration.test_graph_chat import answer, rel
    from tests.integration.test_memory_commands import turns

    cmd = answer("remember", relations=[rel("Zeynep'in kardeşi Kaan", "Zeynep", "sibling", "Kaan")])
    llm = ScriptedLLM(command=lambda r: cmd)
    engine = make_engine(storage, llm, tmp_path)
    asyncio.run(
        turns(
            engine,
            "Bunu kaydet: Zeynep'in kardeşi Kaan.",
            "Çocukluk arkadaşımın kardeşinin eşi kim?",
        )
    )
    logged = "\n".join(r.getMessage() + " " + repr(r.__dict__) for r in caplog.records)
    for secret in ("Kaan", "Zeynep", "Elif", "kardeş"):
        assert secret not in logged, secret
    names = {e.name for e in storage.db.run_sync(lambda c: repo.list_entities(c))}
    assert "Kaan" in names  # the request was carried out; only the logs are clean


def test_the_label_upgrade_runs_once_at_engine_start(
    tmp_path: Path, storage_section: StorageSection, key: SecretBytes
) -> None:
    _v4_with_memory(storage_section, key)
    up = open_storage(storage_section, key, app_version="p7")
    try:
        engine = make_engine(up, ScriptedLLM(), tmp_path)

        async def go() -> dict[str, object]:
            diag = await engine.diagnostics()
            await engine.close()
            return diag

        diag = asyncio.run(go())
        assert diag["memory"]["graph_backfill"] == {"labels": 1, "converted": 1, "kept_as_label": 0}  # type: ignore[index]
        assert diag["memory"]["relationships"] == {"active": 1}  # type: ignore[index]
        assert up.db.run_sync(rels.backfill_user_relations) is None
    finally:
        up.db.close()
