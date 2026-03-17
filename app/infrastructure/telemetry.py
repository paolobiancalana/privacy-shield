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

import hashlib
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
    # Audit / GDPR Article 30 fields
    "audit",
    "pii_type_counts",
    "org_hash",
    # Plan system fields
    "plan_id",
    "from_plan",
    "to_plan",
    "monthly_limit",
    "monthly_used",
    "active_keys",
    "max_keys",
    "price_cents",
    "remaining_tokens",
    "percent_used",
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


_audit_logger = get_logger("audit")


def log_processing_activity(
    operation: str,
    org_id: str,
    pii_types_detected: list[str],
    token_count: int,
    duration_ms: float,
) -> None:
    """
    GDPR Article 30 — Record of Processing Activities.

    Writes a structured audit log entry for every data processing operation.
    The org_id is hashed (SHA-256, first 12 hex chars) to pseudonymise the record.

    NEVER writes: actual PII, token values, request body, IP addresses.
    """
    org_hash = hashlib.sha256(org_id.encode()).hexdigest()[:12]

    # Aggregate PII type counts for Article 30 record — audit logs are
    # access-controlled, unlike Prometheus metrics which omit type distribution.
    type_counts: dict[str, int] = {}
    for t in pii_types_detected:
        type_counts[t] = type_counts.get(t, 0) + 1

    _audit_logger.info(
        f"processing_activity operation={operation}",
        extra={
            "_ps_audit": True,
            "_ps_operation": operation,
            "_ps_org_hash": org_hash,
            "_ps_pii_type_counts": type_counts,
            "_ps_token_count": token_count,
            "_ps_duration_ms": round(duration_ms, 3),
        },
    )
