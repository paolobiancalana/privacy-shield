"""
API Key Authentication E2E integration tests.

Adversarial Analysis:
  1. Cross-tenant: A key for org-A must not allow tokenization with body.organization_id=org-B.
     The production code overrides body org_id with auth org_id (from key). Test that the
     key's org_id takes precedence and that vault data is org-scoped.
  2. Rate limit exhaustion: After exactly N calls at limit=N, the (N+1)th call must return 429
     with Retry-After header. Test that the header value is exactly "60".
  3. Admin key timing attack: The auth module uses hmac.compare_digest for admin key
     comparison, which is constant-time. But an empty ADMIN_API_KEY disables the endpoint (403).

Boundary Map:
  X-Api-Key header: present/valid, present/invalid, missing, empty string
  X-Admin-Key header: present/valid, present/invalid, missing
  rate_limit_per_minute: 3 (low, easy to exhaust in test)
  environment: "live", "test"
"""
from __future__ import annotations

import base64
import hashlib
import os

# Set env vars BEFORE any app import to avoid module-level Settings() failure
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app

VALID_ORG_A = "00000000-0000-0000-0000-00000000000a"
VALID_ORG_B = "00000000-0000-0000-0000-00000000000b"
VALID_REQ_ID = "00000000-0000-0000-0000-000000000099"
ADMIN_SECRET = "test-admin-secret-key-2026"


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
        DEFAULT_RATE_LIMIT=100,
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncClient:
    """Create a test client with fakeredis injected into the container."""
    app = create_app(settings=test_settings)

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port  # triggers KEK validation
    app.state.container = container

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await fake_redis.aclose()


async def _create_key(
    client: AsyncClient,
    org_id: str = VALID_ORG_A,
    rate_limit: int = 100,
    environment: str = "live",
) -> str:
    """Helper: create a key via admin API and return the raw key string."""
    resp = await client.post(
        "/api/v1/keys",
        headers={"X-Admin-Key": ADMIN_SECRET},
        json={
            "organization_id": org_id,
            "rate_limit_per_minute": rate_limit,
            "environment": environment,
        },
    )
    assert resp.status_code == 200, f"Key creation failed: {resp.text}"
    return resp.json()["key"]


# -----------------------------------------------------------------------
# Unauthenticated Access (must fail)
# -----------------------------------------------------------------------


class TestUnauthenticatedAccess:
    """All operational endpoints must reject requests without X-Api-Key."""

    async def test_tokenize_without_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 401
        assert "Missing" in resp.json()["detail"] or "Api-Key" in resp.json()["detail"]

    async def test_rehydrate_without_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/rehydrate",
            json={"text": "test", "organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401

    async def test_flush_without_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/flush",
            json={"organization_id": VALID_ORG_A, "request_id": VALID_REQ_ID},
        )
        assert resp.status_code == 401

    async def test_tokenize_with_invalid_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": "ps_live_totally_invalid_key_here"},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 401
        assert "Invalid" in resp.json()["detail"] or "revoked" in resp.json()["detail"]

    async def test_tokenize_with_empty_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": ""},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# Admin Endpoint Auth
# -----------------------------------------------------------------------


class TestAdminAuth:
    """Admin endpoints require X-Admin-Key."""

    async def test_create_key_without_admin_key_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/keys",
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401

    async def test_create_key_with_wrong_admin_key_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "wrong-secret"},
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 401

    async def test_list_keys_without_admin_key_returns_401(
        self, client: AsyncClient
    ) -> None:
        resp = await client.get("/api/v1/keys")
        assert resp.status_code == 401

    async def test_usage_without_admin_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.get(f"/api/v1/usage/{VALID_ORG_A}")
        assert resp.status_code == 401

    async def test_revoke_without_admin_key_returns_401(self, client: AsyncClient) -> None:
        resp = await client.delete("/api/v1/keys/somehash")
        assert resp.status_code == 401


# -----------------------------------------------------------------------
# Unauthenticated Endpoints (health, metrics remain open)
# -----------------------------------------------------------------------


