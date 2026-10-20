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

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    # ADR-0001 (Accepted): primary gemma4:12b-it-qat, fallback qwen3.5:9b-q4_K_M.
    # The UI preselects the primary model when installed.
    primary_model: str | None = "gemma4:12b-it-qat"
    # Shown in diagnostics; LAZIS never switches models on its own (the user picks one).
    fallback_model: str | None = "qwen3.5:9b-q4_K_M"
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


class ConversationSection(_Section):
    """Conversation engine (P3): context budget, compaction and cache warming.

    Token values are tokens of the active model, measured by the runtime where possible
    (``prompt_eval_count`` / ``eval_count``) and estimated conservatively otherwise.
    """

    # Named model context profile used for chat turns, compaction and pre-warming. One profile
    # for every request type, so the runtime never reloads the model (ADR-0001).
    context_profile: Literal["short", "normal", "long"] = "normal"
    # Safety margin kept free in the context window, as a fraction of num_ctx (absorbs
    # estimation error for text the runtime has not counted yet).
    safety_fraction: float = Field(default=0.10, ge=0.0, le=0.5)
    # Idle compaction starts when the next prompt is estimated above this many tokens.
    # Chosen from the Phase 2 cold-cache measurement: a cache miss costs ~3.5–4.5 s per 1K
    # tokens on Gemma 4 12B, so the active context is kept well below the hard limit.
    compact_at_tokens: int = Field(default=6144, ge=1024, le=65536)
    # After compaction the most recent messages are kept verbatim up to this many tokens
    # (at least `keep_recent_messages` messages).
    keep_recent_tokens: int = Field(default=2048, ge=256, le=32768)
    keep_recent_messages: int = Field(default=4, ge=2, le=40)
    summary_max_tokens: int = Field(default=1200, ge=200, le=4096)
    # Background compaction waits until no turn has run for this long. Short on purpose: it
    # should run while the user reads the reply; a turn preempts it, and progress is kept
    # per chunk.
    idle_compaction_delay_s: float = Field(default=5.0, ge=0.0, le=3600.0)
    # Estimated tokens of old messages folded into the summary per model call.
    compaction_chunk_tokens: int = Field(default=6000, ge=1024, le=65536)
    # Pre-warm the active conversation's prompt prefix (on open, on typing, after compaction).
    prewarm: bool = True
    # Partial assistant output is persisted at most this often while streaming.
    flush_interval_s: float = Field(default=1.0, gt=0.0, le=30.0)
    flush_chars: int = Field(default=400, ge=1, le=100_000)
    title_max_chars: int = Field(default=60, ge=10, le=200)
    page_size: int = Field(default=50, ge=10, le=500)
    # Conservative estimate for text the runtime has not counted yet. Measured Turkish ratios
    # on Gemma 4 12B were 2.5–3.8 characters per token (code at the low end).
    estimate_chars_per_token: float = Field(default=2.2, gt=0.5, le=8.0)
    estimate_overhead_tokens: int = Field(default=8, ge=0, le=128)

    @model_validator(mode="after")
    def _compaction_can_shrink(self) -> ConversationSection:
        # Compaction keeps a verbatim tail plus the summary; if those alone reach the
        # threshold, compacting could never bring the context back below it.
        if self.keep_recent_tokens + self.summary_max_tokens >= self.compact_at_tokens:
            raise ValueError(
                "conversation.keep_recent_tokens + summary_max_tokens must stay below "
                "compact_at_tokens"
            )
        return self


class VoiceSection(_Section):
    """Placeholder for P13. Voice cannot be enabled before it exists."""

    enabled: Literal[False] = False
    interaction_mode: Literal["push_to_talk", "hands_free_session"] = "push_to_talk"
    microphone_always_on: Literal[False] = False


class PersonalitySection(_Section):
    """LAZIS's communication defaults (P5, ADR-0013). The persona itself (identity, honesty
    rules, style) is versioned code, not configuration; only these preferences are tunable."""

    # adaptive: length follows the question; short / detailed bias every reply.
    verbosity: Literal["adaptive", "short", "detailed"] = "adaptive"
    humor: Literal["light", "off"] = "light"


class MemorySection(_Section):
    """Personal memory (P6, MEMORY_ARCHITECTURE). Everything stays in the encrypted database."""

    # Learn from conversations in the background (after each reply, on the cached prefix).
    auto_extract: bool = True
    # Only these models may write memory, automatically or on request. Chosen from the
    # extraction gold set (PHASE_6_REPORT): another model's turns are queued as "deferred"
    # and processed when a trusted model is in use again.
    trusted_models: tuple[str, ...] = ("gemma4:12b-it-qat",)
    # Output budget of one extraction request (an empty result is ~5 tokens).
    extraction_max_tokens: int = Field(default=700, ge=100, le=4096)
    # Queued user messages processed per extraction request.
    batch_messages: int = Field(default=3, ge=1, le=10)
    # A job that failed this many times stays failed (visible in diagnostics).
    max_attempts: int = Field(default=3, ge=1, le=10)
    # Recall: at most this many (estimated) tokens of memory in front of a user message. Each
    # token is new prefill for that turn (~4 ms on Gemma 4 12B here: 200 tokens ≈ +0.8 s TTFT).
    context_budget_tokens: int = Field(default=200, ge=0, le=4000)
    # Background learning starts only after this long without a turn.
    learn_after_idle_s: float = Field(default=6.0, ge=0.0, le=600.0)


class Settings(_Section):
    app: AppSection = AppSection()
    backend: BackendSection = BackendSection()
    storage: StorageSection = StorageSection()
    logging: LoggingSection = LoggingSection()
    network: NetworkSection = NetworkSection()
    research: ResearchSection = ResearchSection()
    models: ModelsSection = ModelsSection()
    conversation: ConversationSection = ConversationSection()
    personality: PersonalitySection = PersonalitySection()
    memory: MemorySection = MemorySection()
    voice: VoiceSection = VoiceSection()

    def effective_origins(self) -> tuple[str, ...]:
        if self.app.environment == "development":
            return self.backend.allowed_origins + self.backend.dev_origins
        return self.backend.allowed_origins
