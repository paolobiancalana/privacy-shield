"""
RedisVaultAdapter tests — store/retrieve/flush lifecycle with fakeredis.

Adversarial Analysis:
  1. Cross-org key namespace must prevent contamination (different org_ids -> different keys).
  2. Flush for one request must not affect tokens from another request.
  3. Batch retrieve with mixed hits/misses must return correct mapping.
"""
from __future__ import annotations

import pytest

from app.infrastructure.adapters.redis_vault import RedisVaultAdapter


ORG_A = "org-aaaa"
ORG_B = "org-bbbb"
REQ_1 = "req-0001"
REQ_2 = "req-0002"


class TestStoreRetrieve:
    """Basic store + retrieve roundtrip."""

    async def test_store_and_retrieve(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "a3f2", b"encrypted_data", ttl_seconds=60)
        result = await wired_vault.retrieve(ORG_A, REQ_1, "a3f2")
        assert result == b"encrypted_data"

    async def test_retrieve_nonexistent_returns_none(self, wired_vault: RedisVaultAdapter) -> None:
        result = await wired_vault.retrieve(ORG_A, REQ_1, "nope")
        assert result is None

    async def test_store_overwrites_existing(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "a3f2", b"first", ttl_seconds=60)
        await wired_vault.store(ORG_A, REQ_1, "a3f2", b"second", ttl_seconds=60)
        result = await wired_vault.retrieve(ORG_A, REQ_1, "a3f2")
        assert result == b"second"


class TestRetrieveBatch:
    """MGET batch retrieve."""

    async def test_batch_all_hits(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"v1", ttl_seconds=60)
        await wired_vault.store(ORG_A, REQ_1, "h2", b"v2", ttl_seconds=60)
        result = await wired_vault.retrieve_batch(ORG_A, REQ_1, ["h1", "h2"])
        assert result == {"h1": b"v1", "h2": b"v2"}

    async def test_batch_mixed_hits_misses(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"v1", ttl_seconds=60)
        result = await wired_vault.retrieve_batch(ORG_A, REQ_1, ["h1", "missing"])
        assert result["h1"] == b"v1"
        assert result["missing"] is None

    async def test_batch_empty_list(self, wired_vault: RedisVaultAdapter) -> None:
        result = await wired_vault.retrieve_batch(ORG_A, REQ_1, [])
        assert result == {}


class TestRegisterRequestAndFlush:
    """Request token registration and flush lifecycle."""

    async def test_register_and_flush(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"v1", ttl_seconds=60)
        await wired_vault.store(ORG_A, REQ_1, "h2", b"v2", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_1, "h1", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_1, "h2", ttl_seconds=60)

        flushed = await wired_vault.flush_request(ORG_A, REQ_1)
        assert flushed == 2

        # Tokens should be gone
        assert await wired_vault.retrieve(ORG_A, REQ_1, "h1") is None
        assert await wired_vault.retrieve(ORG_A, REQ_1, "h2") is None

    async def test_flush_empty_request_returns_zero(self, wired_vault: RedisVaultAdapter) -> None:
        flushed = await wired_vault.flush_request(ORG_A, "nonexistent")
        assert flushed == 0

    async def test_flush_idempotent(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"v1", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_1, "h1", ttl_seconds=60)

        flushed1 = await wired_vault.flush_request(ORG_A, REQ_1)
        flushed2 = await wired_vault.flush_request(ORG_A, REQ_1)
        assert flushed1 == 1
        assert flushed2 == 0

    async def test_flush_one_request_does_not_affect_another(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"v1", ttl_seconds=60)
        await wired_vault.store(ORG_A, REQ_2, "h2", b"v2", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_1, "h1", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_2, "h2", ttl_seconds=60)

        await wired_vault.flush_request(ORG_A, REQ_1)

        # h1 gone, h2 still present
        assert await wired_vault.retrieve(ORG_A, REQ_1, "h1") is None
        assert await wired_vault.retrieve(ORG_A, REQ_2, "h2") == b"v2"


class TestDekStorage:
    """DEK store/retrieve (no TTL)."""

    async def test_dek_roundtrip(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store_dek(ORG_A, b"encrypted_dek_bytes")
        result = await wired_vault.retrieve_dek(ORG_A)
        assert result == b"encrypted_dek_bytes"

    async def test_dek_absent_returns_none(self, wired_vault: RedisVaultAdapter) -> None:
        result = await wired_vault.retrieve_dek("nonexistent-org")
        assert result is None


class TestKeyNamespacing:
    """Redis key schema prevents cross-org contamination."""

    async def test_different_orgs_different_keys(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"org_a_data", ttl_seconds=60)
        await wired_vault.store(ORG_B, REQ_1, "h1", b"org_b_data", ttl_seconds=60)

        assert await wired_vault.retrieve(ORG_A, REQ_1, "h1") == b"org_a_data"
        assert await wired_vault.retrieve(ORG_B, REQ_1, "h1") == b"org_b_data"

    async def test_flush_org_a_does_not_affect_org_b(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        await wired_vault.store(ORG_A, REQ_1, "h1", b"a_data", ttl_seconds=60)
        await wired_vault.store(ORG_B, REQ_1, "h1", b"b_data", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_1, "h1", ttl_seconds=60)

        await wired_vault.flush_request(ORG_A, REQ_1)

        assert await wired_vault.retrieve(ORG_A, REQ_1, "h1") is None
        assert await wired_vault.retrieve(ORG_B, REQ_1, "h1") == b"b_data"

    async def test_dek_per_org_isolation(self, wired_vault: RedisVaultAdapter) -> None:
        await wired_vault.store_dek(ORG_A, b"dek_a")
        await wired_vault.store_dek(ORG_B, b"dek_b")

        assert await wired_vault.retrieve_dek(ORG_A) == b"dek_a"
        assert await wired_vault.retrieve_dek(ORG_B) == b"dek_b"
