"""Split chat-formatted data into train/val/test sets.

Performs stratified splitting based on entity types present in each example,
ensuring proportional distribution of hard negatives across splits.

Usage:
    python -m dataset.split
    python -m dataset.split --input data/processed/chat_formatted.jsonl --output-dir data/final
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from sklearn.model_selection import train_test_split

from dataset.entity_types import PS_TYPES

logger = logging.getLogger(__name__)


def _extract_stratification_key(example: dict) -> str:
    """Extract a stratification key from a chat-formatted example.

    Key is based on the set of entity types present in the assistant's response.
    Empty entities get the key "EMPTY".
    """
    try:
        assistant_content = example["messages"][2]["content"]
        entities = json.loads(assistant_content)
    except (KeyError, IndexError, json.JSONDecodeError):
        return "EMPTY"

    if not entities:
        return "EMPTY"

    types = sorted(set(e.get("y", "?") for e in entities))
    return "+".join(types)


def _load_jsonl(path: Path) -> list[dict]:
    """Load JSONL file."""
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))
    return examples


def _save_jsonl(examples: list[dict], path: Path) -> None:
    """Save examples to JSONL, preserving _source metadata for evaluation."""
    with open(path, "w", encoding="utf-8") as f:
        for ex in examples:
            output = {"messages": ex["messages"]}
            if "_source" in ex:
                output["_source"] = ex["_source"]
            f.write(json.dumps(output, ensure_ascii=False) + "\n")


def _compute_type_distribution(examples: list[dict]) -> Counter:
    """Count entity types across all examples."""
    counter: Counter = Counter()
    for ex in examples:
        try:
            assistant_content = ex["messages"][2]["content"]
            entities = json.loads(assistant_content)
        except (KeyError, IndexError, json.JSONDecodeError):
            continue

        if not entities:
            counter["EMPTY"] += 1
        else:
            for ent in entities:
                counter[ent.get("y", "?")] += 1

    return counter


def split_dataset(
    input_path: Path,
    output_dir: Path,
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    seed: int = 42,
) -> None:
    """Split the chat-formatted dataset into train/val/test."""
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading data from %s", input_path)
    examples = _load_jsonl(input_path)
    logger.info("Loaded %d examples", len(examples))

    if len(examples) == 0:
        logger.error("No examples found in %s", input_path)
        return

    # Extract stratification keys
    strat_keys = [_extract_stratification_key(ex) for ex in examples]

    # Collapse rare keys to avoid stratification errors
    # Any key with fewer than 2 examples gets merged into "RARE"
    key_counts = Counter(strat_keys)
    strat_keys_safe = [
        k if key_counts[k] >= 2 else "RARE" for k in strat_keys
    ]

    # Check if RARE also has < 2, fallback to no stratification
    rare_count = sum(1 for k in strat_keys_safe if k == "RARE")
    use_stratify = True

    # If any class has fewer than 2 samples after collapsing, disable stratification
    final_counts = Counter(strat_keys_safe)
    if any(c < 2 for c in final_counts.values()):
        logger.warning(
            "Some stratification classes have < 2 samples after collapsing. "
            "Falling back to random split."
        )
        use_stratify = False

    test_ratio = 1.0 - train_ratio - val_ratio
    assert test_ratio > 0, f"Invalid ratios: train={train_ratio}, val={val_ratio}, test={test_ratio}"

    # First split: train vs (val+test)
    val_test_ratio = val_ratio + test_ratio
    try:
        train_data, val_test_data, train_keys, val_test_keys = train_test_split(
            examples,
            strat_keys_safe,
            test_size=val_test_ratio,
            random_state=seed,
            stratify=strat_keys_safe if use_stratify else None,
        )
    except ValueError as e:
        logger.warning("Stratified split failed (%s), falling back to random split", e)
        train_data, val_test_data, train_keys, val_test_keys = train_test_split(
            examples,
            strat_keys_safe,
            test_size=val_test_ratio,
            random_state=seed,
        )

    # Second split: val vs test
    relative_test = test_ratio / val_test_ratio
    try:
        val_data, test_data = train_test_split(
            val_test_data,
            test_size=relative_test,
            random_state=seed,
            stratify=val_test_keys if use_stratify else None,
        )
    except ValueError:
        val_data, test_data = train_test_split(
            val_test_data,
            test_size=relative_test,
            random_state=seed,
        )

    # Save splits
    train_path = output_dir / "train.jsonl"
    val_path = output_dir / "val.jsonl"
    test_path = output_dir / "test.jsonl"

    _save_jsonl(train_data, train_path)
    _save_jsonl(val_data, val_path)
    _save_jsonl(test_data, test_path)

    # Compute and print statistics
    train_dist = _compute_type_distribution(train_data)
    val_dist = _compute_type_distribution(val_data)
    test_dist = _compute_type_distribution(test_data)

    all_types = sorted(set(train_dist.keys()) | set(val_dist.keys()) | set(test_dist.keys()))

    print(f"\n{'=' * 60}")
    print(f"Dataset Split Complete")
    print(f"  Total:  {len(examples):,}")
    print(f"  Train:  {len(train_data):,} ({len(train_data)/len(examples)*100:.1f}%)")
    print(f"  Val:    {len(val_data):,} ({len(val_data)/len(examples)*100:.1f}%)")
    print(f"  Test:   {len(test_data):,} ({len(test_data)/len(examples)*100:.1f}%)")
    print(f"\n  Type distribution:")
    print(f"  {'Type':<10s} {'Train':>8s} {'Val':>8s} {'Test':>8s}")
    print(f"  {'-' * 38}")
    for t in all_types:
        print(f"  {t:<10s} {train_dist.get(t, 0):>8,} {val_dist.get(t, 0):>8,} {test_dist.get(t, 0):>8,}")
    print(f"\n  Output: {output_dir}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Split chat-formatted data into train/val/test sets."
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/processed/chat_formatted.jsonl"),
        help="Input chat-formatted JSONL file (default: data/processed/chat_formatted.jsonl)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/final"),
        help="Output directory for split files (default: data/final)",
    )
    parser.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="Train split ratio (default: 0.8)",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.1,
        help="Validation split ratio (default: 0.1)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed (default: 42)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    split_dataset(
        args.input,
        args.output_dir,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()
