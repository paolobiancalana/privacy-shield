"""Privacy Shield PII Detection — FastAPI Service.

Serves the ONNX INT8 NER model + regex engine + span fusion
via a single /predict endpoint.

Usage:
    uvicorn server:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import AutoTokenizer

from inference.span_fusion import fuse_spans
from dataset.entity_types import ID2LABEL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("pii-service")

# ── Config ────────────────────────────────────────────────────────────

MODEL_DIR = os.environ.get("PII_MODEL_DIR", "/opt/pii/model")
HOST = os.environ.get("PII_HOST", "0.0.0.0")
PORT = int(os.environ.get("PII_PORT", "8000"))

# ── Regex PII patterns ───────────────────────────────────────────────

_REGEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("cf", re.compile(r"\b([A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z])\b")),
    ("ib", re.compile(r"\b(IT\d{2}[A-Z]\d{22})\b")),
    ("em", re.compile(r"\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")),
    ("tel", re.compile(r"(?:\+39\s?)?(?:0\d{1,4}[\s\-]?\d{4,8}|3\d{2}[\s\-]?\d{6,7})\b")),
    ("piva", re.compile(r"\b(?:P\.?\s?IVA\s?)(\d{11})\b", re.IGNORECASE)),
    ("pec", re.compile(r"\b([a-zA-Z0-9._%+\-]+@pec\.[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b")),
    ("sdi", re.compile(r"\b(?:SDI|codice\s+sdi)\s+([A-Z0-9]{7})\b", re.IGNORECASE)),
]


def _extract_regex(text: str) -> list[dict]:
    entities = []
    for pii_type, pattern in _REGEX_PATTERNS:
        for match in pattern.finditer(text):
            group = match.group(1) if match.lastindex else match.group(0)
            start = match.start(1) if match.lastindex else match.start(0)
            end = match.end(1) if match.lastindex else match.end(0)
            entities.append({"t": group, "y": pii_type, "s": start, "e": end, "source": "regex"})
    return entities


def _merge_regex_ner(regex_ents: list[dict], ner_ents: list[dict]) -> list[dict]:
    regex_ranges: set[int] = set()
    for ent in regex_ents:
        regex_ranges.update(range(ent["s"], ent["e"]))

    merged = list(regex_ents)
    for ent in ner_ents:
        ent_range = set(range(ent["s"], ent["e"]))
        overlap = ent_range & regex_ranges
        if len(overlap) / max(len(ent_range), 1) < 0.5:
            merged.append({**ent, "source": "ner"})

    merged.sort(key=lambda e: e["s"])
    return merged


# ── NER Engine ────────────────────────────────────────────────────────

class ONNXNerEngine:
    def __init__(self, model_dir: str):
        logger.info("Loading model from %s", model_dir)
        t0 = time.time()

        self.tokenizer = AutoTokenizer.from_pretrained(model_dir)
        model_path = str(Path(model_dir) / "model_int8.onnx")
        self.session = ort.InferenceSession(
            model_path,
            providers=["CPUExecutionProvider"],
        )
        self._id2label = ID2LABEL

        elapsed = time.time() - t0
        provider = self.session.get_providers()[0]
        logger.info("Model loaded in %.1fs (provider: %s)", elapsed, provider)

    def predict(self, text: str) -> list[dict]:
        if not text or not text.strip():
            return []

        inputs = self.tokenizer(
            text, return_offsets_mapping=True,
            max_length=512, truncation=True, padding=False,
            return_tensors="np",
        )
        offset_mapping = inputs.pop("offset_mapping")[0].tolist()
        word_ids_enc = self.tokenizer(
            text, max_length=512, truncation=True, padding=False,
        )
        word_ids = word_ids_enc.word_ids()

        logits = self.session.run(
            ["logits"],
            {"input_ids": inputs["input_ids"], "attention_mask": inputs["attention_mask"]},
        )[0]
        predictions = np.argmax(logits[0], axis=1).tolist()

        # Reconstruct spans (first strategy)
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

            lbl = self._id2label.get(pred_id, "O")

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

        return fuse_spans(entities, text)


# ── FastAPI ───────────────────────────────────────────────────────────

app = FastAPI(title="Privacy Shield PII", version="2.0")
engine: ONNXNerEngine | None = None


@app.on_event("startup")
def startup():
    global engine
    engine = ONNXNerEngine(MODEL_DIR)


class PredictRequest(BaseModel):
    text: str


class Entity(BaseModel):
    text: str
    type: str
    start: int
    end: int
    source: str


class PredictResponse(BaseModel):
    entities: list[Entity]
    timing_ms: float
    counts: dict


@app.post("/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    if engine is None:
        raise HTTPException(503, "Model not loaded")

    t0 = time.time()

    regex_ents = _extract_regex(req.text)
    ner_ents = engine.predict(req.text)
    merged = _merge_regex_ner(regex_ents, ner_ents)

    elapsed_ms = (time.time() - t0) * 1000

    entities = [
        Entity(
            text=e["t"], type=e["y"],
            start=e["s"], end=e["e"],
            source=e.get("source", "ner"),
        )
        for e in merged
    ]

    return PredictResponse(
        entities=entities,
        timing_ms=round(elapsed_ms, 2),
        counts={
            "regex": len(regex_ents),
            "ner": len(ner_ents),
            "total": len(merged),
        },
    )


@app.get("/health")
def health():
    return {"status": "ok", "model_loaded": engine is not None}
