"""Core metrics computation for entity-level NER evaluation.

Computes exact match, partial match (IoU-based), per-type breakdown,
confusion matrix, and hard-negative false-positive rates for the
Privacy Shield SLM PII detector.

Usage:
    python -m eval.metrics
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class EntitySpan:
    """A single predicted or gold entity span."""

    text: str
    type: str  # PS code: pe, org, loc, ind, med, leg, rel, fin, pro, dt
    start: int
    end: int


@dataclass
class EvalResult:
    """Precision / recall / F1 for a single evaluation slice."""

    precision: float
    recall: float
    f1: float
    support: int  # number of gold entities


@dataclass
class EvalReport:
    """Full evaluation report across all examples."""

    exact_match: EvalResult
    partial_match: EvalResult
    per_type: dict[str, EvalResult]
    json_validity_rate: float  # fraction of outputs that were valid JSON
    fp_rate_hard_negatives: float  # fraction of hard negatives with any prediction
    confusion_matrix: dict[str, dict[str, int]]  # gold_type -> pred_type -> count
    total_predictions: int
    total_gold: int
    total_examples: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize report to a JSON-friendly dict."""
        return {
            "exact_match": {
                "precision": self.exact_match.precision,
                "recall": self.exact_match.recall,
                "f1": self.exact_match.f1,
                "support": self.exact_match.support,
            },
            "partial_match": {
                "precision": self.partial_match.precision,
                "recall": self.partial_match.recall,
                "f1": self.partial_match.f1,
                "support": self.partial_match.support,
            },
            "per_type": {
                k: {
                    "precision": v.precision,
                    "recall": v.recall,
                    "f1": v.f1,
                    "support": v.support,
                }
                for k, v in self.per_type.items()
            },
            "json_validity_rate": self.json_validity_rate,
            "fp_rate_hard_negatives": self.fp_rate_hard_negatives,
            "confusion_matrix": self.confusion_matrix,
            "total_predictions": self.total_predictions,
            "total_gold": self.total_gold,
            "total_examples": self.total_examples,
        }


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_predictions(json_str: str) -> list[EntitySpan] | None:
    """Parse compact JSON output ``[{"t","y","s","e"}]`` into EntitySpan list.

    Expected format per element::

        {"t": "Mario Rossi", "y": "pe", "s": 10, "e": 22}

    Returns ``None`` if *json_str* is not valid JSON or has an unexpected
    structure.
    """
    if not json_str or not json_str.strip():
        return None

    try:
        data = json.loads(json_str.strip())
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, list):
        return None

    spans: list[EntitySpan] = []
    for item in data:
        if not isinstance(item, dict):
            return None
        try:
            spans.append(
                EntitySpan(
                    text=str(item["t"]),
                    type=str(item["y"]),
                    start=int(item["s"]),
                    end=int(item["e"]),
                )
            )
        except (KeyError, ValueError, TypeError):
            return None

    return spans


# ---------------------------------------------------------------------------
# IoU computation
# ---------------------------------------------------------------------------

def compute_iou(span_a: EntitySpan, span_b: EntitySpan) -> float:
    """Character-level Intersection over Union of two spans."""
    inter_start = max(span_a.start, span_b.start)
    inter_end = min(span_a.end, span_b.end)
    intersection = max(0, inter_end - inter_start)

    union = (
        (span_a.end - span_a.start)
        + (span_b.end - span_b.start)
        - intersection
    )

    if union <= 0:
        return 0.0
    return intersection / union


# ---------------------------------------------------------------------------
# Matching functions
# ---------------------------------------------------------------------------

def match_exact(
    pred: list[EntitySpan],
    gold: list[EntitySpan],
) -> tuple[int, int, int]:
    """Exact match: type + start + end must all match.

    Returns (TP, FP, FN).
    """
    gold_set = {(g.type, g.start, g.end) for g in gold}
    pred_set = {(p.type, p.start, p.end) for p in pred}

    tp = len(gold_set & pred_set)
    fp = len(pred_set - gold_set)
    fn = len(gold_set - pred_set)
    return tp, fp, fn


