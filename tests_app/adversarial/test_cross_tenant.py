"""
Cross-tenant isolation tests using fakeredis.

The Twin-Tenant Protocol: every test instantiates TWO distinct org_ids and
explicitly attempts to access one org's data from another org's context.

Adversarial Analysis:
  1. Org A's DEK cannot decrypt org B's vault entries.
  2. Flush for org A must not affect org B's tokens.
  3. Redis key namespace must prevent cross-contamination.
"""
from __future__ import annotations

import os

import pytest

from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter


ORG_A = "00000000-0000-0000-0000-00000000000a"
ORG_B = "00000000-0000-0000-0000-00000000000b"
REQ_A = "00000000-0000-0000-0000-0000000000a1"
REQ_B = "00000000-0000-0000-0000-0000000000b1"


class TestDekIsolation:
    """Org A's DEK cannot decrypt org B's vault entries."""

    async def test_cross_org_dek_cannot_decrypt(
        self, wired_vault: RedisVaultAdapter, fake_kek: bytes
    ) -> None:
        crypto = AesCryptoAdapter(kek=fake_kek, vault=wired_vault)

        # Create DEKs for both orgs
        dek_a = await crypto.get_or_create_dek(ORG_A)
        dek_b = await crypto.get_or_create_dek(ORG_B)

        # DEKs must be different (different random bytes)
        assert dek_a != dek_b

        # Encrypt under org A's DEK
        ct_a = crypto.encrypt(dek_a, "Mario Rossi")

        # Attempting to decrypt with org B's DEK must fail
        with pytest.raises(Exception):
            crypto.decrypt(dek_b, ct_a)

    async def test_org_a_dek_not_readable_as_org_b(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        """DEK keys are namespaced per org in Redis."""
        await wired_vault.store_dek(ORG_A, b"dek_data_a")

        result_b = await wired_vault.retrieve_dek(ORG_B)
        assert result_b is None


class TestVaultIsolation:
    """Org A's vault entries are inaccessible from org B's context."""

    async def test_org_b_cannot_read_org_a_tokens(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        await wired_vault.store(ORG_A, REQ_A, "a3f2", b"secret_a", ttl_seconds=60)

        result = await wired_vault.retrieve(ORG_B, REQ_A, "a3f2")
        assert result is None

    async def test_org_b_batch_cannot_read_org_a_tokens(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        await wired_vault.store(ORG_A, REQ_A, "a3f2", b"secret_a", ttl_seconds=60)

        result = await wired_vault.retrieve_batch(ORG_B, REQ_A, ["a3f2"])
        assert result["a3f2"] is None

    async def test_same_hash_different_orgs_coexist(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        """Both orgs can store under same token_hash without collision."""
        await wired_vault.store(ORG_A, REQ_A, "a3f2", b"data_a", ttl_seconds=60)
        await wired_vault.store(ORG_B, REQ_A, "a3f2", b"data_b", ttl_seconds=60)

        assert await wired_vault.retrieve(ORG_A, REQ_A, "a3f2") == b"data_a"
        assert await wired_vault.retrieve(ORG_B, REQ_A, "a3f2") == b"data_b"


class TestFlushIsolation:
    """Flush for org A does not affect org B's tokens."""

    async def test_flush_org_a_preserves_org_b(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        # Store tokens for both orgs
        await wired_vault.store(ORG_A, REQ_A, "h1", b"a_data", ttl_seconds=60)
        await wired_vault.store(ORG_B, REQ_B, "h1", b"b_data", ttl_seconds=60)

        await wired_vault.register_request_token(ORG_A, REQ_A, "h1", ttl_seconds=60)

        # Flush org A
        flushed = await wired_vault.flush_request(ORG_A, REQ_A)
        assert flushed == 1

        # Org B's data must be intact
        assert await wired_vault.retrieve(ORG_B, REQ_B, "h1") == b"b_data"
        # Org A's data must be gone
        assert await wired_vault.retrieve(ORG_A, REQ_A, "h1") is None

    async def test_flush_request_a_does_not_affect_request_b_same_org(
        self, wired_vault: RedisVaultAdapter
    ) -> None:
        """Even within the same org, different request_ids are isolated."""
        await wired_vault.store(ORG_A, REQ_A, "h1", b"data1", ttl_seconds=60)
        await wired_vault.store(ORG_A, REQ_B, "h2", b"data2", ttl_seconds=60)

        await wired_vault.register_request_token(ORG_A, REQ_A, "h1", ttl_seconds=60)
        await wired_vault.register_request_token(ORG_A, REQ_B, "h2", ttl_seconds=60)

        await wired_vault.flush_request(ORG_A, REQ_A)

        assert await wired_vault.retrieve(ORG_A, REQ_A, "h1") is None
        assert await wired_vault.retrieve(ORG_A, REQ_B, "h2") == b"data2"


class TestKeyNamespaceIntegrity:
    """Verify Redis key patterns prevent cross-contamination."""

    async def test_key_patterns_include_org_id(
        self, wired_vault: RedisVaultAdapter, fake_redis
    ) -> None:
        await wired_vault.store(ORG_A, REQ_A, "h1", b"data", ttl_seconds=60)

        # Verify the actual Redis key includes the org_id and request_id
        key = f"ps:{ORG_A}:{REQ_A}:h1"
        value = await fake_redis.get(key)
        assert value == b"data"

        # The same hash under a different org prefix must not exist
        key_b = f"ps:{ORG_B}:{REQ_A}:h1"
        value_b = await fake_redis.get(key_b)
        assert value_b is None
