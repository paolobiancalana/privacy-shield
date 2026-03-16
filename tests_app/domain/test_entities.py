"""
Domain entity tests — validation, immutability, edge cases.

Adversarial Analysis:
  1. Negative/zero start or end values could corrupt offset math downstream.
  2. Confidence outside [0,1] would produce nonsensical fusion priority scores.
  3. Frozen dataclasses can still be mutated via object.__setattr__ if not tested.
"""
from __future__ import annotations

import pytest

from app.domain.entities import (
    DetectionResult,
    FlushResult,
    OrgKeyPair,
    PiiSpan,
    RehydrateResult,
    TokenEntry,
    TokenizeResult,
)


# ======================================================================
# PiiSpan
# ======================================================================


class TestPiiSpan:
    """PiiSpan construction, validation, and method tests."""

    # --- Valid construction ---

    def test_valid_construction(self) -> None:
        span = PiiSpan(
            start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0
        )
        assert span.start == 0
        assert span.end == 5
        assert span.text == "Mario"
        assert span.pii_type == "pe"
        assert span.source == "regex"
        assert span.confidence == 1.0

    def test_valid_construction_slm_source(self) -> None:
        span = PiiSpan(
            start=10, end=15, text="Paolo", pii_type="pe", source="slm", confidence=0.8
        )
        assert span.source == "slm"
        assert span.confidence == 0.8

    # --- start validation ---

    def test_negative_start_raises(self) -> None:
        with pytest.raises(ValueError, match="start must be >= 0"):
            PiiSpan(start=-1, end=5, text="x", pii_type="pe", source="regex", confidence=1.0)

    # --- end validation ---

    def test_end_equal_to_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end.*must be > start"):
            PiiSpan(start=5, end=5, text="", pii_type="pe", source="regex", confidence=1.0)

    def test_end_less_than_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end.*must be > start"):
            PiiSpan(start=10, end=3, text="x", pii_type="pe", source="regex", confidence=1.0)

    # --- confidence validation ---

    def test_confidence_below_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            PiiSpan(start=0, end=1, text="x", pii_type="pe", source="regex", confidence=-0.01)

    def test_confidence_above_one_raises(self) -> None:
        with pytest.raises(ValueError, match="confidence must be in"):
            PiiSpan(start=0, end=1, text="x", pii_type="pe", source="regex", confidence=1.01)

    def test_confidence_exactly_zero(self) -> None:
        span = PiiSpan(start=0, end=1, text="x", pii_type="pe", source="regex", confidence=0.0)
        assert span.confidence == 0.0

    def test_confidence_exactly_one(self) -> None:
        span = PiiSpan(start=0, end=1, text="x", pii_type="pe", source="regex", confidence=1.0)
        assert span.confidence == 1.0

    # --- source validation ---

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source must be"):
            PiiSpan(start=0, end=1, text="x", pii_type="pe", source="invalid", confidence=1.0)

    def test_empty_string_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source must be"):
            PiiSpan(start=0, end=1, text="x", pii_type="pe", source="", confidence=1.0)

    # --- length property ---

    def test_length_property(self) -> None:
        span = PiiSpan(start=3, end=10, text="abcdefg", pii_type="pe", source="regex", confidence=1.0)
        assert span.length == 7

    def test_length_minimal_span(self) -> None:
        span = PiiSpan(start=0, end=1, text="x", pii_type="pe", source="regex", confidence=1.0)
        assert span.length == 1

    # --- overlaps() ---

    def test_overlaps_true_partial(self) -> None:
        a = PiiSpan(start=0, end=5, text="xxxxx", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=3, end=8, text="yyyyy", pii_type="pe", source="regex", confidence=1.0)
        assert a.overlaps(b) is True
        assert b.overlaps(a) is True

    def test_overlaps_false_adjacent(self) -> None:
        a = PiiSpan(start=0, end=5, text="xxxxx", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="yyyyy", pii_type="pe", source="regex", confidence=1.0)
        assert a.overlaps(b) is False

    def test_overlaps_true_containment(self) -> None:
        a = PiiSpan(start=0, end=10, text="x" * 10, pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=2, end=5, text="yyy", pii_type="pe", source="regex", confidence=1.0)
        assert a.overlaps(b) is True
        assert b.overlaps(a) is True

    # --- is_adjacent_same_type() ---

    def test_adjacent_same_type_gap_zero(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="Rossi", pii_type="pe", source="regex", confidence=1.0)
        assert a.is_adjacent_same_type(b) is True

    def test_adjacent_same_type_gap_one(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=6, end=11, text="Rossi", pii_type="pe", source="regex", confidence=1.0)
        assert a.is_adjacent_same_type(b) is True

    def test_not_adjacent_gap_two(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=7, end=12, text="Rossi", pii_type="pe", source="regex", confidence=1.0)
        assert a.is_adjacent_same_type(b) is False

    def test_adjacent_different_type_not_merged(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="12345", pii_type="tel", source="regex", confidence=1.0)
        assert a.is_adjacent_same_type(b) is False

    # --- Immutability ---

    def test_frozen_cannot_set_attribute(self) -> None:
        span = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        with pytest.raises(AttributeError):
            span.start = 99  # type: ignore[misc]