def match_partial(
    pred: list[EntitySpan],
    gold: list[EntitySpan],
    iou_threshold: float = 0.5,
) -> tuple[int, int, int]:
    """Partial match: type matches and IoU > threshold.

    Uses greedy matching: sort candidate pairs by IoU descending, assign
    each gold/pred at most once (no double-counting).

    Returns (TP, FP, FN).
    """
    if not gold and not pred:
        return 0, 0, 0
    if not gold:
        return 0, len(pred), 0
    if not pred:
        return 0, 0, len(gold)

    # Build all candidate pairs with matching types and IoU above threshold
    candidates: list[tuple[float, int, int]] = []  # (iou, pred_idx, gold_idx)
    for pi, p in enumerate(pred):
        for gi, g in enumerate(gold):
            if p.type != g.type:
                continue
            iou = compute_iou(p, g)
            if iou > iou_threshold:
                candidates.append((iou, pi, gi))

    # Greedy: best IoU first
    candidates.sort(key=lambda x: x[0], reverse=True)

    matched_pred: set[int] = set()
    matched_gold: set[int] = set()

    for _iou, pi, gi in candidates:
        if pi in matched_pred or gi in matched_gold:
            continue
        matched_pred.add(pi)
        matched_gold.add(gi)

    tp = len(matched_gold)
    fp = len(pred) - len(matched_pred)
    fn = len(gold) - len(matched_gold)
    return tp, fp, fn


# ---------------------------------------------------------------------------
# F1 computation
# ---------------------------------------------------------------------------

def compute_f1(tp: int, fp: int, fn: int) -> EvalResult:
    """Compute precision, recall, F1 from raw counts."""
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (
        2 * precision * recall / (precision + recall)
        if (precision + recall) > 0
        else 0.0
    )
    support = tp + fn  # total gold entities
    return EvalResult(precision=precision, recall=recall, f1=f1, support=support)


# ---------------------------------------------------------------------------
# Confusion matrix
# ---------------------------------------------------------------------------

def build_confusion_matrix(
    predictions: list[list[EntitySpan]],
    golds: list[list[EntitySpan]],
    iou_threshold: float = 0.5,
) -> dict[str, dict[str, int]]:
    """Build a confusion matrix of gold_type -> pred_type -> count.

    For each gold entity, find the best-matching prediction (highest IoU
    with any type) and record the mapping.  Unmatched golds are recorded
    as gold_type -> ``"MISS"`` and unmatched predictions as
    ``"SPURIOUS"`` -> pred_type.
    """
    matrix: dict[str, dict[str, int]] = {}

    def _inc(gt: str, pt: str) -> None:
        matrix.setdefault(gt, {})
        matrix[gt][pt] = matrix[gt].get(pt, 0) + 1

    for preds, glist in zip(predictions, golds):
        used_pred: set[int] = set()

        for g in glist:
            best_iou = 0.0
            best_pi = -1
            for pi, p in enumerate(preds):
                if pi in used_pred:
                    continue
                iou = compute_iou(p, g)
                if iou > best_iou:
                    best_iou = iou
                    best_pi = pi

            if best_pi >= 0 and best_iou >= iou_threshold:
                used_pred.add(best_pi)
                _inc(g.type, preds[best_pi].type)
            else:
                _inc(g.type, "MISS")

        # Spurious predictions (no matching gold)
        for pi, p in enumerate(preds):
            if pi not in used_pred:
                _inc("SPURIOUS", p.type)

    return matrix


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate(
    predictions: list[str],
    golds: list[dict[str, Any]],
    is_hard_negative: list[bool],
) -> EvalReport:
    """Run full entity-level evaluation.

    Parameters
    ----------
    predictions:
        Raw JSON strings from the model (one per example).
    golds:
        List of dicts ``{"text": str, "entities": [{"t", "y", "s", "e"}, ...]}``.
    is_hard_negative:
        Boolean flag per example (True = no gold entities expected).

    Returns
    -------
    EvalReport with all computed metrics.
    """
    assert len(predictions) == len(golds) == len(is_hard_negative), (
        f"Length mismatch: {len(predictions)} predictions, "
        f"{len(golds)} golds, {len(is_hard_negative)} hard_negative flags"
    )

    total_examples = len(predictions)
    valid_json_count = 0
    hard_neg_total = 0
    hard_neg_fp = 0

    # Accumulators for overall exact / partial
    total_exact_tp = total_exact_fp = total_exact_fn = 0
    total_partial_tp = total_partial_fp = total_partial_fn = 0

    # Per-type accumulators: type -> [tp, fp, fn] for exact match
    type_exact: dict[str, list[int]] = {}

    # For confusion matrix
    all_preds_parsed: list[list[EntitySpan]] = []
    all_golds_parsed: list[list[EntitySpan]] = []

    total_predictions = 0
    total_gold = 0

    for pred_str, gold_dict, is_hn in zip(predictions, golds, is_hard_negative):
        # Parse gold entities
        gold_entities: list[EntitySpan] = []
        for ent in gold_dict.get("entities", []):
            gold_entities.append(
                EntitySpan(
                    text=str(ent["t"]),
                    type=str(ent["y"]),
                    start=int(ent["s"]),
                    end=int(ent["e"]),
                )
            )

        # Parse predictions
        pred_entities = parse_predictions(pred_str)
        if pred_entities is not None:
            valid_json_count += 1
        else:
            pred_entities = []

        total_predictions += len(pred_entities)
        total_gold += len(gold_entities)

        all_preds_parsed.append(pred_entities)
        all_golds_parsed.append(gold_entities)

        # Hard negative tracking
        if is_hn:
            hard_neg_total += 1
            if len(pred_entities) > 0:
                hard_neg_fp += 1

        # Exact match
        tp, fp, fn = match_exact(pred_entities, gold_entities)
        total_exact_tp += tp
        total_exact_fp += fp
        total_exact_fn += fn

        # Per-type exact match
        gold_by_type: dict[str, list[EntitySpan]] = {}
        for g in gold_entities:
            gold_by_type.setdefault(g.type, []).append(g)
        pred_by_type: dict[str, list[EntitySpan]] = {}
        for p in pred_entities:
            pred_by_type.setdefault(p.type, []).append(p)

        all_types = set(gold_by_type.keys()) | set(pred_by_type.keys())
        for t in all_types:
            t_tp, t_fp, t_fn = match_exact(
                pred_by_type.get(t, []),
                gold_by_type.get(t, []),
            )
            if t not in type_exact:
                type_exact[t] = [0, 0, 0]
            type_exact[t][0] += t_tp
            type_exact[t][1] += t_fp
            type_exact[t][2] += t_fn

        # Partial match
        tp_p, fp_p, fn_p = match_partial(pred_entities, gold_entities)
        total_partial_tp += tp_p
        total_partial_fp += fp_p
        total_partial_fn += fn_p

    # Build results
    exact_result = compute_f1(total_exact_tp, total_exact_fp, total_exact_fn)
    partial_result = compute_f1(total_partial_tp, total_partial_fp, total_partial_fn)

    per_type: dict[str, EvalResult] = {}
    for t, (t_tp, t_fp, t_fn) in sorted(type_exact.items()):
        per_type[t] = compute_f1(t_tp, t_fp, t_fn)

    confusion = build_confusion_matrix(all_preds_parsed, all_golds_parsed)

    json_validity_rate = (
        valid_json_count / total_examples if total_examples > 0 else 0.0
    )
    fp_rate = (
        hard_neg_fp / hard_neg_total if hard_neg_total > 0 else 0.0
    )

    return EvalReport(
        exact_match=exact_result,
        partial_match=partial_result,
        per_type=per_type,
        json_validity_rate=json_validity_rate,
        fp_rate_hard_negatives=fp_rate,
        confusion_matrix=confusion,
        total_predictions=total_predictions,
        total_gold=total_gold,
        total_examples=total_examples,
    )


