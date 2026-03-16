"""
Security adversarial tests — tampered data, malformed tokens, collision exhaustion.

Adversarial Analysis:
  1. Tampered ciphertext must ALWAYS raise, never silently produce wrong plaintext.
  2. Malformed token strings must be rejected by parse_token.
  3. HMAC collision counter exhaustion must raise RuntimeError.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock

import pytest
from cryptography.exceptions import InvalidTag

from app.application.tokenize_text import TokenizeTextUseCase, _MAX_COLLISION_ATTEMPTS
from app.domain.entities import DetectionResult, PiiSpan
from app.domain.services.token_format import parse_token
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter


class TestTamperedCiphertext:
    """Tampered ciphertext must raise, never silently corrupt."""

    def test_single_bit_flip_raises(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Sensitive PII")

        tampered = bytearray(ct)
        # Flip a bit in the ciphertext portion (after nonce)
        tampered[15] ^= 0x01
        with pytest.raises((InvalidTag, ValueError, Exception)):
            wired_crypto.decrypt(dek, bytes(tampered))

    def test_nonce_corruption_raises(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Data")

        tampered = bytearray(ct)
        tampered[0] ^= 0xFF  # corrupt nonce
        with pytest.raises((InvalidTag, ValueError, Exception)):
            wired_crypto.decrypt(dek, bytes(tampered))

    def test_appended_bytes_raises(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Data")
        extended = ct + b"\x00\x00\x00\x00"
        with pytest.raises((InvalidTag, ValueError, Exception)):
            wired_crypto.decrypt(dek, extended)

    def test_zero_length_ciphertext_raises(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        with pytest.raises(ValueError):
            wired_crypto.decrypt(dek, b"")

    def test_wrong_dek_raises(self, wired_crypto: AesCryptoAdapter) -> None:
        dek_real = os.urandom(32)
        dek_wrong = os.urandom(32)
        ct = wired_crypto.encrypt(dek_real, "Secret")
        with pytest.raises((InvalidTag, Exception)):
            wired_crypto.decrypt(dek_wrong, ct)


class TestMalformedTokenParsing:
    """Malformed token strings must be rejected by parse_token."""

    @pytest.mark.parametrize(
        "bad_token",
        [
            "",
            "hello",
            "[pe:a3f2]",       # missing #
            "[#pe:a3f2",       # missing ]
            "#pe:a3f2]",       # missing [
            "[#pe:A3F2]",      # uppercase hex
            "[#pe:a3f]",       # 3 hex chars only
            "[#pe:a3f2g]",     # 5 hex chars
            "[#xx:a3f2]",      # invalid type
            "[#:a3f2]",        # empty type
            "[#pe:]",          # empty hash
            "[#pe:a3f2]\n",    # trailing newline
            "  [#pe:a3f2]  ",  # leading/trailing spaces
            "[#pe:a3f2][#pe:a3f2]",  # two tokens concatenated
            "\x00[#pe:a3f2]",  # null byte prefix
        ],
    )
    def test_malformed_returns_none(self, bad_token: str) -> None:
        assert parse_token(bad_token) is None


class TestCollisionExhaustion:
    """HMAC collision counter exhaustion: >50 collisions raises RuntimeError."""

    async def test_50_collisions_raises(self) -> None:
        mock_detection = AsyncMock()
        mock_vault = AsyncMock()
        mock_vault.store = AsyncMock()
        mock_vault.register_request_token = AsyncMock()
        mock_vault.count_org_tokens = AsyncMock(return_value=0)
        mock_crypto = MagicMock()
        mock_crypto.get_or_create_dek = AsyncMock(return_value=b"\x02" * 32)
        mock_crypto.encrypt = MagicMock(return_value=b"enc")
        # All values hash to same base
        mock_crypto.hmac_token_hash = MagicMock(return_value="aaaa")

        # Pre-seed 50 different values with the same hash base
        existing = {}
        for i in range(1, _MAX_COLLISION_ATTEMPTS + 1):
            suffix = f"aaaa_{i}" if i > 1 else "aaaa"
            existing[f"value_{i}"] = f"[#pe:{suffix}]"

        mock_detection.detect = AsyncMock(
            return_value=DetectionResult(
                spans=[PiiSpan(start=0, end=9, text="new_value", pii_type="pe", source="regex", confidence=1.0)],
                detection_ms=0.5,
                source="regex",
            )
        )

        use_case = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            token_ttl_seconds=60,
        )

        with pytest.raises(RuntimeError, match="Exceeded.*collision attempts"):
            await use_case.execute("new_value", "org-1", "req-1", existing_tokens=existing)


class TestNullBytesInInput:
    """Null bytes in PII text must not crash the system."""

    def test_encrypt_decrypt_with_null_bytes(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        text_with_nulls = "Mario\x00Rossi\x00"
        ct = wired_crypto.encrypt(dek, text_with_nulls)
        recovered = wired_crypto.decrypt(dek, ct)
        assert recovered == text_with_nulls

    def test_hmac_with_null_bytes(self, wired_crypto: AesCryptoAdapter) -> None:
        dek = os.urandom(32)
        h = wired_crypto.hmac_token_hash(dek, "Mario\x00Rossi")
        assert len(h) == 8
