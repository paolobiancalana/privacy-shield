"""Validate the final dataset files for Privacy Shield training.

Performs comprehensive checks on train/val/test JSONL files to ensure
data quality, offset alignment, schema correctness, and type consistency.

Usage:
    python -m dataset.validate
    python -m dataset.validate --data-dir data/final
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from dataset.entity_types import SYSTEM_PROMPT, PS_TYPES, REGEX_TYPES

logger = logging.getLogger(__name__)

REQUIRED_ENTITY_KEYS = {"t", "y", "s", "e"}


@dataclass
class ValidationError:
    file: str
    line: int
    check: str
    message: str

    def __str__(self) -> str:
        return f"  [{self.file}:{self.line}] {self.check}: {self.message}"


@dataclass
class ValidationResult:
    errors: list[ValidationError] = field(default_factory=list)
    total_examples: Counter = field(default_factory=Counter)
    entity_counts: dict[str, Counter] = field(default_factory=lambda: {})
    source_counts: dict[str, Counter] = field(default_factory=lambda: {})

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def _validate_file(file_path: Path, result: ValidationResult) -> None:
    """Validate a single JSONL file."""
    split_name = file_path.stem  # train, val, or test

    if split_name not in result.entity_counts:
        result.entity_counts[split_name] = Counter()
    if split_name not in result.source_counts:
        result.source_counts[split_name] = Counter()

    if not file_path.exists():
        result.errors.append(ValidationError(
            file=split_name, line=0, check="file_exists",
            message=f"File not found: {file_path}",
        ))
        return

    with open(file_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            # Check 1: Valid JSON structure
            try:
                example = json.loads(line)
            except json.JSONDecodeError as e:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="valid_json",
                    message=f"Invalid JSON: {e}",
                ))
                continue

            # Track source if available
            source = example.get("_source", "unknown")
            result.source_counts[split_name][source] += 1

            # Check 2: Has "messages" array
            if "messages" not in example:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="has_messages",
                    message="Missing 'messages' key",
                ))
                continue

            messages = example["messages"]
            if not isinstance(messages, list):
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="messages_is_list",
                    message=f"'messages' is {type(messages).__name__}, expected list",
                ))
                continue

            # Check 3: Exactly 3 messages with correct roles
            if len(messages) != 3:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="message_count",
                    message=f"Expected 3 messages, got {len(messages)}",
                ))
                continue

            expected_roles = ["system", "user", "assistant"]
            actual_roles = [m.get("role") for m in messages]
            if actual_roles != expected_roles:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="message_roles",
                    message=f"Expected roles {expected_roles}, got {actual_roles}",
                ))
                continue

            # Check 4: System prompt matches
            system_content = messages[0].get("content", "")
            if system_content != SYSTEM_PROMPT:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="system_prompt",
                    message="System prompt does not match SYSTEM_PROMPT constant",
                ))

            user_text = messages[1].get("content", "")
            assistant_content = messages[2].get("content", "")

            # Check 5: Assistant content is valid JSON array
            try:
                entities = json.loads(assistant_content)
            except json.JSONDecodeError:
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="assistant_json",
                    message=f"Assistant content is not valid JSON: {assistant_content[:100]}",
                ))
                continue

            if not isinstance(entities, list):
                result.errors.append(ValidationError(
                    file=split_name, line=line_num, check="assistant_is_list",
                    message=f"Assistant content is {type(entities).__name__}, expected list",
                ))
                continue

            result.total_examples[split_name] += 1

            if not entities:
                result.entity_counts[split_name]["EMPTY"] += 1
                continue

            # Validate each entity
            seen_spans: list[tuple[int, int]] = []

            for ent_idx, ent in enumerate(entities):
                # Check 6: Required keys
                if not isinstance(ent, dict):
                    result.errors.append(ValidationError(
                        file=split_name, line=line_num, check="entity_is_dict",
                        message=f"Entity {ent_idx} is {type(ent).__name__}, expected dict",
                    ))
                    continue

                missing_keys = REQUIRED_ENTITY_KEYS - set(ent.keys())
                if missing_keys:
                    result.errors.append(ValidationError(
                        file=split_name, line=line_num, check="entity_keys",
                        message=f"Entity {ent_idx} missing keys: {missing_keys}",
                    ))
                    continue

                ent_text = ent["t"]
                ent_type = ent["y"]
                ent_start = ent["s"]
                ent_end = ent["e"]

                # Check 7: Type is in PS_TYPES
                if ent_type not in PS_TYPES:
                    result.errors.append(ValidationError(
                        file=split_name, line=line_num, check="entity_type_valid",
                        message=f"Entity {ent_idx}: type '{ent_type}' not in PS_TYPES",
                    ))

                # Check 8: No regex types leaked
                if ent_type in REGEX_TYPES:
                    result.errors.append(ValidationError(
                        file=split_name, line=line_num, check="no_regex_types",
                        message=f"Entity {ent_idx}: regex type '{ent_type}' leaked into training data",
                    ))

                # Check 9: Offset alignment
                if isinstance(ent_start, int) and isinstance(ent_end, int):
                    if ent_start < 0 or ent_end > len(user_text) or ent_start >= ent_end:
                        result.errors.append(ValidationError(
                            file=split_name, line=line_num, check="offset_bounds",
                            message=(
                                f"Entity {ent_idx}: invalid offsets "
                                f"[{ent_start}:{ent_end}] for text of length {len(user_text)}"
                            ),
                        ))
                    elif user_text[ent_start:ent_end] != ent_text:
                        result.errors.append(ValidationError(
                            file=split_name, line=line_num, check="offset_alignment",
                            message=(
                                f"Entity {ent_idx}: text[{ent_start}:{ent_end}]="
                                f"'{user_text[ent_start:ent_end]}' != '{ent_text}'"
                            ),
                        ))

                    # Check 10: No overlapping spans
                    for prev_start, prev_end in seen_spans:
                        if ent_start < prev_end and ent_end > prev_start:
                            result.errors.append(ValidationError(
                                file=split_name, line=line_num, check="no_overlap",
                                message=(
                                    f"Entity {ent_idx}: span [{ent_start}:{ent_end}] "
                                    f"overlaps with [{prev_start}:{prev_end}]"
                                ),
                            ))
                            break

                    seen_spans.append((ent_start, ent_end))

                result.entity_counts[split_name][ent_type] += 1


def validate_dataset(data_dir: Path) -> ValidationResult:
    """Validate all split files in the data directory."""
    result = ValidationResult()

    for split_name in ["train", "val", "test"]:
        file_path = data_dir / f"{split_name}.jsonl"
        logger.info("Validating %s ...", file_path)
        _validate_file(file_path, result)

    return result


def print_results(result: ValidationResult) -> None:
    """Print validation results."""
    print(f"\n{'=' * 60}")
    print(f"Dataset Validation Results")
    print(f"{'=' * 60}")

    # Example counts per split
    print(f"\n  Examples per split:")
    total = 0
    for split_name in ["train", "val", "test"]:
        count = result.total_examples.get(split_name, 0)
        total += count
        print(f"    {split_name:6s}: {count:,}")
    print(f"    {'total':6s}: {total:,}")

    # Entity counts per type per split
    all_types = sorted(
        set().union(*(c.keys() for c in result.entity_counts.values()))
    )
    if all_types:
        print(f"\n  Entity count per type per split:")
        print(f"  {'Type':<10s} {'Train':>8s} {'Val':>8s} {'Test':>8s} {'Total':>8s}")
        print(f"  {'-' * 46}")
        for t in all_types:
            train_c = result.entity_counts.get("train", {}).get(t, 0)
            val_c = result.entity_counts.get("val", {}).get(t, 0)
            test_c = result.entity_counts.get("test", {}).get(t, 0)
            total_c = train_c + val_c + test_c
            print(f"  {t:<10s} {train_c:>8,} {val_c:>8,} {test_c:>8,} {total_c:>8,}")

    # Source distribution
    has_sources = any(c for c in result.source_counts.values())
    if has_sources:
        all_sources = sorted(
            set().union(*(c.keys() for c in result.source_counts.values()))
        )
        if all_sources:
            print(f"\n  Source distribution:")
            print(f"  {'Source':<25s} {'Train':>8s} {'Val':>8s} {'Test':>8s}")
            print(f"  {'-' * 53}")
            for src in all_sources:
                train_c = result.source_counts.get("train", {}).get(src, 0)
                val_c = result.source_counts.get("val", {}).get(src, 0)
                test_c = result.source_counts.get("test", {}).get(src, 0)
                print(f"  {src:<25s} {train_c:>8,} {val_c:>8,} {test_c:>8,}")

    # Validation errors
    if result.errors:
        print(f"\n  VALIDATION ERRORS: {len(result.errors)}")
        # Show first 50 errors
        for err in result.errors[:50]:
            print(f"  {err}")
        if len(result.errors) > 50:
            print(f"  ... and {len(result.errors) - 50} more errors")
    else:
        print(f"\n  ALL CHECKS PASSED")

    print(f"\n{'=' * 60}\n")


# ---------------------------------------------------------------------------
# NER (Arrow) dataset validation
# ---------------------------------------------------------------------------

@dataclass
class NERValidationResult:
    errors: list[ValidationError] = field(default_factory=list)
    total_examples: Counter = field(default_factory=Counter)
    label_counts: dict[str, Counter] = field(default_factory=lambda: {})

    @property
    def is_valid(self) -> bool:
        return len(self.errors) == 0


def validate_ner_dataset(data_dir: Path) -> NERValidationResult:
    """Validate NER Arrow datasets for token classification training.

    Checks:
    - Required columns: input_ids, attention_mask, labels
    - Label values in [0, 20] or -100
    - BIO consistency (I- without preceding B-/I- of same type)
    """
    from datasets import load_from_disk
    from dataset.entity_types import NER_LABELS, NUM_LABELS

    result = NERValidationResult()

    for split_name in ["train", "val", "test"]:
        split_dir = data_dir / split_name
        if not split_dir.exists():
            result.errors.append(ValidationError(
                file=split_name, line=0, check="dir_exists",
                message=f"Split directory not found: {split_dir}",
            ))
            continue

        logger.info("Validating NER split: %s", split_dir)

        try:
            dataset = load_from_disk(str(split_dir))
        except Exception as e:
            result.errors.append(ValidationError(
                file=split_name, line=0, check="load_dataset",
                message=f"Failed to load Arrow dataset: {e}",
            ))
            continue

        # Check required columns
        required_cols = {"input_ids", "attention_mask", "labels"}
        missing_cols = required_cols - set(dataset.column_names)
        if missing_cols:
            result.errors.append(ValidationError(
                file=split_name, line=0, check="required_columns",
                message=f"Missing columns: {missing_cols}",
            ))
            continue

        result.total_examples[split_name] = len(dataset)

        if split_name not in result.label_counts:
            result.label_counts[split_name] = Counter()

        valid_label_ids = set(range(NUM_LABELS)) | {-100}

        for idx in range(len(dataset)):
            labels = dataset[idx]["labels"]

            # Check label values
            for pos, label_id in enumerate(labels):
                if label_id not in valid_label_ids:
                    result.errors.append(ValidationError(
                        file=split_name, line=idx + 1, check="label_range",
                        message=f"Invalid label {label_id} at position {pos} "
                                f"(expected 0-{NUM_LABELS - 1} or -100)",
                    ))
                    break

                if label_id >= 0:
                    label_name = NER_LABELS[label_id]
                    result.label_counts[split_name][label_name] += 1

            # Check BIO consistency
            prev_label = "O"
            for pos, label_id in enumerate(labels):
                if label_id == -100:
                    continue

                label_name = NER_LABELS[label_id] if 0 <= label_id < NUM_LABELS else "O"

                if label_name.startswith("I-"):
                    entity_type = label_name[2:]
                    expected_prev = {f"B-{entity_type}", f"I-{entity_type}"}
                    if prev_label not in expected_prev:
                        result.errors.append(ValidationError(
                            file=split_name, line=idx + 1, check="bio_consistency",
                            message=f"I-{entity_type} at pos {pos} without "
                                    f"preceding B-/I-{entity_type} (prev: {prev_label})",
                        ))
                        break

                prev_label = label_name

    return result


def print_ner_results(result: NERValidationResult) -> None:
    """Print NER validation results."""
    print(f"\n{'=' * 60}")
    print("NER Dataset Validation Results")
    print(f"{'=' * 60}")

    print(f"\n  Examples per split:")
    for split_name in ["train", "val", "test"]:
        count = result.total_examples.get(split_name, 0)
        print(f"    {split_name:6s}: {count:,}")

    # Label distribution
    for split_name in ["train", "val", "test"]:
        counts = result.label_counts.get(split_name, {})
        if counts:
            print(f"\n  Label distribution ({split_name}):")
            for label, count in sorted(counts.items()):
                print(f"    {label:8s}: {count:,}")

    if result.errors:
        print(f"\n  VALIDATION ERRORS: {len(result.errors)}")
        for err in result.errors[:50]:
            print(f"  {err}")
        if len(result.errors) > 50:
            print(f"  ... and {len(result.errors) - 50} more errors")
    else:
        print(f"\n  ALL CHECKS PASSED")

    print(f"\n{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate final dataset files for Privacy Shield training."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path("data/final"),
        help="Directory with train/val/test JSONL files (default: data/final)",
    )
    parser.add_argument(
        "--format",
        type=str,
        choices=["chat", "ner"],
        default="chat",
        help="Dataset format to validate: 'chat' (JSONL) or 'ner' (Arrow) (default: chat)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.format == "ner":
        result = validate_ner_dataset(args.data_dir)
        print_ner_results(result)
        if not result.is_valid:
            raise SystemExit(1)
    else:
        result = validate_dataset(args.data_dir)
        print_results(result)
        if not result.is_valid:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
