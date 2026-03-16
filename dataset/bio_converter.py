"""Convert unified entity format to BIO-tagged token classification labels.

Converts examples in unified format ({"text", "entities": [{"text","type","start","end"}]})
to mDeBERTa-tokenized sequences with BIO labels using offset_mapping.

mDeBERTa-v3-base uses DebertaV2TokenizerFast (SentencePiece), which includes
leading spaces in tokens (e.g., " Rossi" is a single token). The offset_mapping
from the tokenizer is the authoritative source for character boundaries — no
manual alignment is attempted.

Usage:
    from dataset.bio_converter import convert_example, convert_jsonl_to_dataset
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from datasets import Dataset

from dataset.entity_types import LABEL2ID

logger = logging.getLogger(__name__)


def convert_example(
    text: str,
    entities: list[dict],
    tokenizer,
    max_length: int = 512,
) -> dict:
    """Convert a single example to BIO-tagged token classification format.

    Parameters
    ----------
    text:
        The input text.
    entities:
        List of entity dicts with keys: "text" (or "t"), "type" (or "y"),
        "start" (or "s"), "end" (or "e").
    tokenizer:
        A HuggingFace tokenizer with ``return_offsets_mapping`` support.
    max_length:
        Maximum sequence length (tokens are truncated beyond this).

    Returns
    -------
    Dict with ``input_ids``, ``attention_mask``, ``labels``.
    """
    # Normalize entity format (accept both verbose and compact keys)
    normalized: list[dict] = []
    for ent in entities:
        normalized.append({
            "type": ent.get("type") or ent.get("y"),
            "start": ent.get("start") if "start" in ent else ent.get("s"),
            "end": ent.get("end") if "end" in ent else ent.get("e"),
        })

    # Sort entities by start position for deterministic processing
    normalized.sort(key=lambda e: e["start"])

    # Tokenize with offset mapping
    encoding = tokenizer(
        text,
        return_offsets_mapping=True,
        max_length=max_length,
        truncation=True,
        padding=False,
        return_tensors=None,
    )

    offset_mapping = encoding["offset_mapping"]
    word_ids = encoding.word_ids()

    labels = []

    for idx, (char_start, char_end) in enumerate(offset_mapping):
        # Special tokens (CLS, SEP, PAD) have offset (0, 0)
        if char_start == 0 and char_end == 0:
            labels.append(-100)
            continue

        # Non-first subword tokens get -100 (ignored in loss)
        if word_ids is not None and idx > 0 and word_ids[idx] == word_ids[idx - 1]:
            labels.append(-100)
            continue

        # Find which entity (if any) this token belongs to
        label = "O"
        for ent in normalized:
            ent_start = ent["start"]
            ent_end = ent["end"]
            ent_type = ent["type"]

            # Check if token overlaps with entity span
            if char_start >= ent_end or char_end <= ent_start:
                continue

            # Token overlaps with this entity
            if char_start <= ent_start:
                # Token starts at or before entity start → B-tag
                label = f"B-{ent_type}"
            else:
                # Token starts inside entity → I-tag
                label = f"I-{ent_type}"
            break  # Entities are sorted and non-overlapping

        labels.append(LABEL2ID.get(label, 0))

    return {
        "input_ids": encoding["input_ids"],
        "attention_mask": encoding["attention_mask"],
        "labels": labels,
    }


def convert_jsonl_to_dataset(
    input_path: Path,
    tokenizer,
    max_length: int = 512,
) -> Dataset:
    """Convert a JSONL file of unified format examples to a HuggingFace Dataset.

    Each line of the JSONL must be either:
    - Unified format: ``{"text": "...", "entities": [{"text","type","start","end"}, ...]}``
    - Chat format: ``{"messages": [{"role":"system",...}, {"role":"user","content":"<text>"},
      {"role":"assistant","content":"[{\"t\":...,\"y\":...,\"s\":...,\"e\":...}]"}]}``

    Parameters
    ----------
    input_path:
        Path to the JSONL file.
    tokenizer:
        A HuggingFace tokenizer.
    max_length:
        Maximum sequence length.

    Returns
    -------
    HuggingFace Dataset with columns: input_ids, attention_mask, labels.
    """
    all_input_ids = []
    all_attention_mask = []
    all_labels = []

    skipped = 0
    total = 0

    with open(input_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1

            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("Skipping invalid JSON at %s:%d", input_path, line_num)
                skipped += 1
                continue

            # Handle both unified and chat formats
            if "messages" in obj:
                text, entities = _extract_from_chat_format(obj)
            elif "text" in obj:
                text = obj["text"]
                entities = obj.get("entities", [])
            else:
                logger.warning("Skipping unknown format at %s:%d", input_path, line_num)
                skipped += 1
                continue

            if not text:
                skipped += 1
                continue

            result = convert_example(text, entities, tokenizer, max_length)
            all_input_ids.append(result["input_ids"])
            all_attention_mask.append(result["attention_mask"])
            all_labels.append(result["labels"])

    if skipped > 0:
        logger.warning("Skipped %d/%d lines from %s", skipped, total, input_path)

    logger.info(
        "Converted %d examples from %s (skipped %d)",
        len(all_input_ids), input_path.name, skipped,
    )

    return Dataset.from_dict({
        "input_ids": all_input_ids,
        "attention_mask": all_attention_mask,
        "labels": all_labels,
    })


def _extract_from_chat_format(obj: dict) -> tuple[str, list[dict]]:
    """Extract text and entities from chat-formatted example."""
    messages = obj.get("messages", [])
    text = ""
    entities = []

    for msg in messages:
        role = msg.get("role", "")
        if role == "user":
            text = msg.get("content", "")
        elif role == "assistant":
            content = msg.get("content", "[]")
            try:
                raw_entities = json.loads(content)
                if isinstance(raw_entities, list):
                    entities = raw_entities
            except (json.JSONDecodeError, TypeError):
                entities = []

    return text, entities
