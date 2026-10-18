"""Explicit response schemas for API v1 (exported to OpenAPI → generated TypeScript types)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from lazis.config.model import ResearchMode
from lazis.security.network_guard import SandboxStatus


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
    # "enforced": the OS denies this process (and its children) network access to other
    # hosts. "not_enforced"/"unknown": only the application-level guard applies.
    os_network_sandbox: SandboxStatus


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
    models_fallback_model: str | None
    personality_verbosity: Literal["adaptive", "short", "detailed"]
    personality_humor: Literal["light", "off"]
    models_context_short: int
    models_context_normal: int
    models_context_long: int
    models_keep_alive: str
    backups_keep: int
    max_request_bytes: int


# ----- local inference (P2) ---------------------------------------------------------------
MODEL_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]{0,79}(?::[A-Za-z0-9][A-Za-z0-9._-]{0,79})?$"
REQUEST_ID_PATTERN = r"^[A-Za-z0-9-]{8,64}$"
MAX_MESSAGES = 40
MAX_MESSAGE_CHARS = 16_000
MAX_TOTAL_CHARS = 48_000


class RuntimeStatusModel(_Schema):
    available: bool
    runtime: str
    version: str | None
    error_code: str | None


class LoadedModelModel(_Schema):
    name: str
    size_bytes: int
    vram_bytes: int
    context_length: int | None
    expires_at: str


class LlmStatusResponse(_Schema):
    runtime: RuntimeStatusModel
    loaded: list[LoadedModelModel]
    primary_model: str | None
    cloud_inference: Literal["disabled"]


class ModelInfoModel(_Schema):
    name: str
    digest: str
    size_bytes: int
    family: str
    parameter_size: str
    quantization: str
    format: str


class ModelListResponse(_Schema):
    models: list[ModelInfoModel]


class ChatTurn(_Schema):
    role: Literal["user", "assistant"]  # no client-supplied system prompts
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)


class ChatOptions(_Schema):
    context: Literal["short", "normal", "long"] = "normal"
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=16, le=8192)


class ChatStreamRequest(_Schema):
    model: str = Field(pattern=MODEL_NAME_PATTERN)
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)
    messages: list[ChatTurn] = Field(min_length=1, max_length=MAX_MESSAGES)
    options: ChatOptions = Field(default_factory=ChatOptions)

    @field_validator("messages")
    @classmethod
    def _shape(cls, messages: list[ChatTurn]) -> list[ChatTurn]:
        if messages[-1].role != "user":
            raise ValueError("the last message must come from the user")
        if sum(len(m.content) for m in messages) > MAX_TOTAL_CHARS:
            raise ValueError("conversation is too long for one request")
        return messages


class ChatCancelRequest(_Schema):
    request_id: str = Field(pattern=REQUEST_ID_PATTERN)


class ChatCancelResponse(_Schema):
    cancelled: bool


# ----- conversations (P3) ----------------------------------------------------------------
ULID_PATTERN = r"^[0-9A-HJKMNP-TV-Z]{26}$"


class ConversationModel(_Schema):
    id: str
    title: str
    title_source: Literal["auto", "user"]
    model: str
    status: Literal["active", "archived"]
    message_count: int
    created_at: str
    updated_at: str


class MessageMetricsModel(_Schema):
    ttft_ms: float | None
    total_ms: float | None
    prompt_tokens: int | None
    output_tokens: int | None


class MessageModel(_Schema):
    id: str
    conversation_id: str
    seq: int
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["complete", "streaming", "cancelled", "interrupted", "failed"]
    client_id: str | None
    reply_to: str | None
    model: str | None
    error_code: str | None
    created_at: str
    completed_at: str | None
    timeline_seq: int
    channel: Literal["text", "voice"]
    metrics: MessageMetricsModel | None


class TimelinePageResponse(_Schema):
    """A page of the single assistant timeline (all technical sessions), oldest first."""

    messages: list[MessageModel]
    has_more: bool


class SummaryInfoModel(_Schema):
    version: int
    to_seq: int
    kept_items: int
    dropped_items: int
    created_at: str


class ContextInfoModel(_Schema):
    strategy: Literal["full", "summary_window", "window_only"]
    context_version: int
    window_start_seq: int
    estimated_tokens: int
    anchored: bool
    omitted: list[int] | None
    summary: SummaryInfoModel | None
    num_ctx: int
    hard_limit: int
    compact_at: int
    cache: Literal["warm", "cold"]
    background: Literal["prewarm", "compaction"] | None


class AssistantStateResponse(_Schema):
    """The one assistant: its active technical session (None before the first message), that
    session's context state, and where the session starts in the timeline (messages before
    ``active_from_timeline_seq`` are not in the model's current context)."""

    session: ConversationModel | None
    context: ContextInfoModel | None
    timeline_messages: int
    active_from_timeline_seq: int | None


