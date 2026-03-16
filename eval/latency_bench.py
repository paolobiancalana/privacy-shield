"""Dedicated latency benchmark for Privacy Shield SLM on llama.cpp.

Generates test inputs of varying lengths, warms up the server, then
runs a configurable number of timed requests to measure per-request
latency distribution and output throughput.

Usage:
    python -m eval.latency_bench --port 11434
    python -m eval.latency_bench --num-requests 200 --warmup 20
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from pathlib import Path
from typing import Any

import requests

from dataset.entity_types import SYSTEM_PROMPT

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("latency_bench")


# ---------------------------------------------------------------------------
# Test input generation
# ---------------------------------------------------------------------------

# Representative Italian text fragments for synthetic inputs
_FRAGMENTS = [
    "Il signor Giovanni Bianchi, residente in Via Roma 42, Milano,",
    "ha presentato domanda di rimborso presso la filiale di Torino.",
    "La paziente Maria Verdi, nata il quindici marzo millenovecentottanta,",
    "si e recata al Policlinico Umberto I per un controllo cardiologico.",
    "L'avvocato Luca Neri dello studio legale Neri & Associati",
    "ha depositato il ricorso presso il Tribunale di Napoli.",
    "La societa Alfa S.r.l., con sede in Piazza Duomo 7, Firenze,",
    "ha comunicato la cessazione dell'attivita commerciale.",
    "Il dipendente Marco Russo, matricola 45892, settore logistica,",
    "e stato trasferito alla sede operativa di Bologna.",
    "La dottoressa Elena Conti ha prescritto una terapia farmacologica",
    "per il paziente affetto da ipertensione arteriosa di grado moderato.",
    "Il contratto stipulato tra le parti prevede un compenso annuale",
    "pari a quarantaduemila euro lordi, con scadenza al trentuno dicembre.",
    "Si comunica che l'assemblea dei soci si terra il prossimo venerdi",
    "presso la sala conferenze dell'Hotel Excelsior, Roma.",
    "Il responsabile della sicurezza ha segnalato un'anomalia",
    "nel sistema di accesso dell'edificio principale.",
    "La pratica numero 2024-7831 relativa al cliente Rossi",
    "e in fase di verifica da parte dell'ufficio competente.",
]


def generate_test_inputs(
    num_inputs: int = 100,
    length_buckets: tuple[int, ...] = (50, 100, 200, 400),
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Generate synthetic test inputs of varying token-approximate lengths.

    Each returned dict has ``{"text": str, "target_tokens": int}``.
    Token count is approximate (word-based heuristic: ~1.3 tokens/word
    for Italian).
    """
    rng = random.Random(seed)
    inputs: list[dict[str, Any]] = []
    per_bucket = num_inputs // len(length_buckets)
    remainder = num_inputs - per_bucket * len(length_buckets)

    for bi, target_tokens in enumerate(length_buckets):
        count = per_bucket + (1 if bi < remainder else 0)
        target_words = int(target_tokens / 1.3)

        for _ in range(count):
            words: list[str] = []
            while len(words) < target_words:
                fragment = rng.choice(_FRAGMENTS)
                words.extend(fragment.split())
            text = " ".join(words[:target_words])
            inputs.append({"text": text, "target_tokens": target_tokens})

    rng.shuffle(inputs)
    return inputs


# ---------------------------------------------------------------------------
# Benchmarking
# ---------------------------------------------------------------------------

