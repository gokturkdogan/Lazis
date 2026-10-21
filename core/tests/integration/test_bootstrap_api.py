"""The personal knowledge import API end to end (Phase 8): upload, preview, decisions, apply,
undo, refusals with their own codes. Authenticated test client, encrypted database, synthetic
data only."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lazis.storage import StorageHandle
from tests.bootstrap_support import active, profile_bytes, remember, snapshot
from tests.conftest import make_client

API = "/api/v1/memory/bootstrap"

DOC: dict[str, Any] = {
    "profile": {"name": "Kerem", "city": "İzmir", "occupation": "yazılım geliştirici"},
    "people": [
        {"id": "ak", "name": "Ahmet", "relation": "komşum", "facts": {"occupation": "mimar"}},
        {"id": "ai", "name": "Ahmet", "relation": "iş arkadaşım",
         "facts": {"occupation": "muhasebeci"}},
    ],
    "preferences": ["filtre kahve"],
    "relationships": [{"from": "ak", "type": "sibling", "to": "ai"}],
}  # fmt: skip


def client(tmp_path: Path, storage: StorageHandle, token: str) -> tuple[TestClient, dict[str, str]]:
    return make_client(tmp_path, storage, token), {"Authorization": f"Bearer {token}"}


def upload(c: TestClient, h: dict[str, str], data: bytes, name: str = "profil.json") -> Any:
    return c.post(f"{API}/analyze", headers=h,
                  json={"file_name": name, "content_base64": base64.b64encode(data).decode()})  # fmt: skip


def test_requires_the_session_token(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c, _ = client(tmp_path, storage, token)
    assert c.get(API).status_code == 401
    assert upload(c, {}, profile_bytes(DOC)).status_code == 401


def test_json_import_preview_nothing_approved_and_nothing_written(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    c, h = client(tmp_path, storage, token)
    before = snapshot(storage)
    r = upload(c, h, profile_bytes(DOC))
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["status"] == "ready" and b["format"] == "json" and b["running"] is False
    pv = c.get(f"{API}/{b['id']}", headers=h).json()
    assert {i["decision"] for i in pv["items"]} == {"pending"}
    assert {p["decision"] for p in pv["people"]} == {"pending"}
    assert pv["summary"]["approved"] == 0 and pv["summary"]["writable"] == 0
    assert all(i["excerpt"] and i["line"] and i["section"] for i in pv["items"])
    assert {i["method"] for i in pv["items"]} == {"json"}
    assert snapshot(storage) == before  # analysis writes no memory


def test_decide_apply_undo_round_trip(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c, h = client(tmp_path, storage, token)
    before = snapshot(storage)
    iid = upload(c, h, profile_bytes(DOC)).json()["id"]
    pv = c.get(f"{API}/{iid}", headers=h).json()
    ppl = [{"id": p["id"], "decision": "create"} for p in pv["people"]]
    its = [{"id": i["id"], "decision": "approve"} for i in pv["items"]
           if i["classification"] != "excluded"]  # fmt: skip
    pv = c.post(f"{API}/{iid}/decisions", headers=h, json={"people": ppl, "items": its}).json()
    assert pv["summary"]["writable"] == len(its) and pv["summary"]["blocked"] == 0
    r = c.post(f"{API}/{iid}/apply", headers=h)
    assert r.status_code == 200, r.text
    done = r.json()["batch"]
    assert done["status"] == "applied" and done["counts"]["written"] == len(its)
    assert done["counts"]["people_created"] == 2
    assert ("Ahmet", "occupation", "mimar") in active(storage)
    again = c.post(f"{API}/{iid}/apply", headers=h)
    assert again.status_code == 409 and again.json()["error"]["code"] == "import_already_applied"

    plan = c.get(f"{API}/{iid}/undo-plan", headers=h).json()
    assert plan["counts"]["remove"] >= len(its) and plan["already_undone"] is False
    u = c.post(f"{API}/{iid}/undo", headers=h, json={})
    assert u.status_code == 200 and u.json()["batch"]["status"] == "undone"
    assert u.json()["change_set_id"]
    assert snapshot(storage) == before
    u2 = c.post(f"{API}/{iid}/undo", headers=h, json={}).json()
    assert u2["change_set_id"] is None and u2["plan"]["already_undone"] is True


def test_refusals_have_their_own_codes(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    c, h = client(tmp_path, storage, token)
    bad = upload(c, h, b'{"schema_version": "1.0", "profile": {"city": "Izmir",}}')
    assert bad.status_code == 422
    err = bad.json()["error"]
    assert err["code"] == "import_profile_invalid_json" and err["details"]["line"] == 1
    assert "Izmir" not in bad.text  # file content is never echoed
    assert (
        upload(c, h, b"x", name="a.pdf").json()["error"]["code"] == "import_file_unsupported_format"
    )
    assert (
        upload(c, h, b"\x00\x01\x02", name="a.txt").json()["error"]["code"] == "import_file_binary"
    )
    assert upload(c, h, b"   ", name="a.md").json()["error"]["code"] == "import_file_empty"
    big = upload(c, h, b"a" * 1_000_001, name="a.txt")
    assert big.json()["error"]["code"] == "import_file_too_large"
    nob64 = c.post(f"{API}/analyze", headers=h, json={"file_name": "a.json", "content_base64": "*"})
    assert nob64.json()["error"]["code"] == "import_file_encoding"

    remember(storage, "location", "Ankara", "Kullanıcı Ankara'da yaşıyor.")
    iid = upload(c, h, profile_bytes({"profile": {"city": "İzmir"}})).json()["id"]
    pv = c.get(f"{API}/{iid}", headers=h).json()
    city = next(i for i in pv["items"] if i["value"] == "İzmir")
    assert city["classification"] in ("conflict", "temporal_update") and city["existing"]
    r = c.post(f"{API}/{iid}/decisions", headers=h,
               json={"items": [{"id": city["id"], "decision": "approve"}]})  # fmt: skip
    assert r.status_code == 409 and r.json()["error"]["code"] == "import_needs_resolution"
    assert (
        c.get(f"{API}/{iid}/undo-plan", headers=h).json()["error"]["code"] == "import_not_applied"
    )
    assert c.post(f"{API}/{iid}/retry", headers=h).status_code in (409, 503)
    unknown = c.get(f"{API}/01J0000000000000000000000X", headers=h)
    assert unknown.status_code == 404


def test_a_file_up_to_the_limit_passes_the_request_guard(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    c, h = client(tmp_path, storage, token)
    data = profile_bytes({"facts": [f"Sentetik bilgi {i}: deneme" for i in range(450)]})
    data = data + b" " * (900_000 - len(data))  # ~0.9 MB of JSON (whitespace is valid)
    r = upload(c, h, data)
    assert r.status_code == 200, r.text
    # Other routes keep the normal limit; this one is bounded too.
    other = c.post(f"{API}/x/decisions", headers={**h, "content-type": "application/json"},
                   content=b"{" + b" " * 70_000 + b"}")  # fmt: skip
    assert other.json()["error"]["code"] == "request_too_large"
    huge = c.post(f"{API}/analyze", headers={**h, "content-type": "application/json"},
                  content=b"{" + b" " * 1_500_000 + b"}")  # fmt: skip
    assert huge.json()["error"]["code"] == "request_too_large"


def test_discard_and_cancel_delete_the_draft(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    c, h = client(tmp_path, storage, token)
    iid = upload(c, h, profile_bytes(DOC)).json()["id"]
    gone = c.delete(f"{API}/{iid}", headers=h).json()
    assert gone["status"] == "discarded"
    assert c.get(f"{API}/{iid}", headers=h).json()["items"] == []
    assert c.get(API, headers=h).json()["batches"] == []  # a discarded draft is not listed
