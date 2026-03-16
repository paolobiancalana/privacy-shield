# privacy-shield/app/infrastructure/telemetry.py
"""
Structured JSON logging for the Privacy Shield microservice.

Design rules:
  - NEVER log PII values, original text, or token→plaintext mappings.
  - Log operation name, org_id, duration_ms, counts, and source only.
  - JSON format for log aggregation (Loki, CloudWatch, etc.).
  - Uses stdlib 'logging' with a custom JSON formatter — no third-party log lib.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any


class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, datefmt="%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Merge any extra fields attached to the record
        for key, value in record.__dict__.items():
            if key.startswith("_ps_"):
                payload[key[4:]] = value  # strip "_ps_" prefix

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure the root logger and the 'privacy_shield' logger.

    Call once during application startup (in lifespan or main).
    """
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(log_level)

    # Suppress noisy uvicorn access logs from polluting structured output
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a child logger under 'privacy_shield.*' namespace."""
    return logging.getLogger(f"privacy_shield.{name}")


# Allowlist of safe (non-PII) kwargs that log_operation accepts.
# Any key not in this set is rejected with ValueError to prevent accidental
# PII leakage via structured log fields.
SAFE_LOG_FIELDS: frozenset[str] = frozenset({
    "token_count",
    "span_count",
    "source",
    "rehydrated_count",
    "flushed_count",
    "duration_ms",
    "org_id",
    "request_id",
    "operation",
    "detection_ms",
    "tokenization_ms",
    "status",
    "key_id",
    "plan",
    "count",
    "limit",
    "error_code",
    "re_encrypted_count",
    "component_status",
    # Additional operational fields used by existing call sites
    "text_count",
    "environment",
    "key_hash",
})


def log_operation(
    logger: logging.Logger,
    operation: str,
    org_id: str,
    duration_ms: float,
    **kwargs: Any,
) -> None:
    """
    Emit a structured INFO log for a completed operation.

    Only keys present in SAFE_LOG_FIELDS are allowed in kwargs.
    Any forbidden key raises ValueError immediately so PII can never
    be accidentally written to structured logs.

    FORBIDDEN in kwargs:
      original_text, pii_value, token_hash_to_value_mapping, decrypted_*
    """
    for key in kwargs:
        if key not in SAFE_LOG_FIELDS:
            raise ValueError(f"Forbidden log field: {key}")

    extra: dict[str, Any] = {
        "_ps_operation": operation,
        "_ps_org_id": org_id,
        "_ps_duration_ms": round(duration_ms, 3),
    }
    for k, v in kwargs.items():
        extra[f"_ps_{k}"] = v

    logger.info(
        f"operation={operation} org={org_id} duration_ms={round(duration_ms, 3)}",
        extra=extra,
    )


def log_error(
    logger: logging.Logger,
    operation: str,
    org_id: str,
    error_code: str,
    message: str,
    exc: Exception | None = None,
) -> None:
    """
    Emit a structured ERROR log.

    'message' must NOT contain PII. Keep it generic (e.g. "vault retrieval failed").
    """
    extra: dict[str, Any] = {
        "_ps_operation": operation,
        "_ps_org_id": org_id,
        "_ps_error_code": error_code,
    }
    logger.error(
        f"operation={operation} org={org_id} error={error_code}: {message}",
        extra=extra,
        exc_info=exc,
    )
