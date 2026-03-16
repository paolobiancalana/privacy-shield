# privacy-shield/app/infrastructure/api/middleware.py
"""
FastAPI middleware and exception handlers for the Privacy Shield API.

Responsibilities:
  - Catch all unhandled exceptions and return structured ErrorResponse (no stack traces).
  - Log errors without PII in the message.
  - Provide a dependency that injects a fresh request_id when the caller omits one.

org_id validation is handled at the Pydantic schema level (field_validator),
so middleware only deals with generic exception boundaries.
"""
from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.infrastructure.api.schemas import ErrorResponse
from app.infrastructure.telemetry import get_logger, log_error

_logger = get_logger("middleware")


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all exception handler registered on the FastAPI app.

    Returns a sanitized 500 response. NEVER exposes internal error details,
    stack traces, or PII in the response body.
    """
    log_error(
        _logger,
        operation="request",
        org_id="unknown",  # org_id may not be parsed yet
        error_code="INTERNAL_ERROR",
        message=f"Unhandled exception on {request.method} {request.url.path}",
        exc=exc,
    )
    body = ErrorResponse(
        error="Internal server error",
        code="INTERNAL_ERROR",
        detail=None,  # deliberately empty — no internal detail leaked
    )
    return JSONResponse(status_code=500, content=body.model_dump())


async def validation_exception_handler(
    request: Request, exc: Exception
) -> JSONResponse:
    """
    Handle Pydantic validation errors (422 Unprocessable Entity).

    The error message is sanitized to remove any PII that may appear in
    validation failure messages (e.g. the invalid field value itself).
    """
    if isinstance(exc, ValidationError):
        # Extract field names and error messages only — not the actual values
        errors = [
            {"field": ".".join(str(loc) for loc in e["loc"]), "msg": e["msg"]}
            for e in exc.errors()
        ]
        body = ErrorResponse(
            error="Validation failed",
            code="VALIDATION_ERROR",
            detail=str(errors),
        )
        return JSONResponse(status_code=422, content=body.model_dump())

    # Fallback for RequestValidationError
    body = ErrorResponse(
        error="Request validation failed",
        code="VALIDATION_ERROR",
        detail=None,
    )
    return JSONResponse(status_code=422, content=body.model_dump())


def generate_request_id() -> str:
    """FastAPI dependency: return a fresh UUID4 string as request_id."""
    return str(uuid.uuid4())
