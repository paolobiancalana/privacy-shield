"""Export trained NER model to ONNX format.

Uses HuggingFace Optimum for clean export with tokenizer and config.
Validates output equivalence against the Python model.

Usage:
    python -m export.onnx_export --model-path /content/ner_v2 --output-dir output/onnx
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForTokenClassification, AutoTokenizer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("onnx_export")

# Test sentences for equivalence validation
_VALIDATION_TEXTS = [
    "Il dottor Bianchi di Milano ha diagnosticato diabete tipo 2.",
    "Mario Rossi abita in Via Garibaldi 42, 20100 Milano (MI).",
    "La pizza margherita è buonissima.",
    "Fattura di Rossi S.r.l., partita iva 01234567890.",
    "Mio fratello Marco lavora al tribunale di Roma.",
]


def export_onnx(model_path: str, output_dir: str) -> Path:
    """Export model to ONNX with validation."""
    model_path = Path(model_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Loading model from %s", model_path)
    tokenizer = AutoTokenizer.from_pretrained(str(model_path))
    model = AutoModelForTokenClassification.from_pretrained(str(model_path))
    model.eval()

    # Get a sample input for tracing
    sample = tokenizer(
        "Mario Rossi abita a Milano.",
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )

    onnx_path = output_dir / "model.onnx"

    logger.info("Exporting to ONNX: %s", onnx_path)
    with torch.no_grad():
        torch.onnx.export(
            model,
            (sample["input_ids"], sample["attention_mask"]),
            str(onnx_path),
            opset_version=14,
            input_names=["input_ids", "attention_mask"],
            output_names=["logits"],
            dynamic_axes={
                "input_ids": {0: "batch", 1: "sequence"},
                "attention_mask": {0: "batch", 1: "sequence"},
                "logits": {0: "batch", 1: "sequence"},
            },
        )

    # Copy tokenizer and config to output dir
    tokenizer.save_pretrained(str(output_dir))
    model.config.save_pretrained(str(output_dir))

    onnx_size_mb = onnx_path.stat().st_size / (1024 * 1024)
    logger.info("ONNX exported: %.1f MB", onnx_size_mb)

    # Validate equivalence
    logger.info("Validating ONNX output equivalence...")
    import onnxruntime as ort

    session = ort.InferenceSession(
        str(onnx_path),
        providers=["CPUExecutionProvider"],
    )

    max_diff = 0.0
    for text in _VALIDATION_TEXTS:
        inputs = tokenizer(
            text, return_tensors="pt", padding=True,
            truncation=True, max_length=512,
        )

        # Python model
        with torch.no_grad():
            pt_logits = model(
                input_ids=inputs["input_ids"],
                attention_mask=inputs["attention_mask"],
            ).logits.numpy()

        # ONNX model
        ort_inputs = {
            "input_ids": inputs["input_ids"].numpy(),
            "attention_mask": inputs["attention_mask"].numpy(),
        }
        ort_logits = session.run(["logits"], ort_inputs)[0]

        diff = np.abs(pt_logits - ort_logits).max()
        max_diff = max(max_diff, diff)

        # Check prediction equivalence
        pt_preds = np.argmax(pt_logits, axis=2)
        ort_preds = np.argmax(ort_logits, axis=2)
        assert np.array_equal(pt_preds, ort_preds), (
            f"Prediction mismatch on: {text[:60]}"
        )

    logger.info("Validation passed. Max logit diff: %.6f", max_diff)

    # Print summary
    print(f"\n{'=' * 60}")
    print("ONNX Export Complete")
    print(f"  Model:     {model_path}")
    print(f"  Output:    {onnx_path}")
    print(f"  Size:      {onnx_size_mb:.1f} MB")
    print(f"  Max diff:  {max_diff:.6f}")
    print(f"  Validated: {len(_VALIDATION_TEXTS)} texts, predictions identical")
    print(f"{'=' * 60}\n")

    return onnx_path


def main():
    parser = argparse.ArgumentParser(description="Export NER model to ONNX.")
    parser.add_argument("--model-path", type=str, required=True)
    parser.add_argument("--output-dir", type=str, default="output/onnx")
    args = parser.parse_args()

    export_onnx(args.model_path, args.output_dir)


if __name__ == "__main__":
    main()
