"""Benchmark span_fusion and aggregation strategies on the test set.

Runs inference with all combinations of:
- span_fusion: on / off
- aggregation_strategy: first / average / max

Produces:
1. Comparison table (exact F1 overall, per pe, per ind, partial F1, FP rate, total preds)
2. 20 diff examples (before→after span_fusion), including successes and failures

Usage:
    python -m eval.benchmark_fusion --model-path /content/ner_mix_clean --test-file data/mix_clean/test.jsonl
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any

from eval.metrics import evaluate, EvalReport, parse_predictions

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("benchmark_fusion")


def _load_test_data(test_file: str) -> tuple[list[str], list[dict[str, Any]], list[bool]]:
    """Load test data, return (texts, gold_dicts, is_hard_negative)."""
    user_texts: list[str] = []
    golds: list[dict[str, Any]] = []
    is_hard_negative: list[bool] = []

    with open(test_file, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)

            if "messages" in obj:
                text = ""
                entities = []
                for msg in obj["messages"]:
                    if msg.get("role") == "user":
                        text = msg.get("content", "")
                    elif msg.get("role") == "assistant":
                        try:
                            entities = json.loads(msg.get("content", "[]"))
                        except (json.JSONDecodeError, TypeError):
                            entities = []
            elif "text" in obj:
                text = obj["text"]
                raw = obj.get("entities", [])
                entities = []
                for e in raw:
                    entities.append({
                        "t": e.get("t") or e.get("text", ""),
                        "y": e.get("y") or e.get("type", ""),
                        "s": e.get("s") if "s" in e else e.get("start", 0),
                        "e": e.get("e") if "e" in e else e.get("end", 0),
                    })
            else:
                continue

            gold_dict = {"text": text, "entities": entities}
            user_texts.append(text)
            golds.append(gold_dict)

            source = obj.get("_source", "")
            is_hn = source == "hard_negatives" or (source == "" and len(entities) == 0)
            is_hard_negative.append(is_hn)

    return user_texts, golds, is_hard_negative


def _run_config(
    model_path: str,
    texts: list[str],
    golds: list[dict],
    is_hn: list[bool],
    aggregation: str,
    fusion: bool,
    device: str | None,
) -> tuple[EvalReport, list[str]]:
    """Run inference with a given config and return (report, predictions_json)."""
    from inference.inference import NERInferenceEngine

    engine = NERInferenceEngine(
        model_path,
        device=device,
        aggregation_strategy=aggregation,
        use_span_fusion=fusion,
    )

    predictions_json: list[str] = []
    for text in texts:
        entities = engine.predict(text)
        pred_json = json.dumps(entities, ensure_ascii=False, separators=(",", ":"))
        predictions_json.append(pred_json)

    report = evaluate(predictions_json, golds, is_hn)
    return report, predictions_json


def _extract_per_type_f1(report: EvalReport, type_code: str) -> float:
    if type_code in report.per_type:
        return report.per_type[type_code].f1
    return 0.0


def _collect_diffs(
    texts: list[str],
    golds: list[dict],
    preds_before: list[str],
    preds_after: list[str],
    max_diffs: int = 20,
) -> list[dict]:
    """Find examples where fusion changed the prediction, categorize as success/failure."""
    diffs: list[dict] = []

    for i, (text, gold, before_json, after_json) in enumerate(
        zip(texts, golds, preds_before, preds_after)
    ):
        if before_json == after_json:
            continue

        before_ents = parse_predictions(before_json) or []
        after_ents = parse_predictions(after_json) or []

        gold_ents = gold.get("entities", [])
        gold_set = set()
        for g in gold_ents:
            gt = g.get("t") or g.get("text", "")
            gy = g.get("y") or g.get("type", "")
            gs = g.get("s") if "s" in g else g.get("start", 0)
            ge = g.get("e") if "e" in g else g.get("end", 0)
            gold_set.add((gy, gs, ge))

        # Count exact matches before and after
        before_matches = sum(1 for e in before_ents if (e.type, e.start, e.end) in gold_set)
        after_matches = sum(1 for e in after_ents if (e.type, e.start, e.end) in gold_set)

        if after_matches > before_matches:
            verdict = "SUCCESS"
        elif after_matches < before_matches:
            verdict = "REGRESSION"
        else:
            verdict = "NEUTRAL"

        diffs.append({
            "idx": i,
            "text": text[:120] + ("..." if len(text) > 120 else ""),
            "gold": [(g.get("y") or g.get("type", ""), g.get("t") or g.get("text", "")) for g in gold_ents],
            "before": [(e.type, e.text) for e in before_ents],
            "after": [(e.type, e.text) for e in after_ents],
            "before_exact": before_matches,
            "after_exact": after_matches,
            "verdict": verdict,
        })

        if len(diffs) >= max_diffs:
            break

    return diffs


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark span_fusion and aggregation strategies.")
    parser.add_argument("--model-path", type=str, required=True)
    parser.add_argument("--test-file", type=str, default="data/mix_clean/test.jsonl")
    parser.add_argument("--device", type=str, default=None)
    parser.add_argument("--output", type=str, default="output/benchmark_fusion.json")
    args = parser.parse_args()

    texts, golds, is_hn = _load_test_data(args.test_file)
    logger.info("Loaded %d examples (%d hard negatives)", len(texts), sum(is_hn))

    # Run all configurations
    configs = [
        ("first", False, "baseline"),
        ("first", True, "first+fusion"),
        ("average", True, "average+fusion"),
        ("max", True, "max+fusion"),
    ]

    results: dict[str, dict] = {}
    preds_by_config: dict[str, list[str]] = {}

    for agg, fusion, label in configs:
        logger.info("Running: %s (aggregation=%s, fusion=%s)", label, agg, fusion)
        t0 = time.time()
        report, preds = _run_config(
            args.model_path, texts, golds, is_hn, agg, fusion, args.device,
        )
        elapsed = time.time() - t0
        preds_by_config[label] = preds

        results[label] = {
            "exact_f1": report.exact_match.f1,
            "exact_f1_pe": _extract_per_type_f1(report, "pe"),
            "exact_f1_ind": _extract_per_type_f1(report, "ind"),
            "partial_f1": report.partial_match.f1,
            "fp_rate_hn": report.fp_rate_hard_negatives,
            "total_preds": report.total_predictions,
            "total_gold": report.total_gold,
            "elapsed_s": round(elapsed, 1),
        }

    # Print comparison table
    print("\n" + "=" * 100)
    print("  BENCHMARK: Span Fusion & Aggregation Strategy")
    print("=" * 100)
    print(f"\n  {'Config':<20s} {'Exact F1':>10s} {'PE F1':>10s} {'IND F1':>10s} "
          f"{'Partial F1':>10s} {'FP Rate':>10s} {'#Preds':>10s} {'Time':>8s}")
    print(f"  {'-' * 90}")

    for label in [c[2] for c in configs]:
        r = results[label]
        print(f"  {label:<20s} {r['exact_f1']:>10.4f} {r['exact_f1_pe']:>10.4f} "
              f"{r['exact_f1_ind']:>10.4f} {r['partial_f1']:>10.4f} "
              f"{r['fp_rate_hn']:>10.4f} {r['total_preds']:>10d} {r['elapsed_s']:>7.1f}s")

    # Collect and print diffs (baseline vs first+fusion)
    diffs = _collect_diffs(
        texts, golds,
        preds_by_config["baseline"],
        preds_by_config["first+fusion"],
        max_diffs=20,
    )

    success_count = sum(1 for d in diffs if d["verdict"] == "SUCCESS")
    regression_count = sum(1 for d in diffs if d["verdict"] == "REGRESSION")
    neutral_count = sum(1 for d in diffs if d["verdict"] == "NEUTRAL")

    print(f"\n{'=' * 100}")
    print(f"  DIFF ANALYSIS: baseline → first+fusion ({len(diffs)} changed examples)")
    print(f"  Successes: {success_count}, Regressions: {regression_count}, Neutral: {neutral_count}")
    print(f"{'=' * 100}")

    for d in diffs:
        print(f"\n  [{d['verdict']}] Example #{d['idx']} (exact: {d['before_exact']}→{d['after_exact']})")
        print(f"    Text: {d['text']}")
        print(f"    Gold:   {d['gold']}")
        print(f"    Before: {d['before']}")
        print(f"    After:  {d['after']}")

    # Save results
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({
            "results": results,
            "diffs_summary": {
                "total_changed": len(diffs),
                "successes": success_count,
                "regressions": regression_count,
                "neutral": neutral_count,
            },
            "diffs": diffs,
        }, fh, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", out)

    print(f"\n{'=' * 100}")


if __name__ == "__main__":
    main()
