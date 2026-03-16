"""
RedisApiKeyAdapter adversarial tests against fakeredis.

Adversarial Analysis:
  1. validate_key must return None for revoked keys (active=False stored in Redis).
     If the JSON deserialization or the active flag check is wrong, a revoked key
     could pass validation -- a critical auth bypass.
  2. list_keys with org_id filter must not leak keys from other orgs. If the filter
     uses substring matching or falsy checks, org_id="" or org_id=None could leak.
  3. check_rate_limit uses time.time()//60 internally. Two calls within the same
     minute must share the same counter. The TTL must be set only on the first call.

Boundary Map:
  key_hash: valid string, empty string "", very long hash
  limit (rate): 1 (minimum useful), 0 (should always fail), large (10000)
  token_count (usage): 0 (no-op), 1, negative (production code guards > 0)
  org_id: non-empty, empty "", None
"""
from __future__ import annotations

from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from app.domain.entities import ApiKeyMetadata, UsageRecord
from app.infrastructure.adapters.redis_api_key import RedisApiKeyAdapter


def _make_meta(
    key_hash: str = "abc123def456",
    org_id: str = "org-1",
    active: bool = True,
    **overrides,
) -> ApiKeyMetadata:
    defaults = {
        "key_id": "kid_001",
        "org_id": org_id,
        "key_hash": key_hash,
        "plan": "standard",
        "rate_limit_per_minute": 100,
        "active": active,
        "created_at": "2026-03-15T12:00:00Z",
        "environment": "live",
    }
    defaults.update(overrides)
    return ApiKeyMetadata(**defaults)