class TestPublicEndpoints:
    """Health remains publicly accessible; /metrics now requires X-Admin-Key."""

    async def test_health_no_auth_required(self, client: AsyncClient) -> None:
        resp = await client.get("/health")
        assert resp.status_code == 200

    async def test_metrics_requires_admin_key(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics")
        assert resp.status_code == 401

    async def test_metrics_returns_200_with_admin_key(self, client: AsyncClient) -> None:
        resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        assert resp.status_code == 200


# -----------------------------------------------------------------------
# API Key Lifecycle (Happy Path)
# -----------------------------------------------------------------------


class TestApiKeyLifecycle:
    """Full lifecycle: create -> use -> revoke -> reject."""

    async def test_create_key_returns_raw_key_and_metadata(
        self, client: AsyncClient
    ) -> None:
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["key"].startswith("ps_live_")
        assert len(data["key"]) == 40
        assert data["key_id"].startswith("kid_")
        assert data["organization_id"] == VALID_ORG_A

    async def test_create_test_environment_key(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": VALID_ORG_A, "environment": "test"},
        )
        assert resp.status_code == 200
        assert resp.json()["key"].startswith("ps_test_")

    async def test_create_then_tokenize_succeeds(self, client: AsyncClient) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A)

        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tokenized_texts"]) == 1
        assert "[#cf:" in data["tokenized_texts"][0]
        assert "RSSMRA85M01H501Z" not in data["tokenized_texts"][0]

    async def test_revoked_key_returns_401(self, client: AsyncClient) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        # Revoke
        resp = await client.delete(
            f"/api/v1/keys/{key_hash}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["revoked"] is True

        # Try to use revoked key
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 401

    async def test_revoke_nonexistent_key_returns_404(self, client: AsyncClient) -> None:
        resp = await client.delete(
            "/api/v1/keys/0000000000000000000000000000000000000000000000000000000000000000",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 404

    async def test_list_keys_returns_created_keys(self, client: AsyncClient) -> None:
        await _create_key(client, org_id=VALID_ORG_A)
        await _create_key(client, org_id=VALID_ORG_B)

        resp = await client.get(
            "/api/v1/keys", headers={"X-Admin-Key": ADMIN_SECRET}
        )
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 2

    async def test_list_keys_filtered_by_org(self, client: AsyncClient) -> None:
        await _create_key(client, org_id=VALID_ORG_A)
        await _create_key(client, org_id=VALID_ORG_B)

        resp = await client.get(
            "/api/v1/keys",
            params={"org_id": VALID_ORG_A},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        keys = resp.json()
        assert len(keys) == 1
        assert keys[0]["org_id"] == VALID_ORG_A


# -----------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------


class TestRateLimiting:
    async def test_rate_limit_returns_429_with_retry_after(
        self, client: AsyncClient
    ) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A, rate_limit=3)

        # Exhaust rate limit (3 allowed calls)
        for _ in range(3):
            resp = await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": raw_key},
                json={
                    "texts": ["test"],
                    "organization_id": VALID_ORG_A,
                    "request_id": VALID_REQ_ID,
                },
            )
            assert resp.status_code == 200

        # 4th call must be rate-limited
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 429
        assert resp.json()["detail"] == "Rate limit exceeded"
        assert resp.headers["retry-after"] == "60"
        assert resp.headers["x-ratelimit-limit"] == "3"

    async def test_different_keys_have_independent_rate_limits(
        self, client: AsyncClient
    ) -> None:
        key_a = await _create_key(client, org_id=VALID_ORG_A, rate_limit=2)
        key_b = await _create_key(client, org_id=VALID_ORG_B, rate_limit=2)

        # Exhaust key A
        for _ in range(2):
            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key_a},
                json={
                    "texts": ["test"],
                    "organization_id": VALID_ORG_A,
                    "request_id": VALID_REQ_ID,
                },
            )

        # Key A should be rate-limited
        resp_a = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp_a.status_code == 429

        # Key B should still work
        resp_b = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_b},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_B,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp_b.status_code == 200


# -----------------------------------------------------------------------
# Usage Tracking
# -----------------------------------------------------------------------


class TestUsageTracking:
    async def test_tokenize_call_increments_usage(self, client: AsyncClient) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A)

        await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )

        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tokenize_calls"] >= 1
        assert data["org_id"] == VALID_ORG_A

    async def test_rehydrate_call_increments_usage(self, client: AsyncClient) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A)

        # First tokenize to have something to rehydrate
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["Email: mario@test.com"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        tokenized = tok_resp.json()["tokenized_texts"][0]

        # Rehydrate
        await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": raw_key},
            json={"text": tokenized, "organization_id": VALID_ORG_A, "request_id": VALID_REQ_ID},
        )

        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["rehydrate_calls"] >= 1

    async def test_flush_call_increments_usage(self, client: AsyncClient) -> None:
        raw_key = await _create_key(client, org_id=VALID_ORG_A)

        await client.post(
            "/api/v1/flush",
            headers={"X-Api-Key": raw_key},
            json={"organization_id": VALID_ORG_A, "request_id": VALID_REQ_ID},
        )

        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        assert resp.json()["flush_calls"] >= 1

    async def test_usage_zero_for_unused_org(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG_B}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tokenize_calls"] == 0
        assert data["rehydrate_calls"] == 0
        assert data["flush_calls"] == 0
        assert data["total_tokens_created"] == 0

    async def test_usage_with_explicit_month(self, client: AsyncClient) -> None:
        resp = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            params={"month": "1999-01"},
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["month"] == "1999-01"
        assert data["tokenize_calls"] == 0


# -----------------------------------------------------------------------
# Cross-Tenant Isolation (THE critical test)
# -----------------------------------------------------------------------


