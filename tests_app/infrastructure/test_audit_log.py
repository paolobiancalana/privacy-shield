"""
log_processing_activity() — GDPR Article 30 audit logger adversarial tests.

Adversarial Analysis:
  1. org_id leakage: If the raw org_id appears anywhere in the log record
     (message string, extra fields), the pseudonymisation contract is broken.
     The function must only emit the SHA-256[:12] hash.
  2. PII injection via pii_types_detected: If callers pass actual PII values
     (e.g. "RSSMRA85M01H501Z") instead of type codes (e.g. "cf"), the audit
     log would contain PII in the type_counts field. We can't prevent this
     at the function boundary, but we CAN verify that no forbidden fields
     (original_text, pii_value) are accepted.
  3. Duration precision: round(duration_ms, 3) should produce at most 3
     decimal places. Verify this explicitly.

Boundary Map:
  pii_types_detected: [] (empty), ["pe"] (single), ["pe","pe","cf"] (dups)
  token_count: 0, 1, 2**31 (very large)
  duration_ms: 0.0, 0.1234567 (precision), 1e15 (very large)
  org_id: UUID string, empty string, string with special chars
"""
from __future__ import annotations

import hashlib
import json
import logging
from unittest.mock import MagicMock, patch

import pytest

from app.infrastructure.telemetry import log_processing_activity


# ── Helpers ─────────────────────────────────────────────────────────

