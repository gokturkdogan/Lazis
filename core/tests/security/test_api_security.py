"""Local API protection: token, Host, Origin, preflight, body and rate limits, error hygiene."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lazis.storage import StorageHandle
from tests.conftest import TEST_PORT, make_client


@pytest.fixture
def client(tmp_path: Path, storage: StorageHandle, token: str) -> TestClient:
    return make_client(tmp_path, storage, token)


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_health_with_token(client: TestClient, token: str) -> None:
    response = client.get("/api/v1/health", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok" and body["checks"]["database"]["status"] == "ok"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "server" not in response.headers


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer "},
    ],
)
def test_requests_without_valid_token_are_rejected(
    client: TestClient, headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/health", headers=headers)
    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthorized"
    assert error["message"] == "Yetkisiz istek."


def test_foreign_origin_is_rejected_even_with_token(client: TestClient, token: str) -> None:
    response = client.get(
        "/api/v1/health", headers={**_auth(token), "Origin": "https://evil.example"}
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "origin_not_allowed"
    assert "access-control-allow-origin" not in response.headers


def test_allowed_origin_gets_cors_headers(client: TestClient, token: str) -> None:
    response = client.get("/api/v1/health", headers={**_auth(token), "Origin": "tauri://localhost"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "tauri://localhost"


def test_dev_origin_is_not_allowed_outside_development(client: TestClient, token: str) -> None:
    response = client.get(
        "/api/v1/health", headers={**_auth(token), "Origin": "http://localhost:1420"}
    )
    assert response.status_code == 403


def test_preflight_from_allowed_origin_needs_no_token(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={
            "Origin": "tauri://localhost",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert response.status_code == 204
    assert "authorization" in response.headers["access-control-allow-headers"]


def test_preflight_from_foreign_origin_is_rejected(client: TestClient) -> None:
    response = client.options(
        "/api/v1/health",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "host", ["evil.example", "localhost:8123", f"127.0.0.1:{TEST_PORT + 1}", "192.168.1.10:8123"]
)
def test_dns_rebinding_host_headers_are_rejected(client: TestClient, token: str, host: str) -> None:
    response = client.get("/api/v1/health", headers={**_auth(token), "Host": host})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "host_not_allowed"


def test_large_bodies_are_rejected(client: TestClient, token: str) -> None:
    response = client.post("/api/v1/health", headers=_auth(token), content=b"x" * (65 * 1024))
    assert response.status_code == 413


def test_rate_limit(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    limited = make_client(tmp_path, storage, token, rate_limit_burst=3, rate_limit_per_second=0.01)
    codes = [limited.get("/api/v1/health", headers=_auth(token)).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200]
    assert codes[3:] == [429, 429]


def test_unknown_route_returns_turkish_json_error(client: TestClient, token: str) -> None:
    response = client.get("/api/v1/does-not-exist", headers=_auth(token))
    assert response.status_code == 404
    assert response.json()["error"]["message"] == "İstenen kaynak bulunamadı."


def test_no_docs_or_openapi_are_served(client: TestClient, token: str) -> None:
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path, headers=_auth(token)).status_code == 404


def test_unexpected_errors_do_not_leak_details(tmp_path: Path, token: str) -> None:
    # storage=None makes /system/status fail internally.
    broken = make_client(tmp_path, None, token)
    response = broken.get("/api/v1/system/status", headers=_auth(token))
    assert response.status_code == 500
    text = response.text
    assert "Traceback" not in text and "storage not initialised" not in text
    assert response.json()["error"]["code"] == "internal_error"


def test_denied_requests_are_audited(tmp_path: Path, storage: StorageHandle, token: str) -> None:
    from lazis.api.app_factory import ApiContext, build_asgi
    from lazis.security.secrets import SecretBytes, StartupSecrets
    from lazis.storage.repositories import count_audit, write_audit
    from tests.conftest import make_settings

    def on_denied(code: str) -> None:
        storage.db.run_sync(
            lambda c: write_audit(
                c, category="security", action="request_denied", outcome="denied", reason_code=code
            )
        )

    secrets_obj = StartupSecrets(session_token=token, db_key=SecretBytes(b"\x00" * 32))
    ctx = ApiContext(
        settings=make_settings(tmp_path),
        storage=storage,
        token_matches=secrets_obj.token_matches,
        port=TEST_PORT,
        on_denied=on_denied,
    )
    _, asgi = build_asgi(ctx)
    TestClient(asgi, base_url=f"http://127.0.0.1:{TEST_PORT}").get("/api/v1/health")
    assert storage.db.run_sync(lambda c: count_audit(c, "security", "request_denied")) == 1
