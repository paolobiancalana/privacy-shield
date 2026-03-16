"""
NerDetectionAdapter — implements DetectionPort using ONNX Runtime NER model.

Uses XLM-RoBERTa-base (INT8 quantized) for token classification with
deterministic span reconstruction and span_fusion post-processing.

No PyTorch dependency — runs entirely on ONNX Runtime CPU.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer

from app.domain.entities import DetectionResult, PiiSpan
from app.domain.ports.detection_port import DetectionPort

logger = logging.getLogger("pii.ner_detection")

# BIO label system — must match training
_NER_LABELS = [
    "O", "B-pe", "I-pe", "B-org", "I-org", "B-loc", "I-loc",
    "B-ind", "I-ind", "B-med", "I-med", "B-leg", "I-leg",
    "B-rel", "I-rel", "B-fin", "I-fin", "B-pro", "I-pro",
    "B-dt", "I-dt",
]
_ID2LABEL = {i: label for i, label in enumerate(_NER_LABELS)}

# Punctuation to trim from entity boundaries
_TRIM_TRAILING = set(",:;]}>?\u2014\u2013!")
_TRIM_LEADING = set("[{<")
_KNOWN_ABBREVS = frozenset({
    "dott.", "ing.", "avv.", "geom.", "prof.", "arch.", "rag.",
    "sig.", "sigg.", "spett.", "ecc.",
})

import re
_ABBREV_TAIL_RE = re.compile(r"[A-Z](?:\.[a-zA-Z])+\.$")


class NerDetectionAdapter(DetectionPort):
    """
    ONNX Runtime NER detector for contextual PII entities.

    Detects: pe, org, loc, ind, med, leg, rel, fin, pro, dt.
    Thread-safe after initialization (read-only model session).
    """

    def __init__(self, model_dir: str) -> None:
        logger.info("Loading NER model from %s", model_dir)
        t0 = time.time()

        self._tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model_path = str(Path(model_dir) / "model_int8.onnx")
        if not Path(model_path).exists():
            # Fallback to fp32
            model_path = str(Path(model_dir) / "model.onnx")
        self._session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )

        elapsed = time.time() - t0
        provider = self._session.get_providers()[0]
        logger.info("NER model loaded in %.1fs (provider: %s)", elapsed, provider)

    async def detect(self, text: str) -> DetectionResult:
        """Run NER on text and return PiiSpan entities."""
        if not text or not text.strip():
            return DetectionResult(spans=[], detection_ms=0.0, source="slm")

        t0 = time.perf_counter()

        # Tokenize
        inputs = self._tokenizer(
            text, return_offsets_mapping=True,
            max_length=512, truncation=True, padding=False,
            return_tensors="np",
        )
        offset_mapping = inputs.pop("offset_mapping")[0].tolist()
        word_ids_enc = self._tokenizer(
            text, max_length=512, truncation=True, padding=False,
        )
        word_ids = word_ids_enc.word_ids()

        # Inference
        logits = self._session.run(
            ["logits"],
            {"input_ids": inputs["input_ids"], "attention_mask": inputs["attention_mask"]},
        )[0]
        predictions = np.argmax(logits[0], axis=1).tolist()

        # Reconstruct spans
        raw_entities = self._reconstruct_spans(text, predictions, offset_mapping, word_ids)

        # Trim punctuation
        trimmed = self._trim_spans(raw_entities, text)

        # Build PiiSpan objects
        spans: list[PiiSpan] = []
        for ent in trimmed:
            try:
                spans.append(PiiSpan(
                    start=ent["s"],
                    end=ent["e"],
                    text=ent["t"],
                    pii_type=ent["y"],
                    source="slm",
                    confidence=0.85,
                ))
            except ValueError:
                continue  # skip invalid spans

        detection_ms = (time.perf_counter() - t0) * 1000.0
        return DetectionResult(spans=spans, detection_ms=detection_ms, source="slm")

    def _reconstruct_spans(
        self, text: str, predictions: list[int],
        offset_mapping: list[list[int]], word_ids: list[int | None],
    ) -> list[dict]:
        """BIO → span reconstruction with first-subword strategy."""
        entities: list[dict] = []
        current = None
        prev_wid = None

        for idx, (pred_id, (cs, ce)) in enumerate(zip(predictions, offset_mapping)):
            wid = word_ids[idx] if idx < len(word_ids) else None

            if cs == 0 and ce == 0:
                if current:
                    entities.append(current)
                    current = None
                prev_wid = wid
                continue

            if wid is not None and wid == prev_wid:
                if current:
                    current["e"] = ce
                    current["t"] = text[current["s"]:ce]
                prev_wid = wid
                continue

            lbl = _ID2LABEL.get(pred_id, "O")

            if lbl.startswith("B-"):
                if current:
                    entities.append(current)
                current = {"t": text[cs:ce], "y": lbl[2:], "s": cs, "e": ce}
            elif lbl.startswith("I-"):
                etype = lbl[2:]
                if current and current["y"] == etype:
                    current["e"] = ce
                    current["t"] = text[current["s"]:ce]
                else:
                    if current:
                        entities.append(current)
                    current = {"t": text[cs:ce], "y": etype, "s": cs, "e": ce}
            else:
                if current:
                    entities.append(current)
                    current = None

            prev_wid = wid

        if current:
            entities.append(current)

        return entities

    def _trim_spans(self, entities: list[dict], text: str) -> list[dict]:
        """Trim punctuation from span boundaries."""
        result = []
        for ent in entities:
            s, e = ent["s"], ent["e"]

            # Trim leading
            while s < e and text[s] in _TRIM_LEADING:
                s += 1
            while s < e and text[s] in "\"(" and (s == 0 or text[s - 1] in " \n\t"):
                s += 1

            # Trim trailing
            while e > s:
                ch = text[e - 1]
                if ch in _TRIM_TRAILING:
                    if ch == ")" and "(" in text[s:e - 1]:
                        break
                    e -= 1
                    continue
                if ch == ".":
                    candidate = text[s:e]
                    if _ABBREV_TAIL_RE.search(candidate):
                        break
                    last_word_start = candidate.rfind(" ") + 1
                    last_word = candidate[last_word_start:].lower()
                    if last_word in _KNOWN_ABBREVS:
                        break
                    e -= 1
                    continue
                if ch == ")" and "(" not in text[s:e - 1]:
                    e -= 1
                    continue
                if ch == "s" and e - s >= 3 and text[e - 2] in "'\u2019" and text[e - 3].isalpha():
                    e -= 2
                    continue
                if ch in "'\u2019":
                    if e - 2 >= s and text[e - 2].isalpha():
                        break
                    e -= 1
                    continue
                if ch == "\"":
                    e -= 1
                    continue
                break

            if e > s:
                result.append({"t": text[s:e], "y": ent["y"], "s": s, "e": e})

        return result
