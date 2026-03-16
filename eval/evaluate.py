"""Run entity-level evaluation against a llama.cpp server.

Loads a test JSONL file, sends each example to a running (or freshly
started) llama-server, collects predictions, and computes precision /
recall / F1 at both exact and partial match levels.

Usage:
    python -m eval.evaluate --model output/gguf/model-Q4_K_M.gguf
    python -m eval.evaluate --server-already-running --port 11434
    python -m eval.evaluate --model output/gguf/model-Q4_K_M.gguf --quantizations Q4_K_M,Q5_K_M
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

from dataset.entity_types import SYSTEM_PROMPT
from eval.metrics import evaluate, EvalReport

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("evaluate")


# ---------------------------------------------------------------------------
# Server management
# ---------------------------------------------------------------------------

def _start_server(
    model_path: str,
    port: int,
    llama_cpp_dir: str | None,
    ctx_size: int = 1024,
    n_predict: int = 256,
    threads: int = 2,
) -> subprocess.Popen:
    """Start a llama-server process and return the Popen handle."""
    if llama_cpp_dir:
        server_bin = os.path.join(llama_cpp_dir, "llama-server")
    else:
        server_bin = "llama-server"

    cmd = [
        server_bin,
        "--model", model_path,
        "--ctx-size", str(ctx_size),
        "--n-predict", str(n_predict),
        "--threads", str(threads),
        "--port", str(port),
    ]

    logger.info("Starting llama-server: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return proc


def _wait_for_server(port: int, timeout: float = 60.0) -> bool:
    """Poll /health until the server is ready or timeout expires."""
    url = f"http://localhost:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=2)
            if resp.status_code == 200:
                logger.info("Server ready on port %d", port)
                return True
        except requests.ConnectionError:
            pass
        time.sleep(1.0)
    logger.error("Server did not become ready within %.0fs", timeout)
    return False


def _stop_server(proc: subprocess.Popen) -> None:
    """Gracefully terminate the server process."""
    logger.info("Stopping llama-server (pid %d)...", proc.pid)
    proc.send_signal(signal.SIGTERM)
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("Server did not stop; sending SIGKILL")
        proc.kill()
        proc.wait(timeout=5)


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def _load_test_data(
    test_file: str,
) -> tuple[list[str], list[dict[str, Any]], list[bool]]:
    """Load test.jsonl and return (user_texts, gold_dicts, is_hard_negative).

    Each JSONL line is expected to have the ChatML structure::

        {
            "messages": [
                {"role": "system", "content": "..."},
                {"role": "user", "content": "<the text>"},
                {"role": "assistant", "content": "[{\"t\":...,\"y\":...,\"s\":...,\"e\":...}]"}
            ]
        }

    Gold labels are parsed from the assistant content.  A line is marked
    as a hard negative if the assistant content is ``"[]"``.
    """
    user_texts: list[str] = []
    golds: list[dict[str, Any]] = []
    is_hard_negative: list[bool] = []

    path = Path(test_file)
    if not path.is_file():
        logger.error("Test file not found: %s", path)
        sys.exit(1)

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

            messages = obj.get("messages", [])
            user_content = ""
            assistant_content = "[]"

            for msg in messages:
                role = msg.get("role", "")
                if role == "user":
                    user_content = msg.get("content", "")
                elif role == "assistant":
                    assistant_content = msg.get("content", "[]")

            # Parse gold entities from assistant content
            try:
                entities_raw = json.loads(assistant_content)
            except json.JSONDecodeError:
                entities_raw = []

            if not isinstance(entities_raw, list):
                entities_raw = []

            gold_dict = {
                "text": user_content,
                "entities": entities_raw,
            }

            user_texts.append(user_content)
            golds.append(gold_dict)
            example_source = example.get("_source", "")
            is_hn = example_source == "hard_negative" or (
                example_source == "" and len(entities_raw) == 0
            )
            is_hard_negative.append(is_hn)

    logger.info(
        "Loaded %d examples from %s (%d hard negatives)",
        len(user_texts),
        test_file,
        sum(is_hard_negative),
    )
    return user_texts, golds, is_hard_negative


# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def _run_inference(
    user_texts: list[str],
    port: int,
) -> tuple[list[str], list[float]]:
    """Send each text to the llama-server and collect predictions + latencies.

    Returns (predictions, latencies_ms).
    """
    url = f"http://localhost:{port}/v1/chat/completions"
    predictions: list[str] = []
    latencies: list[float] = []

    total = len(user_texts)
    for idx, text in enumerate(user_texts):
        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "temperature": 0.0,
            "max_tokens": 256,
            "stop": ["\n\n"],
        }

        t0 = time.time()
        try:
            resp = requests.post(url, json=payload, timeout=30)
            resp.raise_for_status()
            elapsed_ms = (time.time() - t0) * 1000.0
            result = resp.json()
            content = (
                result.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "[]")
            )
        except (requests.RequestException, KeyError, IndexError) as exc:
            elapsed_ms = (time.time() - t0) * 1000.0
            logger.warning("Request %d/%d failed: %s", idx + 1, total, exc)
            content = ""

        predictions.append(content)
        latencies.append(elapsed_ms)

        if (idx + 1) % 50 == 0 or (idx + 1) == total:
            logger.info("Progress: %d/%d (%.0f ms avg)", idx + 1, total,
                        sum(latencies) / len(latencies))

    return predictions, latencies


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _compute_latency_stats(latencies: list[float]) -> dict[str, float]:
    """Compute latency statistics in milliseconds."""
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
    """Print a formatted results table."""
    try:
        from tabulate import tabulate
    except ImportError:
        tabulate = None

    print()
    print("=" * 70)
    print("  EVALUATION RESULTS")
    print("=" * 70)

    # Overall metrics
    overall_rows = [
        ["Exact Match", f"{report.exact_match.precision:.4f}",
         f"{report.exact_match.recall:.4f}", f"{report.exact_match.f1:.4f}",
         str(report.exact_match.support)],
        ["Partial Match", f"{report.partial_match.precision:.4f}",
         f"{report.partial_match.recall:.4f}", f"{report.partial_match.f1:.4f}",
         str(report.partial_match.support)],
    ]
    headers = ["", "Precision", "Recall", "F1", "Support"]

    if tabulate:
        print(tabulate(overall_rows, headers=headers, tablefmt="grid"))
    else:
        print(f"{'':20s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'Support':>10s}")
        print("-" * 62)
        for row in overall_rows:
            print(f"{row[0]:20s} {row[1]:>10s} {row[2]:>10s} {row[3]:>10s} {row[4]:>10s}")

    # Per-type metrics
    print()
    print("Per-type (exact match):")
    type_rows = []
    for t, res in sorted(report.per_type.items()):
        type_rows.append([
            t, f"{res.precision:.4f}", f"{res.recall:.4f}",
            f"{res.f1:.4f}", str(res.support),
        ])

    if tabulate:
        print(tabulate(type_rows, headers=["Type", "Precision", "Recall", "F1", "Support"],
                        tablefmt="grid"))
    else:
        print(f"{'Type':>8s} {'Precision':>10s} {'Recall':>10s} {'F1':>10s} {'Support':>10s}")
        print("-" * 50)
        for row in type_rows:
            print(f"{row[0]:>8s} {row[1]:>10s} {row[2]:>10s} {row[3]:>10s} {row[4]:>10s}")

    # Quality indicators
    print()
    print(f"JSON validity rate:        {report.json_validity_rate:.2%}")
    print(f"FP rate (hard negatives):  {report.fp_rate_hard_negatives:.2%}")
    print(f"Total predictions:         {report.total_predictions}")
    print(f"Total gold entities:       {report.total_gold}")
    print(f"Total examples:            {report.total_examples}")

    # Latency
    if latency_stats:
        print()
        print("Latency (ms):")
        for k, v in latency_stats.items():
            print(f"  {k:15s}: {v:8.1f}")

    print("=" * 70)
    print()


def _save_results(
    report: EvalReport,
    latency_stats: dict[str, float],
    output_path: str,
    model_name: str,
    quantization: str | None = None,
) -> None:
    """Save full evaluation results to JSON."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Load existing results for multi-quantization comparison
    existing: dict[str, Any] = {}
    if out.is_file():
        try:
            with open(out, "r", encoding="utf-8") as fh:
                existing = json.load(fh)
        except (json.JSONDecodeError, OSError):
            existing = {}

    result_key = quantization or "default"
    result_entry = {
        "model": model_name,
        "quantization": quantization,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "metrics": report.to_dict(),
        "latency": latency_stats,
    }

    if "results" not in existing:
        existing["results"] = {}
    existing["results"][result_key] = result_entry

    with open(out, "w", encoding="utf-8") as fh:
        json.dump(existing, fh, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s (key: %s)", out, result_key)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate Privacy Shield SLM against a llama.cpp server."
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Path to GGUF model file (required unless --server-already-running)",
    )
    parser.add_argument(
        "--test-file",
        type=str,
        default="data/final/test.jsonl",
        help="Path to test JSONL file (default: data/final/test.jsonl)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=11434,
        help="Port for llama-server (default: 11434)",
    )
    parser.add_argument(
        "--llama-cpp-dir",
        type=str,
        default=None,
        help="Directory containing llama-server binary (default: use PATH)",
    )
    parser.add_argument(
        "--server-already-running",
        action="store_true",
        help="Skip server startup; assume it is already running",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/eval_results.json",
        help="Output path for results JSON (default: output/eval_results.json)",
    )
    parser.add_argument(
        "--quantizations",
        type=str,
        default="Q4_K_M",
        help="Comma-separated quantization names to evaluate (default: Q4_K_M)",
    )
    return parser.parse_args()


