"""``serve``: the managed backend process started by the desktop shell.

Startup order (fail closed at every step, reporting a code through the handshake):

1. umask 077 → close inherited descriptors → configuration → logging (redacting)
2. OS network sandbox check (required when started by the desktop shell) → network and
   process guard (audit hook)
3. startup secrets from stdin (token + database key) → registered for redaction
4. encrypted storage: data-directory lock (single instance), recovery of an interrupted
   restore, driver check, open, migrate with pre-migration backup, verify
5. bind 127.0.0.1:0 (OS-assigned port) → serve; READY handshake after app startup

Shutdown is triggered by stdin EOF (the shell exited or closed the lifeline), the parent
process disappearing, or SIGTERM/SIGINT. It is always graceful: audit, WAL checkpoint, close.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import uvicorn

from lazis import API_VERSION, __version__
from lazis.api.app_factory import ApiContext, build_asgi
from lazis.app.handshake import EXIT_FATAL, EXIT_OK, emit_fatal, emit_ready
from lazis.config import Settings, load_settings
from lazis.config.model import APP_SUPPORT
from lazis.errors import ConfigError, LazisError, NetworkSandboxError
from lazis.ids import utc_now_iso
from lazis.observability import SecretRegistry, get_logger, log_event, setup_logging
from lazis.providers.llm.ollama import OllamaProvider
from lazis.security.network_guard import (
    SandboxStatus,
    close_inherited_descriptors,
    install_network_guard,
    os_network_sandbox_status,
)
from lazis.security.secrets import StartupSecrets, read_secrets_from_fd
from lazis.storage import StorageHandle, open_storage
from lazis.storage.repositories import write_audit

_log = get_logger("app")


@dataclass(frozen=True)
class ServeOptions:
    environment: str | None = None
    data_dir: Path | None = None
    log_dir: Path | None = None
    config_path: Path | None = None
    secrets_timeout: float | None = None
    require_os_sandbox: bool = False


def _overrides(options: ServeOptions) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    if options.environment:
        result.setdefault("app", {})["environment"] = options.environment
    if options.data_dir:
        result.setdefault("storage", {})["data_dir"] = str(options.data_dir)
    if options.log_dir:
        result.setdefault("logging", {})["directory"] = str(options.log_dir)
    if options.secrets_timeout:
        result.setdefault("backend", {})["secrets_timeout_seconds"] = options.secrets_timeout
    return result


def _watch_lifeline(fd: int, stop: Callable[[str], None]) -> None:
    try:
        while os.read(fd, 4096):
            pass
    except OSError:
        pass
    stop("lifeline_closed")


def _watch_parent(original_ppid: int, stop: Callable[[str], None]) -> None:
    while True:
        time.sleep(1.0)
        if os.getppid() != original_ppid:
            stop("parent_exited")
            return


def _bind_loopback(settings: Settings) -> socket.socket:
    family = socket.AF_INET6 if ":" in settings.backend.host else socket.AF_INET
    sock = socket.socket(family, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((settings.backend.host, settings.backend.port))
    sock.listen(64)
    sock.set_inheritable(False)
    return sock


def serve(options: ServeOptions, *, stdin_fd: int | None = None) -> int:
    os.umask(0o077)
    keep = frozenset({0, 1, 2} | ({stdin_fd} if stdin_fd is not None else set()))
    inherited_closed = close_inherited_descriptors(keep)
    registry = SecretRegistry()
    user_config = options.config_path or (APP_SUPPORT / "config.toml")
    try:
        settings = load_settings(
            user_config=user_config, environ=os.environ, overrides=_overrides(options)
        )
    except ConfigError as exc:
        # Logging is not configured yet; field paths only (no values) go to stderr.
        sys.stderr.write(f"lazis-core: configuration invalid: {exc.detail}\n")
        emit_fatal(exc.code)
        return EXIT_FATAL

    file_handler = setup_logging(settings.logging, registry)
    sandbox = os_network_sandbox_status()
    log_event(
        _log,
        logging.INFO,
        "app.starting",
        version=__version__,
        environment=settings.app.environment,
        pid=os.getpid(),
        os_network_sandbox=sandbox,
        inherited_descriptors_closed=len(inherited_closed),
        inherited_descriptor_kinds=inherited_closed,
    )
    install_network_guard(
        on_block=lambda event, _target: log_event(
            _log, logging.WARNING, "security.policy_blocked", audit_event=event
        )
    )

    storage: StorageHandle | None = None
    try:
        if options.require_os_sandbox and sandbox != "enforced":
            raise NetworkSandboxError(f"OS network sandbox status: {sandbox}")
        secrets: StartupSecrets = read_secrets_from_fd(
            sys.stdin.fileno() if stdin_fd is None else stdin_fd,
            settings.backend.secrets_timeout_seconds,
        )
        registry.register(secrets.session_token)
        registry.register(secrets.db_key.hex())
        storage = open_storage(settings.storage, secrets.db_key, app_version=__version__)
        return _run_server(settings, secrets, storage, stdin_fd, sandbox)
    except LazisError as exc:
        log_event(_log, logging.ERROR, "app.startup_failed", code=exc.code)
        emit_fatal(exc.code)
        return EXIT_FATAL
    except Exception as exc:
        _log.error("app.unexpected_failure", exc_info=exc)
        emit_fatal("internal_error")
        return EXIT_FATAL
    finally:
        if storage is not None:
            storage.db.close()  # also releases the data-directory lock
            log_event(_log, logging.INFO, "storage.closed")
        log_event(_log, logging.INFO, "app.stopped")
        file_handler.flush()


def _run_server(
    settings: Settings,
    secrets: StartupSecrets,
    storage: StorageHandle,
    stdin_fd: int | None,
    sandbox: SandboxStatus,
) -> int:
    db = storage.db
    db.run_sync(
        lambda conn: write_audit(
            conn,
            category="app",
            action="started",
            outcome="success",
            details={"version": __version__, "schema_version": storage.schema_version},
        )
    )

    def _on_denied(code: str) -> None:
        with contextlib.suppress(Exception):  # auditing must never break request handling
            db.run_sync(
                lambda conn: write_audit(
                    conn,
                    category="security",
                    action="request_denied",
                    outcome="denied",
                    reason_code=code,
                )
            )

    sock = _bind_loopback(settings)
    port = int(sock.getsockname()[1])
    ctx = ApiContext(
        settings=settings,
        storage=storage,
        token_matches=secrets.token_matches,
        port=port,
        started_at=utc_now_iso(),
        on_denied=_on_denied,
        os_network_sandbox=sandbox,
        llm=OllamaProvider(settings.models.endpoint),
    )
    _, asgi = build_asgi(ctx)

    config = uvicorn.Config(
        asgi,
        log_config=None,
        access_log=False,
        server_header=False,
        date_header=False,
        lifespan="on",
        limit_concurrency=settings.backend.limit_concurrency,
        timeout_graceful_shutdown=settings.backend.shutdown_timeout_seconds,
        h11_max_incomplete_event_size=16 * 1024,
    )
    server = uvicorn.Server(config)
    stop_reason: list[str] = []

    def stop(reason: str) -> None:
        if not stop_reason:
            stop_reason.append(reason)
            log_event(_log, logging.INFO, "app.stopping", reason=reason)
        server.should_exit = True

    def on_startup() -> None:
        log_event(_log, logging.INFO, "app.ready", port=port, api_version=API_VERSION)
        emit_ready(
            port=port,
            pid=os.getpid(),
            api_version=API_VERSION,
            version=__version__,
            schema_version=storage.schema_version,
        )

    ctx.on_startup = on_startup
    # uvicorn re-raises a captured signal after its graceful shutdown using the handler that
    # was installed before it started. Installing ours first means that re-raise only calls
    # stop() again instead of killing the process before our cleanup (audit, checkpoint,
    # lock release) has run.
    for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(sig, lambda signum, _frame: stop(f"signal_{signal.Signals(signum).name}"))
    fd = sys.stdin.fileno() if stdin_fd is None else stdin_fd
    threading.Thread(target=_watch_lifeline, args=(fd, stop), name="lifeline", daemon=True).start()
    threading.Thread(
        target=_watch_parent, args=(os.getppid(), stop), name="parent-watch", daemon=True
    ).start()

    try:
        asyncio.run(server.serve(sockets=[sock]))
    finally:
        sock.close()
        reason = stop_reason[0] if stop_reason else "signal"
        db.run_sync(
            lambda conn: write_audit(
                conn, category="app", action="stopped", outcome="success", reason_code=reason
            )
        )
    return EXIT_OK
