"""
Cross-tenant E2E adversarial tests (T4.1) — full container wired with fakeredis.

These tests are the most critical in the entire suite. They verify that the
Privacy Shield microservice provides ZERO cross-tenant data leakage at every layer.

Adversarial Analysis:
  1. Same PII value tokenized for org A and org B must produce DIFFERENT HMAC hashes
     because each org has its own DEK. If the HMAC used a shared secret, identical
     PII across orgs would collide — a tenant-leak vector.
  2. Flush for org A must not delete org B's tokens even if they have the same
     token_hash. The key namespace (ps:{org_id}:{hash}) provides isolation, but
     the request tracking SET (ps:req:{org_id}:{req_id}) must also be org-scoped.
  3. DEK rotation for org A must not re-encrypt org B's tokens. The scan pattern
     (ps:req:{org_id}:*) must be strictly org-scoped.

Boundary Map:
  org_id: ORG_A (uuid-a), ORG_B (uuid-b), 10 random orgs (concurrent test)
  PII: same text for both orgs, different text for both orgs
  Operations: tokenize, flush, rehydrate, DEK rotation
"""
from __future__ import annotations

import asyncio
import uuid

import fakeredis.aioredis
import pytest

from app.application.flush_request import FlushRequestUseCase
from app.application.rehydrate_text import RehydrateTextUseCase
from app.application.rotate_dek import RotateDekUseCase
from app.application.tokenize_text import TokenizeTextUseCase
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter

ORG_A = "00000000-0000-0000-0000-00000000000a"
ORG_B = "00000000-0000-0000-0000-00000000000b"
REQ_A = "00000000-0000-0000-0000-0000000000a1"
REQ_B = "00000000-0000-0000-0000-0000000000b1"

TOKEN_TTL = 60


@pytest.fixture
async def redis():
    """Fresh fakeredis per test."""
    r = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield r
    await r.aclose()


@pytest.fixture
def vault(redis) -> RedisVaultAdapter:
    return RedisVaultAdapter(redis_client=redis)


@pytest.fixture
def kek() -> bytes:
    return b"\x01" * 32


@pytest.fixture
def crypto(kek, vault) -> AesCryptoAdapter:
    return AesCryptoAdapter(kek=kek, vault=vault)


@pytest.fixture
def detection() -> RegexDetectionAdapter:
    return RegexDetectionAdapter()


@pytest.fixture
def make_tokenize_use_case(detection, vault, crypto):
    """Factory to create a TokenizeTextUseCase."""
    return TokenizeTextUseCase(
        detection=detection,
        vault=vault,
        crypto=crypto,
        token_ttl_seconds=TOKEN_TTL,
    )


@pytest.fixture
def make_rehydrate_use_case(vault, crypto):
    return RehydrateTextUseCase(vault=vault, crypto=crypto)


@pytest.fixture
def make_flush_use_case(vault):
    return FlushRequestUseCase(vault=vault)


class TestTokenIsolation:
    """Org A's tokens are not accessible by org B."""

    async def test_org_b_cannot_rehydrate_org_a_tokens(
        self,
        make_tokenize_use_case: TokenizeTextUseCase,
        make_rehydrate_use_case: RehydrateTextUseCase,
    ) -> None:
        """Tokenize as org A, try to rehydrate as org B -> tokens remain opaque."""
        result_a = await make_tokenize_use_case.execute(
            text="Il mio CF e' RSSMRA85M01H501Z",
            org_id=ORG_A,
            request_id=REQ_A,
        )
        # The tokenized text contains tokens
        assert "[#" in result_a.tokenized_text

        # Try to rehydrate as org B -> tokens should NOT be resolved
        result_b = await make_rehydrate_use_case.execute(
            text=result_a.tokenized_text,
            org_id=ORG_B,
            request_id=REQ_A,
        )
        # Org B cannot resolve org A's tokens -> text unchanged (tokens left as-is)
        assert "[#" in result_b.text
        assert result_b.rehydrated_count == 0

    async def test_same_pii_different_org_different_hmac(
        self, crypto: AesCryptoAdapter
    ) -> None:
        """Same PII value + different org -> different HMAC due to different DEK."""
        dek_a = await crypto.get_or_create_dek(ORG_A)
        dek_b = await crypto.get_or_create_dek(ORG_B)

        hash_a = crypto.hmac_token_hash(dek_a, "RSSMRA85M01H501Z")
        hash_b = crypto.hmac_token_hash(dek_b, "RSSMRA85M01H501Z")

        # Different DEKs produce different HMAC hashes
        assert hash_a != hash_b


class TestFlushIsolation:
    """Flush for org A doesn't affect org B's tokens."""

    async def test_flush_org_a_preserves_org_b(
        self,
        make_tokenize_use_case: TokenizeTextUseCase,
        make_rehydrate_use_case: RehydrateTextUseCase,
        make_flush_use_case: FlushRequestUseCase,
    ) -> None:
        # Tokenize for both orgs
        result_a = await make_tokenize_use_case.execute(
            text="Mario Rossi con CF RSSMRA85M01H501Z",
            org_id=ORG_A,
            request_id=REQ_A,
        )
        result_b = await make_tokenize_use_case.execute(
            text="Luigi Verdi con CF VRDLGU90A01F205X",
            org_id=ORG_B,
            request_id=REQ_B,
        )

        # Flush org A only
        await make_flush_use_case.execute(org_id=ORG_A, request_id=REQ_A)

        # Org A's tokens should no longer resolve
        rehydrated_a = await make_rehydrate_use_case.execute(
            text=result_a.tokenized_text,
            org_id=ORG_A,
            request_id=REQ_A,
        )
        assert rehydrated_a.rehydrated_count == 0  # all tokens expired/flushed

        # Org B's tokens should still resolve
        rehydrated_b = await make_rehydrate_use_case.execute(
            text=result_b.tokenized_text,
            org_id=ORG_B,
            request_id=REQ_B,
        )
        assert rehydrated_b.rehydrated_count > 0


