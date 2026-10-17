"""FastAPI application for API v1 (Phase 1: health, app info, system status, settings view).

No LLM, memory or research endpoints exist in Phase 1 by design.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import resource
import sys
import time
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from lazis import API_VERSION, PHASE, __version__
from lazis.api.schemas import (
    AiStatus,
    AppInfoResponse,
    BackendStatus,
    DatabaseStatusModel,
    EffectiveSettingsResponse,
    ErrorResponse,
    HealthCheck,
    HealthResponse,
    PrivacyStatus,
    SystemStatusResponse,
)
from lazis.api.security import LocalApiGuard, TokenBucket, error_payload
from lazis.config.model import Settings
from lazis.errors import LazisError
from lazis.observability.logging import get_logger, log_event
from lazis.storage import StorageHandle

_log = get_logger("api")
PREFIX = f"/api/{API_VERSION}"
_ERRORS: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    429: {"model": ErrorResponse},
    500: {"model": ErrorResponse},
}


@dataclass
class ApiContext:
    settings: Settings
    storage: StorageHandle | None
    token_matches: Callable[[str], bool]
    port: int = 0
    started_monotonic: float = field(default_factory=time.monotonic)
    started_at: str = ""
    on_startup: Callable[[], None] | None = None
    on_shutdown: Callable[[], None] | None = None
    on_denied: Callable[[str], None] | None = None

    def require_storage(self) -> StorageHandle:
        if self.storage is None:
            raise LazisError("storage not initialised")
        return self.storage


def _json_error(status: int, code: str, recoverable: bool, request: Request) -> JSONResponse:
    request_id = str(request.scope.get("state", {}).get("request_id", "")) or "-"
    return JSONResponse(
        status_code=status, content=json.loads(error_payload(code, recoverable, request_id))
    )


def create_app(ctx: ApiContext) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        if ctx.on_startup is not None:
            ctx.on_startup()
        yield
        if ctx.on_shutdown is not None:
            ctx.on_shutdown()

    app = FastAPI(
        title="LAZIS Core",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,  # schema is exported via the CLI, never served
        lifespan=lifespan,
    )

    @app.exception_handler(LazisError)
    async def _lazis_error(request: Request, exc: LazisError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        log_event(_log, logging.WARNING, "api.error", code=exc.code, path=request.url.path)
        return _json_error(exc.http_status, exc.code, exc.recoverable, request)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, _exc: RequestValidationError) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        return _json_error(422, "validation_error", True, request)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        code = "not_found" if exc.status_code == 404 else "internal_error"
        return _json_error(exc.status_code, code, exc.status_code < 500, request)

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        _log.error(
            "api.unexpected_error", exc_info=exc, extra={"lazis_fields": {"path": request.url.path}}
        )
        return _json_error(500, "internal_error", False, request)

    @app.get(f"{PREFIX}/health", response_model=HealthResponse, responses=_ERRORS)
    async def health() -> HealthResponse:  # pyright: ignore[reportUnusedFunction]
        checks: dict[str, HealthCheck] = {}
        try:
            storage = ctx.require_storage()
            await storage.db.run(lambda conn: conn.execute("SELECT 1").fetchone())
            checks["database"] = HealthCheck(status="ok")
        except Exception:
            checks["database"] = HealthCheck(status="failed", code="database_error")
        overall = "ok" if all(c.status == "ok" for c in checks.values()) else "degraded"
        return HealthResponse(status=overall, version=__version__, checks=checks)

    @app.get(f"{PREFIX}/app/info", response_model=AppInfoResponse, responses=_ERRORS)
    async def app_info() -> AppInfoResponse:  # pyright: ignore[reportUnusedFunction]
        return AppInfoResponse(
            name="LAZIS",
            version=__version__,
            api_version=API_VERSION,
            phase=PHASE,
            environment=ctx.settings.app.environment,
            python_version=platform.python_version(),
        )

    @app.get(f"{PREFIX}/system/status", response_model=SystemStatusResponse, responses=_ERRORS)
    async def system_status() -> SystemStatusResponse:  # pyright: ignore[reportUnusedFunction]
        storage = ctx.require_storage()
        db_status = await storage.db.astatus()
        usage = resource.getrusage(resource.RUSAGE_SELF)
        peak_rss = usage.ru_maxrss if sys.platform == "darwin" else usage.ru_maxrss * 1024
        return SystemStatusResponse(
            backend=BackendStatus(
                pid=os.getpid(),
                started_at=ctx.started_at,
                uptime_seconds=round(time.monotonic() - ctx.started_monotonic, 3),
                peak_rss_bytes=int(peak_rss),
                python_version=platform.python_version(),
                platform=platform.platform(terse=True),
                machine=platform.machine(),
            ),
            database=DatabaseStatusModel(
                state="ready",
                encrypted=db_status.encrypted,
                encryption_verified=db_status.encryption_verified,
                cipher_version=db_status.cipher_version,
                cipher_provider=db_status.cipher_provider,
                sqlite_version=db_status.sqlite_version,
                schema_version=storage.schema_version,
                journal_mode=db_status.journal_mode,
                integrity="ok" if db_status.quick_check == "ok" else "failed",
                size_bytes=db_status.size_bytes,
                instance_id=storage.meta.get("instance_id", ""),
                created_at=storage.meta.get("created_at", ""),
            ),
            privacy=PrivacyStatus(
                network_egress="disabled",
                research_mode=ctx.settings.research.mode,
                microphone="off",
                voice_enabled=ctx.settings.voice.enabled,
            ),
            ai=AiStatus(
                configured=False,
                provider=ctx.settings.models.provider,
                available_from_phase="P2",
            ),
        )

    @app.get(f"{PREFIX}/settings", response_model=EffectiveSettingsResponse, responses=_ERRORS)
    async def effective_settings() -> EffectiveSettingsResponse:  # pyright: ignore[reportUnusedFunction]
        s = ctx.settings
        return EffectiveSettingsResponse(
            environment=s.app.environment,
            data_dir=str(s.storage.data_dir),
            log_dir=str(s.logging.directory),
            log_level=s.logging.level,
            research_mode=s.research.mode,
            network_egress_enabled=s.network.egress_enabled,
            voice_enabled=s.voice.enabled,
            voice_interaction_mode=s.voice.interaction_mode,
            models_provider=s.models.provider,
            models_primary_model=s.models.primary_model,
            models_context_length=s.models.context_length,
            backups_keep=s.storage.backups_keep,
            max_request_bytes=s.backend.max_request_bytes,
        )

    guarded = LocalApiGuard(
        app,
        token_matches=ctx.token_matches,
        allowed_host=lambda: f"127.0.0.1:{ctx.port}",
        allowed_origins=frozenset(ctx.settings.effective_origins()),
        max_request_bytes=ctx.settings.backend.max_request_bytes,
        bucket=TokenBucket(
            ctx.settings.backend.rate_limit_per_second, ctx.settings.backend.rate_limit_burst
        ),
        on_denied=ctx.on_denied,
    )
    app.state.guarded_asgi = guarded
    return app


def build_asgi(ctx: ApiContext) -> tuple[FastAPI, LocalApiGuard]:
    app = create_app(ctx)
    return app, app.state.guarded_asgi
