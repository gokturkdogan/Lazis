"""A synthetic relationship graph for the Phase 7 tests (the ``world`` fixture)."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from lazis.ids import utc_now_iso
from lazis.memory import relationships as rels
from lazis.memory import repository as repo
from lazis.memory.models import USER_ID
from lazis.storage import StorageHandle, driver
from lazis.storage.unit_of_work import UnitOfWork

World = dict[str, str]

PEOPLE = {
    "ahmet": ("Ahmet", "person", "çocukluk arkadaşı"),
    "ahmet2": ("Ahmet", "person", "iş ortağı"),
    "mehmet": ("Mehmet", "person", None),
    "elif": ("Elif", "person", None),
    "deniz": ("Deniz", "person", None),
    "zeynep": ("Zeynep", "person", None),
    "selin": ("Selin", "person", None),
    "ayse": ("Ayşe", "person", "annesi"),
    "fatma": ("Fatma", "person", None),
    "ali": ("Ali", "person", None),
    "can": ("Can", "person", None),
    "kervan": ("Kervan Lojistik", "organization", None),
    "pusula": ("Pusula", "project", None),
    "izmir": ("İzmir", "place", None),
}

EDGES: list[tuple[str, str, str, str]] = [
    ("user", "childhood_friend", "ahmet", "active"),
    ("user", "business_partner", "ahmet2", "active"),
    ("ahmet", "sibling", "mehmet", "active"),
    ("mehmet", "spouse", "elif", "active"),
    ("mehmet", "ex_spouse", "deniz", "active"),
    ("ahmet", "cousin", "zeynep", "active"),
    ("ahmet", "partner", "selin", "active"),  # sensitive
    ("user", "mother", "ayse", "active"),
    ("ayse", "sibling", "fatma", "active"),
    ("ali", "acquaintance", "mehmet", "active"),  # Ali knows Mehmet (one way)
    ("mehmet", "works_at", "kervan", "active"),
    ("mehmet", "works_on", "pusula", "active"),
    ("elif", "works_on", "pusula", "active"),
    ("zeynep", "works_at", "kervan", "ended"),
    ("can", "spouse", "zeynep", "ended"),
    ("mehmet", "lives_in", "izmir", "active"),
]


def run[T](storage: StorageHandle, fn: Callable[[driver.Connection], T]) -> T:
    return storage.db.run_sync(fn)


@pytest.fixture
def world(storage: StorageHandle) -> World:
    def seed(c: driver.Connection) -> World:
        ids: World = {"user": USER_ID}
        now = utc_now_iso()
        with UnitOfWork(c, kind="import", actor="system", summary="seed"):
            for key, (name, kind, relation) in PEOPLE.items():
                e = repo.insert_entity(c, kind=kind, name=name, relation=relation,
                                       description=None, now=now)  # fmt: skip
                ids[key] = e.id
        for s, t, o, status in EDGES:
            rels.add_relationship(c, source_id=ids[s], type=t, target_id=ids[o],
                                  status=status if status != "ended" else "active")  # fmt: skip
            if status == "ended":
                r = rels.gs.relationships_between(c, ids[s], ids[o])[0]
                rels.gs.set_status(c, r.id, "ended", now, ended=True)
        return ids

    return run(storage, seed)
