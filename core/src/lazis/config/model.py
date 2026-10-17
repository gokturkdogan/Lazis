"""Typed configuration model.

Defaults are privacy-preserving: loopback-only API, network egress disabled, research in
``offline_only`` mode, voice disabled and the microphone never always-on. Sections for future
phases (models, voice, research) are placeholders that are validated but not used yet.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator

Environment = Literal["development", "production", "test"]
ResearchMode = Literal["offline_only", "ask_per_session", "auto_public", "custom"]

APP_SUPPORT = Path.home() / "Library" / "Application Support" / "LAZIS"
LOGS_ROOT = Path.home() / "Library" / "Logs" / "LAZIS"


OLLAMA_PORT = 11434  # must match apps/desktop/src-tauri/sandbox/backend.sb


class _Section(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


def _is_loopback_literal(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class AppSection(_Section):
    environment: Environment = "production"


class BackendSection(_Section):
    host: str = "127.0.0.1"
    port: int = Field(default=0, ge=0, le=65535)  # 0 = OS-assigned (collision-safe)
    allowed_origins: tuple[str, ...] = ("tauri://localhost",)
    dev_origins: tuple[str, ...] = ("http://localhost:1420",)
    max_request_bytes: int = Field(default=64 * 1024, ge=1024, le=1024 * 1024)
    rate_limit_per_second: float = Field(default=50.0, gt=0, le=1000)
    rate_limit_burst: int = Field(default=100, ge=1, le=10_000)
    limit_concurrency: int = Field(default=32, ge=1, le=256)
    secrets_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    shutdown_timeout_seconds: int = Field(default=5, ge=1, le=60)

    @field_validator("host")
    @classmethod
    def _loopback_only(cls, value: str) -> str:
        # Literal loopback IPs only: hostnames such as "localhost" depend on resolution.
        if not _is_loopback_literal(value):
            raise ValueError("backend.host must be a loopback IP literal (127.0.0.1 or ::1)")
        return value


class StorageSection(_Section):
    data_dir: Path = APP_SUPPORT / "data.noindex"
    database_filename: str = "lazis.db"
    backups_keep: int = Field(default=10, ge=1, le=200)
    quick_check_on_startup: bool = True

    @property
    def database_path(self) -> Path:
        return self.data_dir / self.database_filename

    @property
    def backup_dir(self) -> Path:
        return self.data_dir / "backups"


class LoggingSection(_Section):
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    directory: Path = LOGS_ROOT
    max_bytes: int = Field(default=10 * 1024 * 1024, ge=64 * 1024)
    backup_count: int = Field(default=10, ge=1, le=100)
    console: bool = False


class NetworkSection(_Section):
    # Outbound network access arrives with research in P12. Until then it cannot be enabled.
    egress_enabled: Literal[False] = False


class ResearchSection(_Section):
    mode: ResearchMode = "offline_only"

    @field_validator("mode")
    @classmethod
    def _offline_until_p12(cls, value: ResearchMode) -> ResearchMode:
        if value != "offline_only":
            raise ValueError("research.mode supports only 'offline_only' before Phase 12")
        return value


class ModelsSection(_Section):
    """Local inference (P2). Only a loopback runtime is ever used; no cloud inference."""

    provider: Literal["ollama"] = "ollama"
    endpoint: str = "http://127.0.0.1:11434"
    # Provisional P2 recommendation (docs/adr/0001-primary-model.md, status Proposed): final
    # after the owner's blind rating. The UI preselects it when installed.
    primary_model: str | None = "gemma4:12b-it-qat"
    # Named context sizes (tokens). Requests choose a name, never a raw num_ctx: each distinct
    # num_ctx makes Ollama's llama.cpp runner reload the model (measured 0.9–2.8 s). Measured
    # memory differs by ≤ 0.3 GB between 8K and 16K for the recommended models, so short and
    # normal share 16K (no reloads in conversation); long (32K) is for explicit long tasks.
    context_short: int = Field(default=16384, ge=2048, le=65536)
    context_normal: int = Field(default=16384, ge=2048, le=65536)
    context_long: int = Field(default=32768, ge=2048, le=65536)
    keep_alive: str = Field(default="10m", pattern=r"^(0|-1|[0-9]+[smh])$")
    max_output_tokens: int = Field(default=1024, ge=16, le=8192)

    @field_validator("endpoint")
    @classmethod
    def _loopback_endpoint(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme != "http" or not _is_loopback_literal(parsed.hostname or ""):
            raise ValueError("models.endpoint must be http on a loopback IP (local inference only)")
        if parsed.port != OLLAMA_PORT:
            # The backend's OS sandbox allows outbound connections to this port only.
            raise ValueError(f"models.endpoint port must be {OLLAMA_PORT} (sandbox policy)")
        return value

    def context_tokens(self, profile: Literal["short", "normal", "long"]) -> int:
        return {
            "short": self.context_short,
            "normal": self.context_normal,
            "long": self.context_long,
        }[profile]


class VoiceSection(_Section):
    """Placeholder for P13. Voice cannot be enabled before it exists."""

    enabled: Literal[False] = False
    interaction_mode: Literal["push_to_talk", "hands_free_session"] = "push_to_talk"
    microphone_always_on: Literal[False] = False


class Settings(_Section):
    app: AppSection = AppSection()
    backend: BackendSection = BackendSection()
    storage: StorageSection = StorageSection()
    logging: LoggingSection = LoggingSection()
    network: NetworkSection = NetworkSection()
    research: ResearchSection = ResearchSection()
    models: ModelsSection = ModelsSection()
    voice: VoiceSection = VoiceSection()

    def effective_origins(self) -> tuple[str, ...]:
        if self.app.environment == "development":
            return self.backend.allowed_origins + self.backend.dev_origins
        return self.backend.allowed_origins
