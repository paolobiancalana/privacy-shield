# privacy-shield/app/domain/services/span_fusion.py
"""
Pure domain service: overlapping PiiSpan fusion.

Rules (in priority order):
  1. Regex beats SLM when they overlap (structured patterns have higher precision).
  2. Among equal-source overlapping spans, the longer span wins.
  3. Adjacent spans of the same pii_type with gap <= 1 char are merged into one.
  4. Output is sorted by start position and guaranteed non-overlapping.

No infrastructure imports. Fully deterministic and unit-testable.
"""
from __future__ import annotations

from app.domain.entities import PiiSpan


def _source_priority(source: str) -> int:
    """Higher number = higher priority. regex wins over slm."""
    return 1 if source == "regex" else 0


def _merge_adjacent(spans: list[PiiSpan]) -> list[PiiSpan]:
    """
    Merge adjacent same-type spans (gap <= 1 char).

    Assumes 'spans' is already sorted by start and non-overlapping.
    When merging, the merged span inherits the higher source priority and
    the average confidence.
    """
    if not spans:
        return []

    merged: list[PiiSpan] = [spans[0]]
    for current in spans[1:]:
        last = merged[-1]
        gap = current.start - last.end
        if last.pii_type == current.pii_type and 0 <= gap <= 1:
            # Merge: extend last span to cover current
            merged_text = last.text + (" " if gap == 1 else "") + current.text
            best_source = last.source if _source_priority(last.source) >= _source_priority(current.source) else current.source
            avg_confidence = (last.confidence + current.confidence) / 2.0
            merged[-1] = PiiSpan(
                start=last.start,
                end=current.end,
                text=merged_text,
                pii_type=last.pii_type,
                source=best_source,
                confidence=avg_confidence,
            )
        else:
            merged.append(current)
    return merged


def _resolve_overlapping(spans: list[PiiSpan]) -> list[PiiSpan]:
    """
    Given a sorted list of spans, resolve overlaps using priority rules.

    Process spans left-to-right; when an overlap is detected:
      - Pick the span with higher source priority (regex > slm).
      - Tie-break: longer span wins.
      - Tie-break: lower start wins (earlier detection).
    The winning span is kept; the losing span is dropped entirely.
    """
    if not spans:
        return []

    resolved: list[PiiSpan] = [spans[0]]
    for candidate in spans[1:]:
        last = resolved[-1]
        if not last.overlaps(candidate):
            resolved.append(candidate)
            continue

        # They overlap — pick winner
        last_priority = _source_priority(last.source)
        cand_priority = _source_priority(candidate.source)

        if last_priority > cand_priority:
            winner = last
        elif cand_priority > last_priority:
            winner = candidate
        elif candidate.length > last.length:
            winner = candidate
        else:
            winner = last  # keep last (earlier start, same priority/length)

        resolved[-1] = winner

    return resolved


def fuse_spans(spans: list[PiiSpan]) -> list[PiiSpan]:
    """
    Merge and deduplicate a list of PiiSpan objects.

    Steps:
      1. Sort by start position; ties broken by descending length so that
         longer spans are evaluated first during overlap resolution.
      2. Resolve overlaps using source-priority + length rules.
      3. Merge adjacent same-type spans (gap <= 1 char).

    Args:
        spans: Raw, potentially overlapping list from one or more detectors.

    Returns:
        Sorted, non-overlapping, deduplicated list of PiiSpan objects.
    """
    if not spans:
        return []

    # Step 1: sort by start asc, then length desc (so longest candidate is
    # encountered first when multiple spans share the same start)
    sorted_spans = sorted(spans, key=lambda s: (s.start, -s.length))

    # Step 2: resolve overlaps
    resolved = _resolve_overlapping(sorted_spans)

    # Step 3: merge adjacent same-type spans
    return _merge_adjacent(resolved)
