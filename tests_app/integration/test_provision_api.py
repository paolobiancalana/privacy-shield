"""
Integration tests for POST /api/v1/provision endpoint.

Adversarial Analysis:
  1. Missing X-Admin-Key must return 401, not proceed with provisioning.
  2. Invalid UUID in organization_id must return 422 from Pydantic validation.
  3. Unknown plan_id must return 404 (route checks plan catalog before use case).

Tests use the same pattern as test_api_lifecycle.py: fakeredis + ASGI TestClient.
"""
from __future__ import annotations

import base64
import os

# Set env var BEFORE any app import to avoid module-level Settings() failure
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app


VALID_ORG_A = "00000000-0000-0000-0000-000000000001"
VALID_ORG_B = "00000000-0000-0000-0000-000000000002"
ADMIN_SECRET = "test-admin-key-provision"


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
    """Create a test client with fakeredis injected into the container."""
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


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": ADMIN_SECRET}


# ---------------------------------------------------------------------------
# Auth Enforcement
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """Provision endpoint requires X-Admin-Key."""

    async def test_missing_admin_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401

    async def test_wrong_admin_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers={"X-Admin-Key": "wrong-secret"},
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401

    async def test_empty_admin_key_header_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers={"X-Admin-Key": ""},
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestValidation:
    """Input validation before reaching the use case."""

    async def test_invalid_uuid_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": "not-a-uuid"},
        )
        assert resp.status_code == 422

    async def test_missing_organization_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={},
        )
        assert resp.status_code == 422

    async def test_invalid_environment_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={
                "organization_id": VALID_ORG_A,
                "environment": "staging",
            },
        )
        assert resp.status_code == 422

    async def test_unknown_plan_id_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={
                "organization_id": VALID_ORG_A,
                "plan_id": "nonexistent_plan",
            },
        )
        assert resp.status_code == 404
        assert "nonexistent_plan" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Functional success via the full HTTP stack."""

    async def test_provision_new_org_returns_200_with_key(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["key"].startswith("ps_live_")
        assert len(data["key"]) == 40
        assert data["key_id"].startswith("kid_")
        assert data["organization_id"] == VALID_ORG_A
        assert data["plan"] == "free"
        assert data["environment"] == "live"

    async def test_provision_default_plan_is_free(self, client: AsyncClient) -> None:
        """Omitting plan_id must default to 'free'."""
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 200
        assert resp.json()["plan"] == "free"

    async def test_provision_with_test_environment(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={
                "organization_id": VALID_ORG_A,
                "plan_id": "free",
                "environment": "test",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["created"] is True
        assert data["key"].startswith("ps_test_")
        assert data["environment"] == "test"


# ---------------------------------------------------------------------------
# Idempotency via HTTP
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Calling provision twice for the same (org, environment)."""

    async def test_second_provision_returns_created_false(self, client: AsyncClient) -> None:
        resp1 = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free"},
        )
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["created"] is True
        first_key_id = data1["key_id"]

        resp2 = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free"},
        )
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["created"] is False
        assert data2["key"] == ""
        assert data2["key_id"] == first_key_id

    async def test_different_environment_creates_new_key(self, client: AsyncClient) -> None:
        """Provision 'live' then 'test' -- both should return created=True."""
        resp_live = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free", "environment": "live"},
        )
        assert resp_live.status_code == 200
        assert resp_live.json()["created"] is True

        resp_test = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free", "environment": "test"},
        )
        assert resp_test.status_code == 200
        assert resp_test.json()["created"] is True
        assert resp_test.json()["key"].startswith("ps_test_")


# ---------------------------------------------------------------------------
# Tenant Isolation via HTTP
# ---------------------------------------------------------------------------


class TestTenantIsolationHTTP:
    """Provisioning two different orgs must produce independent results."""

    async def test_provision_two_orgs_returns_different_keys(self, client: AsyncClient) -> None:
        resp_a = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free"},
        )
        resp_b = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_B, "plan_id": "starter"},
        )

        assert resp_a.status_code == 200
        assert resp_b.status_code == 200

        data_a = resp_a.json()
        data_b = resp_b.json()

        assert data_a["organization_id"] == VALID_ORG_A
        assert data_b["organization_id"] == VALID_ORG_B
        assert data_a["key"] != data_b["key"]
        assert data_a["key_id"] != data_b["key_id"]

    async def test_idempotent_check_does_not_see_other_orgs_keys(
        self, client: AsyncClient
    ) -> None:
        """Provision org-A, then provision org-B. Org-B must not see org-A's key."""
        await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "free"},
        )

        resp_b = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_B, "plan_id": "free"},
        )

        data_b = resp_b.json()
        assert data_b["created"] is True
        assert data_b["organization_id"] == VALID_ORG_B


# ---------------------------------------------------------------------------
# Error Handling via HTTP
# ---------------------------------------------------------------------------


class TestErrorHandlingHTTP:
    """Errors must return structured responses, not expose stack traces."""

    async def test_404_response_has_detail_field(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/provision",
            headers=_admin_headers(),
            json={"organization_id": VALID_ORG_A, "plan_id": "totally_fake_plan"},
        )
        assert resp.status_code == 404
        body = resp.json()
        assert "detail" in body
        # Should mention the plan name
        assert "totally_fake_plan" in body["detail"]
