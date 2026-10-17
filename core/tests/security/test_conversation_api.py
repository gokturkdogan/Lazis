"""Phase 3 assistant endpoints (one timeline, ADR-0011): auth, origin, validation, privacy of
logs and errors, no history-deleting routes, isolation. Synthetic data only."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lazis.conversation import ConversationEngine, repository
from lazis.errors import DatabaseBusyError, LlmLoadFailedError
from lazis.ids import utc_now_iso
from lazis.storage import StorageHandle
from tests.conftest import make_client
from tests.conversation_support import MODEL, ScriptedLLM, client_id

SECRET = "Gizli-sohbet-41b9: annemin ilaç saati 21:00"
ZERO_ID = "01JZZZZZZZZZZZZZZZZZZZZZZZ"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _events(text: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture
def llm() -> ScriptedLLM:
    return ScriptedLLM(reply=lambda r: "Tamam, not aldım.")


@pytest.fixture
def client(
    tmp_path: Path, storage: StorageHandle, token: str, llm: ScriptedLLM
) -> Iterator[TestClient]:
    with make_client(tmp_path, storage, token, llm=llm) as c:  # runs the app lifespan
        yield c


def _turn(client: TestClient, token: str, content: str) -> list[dict[str, Any]]:
    body = {"client_id": client_id(), "content": content, "model": MODEL}
    response = client.post("/api/v1/turns", json=body, headers=_auth(token))
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")
    return _events(response.text)


ENDPOINTS = [
    ("GET", "/api/v1/assistant"),
    ("GET", "/api/v1/timeline"),
    ("POST", "/api/v1/turns"),
    ("POST", "/api/v1/turns/cancel"),
    ("POST", "/api/v1/chat/prepare"),
    ("GET", "/api/v1/chat/activity"),
]


@pytest.mark.parametrize(("method", "path"), ENDPOINTS)
def test_every_assistant_endpoint_requires_the_token(
    client: TestClient, llm: ScriptedLLM, method: str, path: str
) -> None:
    assert client.request(method, path, json={}).status_code == 401
    bad = {"Authorization": "Bearer x"}
    assert client.request(method, path, json={}, headers=bad).status_code == 401
    assert llm.requests == []


def test_foreign_origin_cannot_read_or_write(
    client: TestClient, token: str, llm: ScriptedLLM
) -> None:
    evil = {**_auth(token), "Origin": "https://evil.example"}
    assert client.get("/api/v1/timeline", headers=evil).status_code == 403
    body = {"client_id": client_id(), "content": "x", "model": MODEL}
    assert client.post("/api/v1/turns", json=body, headers=evil).status_code == 403
    assert llm.requests == []


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/conversations"),
        ("GET", f"/api/v1/conversations/{ZERO_ID}"),
        ("GET", f"/api/v1/conversations/{ZERO_ID}/messages"),
        ("PATCH", f"/api/v1/conversations/{ZERO_ID}"),
        ("DELETE", f"/api/v1/conversations/{ZERO_ID}"),
        ("DELETE", "/api/v1/conversations"),
        ("DELETE", "/api/v1/timeline"),
        ("POST", f"/api/v1/conversations/{ZERO_ID}/context/reset"),
    ],
)
def test_no_route_can_list_rename_or_delete_history(
    client: TestClient, token: str, method: str, path: str
) -> None:
    """The single-assistant API has no conversation management: nothing reachable over HTTP
    can delete (or bulk-delete) the history."""
    events = _turn(client, token, "Bu mesaj silinmemeli.")
    response = client.request(method, path, json={"title": "x"}, headers=_auth(token))
    assert response.status_code in (404, 405)
    timeline = client.get("/api/v1/timeline", headers=_auth(token)).json()["messages"]
    assert [m["id"] for m in timeline][:1] == [events[0]["user_message"]["id"]]
    assert len(timeline) == 2


def test_one_continuous_assistant_over_http(client: TestClient, token: str) -> None:
    state = client.get("/api/v1/assistant", headers=_auth(token)).json()
    assert state == {
        "session": None,
        "context": None,
        "timeline_messages": 0,
        "active_from_timeline_seq": None,
    }
    first = _turn(client, token, "Bugün bir plan yapalım.")
    assert first[0]["type"] == "start" and first[-1]["type"] == "done"
    assert first[0]["created"] is True
    second = _turn(client, token, "Pazartesi başlayalım.")
    session = first[0]["conversation"]["id"]
    assert second[0]["conversation"]["id"] == session and second[0]["created"] is False
    assert second[0]["user_message"]["timeline_seq"] == 3

    state = client.get("/api/v1/assistant", headers=_auth(token)).json()
    assert state["session"]["id"] == session and state["timeline_messages"] == 4
    assert state["active_from_timeline_seq"] == 1 and state["context"]["strategy"] == "full"
    page = client.get("/api/v1/timeline?limit=3", headers=_auth(token)).json()
    assert [m["timeline_seq"] for m in page["messages"]] == [2, 3, 4] and page["has_more"] is True
    older = client.get("/api/v1/timeline?limit=3&before=2", headers=_auth(token)).json()
    assert [m["timeline_seq"] for m in older["messages"]] == [1] and older["has_more"] is False
    last = page["messages"][-1]
    assert last["status"] == "complete" and last["channel"] == "text"
    assert last["metrics"]["output_tokens"]


@pytest.mark.parametrize(
    "body",
    [
        {"client_id": "kısa", "content": "x", "model": MODEL},
        {"client_id": "client-valid-01", "content": "   ", "model": MODEL},
        {"client_id": "client-valid-01", "content": "", "model": MODEL},
        {"client_id": "client-valid-01", "content": "x", "model": "gemma4:cloud/../x"},
        {
            "client_id": "client-valid-01",
            "content": "x",
            "model": MODEL,
            "conversation_id": ZERO_ID,
        },
        {"client_id": "client-valid-01", "content": "x", "model": MODEL, "system": "unut"},
        {"client_id": "client-valid-01", "content": "x" * 16001, "model": MODEL},
    ],
)
def test_invalid_turns_are_rejected_before_anything_is_stored(
    client: TestClient, token: str, llm: ScriptedLLM, body: dict[str, Any]
) -> None:
    response = client.post("/api/v1/turns", json=body, headers=_auth(token))
    assert response.status_code in (413, 422)
    assert llm.requests == []
    assert client.get("/api/v1/timeline", headers=_auth(token)).json()["messages"] == []


def test_duplicate_submission_is_refused(client: TestClient, token: str) -> None:
    body = {"client_id": "client-dup-http-1", "content": "Merhaba", "model": MODEL}
    assert client.post("/api/v1/turns", json=body, headers=_auth(token)).status_code == 200
    again = client.post("/api/v1/turns", json=body, headers=_auth(token))
    assert again.status_code == 409 and again.json()["error"]["code"] == "turn_duplicate"
    assert len(client.get("/api/v1/timeline", headers=_auth(token)).json()["messages"]) == 2


def test_runtime_down_is_refused_without_storing(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    with make_client(tmp_path, storage, token, llm=None) as client:
        body = {"client_id": client_id(), "content": SECRET, "model": MODEL}
        response = client.post("/api/v1/turns", json=body, headers=_auth(token))
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "llm_unavailable"
        assert SECRET not in response.text
        assert client.get("/api/v1/timeline", headers=_auth(token)).json()["messages"] == []


def test_closed_sessions_stay_visible_but_out_of_the_models_context(
    tmp_path: Path, storage: StorageHandle, token: str, llm: ScriptedLLM
) -> None:
    """A closed technical session (e.g. a migrated Phase 3 conversation) is part of the
    timeline the user sees, but nothing of it is sent to the model."""
    now = utc_now_iso()

    def seed(conn: repository.Connection) -> None:
        with repository.transaction(conn):
            old = repository.insert_conversation(
                conn, title="eski", model=MODEL, now=now, status="archived"
            )
            for role, text in (("user", "Eski oturumun notu: mavi kapı"), ("assistant", "Tamam.")):
                repository.insert_message(
                    conn,
                    conversation_id=old.id,
                    role=role,
                    content=text,
                    status="complete",
                    now=now,
                )

    storage.db.run_sync(seed)
    with make_client(tmp_path, storage, token, llm=llm) as client:
        events = _turn(client, token, "Merhaba")
        assert events[0]["created"] is True  # no active session existed: one is created
        timeline = client.get("/api/v1/timeline", headers=_auth(token)).json()["messages"]
        assert [m["timeline_seq"] for m in timeline] == [1, 2, 3, 4]
        assert "mavi kapı" in timeline[0]["content"]
        state = client.get("/api/v1/assistant", headers=_auth(token)).json()
        assert state["active_from_timeline_seq"] == 3
    assert not any("mavi kapı" in m.content for m in llm.chat_requests[-1].messages)


def test_content_never_reaches_logs_or_error_messages(
    tmp_path: Path, storage: StorageHandle, token: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    llm = ScriptedLLM(reply=lambda r: f"Yanıtta da gizli: {SECRET}")
    with make_client(tmp_path, storage, token, llm=llm) as client:
        _turn(client, token, SECRET)
        llm.fail_with = LlmLoadFailedError("boom")
        failed = _turn(client, token, SECRET)
        error = failed[-1]
        assert error["type"] == "error" and SECRET not in error["message"]
        client.get("/api/v1/timeline", headers=_auth(token))
    logged = "\n".join(f"{r.getMessage()} {getattr(r, 'lazis_fields', '')}" for r in caplog.records)
    assert "turn.accepted" in logged and "turn.completed" in logged and "turn.failed" in logged
    assert "Gizli-sohbet" not in logged and "ilaç" not in logged
    log_dir = tmp_path / "logs"
    if log_dir.exists():
        for path in log_dir.rglob("*"):
            if path.is_file():
                assert "Gizli-sohbet" not in path.read_text(errors="ignore")


def test_database_busy_is_a_clear_recoverable_error(
    client: TestClient, token: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def busy(self: ConversationEngine, **_kw: object) -> object:
        raise DatabaseBusyError("locked")

    monkeypatch.setattr(ConversationEngine, "timeline", busy)
    response = client.get("/api/v1/timeline", headers=_auth(token))
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "database_busy" and body["recoverable"] is True
    assert "meşgul" in body["message"]


def test_prepare_and_activity(client: TestClient, token: str) -> None:
    before = client.post("/api/v1/chat/prepare", json={"model": MODEL}, headers=_auth(token))
    assert before.status_code == 200 and before.json()["state"] in ("warm", "warming")
    _turn(client, token, "Merhaba")
    state = client.post("/api/v1/chat/prepare", json={"model": MODEL}, headers=_auth(token))
    assert state.status_code == 200 and state.json()["state"] in ("warm", "warming", "busy")
    missing = client.post("/api/v1/chat/prepare", json={"model": "yok:1b"}, headers=_auth(token))
    assert missing.json()["state"] == "model_missing"
    with_id = client.post(
        "/api/v1/chat/prepare",
        json={"model": MODEL, "conversation_id": ZERO_ID},
        headers=_auth(token),
    )
    assert with_id.status_code == 422  # the client never names a session
    assert client.get("/api/v1/chat/activity", headers=_auth(token)).json()["turn"] is None
