"""
Graceful shutdown integration tests (T4.6).

Adversarial Analysis:
  1. The shutdown_guard middleware uses a mutable list [False] as a module-level
     flag. If the test creates multiple app instances, they share the same flag.
     Tests must reset the flag in teardown.
  2. The _flush_orphaned_request_sets function catches all exceptions to avoid
     crashing shutdown. A test must verify it swallows errors gracefully.
  3. Health and metrics endpoints are exempt from shutdown guard. A bug would
     be returning 503 for /health during shutdown, blocking monitoring.

Boundary Map:
  shutdown_flag: [False] (normal), [True] (shutting down)
  request path: /health (exempt), /metrics (exempt), /api/v1/tokenize (guarded)
  Redis scan result: empty (no orphans), non-empty, error (connection refused)
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, patch

# Set env var BEFORE any app import
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import _flush_orphaned_request_sets, _shutdown_flag, create_app

_ADMIN_SECRET = "test-admin-secret-shutdown"


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
        ADMIN_API_KEY=_ADMIN_SECRET,
    )


@pytest.fixture
def _reset_shutdown_flag():
    """Reset the module-level shutdown flag before and after each test."""
    _shutdown_flag[0] = False
    yield
    _shutdown_flag[0] = False


@pytest.fixture
async def wired_app(test_settings: Settings, _reset_shutdown_flag):
    """Create an app with a fake Redis container, ready for requests."""
    app = create_app(settings=test_settings)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container
    app.state.active_requests = 0

    yield app

    await fake_redis.aclose()


class TestNormalRequestsBeforeShutdown:
    """Normal requests return 200 before shutdown."""

    async def test_health_returns_200(self, wired_app) -> None:
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_metrics_returns_200(self, wired_app) -> None:
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics", headers={"X-Admin-Key": _ADMIN_SECRET})
        assert resp.status_code == 200


class TestShutdownGuard:
    """During shutdown, non-exempt endpoints return 503."""

    async def test_tokenize_returns_503_during_shutdown(self, wired_app) -> None:
        _shutdown_flag[0] = True
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/tokenize",
                json={
                    "texts": ["Hello"],
                    "organization_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
                    "request_id": "00000000-0000-0000-0000-bbbbbbbbbbbb",
                },
            )
        assert resp.status_code == 503
        assert resp.json()["code"] == "SHUTTING_DOWN"

    async def test_rehydrate_returns_503_during_shutdown(self, wired_app) -> None:
        _shutdown_flag[0] = True
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/rehydrate",
                json={
                    "text": "[#pe:a1b2]",
                    "organization_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
                },
            )
        assert resp.status_code == 503

    async def test_flush_returns_503_during_shutdown(self, wired_app) -> None:
        _shutdown_flag[0] = True
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/flush",
                json={
                    "organization_id": "00000000-0000-0000-0000-aaaaaaaaaaaa",
                    "request_id": "00000000-0000-0000-0000-bbbbbbbbbbbb",
                },
            )
        assert resp.status_code == 503


class TestShutdownExemptEndpoints:
    """Health and metrics are exempt from shutdown guard."""

    async def test_health_returns_200_during_shutdown(self, wired_app) -> None:
        _shutdown_flag[0] = True
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_metrics_returns_200_during_shutdown(self, wired_app) -> None:
        _shutdown_flag[0] = True
        transport = ASGITransport(app=wired_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/metrics", headers={"X-Admin-Key": _ADMIN_SECRET})
        assert resp.status_code == 200


class TestFlushOrphanedRequestSets:
    """_flush_orphaned_request_sets edge cases."""

    async def test_empty_scan_result(self, test_settings: Settings) -> None:
        """No orphan keys -> should complete without error."""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        container = Container(config=test_settings)
        container._redis = fake_redis

        # Should complete successfully with no keys to unlink
        await _flush_orphaned_request_sets(container)
        await fake_redis.aclose()

    async def test_flushes_existing_orphan_keys(self, test_settings: Settings) -> None:
        """Existing ps:req:* keys are unlinked during shutdown."""
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        container = Container(config=test_settings)
        container._redis = fake_redis

        # Create some orphan keys
        await fake_redis.sadd("ps:req:org1:req1", "hash1")
        await fake_redis.sadd("ps:req:org2:req2", "hash2")

        await _flush_orphaned_request_sets(container)

        # Keys should be gone
        assert await fake_redis.exists("ps:req:org1:req1") == 0
        assert await fake_redis.exists("ps:req:org2:req2") == 0
        await fake_redis.aclose()

    async def test_redis_error_is_swallowed(self, test_settings: Settings) -> None:
        """Redis errors during flush must not crash shutdown."""
        container = Container(config=test_settings)
        mock_redis = AsyncMock()
        mock_redis.scan = AsyncMock(side_effect=ConnectionError("Redis went away"))
        container._redis = mock_redis

        # Must not raise
        await _flush_orphaned_request_sets(container)
