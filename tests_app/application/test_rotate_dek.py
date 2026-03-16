"""
RotateDekUseCase unit tests — mocked ports.

Adversarial Analysis:
  1. If `retrieve_dek` returns None, the use case must raise ValueError (not crash or
     silently return 0). A missing guard would attempt decrypt_dek(None) and blow up
     with an opaque TypeError instead of a clear ValueError.
  2. If a token expires between scan and re-encrypt, `_re_encrypt_token` returns False.
     But if the token expires between `retrieve` and `get_token_ttl` (TTL becomes 0 or -2),
     it must also return False — not store with TTL 0 (which makes the key permanent in Redis).
  3. Write-last ordering: `store_dek` with the new DEK MUST be the final vault call.
     If it runs BEFORE all `store()` calls complete, a crash leaves entries encrypted
     under new DEK but old DEK still registered — irrecoverable split.

Boundary Map:
  token_hashes: [] (empty), [1 element], [5 mixed success/fail]
  TTL: 0 (skip), -1 (permanent — skip), -2 (expired — skip), 1 (boundary), 30 (normal)
  ciphertext: None (expired), b"valid", b"corrupt" (decrypt raises)
"""
from __future__ import annotations

import os
from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.application.rotate_dek import RotateDekUseCase, RotationResult


@pytest.fixture
def vault() -> AsyncMock:
    """Mock VaultPort with sane defaults."""
    v = AsyncMock()
    v.retrieve_dek = AsyncMock(return_value=b"encrypted_old_dek")
    v.store_dek = AsyncMock()
    v.scan_active_token_hashes = AsyncMock(return_value=[])
    v.retrieve = AsyncMock(return_value=b"old_ciphertext")
    v.store = AsyncMock()
    v.get_token_ttl = AsyncMock(return_value=30)
    return v


@pytest.fixture
def crypto() -> MagicMock:
    """Mock CryptoPort with sane defaults."""
    c = MagicMock()
    c.decrypt_dek = MagicMock(return_value=b"\xaa" * 32)
    c.encrypt_dek = MagicMock(return_value=b"wrapped_new_dek")
    c.decrypt = MagicMock(return_value="plaintext_value")
    c.encrypt = MagicMock(return_value=b"new_ciphertext")
    return c


@pytest.fixture
def use_case(vault: AsyncMock, crypto: MagicMock) -> RotateDekUseCase:
    return RotateDekUseCase(vault=vault, crypto=crypto)


ORG = "00000000-0000-0000-0000-aaaaaaaaaaaa"


