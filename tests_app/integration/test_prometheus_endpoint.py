"""
GET /metrics/prometheus endpoint integration tests.

Adversarial Analysis:
  1. Auth bypass: The endpoint must reject requests without X-Admin-Key (401).
     A misconfigured dependency could expose operational metrics publicly.
  2. Content-type mismatch: Prometheus scrapers expect
     'text/plain; version=0.0.4; charset=utf-8'. Any deviation causes scrape failure.
  3. Empty state: On a fresh server with zero observations, the endpoint must still
     return valid Prometheus text (not empty body or 500).

Boundary Map:
  Auth: no header → 401, wrong key → 401, correct key → 200
  State: fresh (no calls) → valid output, after tokenize → updated counters
"""
from __future__ import annotations

import base64
import os
import re

_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app


ADMIN_SECRET = "test-admin-key-prometheus"


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-test",
        ADMIN_API_KEY=ADMIN_SECRET,
    )


@pytest.fixture
async def client_and_redis(test_settings: Settings):
    """Create a test client with a fully wired container (fakeredis)."""
    app = create_app(settings=test_settings)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container
    app.state.active_requests = 0

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")

    yield client, fake_redis

    await client.aclose()
    await fake_redis.aclose()


async def _get_api_key(client: AsyncClient, org_id: str) -> str:
    """Helper: create an API key and return the raw key."""
    resp = await client.post(
        "/api/v1/keys",
        headers={"X-Admin-Key": ADMIN_SECRET},
        json={"organization_id": org_id},
    )
    assert resp.status_code == 200
    return resp.json()["key"]


# ── Auth Enforcement ────────────────────────────────────────────────

class TestPrometheusEndpointAuth:
    """Admin key enforcement on /metrics/prometheus."""

    async def test_returns_401_without_admin_key(self, client_and_redis) -> None:
        """Request without X-Admin-Key header returns 401."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get("/metrics/prometheus")

        assert resp.status_code == 401

    async def test_returns_401_with_wrong_admin_key(self, client_and_redis) -> None:
        """Request with incorrect X-Admin-Key returns 401."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": "wrong-key-definitely-not-valid"},
            )

        assert resp.status_code == 401

    async def test_returns_200_with_correct_admin_key(self, client_and_redis) -> None:
        """Request with correct X-Admin-Key returns 200."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        assert resp.status_code == 200


# ── Content Type ────────────────────────────────────────────────────

class TestPrometheusContentType:
    """Response content type matches Prometheus text exposition format 0.0.4."""

    async def test_correct_content_type(self, client_and_redis) -> None:
        """Content-Type is 'text/plain; version=0.0.4; charset=utf-8'."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        content_type = resp.headers.get("content-type", "")
        assert "text/plain" in content_type, f"Expected text/plain, got {content_type}"
        assert "version=0.0.4" in content_type, f"Missing version=0.0.4 in {content_type}"
        assert "charset=utf-8" in content_type, f"Missing charset=utf-8 in {content_type}"


# ── Response Body Structure ─────────────────────────────────────────

class TestPrometheusResponseBody:
    """Response body contains valid Prometheus text."""

    async def test_body_contains_type_lines(self, client_and_redis) -> None:
        """Response body contains # TYPE lines for registered metrics."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        assert "# TYPE" in body, "Response body missing # TYPE declarations"

    async def test_body_contains_uptime_gauge(self, client_and_redis) -> None:
        """Response body contains ps_uptime_seconds gauge."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        assert "# TYPE ps_uptime_seconds gauge" in body
        assert "ps_uptime_seconds " in body

    async def test_body_contains_all_pre_registered_counters(self, client_and_redis) -> None:
        """All pre-registered counters appear in the Prometheus output."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        expected_counters = [
            "ps_tokenizations_total",
            "ps_tokens_created",
            "ps_failures_total",
            "ps_flush_total",
            "ps_dek_rotations_total",
            "ps_health_checks_total",
            "ps_auth_failures_total",
        ]
        for name in expected_counters:
            assert f"# TYPE {name} counter" in body, (
                f"Missing TYPE declaration for {name}"
            )

    async def test_body_contains_histogram(self, client_and_redis) -> None:
        """The ps_latency_ms histogram appears in the Prometheus output."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        assert "# TYPE ps_latency_ms histogram" in body

    async def test_fresh_metrics_output_is_not_empty(self, client_and_redis) -> None:
        """Even on a fresh server, the endpoint returns non-empty valid text."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        assert len(body.strip()) > 0, "Prometheus output is empty on fresh server"
        # Should have at least the TYPE declarations and uptime
        assert body.count("# TYPE") >= 8  # 7 counters + 1 histogram

    async def test_body_ends_with_newline(self, client_and_redis) -> None:
        """Prometheus text format must end with a newline."""
        client, _ = client_and_redis
        async with client:
            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        assert resp.text.endswith("\n"), "Prometheus output must end with newline"

    async def test_no_pii_in_prometheus_endpoint(self, client_and_redis) -> None:
        """No PII appears in the Prometheus endpoint output after metrics activity.

        We simulate metrics activity directly (increment counters, observe histogram)
        rather than calling /api/v1/tokenize, because the NER model is not available
        in all test environments. The unit-level PII check in test_prometheus_metrics.py
        provides deeper coverage.
        """
        client, _ = client_and_redis

        async with client:
            # Manually drive the metrics through the container (simulates real activity)
            container = client._transport.app.state.container  # type: ignore[attr-defined]
            container.metrics.record_tokenization("regex", ["pe", "cf", "ib"])
            container.metrics.record_latency("tokenize", 42.5)
            container.metrics.record_failure("timeout")

            resp = await client.get(
                "/metrics/prometheus",
                headers={"X-Admin-Key": ADMIN_SECRET},
            )

        body = resp.text
        assert resp.status_code == 200

        # PII values must never appear
        assert "RSSMRA85M01H501Z" not in body
        assert "mario.rossi@email.com" not in body

        # No UUID pattern at all
        uuid_re = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
            re.I,
        )
        assert not uuid_re.search(body), "UUID found in Prometheus output"

        # No org_id in any form
        assert "org_id" not in body.lower()
