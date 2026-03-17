"""
Plan system adversarial abuse tests.

Adversarial Analysis:
  1. Attacker tries to inject plan/rate_limit fields in CreateKeyRequest body.
     Model has extra="ignore" — must be silently dropped.
  2. Non-UUID org_id must return 422 (FastAPI validation), not 500.
  3. SQL injection in plan_id must return 404 (plan not found), not crash.
  4. Downgrading a plan when too many keys exist must be blocked.
  5. Extremely large strings in path params must not crash the server.

Boundary Map:
  org_id: non-UUID, empty UUID, null-byte UUID, oversized string
  plan_id: SQL injection, null bytes, whitespace-only
  CreateKeyRequest body: extra fields (plan, rate_limit_per_minute)
"""
from __future__ import annotations

import base64
import os

_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app

VALID_ORG = "00000000-0000-0000-0000-00000000000a"
ADMIN_SECRET = "test-admin-adversarial"


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
async def client(test_settings: Settings) -> AsyncClient:
    app = create_app(settings=test_settings)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await fake_redis.aclose()


class TestPlanBypassAttempts:
    """Attacker tries to bypass plan enforcement via request body manipulation."""

    async def test_extra_plan_field_in_create_key_body_is_ignored(
        self, client: AsyncClient
    ) -> None:
        """CreateKeyRequest has extra='ignore', so 'plan' field in body is dropped."""
        # First assign free plan so we can verify plan override doesn't work
        await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "free"},
        )
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={
                "organization_id": VALID_ORG,
                "plan": "enterprise",  # attacker tries to set enterprise
            },
        )
        assert resp.status_code == 200
        # Verify via list that the plan is still "free"
        keys_resp = await client.get(
            "/api/v1/keys",
            params={"org_id": VALID_ORG},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        key = keys_resp.json()[0]
        assert key["plan"] == "free"
        assert key["rate_limit_per_minute"] == 10  # free plan rate

    async def test_extra_rate_limit_field_in_create_key_body_is_ignored(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "free"},
        )
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={
                "organization_id": VALID_ORG,
                "rate_limit_per_minute": 999_999,  # attacker tries high rate
            },
        )
        assert resp.status_code == 200
        keys_resp = await client.get(
            "/api/v1/keys",
            params={"org_id": VALID_ORG},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        key = keys_resp.json()[0]
        assert key["rate_limit_per_minute"] == 10  # free plan, not 999999


class TestMalformedOrgId:
    """Non-UUID org_id in path params must return 422."""

    async def test_non_uuid_org_id_in_get_plan_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get(
            "/api/v1/org/not-a-uuid/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 422

    async def test_non_uuid_org_id_in_set_plan_returns_422(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/org/not-a-uuid/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "starter"},
        )
        assert resp.status_code == 422

    async def test_extremely_large_org_id_returns_422(self, client: AsyncClient) -> None:
        large_id = "a" * 10_000
        resp = await client.get(
            f"/api/v1/org/{large_id}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 422

    async def test_null_byte_org_id_does_not_crash(self, client: AsyncClient) -> None:
        """Null bytes in path params are rejected by httpx (URL safety).

        We verify the server doesn't crash by testing URL-encoded null byte
        (%00) instead, which httpx allows and FastAPI will see as a non-UUID.
        """
        resp = await client.get(
            "/api/v1/org/00000000-0000-0000-0000-00000000000%00a/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        # Should be 422 (invalid UUID) or another client error, not 500
        assert resp.status_code < 500


class TestMalformedPlanId:
    """Injection and malformed plan_id values."""

    async def test_sql_injection_in_plan_id_returns_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "'; DROP TABLE plans; --"},
        )
        assert resp.status_code == 404

    async def test_empty_plan_id_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": ""},
        )
        assert resp.status_code == 404

    async def test_whitespace_only_plan_id_returns_404(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "   "},
        )
        assert resp.status_code == 404


class TestDowngradeProtection:
    """Downgrading a plan when too many active keys exist must fail."""

    async def test_downgrade_blocked_free_to_free_with_excess_keys(
        self, client: AsyncClient
    ) -> None:
        """
        Assign starter (5 keys), create 3, then downgrade to free (2 keys).
        Must return 409 because 3 > 2.
        """
        await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "starter"},
        )
        for _ in range(3):
            await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": ADMIN_SECRET},
                json={"organization_id": VALID_ORG},
            )
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "free"},
        )
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "3 active" in detail
        assert "2" in detail  # free max_keys
