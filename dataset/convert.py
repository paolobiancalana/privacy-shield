"""Convert raw datasets to unified internal format.

Each example becomes: {"text": str, "entities": [{"text": str, "type": str, "start": int, "end": int}]}

Usage:
    python -m dataset.convert
    python -m dataset.convert --input-dir data/raw --output-dir data/processed
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

import pandas as pd

from dataset.entity_types import (
    map_entity_type,
    AI4PRIVACY_MAP,
    MULTINERD_MAP,
    WIKINEURAL_MAP,
    HUMADEX_MAP,
)

logger = logging.getLogger(__name__)

# Regex patterns for entities that should be skipped even if the dataset labels them
_REGEX_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),  # email
    re.compile(r"\+?\d[\d\s\-./]{7,15}\d"),  # phone
    re.compile(r"[A-Z]{2}\d{2}\s?[\dA-Z]{4}\s?[\dA-Z]{4}\s?[\dA-Z]{4}\s?[\dA-Z]{4}\s?[\dA-Z]{0,4}"),  # IBAN
    re.compile(r"[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]"),  # codice fiscale
]


@dataclass
class Entity:
    text: str
    type: str
    start: int
    end: int


@dataclass
class Example:
    text: str
    entities: list[Entity] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "entities": [asdict(e) for e in self.entities],
        }


@dataclass
class ConversionStats:
    total_examples: int = 0
    total_entities: int = 0
    skipped_entities: int = 0
    entity_type_counts: Counter = field(default_factory=Counter)
    skip_reasons: Counter = field(default_factory=Counter)


def _looks_like_regex_entity(text: str) -> bool:
    """Check if entity text matches a regex-handled pattern."""
    for pattern in _REGEX_PATTERNS:
        if pattern.fullmatch(text.strip()):
            return True
    return False


def _validate_entity(text: str, entity: Entity) -> bool:
    """Validate that entity offsets align with the text."""
    if entity.start < 0 or entity.end > len(text) or entity.start >= entity.end:
        return False
    return text[entity.start : entity.end] == entity.text


# ──────────────────────────────────────────────────────────────────────
# BIO format conversion (MultiNERD, WikiNEuRal)
# ──────────────────────────────────────────────────────────────────────


def _bio_to_examples(
    df: pd.DataFrame,
    label_names: list[str],
    type_map: dict[str, str | None],
    dataset_name: str,
    stats: ConversionStats,
) -> list[Example]:
    """Convert a BIO-tagged DataFrame to a list of Examples.

    Expects columns 'tokens' (list[str]) and 'ner_tags' (list[int]).
    label_names maps int tags to BIO label strings (e.g. "O", "B-PER", "I-PER").
    """
    examples: list[Example] = []

    for _, row in df.iterrows():
        tokens = row["tokens"]
        tags = row["ner_tags"]

        if tokens is None or tags is None or len(tokens) == 0 or len(tags) == 0 or len(tokens) != len(tags):
            continue

        # Reconstruct text with spaces and compute char offsets per token
        text_parts: list[str] = []
        offsets: list[tuple[int, int]] = []
        pos = 0
        for tok in tokens:
            if text_parts:
                text_parts.append(" ")
                pos += 1
            start = pos
            text_parts.append(tok)
            pos += len(tok)
            offsets.append((start, pos))
        text = "".join(text_parts)

        # Extract entities from BIO tags
        entities: list[Entity] = []
        current_type: str | None = None
        current_start: int | None = None
        current_end: int | None = None

        for i, tag_id in enumerate(tags):
            if tag_id < 0 or tag_id >= len(label_names):
                label = "O"
            else:
                label = label_names[tag_id]

            if label.startswith("B-"):
                # Close previous entity
                if current_type is not None:
                    _emit_bio_entity(
                        text, current_type, current_start, current_end,
                        type_map, dataset_name, entities, stats,
                    )
                raw_type = label[2:]
                current_type = raw_type
                current_start = offsets[i][0]
                current_end = offsets[i][1]
            elif label.startswith("I-") and current_type is not None:
                raw_type = label[2:]
                if raw_type == current_type:
                    current_end = offsets[i][1]
                else:
                    _emit_bio_entity(
                        text, current_type, current_start, current_end,
                        type_map, dataset_name, entities, stats,
                    )
                    current_type = None
                    current_start = None
                    current_end = None
            else:
                if current_type is not None:
                    _emit_bio_entity(
                        text, current_type, current_start, current_end,
                        type_map, dataset_name, entities, stats,
                    )
                current_type = None
                current_start = None
                current_end = None

        # Close any trailing entity
        if current_type is not None:
            _emit_bio_entity(
                text, current_type, current_start, current_end,
                type_map, dataset_name, entities, stats,
            )

        if entities:
            examples.append(Example(text=text, entities=entities))
            stats.total_examples += 1
            stats.total_entities += len(entities)

    return examples


def _emit_bio_entity(
    text: str,
    raw_type: str,
    start: int | None,
    end: int | None,
    type_map: dict[str, str | None],
    dataset_name: str,
    entities: list[Entity],
    stats: ConversionStats,
) -> None:
    """Validate and emit a single BIO entity."""
    if start is None or end is None:
        return

    ps_type = type_map.get(raw_type)
    if ps_type is None:
        stats.skipped_entities += 1
        stats.skip_reasons[f"unmapped:{raw_type}"] += 1
        return

    entity_text = text[start:end]
    if _looks_like_regex_entity(entity_text):
        stats.skipped_entities += 1
        stats.skip_reasons["regex_pattern"] += 1
        return

    entity = Entity(text=entity_text, type=ps_type, start=start, end=end)
    assert _validate_entity(text, entity), (
        f"Offset mismatch: text[{start}:{end}]='{text[start:end]}' != '{entity_text}'"
    )
    entities.append(entity)
    stats.entity_type_counts[ps_type] += 1


# ──────────────────────────────────────────────────────────────────────
# MultiNERD label list
# ──────────────────────────────────────────────────────────────────────

MULTINERD_LABELS = [
    "O",
    "B-PER", "I-PER",
    "B-ORG", "I-ORG",
    "B-LOC", "I-LOC",
    "B-ANIM", "I-ANIM",
    "B-BIO", "I-BIO",
    "B-CEL", "I-CEL",
    "B-DIS", "I-DIS",
    "B-EVE", "I-EVE",
    "B-FOOD", "I-FOOD",
    "B-INST", "I-INST",
    "B-MEDIA", "I-MEDIA",
    "B-MYTH", "I-MYTH",
    "B-PLANT", "I-PLANT",
    "B-TIME", "I-TIME",
    "B-VEHI", "I-VEHI",
]

# ──────────────────────────────────────────────────────────────────────
# WikiNEuRal label list
# ──────────────────────────────────────────────────────────────────────

WIKINEURAL_LABELS = [
    "O",
    "B-PER", "I-PER",
    "B-ORG", "I-ORG",
    "B-LOC", "I-LOC",
    "B-MISC", "I-MISC",
]


# ──────────────────────────────────────────────────────────────────────
# ai4privacy converters
# ──────────────────────────────────────────────────────────────────────

_LANG_KEEP = {"it", "Italian", "en", "English"}


def _convert_ai4privacy(
    raw_dir: Path,
    dataset_name: str,
    stats: ConversionStats,
) -> list[Example]:
    """Convert an ai4privacy dataset from raw Parquet files."""
    examples: list[Example] = []
    parquet_files = sorted(raw_dir.glob("*.parquet"))

    if not parquet_files:
        logger.warning("No parquet files found in %s", raw_dir)
        return examples

    for pf in parquet_files:
        logger.info("  Reading %s", pf.name)
        df = pd.read_parquet(pf)

        # Filter by language if column exists
        lang_col = None
        for candidate in ("language", "lang", "Language"):
            if candidate in df.columns:
                lang_col = candidate
                break
        if lang_col:
            before = len(df)
            df = df[df[lang_col].isin(_LANG_KEEP)]
            logger.info("  Language filter: %d -> %d rows", before, len(df))

        for _, row in df.iterrows():
            example = _parse_ai4privacy_row(row, dataset_name, stats)
            if example and example.entities:
                examples.append(example)
                stats.total_examples += 1
                stats.total_entities += len(example.entities)

    return examples


def _parse_ai4privacy_row(
    row: Any,
    dataset_name: str,
    stats: ConversionStats,
) -> Example | None:
    """Parse a single ai4privacy row into an Example."""
    # Try different column layouts
    text = None
    entities: list[Entity] = []

    # Layout 1: source_text + span_labels (JSON or structured)
    if "source_text" in row.index:
        text = str(row["source_text"])
    elif "text" in row.index:
        text = str(row["text"])

    if text is None:
        return None

    # Try to extract entities from available columns
    if "span_labels" in row.index and row["span_labels"] is not None:
        span_labels = row["span_labels"]
        entities = _parse_span_labels(text, span_labels, dataset_name, stats)
    elif "privacy_mask" in row.index and row["privacy_mask"] is not None:
        # privacy_mask is a JSON-encoded list of PII annotations
        privacy_mask = row["privacy_mask"]
        entities = _parse_span_labels(text, privacy_mask, dataset_name, stats)

    # Fallback: try BIO tokens (mbert_tokens + mbert_token_classes)
    if not entities:
        token_col = "mbert_tokens" if "mbert_tokens" in row.index else "mbert_text_tokens" if "mbert_text_tokens" in row.index else None
        label_col = "mbert_token_classes" if "mbert_token_classes" in row.index else "mbert_bio_labels" if "mbert_bio_labels" in row.index else None
        if token_col and label_col and row[token_col] is not None and row[label_col] is not None:
            entities = _parse_bio_tokens(text, row[token_col], row[label_col], dataset_name, stats)

    if not entities:
        return None

    return Example(text=text, entities=entities)


def _parse_span_labels(
    text: str,
    span_labels: Any,
    dataset_name: str,
    stats: ConversionStats,
) -> list[Entity]:
    """Parse span_labels into entities. Handles JSON strings and lists."""
    entities: list[Entity] = []

    # Parse JSON if string
    if isinstance(span_labels, str):
        try:
            span_labels = json.loads(span_labels)
        except json.JSONDecodeError:
            # Try comma-separated format: "TYPE: text, TYPE: text"
            return _parse_label_string(text, span_labels, dataset_name, stats)

    # Handle numpy arrays (ai4privacy stores privacy_mask as ndarray of dicts)
    import numpy as np
    if isinstance(span_labels, np.ndarray):
        span_labels = span_labels.tolist()

    if isinstance(span_labels, list):
        for item in span_labels:
            if isinstance(item, dict):
                label_type = str(
                    item.get("label") or item.get("type") or item.get("entity_type") or ""
                ).upper()
                entity_text = item.get("text") or item.get("value", "")
                start = item.get("start")
                end = item.get("end")

                ps_type = AI4PRIVACY_MAP.get(label_type)
                if ps_type is None:
                    stats.skipped_entities += 1
                    stats.skip_reasons[f"unmapped:{label_type}"] += 1
                    continue

                if _looks_like_regex_entity(str(entity_text)):
                    stats.skipped_entities += 1
                    stats.skip_reasons["regex_pattern"] += 1
                    continue

                # Resolve offsets if not provided
                if start is not None and end is not None:
                    start, end = int(start), int(end)
                else:
                    idx = text.find(str(entity_text))
                    if idx == -1:
                        stats.skipped_entities += 1
                        stats.skip_reasons["not_found_in_text"] += 1
                        continue
                    start, end = idx, idx + len(str(entity_text))

                if text[start:end] != str(entity_text):
                    stats.skipped_entities += 1
                    stats.skip_reasons["offset_mismatch"] += 1
                    continue

                entity = Entity(text=str(entity_text), type=ps_type, start=start, end=end)
                entities.append(entity)
                stats.entity_type_counts[ps_type] += 1

    return entities


def _parse_label_string(
    text: str,
    label_str: str,
    dataset_name: str,
    stats: ConversionStats,
) -> list[Entity]:
    """Parse ai4privacy label string format (e.g., 'FIRSTNAME: Mario, LASTNAME: Rossi')."""
    entities: list[Entity] = []
    parts = re.split(r",\s*", label_str)

    for part in parts:
        match = re.match(r"(\w+)\s*:\s*(.+)", part.strip())
        if not match:
            continue

        label_type = match.group(1).strip().upper()
        entity_text = match.group(2).strip()

        ps_type = AI4PRIVACY_MAP.get(label_type)
        if ps_type is None:
            stats.skipped_entities += 1
            stats.skip_reasons[f"unmapped:{label_type}"] += 1
            continue

        if _looks_like_regex_entity(entity_text):
            stats.skipped_entities += 1
            stats.skip_reasons["regex_pattern"] += 1
            continue

        idx = text.find(entity_text)
        if idx == -1:
            stats.skipped_entities += 1
            stats.skip_reasons["not_found_in_text"] += 1
            continue

        entity = Entity(text=entity_text, type=ps_type, start=idx, end=idx + len(entity_text))
        assert _validate_entity(text, entity), f"Offset mismatch in label_string parse"
        entities.append(entity)
        stats.entity_type_counts[ps_type] += 1

    return entities


def _parse_bio_tokens(
    text: str,
    tokens: Any,
    labels: Any,
    dataset_name: str,
    stats: ConversionStats,
) -> list[Entity]:
    """Parse BIO-style mbert_text_tokens + mbert_bio_labels."""
    entities: list[Entity] = []

    if not isinstance(tokens, list) or not isinstance(labels, list):
        return entities

    if len(tokens) != len(labels):
        return entities

    # Try to align tokens to text
    current_type: str | None = None
    current_start: int | None = None
    current_end: int | None = None  # tracked character end of the last entity token
    pos = 0

    for token, label in zip(tokens, labels):
        token_str = str(token)

        # Find token position in text
        idx = text.find(token_str, pos)
        if idx == -1:
            # Token not found, reset current entity
            if current_type is not None:
                _finalize_bio_entity(
                    text, current_type, current_start, current_end,
                    dataset_name, entities, stats,
                )
            current_type = None
            current_start = None
            current_end = None
            continue

        token_end = idx + len(token_str)
        label_str = str(label)

        if label_str.startswith("B-"):
            if current_type is not None:
                _finalize_bio_entity(
                    text, current_type, current_start, current_end,
                    dataset_name, entities, stats,
                )
            current_type = label_str[2:]
            current_start = idx
            current_end = token_end
        elif label_str.startswith("I-") and current_type is not None:
            current_end = token_end
        else:
            if current_type is not None:
                _finalize_bio_entity(
                    text, current_type, current_start, current_end,
                    dataset_name, entities, stats,
                )
            current_type = None
            current_start = None
            current_end = None

        pos = token_end

    if current_type is not None:
        _finalize_bio_entity(
            text, current_type, current_start, current_end,
            dataset_name, entities, stats,
        )

    return entities


def _finalize_bio_entity(
    text: str,
    raw_type: str,
    start: int | None,
    end: int | None,
    dataset_name: str,
    entities: list[Entity],
    stats: ConversionStats,
) -> None:
    """Finalize a BIO entity using tracked character offsets from the source text.

    start/end are character positions derived directly from token alignment
    (not recomputed from joined text parts), which correctly handles
    subword tokens and punctuation-attached tokens.
    """
    if start is None or end is None or end <= start:
        return

    ps_type = AI4PRIVACY_MAP.get(raw_type.upper())
    if ps_type is None:
        stats.skipped_entities += 1
        stats.skip_reasons[f"unmapped:{raw_type}"] += 1
        return

    entity_text = text[start:end]

    if _looks_like_regex_entity(entity_text):
        stats.skipped_entities += 1
        stats.skip_reasons["regex_pattern"] += 1
        return

    entity = Entity(text=entity_text, type=ps_type, start=start, end=end)
    # Validate: text[start:end] must equal entity_text by construction
    assert entity_text == text[start:end], (
        f"Offset mismatch: text[{start}:{end}]='{text[start:end]}' != '{entity_text}'"
    )
    entities.append(entity)
    stats.entity_type_counts[ps_type] += 1


# ──────────────────────────────────────────────────────────────────────
# HUMADEX converter
# ──────────────────────────────────────────────────────────────────────


def _convert_humadex(
    raw_dir: Path,
    stats: ConversionStats,
) -> list[Example]:
    """Convert HUMADEX Italian NER dataset."""
    examples: list[Example] = []
    parquet_files = sorted(raw_dir.glob("*.parquet"))

    if not parquet_files:
        logger.warning("No parquet files found in %s", raw_dir)
        return examples

    for pf in parquet_files:
        logger.info("  Reading %s", pf.name)
        df = pd.read_parquet(pf)

        # HUMADEX may have tokens+labels (BIO) or text+annotations format
        if "tokens" in df.columns and ("ner_tags" in df.columns or "labels" in df.columns):
            tag_col = "ner_tags" if "ner_tags" in df.columns else "labels"
            for _, row in df.iterrows():
                tokens = row["tokens"]
                tags = row[tag_col]
                if tokens is None or tags is None or len(tokens) == 0 or len(tags) == 0:
                    continue
                if len(tokens) != len(tags):
                    logger.warning("Token/tag length mismatch in HUMADEX row, skipping")
                    continue

                # Build text and extract entities
                text_parts: list[str] = []
                offsets: list[tuple[int, int]] = []
                pos = 0
                for tok in tokens:
                    if text_parts:
                        text_parts.append(" ")
                        pos += 1
                    start = pos
                    text_parts.append(str(tok))
                    pos += len(str(tok))
                    offsets.append((start, pos))
                text = "".join(text_parts)

                entities: list[Entity] = []
                current_type: str | None = None
                current_start: int | None = None
                current_end: int | None = None

                for i, tag in enumerate(tags):
                    tag_str = str(tag)
                    if tag_str.startswith("B-"):
                        if current_type is not None:
                            _emit_humadex_entity(
                                text, current_type, current_start, current_end,
                                entities, stats,
                            )
                        current_type = tag_str[2:]
                        current_start = offsets[i][0]
                        current_end = offsets[i][1]
                    elif tag_str.startswith("I-") and current_type is not None:
                        current_end = offsets[i][1]
                    else:
                        if current_type is not None:
                            _emit_humadex_entity(
                                text, current_type, current_start, current_end,
                                entities, stats,
                            )
                        current_type = None
                        current_start = None
                        current_end = None

                if current_type is not None:
                    _emit_humadex_entity(
                        text, current_type, current_start, current_end,
                        entities, stats,
                    )

                if entities:
                    examples.append(Example(text=text, entities=entities))
                    stats.total_examples += 1
                    stats.total_entities += len(entities)

        elif "text" in df.columns and "annotations" in df.columns:
            for _, row in df.iterrows():
                text = str(row["text"])
                annotations = row["annotations"]
                if not annotations:
                    continue

                entities = []
                if isinstance(annotations, str):
                    try:
                        annotations = json.loads(annotations)
                    except json.JSONDecodeError:
                        continue

                if isinstance(annotations, list):
                    for ann in annotations:
                        if isinstance(ann, dict):
                            raw_type = ann.get("label") or ann.get("type", "")
                            ps_type = HUMADEX_MAP.get(raw_type.upper())
                            if ps_type is None:
                                stats.skipped_entities += 1
                                stats.skip_reasons[f"unmapped:{raw_type}"] += 1
                                continue

                            start = int(ann.get("start", 0))
                            end = int(ann.get("end", 0))
                            entity_text = text[start:end]

                            if _looks_like_regex_entity(entity_text):
                                stats.skipped_entities += 1
                                stats.skip_reasons["regex_pattern"] += 1
                                continue

                            entity = Entity(text=entity_text, type=ps_type, start=start, end=end)
                            if _validate_entity(text, entity):
                                entities.append(entity)
                                stats.entity_type_counts[ps_type] += 1
                            else:
                                stats.skipped_entities += 1
                                stats.skip_reasons["offset_mismatch"] += 1

                if entities:
                    examples.append(Example(text=text, entities=entities))
                    stats.total_examples += 1
                    stats.total_entities += len(entities)
        else:
            logger.warning(
                "HUMADEX: unrecognized format, columns: %s",
                list(df.columns),
            )

    return examples


def _emit_humadex_entity(
    text: str,
    raw_type: str,
    start: int | None,
    end: int | None,
    entities: list[Entity],
    stats: ConversionStats,
) -> None:
    if start is None or end is None:
        return

    ps_type = HUMADEX_MAP.get(raw_type.upper())
    if ps_type is None:
        stats.skipped_entities += 1
        stats.skip_reasons[f"unmapped:{raw_type}"] += 1
        return

    entity_text = text[start:end]
    if _looks_like_regex_entity(entity_text):
        stats.skipped_entities += 1
        stats.skip_reasons["regex_pattern"] += 1
        return

    entity = Entity(text=entity_text, type=ps_type, start=start, end=end)
    assert _validate_entity(text, entity), (
        f"HUMADEX offset mismatch: text[{start}:{end}]='{text[start:end]}' != '{entity_text}'"
    )
    entities.append(entity)
    stats.entity_type_counts[ps_type] += 1


# ──────────────────────────────────────────────────────────────────────
# BIO dataset converters (MultiNERD, WikiNEuRal)
# ──────────────────────────────────────────────────────────────────────


def _convert_bio_dataset(
    raw_dir: Path,
    label_names: list[str],
    type_map: dict[str, str | None],
    dataset_name: str,
    stats: ConversionStats,
) -> list[Example]:
    """Convert a BIO-format dataset from Parquet files."""
    examples: list[Example] = []
    parquet_files = sorted(raw_dir.glob("*.parquet"))

    if not parquet_files:
        logger.warning("No parquet files found in %s", raw_dir)
        return examples

    for pf in parquet_files:
        logger.info("  Reading %s", pf.name)
        df = pd.read_parquet(pf)
        batch = _bio_to_examples(df, label_names, type_map, dataset_name, stats)
        examples.extend(batch)

    return examples


# ──────────────────────────────────────────────────────────────────────
# Main conversion orchestrator
# ──────────────────────────────────────────────────────────────────────


def convert_all(input_dir: Path, output_dir: Path) -> None:
    """Convert all raw datasets to unified format."""
    output_dir.mkdir(parents=True, exist_ok=True)

    converters: list[tuple[str, Any]] = [
        ("ai4privacy_500k", lambda d, s: _convert_ai4privacy(d, "ai4privacy_500k", s)),
        ("ai4privacy_400k", lambda d, s: _convert_ai4privacy(d, "ai4privacy_400k", s)),
        ("multinerd", lambda d, s: _convert_bio_dataset(d, MULTINERD_LABELS, MULTINERD_MAP, "multinerd", s)),
        ("wikineural", lambda d, s: _convert_bio_dataset(d, WIKINEURAL_LABELS, WIKINEURAL_MAP, "wikineural", s)),
        ("humadex", lambda d, s: _convert_humadex(d, s)),
    ]

    for name, converter in converters:
        raw_path = input_dir / name
        if not raw_path.exists():
            logger.warning("Skipping %s: directory not found at %s", name, raw_path)
            continue

        logger.info("Converting %s ...", name)
        stats = ConversionStats()
        examples = converter(raw_path, stats)

        # Save to JSONL
        output_path = output_dir / f"{name}.jsonl"
        with open(output_path, "w", encoding="utf-8") as f:
            for ex in examples:
                f.write(json.dumps(ex.to_dict(), ensure_ascii=False) + "\n")

        # Print statistics
        print(f"\n{'=' * 60}")
        print(f"Dataset: {name}")
        print(f"  Total examples:     {stats.total_examples:,}")
        print(f"  Total entities:     {stats.total_entities:,}")
        print(f"  Skipped entities:   {stats.skipped_entities:,}")
        print(f"  Entity types:")
        for etype, count in sorted(stats.entity_type_counts.items()):
            print(f"    {etype:6s}: {count:,}")
        if stats.skip_reasons:
            print(f"  Skip reasons:")
            for reason, count in stats.skip_reasons.most_common():
                print(f"    {reason}: {count:,}")
        print(f"  Output: {output_path}")
        print(f"{'=' * 60}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert raw datasets to unified internal format for Privacy Shield."
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path("data/raw"),
        help="Input directory with raw datasets (default: data/raw)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/processed"),
        help="Output directory for processed JSONL files (default: data/processed)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    convert_all(args.input_dir, args.output_dir)
    logger.info("Conversion complete.")


if __name__ == "__main__":
    main()
