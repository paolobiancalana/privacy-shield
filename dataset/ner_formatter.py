"""Format split JSONL data into BIO-tagged Arrow datasets for NER training.

Reads pre-split unified/chat-format JSONL files from data/final/ (produced by
dataset.split), converts each split independently to mDeBERTa-tokenized
Arrow datasets via bio_converter, and saves to data/final_ner/.

Split happens BEFORE tokenization to avoid data leakage.

Usage:
    python -m dataset.ner_formatter
    python -m dataset.ner_formatter --input-dir data/final --output-dir data/final_ner
    python -m dataset.ner_formatter --model microsoft/mdeberta-v3-base
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from transformers import AutoTokenizer

from dataset.bio_converter import convert_jsonl_to_dataset

logger = logging.getLogger(__name__)


def format_ner_dataset(
    input_dir: Path,
    output_dir: Path,
    model_id: str = "microsoft/mdeberta-v3-base",
    max_length: int = 512,
) -> None:
    """Convert all splits to BIO-tagged Arrow datasets.

    Parameters
    ----------
    input_dir:
        Directory with pre-split JSONL files (train.jsonl, val.jsonl, test.jsonl).
    output_dir:
        Directory to save Arrow datasets (one subdirectory per split).
    model_id:
        HuggingFace model ID for tokenizer.
    max_length:
        Maximum sequence length for tokenization.
    """
    logger.info("Loading tokenizer: %s", model_id)
    tokenizer = AutoTokenizer.from_pretrained(model_id)

    output_dir.mkdir(parents=True, exist_ok=True)

    splits = ["train", "val", "test"]
    total_examples = {}

    for split in splits:
        input_path = input_dir / f"{split}.jsonl"
        if not input_path.exists():
            logger.warning("Split file not found, skipping: %s", input_path)
            continue

        logger.info("Processing split: %s", split)
        dataset = convert_jsonl_to_dataset(input_path, tokenizer, max_length)

        split_output = output_dir / split
        dataset.save_to_disk(str(split_output))
        total_examples[split] = len(dataset)
        logger.info("Saved %d examples to %s", len(dataset), split_output)

    # Print summary
    print(f"\n{'=' * 60}")
    print("NER Dataset Formatting Complete")
    print(f"  Model: {model_id}")
    print(f"  Max length: {max_length}")
    for split, count in total_examples.items():
        print(f"  {split:6s}: {count:,} examples")
    print(f"  Output: {output_dir}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert split JSONL to BIO-tagged Arrow datasets for NER."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/final"),
        help="Directory with pre-split JSONL files (default: data/final)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/final_ner"),
        help="Directory to save Arrow datasets (default: data/final_ner)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="microsoft/mdeberta-v3-base",
        help="HuggingFace model ID for tokenizer (default: microsoft/mdeberta-v3-base)",
    )
    parser.add_argument(
        "--max-length",
        type=int,
        default=512,
        help="Maximum sequence length (default: 512)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    format_ner_dataset(args.input_dir, args.output_dir, args.model, args.max_length)


if __name__ == "__main__":
    main()
