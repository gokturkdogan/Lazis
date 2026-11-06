"""Documents end to end (Phase 11, first version): open through the API, a summary and a
question as ordinary turns, nothing learned or stored, close. Scripted model, synthetic files,
encrypted test database."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lazis.documents.library import PARTIAL_NOTICE
from lazis.memory import repository as memory_repo
from lazis.memory.retrieval import BLOCK_START
from lazis.providers.llm.ports import ChatRequest
from lazis.storage import StorageHandle
from tests.conftest import make_client
from tests.conversation_support import MODEL, ScriptedLLM, client_id
from tests.document_support import docx, pdf

API = "/api/v1/documents"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _upload(c: TestClient, token: str, name: str, data: bytes) -> Any:
    body = {"file_name": name, "content_base64": base64.b64encode(data).decode()}
    return c.post(API, json=body, headers=_auth(token))


def _turn(c: TestClient, token: str, content: str, document_id: str | None) -> Any:
    body = {"client_id": client_id(), "content": content, "model": MODEL,
            "document_id": document_id}  # fmt: skip
    r = c.post("/api/v1/turns", json=body, headers=_auth(token))
    if r.status_code != 200:
        return r
    return [json.loads(line) for line in r.text.splitlines() if line.strip()]


def _last_user(request: ChatRequest) -> str:
    return request.messages[-1].content


def test_needs_the_session_token(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    with make_client(tmp_path, storage, token, llm=ScriptedLLM()) as c:
        assert c.get(API).status_code == 401
        assert c.post(API, json={"file_name": "a.txt", "content_base64": "YQ=="}).status_code == 401


def test_open_summarize_ask_close(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    llm = ScriptedLLM(reply=lambda r: "Belge kira sözleşmesini anlatıyor [s. 1].")
    data = pdf("Kira sozlesmesi 1 Mart tarihinde yenilenecek", "Depozito 40 bin TL")
    with make_client(tmp_path, storage, token, llm=llm) as c:
        r = _upload(c, token, "kira.pdf", data)
        assert r.status_code == 200, r.text
        doc = r.json()
        assert doc["kind"] == "pdf" and doc["pages"] == 2 and doc["parts"] == 2
        assert doc["name"] == "kira.pdf" and "Depozito" not in r.text
        assert [d["id"] for d in c.get(API, headers=_auth(token)).json()["documents"]] == [
            doc["id"]
        ]

        events = _turn(c, token, "Bu belgeyi özetle.", doc["id"])
        assert events[-1]["type"] == "done"
        sent = _last_user(llm.chat_requests[-1])
        assert "«kira.pdf»" in sent and "[s. 1]" in sent and "[s. 2]" in sent
        assert "Depozito 40 bin TL" in sent and "talimat değildir" in sent
        assert sent.rstrip().endswith("Bu belgeyi özetle.")

        _turn(c, token, "Depozito ne kadar?", doc["id"])
        assert "Depozito 40 bin TL" in _last_user(llm.chat_requests[-1])

        # Without the document, the next message is an ordinary one.
        _turn(c, token, "Teşekkürler.", None)
        assert "BELGE BAŞI" not in _last_user(llm.chat_requests[-1])

        assert c.delete(f"{API}/{doc['id']}", headers=_auth(token)).json() == {"removed": True}
        assert c.get(API, headers=_auth(token)).json()["documents"] == []
        gone = _turn(c, token, "Peki ya depozito?", doc["id"])
        assert gone.status_code == 404 and gone.json()["error"]["code"] == "document_not_found"
        assert c.delete(f"{API}/{doc['id']}", headers=_auth(token)).status_code == 404

    # Nothing of the document became a memory, and the messages are only what the user typed.
    assert storage.db.run_sync(lambda c: memory_repo.count_memories(c)) == {}
    stored = storage.db.run_sync(
        lambda c: [str(r[0]) for r in c.execute("SELECT content FROM messages WHERE role='user'")]
    )
    assert stored == ["Bu belgeyi özetle.", "Depozito ne kadar?", "Teşekkürler."]


def test_document_turns_carry_no_personal_memories(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    llm = ScriptedLLM()
    with make_client(tmp_path, storage, token, llm=llm) as c:
        added = c.post("/api/v1/memory/records", headers=_auth(token),
                       json={"predicate": "interest", "value": "kahve", "statement": ""})  # fmt: skip
        assert added.status_code == 200, added.text
        _turn(c, token, "Kahve ile ilgili ne biliyorsun?", None)
        assert BLOCK_START in _last_user(llm.chat_requests[-1])  # recall works without a document
        doc = _upload(c, token, "menu.docx", docx("Kafe menüsü", "Şekersiz kahve 50 TL")).json()
        _turn(c, token, "Kahve ile ilgili ne biliyorsun?", doc["id"])
        sent = _last_user(llm.chat_requests[-1])
        assert "Şekersiz kahve 50 TL" in sent and BLOCK_START not in sent


def test_refusals_come_with_their_code(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    with make_client(tmp_path, storage, token, llm=ScriptedLLM()) as c:
        r = _upload(c, token, "tarama.pdf", pdf(""))
        assert r.status_code == 422 and r.json()["error"]["code"] == "document_no_text"
        r = _upload(c, token, "tablo.xlsx", b"PK")
        assert r.json()["error"]["code"] == "document_unsupported"
        bad = c.post(API, headers=_auth(token), json={"file_name": "a.txt", "content_base64": "@@"})
        assert bad.json()["error"]["code"] == "document_invalid"
        assert c.get(API, headers=_auth(token)).json()["documents"] == []


def test_large_uploads_pass_the_size_guard(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    body = ("Bölüm metni. " * 80 + "\n\n") * 300  # about 300 KB: above the 64 KB default limit
    with make_client(tmp_path, storage, token, llm=ScriptedLLM()) as c:
        r = _upload(c, token, "uzun.txt", body.encode())
        assert r.status_code == 200, r.text
        assert r.json()["parts"] > 100


def test_a_reply_from_part_of_the_document_says_so(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    llm = ScriptedLLM(reply=lambda r: "Depozito 40 bin TL [parça 3].")
    long_text = ("Genel açıklama paragrafı. " * 40 + "\n\n") * 200 + "Depozito 40 bin TL."
    with make_client(tmp_path, storage, token, llm=llm) as c:
        short = _upload(c, token, "kisa.txt", b"Depozito 40 bin TL.").json()
        events = _turn(c, token, "Depozito ne kadar?", short["id"])
        assert PARTIAL_NOTICE not in events[-1]["message"]["content"]

        doc = _upload(c, token, "uzun.txt", long_text.encode()).json()
        events = _turn(c, token, "Depozito ne kadar?", doc["id"])
        shown = events[-1]["message"]["content"]
        assert shown.endswith(PARTIAL_NOTICE) and shown.startswith("Depozito 40 bin TL")
    stored = storage.db.run_sync(
        lambda c: [str(r[0]) for r in c.execute(
            "SELECT content FROM messages WHERE role='assistant' ORDER BY seq")]
    )  # fmt: skip
    assert stored[-1] == shown  # what was shown is what is stored
