"""
AesCryptoAdapter tests — AES-256-GCM, HMAC, DEK envelope.

Adversarial Analysis:
  1. Tampered ciphertext must raise on decrypt (not silent corruption).
  2. Same plaintext encrypted twice must produce DIFFERENT ciphertexts (fresh nonce).
  3. Invalid KEK length must raise at construction (fail fast).
"""
from __future__ import annotations

import os

import pytest
from cryptography.exceptions import InvalidTag

from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter


@pytest.fixture
def kek() -> bytes:
    return b"\x01" * 32


@pytest.fixture
def crypto(kek: bytes, mock_vault) -> AesCryptoAdapter:
    return AesCryptoAdapter(kek=kek, vault=mock_vault)


@pytest.fixture
def dek() -> bytes:
    """A deterministic DEK for testing."""
    return b"\x02" * 32


class TestEncryptDecryptRoundtrip:
    """Encrypt -> decrypt roundtrip: plaintext recovered exactly."""

    def test_basic_roundtrip(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        plaintext = "Mario Rossi"
        ct = crypto.encrypt(dek, plaintext)
        recovered = crypto.decrypt(dek, ct)
        assert recovered == plaintext

    def test_roundtrip_unicode(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        plaintext = "Nome: Mario"
        ct = crypto.encrypt(dek, plaintext)
        recovered = crypto.decrypt(dek, ct)
        assert recovered == plaintext

    def test_roundtrip_empty_string(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        ct = crypto.encrypt(dek, "")
        recovered = crypto.decrypt(dek, ct)
        assert recovered == ""


class TestEncryptNonceFreshness:
    """Each encryption produces different ciphertext (fresh nonce)."""

    def test_different_ciphertexts_same_plaintext(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        ct1 = crypto.encrypt(dek, "Mario")
        ct2 = crypto.encrypt(dek, "Mario")
        assert ct1 != ct2

    def test_different_plaintexts_different_ciphertexts(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        ct1 = crypto.encrypt(dek, "Mario")
        ct2 = crypto.encrypt(dek, "Paolo")
        assert ct1 != ct2


class TestHmacDeterminism:
    """HMAC-SHA256[:4] is deterministic for same DEK + value."""

    def test_same_input_same_hash(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        h1 = crypto.hmac_token_hash(dek, "Mario Rossi")
        h2 = crypto.hmac_token_hash(dek, "Mario Rossi")
        assert h1 == h2

    def test_different_values_different_hashes(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        h1 = crypto.hmac_token_hash(dek, "Mario")
        h2 = crypto.hmac_token_hash(dek, "Paolo")
        # With very high probability these differ
        assert h1 != h2

    def test_hash_is_8_hex_chars(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        h = crypto.hmac_token_hash(dek, "test")
        assert len(h) == 8
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_deks_different_hashes(self, crypto: AesCryptoAdapter) -> None:
        dek_a = b"\x02" * 32
        dek_b = b"\x03" * 32
        h_a = crypto.hmac_token_hash(dek_a, "Mario")
        h_b = crypto.hmac_token_hash(dek_b, "Mario")
        assert h_a != h_b


class TestInvalidKek:
    """Invalid KEK raises ValueError at construction time."""

    def test_kek_too_short_raises(self, mock_vault) -> None:
        with pytest.raises(ValueError, match="KEK must be exactly 32 bytes"):
            AesCryptoAdapter(kek=b"\x01" * 16, vault=mock_vault)

    def test_kek_too_long_raises(self, mock_vault) -> None:
        with pytest.raises(ValueError, match="KEK must be exactly 32 bytes"):
            AesCryptoAdapter(kek=b"\x01" * 64, vault=mock_vault)

    def test_kek_empty_raises(self, mock_vault) -> None:
        with pytest.raises(ValueError, match="KEK must be exactly 32 bytes"):
            AesCryptoAdapter(kek=b"", vault=mock_vault)


class TestTamperedCiphertext:
    """Tampered ciphertext must raise, not produce silent corruption."""

    def test_flipped_bit_raises_invalid_tag(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        ct = crypto.encrypt(dek, "Mario")
        tampered = bytearray(ct)
        tampered[-1] ^= 0xFF  # flip last byte
        with pytest.raises((InvalidTag, ValueError)):
            crypto.decrypt(dek, bytes(tampered))

    def test_truncated_ciphertext_raises(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        ct = crypto.encrypt(dek, "Mario")
        truncated = ct[:10]  # less than nonce + tag
        with pytest.raises(ValueError, match="Ciphertext too short"):
            crypto.decrypt(dek, truncated)

    def test_empty_ciphertext_raises(self, crypto: AesCryptoAdapter, dek: bytes) -> None:
        with pytest.raises(ValueError, match="Ciphertext too short"):
            crypto.decrypt(dek, b"")


class TestDekEnvelope:
    """DEK envelope: encrypt_dek -> decrypt_dek roundtrip."""

    def test_dek_roundtrip(self, crypto: AesCryptoAdapter) -> None:
        raw_dek = os.urandom(32)
        encrypted = crypto.encrypt_dek(raw_dek)
        recovered = crypto.decrypt_dek(encrypted)
        assert recovered == raw_dek

    def test_dek_different_encryptions(self, crypto: AesCryptoAdapter) -> None:
        raw_dek = os.urandom(32)
        enc1 = crypto.encrypt_dek(raw_dek)
        enc2 = crypto.encrypt_dek(raw_dek)
        assert enc1 != enc2  # fresh nonce each time

    def test_dek_tampered_raises(self, crypto: AesCryptoAdapter) -> None:
        raw_dek = os.urandom(32)
        encrypted = crypto.encrypt_dek(raw_dek)
        tampered = bytearray(encrypted)
        tampered[-1] ^= 0xFF
        with pytest.raises((InvalidTag, ValueError)):
            crypto.decrypt_dek(bytes(tampered))

    def test_dek_truncated_raises(self, crypto: AesCryptoAdapter) -> None:
        with pytest.raises(ValueError, match="Encrypted DEK too short"):
            crypto.decrypt_dek(b"\x00" * 10)


class TestGetOrCreateDek:
    """get_or_create_dek: async DEK lifecycle via vault."""

    async def test_creates_new_dek_when_absent(
        self, crypto: AesCryptoAdapter, mock_vault
    ) -> None:
        # T4.3: get_or_create_dek now uses set_dek_if_absent (atomic Lua SET-NX)
        # instead of store_dek to eliminate the multi-instance race condition.
        mock_vault.retrieve_dek.return_value = None
        dek = await crypto.get_or_create_dek("org-1")
        assert len(dek) == 32
        mock_vault.set_dek_if_absent.assert_called_once()
        # store_dek is no longer called by get_or_create_dek (replaced by set_dek_if_absent)
        mock_vault.store_dek.assert_not_called()

    async def test_retrieves_existing_dek(
        self, crypto: AesCryptoAdapter, mock_vault
    ) -> None:
        # Fast path: DEK already exists — no write needed.
        raw_dek = os.urandom(32)
        encrypted = crypto.encrypt_dek(raw_dek)
        mock_vault.retrieve_dek.return_value = encrypted

        recovered = await crypto.get_or_create_dek("org-1")
        assert recovered == raw_dek
        mock_vault.store_dek.assert_not_called()
        mock_vault.set_dek_if_absent.assert_not_called()
