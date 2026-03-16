"""
Health endpoint integration tests.

Updated for T4.5 — structured per-component health response format.

Adversarial Analysis:
  1. Redis up -> 200 with status "healthy" and per-component breakdown.
  2. Redis down -> 503 with status "degraded".
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock

# Set env var BEFORE any app import
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app


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
    )


class TestHealthRedisUp:
    """GET /health with Redis up — T4.5 enhanced structured response."""

    async def test_health_ok(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["version"] == "0.0.0-test"

        # Per-component checks
        assert data["components"]["redis"]["status"] == "up"
        assert data["components"]["redis"]["latency_ms"] is not None
        assert data["components"]["crypto"]["status"] == "up"
        assert data["components"]["crypto"]["kek_valid"] is True
        assert data["components"]["slm"]["status"] == "not_configured"

        await fake_redis.aclose()


class TestHealthRedisDown:
    """GET /health with Redis down — should return 503 and degraded status."""

    async def test_health_degraded(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)

        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("Connection refused"))

        container = Container(config=test_settings)
        container._redis = mock_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["redis"]["status"] == "down"
        # Crypto self-test may still pass even with Redis down (uses in-memory KEK)
        assert "components" in data
        assert data["components"]["slm"]["status"] == "not_configured"
