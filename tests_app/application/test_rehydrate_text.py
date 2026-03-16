"""
RehydrateTextUseCase tests — token replacement with mocked ports.

Adversarial Analysis:
  1. Missing token in vault (expired/flushed) must leave token as-is (not crash).
  2. Decryption failure (tampered ciphertext) must leave token as-is and log warning.
  3. No tokens in text must return text unchanged with zero overhead.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.rehydrate_text import RehydrateTextUseCase
from app.domain.entities import RehydrateResult


ORG_ID = "00000000-0000-0000-0000-000000000001"
REQUEST_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture
def use_case(mock_vault: AsyncMock, mock_crypto: MagicMock) -> RehydrateTextUseCase:
    return RehydrateTextUseCase(vault=mock_vault, crypto=mock_crypto)


class TestRehydrateSingleToken:
    """Single token in text: rehydrated to original value."""

    async def test_single_token_rehydrated(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_vault.retrieve_batch.return_value = {"a3f2": b"encrypted_mario"}
        mock_crypto.decrypt.return_value = "Mario"

        result = await use_case.execute("Ciao [#pe:a3f2]!", ORG_ID, request_id=REQUEST_ID)

        assert isinstance(result, RehydrateResult)
        assert result.text == "Ciao Mario!"
        assert result.rehydrated_count == 1
        assert result.duration_ms >= 0.0


class TestRehydrateMultipleTokens:
    """Multiple tokens in text: all rehydrated."""

    async def test_multiple_tokens_all_rehydrated(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_vault.retrieve_batch.return_value = {
            "a3f2": b"enc_mario",
            "7b2c": b"enc_phone",
        }
        # decrypt called with different ciphertexts
        mock_crypto.decrypt.side_effect = lambda dek, ct, associated_data=None: {
            b"enc_mario": "Mario",
            b"enc_phone": "+39 333 1234567",
        }[ct]

        result = await use_case.execute(
            "Chiama [#pe:a3f2] al [#tel:7b2c]", ORG_ID, request_id=REQUEST_ID
        )

        assert result.text == "Chiama Mario al +39 333 1234567"
        assert result.rehydrated_count == 2


class TestRehydrateMissingToken:
    """Token not found in vault (expired/flushed): left as-is."""

    async def test_missing_token_left_as_is(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        mock_vault.retrieve_batch.return_value = {"a3f2": None}

        result = await use_case.execute("Ciao [#pe:a3f2]!", ORG_ID, request_id=REQUEST_ID)

        assert result.text == "Ciao [#pe:a3f2]!"
        assert result.rehydrated_count == 0


class TestRehydrateMixedFoundAndMissing:
    """Partial rehydration: some found, some not."""

    async def test_partial_rehydration(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_vault.retrieve_batch.return_value = {
            "a3f2": b"enc_mario",
            "7b2c": None,  # expired
        }
        mock_crypto.decrypt.return_value = "Mario"

        result = await use_case.execute(
            "[#pe:a3f2] chiama [#tel:7b2c]", ORG_ID, request_id=REQUEST_ID
        )

        assert "Mario" in result.text
        assert "[#tel:7b2c]" in result.text
        assert result.rehydrated_count == 1


class TestRehydrateNoTokensInText:
    """Text without any tokens: unchanged, fast path."""

    async def test_no_tokens_text_unchanged(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        result = await use_case.execute("Testo senza token.", ORG_ID, request_id=REQUEST_ID)

        assert result.text == "Testo senza token."
        assert result.rehydrated_count == 0
        # Vault should NOT be called (fast path)
        mock_vault.retrieve_batch.assert_not_called()


class TestRehydrateDecryptionFailure:
    """Decryption failure (tampered ciphertext): token left as-is, no crash."""

    async def test_decrypt_failure_leaves_token(
        self,
        use_case: RehydrateTextUseCase,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_vault.retrieve_batch.return_value = {"a3f2": b"tampered_data"}
        mock_crypto.decrypt.side_effect = Exception("InvalidTag")

        result = await use_case.execute("Ciao [#pe:a3f2]!", ORG_ID, request_id=REQUEST_ID)

        # Token left in place, not crashed
        assert result.text == "Ciao [#pe:a3f2]!"
        assert result.rehydrated_count == 0


class TestRehydrateEmptyText:
    """Empty text string."""

    async def test_empty_text_returns_empty(
        self,
        use_case: RehydrateTextUseCase,
    ) -> None:
        result = await use_case.execute("", ORG_ID, request_id=REQUEST_ID)
        assert result.text == ""
        assert result.rehydrated_count == 0