class TestDekIsolation:
    """Org A and org B have different DEKs."""

    async def test_different_orgs_different_deks(self, crypto: AesCryptoAdapter) -> None:
        dek_a = await crypto.get_or_create_dek(ORG_A)
        dek_b = await crypto.get_or_create_dek(ORG_B)

        assert dek_a != dek_b
        assert len(dek_a) == 32
        assert len(dek_b) == 32

    async def test_dek_stable_per_org(self, crypto: AesCryptoAdapter) -> None:
        """Multiple calls to get_or_create_dek for the same org return the same DEK."""
        dek1 = await crypto.get_or_create_dek(ORG_A)
        dek2 = await crypto.get_or_create_dek(ORG_A)
        assert dek1 == dek2


class TestConcurrentMultiOrg:
    """Concurrent tokenize calls for 10 different orgs -> zero cross-contamination."""

    async def test_10_orgs_concurrent_zero_leakage(
        self,
        detection: RegexDetectionAdapter,
        vault: RedisVaultAdapter,
        crypto: AesCryptoAdapter,
    ) -> None:
        org_ids = [str(uuid.uuid4()) for _ in range(10)]
        req_ids = [str(uuid.uuid4()) for _ in range(10)]

        # Each org gets unique PII to verify no cross-contamination
        pii_texts = [
            f"Nome {i}: CF RSSMRA85M01H50{i}Z email test{i}@example.com"
            for i in range(10)
        ]

        tokenize_uc = TokenizeTextUseCase(
            detection=detection,
            vault=vault,
            crypto=crypto,
            token_ttl_seconds=TOKEN_TTL,
        )
        rehydrate_uc = RehydrateTextUseCase(vault=vault, crypto=crypto)

        # Tokenize concurrently
        tokenize_tasks = [
            tokenize_uc.execute(text=pii_texts[i], org_id=org_ids[i], request_id=req_ids[i])
            for i in range(10)
        ]
        tokenize_results = await asyncio.gather(*tokenize_tasks)

        # Verify each org can rehydrate its own tokens
        for i in range(10):
            rehydrated = await rehydrate_uc.execute(
                text=tokenize_results[i].tokenized_text,
                org_id=org_ids[i],
                request_id=req_ids[i],
            )
            assert rehydrated.rehydrated_count > 0

        # Verify cross-org rehydration fails (org 0 trying to read org 1's tokens)
        for i in range(10):
            other_org = org_ids[(i + 1) % 10]
            rehydrated = await rehydrate_uc.execute(
                text=tokenize_results[i].tokenized_text,
                org_id=other_org,
                request_id=req_ids[i],
            )
            assert rehydrated.rehydrated_count == 0, (
                f"TENANT LEAK: org {other_org} rehydrated tokens belonging to org {org_ids[i]}"
            )


class TestTokenCollision:
    """Same PII value + different org -> different HMAC (different DEK)."""

    async def test_identical_pii_different_tokens(
        self,
        make_tokenize_use_case: TokenizeTextUseCase,
    ) -> None:
        """The same PII tokenized under different orgs produces different tokens."""
        shared_text = "Il codice fiscale e' RSSMRA85M01H501Z"

        result_a = await make_tokenize_use_case.execute(
            text=shared_text,
            org_id=ORG_A,
            request_id=REQ_A,
        )
        result_b = await make_tokenize_use_case.execute(
            text=shared_text,
            org_id=ORG_B,
            request_id=REQ_B,
        )

        # Both should have tokenized the CF
        assert "[#" in result_a.tokenized_text
        assert "[#" in result_b.tokenized_text

        # The token strings should be different (different HMAC due to different DEK)
        if result_a.tokens and result_b.tokens:
            token_a = result_a.tokens[0].token
            token_b = result_b.tokens[0].token
            assert token_a != token_b, (
                f"COLLISION: identical tokens for different orgs: {token_a}"
            )


class TestDekRotationIsolation:
    """DEK rotation for org A must not re-encrypt org B's tokens."""

    async def test_rotation_org_a_preserves_org_b(
        self,
        make_tokenize_use_case: TokenizeTextUseCase,
        make_rehydrate_use_case: RehydrateTextUseCase,
        vault: RedisVaultAdapter,
        crypto: AesCryptoAdapter,
    ) -> None:
        # Tokenize for both orgs
        result_b = await make_tokenize_use_case.execute(
            text="Luigi Verdi VRDLGU90A01F205X",
            org_id=ORG_B,
            request_id=REQ_B,
        )

        result_a = await make_tokenize_use_case.execute(
            text="Mario Rossi RSSMRA85M01H501Z",
            org_id=ORG_A,
            request_id=REQ_A,
        )

        # Rotate DEK for org A only
        rotate_uc = RotateDekUseCase(vault=vault, crypto=crypto)
        rotation = await rotate_uc.execute(ORG_A)
        assert rotation.rotated is True

        # Org B's tokens must still resolve (not affected by org A's rotation)
        rehydrated_b = await make_rehydrate_use_case.execute(
            text=result_b.tokenized_text,
            org_id=ORG_B,
            request_id=REQ_B,
        )
        assert rehydrated_b.rehydrated_count > 0

        # Org A's tokens must also still resolve (re-encrypted under new DEK)
        rehydrated_a = await make_rehydrate_use_case.execute(
            text=result_a.tokenized_text,
            org_id=ORG_A,
            request_id=REQ_A,
        )
        assert rehydrated_a.rehydrated_count > 0
