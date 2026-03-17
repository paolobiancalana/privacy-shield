"""
PrivacyShieldMetrics.to_prometheus() — adversarial unit tests.

Adversarial Analysis:
  1. Bucket monotonicity: If histogram buckets are not monotonically non-decreasing,
     Prometheus will reject the scrape. Every observation at boundary B must appear
     in bucket B AND all higher buckets.
  2. +Inf bucket must equal _count: Prometheus spec requires this invariant.
     A mismatch means data corruption or race condition.
  3. Label injection: If label values contain `"` or `}`, the Prometheus output
     becomes unparseable. _label_key_to_prometheus does no escaping.

Boundary Map:
  histogram observations: 0 (empty), 1 (single), 10.0 (exact boundary), 1e6 (above all)
  counter labels: None → no braces, single label → {k="v"}, two labels → {a="1",b="2"}
  uptime_seconds: >= 0.0 (never negative)
"""
from __future__ import annotations

import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.infrastructure.metrics import PrivacyShieldMetrics


# ── Helpers ─────────────────────────────────────────────────────────

_EXPECTED_BUCKETS = [10.0, 25.0, 50.0, 100.0, 250.0, 500.0, 1000.0]

_PROMETHEUS_LINE_RE = re.compile(
    r"^("
    r"# TYPE \w+ (counter|gauge|histogram)"  # TYPE line
    r"|# HELP .+"  # HELP line (optional)
    r"|\w+(\{[^}]*\})? -?\d+(\.\d+)?(e[+-]?\d+)?"  # metric line
    r")$"
)

_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def _parse_metric_lines(output: str) -> list[str]:
    """Return non-comment, non-blank lines from Prometheus output."""
    return [
        line for line in output.strip().splitlines()
        if line and not line.startswith("#")
    ]


def _extract_bucket_counts(output: str, metric_name: str, label_filter: str = "") -> list[int]:
    """
    Extract bucket counts for a specific histogram metric (with optional label filter).
    Returns counts in bucket order (le="10", le="25", ..., le="+Inf").
    """
    counts: list[int] = []
    for line in _parse_metric_lines(output):
        if not line.startswith(f"{metric_name}_bucket"):
            continue
        if label_filter and label_filter not in line:
            continue
        # Extract the numeric value at the end
        value_str = line.rsplit(" ", 1)[-1]
        counts.append(int(value_str))
    return counts


def _extract_metric_value(output: str, metric_name: str, label_filter: str = "") -> float | None:
    """Extract the value of a single metric line."""
    for line in _parse_metric_lines(output):
        if not line.startswith(metric_name):
            continue
        # Avoid matching metric_name_bucket when looking for metric_name_count
        remainder = line[len(metric_name):]
        if remainder and remainder[0] not in (" ", "{"):
            continue
        if label_filter and label_filter not in line:
            continue
        value_str = line.rsplit(" ", 1)[-1]
        return float(value_str)
    return None


# ── Happy Path ──────────────────────────────────────────────────────

