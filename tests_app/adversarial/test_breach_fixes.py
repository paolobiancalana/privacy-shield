"""
Adversarial tests for 5 Red Team breach fixes.

These tests PROVE that the identified breaches are fixed by reproducing the
exact attack scenarios described in the Red Team report and asserting that
the system now rejects them.

Adversarial Analysis:
  1. Admin rate limit can be brute-forced if the IP-based sliding window is
     missing or uses a non-expiring counter. The 11th wrong-key request within
     the same minute-bucket from the same IP MUST return 429.
  2. Token scoping: tokens stored with request_id="req-A" MUST NOT be
     resolvable via request_id="req-B", even within the same org and key.
     Without request_id in the vault key, any API caller in the same org
     could inject [#cf:xxx] into text and rehydrate other sessions' PII.
  3. Injection: A user who manually embeds [#cf:xxx] in their text and
     calls /rehydrate with a different request_id MUST NOT resolve the token.
  4. Auth failure counters must increment reliably for every auth rejection
     mode: invalid key, revoked key, rate-limited, admin-rate-limited.
  5. Per-org token quota: exceeding max_tokens_per_org MUST return 503
     (QuotaExceededError), and a DIFFERENT org's quota is independent.

Boundary Map:
  admin_rate_limit:     [1, 10] per minute-bucket → test at 10, 11
  request_id scoping:   exact UUID match required → test A vs B
  max_tokens_per_org:   configurable limit → test at limit, limit+1
  ps_auth_failures_total: must increment by exact count per failure mode
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
import time

# Set env vars BEFORE any app import to avoid module-level Settings() failure
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.domain.entities import QuotaExceededError
from app.infrastructure.config import Settings
from app.infrastructure.metrics import PrivacyShieldMetrics
from app.main import create_app

ORG_A = "00000000-0000-0000-0000-00000000000a"
ORG_B = "00000000-0000-0000-0000-00000000000b"
REQ_A = "00000000-0000-0000-0000-0000000000a1"
REQ_B = "00000000-0000-0000-0000-0000000000b1"
ADMIN_SECRET = "test-admin-secret-key-breach-fix-2026"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-breach-test",
        ADMIN_API_KEY=ADMIN_SECRET,
        DEFAULT_RATE_LIMIT=100,
        MAX_TOKENS_PER_ORG=10_000,
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncClient:
    """Test client with fakeredis — isolated per test."""
    app = create_app(settings=test_settings)
    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)
    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container

    # Pre-assign enterprise plan to test orgs so rate-limit and quota tests
    # can create many keys without hitting the free plan's max_keys=2 limit.
    await container.org_plan_port.set_org_plan(ORG_A, "enterprise")
    await container.org_plan_port.set_org_plan(ORG_B, "enterprise")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await fake_redis.aclose()


@pytest.fixture
async def quota_client() -> AsyncClient:
    """Test client with max_tokens_per_org=5 for quota testing."""
    settings = Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-quota-test",
        ADMIN_API_KEY=ADMIN_SECRET,
        DEFAULT_RATE_LIMIT=100,
        MAX_TOKENS_PER_ORG=5,
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


async def _create_key(
    client: AsyncClient,
    org_id: str = ORG_A,
    rate_limit: int = 100,
) -> str:
    """Helper: create an API key via admin endpoint and return the raw key."""
    resp = await client.post(
        "/api/v1/keys",
        headers={"X-Admin-Key": ADMIN_SECRET},
        json={"organization_id": org_id, "rate_limit_per_minute": rate_limit},
    )
    assert resp.status_code == 200, f"Key creation failed: {resp.text}"
    return resp.json()["key"]


def _get_metrics(client_or_container) -> dict:
    """Synchronous metrics snapshot accessor from the container."""
    # The container is stored on the app state; we access it in tests
    # after making requests via the client's transport -> app -> state.
    return {}


# ===================================================================
# BREACH #1: Admin Rate Limit (IP-based, 10 req/min)
# ===================================================================


class TestBreachAdminRateLimit:
    """
    Breach #1: Before the fix, the admin endpoint had no rate limit. An
    attacker could brute-force X-Admin-Key at 1000+ req/s. The fix adds
    a Redis sliding-window counter of 10 req/min per client IP, checked
    BEFORE the key comparison.

    Attack reproduction:
      - 11 requests with wrong admin key from the same IP.
      - The 11th MUST return 429 (rate limited), not 401 (invalid key).
    """

    async def test_11th_admin_request_with_wrong_key_returns_429(
        self, client: AsyncClient
    ) -> None:
        """
        Send 11 admin requests with an incorrect key. The first 10 should
        return 401 (invalid key). The 11th should return 429 (rate limited)
        because the IP-based counter has reached the limit of 10.
        """
        for i in range(10):
            resp = await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": f"wrong-key-attempt-{i}"},
                json={"organization_id": ORG_A},
            )
            assert resp.status_code == 401, (
                f"Request {i+1}/10 returned {resp.status_code}, expected 401"
            )

        # 11th request: MUST be rate limited, not just 401
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "wrong-key-attempt-final"},
            json={"organization_id": ORG_A},
        )
        assert resp.status_code == 429, (
            f"11th admin request returned {resp.status_code}, expected 429 "
            f"(admin rate limit). Response: {resp.text}"
        )
        assert "admin" in resp.json()["detail"].lower() or "rate" in resp.json()["detail"].lower()

    async def test_admin_rate_limit_applies_even_with_correct_key(
        self, client: AsyncClient
    ) -> None:
        """
        Even with the CORRECT admin key, the 11th request in the same
        minute-bucket must be rate limited. Rate check happens BEFORE key
        comparison to prevent timing attacks.
        """
        for i in range(10):
            resp = await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": ADMIN_SECRET},
                json={"organization_id": ORG_A},
            )
            assert resp.status_code == 200, (
                f"Request {i+1}/10 with correct key returned {resp.status_code}"
            )

        # 11th request: rate limited even though key is correct
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": ORG_A},
        )
        assert resp.status_code == 429

    async def test_admin_rate_limit_counter_in_metrics(
        self, client: AsyncClient
    ) -> None:
        """
        After triggering admin rate limit, ps_auth_failures_total with
        reason=admin_rate_limited must be incremented.

        Metrics are read directly from the container's in-memory store to
        avoid calling /metrics after the admin rate limit is exhausted
        (which would itself be blocked by the same rate limit counter).
        """
        # Exhaust the rate limit
        for i in range(10):
            await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": "wrong"},
                json={"organization_id": ORG_A},
            )

        # Trigger the rate limit
        await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "wrong"},
            json={"organization_id": ORG_A},
        )

        # Read metrics directly from container — /metrics would be rate-limited
        # because the admin rate limit counter is shared across all admin endpoints.
        container = client._transport.app.state.container  # type: ignore[attr-defined]
        data = container.metrics.snapshot()

        auth_failures = data["counters"]["ps_auth_failures_total"]
        by_label = auth_failures["by_label"]

        # Must have admin_rate_limited entries
        admin_rate_key = "reason=admin_rate_limited"
        assert admin_rate_key in by_label, (
            f"Expected '{admin_rate_key}' in auth failure labels. "
            f"Got: {list(by_label.keys())}"
        )
        assert by_label[admin_rate_key] >= 1

    async def test_admin_rate_limit_does_not_affect_non_admin_endpoints(
        self, client: AsyncClient
    ) -> None:
        """
        The admin rate limit is per-IP for admin endpoints only. Non-admin
        endpoints (health) must remain accessible even after the admin rate
        limit is exhausted.

        Note: /metrics is now an admin endpoint and shares the same rate limit
        counter, so it cannot be called after exhausting the limit. Only /health
        (which has no auth) is tested here. Metrics content is verified via the
        in-memory container snapshot to confirm it is unaffected.
        """
        # Exhaust admin rate limit
        for _ in range(11):
            await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": "wrong"},
                json={"organization_id": ORG_A},
            )

        # /health (no auth) must remain accessible
        assert (await client.get("/health")).status_code == 200

        # /metrics in-memory snapshot is always accessible (not affected by rate limit)
        container = client._transport.app.state.container  # type: ignore[attr-defined]
        snap = container.metrics.snapshot()
        assert "counters" in snap


# ===================================================================
# BREACH #2+3: Token Scoping + Injection Prevention
# THE MOST CRITICAL TEST — exact breach reproduction
# ===================================================================


class TestBreachTokenScopingAndInjection:
    """
    Breach #2: Before the fix, vault keys did NOT include request_id.
    Key was ps:{org_id}:{token_hash}. Any caller with a valid API key
    for the same org could rehydrate tokens from any request, enabling
    cross-session PII exfiltration.

    Breach #3: Combined with #2, a user could craft text containing
    [#cf:xxx] (a token from another request) and call /rehydrate to
    recover the original PII.

    Fix: Vault keys now include request_id: ps:{org_id}:{request_id}:{token_hash}
    Rehydrate only resolves tokens that were stored with the EXACT same
    (org_id, request_id) — enforced at the Redis key level.
    """

    async def test_tokenize_reqA_rehydrate_reqB_returns_zero_rehydrated(
        self, client: AsyncClient
    ) -> None:
        """
        EXACT BREACH REPRODUCTION:
        1. Tokenize with request_id=REQ_A -> get token [#cf:xxx]
        2. Rehydrate with request_id=REQ_B (same org, same key) -> MUST return 0
        3. The token text stays as-is (not resolved)
        """
        key = await _create_key(client, org_id=ORG_A)

        # Step 1: Tokenize with REQ_A
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["Il CF di Mario Rossi e' RSSMRA85M01H501Z"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert tok_resp.status_code == 200
        tokenized_text = tok_resp.json()["tokenized_texts"][0]
        tokens = tok_resp.json()["tokens"]

        # Must have tokenized the CF
        assert len(tokens) >= 1
        cf_token = next((t for t in tokens if t["type"] == "cf"), None)
        assert cf_token is not None, f"No CF token found. Tokens: {tokens}"
        assert "[#cf:" in tokenized_text
        assert "RSSMRA85M01H501Z" not in tokenized_text

        # Step 2: Rehydrate with REQ_B (different request_id, same org+key)
        reh_resp = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_text,
                "organization_id": ORG_A,
                "request_id": REQ_B,  # DIFFERENT request_id
            },
        )
        assert reh_resp.status_code == 200
        reh_data = reh_resp.json()

        # CRITICAL ASSERTION: rehydrated_count MUST be 0
        assert reh_data["rehydrated_count"] == 0, (
            f"BREACH: Token from REQ_A was resolved using REQ_B! "
            f"rehydrated_count={reh_data['rehydrated_count']}, "
            f"text={reh_data['text']!r}"
        )
        # The original PII must NOT appear in the result
        assert "RSSMRA85M01H501Z" not in reh_data["text"], (
            "BREACH: Original PII leaked via cross-request rehydration!"
        )

        # Step 3: Rehydrate with REQ_A (correct request_id) -> MUST succeed
        reh_correct = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_text,
                "organization_id": ORG_A,
                "request_id": REQ_A,  # CORRECT request_id
            },
        )
        assert reh_correct.status_code == 200
        correct_data = reh_correct.json()
        assert correct_data["rehydrated_count"] >= 1, (
            f"Correct request_id failed to rehydrate: {correct_data}"
        )
        assert "RSSMRA85M01H501Z" in correct_data["text"], (
            f"Correct rehydration did not restore PII: {correct_data['text']!r}"
        )

    async def test_injection_crafted_token_in_different_request_not_resolved(
        self, client: AsyncClient
    ) -> None:
        """
        INJECTION ATTACK:
        1. Attacker tokenizes text with REQ_A, obtains token [#cf:xxx]
        2. Attacker crafts a NEW text containing the stolen token string
        3. Attacker calls /rehydrate with REQ_B (their own request)
        4. The system MUST NOT resolve the injected token
        """
        key = await _create_key(client, org_id=ORG_A)

        # Step 1: Tokenize to obtain a real token
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["Email: mario.rossi@pec.it"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert tok_resp.status_code == 200
        tokens = tok_resp.json()["tokens"]
        assert len(tokens) >= 1

        # Extract the token string (e.g., "[#em:a3f2c1d9]")
        stolen_token = tokens[0]["token"]
        assert re.match(r"\[#[a-z]{2,3}:[a-f0-9]{4,8}(?:_\d+)?\]", stolen_token)

        # Step 2: Craft malicious text containing the stolen token
        malicious_text = f"L'email del cliente e' {stolen_token} urgente"

        # Step 3: Call rehydrate with a DIFFERENT request_id
        reh_resp = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": malicious_text,
                "organization_id": ORG_A,
                "request_id": REQ_B,  # Attacker's own request
            },
        )
        assert reh_resp.status_code == 200
        data = reh_resp.json()

        # CRITICAL: The injected token must NOT be resolved
        assert data["rehydrated_count"] == 0, (
            f"BREACH: Injected token from REQ_A was resolved in REQ_B context! "
            f"text={data['text']!r}"
        )
        assert "mario.rossi@pec.it" not in data["text"], (
            "BREACH: PII leaked via token injection attack!"
        )

    async def test_two_concurrent_requests_same_org_tokens_isolated(
        self, client: AsyncClient
    ) -> None:
        """
        Two concurrent tokenization requests for the same org, each with
        different request_ids, produce tokens that are isolated from each
        other. Rehydration of request A's tokens fails when using request B's
        context, and vice versa.
        """
        import asyncio

        key = await _create_key(client, org_id=ORG_A)

        # Concurrent tokenization
        async def tokenize_request(request_id: str, text: str) -> dict:
            resp = await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key},
                json={
                    "texts": [text],
                    "organization_id": ORG_A,
                    "request_id": request_id,
                },
            )
            assert resp.status_code == 200
            return resp.json()

        result_a, result_b = await asyncio.gather(
            tokenize_request(REQ_A, "CF di Mario: RSSMRA85M01H501Z"),
            tokenize_request(REQ_B, "Email: luigi.verdi@example.com"),
        )

        tokenized_a = result_a["tokenized_texts"][0]
        tokenized_b = result_b["tokenized_texts"][0]

        # Verify tokens were created for both
        assert len(result_a["tokens"]) >= 1
        assert len(result_b["tokens"]) >= 1

        # Cross-request rehydration attempt: REQ_A's text with REQ_B
        reh_cross_ab = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_a,
                "organization_id": ORG_A,
                "request_id": REQ_B,
            },
        )
        assert reh_cross_ab.json()["rehydrated_count"] == 0, (
            "BREACH: REQ_A tokens resolved with REQ_B context"
        )

        # Cross-request rehydration attempt: REQ_B's text with REQ_A
        reh_cross_ba = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_b,
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert reh_cross_ba.json()["rehydrated_count"] == 0, (
            "BREACH: REQ_B tokens resolved with REQ_A context"
        )

        # Same-request rehydration: must work
        reh_a = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_a,
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert reh_a.json()["rehydrated_count"] >= 1

        reh_b = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key},
            json={
                "text": tokenized_b,
                "organization_id": ORG_A,
                "request_id": REQ_B,
            },
        )
        assert reh_b.json()["rehydrated_count"] >= 1

    async def test_vault_key_includes_request_id_in_redis(
        self, client: AsyncClient
    ) -> None:
        """
        Verify at the Redis level that the vault key format includes
        request_id: ps:{org_id}:{request_id}:{token_hash}

        This is a structural proof that the breach fix is in place.
        """
        key = await _create_key(client, org_id=ORG_A)

        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["RSSMRA85M01H501Z"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert tok_resp.status_code == 200
        tokens = tok_resp.json()["tokens"]
        assert len(tokens) >= 1

        # Access the container's Redis to verify key structure
        container = client._transport.app.state.container  # type: ignore[attr-defined]
        redis = container.redis_client

        # Scan for all ps: keys (excluding dek, req, apikey, rate, usage)
        token_keys = []
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor=cursor, match=f"ps:{ORG_A}:{REQ_A}:*", count=100)
            token_keys.extend(keys)
            if cursor == 0:
                break

        assert len(token_keys) >= 1, (
            "No vault keys found matching ps:{org}:{req}:{hash} pattern"
        )

        # Verify key format includes request_id
        for key_bytes in token_keys:
            key_str = key_bytes.decode("utf-8") if isinstance(key_bytes, bytes) else key_bytes
            parts = key_str.split(":")
            assert len(parts) == 4, (
                f"Vault key {key_str!r} does not have 4 parts (ps:org:req:hash). "
                f"Got {len(parts)} parts: {parts}"
            )
            assert parts[0] == "ps"
            assert parts[1] == ORG_A
            assert parts[2] == REQ_A
            # parts[3] is the token hash


# ===================================================================
# BREACH #4: Auth Failure Counter (ps_auth_failures_total)
# ===================================================================


class TestBreachAuthFailureCounter:
    """
    Breach #4: Auth failures must be counted in ps_auth_failures_total
    with the exact failure reason label. Before the fix, some auth
    failure paths did not increment the counter, making it impossible
    to detect brute-force attacks via metrics monitoring.
    """

    async def test_5_invalid_key_requests_increment_counter_by_5(
        self, client: AsyncClient
    ) -> None:
        """
        5 requests with an invalid API key must produce exactly 5
        increments of ps_auth_failures_total{reason=invalid_key}.
        """
        for _ in range(5):
            await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": "ps_live_completely_invalid_key_value"},
                json={
                    "texts": ["test"],
                    "organization_id": ORG_A,
                    "request_id": REQ_A,
                },
            )

        metrics_resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        data = metrics_resp.json()
        auth_failures = data["counters"]["ps_auth_failures_total"]
        by_label = auth_failures["by_label"]

        invalid_key_label = "reason=invalid_key"
        assert invalid_key_label in by_label, (
            f"Missing '{invalid_key_label}' in metrics. Labels: {list(by_label.keys())}"
        )
        assert by_label[invalid_key_label] == 5, (
            f"Expected exactly 5 invalid_key failures, got {by_label[invalid_key_label]}"
        )

    async def test_revoked_key_increments_invalid_key_counter(
        self, client: AsyncClient
    ) -> None:
        """
        A revoked key returns 401 and increments ps_auth_failures_total
        with reason=invalid_key (since validate_key returns None for
        revoked keys, same code path as nonexistent keys).
        """
        # Create then revoke a key
        raw_key = await _create_key(client, org_id=ORG_A)
        key_hash = hashlib.sha256(raw_key.encode()).hexdigest()

        await client.delete(
            f"/api/v1/keys/{key_hash}",
            headers={"X-Admin-Key": ADMIN_SECRET},
        )

        # Use the revoked key
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert resp.status_code == 401

        # Check metrics
        metrics_resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        data = metrics_resp.json()
        auth_failures = data["counters"]["ps_auth_failures_total"]
        by_label = auth_failures["by_label"]

        # Revoked keys go through the same invalid_key path
        assert "reason=invalid_key" in by_label
        assert by_label["reason=invalid_key"] >= 1

    async def test_rate_limited_request_increments_rate_limited_counter(
        self, client: AsyncClient
    ) -> None:
        """
        After exhausting a key's rate limit, the rejection must increment
        ps_auth_failures_total{reason=rate_limited}.
        """
        raw_key = await _create_key(client, org_id=ORG_A, rate_limit=2)

        # Exhaust rate limit (2 allowed)
        for _ in range(2):
            resp = await client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": raw_key},
                json={
                    "texts": ["test"],
                    "organization_id": ORG_A,
                    "request_id": REQ_A,
                },
            )
            assert resp.status_code == 200

        # 3rd request: rate limited
        resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert resp.status_code == 429

        # Check metrics
        metrics_resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        data = metrics_resp.json()
        auth_failures = data["counters"]["ps_auth_failures_total"]
        by_label = auth_failures["by_label"]

        rate_limited_label = "reason=rate_limited"
        assert rate_limited_label in by_label, (
            f"Missing '{rate_limited_label}' in metrics after rate limit. "
            f"Labels: {list(by_label.keys())}"
        )
        assert by_label[rate_limited_label] >= 1

    async def test_admin_invalid_key_increments_admin_invalid_counter(
        self, client: AsyncClient
    ) -> None:
        """
        An invalid admin key (below rate limit) must increment
        ps_auth_failures_total{reason=admin_invalid}.
        """
        resp = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "wrong-admin-key"},
            json={"organization_id": ORG_A},
        )
        assert resp.status_code == 401

        metrics_resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        data = metrics_resp.json()
        auth_failures = data["counters"]["ps_auth_failures_total"]
        by_label = auth_failures["by_label"]

        admin_invalid_label = "reason=admin_invalid"
        assert admin_invalid_label in by_label, (
            f"Missing '{admin_invalid_label}' after wrong admin key. "
            f"Labels: {list(by_label.keys())}"
        )
        assert by_label[admin_invalid_label] >= 1

    async def test_all_failure_reasons_are_distinct_labels(
        self, client: AsyncClient
    ) -> None:
        """
        Exercise all 3 operational auth failure modes and verify they
        appear as distinct labels in the metrics snapshot.
        """
        # 1. Invalid key
        await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": "ps_live_bogus"},
            json={
                "texts": ["test"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )

        # 2. Rate limited
        raw_key = await _create_key(client, org_id=ORG_A, rate_limit=1)
        await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": raw_key},
            json={
                "texts": ["test"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )

        # 3. Admin invalid
        await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "wrong"},
            json={"organization_id": ORG_A},
        )

        metrics_resp = await client.get("/metrics", headers={"X-Admin-Key": ADMIN_SECRET})
        data = metrics_resp.json()
        by_label = data["counters"]["ps_auth_failures_total"]["by_label"]

        expected_labels = {"reason=invalid_key", "reason=rate_limited", "reason=admin_invalid"}
        actual_labels = set(by_label.keys())

        for label in expected_labels:
            assert label in actual_labels, (
                f"Missing auth failure label '{label}'. Got: {actual_labels}"
            )


# ===================================================================
# BREACH #5: Per-Org Token Quota
# ===================================================================


class TestBreachPerOrgTokenQuota:
    """
    Breach #5: Before the fix, there was no limit on how many tokens a
    single org could accumulate in Redis. A malicious tenant could
    exhaust Redis memory (LRU eviction) and cause data loss for other
    tenants. The fix adds a per-org quota checked before every vault write.

    Fix: count_org_tokens() checks active token count before tokenization.
    If >= max_tokens_per_org, raises QuotaExceededError -> HTTP 503.
    """

    async def test_exceeding_quota_returns_503(
        self, quota_client: AsyncClient
    ) -> None:
        """
        With max_tokens_per_org=5, tokenizing texts that create 5 tokens
        must succeed. The next tokenization that would create more tokens
        must return 503 (QuotaExceededError).
        """
        key = await _create_key(quota_client, org_id=ORG_A)

        # Create 5 tokens — each text should produce at least 1 token.
        # We send 5 separate texts, each containing one PII entity.
        pii_texts = [
            "CF RSSMRA85M01H501Z",
            "Email: a@b.com",
            "Email: c@d.com",
            "CF VRDLGU90A01F205X",
            "Email: e@f.com",
        ]

        total_tokens = 0
        for text in pii_texts:
            if total_tokens >= 5:
                break
            resp = await quota_client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key},
                json={
                    "texts": [text],
                    "organization_id": ORG_A,
                    "request_id": REQ_A,
                },
            )
            if resp.status_code == 503:
                # We hit the quota — that's expected once we reach 5
                break
            assert resp.status_code == 200, (
                f"Unexpected status {resp.status_code} for text '{text}': {resp.text}"
            )
            total_tokens += len(resp.json()["tokens"])

        # Now try one more — should fail with 503
        resp = await quota_client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["IBAN IT60X0542811101000000123456"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert resp.status_code == 503, (
            f"Expected 503 (QuotaExceeded) after filling quota, got {resp.status_code}: {resp.text}"
        )
        assert "quota" in resp.json()["detail"].lower()

    async def test_different_org_not_affected_by_other_orgs_quota(
        self, quota_client: AsyncClient
    ) -> None:
        """
        Org B must NOT be affected by Org A's quota consumption.
        Token quota is strictly per-org.
        """
        key_a = await _create_key(quota_client, org_id=ORG_A)
        key_b = await _create_key(quota_client, org_id=ORG_B)

        # Fill org A's quota
        for text in [
            "CF RSSMRA85M01H501Z",
            "Email: a@b.com",
            "Email: c@d.com",
            "CF VRDLGU90A01F205X",
            "Email: e@f.com",
        ]:
            resp = await quota_client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key_a},
                json={
                    "texts": [text],
                    "organization_id": ORG_A,
                    "request_id": REQ_A,
                },
            )
            if resp.status_code == 503:
                break

        # Org A should be at or over quota
        resp_a = await quota_client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["Email: x@y.com"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert resp_a.status_code == 503, "Org A should be over quota"

        # Org B must still work
        resp_b = await quota_client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_b},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": ORG_B,
                "request_id": REQ_B,
            },
        )
        assert resp_b.status_code == 200, (
            f"BREACH: Org B blocked by Org A's quota! Status: {resp_b.status_code}"
        )
        assert len(resp_b.json()["tokens"]) >= 1

    async def test_quota_released_after_flush(
        self, quota_client: AsyncClient
    ) -> None:
        """
        After flushing a request, the freed tokens must not count against
        the org's quota. A new tokenization request should succeed.
        """
        key = await _create_key(quota_client, org_id=ORG_A)

        # Fill quota
        for text in [
            "CF RSSMRA85M01H501Z",
            "Email: a@b.com",
            "Email: c@d.com",
            "CF VRDLGU90A01F205X",
            "Email: e@f.com",
        ]:
            resp = await quota_client.post(
                "/api/v1/tokenize",
                headers={"X-Api-Key": key},
                json={
                    "texts": [text],
                    "organization_id": ORG_A,
                    "request_id": REQ_A,
                },
            )
            if resp.status_code == 503:
                break

        # Verify quota is full
        resp_over = await quota_client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["Email: z@z.com"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert resp_over.status_code == 503

        # Flush REQ_A to release tokens
        flush_resp = await quota_client.post(
            "/api/v1/flush",
            headers={"X-Api-Key": key},
            json={"organization_id": ORG_A, "request_id": REQ_A},
        )
        assert flush_resp.status_code == 200
        assert flush_resp.json()["flushed_count"] >= 1

        # Now tokenization should succeed again (quota freed)
        # Use a new request_id since REQ_A was flushed
        new_req = "00000000-0000-0000-0000-0000000000c1"
        resp_after = await quota_client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key},
            json={
                "texts": ["CF RSSMRA85M01H501Z"],
                "organization_id": ORG_A,
                "request_id": new_req,
            },
        )
        assert resp_after.status_code == 200, (
            f"Quota not released after flush! Status: {resp_after.status_code}: {resp_after.text}"
        )

    async def test_quota_exceeded_error_entity_attributes(self) -> None:
        """
        QuotaExceededError must carry org_id, current count, and limit
        for observability and error reporting.
        """
        err = QuotaExceededError("org-test", 100, 100)
        assert err.org_id == "org-test"
        assert err.current == 100
        assert err.limit == 100
        assert "org-test" in str(err)
        assert "100" in str(err)


# ===================================================================
# Cross-Breach Integration: Combined attack scenario
# ===================================================================


class TestCrossBreachIntegration:
    """
    Combined attack scenario that exercises multiple breach fixes together:
    - Uses API key auth (Breach #4 metrics)
    - Tokenizes under one request_id (Breach #2 scoping)
    - Attempts cross-request injection (Breach #3)
    - Verifies metrics are correct throughout (Breach #4)
    """

    async def test_full_attack_scenario_all_breaches_blocked(
        self, client: AsyncClient
    ) -> None:
        """
        Simulates a realistic attacker session:
        1. Obtain valid API key for org A
        2. Tokenize sensitive data in request A
        3. Attempt to exfiltrate via request B (should fail)
        4. Attempt admin brute-force (should be rate limited)
        5. Verify all metrics counters are correct
        """
        key_a = await _create_key(client, org_id=ORG_A)

        # Step 1: Legitimate tokenization
        tok_resp = await client.post(
            "/api/v1/tokenize",
            headers={"X-Api-Key": key_a},
            json={
                "texts": ["Mario Rossi ha email mario@test.com e CF RSSMRA85M01H501Z"],
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert tok_resp.status_code == 200
        tokenized = tok_resp.json()["tokenized_texts"][0]
        assert "mario@test.com" not in tokenized
        assert "RSSMRA85M01H501Z" not in tokenized

        # Step 2: Cross-request exfiltration attempt (Breach #2+3)
        reh_resp = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key_a},
            json={
                "text": tokenized,
                "organization_id": ORG_A,
                "request_id": REQ_B,  # WRONG request
            },
        )
        assert reh_resp.json()["rehydrated_count"] == 0
        assert "mario@test.com" not in reh_resp.json()["text"]
        assert "RSSMRA85M01H501Z" not in reh_resp.json()["text"]

        # Step 3: Admin brute-force attempt (Breach #1)
        # Note: _create_key above already consumed 1 admin rate limit slot,
        # so we only need 9 more wrong-key requests to hit the limit of 10.
        for _ in range(9):
            await client.post(
                "/api/v1/keys",
                headers={"X-Admin-Key": "brute-force-attempt"},
                json={"organization_id": ORG_A},
            )
        # The next request (11th admin call overall) must be rate limited
        brute = await client.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": "brute-force-attempt"},
            json={"organization_id": ORG_A},
        )
        assert brute.status_code == 429

        # Step 4: Verify metrics (Breach #4)
        # /metrics is now admin-gated and shares the same rate limit counter, so
        # it cannot be called over HTTP after exhausting the admin rate limit.
        # Read the in-memory snapshot directly from the container instead.
        container = client._transport.app.state.container  # type: ignore[attr-defined]
        data = container.metrics.snapshot()
        by_label = data["counters"]["ps_auth_failures_total"]["by_label"]

        assert "reason=admin_invalid" in by_label
        assert by_label["reason=admin_invalid"] >= 9  # 9 wrong-key attempts before rate limit
        assert "reason=admin_rate_limited" in by_label
        assert by_label["reason=admin_rate_limited"] >= 1

        # Step 5: Legitimate rehydration still works (regression check)
        reh_correct = await client.post(
            "/api/v1/rehydrate",
            headers={"X-Api-Key": key_a},
            json={
                "text": tokenized,
                "organization_id": ORG_A,
                "request_id": REQ_A,
            },
        )
        assert reh_correct.json()["rehydrated_count"] >= 1
        assert "mario@test.com" in reh_correct.json()["text"]
