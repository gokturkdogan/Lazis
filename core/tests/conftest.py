from __future__ import annotations

import secrets
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lazis.api.app_factory import ApiContext, build_asgi
from lazis.config.model import (
    AppSection,
    BackendSection,
    LoggingSection,
    Settings,
    StorageSection,
)
from lazis.security.secrets import SecretBytes, StartupSecrets
from lazis.storage import StorageHandle, open_storage

TEST_PORT = 8123
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def key() -> SecretBytes:
    return SecretBytes(secrets.token_bytes(32))


@pytest.fixture
def token() -> str:
    return secrets.token_hex(32)


@pytest.fixture
def storage_section(tmp_path: Path) -> StorageSection:
    return StorageSection(data_dir=tmp_path / "data")


def make_settings(tmp_path: Path, **backend: object) -> Settings:
    return Settings(
        app=AppSection(environment="test"),
        backend=BackendSection(**backend),  # pyright: ignore[reportArgumentType]
        storage=StorageSection(data_dir=tmp_path / "data"),
        logging=LoggingSection(directory=tmp_path / "logs"),
    )


@pytest.fixture
def storage(storage_section: StorageSection, key: SecretBytes) -> Iterator[StorageHandle]:
    handle = open_storage(storage_section, key, app_version="test")
    try:
        yield handle
    finally:
        handle.db.close()


def make_client(
    tmp_path: Path, storage: StorageHandle | None, token: str, **backend: object
) -> TestClient:
    settings = make_settings(tmp_path, **backend)
    startup = StartupSecrets(session_token=token, db_key=SecretBytes(b"\x00" * 32))
    ctx = ApiContext(
        settings=settings,
        storage=storage,
        token_matches=startup.token_matches,
        port=TEST_PORT,
        started_at="2026-01-01T00:00:00.000Z",
    )
    _, asgi = build_asgi(ctx)
    return TestClient(asgi, base_url=f"http://127.0.0.1:{TEST_PORT}")