class TestPrometheusHappyPath:
    """Valid Prometheus output for normal metric states."""

    def test_fresh_metrics_produces_valid_output(self) -> None:
        """Fresh metrics (never incremented) produce valid Prometheus text with all counters at 0."""
        m = PrivacyShieldMetrics()
        output = m.to_prometheus()

        assert isinstance(output, str)
        assert len(output) > 0
        assert output.endswith("\n")

        # All pre-registered counters should appear with value 0
        for name in (
            "ps_tokenizations_total",
            "ps_tokens_created",
            "ps_failures_total",
            "ps_flush_total",
            "ps_dek_rotations_total",
            "ps_health_checks_total",
            "ps_auth_failures_total",
        ):
            assert f"# TYPE {name} counter" in output, f"Missing TYPE declaration for {name}"
            val = _extract_metric_value(output, name)
            assert val is not None, f"Missing metric line for {name}"
            assert val == 0.0, f"{name} should be 0 on fresh metrics, got {val}"

    def test_uptime_gauge_present_and_nonnegative(self) -> None:
        """Uptime gauge is present, typed as gauge, and non-negative."""
        m = PrivacyShieldMetrics()
        output = m.to_prometheus()

        assert "# TYPE ps_uptime_seconds gauge" in output
        val = _extract_metric_value(output, "ps_uptime_seconds")
        assert val is not None, "ps_uptime_seconds metric line missing"
        assert val >= 0.0, f"Uptime must be non-negative, got {val}"

    def test_counter_with_labels_produces_braces(self) -> None:
        """Counter with labels emits {source="regex"} format."""
        m = PrivacyShieldMetrics()
        m.increment("ps_tokenizations_total", {"source": "regex"})
        m.increment("ps_tokenizations_total", {"source": "regex"})
        m.increment("ps_tokenizations_total", {"source": "slm"})
        output = m.to_prometheus()

        val_regex = _extract_metric_value(output, "ps_tokenizations_total", 'source="regex"')
        assert val_regex == 2.0

        val_slm = _extract_metric_value(output, "ps_tokenizations_total", 'source="slm"')
        assert val_slm == 1.0

    def test_counter_without_labels_no_braces(self) -> None:
        """Counter incremented without labels emits no braces."""
        m = PrivacyShieldMetrics()
        m.increment("ps_dek_rotations_total")
        output = m.to_prometheus()

        # Should have a line like "ps_dek_rotations_total 1" without braces
        lines = _parse_metric_lines(output)
        dek_lines = [l for l in lines if l.startswith("ps_dek_rotations_total")]
        assert len(dek_lines) == 1
        assert "{" not in dek_lines[0], f"Expected no braces, got: {dek_lines[0]}"
        assert dek_lines[0] == "ps_dek_rotations_total 1"

    def test_histogram_with_observations_correct_buckets(self) -> None:
        """Histogram with observations produces correct bucket boundaries and counts."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 5.0, {"operation": "tokenize"})
        m.observe("ps_latency_ms", 50.0, {"operation": "tokenize"})
        m.observe("ps_latency_ms", 200.0, {"operation": "tokenize"})
        output = m.to_prometheus()

        assert "# TYPE ps_latency_ms histogram" in output
        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="tokenize"')

        # 8 buckets: le="10", le="25", le="50", le="100", le="250", le="500", le="1000", le="+Inf"
        assert len(buckets) == 8, f"Expected 8 buckets, got {len(buckets)}: {buckets}"

        # 5.0 <= 10: count=1; 50.0 <= 50: count=2; 200.0 <= 250: count=3
        assert buckets[0] == 1  # le="10": 5.0
        assert buckets[1] == 1  # le="25": 5.0
        assert buckets[2] == 2  # le="50": 5.0, 50.0
        assert buckets[3] == 2  # le="100": 5.0, 50.0
        assert buckets[4] == 3  # le="250": all
        assert buckets[5] == 3  # le="500": all
        assert buckets[6] == 3  # le="1000": all
        assert buckets[7] == 3  # le="+Inf": all

    def test_histogram_count_and_sum(self) -> None:
        """Histogram _count and _sum are correct after observations."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 10.0, {"operation": "flush"})
        m.observe("ps_latency_ms", 20.0, {"operation": "flush"})
        output = m.to_prometheus()

        count_val = _extract_metric_value(output, "ps_latency_ms_count", 'operation="flush"')
        sum_val = _extract_metric_value(output, "ps_latency_ms_sum", 'operation="flush"')

        assert count_val == 2.0
        assert sum_val == 30.0

    def test_multiple_label_sets_produce_separate_bucket_series(self) -> None:
        """Two different label sets on the same histogram produce separate bucket series."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 5.0, {"operation": "tokenize"})
        m.observe("ps_latency_ms", 500.0, {"operation": "rehydrate"})
        output = m.to_prometheus()

        tok_buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="tokenize"')
        reh_buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="rehydrate"')

        assert len(tok_buckets) == 8
        assert len(reh_buckets) == 8

        # tokenize: 5.0 is in all buckets
        assert tok_buckets[0] == 1  # le="10"
        assert tok_buckets[-1] == 1  # le="+Inf"

        # rehydrate: 500.0 is NOT in le="250" but IS in le="500"
        assert reh_buckets[4] == 0  # le="250": 500 > 250
        assert reh_buckets[5] == 1  # le="500": 500 <= 500
        assert reh_buckets[-1] == 1  # le="+Inf"

    def test_counter_incremented_many_times(self) -> None:
        """Counter incremented 1000 times shows correct total."""
        m = PrivacyShieldMetrics()
        for _ in range(1000):
            m.increment("ps_tokens_created")
        output = m.to_prometheus()

        val = _extract_metric_value(output, "ps_tokens_created")
        assert val == 1000.0


# ── Edge Cases (Bucket Boundaries) ─────────────────────────────────

class TestBucketBoundaryEdgeCases:
    """Observation values at exact bucket boundaries and extremes."""

    def test_observation_exactly_on_bucket_boundary(self) -> None:
        """Observation of exactly 10.0 appears in le="10" bucket and all higher buckets."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 10.0, {"operation": "test"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="test"')
        # 10.0 <= 10.0 is True, so it should be in the le="10" bucket
        assert buckets[0] == 1, f"10.0 should be in le=10 bucket, got {buckets[0]}"
        # And in all higher buckets
        for i in range(1, 8):
            assert buckets[i] == 1, f"10.0 should be in bucket {i}, got {buckets[i]}"

    def test_observation_just_above_bucket_boundary(self) -> None:
        """Observation of 10.001 should NOT be in le="10" but should be in le="25"."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 10.001, {"operation": "test"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="test"')
        assert buckets[0] == 0, f"10.001 should NOT be in le=10 bucket, got {buckets[0]}"
        assert buckets[1] == 1, f"10.001 should be in le=25 bucket, got {buckets[1]}"

    def test_very_large_observation_only_in_inf_bucket(self) -> None:
        """Observation of 1e6 should only appear in +Inf bucket."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 1e6, {"operation": "test"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="test"')
        # All finite buckets should be 0
        for i in range(7):
            assert buckets[i] == 0, f"1e6 should NOT be in bucket {i} (le={_EXPECTED_BUCKETS[i]})"
        # +Inf should be 1
        assert buckets[7] == 1, "1e6 should be in +Inf bucket"

    def test_zero_observation_in_all_buckets(self) -> None:
        """Observation of 0.0 should be in all buckets including le="10"."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", 0.0, {"operation": "test"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="test"')
        for i in range(8):
            assert buckets[i] == 1, f"0.0 should be in bucket {i}"

    def test_negative_observation_in_all_buckets(self) -> None:
        """Negative observation should be in all buckets (Prometheus allows negative values)."""
        m = PrivacyShieldMetrics()
        m.observe("ps_latency_ms", -5.0, {"operation": "test"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="test"')
        for i in range(8):
            assert buckets[i] == 1, f"-5.0 should be in bucket {i}"

    def test_empty_histogram_all_zeros(self) -> None:
        """Registered histogram with no observations emits _count 0, _sum 0, all buckets 0."""
        m = PrivacyShieldMetrics()
        # ps_latency_ms is pre-registered
        output = m.to_prometheus()

        assert "# TYPE ps_latency_ms histogram" in output
        count_val = _extract_metric_value(output, "ps_latency_ms_count")
        sum_val = _extract_metric_value(output, "ps_latency_ms_sum")

        assert count_val == 0.0, f"Empty histogram _count should be 0, got {count_val}"
        assert sum_val == 0.0, f"Empty histogram _sum should be 0, got {sum_val}"

        buckets = _extract_bucket_counts(output, "ps_latency_ms")
        for i, c in enumerate(buckets):
            assert c == 0, f"Empty histogram bucket {i} should be 0, got {c}"


# ── Prometheus Spec Compliance ──────────────────────────────────────

class TestPrometheusSpecCompliance:
    """Structural requirements of Prometheus text exposition format 0.0.4."""

    def test_output_lines_are_valid_prometheus_format(self) -> None:
        """Every non-blank line matches Prometheus TYPE/HELP/metric format."""
        m = PrivacyShieldMetrics()
        m.increment("ps_tokenizations_total", {"source": "regex"})
        m.observe("ps_latency_ms", 42.0, {"operation": "tokenize"})
        output = m.to_prometheus()

        for line in output.strip().splitlines():
            if not line:
                continue
            assert _PROMETHEUS_LINE_RE.match(line), (
                f"Line does not match Prometheus format: {line!r}"
            )

    def test_histogram_buckets_monotonically_nondecreasing(self) -> None:
        """Prometheus requires histogram buckets to be monotonically non-decreasing."""
        m = PrivacyShieldMetrics()
        # Mix of observations across different buckets
        for v in [5.0, 15.0, 50.0, 100.0, 300.0, 999.0, 2000.0]:
            m.observe("ps_latency_ms", v, {"operation": "mixed"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="mixed"')
        for i in range(1, len(buckets)):
            assert buckets[i] >= buckets[i - 1], (
                f"Bucket monotonicity violated: bucket[{i - 1}]={buckets[i - 1]} > bucket[{i}]={buckets[i]}"
            )

    def test_inf_bucket_equals_count(self) -> None:
        """+Inf bucket count must equal _count (Prometheus spec invariant)."""
        m = PrivacyShieldMetrics()
        for v in [1.0, 50.0, 999.0, 5000.0]:
            m.observe("ps_latency_ms", v, {"operation": "check"})
        output = m.to_prometheus()

        buckets = _extract_bucket_counts(output, "ps_latency_ms", 'operation="check"')
        inf_count = buckets[-1]

        count_val = _extract_metric_value(output, "ps_latency_ms_count", 'operation="check"')
        assert inf_count == count_val, (
            f"+Inf bucket ({inf_count}) != _count ({count_val}) — Prometheus spec violation"
        )

    def test_output_ends_with_newline(self) -> None:
        """Prometheus text format must end with a newline."""
        m = PrivacyShieldMetrics()
        output = m.to_prometheus()
        assert output.endswith("\n"), "Prometheus output must end with newline"

    def test_no_trailing_whitespace_on_metric_lines(self) -> None:
        """Metric lines should not have trailing whitespace."""
        m = PrivacyShieldMetrics()
        m.increment("ps_tokens_created")
        output = m.to_prometheus()

        for line in output.strip().splitlines():
            if not line:
                continue
            assert line == line.rstrip(), f"Trailing whitespace on line: {line!r}"


# ── No PII in Output ───────────────────────────────────────────────

class TestNoPiiInPrometheusOutput:
    """Prometheus output must never contain PII, org IDs, or sensitive data."""

    def test_no_uuid_patterns_in_output(self) -> None:
        """No UUID-like patterns should appear in Prometheus output."""
        m = PrivacyShieldMetrics()
        # Simulate real usage
        m.record_tokenization("regex", ["pe", "cf", "ib"])
        m.record_latency("tokenize", 15.5)
        m.record_failure("timeout")
        m.record_flush("success")
        m.record_health_check("healthy")
        output = m.to_prometheus()

        assert not _UUID_RE.search(output), (
            f"UUID pattern found in Prometheus output: {_UUID_RE.search(output).group()}"  # type: ignore[union-attr]
        )

    def test_no_email_patterns_in_output(self) -> None:
        """No email-like patterns should appear in Prometheus output."""
        m = PrivacyShieldMetrics()
        m.record_tokenization("regex", ["pe", "email"])
        output = m.to_prometheus()

        assert not _EMAIL_RE.search(output), "Email pattern found in Prometheus output"

    def test_no_org_id_string_in_output(self) -> None:
        """The literal string 'org_id' should not appear in Prometheus output."""
        m = PrivacyShieldMetrics()
        m.record_tokenization("regex", ["pe"])
        output = m.to_prometheus()

        assert "org_id" not in output.lower(), "'org_id' found in Prometheus output"


# ── Thread Safety ───────────────────────────────────────────────────

class TestPrometheusThreadSafety:
    """Concurrent observe() + to_prometheus() must not crash."""

    def test_concurrent_observe_and_to_prometheus(self) -> None:
        """Concurrent observe + to_prometheus from multiple threads produces no exceptions."""
        m = PrivacyShieldMetrics()
        errors: list[Exception] = []
        stop = threading.Event()

        def observer():
            i = 0
            while not stop.is_set():
                m.observe("ps_latency_ms", float(i % 2000), {"operation": "tokenize"})
                m.increment("ps_tokenizations_total", {"source": "regex"})
                i += 1

        def reader():
            while not stop.is_set():
                try:
                    output = m.to_prometheus()
                    # Basic sanity: must be a non-empty string
                    assert isinstance(output, str)
                    assert len(output) > 0
                except Exception as e:
                    errors.append(e)

        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=observer))
        for _ in range(2):
            threads.append(threading.Thread(target=reader))

        for t in threads:
            t.start()

        time.sleep(0.3)
        stop.set()

        for t in threads:
            t.join(timeout=5.0)

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_concurrent_to_prometheus_never_crashes(self) -> None:
        """50 concurrent to_prometheus() calls while incrementing do not crash."""
        m = PrivacyShieldMetrics()
        for _ in range(100):
            m.increment("ps_tokenizations_total", {"source": "regex"})
            m.observe("ps_latency_ms", 42.0, {"operation": "tokenize"})

        errors: list[Exception] = []

        def call_prometheus():
            try:
                result = m.to_prometheus()
                assert "ps_tokenizations_total" in result
            except Exception as e:
                errors.append(e)

        with ThreadPoolExecutor(max_workers=20) as pool:
            futures = [pool.submit(call_prometheus) for _ in range(50)]
            for f in futures:
                f.result()

        assert len(errors) == 0, f"Concurrent to_prometheus errors: {errors}"


# ── Label Edge Cases ────────────────────────────────────────────────

class TestLabelEdgeCases:
    """Label formatting edge cases in Prometheus output."""

    def test_multiple_labels_formatted_correctly(self) -> None:
        """Counter with two labels produces comma-separated {a="1",b="2"} format."""
        m = PrivacyShieldMetrics()
        m.increment("ps_failures_total", {"reason": "timeout", "source": "api"})
        output = m.to_prometheus()

        # Labels should be sorted by key (from _label_key)
        lines = _parse_metric_lines(output)
        failure_lines = [l for l in lines if l.startswith("ps_failures_total{")]
        assert len(failure_lines) >= 1
        # The label_key sorts keys, so "reason" before "source"
        assert 'reason="timeout"' in failure_lines[0]
        assert 'source="api"' in failure_lines[0]

    def test_empty_label_value(self) -> None:
        """Counter with empty string label value produces {k=""} (valid Prometheus)."""
        m = PrivacyShieldMetrics()
        m.increment("ps_failures_total", {"reason": ""})
        output = m.to_prometheus()

        lines = _parse_metric_lines(output)
        failure_lines = [l for l in lines if l.startswith("ps_failures_total{")]
        assert len(failure_lines) >= 1
        assert 'reason=""' in failure_lines[0]
