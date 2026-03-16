"""
Enhanced health check integration tests (T4.5).

Adversarial Analysis:
  1. The health endpoint's crypto self-test calls `validate_kek()` which does a
     dummy encrypt-decrypt. If this raises (not returns False), the code catches it
     and sets status to 'down'. A bug would be propagating the exception as a 500.
  2. Redis latency_ms is measured with perf_counter. A very fast fakeredis PING
     could return 0.0 — must not be treated as None or cause division errors.
  3. SLM status is hardcoded to 'not_configured' in Fase 1/3. A test must verify
     this placeholder is present and doesn't cause any aggregate status degradation.

Boundary Map:
  Redis: up (PING succeeds), down (PING raises)
  Crypto: valid KEK, invalid KEK (validate_kek returns False)
  SLM: always not_configured
  Overall: healthy (all up), degraded (any down)
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, MagicMock

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
        APP_VERSION="1.2.3-test",
    )


class TestHealthStructuredResponse:
    """GET /health -> structured JSON with components."""

    async def test_healthy_response_structure(self, test_settings: Settings) -> None:
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

        # Top-level
        assert data["status"] == "healthy"
        assert data["version"] == "1.2.3-test"

        # Components
        components = data["components"]
        assert "redis" in components
        assert "crypto" in components
        assert "slm" in components

        # Redis component
        assert components["redis"]["status"] == "up"
        assert isinstance(components["redis"]["latency_ms"], (int, float))
        assert components["redis"]["latency_ms"] >= 0

        # Crypto component
        assert components["crypto"]["status"] == "up"
        assert components["crypto"]["kek_valid"] is True

        # SLM component
        assert components["slm"]["status"] == "not_configured"

        await fake_redis.aclose()


class TestCryptoKekValid:
    """Crypto component shows kek_valid: true when KEK is valid."""

    async def test_kek_valid_true(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        data = resp.json()
        assert data["components"]["crypto"]["kek_valid"] is True
        await fake_redis.aclose()


class TestCryptoKekInvalid:
    """Crypto component shows down when validate_kek returns False."""

    async def test_kek_invalid_degrades_status(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        # Wire a crypto mock that returns False for validate_kek
        mock_crypto = MagicMock()
        mock_crypto.validate_kek.return_value = False
        container._crypto_adapter = mock_crypto
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["crypto"]["status"] == "down"
        assert data["components"]["crypto"]["kek_valid"] is False
        await fake_redis.aclose()


class TestCryptoValidateKekRaises:
    """If validate_kek raises an exception, crypto status is 'down', not 500."""

    async def test_kek_exception_handled_gracefully(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        mock_crypto = MagicMock()
        mock_crypto.validate_kek.side_effect = RuntimeError("KEK corrupted")
        container._crypto_adapter = mock_crypto
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "degraded"
        assert data["components"]["crypto"]["status"] == "down"
        assert data["components"]["crypto"]["kek_valid"] is False
        await fake_redis.aclose()


class TestRedisLatency:
    """Redis component shows latency_ms."""

    async def test_latency_ms_is_numeric(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        data = resp.json()
        latency = data["components"]["redis"]["latency_ms"]
        assert isinstance(latency, (int, float))
        assert latency >= 0
        await fake_redis.aclose()


class TestRedisDown:
    """Redis down results in degraded status with latency_ms None."""

    async def test_redis_down_latency_null(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))

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
        assert data["components"]["redis"]["latency_ms"] is None


class TestSlmNotConfigured:
    """SLM shows not_configured and does not degrade overall status."""

    async def test_slm_not_configured_still_healthy(self, test_settings: Settings) -> None:
        app = create_app(settings=test_settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

        container = Container(config=test_settings)
        container._redis = fake_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")

        data = resp.json()
        # SLM not_configured should NOT degrade the overall status
        assert data["status"] == "healthy"
        assert data["components"]["slm"]["status"] == "not_configured"
        await fake_redis.aclose()
