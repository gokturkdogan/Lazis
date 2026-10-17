"""Explicit response schemas for API v1 (exported to OpenAPI → generated TypeScript types)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from lazis.config.model import ResearchMode


class _Schema(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ErrorBody(_Schema):
    code: str
    message: str
    recoverable: bool
    request_id: str


class ErrorResponse(_Schema):
    error: ErrorBody


class HealthCheck(_Schema):
    status: Literal["ok", "failed"]
    code: str | None = None


class HealthResponse(_Schema):
    status: Literal["ok", "degraded"]
    version: str
    checks: dict[str, HealthCheck]


class AppInfoResponse(_Schema):
    name: str
    version: str
    api_version: str
    phase: str
    environment: str
    python_version: str


class BackendStatus(_Schema):
    pid: int
    started_at: str
    uptime_seconds: float
    peak_rss_bytes: int
    python_version: str
    platform: str
    machine: str


class DatabaseStatusModel(_Schema):
    state: Literal["ready"]
    encrypted: bool
    encryption_verified: bool
    cipher_version: str
    cipher_provider: str
    sqlite_version: str
    schema_version: int
    journal_mode: str
    integrity: Literal["ok", "failed"]
    size_bytes: int
    instance_id: str
    created_at: str


class PrivacyStatus(_Schema):
    network_egress: Literal["disabled"]
    research_mode: ResearchMode
    microphone: Literal["off"]
    voice_enabled: bool


class AiStatus(_Schema):
    configured: bool
    provider: str
    available_from_phase: str


class SystemStatusResponse(_Schema):
    backend: BackendStatus
    database: DatabaseStatusModel
    privacy: PrivacyStatus
    ai: AiStatus


class EffectiveSettingsResponse(_Schema):
    """Non-secret, read-only view of the effective configuration (Phase 1)."""

    environment: str
    data_dir: str
    log_dir: str
    log_level: str
    research_mode: str
    network_egress_enabled: bool
    voice_enabled: bool
    voice_interaction_mode: str
    models_provider: str
    models_primary_model: str | None
    models_context_length: int
    backups_keep: int
    max_request_bytes: int
