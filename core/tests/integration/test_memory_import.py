"""Starting-profile import: JSON parsing, the preview (dry run: nothing written), and applying
only the selected items with the user's choices. Synthetic data only."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lazis.memory import importer, service
from lazis.memory import repository as repo
from lazis.memory.models import Candidate, EntityRef
from lazis.memory.service import NotFound, Source
from lazis.storage import StorageHandle

PROFILE: dict[str, Any] = {
    "user": {"occupation": "veri analisti", "technology": ["Python", "SQL"], "location": "Bursa",
             "note": "wifi şifresi Kedi1234Gizli"},
    "people": [
        {"name": "Ahmet", "relation": "iş ortağı", "facts": {"occupation": "avukat"}},
        {"name": "Elif", "relation": "kardeşi", "facts": {"health": "astım"}},
    ],
    "projects": [{"name": "Pusula", "facts": {"project_description": "bütçe uygulaması"}}],
    "ignored": True,
}  # fmt: skip


def seed(storage: StorageHandle) -> None:
    cands = [
        Candidate(predicate="location", value="İzmir", statement="Kullanıcı İzmir'de yaşıyor."),
        Candidate(predicate="technology", value="Python", statement="Kullanıcı Python kullanıyor."),
        Candidate(predicate="occupation", value="yazılımcı", statement="Ahmet yazılımcı.", about="entity",
                  entity=EntityRef("Ahmet", relation="çocukluk arkadaşı")),
    ]  # fmt: skip
    storage.db.run_sync(
        lambda c: service.apply_candidates(c, cands, source=Source("import"), explicit=True)
    )


def test_json_is_parsed_into_candidates_with_errors_reported() -> None:
    cands, errors = importer.parse_json(json.dumps({"user": {"occupation": "x", "favourite": "y"}}))
    assert [(c.predicate, c.value, c.statement) for c in cands] == [
        ("occupation", "x", "Kullanıcı — meslek: x")
    ]
    assert errors == ["bilinmeyen alan: favourite"]
    with pytest.raises(importer.ImportFormatError):
        importer.parse_json("[1, 2]")
    with pytest.raises(importer.ImportFormatError):
        importer.parse_json("{")


def test_preview_classifies_everything_and_writes_nothing(storage: StorageHandle) -> None:
    seed(storage)
    cands, _ = importer.parse_json(json.dumps(PROFILE))
    before = storage.db.run_sync(lambda c: repo.count_memories(c))
    batch, items = storage.db.run_sync(lambda c: importer.create_batch(c, cands, source="json"))
    assert storage.db.run_sync(lambda c: repo.count_memories(c)) == before
    status = {
        (i.candidate.predicate, i.candidate.value): (i.status, i.reason, i.sensitive) for i in items
    }
    assert status[("occupation", "veri analisti")] == ("new", None, False)
    assert status[("technology", "Python")][0] == "duplicate"
    assert status[("technology", "SQL")][0] == "new"
    assert status[("location", "Bursa")][0] == "conflict"  # one current city: the user decides
    assert status[("note", "wifi şifresi Kedi1234Gizli")][:2] == ("excluded", "secret")
    assert status[("occupation", "avukat")][0] == "ambiguous"  # another Ahmet is stored
    assert status[("health", "astım")] == ("new", None, True)  # flagged sensitive
    assert status[("project_description", "bütçe uygulaması")][0] == "new"
    ambiguous = next(i for i in items if i.status == "ambiguous")
    assert [o["label"] for o in ambiguous.options] == ["Ahmet (çocukluk arkadaşı)"]
    view = ambiguous.view()
    assert view["predicate_label"] == "meslek" and view["subject"] == "Ahmet (iş ortağı)"
    open_batch = storage.db.run_sync(lambda c: repo.get_inbox(c, batch))
    assert open_batch is not None and open_batch.type == "import_batch"


def test_only_selected_items_are_applied(storage: StorageHandle) -> None:
    seed(storage)
    cands, _ = importer.parse_json(json.dumps(PROFILE))
    batch, items = storage.db.run_sync(lambda c: importer.create_batch(c, cands, source="json"))
    idx = {(i.candidate.predicate, i.candidate.value): i.index for i in items}
    choices = {
        idx[("occupation", "veri analisti")]: "apply",
        idx[("location", "Bursa")]: "replace",
        idx[("occupation", "avukat")]: "new",  # a different Ahmet
        idx[("note", "wifi şifresi Kedi1234Gizli")]: "apply",  # still excluded
        idx[("project_description", "bütçe uygulaması")]: "apply",
    }
    report = storage.db.run_sync(lambda c: importer.apply_batch(c, batch, choices))
    assert len(report.created) == 4 and report.dropped == {"secret": 1}
    memories = storage.db.run_sync(lambda c: repo.list_memories(c, limit=50))
    values = {m.value for m in memories}
    assert {"veri analisti", "Bursa", "avukat", "bütçe uygulaması"} <= values
    assert "İzmir" not in values and "SQL" not in values and "astım" not in values  # not selected
    old_city = storage.db.run_sync(lambda c: repo.list_memories(c, status="superseded"))
    assert [m.value for m in old_city] == ["İzmir"]
    assert len(storage.db.run_sync(lambda c: repo.find_entities(c, "ahmet"))) == 2
    assert all("Kedi1234" not in m.content for m in memories)
    assert all(m.origin == "imported" for m in memories if m.value in {"veri analisti", "Bursa"})
    with pytest.raises(NotFound):  # applied once; the batch is closed
        storage.db.run_sync(lambda c: importer.apply_batch(c, batch, choices))


def test_choices_are_required_where_the_user_must_decide(storage: StorageHandle) -> None:
    seed(storage)
    cands, _ = importer.parse_json(json.dumps(PROFILE))
    batch, items = storage.db.run_sync(lambda c: importer.create_batch(c, cands, source="json"))
    conflict = next(i.index for i in items if i.status == "conflict")
    with pytest.raises(ValueError, match="replace or both"):
        storage.db.run_sync(lambda c: importer.apply_batch(c, batch, {conflict: "apply"}))
    # Nothing was written by the refused attempt.
    assert {m.value for m in storage.db.run_sync(lambda c: repo.list_memories(c))} == {
        "İzmir",
        "Python",
        "yazılımcı",
    }


def test_a_discarded_batch_leaves_no_trace(storage: StorageHandle) -> None:
    cands, _ = importer.parse_json(json.dumps({"user": {"occupation": "GİZLİ-MESLEK-91"}}))
    batch, _ = storage.db.run_sync(lambda c: importer.create_batch(c, cands, source="json"))
    storage.db.run_sync(lambda c: importer.discard_batch(c, batch))
    assert storage.db.run_sync(lambda c: repo.get_inbox(c, batch)) is None
    rows = storage.db.run_sync(
        lambda c: c.execute("SELECT COUNT(*) FROM memory_inbox").fetchone()[0]
    )
    assert rows == 0