def _send_request(text: str, port: int) -> dict[str, float]:
    """Send a single chat completion request and return timing info."""
    url = f"http://localhost:{port}/v1/chat/completions"
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
        result = resp.json()
    except requests.RequestException as exc:
        return {
            "latency_ms": (time.time() - t0) * 1000.0,
            "output_tokens": 0,
            "success": False,
            "error": str(exc),
        }

    latency_ms = (time.time() - t0) * 1000.0

    # Try to extract output token count from usage
    usage = result.get("usage", {})
    output_tokens = usage.get("completion_tokens", 0)

    # Fallback: estimate from content length
    if output_tokens == 0:
        content = (
            result.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )
        output_tokens = max(1, len(content.split()) + len(content) // 4)

    return {
        "latency_ms": latency_ms,
        "output_tokens": output_tokens,
        "success": True,
    }


def run_benchmark(
    inputs: list[dict[str, Any]],
    port: int,
    warmup: int = 10,
    num_requests: int = 100,
) -> list[dict[str, Any]]:
    """Run the latency benchmark.

    Returns a list of per-request result dicts.
    """
    # Warmup
    warmup_inputs = inputs[:warmup] if len(inputs) >= warmup else inputs
    logger.info("Warming up with %d requests...", len(warmup_inputs))
    for i, inp in enumerate(warmup_inputs):
        _send_request(inp["text"], port)
        if (i + 1) % 5 == 0:
            logger.info("  Warmup %d/%d", i + 1, len(warmup_inputs))

    logger.info("Warmup complete. Starting benchmark (%d requests)...", num_requests)

    results: list[dict[str, Any]] = []
    bench_inputs = inputs[warmup:warmup + num_requests] if len(inputs) >= warmup + num_requests else inputs[warmup:]

    for i, inp in enumerate(bench_inputs):
        res = _send_request(inp["text"], port)
        res["target_tokens"] = inp["target_tokens"]
        res["input_text_len"] = len(inp["text"])
        results.append(res)

        if (i + 1) % 25 == 0 or (i + 1) == len(bench_inputs):
            successful = [r for r in results if r.get("success")]
            avg = sum(r["latency_ms"] for r in successful) / len(successful) if successful else 0
            logger.info(
                "  Benchmark %d/%d (avg %.0f ms)",
                i + 1, len(bench_inputs), avg,
            )

    return results


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute the p-th percentile (0-100) from a sorted list."""
    if not sorted_values:
        return 0.0
    idx = int(len(sorted_values) * p / 100.0)
    idx = min(idx, len(sorted_values) - 1)
    return sorted_values[idx]


def compute_stats(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall and per-bucket latency statistics."""
    successful = [r for r in results if r.get("success")]
    failed = len(results) - len(successful)

    if not successful:
        return {"error": "No successful requests", "failed": failed}

    latencies = sorted(r["latency_ms"] for r in successful)
    n = len(latencies)

    total_output_tokens = sum(r["output_tokens"] for r in successful)
    total_time_s = sum(r["latency_ms"] for r in successful) / 1000.0

    overall = {
        "num_requests": n,
        "failed_requests": failed,
        "mean_ms": sum(latencies) / n,
        "median_ms": latencies[n // 2],
        "p50_ms": _percentile(latencies, 50),
        "p75_ms": _percentile(latencies, 75),
        "p95_ms": _percentile(latencies, 95),
        "p99_ms": _percentile(latencies, 99),
        "min_ms": latencies[0],
        "max_ms": latencies[-1],
        "output_tokens_per_second": (
            total_output_tokens / total_time_s if total_time_s > 0 else 0.0
        ),
        "total_output_tokens": total_output_tokens,
    }

    # Per input-length bucket
    buckets: dict[int, list[float]] = {}
    for r in successful:
        bucket = r.get("target_tokens", 0)
        buckets.setdefault(bucket, []).append(r["latency_ms"])

    per_bucket: dict[str, dict[str, float]] = {}
    for bucket, lats in sorted(buckets.items()):
        s = sorted(lats)
        bn = len(s)
        per_bucket[f"{bucket}_tokens"] = {
            "count": bn,
            "mean_ms": sum(s) / bn,
            "median_ms": s[bn // 2],
            "p95_ms": _percentile(s, 95),
            "min_ms": s[0],
            "max_ms": s[-1],
        }

    return {"overall": overall, "per_bucket": per_bucket}


def _print_summary(stats: dict[str, Any]) -> None:
    """Print a formatted summary table."""
    try:
        from tabulate import tabulate
    except ImportError:
        tabulate = None

    overall = stats.get("overall", {})
    per_bucket = stats.get("per_bucket", {})

    print()
    print("=" * 70)
    print("  LATENCY BENCHMARK RESULTS")
    print("=" * 70)

    print()
    print(f"  Successful requests:        {overall.get('num_requests', 0)}")
    print(f"  Failed requests:            {overall.get('failed_requests', 0)}")
    print(f"  Output tokens/sec:          {overall.get('output_tokens_per_second', 0):.1f}")
    print()

    # Overall latency
    overall_rows = [
        ["Mean", f"{overall.get('mean_ms', 0):.1f}"],
        ["Median", f"{overall.get('median_ms', 0):.1f}"],
        ["P50", f"{overall.get('p50_ms', 0):.1f}"],
        ["P75", f"{overall.get('p75_ms', 0):.1f}"],
        ["P95", f"{overall.get('p95_ms', 0):.1f}"],
        ["P99", f"{overall.get('p99_ms', 0):.1f}"],
        ["Min", f"{overall.get('min_ms', 0):.1f}"],
        ["Max", f"{overall.get('max_ms', 0):.1f}"],
    ]

    if tabulate:
        print(tabulate(overall_rows, headers=["Metric", "Latency (ms)"], tablefmt="grid"))
    else:
        print(f"  {'Metric':>10s}  {'Latency (ms)':>12s}")
        print(f"  {'-' * 24}")
        for row in overall_rows:
            print(f"  {row[0]:>10s}  {row[1]:>12s}")

    # Per-bucket
    if per_bucket:
        print()
        print("  Per input-length bucket:")
        bucket_rows = []
        for bucket_name, bstats in per_bucket.items():
            bucket_rows.append([
                bucket_name,
                str(bstats.get("count", 0)),
                f"{bstats.get('mean_ms', 0):.1f}",
                f"{bstats.get('median_ms', 0):.1f}",
                f"{bstats.get('p95_ms', 0):.1f}",
            ])

        if tabulate:
            print(tabulate(
                bucket_rows,
                headers=["Bucket", "Count", "Mean (ms)", "Median (ms)", "P95 (ms)"],
                tablefmt="grid",
            ))
        else:
            print(f"  {'Bucket':>15s} {'Count':>6s} {'Mean':>10s} {'Median':>10s} {'P95':>10s}")
            print(f"  {'-' * 55}")
            for row in bucket_rows:
                print(f"  {row[0]:>15s} {row[1]:>6s} {row[2]:>10s} {row[3]:>10s} {row[4]:>10s}")

    print("=" * 70)
    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Latency benchmark for Privacy Shield SLM on llama.cpp."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=11434,
        help="Port where llama-server is running (default: 11434)",
    )
    parser.add_argument(
        "--num-requests",
        type=int,
        default=100,
        help="Number of benchmark requests (default: 100)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=10,
        help="Number of warmup requests to discard (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="output/latency_report.json",
        help="Output path for results JSON (default: output/latency_report.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    # Check server is reachable
    try:
        resp = requests.get(f"http://localhost:{args.port}/health", timeout=5)
        if resp.status_code != 200:
            logger.error(
                "Server on port %d returned status %d. Is llama-server running?",
                args.port, resp.status_code,
            )
            return
    except requests.ConnectionError:
        logger.error(
            "Cannot connect to localhost:%d. Start llama-server first.",
            args.port,
        )
        return

    logger.info("Server is healthy on port %d", args.port)

    # Generate test inputs
    inputs = generate_test_inputs(
        num_inputs=max(args.num_requests, args.warmup + args.num_requests),
        length_buckets=(50, 100, 200, 400),
    )
    logger.info("Generated %d test inputs", len(inputs))

    # Run benchmark
    results = run_benchmark(
        inputs,
        port=args.port,
        warmup=args.warmup,
        num_requests=args.num_requests,
    )

    # Compute stats
    stats = compute_stats(results)
    stats["config"] = {
        "port": args.port,
        "num_requests": args.num_requests,
        "warmup": args.warmup,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }

    # Print summary
    _print_summary(stats)

    # Save results
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(stats, fh, indent=2, ensure_ascii=False)
    logger.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
