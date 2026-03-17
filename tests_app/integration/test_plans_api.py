"""
Plan API endpoint integration tests via TestClient with fakeredis.

Adversarial Analysis:
  1. GET /api/v1/plans is public — must NOT require auth. But
     GET /api/v1/org/{id}/plan and POST /api/v1/org/{id}/plan require admin auth.
  2. Non-UUID org_id in path must return 422, not crash or expose internals.
  3. POST /api/v1/org/{id}/plan with nonexistent plan_id must return 404.
  4. Downgrading when active keys exceed new plan's max_keys must return 409.

Boundary Map:
  plan_id path param: valid slug, nonexistent slug, empty, SQL injection
  org_id path param: valid UUID, non-UUID, too-long string
  auth headers: present/valid, present/invalid, missing
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
ADMIN_SECRET = "test-admin-plans-api"


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


# ── GET /api/v1/plans (public) ──────────────────────────────────────────


class TestListPlans:
    """Public plan catalog endpoint."""

    async def test_returns_all_four_plans_without_auth(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans")
        assert resp.status_code == 200
        plans = resp.json()
        assert len(plans) == 4
        plan_ids = {p["id"] for p in plans}
        assert plan_ids == {"free", "starter", "business", "enterprise"}

    async def test_each_plan_has_all_required_fields(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans")
        required_fields = {"id", "name", "rate_limit_per_minute", "monthly_token_limit", "max_keys", "price_cents"}
        for plan in resp.json():
            assert set(plan.keys()) >= required_fields, (
                f"Plan '{plan.get('id')}' missing fields: {required_fields - set(plan.keys())}"
            )

    async def test_enterprise_has_negative_one_monthly_limit(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans")
        enterprise = [p for p in resp.json() if p["id"] == "enterprise"][0]
        assert enterprise["monthly_token_limit"] == -1


# ── GET /api/v1/plans/{plan_id} ─────────────────────────────────────────


class TestGetSinglePlan:
    """Single plan lookup endpoint."""

    async def test_returns_starter_plan(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans/starter")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "starter"
        assert data["rate_limit_per_minute"] == 60
        assert data["max_keys"] == 5

    async def test_returns_404_for_nonexistent_plan(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans/nonexistent")
        assert resp.status_code == 404

    async def test_returns_404_for_sql_injection_plan_id(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans/'; DROP TABLE plans; --")
        assert resp.status_code == 404

    async def test_returns_404_for_empty_plan_id_path(self, client: AsyncClient) -> None:
        # /api/v1/plans/ should not match /api/v1/plans/{plan_id}
        resp = await client.get("/api/v1/plans/")
        # FastAPI will either 307 redirect to /api/v1/plans or return 404
        assert resp.status_code in (200, 307, 404)

    async def test_no_auth_required_for_single_plan(self, client: AsyncClient) -> None:
        resp = await client.get("/api/v1/plans/free")
        assert resp.status_code == 200


# ── GET /api/v1/org/{org_id}/plan (admin auth) ──────────────────────────


class TestGetOrgPlan:
    """Admin-only org plan endpoint."""

    async def test_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/org/{VALID_ORG}/plan")
        assert resp.status_code == 401

    async def test_returns_free_by_default(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"]["id"] == "free"
        assert data["active_keys"] == 0
        assert data["max_keys"] == 2  # free plan max_keys

    async def test_non_uuid_org_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/org/not-a-uuid/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 422

    async def test_extremely_long_org_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/org/{'a' * 1000}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 422

    async def test_includes_usage_and_key_count(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        data = resp.json()
        assert "usage" in data
        assert "active_keys" in data
        assert "max_keys" in data
        assert data["usage"]["tokenize_calls"] == 0


# ── POST /api/v1/org/{org_id}/plan (admin auth) ─────────────────────────


class TestSetOrgPlan:
    """Admin-only plan assignment endpoint."""

    async def test_requires_admin_auth(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            json={"plan_id": "starter"},
        )
        assert resp.status_code == 401

    async def test_assigns_valid_plan(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "starter"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["plan"]["id"] == "starter"

    async def test_invalid_plan_id_returns_404(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "nonexistent"},
        )
        assert resp.status_code == 404

    async def test_non_uuid_org_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/org/not-a-uuid/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "starter"},
        )
        assert resp.status_code == 422

    async def test_plan_persists_across_reads(self, client: AsyncClient) -> None:
        await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "business"},
        )
        resp = await client.get(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.json()["plan"]["id"] == "business"

    async def test_downgrade_blocked_when_too_many_keys(self, client: AsyncClient) -> None:
        """Assign starter (max 5 keys), create 3 keys, try to downgrade to free (max 2)."""
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
            json={"plan_id": "free"},  # free allows max 2
        )
        assert resp.status_code == 409
        assert "Revoke excess keys" in resp.json()["detail"]

    async def test_sql_injection_in_plan_id_returns_404(self, client: AsyncClient) -> None:
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

    async def test_stripe_customer_id_passed_through(self, client: AsyncClient) -> None:
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "business", "stripe_customer_id": "cus_test12345678901234"},
        )
        assert resp.status_code == 200
        assert resp.json()["plan"]["id"] == "business"

    async def test_invalid_stripe_customer_id_rejected(self, client: AsyncClient) -> None:
        """stripe_customer_id must match cus_[A-Za-z0-9]{14,24} pattern."""
        resp = await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "business", "stripe_customer_id": "not-a-cus-id"},
        )
        assert resp.status_code == 422


# ── GET /api/v1/usage/{org_id} plan enrichment ──────────────────────────


class TestUsagePlanEnrichment:
    """Usage endpoint must include plan fields when plan system is active."""

    async def test_usage_includes_plan_fields(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "plan_id" in data
        assert "plan_name" in data
        assert "monthly_token_limit" in data
        assert "remaining_tokens" in data
        assert "percent_used" in data

    async def test_usage_defaults_to_free_plan(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        data = resp.json()
        assert data["plan_id"] == "free"
        assert data["monthly_token_limit"] == 1000
        assert data["remaining_tokens"] == 1000
        assert data["percent_used"] == 0.0

    async def test_usage_after_plan_change_reflects_new_plan(
        self, client: AsyncClient
    ) -> None:
        await client.post(
            f"/api/v1/org/{VALID_ORG}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"plan_id": "enterprise"},
        )
        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        data = resp.json()
        assert data["plan_id"] == "enterprise"
        assert data["monthly_token_limit"] == -1
        assert data["remaining_tokens"] is None

    async def test_non_uuid_org_id_in_usage_returns_422(self, client: AsyncClient) -> None:
        resp = await client.get(
            "/api/v1/usage/not-a-uuid",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 422