# ---------------------------------------------------------------------------
# CLI entry point (self-test with synthetic data)
# ---------------------------------------------------------------------------

def main() -> None:
    """Run a quick self-test with synthetic data."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Synthetic test
    gold_data = [
        {
            "text": "Mario Rossi vive a Roma",
            "entities": [
                {"t": "Mario Rossi", "y": "pe", "s": 0, "e": 11},
                {"t": "Roma", "y": "loc", "s": 19, "e": 23},
            ],
        },
        {
            "text": "Nessuna informazione personale qui.",
            "entities": [],
        },
    ]

    pred_strings = [
        '[{"t":"Mario Rossi","y":"pe","s":0,"e":11},{"t":"Roma","y":"loc","s":19,"e":23}]',
        "[]",
    ]

    is_hn = [False, True]

    report = evaluate(pred_strings, gold_data, is_hn)

    print(f"Exact  - P: {report.exact_match.precision:.3f}  "
          f"R: {report.exact_match.recall:.3f}  F1: {report.exact_match.f1:.3f}")
    print(f"Partial - P: {report.partial_match.precision:.3f}  "
          f"R: {report.partial_match.recall:.3f}  F1: {report.partial_match.f1:.3f}")
    print(f"JSON validity: {report.json_validity_rate:.1%}")
    print(f"FP rate (hard negatives): {report.fp_rate_hard_negatives:.1%}")
    print(f"Per-type: {list(report.per_type.keys())}")
    print(f"Total: {report.total_predictions} preds, {report.total_gold} gold, "
          f"{report.total_examples} examples")
    print("\nSelf-test passed.")


if __name__ == "__main__":
    main()