class _CaptureHandler(logging.Handler):
    """Logging handler that captures all LogRecord objects for assertion."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _capture_audit_log(
    operation: str = "tokenize",
    org_id: str = "org-abc-123",
    pii_types_detected: list[str] | None = None,
    token_count: int = 5,
    duration_ms: float = 12.345,
) -> logging.LogRecord:
    """Call log_processing_activity and capture the emitted LogRecord."""
    if pii_types_detected is None:
        pii_types_detected = ["pe", "cf"]

    handler = _CaptureHandler()
    logger = logging.getLogger("privacy_shield.audit")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)

    try:
        log_processing_activity(
            operation=operation,
            org_id=org_id,
            pii_types_detected=pii_types_detected,
            token_count=token_count,
            duration_ms=duration_ms,
        )
        assert len(handler.records) == 1, f"Expected 1 log record, got {len(handler.records)}"
        return handler.records[0]
    finally:
        logger.removeHandler(handler)


# ── Happy Path ──────────────────────────────────────────────────────

class TestAuditLogHappyPath:
    """Standard GDPR Article 30 audit log emission."""

    def test_emits_structured_log_with_expected_fields(self) -> None:
        """Log record contains operation, org_hash, pii_type_counts, token_count, duration_ms."""
        record = _capture_audit_log(
            operation="tokenize",
            org_id="org-abc-123",
            pii_types_detected=["pe", "cf", "pe"],
            token_count=3,
            duration_ms=15.678,
        )

        assert record._ps_audit is True  # type: ignore[attr-defined]
        assert record._ps_operation == "tokenize"  # type: ignore[attr-defined]
        assert record._ps_token_count == 3  # type: ignore[attr-defined]
        assert record._ps_duration_ms == 15.678  # type: ignore[attr-defined]

    def test_org_id_is_hashed_sha256_prefix(self) -> None:
        """org_hash is the first 12 hex chars of SHA-256(org_id)."""
        org_id = "org-abc-123"
        expected_hash = hashlib.sha256(org_id.encode()).hexdigest()[:12]

        record = _capture_audit_log(org_id=org_id)

        assert record._ps_org_hash == expected_hash  # type: ignore[attr-defined]
        assert len(record._ps_org_hash) == 12  # type: ignore[attr-defined]

    def test_pii_type_counts_aggregated_correctly(self) -> None:
        """Duplicate PII types are counted correctly."""
        record = _capture_audit_log(
            pii_types_detected=["pe", "cf", "pe", "ib", "pe"],
        )

        type_counts = record._ps_pii_type_counts  # type: ignore[attr-defined]
        assert type_counts == {"pe": 3, "cf": 1, "ib": 1}

    def test_different_org_ids_produce_different_hashes(self) -> None:
        """Two different org_ids must produce different hashes."""
        record_a = _capture_audit_log(org_id="org-alpha")
        record_b = _capture_audit_log(org_id="org-beta")

        assert record_a._ps_org_hash != record_b._ps_org_hash  # type: ignore[attr-defined]


# ── Edge Cases ──────────────────────────────────────────────────────

class TestAuditLogEdgeCases:
    """Boundary and unusual input handling."""

    def test_empty_pii_types_produces_empty_dict(self) -> None:
        """Empty pii_types_detected list produces empty type_counts dict."""
        record = _capture_audit_log(pii_types_detected=[])

        type_counts = record._ps_pii_type_counts  # type: ignore[attr-defined]
        assert type_counts == {}

    def test_single_pii_type(self) -> None:
        """Single PII type produces dict with one entry."""
        record = _capture_audit_log(pii_types_detected=["email"])

        type_counts = record._ps_pii_type_counts  # type: ignore[attr-defined]
        assert type_counts == {"email": 1}

    def test_large_token_count_no_overflow(self) -> None:
        """Very large token_count does not cause overflow (Python ints are arbitrary precision)."""
        record = _capture_audit_log(token_count=2**31)

        assert record._ps_token_count == 2**31  # type: ignore[attr-defined]

    def test_zero_token_count(self) -> None:
        """Zero token_count is valid (detection found PII but no tokens created yet)."""
        record = _capture_audit_log(token_count=0)

        assert record._ps_token_count == 0  # type: ignore[attr-defined]

    def test_duration_ms_rounded_to_3_decimals(self) -> None:
        """Duration is rounded to 3 decimal places in the extra dict."""
        record = _capture_audit_log(duration_ms=12.3456789)

        assert record._ps_duration_ms == 12.346  # type: ignore[attr-defined]

    def test_very_large_duration_ms(self) -> None:
        """Very large duration_ms does not crash."""
        record = _capture_audit_log(duration_ms=1e15)

        assert record._ps_duration_ms == 1e15  # type: ignore[attr-defined]

    def test_zero_duration_ms(self) -> None:
        """Zero duration_ms is valid."""
        record = _capture_audit_log(duration_ms=0.0)

        assert record._ps_duration_ms == 0.0  # type: ignore[attr-defined]

    def test_empty_org_id_still_hashes(self) -> None:
        """Empty string org_id still produces a valid hash (SHA-256 of empty string)."""
        expected_hash = hashlib.sha256(b"").hexdigest()[:12]

        record = _capture_audit_log(org_id="")

        assert record._ps_org_hash == expected_hash  # type: ignore[attr-defined]
        assert len(record._ps_org_hash) == 12  # type: ignore[attr-defined]


# ── Adversarial: org_id Never Leaks ────────────────────────────────

class TestOrgIdNeverLeaksInAuditLog:
    """The raw org_id must NEVER appear in any part of the log record."""

    def test_org_id_not_in_log_message(self) -> None:
        """Raw org_id does not appear in the formatted log message."""
        org_id = "org-secret-12345"
        record = _capture_audit_log(org_id=org_id)

        # The message should contain 'processing_activity' but NOT the raw org_id
        message = record.getMessage()
        assert org_id not in message, (
            f"Raw org_id {org_id!r} found in log message: {message!r}"
        )

    def test_org_id_not_in_extra_fields(self) -> None:
        """Raw org_id does not appear in any _ps_* extra field."""
        org_id = "org-unique-98765"
        record = _capture_audit_log(org_id=org_id)

        for attr_name in dir(record):
            if attr_name.startswith("_ps_"):
                value = getattr(record, attr_name)
                if isinstance(value, str):
                    assert value != org_id, (
                        f"Raw org_id found in extra field {attr_name}={value!r}"
                    )
                elif isinstance(value, dict):
                    # Check dict values too
                    for v in value.values():
                        if isinstance(v, str):
                            assert v != org_id, (
                                f"Raw org_id found in dict field {attr_name}: {v!r}"
                            )

    def test_org_id_with_special_chars_still_hashed(self) -> None:
        """org_id with unicode/special chars is hashed correctly, never appears raw."""
        org_id = "org-\u00e9l\u00e8ve-{inject}"
        expected_hash = hashlib.sha256(org_id.encode()).hexdigest()[:12]

        record = _capture_audit_log(org_id=org_id)

        assert record._ps_org_hash == expected_hash  # type: ignore[attr-defined]
        message = record.getMessage()
        assert org_id not in message


# ── Adversarial: Forbidden Fields ───────────────────────────────────

class TestForbiddenFieldsCannotBeInjected:
    """log_processing_activity must never emit forbidden PII fields."""

    def test_no_original_text_field(self) -> None:
        """The log record has no 'original_text' or '_ps_original_text' attribute."""
        record = _capture_audit_log()

        assert not hasattr(record, "_ps_original_text"), (
            "Forbidden field 'original_text' found in audit log record"
        )
        assert not hasattr(record, "original_text"), (
            "Forbidden field 'original_text' found in audit log record"
        )

    def test_no_pii_value_field(self) -> None:
        """The log record has no 'pii_value' or '_ps_pii_value' attribute."""
        record = _capture_audit_log()

        assert not hasattr(record, "_ps_pii_value"), (
            "Forbidden field 'pii_value' found in audit log record"
        )

    def test_audit_flag_is_set(self) -> None:
        """The _ps_audit field is True, distinguishing this from operational logs."""
        record = _capture_audit_log()

        assert record._ps_audit is True  # type: ignore[attr-defined]


# ── Adversarial: log_operation Allowlist ────────────────────────────

class TestLogOperationAllowlist:
    """log_operation rejects forbidden kwargs to prevent PII injection."""

    def test_forbidden_field_raises_valueerror(self) -> None:
        """log_operation raises ValueError for fields not in SAFE_LOG_FIELDS."""
        from app.infrastructure.telemetry import log_operation, get_logger

        logger = get_logger("test")

        with pytest.raises(ValueError, match="Forbidden log field"):
            log_operation(
                logger,
                operation="test",
                org_id="org-1",
                duration_ms=0.0,
                original_text="LEAKED PII",  # type: ignore[call-arg]
            )

    def test_pii_value_field_rejected(self) -> None:
        """log_operation raises ValueError for 'pii_value' kwarg."""
        from app.infrastructure.telemetry import log_operation, get_logger

        logger = get_logger("test")

        with pytest.raises(ValueError, match="Forbidden log field"):
            log_operation(
                logger,
                operation="test",
                org_id="org-1",
                duration_ms=0.0,
                pii_value="Mario Rossi",  # type: ignore[call-arg]
            )

    def test_safe_fields_accepted(self) -> None:
        """log_operation accepts all SAFE_LOG_FIELDS without error."""
        from app.infrastructure.telemetry import log_operation, get_logger

        logger = get_logger("test")

        # Should not raise
        log_operation(
            logger,
            operation="test",
            org_id="org-1",
            duration_ms=1.5,
            token_count=10,
            source="regex",
        )
