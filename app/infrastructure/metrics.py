"""
PrivacyShieldMetrics — simple in-memory counters and histograms for observability.

Design rationale: avoids heavy dependencies (prometheus_client, statsd) and emits
all data via structured logging. Counters and histograms are thread-safe under
Python's GIL and reset on process restart (intentional — ephemeral microservice).

Exported via GET /metrics as a JSON snapshot.

IMPORTANT: NEVER record PII values, token content, or org-specific text here.
Only counts, durations, and categorical labels are safe to emit.
"""
from __future__ import annotations

import math
import threading
import time
from typing import Any


class _Counter:
  """Lock-protected integer counter with optional label bucketing."""

  def __init__(self) -> None:
    self._lock = threading.Lock()
    self._total: int = 0
    self._by_label: dict[str, int] = {}

  def increment(self, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with self._lock:
      self._total += 1
      self._by_label[key] = self._by_label.get(key, 0) + 1

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      return {
        "total": self._total,
        "by_label": dict(self._by_label),
      }


_HISTOGRAM_MAX_SAMPLES = 10_000


class _Histogram:
  """
  Lock-protected histogram tracking sum, count, min, max, and p50/p99 buckets.

  Uses a ring buffer capped at _HISTOGRAM_MAX_SAMPLES entries to prevent
  unbounded memory growth in long-running processes. When the buffer is
  full, the oldest sample is overwritten (index wraps modulo capacity).
  Per-label lists use the same cap.
  """

  def __init__(self) -> None:
    self._lock = threading.Lock()
    self._samples: list[float] = []
    self._cursor: int = 0
    self._full: bool = False
    self._by_label: dict[str, list[float]] = {}
    self._by_label_cursor: dict[str, int] = {}
    self._by_label_full: dict[str, bool] = {}

  def _ring_append(self, ring: list[float], value: float, cursor: int, full: bool) -> tuple[int, bool]:
    """Append value to a ring buffer, returning the updated (cursor, full) state."""
    if not full and len(ring) < _HISTOGRAM_MAX_SAMPLES:
      ring.append(value)
      cursor = len(ring) % _HISTOGRAM_MAX_SAMPLES
      if len(ring) == _HISTOGRAM_MAX_SAMPLES:
        full = True
    else:
      ring[cursor % _HISTOGRAM_MAX_SAMPLES] = value
      cursor = (cursor + 1) % _HISTOGRAM_MAX_SAMPLES
      full = True
    return cursor, full

  def observe(self, value: float, labels: dict[str, str] | None = None) -> None:
    key = _label_key(labels)
    with self._lock:
      self._cursor, self._full = self._ring_append(
        self._samples, value, self._cursor, self._full
      )
      if key not in self._by_label:
        self._by_label[key] = []
        self._by_label_cursor[key] = 0
        self._by_label_full[key] = False
      c, f = self._ring_append(
        self._by_label[key],
        value,
        self._by_label_cursor[key],
        self._by_label_full[key],
      )
      self._by_label_cursor[key] = c
      self._by_label_full[key] = f

  def snapshot(self) -> dict[str, Any]:
    with self._lock:
      overall = _summarise(self._samples)
      by_label: dict[str, dict[str, float]] = {
        label: _summarise(samples)
        for label, samples in self._by_label.items()
      }
      return {**overall, "by_label": by_label}


def _label_key(labels: dict[str, str] | None) -> str:
  """Convert a label dict to a stable string key, or 'all' for None."""
  if not labels:
    return "all"
  return ",".join(f"{k}={v}" for k, v in sorted(labels.items()))


def _summarise(samples: list[float]) -> dict[str, float]:
  """Compute descriptive statistics over a list of floats."""
  if not samples:
    return {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p99": 0.0}
  sorted_s = sorted(samples)
  count = len(sorted_s)
  return {
    "count": count,
    "sum": round(sum(sorted_s), 3),
    "min": round(sorted_s[0], 3),
    "max": round(sorted_s[-1], 3),
    "p50": round(_percentile(sorted_s, 50), 3),
    "p99": round(_percentile(sorted_s, 99), 3),
  }


def _percentile(sorted_samples: list[float], p: float) -> float:
  """Nearest-rank percentile over a pre-sorted list."""
  if not sorted_samples:
    return 0.0
  idx = math.ceil(p / 100.0 * len(sorted_samples)) - 1
  return sorted_samples[max(0, min(idx, len(sorted_samples) - 1))]


class PrivacyShieldMetrics:
  """
  Singleton-safe in-memory metrics store for the Privacy Shield microservice.

  All metric names use the 'ps_' prefix to avoid collision with infrastructure metrics.

  Tracked metrics:
    ps_tokenizations_total   — counter (label: source=regex|slm)
    ps_tokens_created        — counter (label: type=pe|org|loc|...)
    ps_latency_ms            — histogram (label: operation=tokenize|rehydrate|flush)
    ps_failures_total        — counter (label: reason=timeout|slm_error|redis_error)
    ps_flush_total           — counter (label: status=success|fallback_ttl)
    ps_dek_rotations_total   — counter (label: none)
    ps_health_checks_total   — counter (label: status=healthy|degraded|unhealthy)
    ps_auth_failures_total   — counter (label: reason=invalid_key|revoked_key|rate_limited|admin_rate_limited|admin_invalid)
  """

  def __init__(self) -> None:
    self._counters: dict[str, _Counter] = {}
    self._histograms: dict[str, _Histogram] = {}
    self._started_at = time.time()
    self._lock = threading.Lock()

    for name in (
      "ps_tokenizations_total",
      "ps_tokens_created",
      "ps_failures_total",
      "ps_flush_total",
      "ps_dek_rotations_total",
      "ps_health_checks_total",
      "ps_auth_failures_total",
    ):
      self._get_or_create_counter(name)

    for name in ("ps_latency_ms",):
      self._get_or_create_histogram(name)

  def increment(self, name: str, labels: dict[str, str] | None = None) -> None:
    """Increment a named counter, optionally bucketed by labels."""
    self._get_or_create_counter(name).increment(labels)

  def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
    """Record one observation for a named histogram."""
    self._get_or_create_histogram(name).observe(value, labels)

  def snapshot(self) -> dict[str, Any]:
    """
    Return a JSON-serialisable snapshot of all counters and histograms.

    Safe to call at any frequency — takes brief locks per metric.
    """
    counters: dict[str, Any] = {}
    for name, counter in self._counters.items():
      counters[name] = counter.snapshot()

    histograms: dict[str, Any] = {}
    for name, hist in self._histograms.items():
      histograms[name] = hist.snapshot()

    return {
      "uptime_seconds": round(time.time() - self._started_at, 1),
      "counters": counters,
      "histograms": histograms,
    }

  def record_tokenization(self, source: str, token_types: list[str]) -> None:
    """
    Record one tokenization call and all token types produced.

    Args:
        source: Detection source: 'regex' or 'slm'.
        token_types: List of pii_type codes produced (e.g. ['pe', 'cf', 'ib']).
    """
    self.increment("ps_tokenizations_total", {"source": source})
    # Count total tokens WITHOUT type label to prevent PII type distribution
    # leakage. An attacker with metrics access could infer what kinds of PII
    # an org processes (e.g. "10 CF + 5 IBAN" reveals financial activity).
    for _ in token_types:
      self.increment("ps_tokens_created")

  def record_latency(self, operation: str, duration_ms: float) -> None:
    """Record operation latency in milliseconds."""
    self.observe("ps_latency_ms", duration_ms, {"operation": operation})

  def record_failure(self, reason: str) -> None:
    """
    Record an operation failure.

    Args:
        reason: One of 'timeout', 'slm_error', 'redis_error', 'crypto_error'.
    """
    self.increment("ps_failures_total", {"reason": reason})

  def record_flush(self, status: str) -> None:
    """
    Record a flush outcome.

    Args:
        status: 'success' or 'fallback_ttl' (flush skipped, relying on TTL expiry).
    """
    self.increment("ps_flush_total", {"status": status})

  def record_dek_rotation(self) -> None:
    """Record a successful DEK rotation."""
    self.increment("ps_dek_rotations_total")

  def record_health_check(self, status: str) -> None:
    """
    Record a health check result.

    Args:
        status: 'healthy', 'degraded', or 'unhealthy'.
    """
    self.increment("ps_health_checks_total", {"status": status})

  def _get_or_create_counter(self, name: str) -> _Counter:
    with self._lock:
      if name not in self._counters:
        self._counters[name] = _Counter()
      return self._counters[name]

  def _get_or_create_histogram(self, name: str) -> _Histogram:
    with self._lock:
      if name not in self._histograms:
        self._histograms[name] = _Histogram()
      return self._histograms[name]
