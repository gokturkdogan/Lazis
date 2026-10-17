from __future__ import annotations

import json
import os
from pathlib import Path

from lazis.api.app_factory import ApiContext, create_app
from lazis.config import Settings
from lazis.storage import StorageHandle
from tests.conftest import REPO_ROOT, make_client

OPENAPI_SNAPSHOT = REPO_ROOT / "apps" / "desktop" / "ui" / "src" / "api" / "openapi.json"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_app_info(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    body = (
        make_client(tmp_path, storage, token).get("/api/v1/app/info", headers=_auth(token)).json()
    )
    assert body["name"] == "LAZIS" and body["api_version"] == "v1" and body["phase"] == "P2"
    assert body["environment"] == "test"


def test_system_status_reports_verified_encryption_and_privacy(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    body = (
        make_client(tmp_path, storage, token)
        .get("/api/v1/system/status", headers=_auth(token))
        .json()
    )
    db = body["database"]
    assert db["encrypted"] is True and db["encryption_verified"] is True
    assert db["cipher_version"].startswith("4.") and db["integrity"] == "ok"
    assert db["schema_version"] == 1 and len(db["instance_id"]) == 26
    assert body["privacy"] == {
        "network_egress": "disabled",
        "research_mode": "offline_only",
        "microphone": "off",
        "voice_enabled": False,
        # In-process test app: no shell, so no OS sandbox was applied.
        "os_network_sandbox": "unknown",
    }
    assert body["ai"]["configured"] is False
    assert body["backend"]["pid"] == os.getpid()


def test_settings_view_contains_no_secrets(
    tmp_path: Path, storage: StorageHandle, token: str
) -> None:
    response = make_client(tmp_path, storage, token).get("/api/v1/settings", headers=_auth(token))
    assert response.status_code == 200
    text = response.text
    assert token not in text and storage.db.key.hex() not in text
    assert response.json()["research_mode"] == "offline_only"


def test_openapi_snapshot_matches_code() -> None:
    """The UI's generated types come from this committed snapshot; drift fails CI."""
    app = create_app(ApiContext(settings=Settings(), storage=None, token_matches=lambda _t: False))
    current = json.loads(json.dumps(app.openapi(), sort_keys=True))
    committed = json.loads(OPENAPI_SNAPSHOT.read_text())
    assert committed == current, "run `just openapi` to regenerate the UI API snapshot"
