"""Typed error hierarchy.

Every error carries a stable machine-readable ``code`` (also used as the i18n key suffix),
an HTTP status for the API layer and a ``recoverable`` flag. The free-text ``detail`` is for
sanitized logs only and is never returned to API clients.
"""

from __future__ import annotations


class LazisError(Exception):
    code: str = "internal_error"
    http_status: int = 500
    recoverable: bool = False

    def __init__(self, detail: str = "") -> None:
        super().__init__(detail or self.code)
        self.detail = detail


class ConfigError(LazisError):
    code = "config_invalid"


class SecretsError(LazisError):
    code = "secrets_missing"


class StorageError(LazisError):
    code = "database_error"


class EncryptionUnavailableError(StorageError):
    """SQLCipher is missing or encryption could not be verified. Never fall back to plaintext."""

    code = "encryption_unavailable"


class PlaintextDatabaseError(StorageError):
    """A plaintext SQLite file was found where an encrypted database is expected."""

    code = "database_plaintext_detected"


class DatabaseKeyError(StorageError):
    code = "database_key_invalid"
    recoverable = True


class DatabaseCorruptError(StorageError):
    code = "database_corrupt"


class InstanceLockedError(StorageError):
    code = "instance_already_running"


class MigrationError(StorageError):
    code = "migration_failed"


class RestoreError(StorageError):
    """A backup could not be restored. The previous database is left (or put back) in place."""

    code = "restore_failed"
    recoverable = True


class NetworkSandboxError(LazisError):
    """The OS-level network sandbox required by the desktop shell is not in effect."""

    code = "network_sandbox_unavailable"


class AuthError(LazisError):
    code = "unauthorized"
    http_status = 401
    recoverable = True


class OriginNotAllowedError(LazisError):
    code = "origin_not_allowed"
    http_status = 403


class HostNotAllowedError(LazisError):
    code = "host_not_allowed"
    http_status = 403


class RequestTooLargeError(LazisError):
    code = "request_too_large"
    http_status = 413
    recoverable = True


class RateLimitedError(LazisError):
    code = "rate_limited"
    http_status = 429
    recoverable = True


class NotFoundError(LazisError):
    code = "not_found"
    http_status = 404
    recoverable = True


class NetworkBlockedError(PermissionError):
    """Raised by the process-wide network guard for any non-loopback network operation.

    Subclasses ``PermissionError`` (not ``LazisError``) because it is raised from inside
    socket calls, where callers expect an ``OSError``.
    """

    code = "network_blocked"


# ----- local inference (P2) -----------------------------------------------------------
class LlmError(LazisError):
    """The local inference runtime failed in a way not covered below."""

    code = "llm_error"
    http_status = 502
    recoverable = True


class LlmUnavailableError(LlmError):
    """Ollama is not running (or not installed) on 127.0.0.1:11434."""

    code = "llm_unavailable"
    http_status = 503


class LlmModelNotFoundError(LlmError):
    code = "llm_model_not_found"
    http_status = 404


class LlmModelNotAllowedError(LlmError):
    """Cloud models, registry-qualified names and malformed names are never used."""

    code = "llm_model_not_allowed"
    http_status = 400


class LlmOutOfMemoryError(LlmError):
    code = "llm_out_of_memory"
    http_status = 503


class LlmLoadFailedError(LlmError):
    code = "llm_load_failed"
    http_status = 503


class LlmTimeoutError(LlmError):
    code = "llm_timeout"
    http_status = 504


class LlmInvalidResponseError(LlmError):
    code = "llm_invalid_response"
    http_status = 502


class LlmBusyError(LlmError):
    """One generation at a time (single user, single local model)."""

    code = "llm_busy"
    http_status = 409


class LlmCancelledError(LlmError):
    code = "llm_cancelled"
    http_status = 499


# ----- conversations (P3) ----------------------------------------------------------------
class ConversationNotFoundError(NotFoundError):
    code = "conversation_not_found"


class TurnDuplicateError(LazisError):
    """The client re-submitted a message it already sent (same idempotency key)."""

    code = "turn_duplicate"
    http_status = 409
    recoverable = True


class DatabaseBusyError(StorageError):
    """SQLite stayed locked past the busy timeout."""

    code = "database_busy"
    http_status = 503
    recoverable = True


class MessageSaveError(StorageError):
    code = "message_save_failed"
    recoverable = True


class ContextBuildError(LazisError):
    """The prompt for a turn could not be assembled within the context budget."""

    code = "context_failed"
    http_status = 500
    recoverable = True


class MessageTooLongError(LazisError):
    code = "message_too_long"
    http_status = 413
    recoverable = True
