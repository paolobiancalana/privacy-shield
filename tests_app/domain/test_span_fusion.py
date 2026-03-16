"""
Span fusion domain service tests.

Adversarial Analysis:
  1. Overlapping regex + slm spans: if priority logic is wrong, the SLM span
     could win and produce a less precise token type.
  2. Adjacent merge with gap=1 must NOT merge different pii_types or gap=2.
  3. All-overlapping input could cause O(n^2) scanning if resolve is naive.
"""
from __future__ import annotations

import pytest

from app.domain.entities import PiiSpan
from app.domain.services.span_fusion import fuse_spans


def _span(
    start: int,
    end: int,
    pii_type: str = "pe",
    source: str = "regex",
    confidence: float = 1.0,
) -> PiiSpan:
    """Factory helper for concise test spans."""
    return PiiSpan(
        start=start,
        end=end,
        text="x" * (end - start),
        pii_type=pii_type,
        source=source,
        confidence=confidence,
    )


class TestFuseSpansEmptyAndSingle:
    """Edge cases: empty input and single spans."""

    def test_empty_input_returns_empty(self) -> None:
        assert fuse_spans([]) == []

    def test_single_span_returned_as_is(self) -> None:
        span = _span(0, 5)
        result = fuse_spans([span])
        assert len(result) == 1
        assert result[0].start == 0
        assert result[0].end == 5


class TestFuseSpansNonOverlapping:
    """Non-overlapping spans: should all be preserved, sorted by start."""

    def test_two_non_overlapping_preserved(self) -> None:
        spans = [_span(10, 15), _span(0, 5)]
        result = fuse_spans(spans)
        assert len(result) == 2
        assert result[0].start == 0
        assert result[1].start == 10

    def test_three_non_overlapping_sorted(self) -> None:
        spans = [_span(20, 25), _span(0, 5), _span(10, 15)]
        result = fuse_spans(spans)
        assert [s.start for s in result] == [0, 10, 20]


class TestFuseSpansOverlapPriority:
    """Overlap resolution: regex > slm, then longer wins."""

    def test_overlapping_regex_beats_slm(self) -> None:
        regex_span = _span(0, 10, source="regex")
        slm_span = _span(3, 12, source="slm")
        result = fuse_spans([regex_span, slm_span])
        assert len(result) == 1
        assert result[0].source == "regex"

    def test_overlapping_slm_loses_even_if_longer(self) -> None:
        regex_span = _span(0, 5, source="regex")
        slm_span = _span(2, 20, source="slm")
        result = fuse_spans([regex_span, slm_span])
        assert len(result) == 1
        assert result[0].source == "regex"

    def test_same_source_longer_span_wins(self) -> None:
        short = _span(0, 5, source="regex")
        long_ = _span(0, 10, source="regex")
        result = fuse_spans([short, long_])
        assert len(result) == 1
        assert result[0].end == 10

    def test_same_source_same_length_earlier_start_wins(self) -> None:
        a = _span(0, 5, source="regex")
        b = _span(3, 8, source="regex")
        result = fuse_spans([a, b])
        assert len(result) == 1
        # Both same length (5), same source -- the one with earlier start (sorted first) wins
        assert result[0].start == 0
        assert result[0].end == 5


class TestFuseSpansAdjacentMerge:
    """Adjacent same-type merge: gap <= 1 char."""

    def test_adjacent_same_type_gap_zero_merged(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="Rossi", pii_type="pe", source="regex", confidence=0.9)
        result = fuse_spans([a, b])
        assert len(result) == 1
        assert result[0].start == 0
        assert result[0].end == 10
        assert result[0].text == "MarioRossi"

    def test_adjacent_same_type_gap_one_merged(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=6, end=11, text="Rossi", pii_type="pe", source="regex", confidence=0.8)
        result = fuse_spans([a, b])
        assert len(result) == 1
        assert result[0].start == 0
        assert result[0].end == 11
        assert result[0].text == "Mario Rossi"

    def test_adjacent_different_type_not_merged(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="12345", pii_type="tel", source="regex", confidence=0.85)
        result = fuse_spans([a, b])
        assert len(result) == 2

    def test_adjacent_gap_two_not_merged(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=7, end=12, text="Rossi", pii_type="pe", source="regex", confidence=1.0)
        result = fuse_spans([a, b])
        assert len(result) == 2

    def test_merged_span_inherits_highest_source_priority(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="Rossi", pii_type="pe", source="slm", confidence=0.8)
        result = fuse_spans([a, b])
        assert len(result) == 1
        assert result[0].source == "regex"

    def test_merged_span_has_average_confidence(self) -> None:
        a = PiiSpan(start=0, end=5, text="Mario", pii_type="pe", source="regex", confidence=1.0)
        b = PiiSpan(start=5, end=10, text="Rossi", pii_type="pe", source="regex", confidence=0.6)
        result = fuse_spans([a, b])
        assert len(result) == 1
        assert result[0].confidence == pytest.approx(0.8)


class TestFuseSpansAllOverlapping:
    """All spans overlap: only the highest-priority winner survives."""

    def test_all_overlapping_only_winner_survives(self) -> None:
        spans = [
            _span(0, 10, source="slm"),
            _span(1, 9, source="slm"),
            _span(2, 12, source="regex"),
            _span(3, 8, source="slm"),
        ]
        result = fuse_spans(spans)
        assert len(result) == 1
        assert result[0].source == "regex"


class TestFuseSpansComplex:
    """Complex multi-span scenarios."""

    def test_five_spans_mixed_overlaps(self) -> None:
        """
        Spans:
          [0-10] regex pe
          [5-15] slm pe   -> overlaps [0-10], regex wins
          [20-25] regex cf -> non-overlapping
          [25-30] regex cf -> adjacent same type, gap=0 -> merged with [20-25]
          [40-50] slm pe   -> non-overlapping
        Expected: [0-10], [20-30], [40-50]
        """
        spans = [
            PiiSpan(start=0, end=10, text="0123456789", pii_type="pe", source="regex", confidence=1.0),
            PiiSpan(start=5, end=15, text="5678901234", pii_type="pe", source="slm", confidence=0.9),
            PiiSpan(start=20, end=25, text="abcde", pii_type="cf", source="regex", confidence=1.0),
            PiiSpan(start=25, end=30, text="fghij", pii_type="cf", source="regex", confidence=1.0),
            PiiSpan(start=40, end=50, text="klmnopqrst", pii_type="pe", source="slm", confidence=0.7),
        ]
        result = fuse_spans(spans)
        assert len(result) == 3
        assert result[0].start == 0
        assert result[0].end == 10
        assert result[0].source == "regex"
        # merged cf spans
        assert result[1].start == 20
        assert result[1].end == 30
        assert result[1].text == "abcdefghij"
        # standalone slm
        assert result[2].start == 40
        assert result[2].end == 50

    def test_non_overlapping_output_guarantee(self) -> None:
        """After fusion, no two spans should overlap."""
        spans = [
            _span(0, 10, source="regex"),
            _span(5, 15, source="slm"),
            _span(8, 20, source="regex"),
            _span(18, 25, source="slm"),
        ]
        result = fuse_spans(spans)
        for i in range(len(result) - 1):
            assert result[i].end <= result[i + 1].start, (
                f"Span {i} (end={result[i].end}) overlaps span {i+1} (start={result[i+1].start})"
            )
