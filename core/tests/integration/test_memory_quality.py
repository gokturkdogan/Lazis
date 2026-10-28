"""Memory quality checks, importance tiers and JSON salvage (Phase 9): suggestions only — the
scan never changes the memory; findings come in priority order and can be hidden; tiers are
computed and never a reason to write; a broken answer keeps only its complete objects.
Encrypted database, synthetic data only."""

from __future__ import annotations

from pathlib import Path

import pytest

from lazis.ids import utc_now_iso
from lazis.memory import extraction, importance, quality, service
from lazis.memory import graphstore as gs
from lazis.memory import repository as repo
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.bootstrap_support import snapshot, stored_person
from tests.conftest import make_client


def put(storage: StorageHandle, predicate: str, value: str, *, entity: EntityRef | None = None,
        certain: bool = True, msg: str = "m1", force: str | None = None) -> list[str]:  # fmt: skip
    c = Candidate(predicate=predicate, value=value, statement=f"{value}.", certain=certain,
                  about="user" if entity is None else "entity", entity=entity)  # fmt: skip

    def run(conn: object) -> list[str]:
        from lazis.storage.unit_of_work import UnitOfWork

        if force is None:
            return service.apply_candidates(conn, [c], source=Source("message", msg),  # type: ignore[arg-type]
                                            explicit=True).created  # fmt: skip
        from lazis.memory.models import ApplyReport

        rep = ApplyReport()
        with UnitOfWork(conn, kind="user_edit", actor="user", summary="t") as uow:  # type: ignore[arg-type]
            service.apply_one(conn, uow, c, source=Source("message", msg), explicit=True,  # type: ignore[arg-type]
                              report=rep, now=utc_now_iso(), force=force)  # type: ignore[arg-type]  # fmt: skip
        return rep.created

    return storage.db.run_sync(run)


def scan(storage: StorageHandle) -> list[quality.Finding]:
    return storage.db.run_sync(lambda c: quality.scan(c))


def kinds(storage: StorageHandle) -> list[str]:
    return [f.kind for f in scan(storage)]


def test_an_empty_memory_has_nothing_to_suggest(storage: StorageHandle) -> None:
    assert scan(storage) == []


def test_two_current_values_of_one_fact_are_a_conflict(storage: StorageHandle) -> None:
    put(storage, "location", "Ankara")
    put(storage, "location", "İzmir", force="create", msg="m2")  # "ikisini de tut"
    (f,) = [f for f in scan(storage) if f.kind == "conflict"]
    assert set(f.values) == {"Ankara", "İzmir"} and "Hangisi güncel" in f.title


def test_near_duplicates_are_suggested(storage: StorageHandle) -> None:
    put(storage, "likes", "filtre kahve")
    put(storage, "likes", "filtre kahveler", force="create", msg="m2")
    assert "duplicate" in kinds(storage)


def test_an_old_changing_fact_is_asked_about(storage: StorageHandle) -> None:
    (mid,) = put(storage, "employer", "Kervan Lojistik")
    old = "2024-01-01T00:00:00.000Z"
    storage.db.run_sync(lambda c: c.execute(
        "UPDATE memory_evidence SET created_at = ? WHERE memory_id = ?", (old, mid)))  # fmt: skip
    storage.db.run_sync(lambda c: c.execute(
        "UPDATE memories SET valid_from = ?, created_at = ? WHERE id = ?", (old, old, mid)))  # fmt: skip
    (f,) = [f for f in scan(storage) if f.kind == "stale"]
    assert "Hâlâ geçerli mi" in f.title


def test_two_people_with_one_name_neither_apart_nor_merged(storage: StorageHandle) -> None:
    a = stored_person(storage, "Ahmet", None, {"occupation": "mimar"})
    b = stored_person(storage, "Ahmet", None, {"location": "Bursa"})
    (f,) = [f for f in scan(storage) if f.kind == "ambiguous_person"]
    assert set(f.entity_ids) == {a, b}
    storage.db.run_sync(lambda c: gs.add_distinction(c, a, b, utc_now_iso()))
    assert "ambiguous_person" not in kinds(storage)  # told apart: no question


def test_namesakes_known_apart_by_relation_are_not_asked(storage: StorageHandle) -> None:
    stored_person(storage, "Ahmet", "komşusu", {"occupation": "mimar"})
    stored_person(storage, "Ahmet", "iş arkadaşı", {"occupation": "avukat"})
    assert "ambiguous_person" not in kinds(storage)


def test_uncertain_and_sourceless_facts(storage: StorageHandle) -> None:
    put(storage, "note", "galiba kedisi var", entity=EntityRef("Elif"), certain=False)
    (mid,) = put(storage, "interest", "satranç", msg="m3")
    storage.db.run_sync(lambda c: c.execute("DELETE FROM memory_evidence WHERE memory_id = ?",
                                            (mid,)))  # fmt: skip
    ks = kinds(storage)
    assert "uncertain" in ks and "no_evidence" in ks