@pytest.fixture
async def redis():
    """Fresh fakeredis instance per test (isolated)."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


@pytest.fixture
def adapter(redis) -> RedisApiKeyAdapter:
    return RedisApiKeyAdapter(redis)


# -----------------------------------------------------------------------
# Tenant Isolation
# -----------------------------------------------------------------------


class TestTenantIsolation:
    """Keys from org-A must not be visible through org-B filters."""

    async def test_list_keys_filters_by_org_id_strictly(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.store_key(_make_meta("h1", "org-A"))
        await adapter.store_key(_make_meta("h2", "org-B"))
        await adapter.store_key(_make_meta("h3", "org-A"))

        org_a_keys = await adapter.list_keys(org_id="org-A")
        org_b_keys = await adapter.list_keys(org_id="org-B")

        assert len(org_a_keys) == 2
        assert len(org_b_keys) == 1
        assert all(k.org_id == "org-A" for k in org_a_keys)
        assert all(k.org_id == "org-B" for k in org_b_keys)

    async def test_list_keys_substring_org_id_does_not_match(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        """org-A is a substring of org-AB but must NOT match."""
        await adapter.store_key(_make_meta("h1", "org-A"))
        await adapter.store_key(_make_meta("h2", "org-AB"))

        keys = await adapter.list_keys(org_id="org-A")
        assert len(keys) == 1
        assert keys[0].org_id == "org-A"

    async def test_usage_isolation_between_orgs(self, adapter: RedisApiKeyAdapter) -> None:
        """Usage counters for org-A must not bleed into org-B."""
        await adapter.record_usage("org-A", "tokenize", token_count=10)
        await adapter.record_usage("org-B", "tokenize", token_count=5)

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage_a = await adapter.get_usage("org-A", month)
        usage_b = await adapter.get_usage("org-B", month)

        assert usage_a.tokenize_calls == 1
        assert usage_a.total_tokens_created == 10
        assert usage_b.tokenize_calls == 1
        assert usage_b.total_tokens_created == 5

    async def test_rate_limit_isolation_between_keys(self, adapter: RedisApiKeyAdapter) -> None:
        """Rate limit counter for key-A must not affect key-B."""
        for _ in range(5):
            await adapter.check_rate_limit("key-A", limit=10)

        allowed_b, count_b = await adapter.check_rate_limit("key-B", limit=10)
        assert allowed_b is True
        assert count_b == 1


# -----------------------------------------------------------------------
# Store + Validate
# -----------------------------------------------------------------------


class TestStoreAndValidate:
    async def test_store_then_validate_roundtrip(self, adapter: RedisApiKeyAdapter) -> None:
        meta = _make_meta()
        await adapter.store_key(meta)
        result = await adapter.validate_key("abc123def456")

        assert result is not None
        assert result.org_id == "org-1"
        assert result.active is True
        assert result.key_id == "kid_001"
        assert result.plan == "standard"
        assert result.rate_limit_per_minute == 100
        assert result.environment == "live"
        assert result.key_hash == "abc123def456"
        assert result.created_at == "2026-03-15T12:00:00Z"

    async def test_validate_nonexistent_key_returns_none(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        result = await adapter.validate_key("nonexistent_hash")
        assert result is None

    async def test_validate_revoked_key_returns_none(self, adapter: RedisApiKeyAdapter) -> None:
        meta = _make_meta()
        await adapter.store_key(meta)
        await adapter.revoke_key("abc123def456")
        result = await adapter.validate_key("abc123def456")
        assert result is None

    async def test_validate_key_stored_as_inactive_returns_none(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        """A key stored with active=False must never validate."""
        meta = _make_meta(active=False)
        await adapter.store_key(meta)
        result = await adapter.validate_key("abc123def456")
        assert result is None

    async def test_store_overwrites_existing_key(self, adapter: RedisApiKeyAdapter) -> None:
        """Storing a key with the same hash overwrites the previous metadata."""
        meta1 = _make_meta(plan="standard")
        meta2 = _make_meta(plan="premium")
        await adapter.store_key(meta1)
        await adapter.store_key(meta2)

        result = await adapter.validate_key("abc123def456")
        assert result is not None
        assert result.plan == "premium"


# -----------------------------------------------------------------------
# Revoke
# -----------------------------------------------------------------------


class TestRevokeKey:
    async def test_revoke_existing_key_returns_true(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.store_key(_make_meta())
        revoked = await adapter.revoke_key("abc123def456")
        assert revoked is True

    async def test_revoke_nonexistent_key_returns_false(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        revoked = await adapter.revoke_key("no_such_hash")
        assert revoked is False

    async def test_revoke_twice_returns_true_both_times(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        """Revoke is idempotent -- second call also returns True (key exists, just already inactive)."""
        await adapter.store_key(_make_meta())
        first = await adapter.revoke_key("abc123def456")
        second = await adapter.revoke_key("abc123def456")
        assert first is True
        assert second is True

    async def test_revoked_key_still_appears_in_list(self, adapter: RedisApiKeyAdapter) -> None:
        """Revoked keys should still be listable (for audit purposes)."""
        await adapter.store_key(_make_meta())
        await adapter.revoke_key("abc123def456")
        keys = await adapter.list_keys()
        assert len(keys) == 1
        assert keys[0].active is False


# -----------------------------------------------------------------------
# List Keys
# -----------------------------------------------------------------------


class TestListKeys:
    async def test_list_all_keys(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.store_key(_make_meta("h1", "org-1"))
        await adapter.store_key(_make_meta("h2", "org-2"))
        await adapter.store_key(_make_meta("h3", "org-1"))
        keys = await adapter.list_keys()
        assert len(keys) == 3

    async def test_list_empty_returns_empty(self, adapter: RedisApiKeyAdapter) -> None:
        keys = await adapter.list_keys()
        assert keys == []

    async def test_list_with_none_org_id_returns_all(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.store_key(_make_meta("h1", "org-1"))
        await adapter.store_key(_make_meta("h2", "org-2"))
        keys = await adapter.list_keys(org_id=None)
        assert len(keys) == 2

    async def test_list_nonexistent_org_returns_empty(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.store_key(_make_meta("h1", "org-1"))
        keys = await adapter.list_keys(org_id="org-nonexistent")
        assert keys == []


# -----------------------------------------------------------------------
# Rate Limiting
# -----------------------------------------------------------------------


class TestRateLimit:
    async def test_first_call_returns_count_1_and_allowed(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        allowed, count = await adapter.check_rate_limit("key1", limit=10)
        assert allowed is True
        assert count == 1

    async def test_increments_within_same_minute(self, adapter: RedisApiKeyAdapter) -> None:
        for i in range(5):
            allowed, count = await adapter.check_rate_limit("key1", limit=10)
            assert allowed is True
            assert count == i + 1

    async def test_at_exact_limit_still_allowed(self, adapter: RedisApiKeyAdapter) -> None:
        """count <= limit means exactly AT the limit is still allowed."""
        for _ in range(9):
            await adapter.check_rate_limit("key1", limit=10)
        allowed, count = await adapter.check_rate_limit("key1", limit=10)
        assert allowed is True
        assert count == 10

    async def test_over_limit_returns_false(self, adapter: RedisApiKeyAdapter) -> None:
        for _ in range(10):
            await adapter.check_rate_limit("key1", limit=10)
        allowed, count = await adapter.check_rate_limit("key1", limit=10)
        assert allowed is False
        assert count == 11

    async def test_limit_of_1_allows_exactly_one_call(self, adapter: RedisApiKeyAdapter) -> None:
        allowed1, count1 = await adapter.check_rate_limit("key1", limit=1)
        assert allowed1 is True
        assert count1 == 1

        allowed2, count2 = await adapter.check_rate_limit("key1", limit=1)
        assert allowed2 is False
        assert count2 == 2


# -----------------------------------------------------------------------
# Usage Recording
# -----------------------------------------------------------------------


class TestUsage:
    async def test_record_and_get_tokenize(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.record_usage("org-1", "tokenize", token_count=5)
        await adapter.record_usage("org-1", "tokenize", token_count=3)

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("org-1", month)

        assert usage.org_id == "org-1"
        assert usage.month == month
        assert usage.tokenize_calls == 2
        assert usage.total_tokens_created == 8
        assert usage.rehydrate_calls == 0
        assert usage.flush_calls == 0

    async def test_record_rehydrate_and_flush(self, adapter: RedisApiKeyAdapter) -> None:
        await adapter.record_usage("org-1", "rehydrate")
        await adapter.record_usage("org-1", "rehydrate")
        await adapter.record_usage("org-1", "flush")

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("org-1", month)

        assert usage.rehydrate_calls == 2
        assert usage.flush_calls == 1
        assert usage.tokenize_calls == 0
        assert usage.total_tokens_created == 0

    async def test_zero_token_count_does_not_increment_tokens_created(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        """token_count=0 should not increment tokens_created (guarded by > 0)."""
        await adapter.record_usage("org-1", "tokenize", token_count=0)

        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("org-1", month)

        assert usage.tokenize_calls == 1
        assert usage.total_tokens_created == 0

    async def test_get_usage_empty_month_returns_zeros(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        usage = await adapter.get_usage("org-1", "1999-01")
        assert usage.tokenize_calls == 0
        assert usage.rehydrate_calls == 0
        assert usage.flush_calls == 0
        assert usage.total_tokens_created == 0

    async def test_get_usage_nonexistent_org_returns_zeros(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("nonexistent-org", month)
        assert usage.tokenize_calls == 0
        assert usage.total_tokens_created == 0

    async def test_negative_token_count_does_not_increment(
        self, adapter: RedisApiKeyAdapter
    ) -> None:
        """Production code guards token_count > 0. Negative values should not increment."""
        await adapter.record_usage("org-1", "tokenize", token_count=-5)
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("org-1", month)
        assert usage.tokenize_calls == 1
        assert usage.total_tokens_created == 0


# -----------------------------------------------------------------------
# Concurrency
# -----------------------------------------------------------------------


class TestConcurrency:
    async def test_concurrent_rate_limit_checks(self, adapter: RedisApiKeyAdapter) -> None:
        """50 concurrent rate limit checks must produce exactly 50 increments."""
        import asyncio

        results = await asyncio.gather(
            *[adapter.check_rate_limit("conc-key", limit=100) for _ in range(50)]
        )
        counts = [count for _, count in results]
        # All counts should be distinct values 1..50 (atomic INCR)
        assert sorted(counts) == list(range(1, 51))

    async def test_concurrent_usage_recording(self, adapter: RedisApiKeyAdapter) -> None:
        """50 concurrent usage records must produce exactly 50 in the counter."""
        import asyncio

        await asyncio.gather(
            *[adapter.record_usage("org-conc", "tokenize", token_count=1) for _ in range(50)]
        )
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        usage = await adapter.get_usage("org-conc", month)
        assert usage.tokenize_calls == 50
        assert usage.total_tokens_created == 50
