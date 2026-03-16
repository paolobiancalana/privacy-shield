"""
AesCryptoAdapter — implements CryptoPort using AES-256-GCM (cryptography library).

Envelope encryption model:
  KEK (32 bytes, from env var PRIVACY_SHIELD_KEK_BASE64)
    └── Per-org DEK (32 bytes, random)
          ├── encrypt_dek(dek) → stored in Redis at ps:dek:{org_id} (no TTL)
          └── encrypt(dek, pii) → stored in Redis at ps:{org}:{hash} (TTL 60s)

Wire format for encrypted blobs (both DEK and PII values):
  bytes = nonce (12 B) + auth_tag (16 B) + ciphertext (variable)

Crypto library choice: 'cryptography' (PyCA) for AES-GCM.
Fernet is NOT used because it uses AES-CBC + HMAC, not authenticated GCM,
and does not support deterministic HMAC-SHA256 token derivation.
"""
from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.vault_port import VaultPort

_NONCE_BYTES = 12
_KEY_BYTES = 32


class AesCryptoAdapter(CryptoPort):
  """
  AES-256-GCM crypto adapter with envelope encryption.

  The KEK is validated at construction time so startup fails fast
  if the environment variable is missing or has wrong length.
  """

  def __init__(self, kek: bytes, vault: VaultPort) -> None:
    if len(kek) != _KEY_BYTES:
      raise ValueError(
        f"KEK must be exactly {_KEY_BYTES} bytes, got {len(kek)}"
      )
    self._kek = kek
    self._vault = vault
    self._kek_gcm = AESGCM(kek)

  def encrypt(self, dek: bytes, plaintext: str, associated_data: bytes | None = None) -> bytes:
    """
    AES-256-GCM encrypt 'plaintext' under 'dek'.

    Output: nonce (12 B) + tag+ciphertext (variable, GCM appends tag internally).
    The cryptography library returns tag+ciphertext concatenated; we prepend nonce.

    associated_data: Optional AAD (e.g. org_id.encode()) bound to the ciphertext.
    Decryption must supply the same value or authentication will fail.
    """
    nonce = os.urandom(_NONCE_BYTES)
    gcm = AESGCM(dek)
    tag_and_ciphertext = gcm.encrypt(nonce, plaintext.encode("utf-8"), associated_data)
    return nonce + tag_and_ciphertext

  def decrypt(self, dek: bytes, ciphertext: bytes, associated_data: bytes | None = None) -> str:
    """
    AES-256-GCM decrypt.

    Input: nonce (12 B) + tag+ciphertext (as produced by encrypt()).
    Raises cryptography.exceptions.InvalidTag if authentication fails or AAD mismatches.

    associated_data: Must match the value supplied during encryption.
    """
    if len(ciphertext) < _NONCE_BYTES + 16:
      raise ValueError(
        f"Ciphertext too short: expected at least {_NONCE_BYTES + 16} bytes, "
        f"got {len(ciphertext)}"
      )
    nonce = ciphertext[:_NONCE_BYTES]
    tag_and_ct = ciphertext[_NONCE_BYTES:]
    gcm = AESGCM(dek)
    plaintext_bytes = gcm.decrypt(nonce, tag_and_ct, associated_data)
    return plaintext_bytes.decode("utf-8")

  def hmac_token_hash(self, dek: bytes, pii_value: str) -> str:
    """
    Derive an 8-character hex token suffix from PII value using HMAC-SHA256.

    Deterministic: same (dek, pii_value) → same 8-char result per org.
    This is NOT a security-sensitive hash — it is a short display identifier.
    The actual PII is encrypted separately in the vault.
    """
    digest = hmac.new(dek, pii_value.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest[:8]

  def validate_kek(self) -> bool:
    """
    Verify the KEK by performing a dummy encrypt→decrypt round-trip.

    Uses a fixed probe value; does NOT touch the vault.
    Returns True on success, False on any exception.
    """
    _probe = "__ps_kek_probe__"
    try:
      ciphertext = self.encrypt(self._kek, _probe)
      decrypted = self.decrypt(self._kek, ciphertext)
      return decrypted == _probe
    except Exception:
      return False

  def encrypt_dek(self, dek: bytes) -> bytes:
    """Wrap raw DEK under KEK using AES-256-GCM."""
    nonce = os.urandom(_NONCE_BYTES)
    tag_and_ciphertext = self._kek_gcm.encrypt(nonce, dek, None)
    return nonce + tag_and_ciphertext

  def decrypt_dek(self, encrypted_dek: bytes) -> bytes:
    """Unwrap DEK using KEK. Raises on authentication failure."""
    if len(encrypted_dek) < _NONCE_BYTES + 16:
      raise ValueError(
        f"Encrypted DEK too short: {len(encrypted_dek)} bytes"
      )
    nonce = encrypted_dek[:_NONCE_BYTES]
    tag_and_ct = encrypted_dek[_NONCE_BYTES:]
    return self._kek_gcm.decrypt(nonce, tag_and_ct, None)

  async def get_or_create_dek(self, org_id: str) -> bytes:
    """
    Return the raw DEK for 'org_id', generating and persisting it if absent.

    Uses VaultPort.set_dek_if_absent() for atomic SET-NX semantics via a
    Redis Lua script. This eliminates the TOCTOU race condition present in
    multi-instance deployments: two concurrent first requests for the same
    org both generate a candidate DEK, but only one wins the atomic write.
    Both callers decrypt and return the *winning* DEK (the one stored in
    Redis), so all in-flight requests converge on a single DEK immediately.

    Rationale for generate-then-compare approach: generating a DEK is cheap
    (32 bytes of urandom); the alternative (read-then-maybe-write) would
    require two round-trips in the common case, whereas generate-then-set-if-
    absent always completes in one round-trip.
    """
    raw_encrypted = await self._vault.retrieve_dek(org_id)
    if raw_encrypted is not None:
      return self.decrypt_dek(raw_encrypted)

    candidate_dek = os.urandom(_KEY_BYTES)
    candidate_encrypted = self.encrypt_dek(candidate_dek)
    winning_encrypted = await self._vault.set_dek_if_absent(org_id, candidate_encrypted)

    return self.decrypt_dek(winning_encrypted)