def test_the_scan_never_changes_the_memory(storage: StorageHandle) -> None:
    put(storage, "location", "Ankara")
    put(storage, "location", "İzmir", force="create", msg="m2")
    stored_person(storage, "Ahmet", None, {"occupation": "mimar"})
    stored_person(storage, "Ahmet", None, {"location": "Bursa"})
    before = snapshot(storage)
    for _ in range(3):
        scan(storage)
    assert snapshot(storage) == before


def test_the_most_important_doubt_comes_first(storage: StorageHandle) -> None:
    put(storage, "note", "galiba kedisi var", entity=EntityRef("Elif"), certain=False)
    put(storage, "location", "Ankara")
    put(storage, "location", "İzmir", force="create", msg="m2")
    first = scan(storage)[0]
    assert first.kind == "conflict" and first.subject == "Kullanıcı"


def test_a_hidden_suggestion_stays_hidden(storage: StorageHandle) -> None:
    put(storage, "location", "Ankara")
    put(storage, "location", "İzmir", force="create", msg="m2")
    (f,) = [f for f in scan(storage) if f.kind == "conflict"]
    storage.db.run_sync(lambda c: quality.dismiss(c, f.id, f.kind, utc_now_iso()))
    assert "conflict" not in kinds(storage)


def test_the_api_lists_and_hides(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    put(storage, "location", "Ankara")
    put(storage, "location", "İzmir", force="create", msg="m2")
    c, h = make_client(tmp_path, storage, token), {"Authorization": f"Bearer {token}"}
    got = c.get("/api/v1/memory/quality", headers=h).json()["findings"]
    (f,) = [x for x in got if x["kind"] == "conflict"]
    after = c.post(f"/api/v1/memory/quality/{f['id']}/dismiss", headers=h,
                   json={"kind": "conflict"}).json()["findings"]  # fmt: skip
    assert all(x["id"] != f["id"] for x in after)
    rec = c.get("/api/v1/memory/records", headers=h).json()["records"][0]
    assert rec["tier"] == "high" and rec["sources"] == 1
    new = c.get("/api/v1/memory/records", headers=h, params={"new_days": 7}).json()["records"]
    assert len(new) == 2


@pytest.mark.parametrize(
    ("kw", "tier"),
    [
        ({"predicate": "birthday", "importance": 0.7}, "critical_personal"),
        ({"predicate": "health", "importance": 0.7, "sensitivity": "sensitive"},
         "critical_personal"),
        ({"predicate": "note", "importance": 0.5, "origin": "requested"}, "critical_personal"),
        ({"predicate": "occupation", "importance": 0.7}, "high"),
        ({"predicate": "location", "importance": 0.7}, "high"),
        ({"predicate": "project_status", "importance": 0.6, "about_user": False}, "high"),
        ({"predicate": "likes", "importance": 0.6}, "medium"),
        ({"predicate": "likes", "importance": 0.6, "sources": 3}, "high"),
        ({"predicate": "occupation", "importance": 0.6, "about_user": False}, "medium"),
        ({"predicate": "note", "importance": 0.3}, "low"),
        ({"predicate": "interest", "importance": 0.2}, "low"),
        ({"predicate": "note", "importance": 0.9, "durable": False}, "ephemeral"),
        ({"predicate": "likes", "importance": 0.6, "sources": 50}, "high"),  # never critical
    ],
)  # fmt: skip
def test_importance_tiers(kw: dict[str, object], tier: str) -> None:
    assert importance.tier(**kw) == tier  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ('{"items":[{"a":1},{"b":2}],"relations":[{"c":3},{"d":"broke', (2, 1)),
        ('{"items":[{"a":1},{"b":', (1, 0)),
        ('{"items":[],"relations":[{"c":"x.causal_link_id_1"}', (0, 1)),
        ('{"items":[{"a":"} tricky {"}],"relations":[', (1, 0)),
    ],
)
def test_a_broken_answer_keeps_only_its_complete_objects(raw: str, kept: tuple[int, int]) -> None:
    import json

    assert extraction.parse(raw) is None
    fixed = extraction.salvage(raw)
    assert fixed is not None
    data = json.loads(fixed)
    assert (len(data["items"]), len(data["relations"])) == kept


@pytest.mark.parametrize("raw", ["", "bu JSON değil", "[1, 2", '"items"'])
def test_nothing_to_salvage(raw: str) -> None:
    assert extraction.salvage(raw) is None


def test_model_artefacts_never_reach_a_statement() -> None:
    from lazis.memory.extraction import _str  # pyright: ignore[reportPrivateUsage]

    assert _str({"statement": "Annesinin kardeşi Ayşe.causal_link_id_1"}, "statement") == (
        "Annesinin kardeşi Ayşe."
    )
    assert _str({"statement": "Kullanıcı İzmir'de yaşıyor."}, "statement") == (
        "Kullanıcı İzmir'de yaşıyor."
    )


def test_repo_counts_independent_sources(storage: StorageHandle) -> None:
    (mid,) = put(storage, "likes", "çay")
    put(storage, "likes", "çay", msg="m2")
    put(storage, "likes", "çay", msg="m2")  # the same message again
    assert storage.db.run_sync(lambda c: repo.independent_sources(c, mid)) == 2
