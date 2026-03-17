"""
FastAPI application entry point for the Privacy Shield microservice.

Startup sequence:
  1. Load Settings (validates KEK and env vars — fails fast if misconfigured).
  2. Configure structured JSON logging.
  3. Create Container and initialize (connects Redis, validates crypto).
  4. Mount API router.
  5. Register exception handlers.

Shutdown sequence (T4.6 — Graceful Shutdown):
  1. Set 'shutting_down' flag → new requests receive 503 immediately.
  2. Wait for in-flight requests to drain (up to SHUTDOWN_DRAIN_SECONDS).
  3. Scan and UNLINK all orphaned ps:req:* pipeline request sets in Redis.
  4. Close the Redis connection pool.

The lifespan context manager handles SIGTERM automatically — FastAPI/uvicorn
deliver the signal as a cancellation of the lifespan async generator, which
triggers the `finally` branch.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.container import Container
from app.infrastructure.api.billing_stub import billing_router
from app.infrastructure.api.middleware import (
  global_exception_handler,
  validation_exception_handler,
)
from app.infrastructure.api.routes import router
from app.infrastructure.config import Settings
from app.infrastructure.telemetry import configure_logging, get_logger

_logger = get_logger("main")

_SHUTDOWN_DRAIN_SECONDS = 10

_shutdown_flag: list[bool] = [False]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
  """
  Application lifespan: initialize on startup, drain and shutdown on exit.

  Storing the container on app.state makes it accessible to route handlers
  via the _get_container() dependency without globals.
  """
  settings: Settings = app.state.settings
  container = Container(config=settings)
  app.state.container = container
  app.state.active_requests = 0

  try:
    await container.initialize()
    _logger.info(
      "Privacy Shield microservice started",
      extra={"_ps_operation": "startup", "_ps_version": settings.version},
    )
    yield

  finally:
    _shutdown_flag[0] = True
    _logger.info(
      "Shutdown initiated — rejecting new requests",
      extra={"_ps_operation": "shutdown"},
    )

    active = getattr(app.state, "active_requests", 0)
    if active > 0:
      _logger.info(
        "Draining in-flight requests",
        extra={"_ps_operation": "shutdown", "_ps_active_requests": active},
      )
      deadline = asyncio.get_event_loop().time() + _SHUTDOWN_DRAIN_SECONDS
      while app.state.active_requests > 0:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
          _logger.warning(
            "Drain timeout exceeded — forcing shutdown",
            extra={
              "_ps_operation": "shutdown",
              "_ps_active_requests": app.state.active_requests,
            },
          )
          break
        await asyncio.sleep(0.1)

    await _flush_orphaned_request_sets(container)

    await container.shutdown()
    _logger.info(
      "Privacy Shield microservice stopped",
      extra={"_ps_operation": "shutdown"},
    )


async def _flush_orphaned_request_sets(container: Container) -> None:
  """
  UNLINK all ps:req:* keys left in Redis by pipeline requests that did not
  explicitly call /flush (e.g. timed-out SNAP pipeline requests).

  Uses SCAN with MATCH to avoid blocking the Redis server. UNLINK is
  non-blocking (background deletion) — appropriate for shutdown.
  """
  try:
    redis = container.redis_client
    pattern = "ps:req:*"
    cursor = 0
    unlinked = 0
    while True:
      cursor, keys = await redis.scan(cursor=cursor, match=pattern, count=200)
      if keys:
        count = await redis.unlink(*keys)
        unlinked += count
      if cursor == 0:
        break
    _logger.info(
      "Orphaned request sets flushed",
      extra={"_ps_operation": "shutdown", "_ps_unlinked_keys": unlinked},
    )
  except Exception as exc:
    _logger.warning(
      "Failed to flush orphaned request sets during shutdown",
      extra={"_ps_operation": "shutdown", "_ps_error": str(exc)},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
  """
  Application factory.

  Accepts optional Settings for testing (allows injecting test config
  without relying on environment variables). Production path loads from env.
  """
  if settings is None:
    settings = Settings()

  configure_logging(settings.log_level)

  app = FastAPI(
    title="Privacy Shield",
    description=(
      "Italian PII tokenization microservice. "
      "Replaces PII with opaque tokens and stores encrypted values in Redis."
    ),
    version=settings.version,
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
  )

  app.state.settings = settings

  @app.middleware("http")
  async def shutdown_guard(request: Request, call_next):
    """Return 503 for all non-health requests during shutdown."""
    if _shutdown_flag[0] and request.url.path not in ("/health", "/metrics"):
      return JSONResponse(
        status_code=503,
        content={"error": "Service is shutting down", "code": "SHUTTING_DOWN"},
      )

    app.state.active_requests = getattr(app.state, "active_requests", 0) + 1
    try:
      response = await call_next(request)
      return response
    finally:
      app.state.active_requests = max(
        0, getattr(app.state, "active_requests", 1) - 1
      )

  app.include_router(router)
  app.include_router(billing_router)

  app.add_exception_handler(Exception, global_exception_handler)
  app.add_exception_handler(RequestValidationError, validation_exception_handler)

  return app


app = create_app()
