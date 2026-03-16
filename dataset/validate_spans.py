"""Deterministic span validator for synthetic training data.

Validates that every example has correct offsets, no overlaps,
valid labels, and clean structure. Rejects invalid examples and
writes only clean ones to output.

Usage:
    python -m dataset.validate_spans --input data/synthetic/boundary_hard.jsonl
    python -m dataset.validate_spans --input data/synthetic/boundary_hard.jsonl --output data/synthetic/boundary_hard_clean.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from dataset.entity_types import PS_TYPES

logger = logging.getLogger(__name__)

VALID_LABELS = set(PS_TYPES.keys())


@dataclass
class ValidationReport:
    total: int = 0
    valid: int = 0
    rejected: int = 0
    reject_reasons: Counter = field(default_factory=Counter)
    label_counts: Counter = field(default_factory=Counter)


def _validate_example(
    example: dict,
    line_num: int,
    report: ValidationReport,
) -> bool:
    """Validate a single example. Returns True if valid."""
    report.total += 1

    text = example.get("text")
    if not text or not isinstance(text, str):
        report.reject_reasons["missing_text"] += 1
        logger.debug("Line %d: missing or empty text", line_num)
        return False

    entities = example.get("entities")
    if entities is None:
        report.reject_reasons["missing_entities_key"] += 1
        logger.debug("Line %d: missing entities key", line_num)
        return False

    if not isinstance(entities, list):
        report.reject_reasons["entities_not_list"] += 1
        logger.debug("Line %d: entities is not a list", line_num)
        return False

    # Empty entities (hard negatives) are valid
    if not entities:
        report.valid += 1
        return True

    prev_end = -1

    for i, ent in enumerate(entities):
        # Required keys
        ent_text = ent.get("text") or ent.get("t")
        ent_type = ent.get("type") or ent.get("y")
        ent_start = ent.get("start") if "start" in ent else ent.get("s")
        ent_end = ent.get("end") if "end" in ent else ent.get("e")

        if ent_text is None or ent_type is None or ent_start is None or ent_end is None:
            report.reject_reasons["entity_missing_keys"] += 1
            logger.debug("Line %d, entity %d: missing keys", line_num, i)
            return False

        # Type check
        if not isinstance(ent_start, int) or not isinstance(ent_end, int):
            report.reject_reasons["entity_offset_not_int"] += 1
            logger.debug("Line %d, entity %d: offsets not int", line_num, i)
            return False

        # Label check
        if ent_type not in VALID_LABELS:
            report.reject_reasons[f"invalid_label_{ent_type}"] += 1
            logger.debug("Line %d, entity %d: invalid label %r", line_num, i, ent_type)
            return False

        # Bounds check
        if ent_start < 0 or ent_end > len(text) or ent_start >= ent_end:
            report.reject_reasons["offset_out_of_bounds"] += 1
            logger.debug(
                "Line %d, entity %d: offset [%d:%d] out of bounds (text len %d)",
                line_num, i, ent_start, ent_end, len(text),
            )
            return False

        # Offset alignment: text[start:end] == value
        actual = text[ent_start:ent_end]
        if actual != ent_text:
            report.reject_reasons["offset_mismatch"] += 1
            logger.debug(
                "Line %d, entity %d: text[%d:%d]=%r != %r",
                line_num, i, ent_start, ent_end, actual, ent_text,
            )
            return False

        # Overlap check (entities must be sorted by start and non-overlapping)
        if ent_start < prev_end:
            report.reject_reasons["overlapping_entities"] += 1
            logger.debug(
                "Line %d, entity %d: start %d < prev_end %d (overlap)",
                line_num, i, ent_start, prev_end,
            )
            return False

        prev_end = ent_end
        report.label_counts[ent_type] += 1

    report.valid += 1
    return True


def validate_and_filter(
    input_path: Path,
    output_path: Path | None = None,
) -> ValidationReport:
    """Validate all examples in a JSONL file.

    Args:
        input_path: Source JSONL file.
        output_path: If provided, write only valid examples here.

    Returns:
        ValidationReport with counts and rejection reasons.
    """
    report = ValidationReport()
    valid_examples: list[dict] = []

    with open(input_path, "r", encoding="utf-8") as fh:
        for line_num, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue

            try:
                example = json.loads(line)
            except json.JSONDecodeError:
                report.total += 1
                report.reject_reasons["invalid_json"] += 1
                logger.debug("Line %d: invalid JSON", line_num)
                continue

            if _validate_example(example, line_num, report):
                valid_examples.append(example)

    report.rejected = report.total - report.valid

    # Write clean output
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as fh:
            for ex in valid_examples:
                fh.write(json.dumps(ex, ensure_ascii=False) + "\n")

    # Print report
    print(f"\n{'=' * 60}")
    print("Span Validation Report")
    print(f"{'=' * 60}")
    print(f"  Input:    {input_path}")
    print(f"  Total:    {report.total:,}")
    print(f"  Valid:    {report.valid:,}")
    print(f"  Rejected: {report.rejected:,}")

    if report.reject_reasons:
        print(f"\n  Rejection reasons:")
        for reason, cnt in report.reject_reasons.most_common():
            print(f"    {reason:<30s}: {cnt:,}")

    if report.label_counts:
        print(f"\n  Label distribution (valid examples):")
        for label, cnt in report.label_counts.most_common():
            print(f"    {label:>5s}: {cnt:,}")

    if output_path:
        print(f"\n  Clean output: {output_path}")
    print(f"{'=' * 60}\n")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate synthetic span data.")
    parser.add_argument("--input", type=Path, required=True, help="Input JSONL file")
    parser.add_argument("--output", type=Path, default=None, help="Output JSONL (clean only)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    report = validate_and_filter(args.input, args.output)
    if report.rejected > 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
