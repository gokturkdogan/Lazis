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