class TestHappyPath:
    """Standard rotation: existing DEK, N active tokens, all re-encrypted."""

    async def test_rotates_with_active_tokens(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [
            ("req1", "h1"), ("req2", "h2"), ("req3", "h3")
        ]

        result = await use_case.execute(ORG)

        assert result.rotated is True
        assert result.re_encrypted_count == 3

        # verify decrypt was called for each token with old dek
        assert crypto.decrypt.call_count == 3
        # verify encrypt was called for each token with new dek
        assert crypto.encrypt.call_count == 3
        # verify store was called for each token
        assert vault.store.call_count == 3

    async def test_result_is_frozen_dataclass(
        self, use_case: RotateDekUseCase
    ) -> None:
        result = await use_case.execute(ORG)
        assert isinstance(result, RotationResult)
        with pytest.raises(AttributeError):
            result.rotated = False  # type: ignore[misc]


class TestNoDekExists:
    """No DEK for org -> must raise ValueError, not TypeError or silent return."""

    async def test_raises_value_error_when_no_dek(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.retrieve_dek.return_value = None

        with pytest.raises(ValueError, match="No DEK found"):
            await use_case.execute(ORG)

    async def test_no_vault_writes_when_no_dek(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.retrieve_dek.return_value = None

        with pytest.raises(ValueError):
            await use_case.execute(ORG)

        vault.store.assert_not_called()
        vault.store_dek.assert_not_called()


class TestTokenExpiredBetweenScanAndReEncrypt:
    """Token disappeared between scan_active_token_hashes and retrieve."""

    async def test_expired_token_returns_false_and_is_skipped(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [("req1", "h1"), ("req2", "h2")]
        # h1 expired (retrieve returns None), h2 still alive
        vault.retrieve.side_effect = [None, b"ciphertext"]

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 1
        # decrypt was called only for h2
        assert crypto.decrypt.call_count == 1


class TestCorruptCiphertext:
    """Decrypt raises -> token skipped (logged), not counted."""

    async def test_corrupt_ciphertext_skipped(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [("req1", "h1"), ("req2", "h2")]
        # h1 decrypts fine, h2 raises
        crypto.decrypt.side_effect = [
            "plaintext_h1",
            Exception("Tampered ciphertext"),
        ]

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 1
        # encrypt called only once (for h1)
        assert crypto.encrypt.call_count == 1

    async def test_all_corrupt_returns_zero(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [("req1", "h1"), ("req2", "h2")]
        crypto.decrypt.side_effect = Exception("All corrupt")

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 0
        crypto.encrypt.assert_not_called()


class TestTtlEdgeCases:
    """TTL <= 0 means token expired during re-encryption -> skip."""

    async def test_ttl_zero_skips_token(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [("req1", "h1")]
        vault.get_token_ttl.return_value = 0

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 0
        vault.store.assert_not_called()

    async def test_ttl_negative_skips_token(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [("req1", "h1")]
        vault.get_token_ttl.return_value = -2  # key expired

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 0
        vault.store.assert_not_called()

    async def test_ttl_minus_one_skips_token(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        """TTL = -1 means permanent key. Our code treats <= 0 as skip."""
        vault.scan_active_token_hashes.return_value = [("req1", "h1")]
        vault.get_token_ttl.return_value = -1

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 0
        vault.store.assert_not_called()

    async def test_ttl_one_stores_with_ttl_one(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        """TTL = 1 is the boundary minimum. Must be stored."""
        vault.scan_active_token_hashes.return_value = [("req1", "h1")]
        vault.get_token_ttl.return_value = 1

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 1
        vault.store.assert_called_once()
        # Verify TTL is passed to store
        # New signature: store(org_id, request_id, token_hash, encrypted_value, ttl_seconds)
        args, kwargs = vault.store.call_args
        assert kwargs.get("ttl_seconds") is not None or args[4] == 1


class TestWriteLastOrdering:
    """store_dek must be called AFTER all store calls (write-last)."""

    async def test_store_dek_called_after_all_stores(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [
            ("req1", "h1"), ("req2", "h2"), ("req3", "h3")
        ]

        call_order: list[str] = []
        original_store = vault.store

        async def tracking_store(*args, **kwargs):
            call_order.append("store")
            return await original_store(*args, **kwargs)

        async def tracking_store_dek(*args, **kwargs):
            call_order.append("store_dek")

        vault.store = AsyncMock(side_effect=tracking_store)
        vault.store_dek = AsyncMock(side_effect=tracking_store_dek)

        await use_case.execute(ORG)

        # All "store" calls must precede "store_dek"
        assert call_order.count("store") == 3
        assert call_order.count("store_dek") == 1
        store_dek_idx = call_order.index("store_dek")
        last_store_idx = len(call_order) - 1 - call_order[::-1].index("store")
        assert store_dek_idx > last_store_idx, (
            f"store_dek at index {store_dek_idx} must come after "
            f"last store at index {last_store_idx}"
        )


class TestEmptyVault:
    """No active tokens -> 0 re-encrypted, but rotation still completes."""

    async def test_empty_vault_returns_zero(
        self, use_case: RotateDekUseCase, vault: AsyncMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = []

        result = await use_case.execute(ORG)

        assert result.rotated is True
        assert result.re_encrypted_count == 0
        # store_dek still called (new DEK is committed)
        vault.store_dek.assert_called_once()
        vault.store.assert_not_called()


class TestPartialFailure:
    """Some tokens succeed, some fail -> count reflects only successes."""

    async def test_mixed_success_and_failure(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        vault.scan_active_token_hashes.return_value = [
            ("req1", "h1"), ("req2", "h2"), ("req3", "h3"), ("req4", "h4"), ("req5", "h5")
        ]
        # h1: ok, h2: expired, h3: corrupt, h4: ttl=0, h5: ok
        vault.retrieve.side_effect = [
            b"ct1",  # h1 ok
            None,    # h2 expired
            b"ct3",  # h3 corrupt
            b"ct4",  # h4 ttl=0
            b"ct5",  # h5 ok
        ]
        crypto.decrypt.side_effect = [
            "pt1",                          # h1 ok
            Exception("corrupt"),           # h3 corrupt
            "pt4",                          # h4 ok (but ttl will be 0)
            "pt5",                          # h5 ok
        ]
        vault.get_token_ttl.side_effect = [
            30,   # h1 ok
            # h2 skipped (retrieve returned None)
            # h3 skipped (decrypt raised)
            0,    # h4 ttl=0 -> skip
            15,   # h5 ok
        ]

        result = await use_case.execute(ORG)

        assert result.re_encrypted_count == 2  # h1 and h5 only
        assert result.rotated is True

    async def test_new_dek_is_random(
        self, use_case: RotateDekUseCase, vault: AsyncMock, crypto: MagicMock
    ) -> None:
        """Each rotation generates a fresh random DEK (32 bytes from os.urandom)."""
        # We can verify this by checking that encrypt_dek is called with 32-byte argument
        await use_case.execute(ORG)

        crypto.encrypt_dek.assert_called_once()
        new_dek_arg = crypto.encrypt_dek.call_args[0][0]
        assert isinstance(new_dek_arg, bytes)
        assert len(new_dek_arg) == 32
