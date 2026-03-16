"""Convert processed data to chat instruction-tuning format.

# DEPRECATED: Use dataset/ner_formatter.py for the NER token classification
# approach. This file is kept for backward compatibility and to document
# the generative (chat-formatted) approach.

Reads unified internal format from processed/ and synthetic/ directories,
produces chat-formatted JSONL with system/user/assistant messages.

Usage:
    python -m dataset.chat_formatter
    python -m dataset.chat_formatter --processed-dir data/processed --synthetic-dir data/synthetic
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from pathlib import Path

from dataset.entity_types import SYSTEM_PROMPT

logger = logging.getLogger(__name__)


def _format_assistant_content(entities: list[dict]) -> str:
    """Format entities as compact JSON array with short keys.

    Output format: [{"t":"Bianchi","y":"pe","s":11,"e":18}]
    For empty entities: "[]"
    """
    if not entities:
        return "[]"

    compact = []
    for ent in entities:
        compact.append({
            "t": ent["text"],
            "y": ent["type"],
            "s": ent["start"],
            "e": ent["end"],
        })

    return json.dumps(compact, ensure_ascii=False, separators=(",", ":"))


def _format_example(text: str, entities: list[dict]) -> dict:
    """Create a single chat-formatted training example."""
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": text},
            {"role": "assistant", "content": _format_assistant_content(entities)},
        ]
    }


def _load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file, returning a list of dicts."""
    examples = []
    with open(path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                examples.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON at %s:%d", path, line_num)
    return examples


def format_all(
    processed_dir: Path,
    synthetic_dir: Path,
    output_path: Path,
) -> None:
    """Convert all processed data to chat format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    all_formatted: list[dict] = []
    source_counts: Counter = Counter()
    with_entities = 0
    empty_entities = 0

    # Process converted datasets from processed/
    processed_files = sorted(processed_dir.glob("*.jsonl"))
    # Exclude the output file itself if it's in the same directory
    processed_files = [f for f in processed_files if f.name != output_path.name]

    for pf in processed_files:
        logger.info("Reading processed file: %s", pf.name)
        examples = _load_jsonl(pf)
        source_name = pf.stem

        for ex in examples:
            text = ex.get("text", "")
            entities = ex.get("entities", [])

            if not text:
                continue

            formatted = _format_example(text, entities)
            formatted["_source"] = source_name  # metadata for tracking
            all_formatted.append(formatted)
            source_counts[source_name] += 1

            if entities:
                with_entities += 1
            else:
                empty_entities += 1

    # Process synthetic data
    synthetic_path = synthetic_dir / "synthetic.jsonl"
    if synthetic_path.exists():
        logger.info("Reading synthetic data: %s", synthetic_path)
        examples = _load_jsonl(synthetic_path)
        for ex in examples:
            text = ex.get("text", "")
            entities = ex.get("entities", [])
            if not text:
                continue

            formatted = _format_example(text, entities)
            formatted["_source"] = "synthetic"
            all_formatted.append(formatted)
            source_counts["synthetic"] += 1

            if entities:
                with_entities += 1
            else:
                empty_entities += 1
    else:
        logger.warning("Synthetic data not found at %s", synthetic_path)

    # Process hard negatives
    hard_neg_path = synthetic_dir / "hard_negatives.jsonl"
    if hard_neg_path.exists():
        logger.info("Reading hard negatives: %s", hard_neg_path)
        examples = _load_jsonl(hard_neg_path)
        for ex in examples:
            text = ex.get("text", "")
            entities = ex.get("entities", [])
            if not text:
                continue

            formatted = _format_example(text, entities)
            formatted["_source"] = "hard_negatives"
            all_formatted.append(formatted)
            source_counts["hard_negatives"] += 1
            empty_entities += 1
    else:
        logger.warning("Hard negatives not found at %s", hard_neg_path)

    # Save
    with open(output_path, "w", encoding="utf-8") as f:
        for ex in all_formatted:
            # Write without the _source metadata (but keep it for stats)
            output = {
                "messages": ex["messages"],
                "_source": ex["_source"],
            }
            f.write(json.dumps(output, ensure_ascii=False) + "\n")

    # Print stats
    print(f"\n{'=' * 60}")
    print(f"Chat Formatting Complete")
    print(f"  Total examples:       {len(all_formatted):,}")
    print(f"  With entities:        {with_entities:,}")
    print(f"  Empty (no entities):  {empty_entities:,}")
    print(f"  Source breakdown:")
    for source, count in sorted(source_counts.items()):
        print(f"    {source:25s}: {count:,}")
    print(f"  Output: {output_path}")
    print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert processed data to chat instruction-tuning format."
    )
    parser.add_argument(
        "--processed-dir",
        type=Path,
        default=Path("data/processed"),
        help="Directory with processed JSONL files (default: data/processed)",
    )
    parser.add_argument(
        "--synthetic-dir",
        type=Path,
        default=Path("data/synthetic"),
        help="Directory with synthetic JSONL files (default: data/synthetic)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/processed/chat_formatted.jsonl"),
        help="Output file path (default: data/processed/chat_formatted.jsonl)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    format_all(args.processed_dir, args.synthetic_dir, args.output)


if __name__ == "__main__":
    main()
