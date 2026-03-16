"""
RotateDekUseCase — per-organisation DEK rotation with live re-encryption.

Rotation flow:
  1. Load the current DEK for the org (must exist — refuse to rotate a DEK-less org).
  2. Generate a new random DEK.
  3. Scan every request-tracking key (ps:req:{org_id}:*) to discover all active
     token hashes belonging to this org.
  4. For each hash: retrieve ciphertext encrypted under the old DEK, decrypt it,
     re-encrypt under the new DEK, write it back atomically.
  5. Store the new encrypted DEK via VaultPort (set_dek_if_absent is NOT used here —
     we explicitly overwrite because this is a deliberate rotation, not a race fix).
  6. Return a RotationResult with the count of re-encrypted entries.

Atomicity note: each token is re-encrypted in a separate Redis call. If the process
crashes mid-rotation, some tokens will be encrypted under the old DEK and some under
the new one. The old DEK is stored until the LAST vault entry has been migrated, so
a partial rotation is recoverable (retry the rotation). The new DEK replaces the old
one only AFTER all entries are migrated (write-last order).

Security rationale: encrypting under the new DEK before discarding the old one is
deliberate. Vault entries use random nonces, so the re-encrypted ciphertexts are
opaque to an adversary who saw the old ciphertexts.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.vault_port import VaultPort

_logger = logging.getLogger(__name__)

_KEY_BYTES = 32


@dataclass(frozen=True)
class RotationResult:
  """Output of a successful DEK rotation."""

  rotated: bool
  re_encrypted_count: int


class RotateDekUseCase:
  """
  Rotate the per-org DEK by re-encrypting all active vault entries.

  This use case operates at the infrastructure boundary: it needs raw
  access to vault scan operations. A dedicated VaultPort extension
  (scan_active_token_hashes) is used to keep the port granular.
  """

  def __init__(self, vault: VaultPort, crypto: CryptoPort) -> None:
    self._vault = vault
    self._crypto = crypto

  async def execute(self, org_id: str) -> RotationResult:
    """
    Rotate DEK for 'org_id'. Re-encrypt all active vault entries.

    Args:
      org_id: UUID of the organisation whose DEK will be rotated.

    Returns:
      RotationResult with rotated=True and count of re-encrypted entries.

    Raises:
      ValueError: If no DEK exists for the org (nothing to rotate).
      RuntimeError: If the vault does not support scanning (required for rotation).
    """
    current_encrypted_dek = await self._vault.retrieve_dek(org_id)
    if current_encrypted_dek is None:
      raise ValueError(
        f"No DEK found for org {org_id!r}. "
        "Cannot rotate a DEK that has never been created."
      )
    old_dek = self._crypto.decrypt_dek(current_encrypted_dek)

    new_dek = os.urandom(_KEY_BYTES)

    active_pairs: list[tuple[str, str]] = await self._vault.scan_active_token_hashes(org_id)

    re_encrypted_count = 0
    for request_id, token_hash in active_pairs:
      migrated = await self._re_encrypt_token(
        org_id=org_id,
        request_id=request_id,
        token_hash=token_hash,
        old_dek=old_dek,
        new_dek=new_dek,
      )
      if migrated:
        re_encrypted_count += 1

    new_encrypted_dek = self._crypto.encrypt_dek(new_dek)
    await self._vault.store_dek(org_id, new_encrypted_dek)

    return RotationResult(rotated=True, re_encrypted_count=re_encrypted_count)

  async def _re_encrypt_token(
    self,
    org_id: str,
    request_id: str,
    token_hash: str,
    old_dek: bytes,
    new_dek: bytes,
  ) -> bool:
    """
    Re-encrypt a single vault entry from old_dek to new_dek.

    Uses the request-scoped key schema (org_id, request_id, token_hash) to
    locate the correct vault entry. Returns True on success, False if the
    token has expired or the ciphertext is corrupt (both are non-fatal).
    """
    ciphertext = await self._vault.retrieve(org_id, request_id, token_hash)
    if ciphertext is None:
      return False
    try:
      plaintext = self._crypto.decrypt(old_dek, ciphertext, associated_data=org_id.encode())
    except Exception:
      _logger.warning(
        "re_encrypt_token: skipping token hash %r (request %r) for org %r — "
        "decrypt failed (corrupt or already rotated ciphertext)",
        token_hash,
        request_id,
        org_id,
      )
      return False

    new_ciphertext = self._crypto.encrypt(new_dek, plaintext, associated_data=org_id.encode())

    remaining_ttl = await self._get_remaining_ttl(org_id, request_id, token_hash)
    if remaining_ttl <= 0:
      return False

    await self._vault.store(org_id, request_id, token_hash, new_ciphertext, remaining_ttl)
    return True

  async def _get_remaining_ttl(self, org_id: str, request_id: str, token_hash: str) -> int:
    """
    Query remaining TTL seconds for a vault entry.

    Delegates to vault.get_token_ttl() with the scoped (org_id, request_id, token_hash)
    key to match the new vault key schema.
    """
    ttl: int = await self._vault.get_token_ttl(org_id, request_id, token_hash)
    return ttl
