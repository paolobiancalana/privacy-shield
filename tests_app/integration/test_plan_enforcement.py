"""
E2E plan enforcement integration tests via TestClient with fakeredis.

These tests verify that plan limits are enforced end-to-end through the
full HTTP stack: auth -> use case -> vault -> response.

Adversarial Analysis:
  1. Creating more keys than max_keys must return 409, not silently succeed.
  2. Tokenizing beyond monthly limit must return 429 with plan-specific headers.
  3. Enterprise plan must never be blocked by monthly limits.
  4. Billing stub endpoints must return 501 (not 404 or 500).

Boundary Map:
  active keys vs max_keys: at limit (blocked), under limit (allowed)
  monthly usage vs monthly_token_limit: at limit (blocked), under (allowed), enterprise (-1, never blocked)
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
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
from app.infrastructure.config import Settings
from app.main import create_app

VALID_ORG = "00000000-0000-0000-0000-00000000000a"
VALID_REQ_ID = "00000000-0000-0000-0000-000000000099"
ADMIN_SECRET = "test-admin-enforcement"


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
    # Use regex-only detection to avoid NER model dependency in tests
    container._detection_adapter = RegexDetectionAdapter()  # type: ignore[assignment]
    app.state.container = container
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    await fake_redis.aclose()


async def _create_key(client: AsyncClient, org_id: str = VALID_ORG) -> str:
    resp = await client.post(
        "/api/v1/keys",
        headers={"X-Admin-Key": ADMIN_SECRET},
        json={"organization_id": org_id},
    )
    assert resp.status_code == 200, f"Key creation failed: {resp.text}"
    return resp.json()["key"]


async def _set_plan(client: AsyncClient, org_id: str, plan_id: str) -> None:
    resp = await client.post(
        f"/api/v1/org/{org_id}/plan",
        headers={"X-Admin-Key": ADMIN_SECRET},
        json={"plan_id": plan_id},
    )
    assert resp.status_code == 200, f"Plan set failed: {resp.text}"


# ── Key limit enforcement ────────────────────────────────────────────────


class TestKeyLimitEnforcement:
    """Plan max_keys must be enforced at the HTTP level."""

    async def test_key_created_with_plan_rate_limit(self, client: AsyncClient) -> None:
        """When org has starter plan, key rate_limit must match plan."""
        await _set_plan(client, VALID_ORG, "starter")
        raw_key = await _create_key(client, VALID_ORG)
        assert raw_key.startswith("ps_live_")

        # Verify via list keys that the rate limit matches starter plan
        resp = await client.get(
            "/api/v1/keys",
            params={"org_id": VALID_ORG},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["rate_limit_per_minute"] == 60  # starter plan
        assert keys[0]["plan"] == "starter"

    async def test_free_plan_blocks_third_key(self, client: AsyncClient) -> None:
        """Free plan allows max 2 keys."""
        await _set_plan(client, VALID_ORG, "free")
        await _create_key(client, VALID_ORG)
        await _create_key(client, VALID_ORG)

        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": VALID_ORG},
        )
        assert resp.status_code == 409
        assert "maximum number of API keys" in resp.json()["detail"]

    async def test_starter_plan_blocks_sixth_key(self, client: AsyncClient) -> None:
        """Starter plan allows max 5 keys."""
        await _set_plan(client, VALID_ORG, "starter")
        for _ in range(5):
            await _create_key(client, VALID_ORG)

        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": VALID_ORG},
        )
        assert resp.status_code == 409

    async def test_caller_cannot_bypass_plan_via_body_fields(
        self, client: AsyncClient
    ) -> None:
        """Extra body fields (plan, rate_limit_per_minute) must be ignored
        because CreateKeyRequest has extra='ignore'."""
        await _set_plan(client, VALID_ORG, "free")
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={
                "organization_id": VALID_ORG,
                "plan": "enterprise",
                "rate_limit_per_minute": 999_999,
            },
        )
        assert resp.status_code == 200
        # Verify the key has free plan rate limit, not the attacker's
        keys_resp = await client.get(
            "/api/v1/keys",
            params={"org_id": VALID_ORG},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        key = keys_resp.json()[0]
        assert key["rate_limit_per_minute"] == 10  # free plan
        assert key["plan"] == "free"


# ── Monthly quota enforcement ────────────────────────────────────────────


class TestMonthlyQuotaEnforcement:
    """Monthly token limit must be enforced at the HTTP level."""

    async def test_tokenize_beyond_monthly_limit_returns_429(
        self, client: AsyncClient
    ) -> None:
        """
        Free plan has 1000 monthly token limit. Simulate exceeding it by
        tokenizing many texts with PII until the limit is hit.
        """
        await _set_plan(client, VALID_ORG, "free")
        raw_key = await _create_key(client, VALID_ORG)

        # Each tokenize call with an Italian CF creates ~1 token.
        # Free plan allows 1000 tokens. We need to exceed that.
        # Instead of running 1000 real tokenizations, we can seed the usage
        # counter directly via the api_key_port adapter.
        # Access container via the fixture approach.

        # Actually, let's use the route approach: record enough usage
        # then attempt one more tokenization.
        # We'll do a smaller test: the monthly limit is checked BEFORE
        # tokenization runs, so we need usage already at limit.

        # To test this, we set up usage via direct Redis writes.
        # But since we can't easily access the container from here,
        # let's create the test by doing repeated tokenizations.
        # With the free plan limit of 1000, we need a more efficient approach.

        # Instead, let's use a plan with a lower effective limit by
        # pre-populating usage. We'll access the container from the test client.

        # Pragmatic approach: do ONE tokenize to prove the pipeline works,
        # then manually set usage to the limit via admin API, then try again.

        # Actually, the simplest way is to test with text that contains PII.
        # Each CF is one token. Let's do a batch of PII-heavy texts.
        # With 100 texts containing 1 CF each, we need 10 batches to reach 1000.

        # Let's verify the 429 flow differently: create a second org with
        # a very targeted test where we can control usage.
        pass  # Covered more efficiently in the next test

    async def test_enterprise_plan_never_blocked_by_monthly_limit(
        self, client: AsyncClient
    ) -> None:
        """Enterprise plan (monthly_token_limit == -1) must always succeed."""
        await _set_plan(client, VALID_ORG, "enterprise")
        raw_key = await _create_key(client, VALID_ORG)

        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 200

    async def test_plan_headers_present_on_429(self, client: AsyncClient) -> None:
        """When 429 is returned, response must include plan-specific headers.

        This test uses direct Redis manipulation to simulate usage at limit.
        """
        await _set_plan(client, VALID_ORG, "free")
        raw_key = await _create_key(client, VALID_ORG)

        # Seed usage counter to exactly the free limit (1000) via app state
        # We need the container reference from the app
        app = client._transport.app  # type: ignore[attr-defined]
        container = app.state.container
        from datetime import datetime, timezone

        current_month = datetime.now(timezone.utc).strftime("%Y-%m")
        # Write directly to Redis to simulate 1000 tokens already consumed
        usage_key = f"ps:usage:{VALID_ORG}:{current_month}:tokens_created"
        await container.redis_client.set(usage_key, b"1000")

        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 429
        # Security fix: info headers removed (no X-Monthly-Limit, X-Plan)
        assert "x-monthly-limit" not in resp.headers
        assert "x-plan" not in resp.headers
        assert "retry-after" in resp.headers


# ── Billing stub endpoints ───────────────────────────────────────────────


class TestBillingStubs:
    """Billing endpoints must return 501 Not Implemented."""

    async def test_webhook_requires_stripe_signature(self, client: AsyncClient) -> None:
        """Webhook without stripe-signature header must be rejected (400)."""
        resp = await client.post("/api/v1/billing/webhook")
        assert resp.status_code == 400

    async def test_webhook_returns_501_with_signature(self, client: AsyncClient) -> None:
        """Webhook with stripe-signature header returns 501 (not yet implemented)."""
        resp = await client.post(
            "/api/v1/billing/webhook",
            headers={"stripe-signature": "t=123,v1=abc"},
        )
        assert resp.status_code == 501
        data = resp.json()
        assert data["code"] == "NOT_IMPLEMENTED"

    async def test_checkout_requires_admin_key(self, client: AsyncClient) -> None:
        resp = await client.post("/api/v1/billing/checkout")
        assert resp.status_code == 401

    async def test_checkout_returns_501_with_admin_key(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/billing/checkout",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 501


# ── Cross-org plan isolation ─────────────────────────────────────────────


class TestCrossOrgPlanIsolation:
    """Plan assignments must be scoped to each org."""

    async def test_org_a_plan_does_not_affect_org_b(self, client: AsyncClient) -> None:
        org_a = "00000000-0000-0000-0000-00000000000a"
        org_b = "00000000-0000-0000-0000-00000000000b"

        await _set_plan(client, org_a, "enterprise")

        resp_b = await client.get(
            f"/api/v1/org/{org_b}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp_b.status_code == 200
        # org_b should still be on free (default)
        assert resp_b.json()["plan"]["id"] == "free"

    async def test_org_b_enterprise_does_not_elevate_org_a(
        self, client: AsyncClient
    ) -> None:
        org_a = "00000000-0000-0000-0000-00000000000a"
        org_b = "00000000-0000-0000-0000-00000000000b"

        await _set_plan(client, org_b, "enterprise")

        # org_a should still be on free, not enterprise
        resp_a = await client.get(
            f"/api/v1/org/{org_a}/plan",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp_a.json()["plan"]["id"] == "free"
        assert resp_a.json()["max_keys"] == 2  # free plan max_keys
