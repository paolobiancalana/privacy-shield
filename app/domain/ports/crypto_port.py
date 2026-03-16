# privacy-shield/app/domain/ports/crypto_port.py
"""
CryptoPort — abstract contract for envelope-encryption operations.

Implementor: AesCryptoAdapter.
Encapsulates AES-256-GCM symmetric encryption, HMAC token-hash derivation,
and DEK lifecycle (creation, envelope-encrypt/decrypt, per-org retrieval).

All methods that touch the vault (get_or_create_dek) are async because
DEK storage requires an I/O round-trip to Redis.
Pure crypto operations (encrypt, decrypt, hmac_token_hash) are synchronous —
they perform only CPU work and can be safely awaited if wrapped.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class CryptoPort(ABC):
    """AES-256-GCM crypto primitives and DEK lifecycle management."""

    # ------------------------------------------------------------------
    # Pure crypto primitives (synchronous — CPU-only)
    # ------------------------------------------------------------------

    @abstractmethod
    def encrypt(self, dek: bytes, plaintext: str, associated_data: bytes | None = None) -> bytes:
        """
        Encrypt 'plaintext' under 'dek' using AES-256-GCM.

        Output format: nonce (12 B) + auth_tag (16 B) + ciphertext
        A fresh random nonce is generated for every call.

        associated_data: Optional AAD bound to the ciphertext for cross-tenant
        isolation. Typically org_id.encode(). Decryption must supply the same value.
        """
        ...

    @abstractmethod
    def decrypt(self, dek: bytes, ciphertext: bytes, associated_data: bytes | None = None) -> str:
        """
        Decrypt 'ciphertext' using AES-256-GCM with 'dek'.

        Expected input format: nonce (12 B) + auth_tag (16 B) + ciphertext.
        Raises ValueError if authentication fails (tampered data or wrong AAD).

        associated_data: Must match the value used during encryption.
        """
        ...

    @abstractmethod
    def hmac_token_hash(self, dek: bytes, pii_value: str) -> str:
        """
        Derive an 8-character hex token suffix from the PII value.

        Algorithm: HMAC-SHA256(dek, pii_value.encode('utf-8')).hexdigest()[:8]
        Deterministic: identical inputs always produce identical output.
        """
        ...

    # ------------------------------------------------------------------
    # DEK envelope operations (synchronous — CPU-only)
    # ------------------------------------------------------------------

    @abstractmethod
    def encrypt_dek(self, dek: bytes) -> bytes:
        """
        Wrap a raw DEK under the master KEK using AES-256-GCM.

        Output format: nonce (12 B) + auth_tag (16 B) + encrypted_dek
        """
        ...

    @abstractmethod
    def decrypt_dek(self, encrypted_dek: bytes) -> bytes:
        """
        Unwrap an encrypted DEK using the master KEK.

        Raises ValueError if the KEK is wrong or data is tampered.
        """
        ...

    @abstractmethod
    def validate_kek(self) -> bool:
        """
        Perform a dummy encrypt→decrypt round-trip to verify the KEK is valid.

        Returns True if the KEK can successfully encrypt and decrypt a probe
        value. Returns False if the round-trip fails (e.g. corrupted key).
        Must not raise — exceptions are caught and treated as False.
        """
        ...

    # ------------------------------------------------------------------
    # Per-org DEK retrieval (async — involves I/O to vault)
    # ------------------------------------------------------------------

    @abstractmethod
    async def get_or_create_dek(self, org_id: str) -> bytes:
        """
        Return the raw DEK for 'org_id', creating and persisting it if absent.

        Flow:
          1. Read ps:dek:{org_id} from vault (fast path — no TTL key).
          2. If present: decrypt_dek() → return raw bytes.
          3. If absent: generate candidate DEK → encrypt_dek() → call
             vault.set_dek_if_absent() (atomic Lua SET-NX) → decrypt the
             *winning* encrypted DEK (may be ours or a concurrent writer's).

        Concurrency guarantee: concurrent first requests for the same org
        all converge on the same DEK. No last-writer-wins race condition.
        The encrypted DEK is stored without TTL so it survives token TTL expiry.
        """
        ...
