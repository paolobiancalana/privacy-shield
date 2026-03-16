"""
GET /metrics endpoint integration tests (T4.7).

Adversarial Analysis:
  1. The /metrics endpoint returns container.metrics.snapshot() directly.
     If metrics were never written to, it must still return a valid JSON
     structure with all pre-registered counters at 0.
  2. After a tokenize call, ps_tokenizations_total must be incremented.
     A race between the tokenize response and the metrics read could show
     stale data — but since we use sequential calls, this is deterministic.
  3. Metrics must never contain PII values, token content, or org text.

Boundary Map:
  Endpoint: GET /metrics
  State: fresh (no calls), after tokenize, after flush
"""
from __future__ import annotations

import base64
import os
import uuid

_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app


ADMIN_SECRET = "test-admin-key-metrics"


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


class TestMetricsEndpointStructure:
    """GET /metrics returns JSON with counters and histograms."""

    async def test_metrics_returns_json_structure(self, client_and_redis) -> None:
        client, _ = client_and_redis
        async with client:
            resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})

        assert resp.status_code == 200
        data = resp.json()
        assert "uptime_seconds" in data
        assert "counters" in data
        assert "histograms" in data
        assert isinstance(data["counters"], dict)
        assert isinstance(data["histograms"], dict)

    async def test_pre_registered_counters_present(self, client_and_redis) -> None:
        client, _ = client_and_redis
        async with client:
            resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})

        counters = resp.json()["counters"]
        expected_counters = [
            "ps_tokenizations_total",
            "ps_tokens_created",
            "ps_failures_total",
            "ps_flush_total",
            "ps_dek_rotations_total",
            "ps_health_checks_total",
        ]
        for name in expected_counters:
            assert name in counters, f"Missing pre-registered counter: {name}"
            assert counters[name]["total"] == 0


class TestMetricsAfterTokenize:
    """After a tokenize call, ps_tokenizations_total is incremented."""

    async def test_tokenize_increments_counter(self, client_and_redis) -> None:
        client, _ = client_and_redis
        org_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        async with client:
            api_key = await _get_api_key(client, org_id)

            # Perform a tokenize call (Italian text with a CF)
            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": api_key},
                json={
                    "texts": ["Il codice fiscale e' RSSMRA85M01H501Z."],
                    "organization_id": org_id,
                    "request_id": request_id,
                },
            )

            # Now check metrics
            resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})

        data = resp.json()
        # The tokenization counter should have been incremented
        assert data["counters"]["ps_tokenizations_total"]["total"] >= 1
        # Latency histogram should have at least one observation
        assert data["histograms"]["ps_latency_ms"]["count"] >= 1


class TestMetricsAfterFlush:
    """After a flush call, ps_flush_total is incremented."""

    async def test_flush_increments_counter(self, client_and_redis) -> None:
        client, _ = client_and_redis
        org_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())

        async with client:
            api_key = await _get_api_key(client, org_id)

            # Tokenize first to create vault entries
            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": api_key},
                json={
                    "texts": ["Mario Rossi"],
                    "organization_id": org_id,
                    "request_id": request_id,
                },
            )

            # Flush the request
            await client.post(
                "/api/v1/flush",
                headers={"X-Api-Key": api_key},
                json={
                    "organization_id": org_id,
                    "request_id": request_id,
                },
            )

            # Check metrics
            resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})

        data = resp.json()
        assert data["counters"]["ps_flush_total"]["total"] >= 1
        assert data["counters"]["ps_flush_total"]["by_label"].get("status=success") is not None


class TestMetricsNoPii:
    """Metrics response must never contain PII values."""

    async def test_no_pii_in_metrics(self, client_and_redis) -> None:
        client, _ = client_and_redis
        org_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        pii_text = "RSSMRA85M01H501Z mario.rossi@email.com +39 333 1234567"

        async with client:
            api_key = await _get_api_key(client, org_id)

            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": api_key},
                json={
                    "texts": [pii_text],
                    "organization_id": org_id,
                    "request_id": request_id,
                },
            )
            resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})

        raw = resp.text
        # None of the PII values should appear in the metrics JSON
        assert "RSSMRA85M01H501Z" not in raw
        assert "mario.rossi@email.com" not in raw
        assert "+39 333 1234567" not in raw
        assert "Mario" not in raw
