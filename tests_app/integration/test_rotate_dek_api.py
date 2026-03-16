"""
POST /api/v1/rotate-dek API integration tests.

Adversarial Analysis:
  1. The rotate-dek endpoint depends on _require_admin_key. If X-Admin-Key is missing,
     it must return 401 — not 422 (Pydantic) or 500 (unhandled None comparison).
  2. If ADMIN_API_KEY is empty (default), the endpoint is disabled (403). This prevents
     accidental exposure in non-production deployments.
  3. Invalid org UUID in the request body should be caught by Pydantic before the use
     case executes — a 422, not a 500.

Boundary Map:
  X-Admin-Key header: absent, wrong value, correct value, empty string
  ADMIN_API_KEY config: "" (disabled), "secret" (enabled)
  organization_id: valid UUID, "not-a-uuid", empty string
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock

_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.application.rotate_dek import RotationResult
from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app

ADMIN_KEY = "supersecret-test-key"
VALID_ORG = "00000000-0000-0000-0000-aaaaaaaaaaaa"


@pytest.fixture
def admin_settings() -> Settings:
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-test",
        ADMIN_API_KEY=ADMIN_KEY,
    )


@pytest.fixture
def disabled_admin_settings() -> Settings:
    """Settings with ADMIN_API_KEY empty (endpoint disabled)."""
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-test",
        ADMIN_API_KEY="",
    )


async def _make_client(settings: Settings, mock_rotate_result=None):
    """Create an AsyncClient with a wired container and optional mock rotation."""
    app = create_app(settings=settings)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    container = Container(config=settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container
    app.state.active_requests = 0

    if mock_rotate_result is not None:
        container._rotate_dek_use_case = AsyncMock()
        container._rotate_dek_use_case.execute = AsyncMock(return_value=mock_rotate_result)

    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    return client, fake_redis


class TestRotateDekWithValidAdminKey:
    """POST /api/v1/rotate-dek with correct admin key."""

    async def test_returns_200(self, admin_settings: Settings) -> None:
        result = RotationResult(rotated=True, re_encrypted_count=5)
        client, fake_redis = await _make_client(admin_settings, result)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": VALID_ORG},
                    headers={"X-Admin-Key": ADMIN_KEY},
                )
            assert resp.status_code == 200
            data = resp.json()
            assert data["rotated"] is True
            assert data["re_encrypted_count"] == 5
        finally:
            await fake_redis.aclose()


class TestRotateDekWithoutAdminKey:
    """POST /api/v1/rotate-dek without X-Admin-Key header."""

    async def test_returns_401(self, admin_settings: Settings) -> None:
        client, fake_redis = await _make_client(admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": VALID_ORG},
                )
            assert resp.status_code == 401
        finally:
            await fake_redis.aclose()


class TestRotateDekWithWrongAdminKey:
    """POST /api/v1/rotate-dek with incorrect X-Admin-Key."""

    async def test_returns_401(self, admin_settings: Settings) -> None:
        client, fake_redis = await _make_client(admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": VALID_ORG},
                    headers={"X-Admin-Key": "wrong-key"},
                )
            assert resp.status_code == 401
        finally:
            await fake_redis.aclose()


class TestRotateDekAdminKeyDisabled:
    """POST /api/v1/rotate-dek when ADMIN_API_KEY is empty."""

    async def test_returns_403(self, disabled_admin_settings: Settings) -> None:
        client, fake_redis = await _make_client(disabled_admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": VALID_ORG},
                    headers={"X-Admin-Key": "any-key"},
                )
            assert resp.status_code == 403
        finally:
            await fake_redis.aclose()

    async def test_returns_403_even_without_header(
        self, disabled_admin_settings: Settings
    ) -> None:
        client, fake_redis = await _make_client(disabled_admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": VALID_ORG},
                )
            assert resp.status_code == 403
        finally:
            await fake_redis.aclose()


class TestRotateDekInvalidOrgUuid:
    """POST /api/v1/rotate-dek with invalid org UUID."""

    async def test_returns_422_for_non_uuid(self, admin_settings: Settings) -> None:
        client, fake_redis = await _make_client(admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": "not-a-valid-uuid"},
                    headers={"X-Admin-Key": ADMIN_KEY},
                )
            assert resp.status_code == 422
        finally:
            await fake_redis.aclose()

    async def test_returns_422_for_empty_string(self, admin_settings: Settings) -> None:
        client, fake_redis = await _make_client(admin_settings)
        try:
            async with client:
                resp = await client.post(
                    "/api/v1/rotate-dek",
                    json={"organization_id": ""},
                    headers={"X-Admin-Key": ADMIN_KEY},
                )
            assert resp.status_code == 422
        finally:
            await fake_redis.aclose()
