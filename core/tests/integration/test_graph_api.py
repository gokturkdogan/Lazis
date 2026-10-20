"""The relationship API end to end (authenticated client, encrypted database): vocabulary, an
entity's relationships read from its side, detail with evidence and history, add / edit /
forget, the relation map's neighbourhood, paths, relationship decisions. Synthetic people."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from lazis.memory import graphstore as gs
from lazis.memory import relationships as rels
from lazis.memory.models import USER_ID, EntityRef, RelCandidate
from lazis.memory.service import Source
from lazis.storage import StorageHandle
from tests.conftest import make_client
from tests.graph_support import World

API = "/api/v1/memory"


def client(tmp_path: Path, storage: StorageHandle, token: str) -> tuple[TestClient, dict[str, str]]:
    return make_client(tmp_path, storage, token), {"Authorization": f"Bearer {token}"}


def test_requires_the_session_token(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c, _ = client(tmp_path, storage, token)
    assert c.get(f"{API}/relationship-types").status_code == 401
    assert c.get(f"{API}/entities/user/relationships").status_code == 401


def test_vocabulary(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c, h = client(tmp_path, storage, token)
    types = {t["key"]: t for t in c.get(f"{API}/relationship-types", headers=h).json()["types"]}
    assert types["sibling"]["symmetric"] and types["sibling"]["label"] == "kardeşi"
    assert types["partner"]["sensitivity"] == "sensitive"
    assert types["works_at"]["target_kinds"] == ["organization", "group"]


def test_relationships_read_from_each_side(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    c, h = client(tmp_path, storage, token)
    mine = c.get(f"{API}/entities/user/relationships", headers=h).json()["relationships"]
    readings = {(r["other"]["name"], r["reading"]) for r in mine}
    assert ("Ahmet", "çocukluk arkadaşı") in readings and ("Ayşe", "annesi") in readings
    ayse = c.get(f"{API}/entities/{world['ayse']}/relationships", headers=h).json()["relationships"]
    assert ("Kullanıcı", "çocuğu") in {(r["other"]["name"], r["reading"]) for r in ayse}
    kervan = c.get(f"{API}/entities/{world['kervan']}/relationships", headers=h).json()
    by_other = {r["other"]["name"]: r for r in kervan["relationships"]}
    assert by_other["Mehmet"]["reading"] == "çalışanı" and by_other["Mehmet"]["status"] == "active"
    assert by_other["Zeynep"]["status"] == "ended"  # past relationships are listed, marked
    assert by_other["Mehmet"]["text"] == "Kervan Lojistik: Mehmet'in çalıştığı yer"
    mehmet = c.get(f"{API}/entities/{world['mehmet']}/relationships", headers=h).json()
    ali = next(r for r in mehmet["relationships"] if r["other"]["name"] == "Ali")
    assert ali["reading"] is None  # one-way: Ali knows Mehmet


def test_add_edit_history_and_forget(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    c, h = client(tmp_path, storage, token)
    r = c.post(f"{API}/relationships", headers=h,
               json={"source_id": world["zeynep"], "type": "colleague", "target_id": world["elif"]})  # fmt: skip
    assert r.status_code == 200 and r.json()["created"] == 1
    rel = next(x for x in c.get(f"{API}/entities/{world['elif']}/relationships", headers=h).json()["relationships"]
               if x["type"] == "colleague")  # fmt: skip
    assert rel["origin"] == "user_edit" and rel["reading"] == "iş arkadaşı"

    edited = c.patch(f"{API}/relationships/{rel['id']}", headers=h,
                     json={"type": "friend", "status": "ended", "time_text": "2020'ye kadar"})  # fmt: skip
    assert edited.status_code == 200 and edited.json()["type"] == "friend"
    assert edited.json()["status"] == "ended" and edited.json()["valid_to"] is not None
    detail = c.get(f"{API}/relationships/{rel['id']}", headers=h).json()
    assert [e["source_type"] for e in detail["evidence"]] == ["user_edit", "user_edit"]

    gone = c.delete(f"{API}/relationships/{rel['id']}", headers=h)
    assert gone.json() == {"memories": 1, "entities": 0}
    assert c.get(f"{API}/relationships/{rel['id']}", headers=h).status_code == 404


def test_types_must_fit_the_entities(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    c, h = client(tmp_path, storage, token)
    bad = c.post(f"{API}/relationships", headers=h,
                 json={"source_id": world["mehmet"], "type": "sibling", "target_id": world["kervan"]})  # fmt: skip
    assert bad.status_code == 422
    unknown = c.post(f"{API}/relationships", headers=h,
                     json={"source_id": world["mehmet"], "type": "nemesis", "target_id": world["ali"]})  # fmt: skip
    assert unknown.status_code == 422


def test_neighbourhood_for_the_map(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    c, h = client(tmp_path, storage, token)
    one = c.get(f"{API}/graph/neighbourhood/user", headers=h).json()
    assert {n["name"] for n in one["nodes"]} == {"Kullanıcı", "Ahmet", "Ayşe"}
    two = c.get(f"{API}/graph/neighbourhood/user", headers=h, params={"depth": 2}).json()
    names = {n["name"] for n in two["nodes"]}
    assert {"Mehmet", "Zeynep", "Fatma"} <= names and "Selin" not in names  # sensitive: never
    assert all(e["status"] in ("active", "planned", "unverified") for e in two["edges"])
    past = c.get(f"{API}/graph/neighbourhood/{world['zeynep']}", headers=h, params={"past": True})
    assert "Can" in {n["name"] for n in past.json()["nodes"]}
    assert (
        c.get(f"{API}/graph/neighbourhood/user", headers=h, params={"depth": 3}).status_code == 422
    )


def test_paths(tmp_path: Path, storage: StorageHandle, token: str, world: World) -> None:
    c, h = client(tmp_path, storage, token)
    found = c.get(
        f"{API}/graph/paths", headers=h, params={"from": "user", "to": world["elif"]}
    ).json()
    assert found["paths"][0]["steps"] == [
        "Ahmet: kullanıcının çocukluk arkadaşı",
        "Mehmet: Ahmet'in kardeşi",
        "Elif: Mehmet'in eşi",
    ]
    none = c.get(
        f"{API}/graph/paths", headers=h, params={"from": "user", "to": world["selin"]}
    ).json()
    assert none["paths"] == []


def test_relationship_decisions_in_the_inbox(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    c, h = client(tmp_path, storage, token)
    cand = RelCandidate(type="sibling", target=EntityRef("Mehmet"), source=EntityRef("Ahmet"),
                        quote="Ahmet'in kardeşi Mehmet")  # fmt: skip
    storage.db.run_sync(lambda conn: rels.apply_relations(conn, [cand], source=Source("message", "m-x", "conv-x"),
                                                          explicit=False))  # fmt: skip
    items = c.get(f"{API}/inbox", headers=h).json()["items"]
    ask = next(i for i in items if i["about"] == "relationship")
    assert ask["type"] == "ambiguous_entity" and ask["summary"].startswith("Hangi Ahmet?")
    assert {o["label"] for o in ask["options"]} == {
        "Ahmet (çocukluk arkadaşı)",
        "Ahmet (iş ortağı)",
    }
    done = c.post(f"{API}/inbox/{ask['id']}/resolve", headers=h, json={"choice": world["ahmet"]})
    assert done.status_code == 200
    between = storage.db.run_sync(
        lambda conn: gs.relationships_between(conn, world["ahmet"], world["mehmet"])
    )
    assert [r.type for r in between] == ["sibling"]  # the existing one got the new evidence


def test_merge_confirmation_in_the_inbox(
    tmp_path: Path, storage: StorageHandle, token: str, world: World
) -> None:
    from lazis.memory import commands

    storage.db.run_sync(lambda conn: commands.identity(conn, "same", "Bu iki Ahmet aynı kişi",
                                                       conversation_id="conv-x"))  # fmt: skip
    c, h = client(tmp_path, storage, token)
    item = next(
        i for i in c.get(f"{API}/inbox", headers=h).json()["items"] if i["about"] == "merge"
    )
    assert (
        c.post(
            f"{API}/inbox/{item['id']}/resolve", headers=h, json={"choice": "approve"}
        ).status_code
        == 200
    )
    mine = c.get(f"{API}/entities/{USER_ID}/relationships", headers=h).json()["relationships"]
    assert {r["other"]["id"] for r in mine if r["other"]["name"] == "Ahmet"} == {world["ahmet"]}
