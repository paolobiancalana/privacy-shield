"""Deterministic NER inference engine for Privacy Shield PII detection.

Performs a single forward pass through a token classification model
and reconstructs entity spans from BIO predictions using offset_mapping.
No JSON parsing — spans are constructed programmatically, guaranteeing
100% JSON validity by construction.

Supports three aggregation strategies for subword tokens:
- "first": use only first subword prediction (default, matches -100 training)
- "average": average logits across subwords, then argmax
- "max": take max logit across subwords, then argmax

Usage:
    from inference.inference import NERInferenceEngine

    engine = NERInferenceEngine("output/ner")
    entities = engine.predict("Il dottor Bianchi di Milano ha diagnosticato diabete tipo 2")
    # [{"t": "Bianchi", "y": "pe", "s": 11, "e": 18}, ...]
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal

import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

from dataset.entity_types import ID2LABEL
from inference.span_fusion import fuse_spans

logger = logging.getLogger(__name__)

AggregationStrategy = Literal["first", "average", "max"]


class NERInferenceEngine:
    """Single-pass NER inference with deterministic span reconstruction."""

    def __init__(
        self,
        model_path: str | Path,
        device: str | None = None,
        max_length: int = 512,
        aggregation_strategy: AggregationStrategy = "first",
        use_span_fusion: bool = True,
    ) -> None:
        self.max_length = max_length
        self.aggregation_strategy = aggregation_strategy
        self.use_span_fusion = use_span_fusion

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = torch.device(device)

        logger.info("Loading NER model from %s on %s", model_path, self.device)
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path))
        self.model = AutoModelForTokenClassification.from_pretrained(str(model_path))
        self.model.to(self.device)
        self.model.eval()

        # Verify id2label is baked into the model config
        if hasattr(self.model.config, "id2label"):
            self._id2label = {int(k): v for k, v in self.model.config.id2label.items()}
        else:
            logger.warning("Model config missing id2label, using default from entity_types")
            self._id2label = ID2LABEL

        self._num_labels = len(self._id2label)

        logger.info(
            "NER model loaded: %d labels, max_length=%d, aggregation=%s, fusion=%s",
            self._num_labels, self.max_length,
            self.aggregation_strategy, self.use_span_fusion,
        )

    @torch.no_grad()
    def predict(self, text: str) -> list[dict]:
        """Run NER inference on a single text.

        Returns a list of entity dicts in compact format:
        ``[{"t": text, "y": type, "s": start, "e": end}, ...]``
        """
        if not text or not text.strip():
            return []

        # Tokenize with offset mapping
        encoding = self.tokenizer(
            text,
            return_offsets_mapping=True,
            max_length=self.max_length,
            truncation=True,
            padding=False,
            return_tensors="pt",
        )

        offset_mapping = encoding.pop("offset_mapping")[0].tolist()
        word_ids = encoding.word_ids()
        input_ids = encoding["input_ids"].to(self.device)
        attention_mask = encoding["attention_mask"].to(self.device)

        # Forward pass → logits
        outputs = self.model(input_ids=input_ids, attention_mask=attention_mask)
        logits = outputs.logits[0]  # (seq_len, num_labels)

        # Resolve per-word predictions based on aggregation strategy
        predictions = self._aggregate_predictions(logits, word_ids)

        # Reconstruct spans from BIO predictions
        entities = self._reconstruct_spans(text, predictions, offset_mapping, word_ids)

        # Post-processing
        if self.use_span_fusion:
            entities = fuse_spans(entities, text)

        return entities

    def predict_batch(self, texts: list[str]) -> list[list[dict]]:
        """Run NER inference on a batch of texts."""
        return [self.predict(t) for t in texts]

    def _aggregate_predictions(
        self,
        logits: torch.Tensor,
        word_ids: list[int | None],
    ) -> list[int]:
        """Resolve per-token predictions using the configured aggregation strategy.

        For "first": argmax on each token independently (subwords handled in
            _reconstruct_spans by absorbing into current entity).
        For "average": average logits across subwords of same word, then argmax.
        For "max": take element-wise max logits across subwords, then argmax.
        """
        if self.aggregation_strategy == "first":
            return torch.argmax(logits, dim=1).tolist()

        # For average/max: group subword logits by word_id
        seq_len = logits.size(0)
        word_logits: dict[int, list[torch.Tensor]] = {}
        token_to_word: list[int | None] = []

        for idx in range(seq_len):
            w_id = word_ids[idx] if idx < len(word_ids) else None
            token_to_word.append(w_id)
            if w_id is not None:
                if w_id not in word_logits:
                    word_logits[w_id] = []
                word_logits[w_id].append(logits[idx])

        # Compute aggregated logit per word
        word_pred: dict[int, int] = {}
        for w_id, logit_list in word_logits.items():
            stacked = torch.stack(logit_list)
            if self.aggregation_strategy == "average":
                aggregated = stacked.mean(dim=0)
            else:  # max
                aggregated = stacked.max(dim=0).values
            word_pred[w_id] = torch.argmax(aggregated).item()

        # Map back to per-token predictions
        predictions: list[int] = []
        for idx in range(seq_len):
            w_id = token_to_word[idx]
            if w_id is not None and w_id in word_pred:
                predictions.append(word_pred[w_id])
            else:
                predictions.append(0)  # O for special tokens

        return predictions

    def _reconstruct_spans(
        self,
        text: str,
        predictions: list[int],
        offset_mapping: list[list[int]],
        word_ids: list[int | None],
    ) -> list[dict]:
        """Reconstruct entity spans from BIO predictions and offset_mapping.

        For "first" strategy: non-first subword tokens are absorbed into the
        current entity (their predictions are unreliable since they had -100
        in training). For "average"/"max": all tokens within a word share the
        same aggregated prediction, so subword handling still extends char_end.
        """
        entities: list[dict] = []
        current_entity: dict | None = None
        prev_word_id: int | None = None

        for idx, (pred_id, (char_start, char_end)) in enumerate(
            zip(predictions, offset_mapping)
        ):
            w_id = word_ids[idx] if idx < len(word_ids) else None

            # Skip special tokens (CLS, SEP, PAD)
            if char_start == 0 and char_end == 0:
                if current_entity is not None:
                    entities.append(current_entity)
                    current_entity = None
                prev_word_id = w_id
                continue

            # Non-first subword of the same word: absorb into current entity
            is_subword = w_id is not None and w_id == prev_word_id
            if is_subword:
                if current_entity is not None:
                    current_entity["e"] = char_end
                    current_entity["t"] = text[current_entity["s"]:char_end]
                prev_word_id = w_id
                continue

            # First subword of a new word — use its prediction
            label = self._id2label.get(pred_id, "O")

            if label.startswith("B-"):
                # Flush previous entity
                if current_entity is not None:
                    entities.append(current_entity)

                entity_type = label[2:]
                current_entity = {
                    "t": text[char_start:char_end],
                    "y": entity_type,
                    "s": char_start,
                    "e": char_end,
                }

            elif label.startswith("I-"):
                entity_type = label[2:]
                if (
                    current_entity is not None
                    and current_entity["y"] == entity_type
                ):
                    # Extend current entity
                    current_entity["e"] = char_end
                    current_entity["t"] = text[current_entity["s"]:char_end]
                else:
                    # I- without matching B- → treat as B- (robust fallback)
                    if current_entity is not None:
                        entities.append(current_entity)
                    current_entity = {
                        "t": text[char_start:char_end],
                        "y": entity_type,
                        "s": char_start,
                        "e": char_end,
                    }

            else:
                # O label → flush current entity
                if current_entity is not None:
                    entities.append(current_entity)
                    current_entity = None

            prev_word_id = w_id

        # Flush final entity
        if current_entity is not None:
            entities.append(current_entity)

        return entities