class TurnSubmitRequest(_Schema):
    """One user message to LAZIS. It always goes to the active technical session (created
    with the very first message); the client never chooses a session. ``client_id`` is the
    idempotency key: a retry with the same key is refused with ``turn_duplicate``."""

    client_id: str = Field(pattern=REQUEST_ID_PATTERN)
    content: str = Field(min_length=1, max_length=MAX_MESSAGE_CHARS)
    model: str = Field(pattern=MODEL_NAME_PATTERN)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message is empty")
        return value


class TurnCancelRequest(_Schema):
    client_id: str = Field(pattern=REQUEST_ID_PATTERN)


class TurnCancelResponse(_Schema):
    cancelled: bool


class PrepareRequest(_Schema):
    model: str = Field(pattern=MODEL_NAME_PATTERN)


class PrepareResponse(_Schema):
    state: Literal[
        "warm", "warming", "compacting", "busy", "disabled", "unavailable", "model_missing"
    ]
    model_loaded: bool | None = None
    context_tokens: int | None = None


class TurnActivityModel(_Schema):
    conversation_id: str
    client_id: str | None
    stage: str


class BackgroundActivityModel(_Schema):
    kind: Literal["prewarm", "compaction"]
    conversation_id: str | None


class ActivityResponse(_Schema):
    turn: TurnActivityModel | None
    background: BackgroundActivityModel | None
    cached_conversation_id: str | None
    pending_compaction: list[str]


# ----- diagnostics (P4) ------------------------------------------------------------------
class DiagRuntimeModel(_Schema):
    available: bool
    version: str | None
    error_code: str | None


class DiagLoadedModel(_Schema):
    name: str
    size_bytes: int
    context_length: int | None
    expires_at: str | None


class DiagModelModel(_Schema):
    primary: str | None
    fallback: str | None
    active: str | None
    active_installed: bool
    fallback_installed: bool
    automatic_fallback: bool
    loaded: DiagLoadedModel | None
    keep_alive: str
    num_ctx: int


class DiagLastTurnModel(_Schema):
    at: str
    outcome: Literal["completed", "cancelled", "failed"]
    failed_stage: str | None = None
    ttft_ms: float | None
    total_ms: float | None
    context_prep_ms: float | None
    runtime_ttft_ms: float | None
    prompt_tokens: int | None
    output_tokens: int | None
    decode_tps: float | None


class DiagPrewarmModel(_Schema):
    state: Literal["idle", "running", "done", "failed", "cancelled"]
    scope: Literal["context", "model_only"] | None = None
    at: str | None = None
    duration_ms: int | None = None
    prompt_tokens: int | None = None
    code: str | None = None


class DiagnosticsResponse(_Schema):
    """Technical state for the diagnostics panel. Never contains message content."""

    runtime: DiagRuntimeModel
    model: DiagModelModel
    last_turn: DiagLastTurnModel | None
    prewarm: DiagPrewarmModel
    cache_expected_warm: bool
    background: Literal["prewarm", "compaction"] | None
    turn_active: bool
