"""Prepare rotation in memory; commit ciphertexts + DEK in one vault CAS.

An interruption before commit leaves the old state. A lost response after
commit is resolved with the same operation_id. Contention never mixes keys.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from app.domain.entities import DekNotFoundError
from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.vault_port import VaultPort


@dataclass(frozen=True)
class RotationResult:
  rotated: bool
  re_encrypted_count: int


class RotateDekUseCase:
  def __init__(self, vault: VaultPort, crypto: CryptoPort) -> None:
    self._vault = vault
    self._crypto = crypto

  async def execute(self, org_id: str, operation_id: str | None = None) -> RotationResult:
    operation_id = operation_id or str(uuid.uuid4())
    previous = await self._vault.rotation_result(org_id, operation_id)
    if previous is not None:
      return RotationResult(True, previous)
    for _ in range(5):
      snapshot = await self._vault.snapshot_rotation(org_id)
      if snapshot.encrypted_dek is None:
        raise DekNotFoundError("No DEK found for organization")
      old_dek = self._crypto.decrypt_dek(snapshot.encrypted_dek)
      new_dek = os.urandom(32)
      # Corrupt live ciphertext aborts the entire preparation. Never discard
      # its key and report a successful rotation after skipping decryption.
      tokens = {
        pair: self._crypto.encrypt(new_dek, self._crypto.decrypt(
          old_dek, value, associated_data=org_id.encode(),
        ), associated_data=org_id.encode())
        for pair, value in snapshot.tokens.items()
      }
      count = await self._vault.commit_rotation(
        org_id, snapshot, self._crypto.encrypt_dek(new_dek), tokens, operation_id,
      )
      if count is not None:
        return RotationResult(True, count)
    raise RuntimeError("DEK rotation contention; retry with the same operation_id")
