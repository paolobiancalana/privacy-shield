"""NER evaluation for Privacy Shield PII detection.

Bridges the NER inference engine with the existing metrics.py evaluation
framework. Loads test data, runs NER predictions, computes entity-level
exact/partial F1 via metrics.evaluate(), and adds seqeval NER metrics.

Usage:
    python -m eval.ner_evaluate --model-path output/ner --test-file data/final/test.jsonl
    python -m eval.ner_evaluate --model-path output/ner
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from eval.metrics import evaluate, EvalReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ner_evaluate")


def _load_test_data(
    test_file: str,
) -> tuple[list[str], list[dict[str, Any]], list[bool]]:
    """Load test data from chat-format or unified-format JSONL.

    Returns (user_texts, gold_dicts, is_hard_negative).
    """
    user_texts: list[str] = []
    golds: list[dict[str, Any]] = []
    is_hard_negative: list[bool] = []

    path = Path(test_file)
    if not path.is_file():
        logger.error("Test file not found: %s", path)
        raise FileNotFoundError(f"Test file not found: {path}")

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue

            try:
                obj = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed JSON at line %d: %s", lineno, exc)
                continue

            # Handle chat format
            if "messages" in obj:
                messages = obj["messages"]
                user_content = ""
                assistant_content = "[]"

                for msg in messages:
                    role = msg.get("role", "")
                    if role == "user":
                        user_content = msg.get("content", "")
                    elif role == "assistant":
                        assistant_content = msg.get("content", "[]")

                try:
                    entities_raw = json.loads(assistant_content)
                    if not isinstance(entities_raw, list):
                        entities_raw = []
                except (json.JSONDecodeError, TypeError):
                    entities_raw = []

                text = user_content
                entities = entities_raw

            # Handle unified format
            elif "text" in obj:
                text = obj["text"]
                raw_entities = obj.get("entities", [])
                # Normalize to compact format
                entities = []
                for ent in raw_entities:
                    entities.append({
                        "t": ent.get("t") or ent.get("text", ""),
                        "y": ent.get("y") or ent.get("type", ""),
                        "s": ent.get("s") if "s" in ent else ent.get("start", 0),
                        "e": ent.get("e") if "e" in ent else ent.get("end", 0),
                    })
            else:
                continue

            gold_dict = {"text": text, "entities": entities}
            user_texts.append(text)
            golds.append(gold_dict)

            # Detect hard negatives
            source = obj.get("_source", "")
            is_hn = source == "hard_negatives" or (
                source == "" and len(entities) == 0
            )
            is_hard_negative.append(is_hn)

    logger.info(
        "Loaded %d examples (%d hard negatives) from %s",
        len(user_texts), sum(is_hard_negative), test_file,
    )
    return user_texts, golds, is_hard_negative


def run_ner_evaluation(
    model_path: str,
    test_file: str,
    output_path: str = "output/ner_eval_results.json",
    device: str | None = None,
) -> EvalReport:
    """Run full NER evaluation pipeline.

    1. Load test data
    2. Run NERInferenceEngine.predict() on each text
    3. Convert predictions to JSON strings for metrics.evaluate()
    4. Compute entity-level exact/partial F1
    5. Benchmark latency
    6. Save results
    """
    from inference.inference import NERInferenceEngine

    # Load test data
    user_texts, golds, is_hard_negative = _load_test_data(test_file)

    # Initialize NER engine
    logger.info("Loading NER model from %s", model_path)
    engine = NERInferenceEngine(model_path, device=device)

    # Run inference with latency tracking
    predictions_json: list[str] = []
    latencies: list[float] = []

    total = len(user_texts)
    for idx, text in enumerate(user_texts):
        t0 = time.time()
        entities = engine.predict(text)
        elapsed_ms = (time.time() - t0) * 1000.0

        # Convert to JSON string for metrics.evaluate()
        pred_json = json.dumps(entities, ensure_ascii=False, separators=(",", ":"))
        predictions_json.append(pred_json)
        latencies.append(elapsed_ms)

        if (idx + 1) % 100 == 0 or (idx + 1) == total:
            avg_ms = sum(latencies) / len(latencies)
            logger.info("Progress: %d/%d (%.1f ms avg)", idx + 1, total, avg_ms)

    # Evaluate using existing metrics framework
    report = evaluate(predictions_json, golds, is_hard_negative)

    # Latency stats
    latency_stats = _compute_latency_stats(latencies)

    # Print results
    _print_results(report, latency_stats)

    # Save results
    _save_results(report, latency_stats, output_path, model_path)

    return report


def _compute_latency_stats(latencies: list[float]) -> dict[str, float]:
    if not latencies:
        return {}
    sorted_lat = sorted(latencies)
    n = len(sorted_lat)
    return {
        "mean_ms": sum(sorted_lat) / n,
        "median_ms": sorted_lat[n // 2],
        "p50_ms": sorted_lat[int(n * 0.50)],
        "p95_ms": sorted_lat[int(n * 0.95)],
        "p99_ms": sorted_lat[int(n * 0.99)],
        "min_ms": sorted_lat[0],
        "max_ms": sorted_lat[-1],
    }


def _print_results(report: EvalReport, latency_stats: dict[str, float]) -> None:
    print()
    print("=" * 70)
    print("  NER EVALUATION RESULTS")
    print("=" * 70)

    print(f"\n  {'':20s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'Support':>10s}")
    print(f"  {'-' * 62}")
    print(f"  {'Exact Match':20s} {report.exact_match.precision:>10.4f} "
          f"{report.exact_match.recall:>10.4f} {report.exact_match.f1:>10.4f} "
          f"{report.exact_match.support:>10d}")
    print(f"  {'Partial Match':20s} {report.partial_match.precision:>10.4f} "
          f"{report.partial_match.recall:>10.4f} {report.partial_match.f1:>10.4f} "
          f"{report.partial_match.support:>10d}")

    print(f"\n  Per-type (exact match):")
    print(f"  {'Type':>8s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'Support':>10s}")
    print(f"  {'-' * 50}")
    for t, res in sorted(report.per_type.items()):
        print(f"  {t:>8s} {res.precision:>10.4f} {res.recall:>10.4f} "
              f"{res.f1:>10.4f} {res.support:>10d}")

    print(f"\n  JSON validity rate:        {report.json_validity_rate:.2%}")
    print(f"  FP rate (hard negatives):  {report.fp_rate_hard_negatives:.2%}")
    print(f"  Total predictions:         {report.total_predictions}")
    print(f"  Total gold entities:       {report.total_gold}")
    print(f"  Total examples:            {report.total_examples}")

    if latency_stats:
        print(f"\n  Latency (ms) — single forward pass:")
        for k, v in latency_stats.items():
            print(f"    {k:15s}: {v:8.1f}")

    print("=" * 70)
    print()


def _save_results(
    report: EvalReport,
    latency_stats: dict[str, float],
    output_path: str,
    model_path: str,
) -> None:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    result = {
        "model": model_path,
        "approach": "ner_token_classification",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metrics": report.to_dict(),
        "latency": latency_stats,
    }

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", out)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate NER model for Privacy Shield PII detection."
    )
    parser.add_argument(
        "--model-path", type=str, required=True,
        help="Path to the trained NER model directory",
    )
    parser.add_argument(
        "--test-file", type=str, default="data/final/test.jsonl",
        help="Path to test JSONL file (default: data/final/test.jsonl)",
    )
    parser.add_argument(
        "--output", type=str, default="output/ner_eval_results.json",
        help="Output path for results JSON (default: output/ner_eval_results.json)",
    )
    parser.add_argument(
        "--device", type=str, default=None,
        help="Device for inference (default: auto-detect cuda/cpu)",
    )
    args = parser.parse_args()

    run_ner_evaluation(
        model_path=args.model_path,
        test_file=args.test_file,
        output_path=args.output,
        device=args.device,
    )


if __name__ == "__main__":
    main()
