"""Generate a Markdown evaluation report from eval and latency results.

Reads ``eval_results.json`` and ``latency_report.json``, then produces
a human-readable Markdown report with pass/fail verdicts against
predefined target thresholds.

Usage:
    python -m eval.report
    python -m eval.report --eval-results output/eval_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from dataset.entity_types import PS_TYPES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("report")


# ---------------------------------------------------------------------------
# Target thresholds
# ---------------------------------------------------------------------------

TARGETS = {
    "exact_f1": 0.85,
    "partial_f1": 0.90,
    "precision": 0.90,
    "recall": 0.80,
    "fp_rate_hard_negatives": 0.05,  # must be BELOW this
    "json_validity_rate": 0.99,  # must be ABOVE this
    "latency_mean_ms": 400.0,  # must be BELOW this
    "latency_p99_ms": 800.0,  # must be BELOW this
}


def _pass_fail(value: float, threshold: float, higher_is_better: bool) -> str:
    """Return PASS/FAIL marker."""
    if higher_is_better:
        return "PASS" if value >= threshold else "FAIL"
    return "PASS" if value <= threshold else "FAIL"


# ---------------------------------------------------------------------------
# Report sections
# ---------------------------------------------------------------------------

def _section_summary(
    metrics: dict[str, Any],
    latency: dict[str, Any] | None,
) -> str:
    """Build the summary section with pass/fail verdicts."""
    exact = metrics.get("exact_match", {})
    partial = metrics.get("partial_match", {})
    fp_rate = metrics.get("fp_rate_hard_negatives", 1.0)
    json_rate = metrics.get("json_validity_rate", 0.0)

    lat_mean = 0.0
    lat_p99 = 0.0
    if latency:
        overall = latency.get("overall", {})
        lat_mean = overall.get("mean_ms", 0.0)
        lat_p99 = overall.get("p99_ms", 0.0)

    rows = [
        ("Exact F1", exact.get("f1", 0), TARGETS["exact_f1"], True),
        ("Partial F1", partial.get("f1", 0), TARGETS["partial_f1"], True),
        ("Precision (exact)", exact.get("precision", 0), TARGETS["precision"], True),
        ("Recall (exact)", exact.get("recall", 0), TARGETS["recall"], True),
        ("FP rate (hard neg)", fp_rate, TARGETS["fp_rate_hard_negatives"], False),
        ("JSON validity", json_rate, TARGETS["json_validity_rate"], True),
    ]

    if latency:
        rows.append(("Latency Mean", lat_mean, TARGETS["latency_mean_ms"], False))
        rows.append(("Latency P99", lat_p99, TARGETS["latency_p99_ms"], False))

    lines = [
        "## Summary",
        "",
        "| Metric | Value | Target | Status |",
        "|--------|------:|-------:|--------|",
    ]

    all_pass = True
    for name, value, target, higher_better in rows:
        status = _pass_fail(value, target, higher_better)
        if status == "FAIL":
            all_pass = False

        if name in ("FP rate (hard neg)",):
            val_str = f"{value:.2%}"
            tgt_str = f"< {target:.0%}"
        elif name == "JSON validity":
            val_str = f"{value:.2%}"
            tgt_str = f">= {target:.0%}"
        elif name == "Latency P95":
            val_str = f"{value:.0f} ms"
            tgt_str = f"< {target:.0f} ms"
        else:
            val_str = f"{value:.4f}"
            tgt_str = f">= {target:.2f}"

        lines.append(f"| {name} | {val_str} | {tgt_str} | {status} |")

    verdict = "ALL TARGETS MET" if all_pass else "SOME TARGETS MISSED"
    lines.extend(["", f"**Overall verdict: {verdict}**", ""])
    return "\n".join(lines)


def _section_targets() -> str:
    """Render the target thresholds reference."""
    lines = [
        "## Target Thresholds",
        "",
        "| Metric | Threshold |",
        "|--------|-----------|",
        f"| Exact F1 | >= {TARGETS['exact_f1']:.2f} |",
        f"| Partial F1 | >= {TARGETS['partial_f1']:.2f} |",
        f"| Precision | >= {TARGETS['precision']:.2f} |",
        f"| Recall | >= {TARGETS['recall']:.2f} |",
        f"| FP rate (hard negatives) | < {TARGETS['fp_rate_hard_negatives']:.0%} |",
        f"| JSON validity | > {TARGETS['json_validity_rate']:.0%} |",
        f"| Latency P95 | < {TARGETS['latency_p95_ms']:.0f} ms |",
        "",
    ]
    return "\n".join(lines)


def _section_overall(metrics: dict[str, Any]) -> str:
    """Overall exact + partial match table."""
    exact = metrics.get("exact_match", {})
    partial = metrics.get("partial_match", {})

    lines = [
        "## Overall Metrics",
        "",
        "| Match Type | Precision | Recall | F1 | Support |",
        "|------------|----------:|-------:|---:|--------:|",
        (
            f"| Exact | {exact.get('precision', 0):.4f} | "
            f"{exact.get('recall', 0):.4f} | "
            f"{exact.get('f1', 0):.4f} | "
            f"{exact.get('support', 0)} |"
        ),
        (
            f"| Partial | {partial.get('precision', 0):.4f} | "
            f"{partial.get('recall', 0):.4f} | "
            f"{partial.get('f1', 0):.4f} | "
            f"{partial.get('support', 0)} |"
        ),
        "",
        f"- Total predictions: {metrics.get('total_predictions', 0)}",
        f"- Total gold entities: {metrics.get('total_gold', 0)}",
        f"- Total examples: {metrics.get('total_examples', 0)}",
        "",
    ]
    return "\n".join(lines)


def _section_per_type(metrics: dict[str, Any]) -> str:
    """Per-type precision/recall/F1 table."""
    per_type = metrics.get("per_type", {})

    lines = [
        "## Per-Type Metrics (Exact Match)",
        "",
        "| Type | Full Name | Precision | Recall | F1 | Support |",
        "|------|-----------|----------:|-------:|---:|--------:|",
    ]

    for code in sorted(per_type.keys()):
        res = per_type[code]
        full_name = PS_TYPES.get(code, code)
        lines.append(
            f"| {code} | {full_name} | "
            f"{res.get('precision', 0):.4f} | "
            f"{res.get('recall', 0):.4f} | "
            f"{res.get('f1', 0):.4f} | "
            f"{res.get('support', 0)} |"
        )

    lines.append("")
    return "\n".join(lines)


def _section_confusion(metrics: dict[str, Any]) -> str:
    """Render confusion matrix as markdown table."""
    cm = metrics.get("confusion_matrix", {})
    if not cm:
        return "## Confusion Matrix\n\nNo data available.\n"

    # Collect all labels
    all_labels: set[str] = set()
    for gt, preds in cm.items():
        all_labels.add(gt)
        all_labels.update(preds.keys())
    labels = sorted(all_labels)

    lines = [
        "## Confusion Matrix",
        "",
        "Rows = gold type, columns = predicted type.",
        "",
    ]

    # Header
    header = "| Gold \\ Pred | " + " | ".join(labels) + " |"
    separator = "|" + "---|" * (len(labels) + 1)
    lines.append(header)
    lines.append(separator)

    # Rows
    for gt in labels:
        if gt not in cm:
            cells = ["0"] * len(labels)
        else:
            cells = [str(cm[gt].get(lbl, 0)) for lbl in labels]
        lines.append(f"| {gt} | " + " | ".join(cells) + " |")

    lines.append("")
    return "\n".join(lines)


def _section_hard_negatives(metrics: dict[str, Any]) -> str:
    """Hard negatives analysis."""
    fp_rate = metrics.get("fp_rate_hard_negatives", 0.0)
    status = _pass_fail(fp_rate, TARGETS["fp_rate_hard_negatives"], higher_is_better=False)

    lines = [
        "## Hard Negatives Analysis",
        "",
        f"- FP rate on hard negatives: **{fp_rate:.2%}** ({status})",
        f"- Target: < {TARGETS['fp_rate_hard_negatives']:.0%}",
        f"- JSON validity rate: {metrics.get('json_validity_rate', 0):.2%}",
        "",
        "Hard negatives are inputs with no PII entities. A false positive",
        "on a hard negative means the model predicted entities where none exist.",
        "",
    ]
    return "\n".join(lines)


def _section_latency(latency: dict[str, Any] | None) -> str:
    """Latency distribution section."""
    if not latency:
        return "## Latency Distribution\n\nNo latency data available.\n"

    overall = latency.get("overall", {})
    per_bucket = latency.get("per_bucket", {})

    lines = [
        "## Latency Distribution",
        "",
        "| Metric | Value |",
        "|--------|------:|",
        f"| Mean | {overall.get('mean_ms', 0):.1f} ms |",
        f"| Median | {overall.get('median_ms', 0):.1f} ms |",
        f"| P75 | {overall.get('p75_ms', 0):.1f} ms |",
        f"| P95 | {overall.get('p95_ms', 0):.1f} ms |",
        f"| P99 | {overall.get('p99_ms', 0):.1f} ms |",
        f"| Min | {overall.get('min_ms', 0):.1f} ms |",
        f"| Max | {overall.get('max_ms', 0):.1f} ms |",
        f"| Output tokens/s | {overall.get('output_tokens_per_second', 0):.1f} |",
        "",
    ]

    if per_bucket:
        lines.extend([
            "### By Input Length",
            "",
            "| Bucket | Count | Mean (ms) | Median (ms) | P95 (ms) |",
            "|--------|------:|----------:|------------:|---------:|",
        ])
        for bucket_name, bstats in per_bucket.items():
            lines.append(
                f"| {bucket_name} | {bstats.get('count', 0)} | "
                f"{bstats.get('mean_ms', 0):.1f} | "
                f"{bstats.get('median_ms', 0):.1f} | "
                f"{bstats.get('p95_ms', 0):.1f} |"
            )
        lines.append("")

    return "\n".join(lines)


def _section_quantization_comparison(eval_data: dict[str, Any]) -> str:
    """Compare multiple quantization results side-by-side."""
    results = eval_data.get("results", {})
    if len(results) <= 1:
        return ""

    lines = [
        "## Quantization Comparison",
        "",
        "| Quantization | Exact F1 | Partial F1 | Precision | Recall | JSON Valid | FP Rate |",
        "|--------------|--------:|----------:|----------:|-------:|-----------:|--------:|",
    ]

    for quant_name, entry in sorted(results.items()):
        m = entry.get("metrics", {})
        exact = m.get("exact_match", {})
        partial = m.get("partial_match", {})
        lines.append(
            f"| {quant_name} | "
            f"{exact.get('f1', 0):.4f} | "
            f"{partial.get('f1', 0):.4f} | "
            f"{exact.get('precision', 0):.4f} | "
            f"{exact.get('recall', 0):.4f} | "
            f"{m.get('json_validity_rate', 0):.2%} | "
            f"{m.get('fp_rate_hard_negatives', 0):.2%} |"
        )

    # Latency comparison if available
    has_latency = any(
        entry.get("latency") for entry in results.values()
    )
    if has_latency:
        lines.extend([
            "",
            "### Latency by Quantization",
            "",
            "| Quantization | Mean (ms) | P95 (ms) | P99 (ms) |",
            "|--------------|----------:|---------:|---------:|",
        ])
        for quant_name, entry in sorted(results.items()):
            lat = entry.get("latency", {})
            lines.append(
                f"| {quant_name} | "
                f"{lat.get('mean_ms', 0):.1f} | "
                f"{lat.get('p95_ms', 0):.1f} | "
                f"{lat.get('p99_ms', 0):.1f} |"
            )

    lines.append("")
    return "\n".join(lines)


def _section_recommendations(metrics: dict[str, Any], latency: dict[str, Any] | None) -> str:
    """Generate actionable recommendations based on results."""
    exact = metrics.get("exact_match", {})
    partial = metrics.get("partial_match", {})
    per_type = metrics.get("per_type", {})
    fp_rate = metrics.get("fp_rate_hard_negatives", 0.0)
    json_rate = metrics.get("json_validity_rate", 0.0)

    recs: list[str] = []

    # F1 recommendations
    if exact.get("f1", 0) < TARGETS["exact_f1"]:
        gap = TARGETS["exact_f1"] - exact.get("f1", 0)
        recs.append(
            f"- **Exact F1 below target** (gap: {gap:.3f}). "
            "Consider increasing training data for underperforming types "
            "or extending training epochs."
        )

    if partial.get("f1", 0) < TARGETS["partial_f1"]:
        recs.append(
            "- **Partial F1 below target**. Model may struggle with span "
            "boundary precision. Consider boundary-aware augmentation."
        )

    # Precision vs recall imbalance
    if exact.get("precision", 0) > 0 and exact.get("recall", 0) > 0:
        pr_ratio = exact["precision"] / exact["recall"]
        if pr_ratio > 1.3:
            recs.append(
                "- **Precision >> Recall**: Model is conservative. "
                "Increase training data diversity or lower decision threshold."
            )
        elif pr_ratio < 0.7:
            recs.append(
                "- **Recall >> Precision**: Model over-predicts. "
                "Add more hard negatives to training data."
            )

    # Per-type weaknesses
    weak_types = [
        (code, res.get("f1", 0))
        for code, res in per_type.items()
        if res.get("f1", 0) < 0.70 and res.get("support", 0) >= 5
    ]
    if weak_types:
        weak_str = ", ".join(f"{code} (F1={f1:.2f})" for code, f1 in weak_types)
        recs.append(
            f"- **Weak entity types**: {weak_str}. "
            "Target these types with additional training examples."
        )

    # Hard negatives
    if fp_rate > TARGETS["fp_rate_hard_negatives"]:
        recs.append(
            f"- **High FP rate on hard negatives** ({fp_rate:.1%}). "
            "Increase the proportion of hard negatives in training data "
            "(target: 10-15% of total examples)."
        )

    # JSON validity
    if json_rate < TARGETS["json_validity_rate"]:
        recs.append(
            f"- **JSON validity below target** ({json_rate:.1%}). "
            "Check for truncation issues (increase max_tokens) or "
            "add more format-enforcement examples to training."
        )

    # Latency
    if latency:
        p95 = latency.get("overall", {}).get("p95_ms", 0)
        if p95 > TARGETS["latency_p95_ms"]:
            recs.append(
                f"- **Latency P95 above target** ({p95:.0f} ms > "
                f"{TARGETS['latency_p95_ms']:.0f} ms). "
                "Consider a more aggressive quantization or reducing "
                "context window size."
            )

    if not recs:
        recs.append("- All targets met. Model is ready for deployment.")

    lines = ["## Recommendations", ""] + recs + [""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Report assembly
# ---------------------------------------------------------------------------

def generate_report(
    eval_path: str,
    latency_path: str | None,
    output_path: str,
) -> str:
    """Generate the full Markdown report and write it to disk.

    Returns the report content.
    """
    # Load eval results
    eval_file = Path(eval_path)
    if not eval_file.is_file():
        logger.error("Eval results not found: %s", eval_file)
        sys.exit(1)

    with open(eval_file, "r", encoding="utf-8") as fh:
        eval_data = json.load(fh)

    # Pick the first (or only) result set for the main report
    results = eval_data.get("results", {})
    if not results:
        logger.error("No results found in %s", eval_file)
        sys.exit(1)

    first_key = next(iter(results))
    entry = results[first_key]
    metrics = entry.get("metrics", {})
    model_name = entry.get("model", "unknown")
    quant = entry.get("quantization", first_key)

    # Load latency results (optional)
    latency: dict[str, Any] | None = None
    if latency_path:
        latency_file = Path(latency_path)
        if latency_file.is_file():
            with open(latency_file, "r", encoding="utf-8") as fh:
                latency = json.load(fh)
        else:
            logger.warning("Latency file not found: %s (skipping)", latency_file)

    # Build report
    sections = [
        f"# Privacy Shield SLM - Evaluation Report",
        "",
        f"**Model**: {model_name}",
        f"**Quantization**: {quant}",
        f"**Date**: {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        "---",
        "",
        _section_summary(metrics, latency),
        _section_targets(),
        _section_overall(metrics),
        _section_per_type(metrics),
        _section_confusion(metrics),
        _section_hard_negatives(metrics),
        _section_latency(latency),
        _section_quantization_comparison(eval_data),
        _section_recommendations(metrics, latency),
        "---",
        "",
        f"*Report generated by `eval.report` on {time.strftime('%Y-%m-%d %H:%M:%S')}*",
        "",
    ]

    report = "\n".join(sections)

    # Write output
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(report)
    logger.info("Report written to %s", out)

    return report


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Markdown evaluation report for Privacy Shield SLM."
    )
    parser.add_argument(
        "--eval-results",
        type=str,
        default="output/eval_results.json",
        help="Path to eval_results.json (default: output/eval_results.json)",
    )
    parser.add_argument(
        "--latency-results",
        type=str,
        default="output/latency_report.json",
        help="Path to latency_report.json (default: output/latency_report.json)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/evaluation_report.md",
        help="Output path for the report (default: output/evaluation_report.md)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    report = generate_report(
        eval_path=args.eval_results,
        latency_path=args.latency_results,
        output_path=args.output,
    )

    # Print a preview
    lines = report.split("\n")
    preview = "\n".join(lines[:40])
    print(preview)
    if len(lines) > 40:
        print(f"\n... ({len(lines) - 40} more lines)")

    logger.info("Done.")


if __name__ == "__main__":
    main()
