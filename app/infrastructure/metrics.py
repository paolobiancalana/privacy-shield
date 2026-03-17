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
_PROM_BUCKETS = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]


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


def _label_key_to_prometheus(label_key: str) -> str:
  """
  Convert an internal label key (e.g. 'source=regex') to Prometheus
  label string format (e.g. 'source="regex"').

  Handles multiple labels separated by commas.
  """
  parts = []
  for pair in label_key.split(","):
    k, _, v = pair.partition("=")
    parts.append(f'{k}="{v}"')
  return ",".join(parts)


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
      "ps_monthly_quota_exceeded_total",
      "ps_plan_changes_total",
      "ps_max_keys_exceeded_total",
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

  def to_prometheus(self) -> str:
    """
    Emit all metrics in Prometheus text exposition format 0.0.4.

    Bucket boundaries for histograms: 10, 25, 50, 100, 250, 500, 1000, +Inf ms.

    GDPR safety: NEVER includes org_id, key_id, IP addresses, or PII.
    """
    lines: list[str] = []

    # ── Counters ──────────────────────────────────────────────────
    for name, counter in self._counters.items():
      snap = counter.snapshot()
      lines.append(f"# TYPE {name} counter")
      by_label: dict[str, int] = snap["by_label"]
      if not by_label or (len(by_label) == 1 and "all" in by_label):
        lines.append(f"{name} {by_label.get('all', 0)}")
      else:
        for label_key, count in by_label.items():
          if label_key == "all":
            lines.append(f"{name} {count}")
          else:
            label_str = _label_key_to_prometheus(label_key)
            lines.append(f"{name}{{{label_str}}} {count}")

    # ── Histograms ─────────────────────────────────────────────────
    for name, hist in self._histograms.items():
      lines.append(f"# TYPE {name} histogram")
      with hist._lock:
        all_samples = list(hist._samples)
        by_label = {k: list(v) for k, v in hist._by_label.items()}
      if not by_label:
        by_label = {"all": all_samples}
      for label_key, samples in by_label.items():
        label_str = ""
        if label_key != "all":
          label_str = _label_key_to_prometheus(label_key)

        total_count = len(samples)
        total_sum = sum(samples)

        for bound in _PROM_BUCKETS:
          bucket_count = sum(1 for s in samples if s <= bound)
          le_label = f'le="{int(bound) if bound == int(bound) else bound}"'
          if label_str:
            lines.append(
              f"{name}_bucket{{{label_str},{le_label}}} {bucket_count}"
            )
          else:
            lines.append(f"{name}_bucket{{{le_label}}} {bucket_count}")

        inf_label = 'le="+Inf"'
        if label_str:
          lines.append(
            f"{name}_bucket{{{label_str},{inf_label}}} {total_count}"
          )
        else:
          lines.append(f"{name}_bucket{{{inf_label}}} {total_count}")

        if label_str:
          lines.append(f"{name}_count{{{label_str}}} {total_count}")
          lines.append(
            f"{name}_sum{{{label_str}}} {round(total_sum, 3)}"
          )
        else:
          lines.append(f"{name}_count {total_count}")
          lines.append(f"{name}_sum {round(total_sum, 3)}")

    # ── Uptime gauge ───────────────────────────────────────────────
    lines.append("# TYPE ps_uptime_seconds gauge")
    lines.append(f"ps_uptime_seconds {round(time.time() - self._started_at, 1)}")

    return "\n".join(lines) + "\n"

  def record_monthly_quota_exceeded(self, plan_id: str) -> None:
    """
    Record a monthly token quota breach.

    Args:
        plan_id: The plan that was exhausted (e.g. 'starter', 'business').
    """
    self.increment("ps_monthly_quota_exceeded_total", {"plan_id": plan_id})

  def record_plan_change(self, from_plan: str, to_plan: str) -> None:
    """
    Record an org plan assignment change.

    Args:
        from_plan: Previous plan_id.
        to_plan: New plan_id.
    """
    self.increment("ps_plan_changes_total", {"from_plan": from_plan, "to_plan": to_plan})

  def record_max_keys_exceeded(self, plan_id: str) -> None:
    """
    Record a rejected key creation due to plan max_keys enforcement.

    Args:
        plan_id: The plan whose key limit was hit.
    """
    self.increment("ps_max_keys_exceeded_total", {"plan_id": plan_id})

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
