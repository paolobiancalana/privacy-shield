"""
PrivacyShieldMetrics unit tests.

Adversarial Analysis:
  1. Ring buffer overflow: after _HISTOGRAM_MAX_SAMPLES (10,000) observations,
     the oldest must be overwritten, NOT grow the list unboundedly. A naive
     implementation would append() forever, exhausting memory on long-running procs.
  2. Thread-safety: concurrent increment/observe calls must not lose counts.
     Under CPython's GIL this is mostly safe, but Lock contention could cause
     stale reads if snapshot() acquires partial state.
  3. Percentile with 1 sample: p99 of a single-element list must return that element,
     not crash on ceil(0.99 * 1) - 1 = 0.

Boundary Map:
  counter total: 0 (initial), 1 (after single inc), N (concurrent)
  histogram samples: 0 (empty), 1 (single), 10001 (overflow)
  labels: None (all bucket), {"k": "v"} (specific)
  percentile p: 0 (min boundary), 50 (median), 99 (near-max), 100 (max)
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.infrastructure.metrics import PrivacyShieldMetrics, _Counter, _Histogram, _label_key, _summarise, _percentile


class TestCounterBasics:
    """Counter increment with and without labels."""

    def test_increment_no_labels(self) -> None:
        c = _Counter()
        c.increment()
        snap = c.snapshot()
        assert snap["total"] == 1
        assert snap["by_label"]["all"] == 1

    def test_increment_with_labels_separate_buckets(self) -> None:
        c = _Counter()
        c.increment({"source": "regex"})
        c.increment({"source": "regex"})
        c.increment({"source": "slm"})
        snap = c.snapshot()
        assert snap["total"] == 3
        assert snap["by_label"]["source=regex"] == 2
        assert snap["by_label"]["source=slm"] == 1

    def test_increment_mixed_labels_and_no_labels(self) -> None:
        c = _Counter()
        c.increment()
        c.increment({"a": "1"})
        snap = c.snapshot()
        assert snap["total"] == 2
        assert snap["by_label"]["all"] == 1
        assert snap["by_label"]["a=1"] == 1


class TestHistogramBasics:
    """Histogram observe and percentile calculation."""

    def test_observe_correct_p50_p99(self) -> None:
        h = _Histogram()
        for v in range(1, 101):
            h.observe(float(v))
        snap = h.snapshot()
        assert snap["count"] == 100
        assert snap["min"] == 1.0
        assert snap["max"] == 100.0
        assert snap["p50"] == 50.0
        assert snap["p99"] == 99.0

    def test_single_sample_percentile(self) -> None:
        h = _Histogram()
        h.observe(42.0)
        snap = h.snapshot()
        assert snap["count"] == 1
        assert snap["p50"] == 42.0
        assert snap["p99"] == 42.0
        assert snap["min"] == 42.0
        assert snap["max"] == 42.0

    def test_empty_histogram_snapshot(self) -> None:
        h = _Histogram()
        snap = h.snapshot()
        assert snap["count"] == 0
        assert snap["p50"] == 0.0
        assert snap["p99"] == 0.0
        assert snap["sum"] == 0.0
        assert snap["min"] == 0.0
        assert snap["max"] == 0.0

    def test_observe_with_labels(self) -> None:
        h = _Histogram()
        h.observe(1.0, {"op": "tokenize"})
        h.observe(2.0, {"op": "tokenize"})
        h.observe(5.0, {"op": "flush"})
        snap = h.snapshot()
        assert snap["count"] == 3
        assert snap["by_label"]["op=tokenize"]["count"] == 2
        assert snap["by_label"]["op=flush"]["count"] == 1


class TestRingBuffer:
    """After 10,001 observations, oldest dropped, memory bounded."""

    def test_ring_buffer_caps_at_max_samples(self) -> None:
        h = _Histogram()
        for i in range(10_001):
            h.observe(float(i))

        # Internal list should be exactly 10_000 (not 10_001)
        assert len(h._samples) == 10_000

        snap = h.snapshot()
        assert snap["count"] == 10_000
        # The oldest sample (0.0) should have been overwritten by 10000.0
        assert 0.0 not in h._samples
        assert 10_000.0 in h._samples

    def test_ring_buffer_per_label(self) -> None:
        h = _Histogram()
        for i in range(10_001):
            h.observe(float(i), {"lbl": "a"})

        assert len(h._by_label["lbl=a"]) == 10_000


class TestSnapshot:
    """Snapshot returns correct JSON-serializable structure."""

    def test_snapshot_structure(self) -> None:
        m = PrivacyShieldMetrics()
        snap = m.snapshot()

        assert "uptime_seconds" in snap
        assert isinstance(snap["uptime_seconds"], float)
        assert "counters" in snap
        assert "histograms" in snap

        # Pre-registered counters
        for name in (
            "ps_tokenizations_total",
            "ps_tokens_created",
            "ps_failures_total",
            "ps_flush_total",
            "ps_dek_rotations_total",
            "ps_health_checks_total",
        ):
            assert name in snap["counters"]
            assert snap["counters"][name]["total"] == 0

        # Pre-registered histogram
        assert "ps_latency_ms" in snap["histograms"]

    def test_snapshot_is_json_serializable(self) -> None:
        import json
        m = PrivacyShieldMetrics()
        m.increment("ps_tokenizations_total", {"source": "regex"})
        m.observe("ps_latency_ms", 12.5, {"operation": "tokenize"})
        snap = m.snapshot()
        # Must not raise
        json_str = json.dumps(snap)
        assert isinstance(json_str, str)


class TestThreadSafety:
    """Concurrent increments must not lose counts."""

    def test_concurrent_counter_increments(self) -> None:
        c = _Counter()
        n_threads = 10
        n_per_thread = 1000

        def increment_many():
            for _ in range(n_per_thread):
                c.increment()

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(increment_many) for _ in range(n_threads)]
            for f in futures:
                f.result()

        snap = c.snapshot()
        assert snap["total"] == n_threads * n_per_thread

    def test_concurrent_histogram_observes(self) -> None:
        h = _Histogram()
        n_threads = 10
        n_per_thread = 500

        def observe_many():
            for i in range(n_per_thread):
                h.observe(float(i))

        with ThreadPoolExecutor(max_workers=n_threads) as pool:
            futures = [pool.submit(observe_many) for _ in range(n_threads)]
            for f in futures:
                f.result()

        snap = h.snapshot()
        # Total observations = 10 * 500 = 5000, capped at 10000
        assert snap["count"] == n_threads * n_per_thread

    def test_concurrent_metrics_snapshot(self) -> None:
        """Concurrent snapshot() calls must not crash or return partial data."""
        m = PrivacyShieldMetrics()

        errors: list[Exception] = []

        def writer():
            for i in range(200):
                m.increment("ps_tokenizations_total", {"source": "regex"})
                m.observe("ps_latency_ms", float(i))

        def reader():
            for _ in range(200):
                try:
                    snap = m.snapshot()
                    assert "counters" in snap
                    assert "histograms" in snap
                except Exception as e:
                    errors.append(e)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=writer),
            threading.Thread(target=reader),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


class TestConvenienceHelpers:
    """record_tokenization, record_latency, record_failure, record_flush."""

    def test_record_tokenization(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_tokenization("regex", ["pe", "cf", "pe"])

        snap = m.snapshot()
        assert snap["counters"]["ps_tokenizations_total"]["total"] == 1
        assert snap["counters"]["ps_tokenizations_total"]["by_label"]["source=regex"] == 1
        # ps_tokens_created is incremented without type labels to prevent PII type
        # distribution leakage — check total only, not by_label["type=..."]
        assert snap["counters"]["ps_tokens_created"]["total"] == 3

    def test_record_latency(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_latency("tokenize", 15.5)

        snap = m.snapshot()
        hist = snap["histograms"]["ps_latency_ms"]
        assert hist["count"] == 1
        assert hist["by_label"]["operation=tokenize"]["count"] == 1

    def test_record_failure(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_failure("timeout")

        snap = m.snapshot()
        assert snap["counters"]["ps_failures_total"]["by_label"]["reason=timeout"] == 1

    def test_record_flush(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_flush("success")
        m.record_flush("fallback_ttl")

        snap = m.snapshot()
        assert snap["counters"]["ps_flush_total"]["total"] == 2
        assert snap["counters"]["ps_flush_total"]["by_label"]["status=success"] == 1
        assert snap["counters"]["ps_flush_total"]["by_label"]["status=fallback_ttl"] == 1

    def test_record_dek_rotation(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_dek_rotation()
        snap = m.snapshot()
        assert snap["counters"]["ps_dek_rotations_total"]["total"] == 1

    def test_record_health_check(self) -> None:
        m = PrivacyShieldMetrics()
        m.record_health_check("healthy")
        m.record_health_check("degraded")
        snap = m.snapshot()
        assert snap["counters"]["ps_health_checks_total"]["total"] == 2
        assert snap["counters"]["ps_health_checks_total"]["by_label"]["status=healthy"] == 1
        assert snap["counters"]["ps_health_checks_total"]["by_label"]["status=degraded"] == 1


class TestLabelKey:
    """_label_key edge cases."""

    def test_none_labels_returns_all(self) -> None:
        assert _label_key(None) == "all"

    def test_empty_dict_returns_all(self) -> None:
        assert _label_key({}) == "all"

    def test_single_label(self) -> None:
        assert _label_key({"k": "v"}) == "k=v"

    def test_multiple_labels_sorted(self) -> None:
        result = _label_key({"z": "1", "a": "2"})
        assert result == "a=2,z=1"


class TestPercentileEdge:
    """_percentile edge cases."""

    def test_percentile_empty(self) -> None:
        assert _percentile([], 50) == 0.0

    def test_percentile_single(self) -> None:
        assert _percentile([7.0], 99) == 7.0

    def test_percentile_p0(self) -> None:
        """p=0 should return the minimum (index clamped to 0)."""
        result = _percentile([1.0, 2.0, 3.0], 0)
        assert result == 1.0  # ceil(0) - 1 = -1, clamped to 0

    def test_percentile_p100(self) -> None:
        """p=100 should return the maximum."""
        result = _percentile([1.0, 2.0, 3.0], 100)
        assert result == 3.0


class TestSummarise:
    """_summarise edge cases."""

    def test_summarise_empty(self) -> None:
        result = _summarise([])
        assert result == {"count": 0, "sum": 0.0, "min": 0.0, "max": 0.0, "p50": 0.0, "p99": 0.0}

    def test_summarise_rounds_to_3_decimals(self) -> None:
        result = _summarise([1.11111, 2.22222])
        assert result["sum"] == 3.333  # 1.11111 + 2.22222 = 3.33333, rounded to 3.333
