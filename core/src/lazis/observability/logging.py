"""Structured JSON-lines logging with mandatory redaction and size-based rotation.

Rules (ENGINEERING_STANDARDS §12): event-style messages, content-free, no secrets. Every
record passes through :class:`RedactionFilter` before it is formatted.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import sys
import traceback
from datetime import UTC, datetime
from typing import Any

from lazis.config.model import LoggingSection
from lazis.fsutil import ensure_private_dir, ensure_private_file
from lazis.observability.redaction import SecretRegistry

ROOT_LOGGER = "lazis"
LOG_FILENAME = "core.log"


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{ROOT_LOGGER}.{name}")


def log_event(logger: logging.Logger, level: int, event: str, **fields: Any) -> None:
    logger.log(level, event, extra={"lazis_fields": fields})


def _scrub_value(value: Any, registry: SecretRegistry) -> Any:
    if isinstance(value, str):
        return registry.scrub(value)
    if isinstance(value, bool | int | float) or value is None:
        return value
    if isinstance(value, dict):
        return {str(k): _scrub_value(v, registry) for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
    if isinstance(value, list | tuple):
        return [_scrub_value(v, registry) for v in value]  # pyright: ignore[reportUnknownVariableType]
    return registry.scrub(repr(value))


class RedactionFilter(logging.Filter):
    def __init__(self, registry: SecretRegistry) -> None:
        super().__init__()
        self._registry = registry

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._registry.scrub(record.getMessage())
        record.args = None
        fields = getattr(record, "lazis_fields", None)
        if isinstance(fields, dict):
            record.lazis_fields = _scrub_value(fields, self._registry)
        if record.exc_info and record.exc_info[1] is not None:
            exc = record.exc_info[1]
            text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            record.lazis_exc = self._registry.scrub(text)
            record.exc_info = None
            record.exc_text = None
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields = getattr(record, "lazis_fields", None)
        if isinstance(fields, dict):
            payload.update(fields)  # pyright: ignore[reportUnknownArgumentType]
        exc_text = getattr(record, "lazis_exc", None)
        if exc_text:
            payload["exception"] = exc_text
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(section: LoggingSection, registry: SecretRegistry) -> logging.Handler:
    """Configure the ``lazis`` logger tree. Returns the file handler (for tests/shutdown)."""
    ensure_private_dir(section.directory)
    log_path = section.directory / LOG_FILENAME
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=section.max_bytes, backupCount=section.backup_count, encoding="utf-8"
    )
    ensure_private_file(log_path)
    redaction = RedactionFilter(registry)
    formatter = JsonFormatter()
    handlers: list[logging.Handler] = [file_handler]
    if section.console:
        handlers.append(logging.StreamHandler(sys.stderr))
    for handler in handlers:
        handler.addFilter(redaction)
        handler.setFormatter(formatter)

    root = logging.getLogger(ROOT_LOGGER)
    root.handlers.clear()
    root.setLevel(section.level)
    root.propagate = False
    for handler in handlers:
        root.addHandler(handler)

    # Third-party loggers: warnings and errors only, through the same redacting handlers.
    for name in ("uvicorn", "uvicorn.error", "fastapi"):
        third = logging.getLogger(name)
        third.handlers.clear()
        third.setLevel(logging.WARNING)
        third.propagate = False
        for handler in handlers:
            third.addHandler(handler)
    logging.getLogger("uvicorn.access").disabled = True
    return file_handler