def run_single_evaluation(
    model_path: str | None,
    test_file: str,
    port: int,
    llama_cpp_dir: str | None,
    server_already_running: bool,
    output_path: str,
    quantization: str | None = None,
) -> EvalReport:
    """Run a full evaluation cycle for one model / quantization."""
    server_proc: subprocess.Popen | None = None

    try:
        # Start server if needed
        if not server_already_running:
            if not model_path:
                logger.error("--model is required when not using --server-already-running")
                sys.exit(1)
            server_proc = _start_server(model_path, port, llama_cpp_dir)
            if not _wait_for_server(port):
                logger.error("Aborting: server did not start")
                sys.exit(1)

        # Load data
        user_texts, golds, is_hard_negative = _load_test_data(test_file)

        # Inference
        predictions, latencies = _run_inference(user_texts, port)

        # Evaluate
        report = evaluate(predictions, golds, is_hard_negative)
        latency_stats = _compute_latency_stats(latencies)

        # Report
        _print_results(report, latency_stats)
        _save_results(
            report, latency_stats, output_path,
            model_name=model_path or "external",
            quantization=quantization,
        )

        return report

    finally:
        if server_proc is not None:
            _stop_server(server_proc)


def main() -> None:
    args = parse_args()

    quants = [q.strip() for q in args.quantizations.split(",")]

    for quant in quants:
        logger.info("=" * 60)
        logger.info("Evaluating quantization: %s", quant)
        logger.info("=" * 60)

        # Resolve model path for this quantization
        model_path = args.model
        if model_path and len(quants) > 1:
            # Try to find the quantization-specific GGUF
            model_dir = Path(model_path).parent
            base_stem = Path(model_path).stem.rsplit("-", 1)[0]
            quant_model = model_dir / f"{base_stem}-{quant}.gguf"
            if quant_model.is_file():
                model_path = str(quant_model)
                logger.info("Using model: %s", model_path)
            else:
                logger.warning(
                    "Quantization-specific model not found: %s, using %s",
                    quant_model, model_path,
                )

        run_single_evaluation(
            model_path=model_path,
            test_file=args.test_file,
            port=args.port,
            llama_cpp_dir=args.llama_cpp_dir,
            server_already_running=args.server_already_running,
            output_path=args.output,
            quantization=quant,
        )

    logger.info("All evaluations complete.")


if __name__ == "__main__":
    main()
