"""Benchmark ONNX NER models: latency, throughput, RAM, accuracy.

Compares Python baseline, ONNX fp32, and ONNX INT8 on the same test set.

Usage:
    python -m eval.benchmark_onnx \
        --python-model /content/ner_v2 \
        --onnx-model output/onnx/model.onnx \
        --int8-model output/onnx_int8/model_int8.onnx \
        --test-file data/mix_v2/test.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import numpy as np

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark_onnx")


def _load_test_texts(test_file: str, max_examples: int = 500) -> list[str]:
    """Load test texts (unified or chat format)."""
    texts = []
    with open(test_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if "messages" in obj:
                for msg in obj["messages"]:
                    if msg.get("role") == "user":
                        texts.append(msg.get("content", ""))
            elif "text" in obj:
                texts.append(obj["text"])
            if len(texts) >= max_examples:
                break
    return texts


def _get_ram_mb() -> float:
    """Get current process RSS in MB."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except ImportError:
        # Fallback for systems without psutil
        try:
            import resource
            return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # KB→MB on Linux
        except Exception:
            return 0.0


def _benchmark_python(model_path: str, texts: list[str]) -> dict:
    """Benchmark Python (PyTorch) model."""
    from inference.inference import NERInferenceEngine

    ram_before = _get_ram_mb()
    engine = NERInferenceEngine(model_path, device="cpu", use_span_fusion=True)
    ram_after = _get_ram_mb()

    latencies = []
    all_preds = []
    for text in texts:
        t0 = time.time()
        preds = engine.predict(text)
        latencies.append((time.time() - t0) * 1000)
        all_preds.append(preds)

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)

    return {
        "label": "Python (PyTorch CPU)",
        "latencies": latencies,
        "predictions": all_preds,
        "mean_ms": sum(sorted_lat) / n,
        "p50_ms": sorted_lat[n // 2],
        "p95_ms": sorted_lat[int(n * 0.95)],
        "throughput": n / (sum(latencies) / 1000),
        "ram_delta_mb": ram_after - ram_before,
        "ram_peak_mb": _get_ram_mb(),
    }


def _run_onnx_session(
    model_path: str,
    tokenizer_dir: str,
    texts: list[str],
    label: str,
) -> dict:
    """Benchmark an ONNX model."""
    import onnxruntime as ort
    from transformers import AutoTokenizer
    from inference.span_fusion import fuse_spans
    from dataset.entity_types import ID2LABEL

    ram_before = _get_ram_mb()

    tokenizer = AutoTokenizer.from_pretrained(tokenizer_dir)
    session = ort.InferenceSession(
        model_path,
        providers=["CPUExecutionProvider"],
    )

    ram_after = _get_ram_mb()

    active_provider = session.get_providers()[0]
    logger.info("[%s] Active provider: %s", label, active_provider)

    latencies = []
    all_preds = []

    for text in texts:
        t0 = time.time()

        # Tokenize
        inputs = tokenizer(
            text, return_offsets_mapping=True,
            max_length=512, truncation=True, padding=False,
            return_tensors="np",
        )
        offset_mapping = inputs.pop("offset_mapping")[0].tolist()
        word_ids_enc = tokenizer(
            text, max_length=512, truncation=True, padding=False,
        )
        word_ids = word_ids_enc.word_ids()

        # Inference
        ort_inputs = {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"],
        }
        logits = session.run(["logits"], ort_inputs)[0]
        predictions = np.argmax(logits[0], axis=1).tolist()

        # Reconstruct spans (same logic as inference.py, "first" strategy)
        entities = []
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

            lbl = ID2LABEL.get(pred_id, "O")

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

        # Span fusion
        entities = fuse_spans(entities, text)

        elapsed = (time.time() - t0) * 1000
        latencies.append(elapsed)
        all_preds.append(entities)

    sorted_lat = sorted(latencies)
    n = len(sorted_lat)

    return {
        "label": label,
        "latencies": latencies,
        "predictions": all_preds,
        "mean_ms": sum(sorted_lat) / n,
        "p50_ms": sorted_lat[n // 2],
        "p95_ms": sorted_lat[int(n * 0.95)],
        "throughput": n / (sum(latencies) / 1000),
        "ram_delta_mb": ram_after - ram_before,
        "ram_peak_mb": _get_ram_mb(),
        "provider": active_provider if 'active_provider' in dir() else "unknown",
        "model_size_mb": os.path.getsize(model_path) / (1024 * 1024),
    }


def _compare_predictions(baseline: list, candidate: list, texts: list[str]) -> dict:
    """Compare prediction equivalence."""
    exact_match = 0
    total = len(texts)
    mismatches = []

    for i, (base, cand) in enumerate(zip(baseline, candidate)):
        base_set = {(e["y"], e["s"], e["e"]) for e in base}
        cand_set = {(e["y"], e["s"], e["e"]) for e in cand}
        if base_set == cand_set:
            exact_match += 1
        else:
            if len(mismatches) < 5:
                mismatches.append({
                    "text": texts[i][:80],
                    "baseline": [(e["y"], e["t"]) for e in base],
                    "candidate": [(e["y"], e["t"]) for e in cand],
                })

    return {
        "exact_match_rate": exact_match / total if total > 0 else 0,
        "mismatches": total - exact_match,
        "sample_mismatches": mismatches,
    }


def main():
    parser = argparse.ArgumentParser(description="Benchmark ONNX NER models.")
    parser.add_argument("--python-model", type=str, default=None)
    parser.add_argument("--onnx-model", type=str, default=None)
    parser.add_argument("--int8-model", type=str, default=None)
    parser.add_argument("--tokenizer-dir", type=str, default=None,
                        help="Tokenizer dir (defaults to onnx model parent dir)")
    parser.add_argument("--test-file", type=str, required=True)
    parser.add_argument("--max-examples", type=int, default=500)
    parser.add_argument("--output", type=str, default="output/benchmark_onnx.json")
    args = parser.parse_args()

    texts = _load_test_texts(args.test_file, args.max_examples)
    logger.info("Loaded %d test texts", len(texts))

    results = {}
    baseline_preds = None

    # Python baseline
    if args.python_model:
        logger.info("Benchmarking Python model...")
        r = _benchmark_python(args.python_model, texts)
        results["python"] = {k: v for k, v in r.items() if k not in ("latencies", "predictions")}
        baseline_preds = r["predictions"]
        logger.info("  Mean: %.1f ms, P50: %.1f ms, P95: %.1f ms", r["mean_ms"], r["p50_ms"], r["p95_ms"])

    # ONNX fp32
    if args.onnx_model:
        tok_dir = args.tokenizer_dir or str(Path(args.onnx_model).parent)
        logger.info("Benchmarking ONNX fp32...")
        r = _run_onnx_session(args.onnx_model, tok_dir, texts, "ONNX fp32 (CPU)")
        results["onnx_fp32"] = {k: v for k, v in r.items() if k not in ("latencies", "predictions")}
        if baseline_preds:
            eq = _compare_predictions(baseline_preds, r["predictions"], texts)
            results["onnx_fp32"]["equivalence"] = eq
            logger.info("  Equivalence: %.1f%% exact match", eq["exact_match_rate"] * 100)
        logger.info("  Mean: %.1f ms, P50: %.1f ms, P95: %.1f ms", r["mean_ms"], r["p50_ms"], r["p95_ms"])

    # ONNX INT8
    if args.int8_model:
        tok_dir = args.tokenizer_dir or str(Path(args.int8_model).parent)
        logger.info("Benchmarking ONNX INT8...")
        r = _run_onnx_session(args.int8_model, tok_dir, texts, "ONNX INT8 (CPU)")
        results["onnx_int8"] = {k: v for k, v in r.items() if k not in ("latencies", "predictions")}
        if baseline_preds:
            eq = _compare_predictions(baseline_preds, r["predictions"], texts)
            results["onnx_int8"]["equivalence"] = eq
            logger.info("  Equivalence: %.1f%% exact match", eq["exact_match_rate"] * 100)
        logger.info("  Mean: %.1f ms, P50: %.1f ms, P95: %.1f ms", r["mean_ms"], r["p50_ms"], r["p95_ms"])

    # Print table
    print(f"\n{'=' * 90}")
    print("  ONNX Benchmark Results")
    print(f"{'=' * 90}")
    print(f"  {'Config':<22s} {'Mean':>8s} {'P50':>8s} {'P95':>8s} {'Thrpt':>8s} {'RAM':>8s} {'Size':>8s} {'Equiv':>8s}")
    print(f"  {'-' * 78}")
    for key, r in results.items():
        equiv = f"{r.get('equivalence', {}).get('exact_match_rate', 1.0)*100:.0f}%" if "equivalence" in r else "base"
        size = f"{r.get('model_size_mb', 0):.0f}MB" if r.get("model_size_mb") else "-"
        print(f"  {r['label']:<22s} {r['mean_ms']:>7.1f}ms {r['p50_ms']:>7.1f}ms {r['p95_ms']:>7.1f}ms "
              f"{r['throughput']:>7.1f}/s {r['ram_peak_mb']:>6.0f}MB {size:>8s} {equiv:>8s}")

    print(f"{'=' * 90}\n")

    # Save
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w") as f:
        json.dump(results, f, indent=2, default=str)
    logger.info("Results saved to %s", out)


if __name__ == "__main__":
    main()