class TestCrossTenantIsolation:
    """
    Key for org-A must NOT allow accessing org-B's data. The route overrides
    body.organization_id with auth["org_id"] so the key's org is authoritative.
    """

    async def test_key_org_overrides_body_org(self, client: AsyncClient) -> None:
        """
        A key for org-A tokenizing with body.organization_id=org-B must:
        - Use org-A for vault scoping (not org-B)
        - Record usage for org-A (not org-B)
        """
        key_a = await _create_key(client, org_id=VALID_ORG_A)

        # Send request with org-B in body but key belongs to org-A
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG_B,  # Attacker tries org-B
                "request_id": VALID_REQ_ID,
            },
        )
        # Should succeed (key is valid) but use org-A's vault
        assert resp.status_code == 200

        # Usage must be recorded for org-A, NOT org-B
        usage_a = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        usage_b = await client.get(
            f"/api/v1/usage/{VALID_ORG_B}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        assert usage_a.json()["tokenize_calls"] >= 1
        assert usage_b.json()["tokenize_calls"] == 0

    async def test_rehydrate_across_orgs_does_not_leak(
        self, client: AsyncClient
    ) -> None:
        """
        Tokenize with org-A's key, then attempt rehydrate with org-B's key.
        The rehydration must NOT return the original PII because the vault is org-scoped.
        """
        key_a = await _create_key(client, org_id=VALID_ORG_A)
        key_b = await _create_key(client, org_id=VALID_ORG_B)

        # Tokenize with org-A
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["Email: mario@test.com"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        assert tok_resp.status_code == 200
        tokenized = tok_resp.json()["tokenized_texts"][0]
        assert "[#em:" in tokenized

        # Attempt rehydrate with org-B's key
        reh_resp = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key_b},
            json={
                "text": tokenized,
                "organization_id": VALID_ORG_B,
                "request_id": VALID_REQ_ID,
            },
        )
        assert reh_resp.status_code == 200
        data = reh_resp.json()
        # Must NOT contain the original PII -- token stays unrehydrated
        assert "mario@test.com" not in data["text"]
        assert data["rehydrated_count"] == 0

    async def test_flush_across_orgs_does_not_affect_other(
        self, client: AsyncClient
    ) -> None:
        """Flush with org-B's key must not delete org-A's vault entries."""
        key_a = await _create_key(client, org_id=VALID_ORG_A)
        key_b = await _create_key(client, org_id=VALID_ORG_B)

        # Tokenize with org-A
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["Email: mario@test.com"],
                "organization_id": VALID_ORG_A,
                "request_id": VALID_REQ_ID,
            },
        )
        tokenized = tok_resp.json()["tokenized_texts"][0]

        # Flush with org-B (different org, same request_id)
        await client.post(
            "/api/v1/flush",
            headers={"X-Api-Key": key_b},
            json={"organization_id": VALID_ORG_B, "request_id": VALID_REQ_ID},
        )

        # Rehydrate with org-A should still work
        reh_resp = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key_a},
            json={"text": tokenized, "organization_id": VALID_ORG_A, "request_id": VALID_REQ_ID},
        )
        assert reh_resp.status_code == 200
        assert "mario@test.com" in reh_resp.json()["text"]

    async def test_usage_isolation_no_cross_org_leakage(
        self, client: AsyncClient
    ) -> None:
        """Usage counters for org-A and org-B must be completely independent."""
        key_a = await _create_key(client, org_id=VALID_ORG_A)
        key_b = await _create_key(client, org_id=VALID_ORG_B)

        # 3 tokenize calls for org-A
        for _ in range(3):
            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key_a},
                json={
                    "texts": ["test"],
                    "organization_id": VALID_ORG_A,
                    "request_id": VALID_REQ_ID,
                },
            )

        # 1 tokenize call for org-B
        await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_b},
            json={
                "texts": ["test"],
                "organization_id": VALID_ORG_B,
                "request_id": VALID_REQ_ID,
            },
        )

        usage_a = await client.get(
            f"/api/v1/usage/{VALID_ORG_A}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )
        usage_b = await client.get(
            f"/api/v1/usage/{VALID_ORG_B}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )

        assert usage_a.json()["tokenize_calls"] == 3
        assert usage_b.json()["tokenize_calls"] == 1


# -----------------------------------------------------------------------
# Admin Key Disabled (empty ADMIN_API_KEY)
# -----------------------------------------------------------------------


class TestAdminKeyDisabled:
    """When ADMIN_API_KEY is empty, admin endpoints return 403."""

    @pytest.fixture
    async def client_no_admin(self) -> AsyncClient:
        settings = Settings(
            PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
            REDIS_URL="redis://localhost:6379",
            TOKEN_TTL_SECONDS=60,
            HOST="127.0.0.1",
            PORT=9999,
            LOG_LEVEL="WARNING",
            APP_VERSION="0.0.0-test",
            ADMIN_API_KEY="",  # Empty -> disabled
            DEFAULT_RATE_LIMIT=100,
        )
        app = create_app(settings=settings)
        fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
        container = Container(config=settings)
        container._redis = fake_redis
        _ = container.crypto_port
        app.state.container = container

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
        await fake_redis.aclose()

    async def test_create_key_returns_403_when_admin_disabled(
        self, client_no_admin: AsyncClient
    ) -> None:
        resp = await client_no_admin.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "any-value"},
            json={"organization_id": VALID_ORG_A},
        )
        assert resp.status_code == 403
        assert "disabled" in resp.json()["detail"].lower()