# ======================================================================
# TokenEntry
# ======================================================================


class TestTokenEntry:
    """TokenEntry construction and validation."""

    def test_valid_construction(self) -> None:
        entry = TokenEntry(
            token="[#pe:a3f2]",
            original="Mario",
            pii_type="pe",
            token_hash="a3f2",
            encrypted_value=b"enc",
            start=0,
            end=5,
            source="regex",
        )
        assert entry.token == "[#pe:a3f2]"
        assert entry.start == 0
        assert entry.end == 5

    def test_negative_start_raises(self) -> None:
        with pytest.raises(ValueError, match="start must be >= 0"):
            TokenEntry(
                token="t", original="x", pii_type="pe", token_hash="1234",
                encrypted_value=b"e", start=-1, end=5, source="regex",
            )

    def test_end_less_than_start_raises(self) -> None:
        with pytest.raises(ValueError, match="end.*must be >= start"):
            TokenEntry(
                token="t", original="x", pii_type="pe", token_hash="1234",
                encrypted_value=b"e", start=5, end=3, source="regex",
            )

    def test_end_equal_to_start_valid(self) -> None:
        """TokenEntry allows end == start (zero-width), unlike PiiSpan."""
        entry = TokenEntry(
            token="t", original="", pii_type="pe", token_hash="1234",
            encrypted_value=b"e", start=5, end=5, source="regex",
        )
        assert entry.start == entry.end

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source must be"):
            TokenEntry(
                token="t", original="x", pii_type="pe", token_hash="1234",
                encrypted_value=b"e", start=0, end=5, source="composite",
            )

    def test_frozen_cannot_mutate(self) -> None:
        entry = TokenEntry(
            token="t", original="x", pii_type="pe", token_hash="1234",
            encrypted_value=b"e", start=0, end=5, source="regex",
        )
        with pytest.raises(AttributeError):
            entry.original = "hacked"  # type: ignore[misc]


# ======================================================================
# DetectionResult
# ======================================================================


class TestDetectionResult:
    """DetectionResult construction and validation."""

    def test_valid_with_spans(self) -> None:
        span = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        result = DetectionResult(spans=[span], detection_ms=1.0, source="regex")
        assert len(result.spans) == 1

    def test_valid_empty_spans(self) -> None:
        result = DetectionResult(spans=[], detection_ms=0.5, source="regex")
        assert result.spans == []

    def test_invalid_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source must be"):
            DetectionResult(spans=[], detection_ms=0.0, source="invalid")

    def test_composite_source_valid(self) -> None:
        result = DetectionResult(spans=[], detection_ms=0.0, source="composite")
        assert result.source == "composite"


# ======================================================================
# OrgKeyPair, TokenizeResult, RehydrateResult, FlushResult
# ======================================================================


class TestOrgKeyPair:
    def test_valid_construction(self) -> None:
        pair = OrgKeyPair(organization_id="org-1", encrypted_dek=b"\x00" * 60)
        assert pair.organization_id == "org-1"


class TestTokenizeResult:
    def test_valid_construction(self) -> None:
        result = TokenizeResult(
            tokenized_text="hello [#pe:a3f2]",
            tokens=[],
            detection_ms=1.0,
            tokenization_ms=2.0,
            span_count=0,
        )
        assert result.span_count == 0
        assert result.tokenized_text == "hello [#pe:a3f2]"


class TestRehydrateResult:
    def test_valid_construction(self) -> None:
        result = RehydrateResult(text="hello Mario", rehydrated_count=1, duration_ms=0.5)
        assert result.rehydrated_count == 1


class TestFlushResult:
    def test_valid_construction(self) -> None:
        result = FlushResult(flushed_count=3)
        assert result.flushed_count == 3

    def test_zero_flush(self) -> None:
        result = FlushResult(flushed_count=0)
        assert result.flushed_count == 0
