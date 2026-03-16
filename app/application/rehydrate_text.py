"""
RehydrateTextUseCase — replace Privacy Shield tokens in text with original PII.

Flow:
  1. Find all tokens in text via token_format.find_all_tokens()
  2. Batch retrieve encrypted values from vault (single MGET round-trip)
  3. Resolve the org DEK
  4. Decrypt each encrypted value
  5. Replace tokens with plaintext (right-to-left, preserving offsets)
  6. Return rehydrated text and count of successfully rehydrated tokens

Tokens that cannot be found in the vault (expired or never stored) are left
as-is in the output. This is intentional: callers should not assume that
every token in a text is always resolvable (e.g. TTL may have elapsed).
"""
from __future__ import annotations

import time

from app.domain.entities import RehydrateResult
from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.vault_port import VaultPort
from app.domain.services.token_format import find_all_tokens
from app.infrastructure.telemetry import get_logger

_logger = get_logger("rehydrate_text")


class RehydrateTextUseCase:
  """Replace opaque tokens in text with their original plaintext PII values."""

  def __init__(
    self,
    vault: VaultPort,
    crypto: CryptoPort,
  ) -> None:
    self._vault = vault
    self._crypto = crypto

  async def execute(
    self,
    text: str,
    org_id: str,
    request_id: str,
  ) -> RehydrateResult:
    """
    Rehydrate all tokens found in 'text'.

    Args:
      text: Text containing zero or more "[#tipo:xxxx]" tokens.
      org_id: Organization UUID — identifies which DEK to use for decryption.
      request_id: UUID of the originating tokenization request. Must match the
                  request_id used during tokenize — enforces vault scoping so
                  tokens from other requests are not resolvable.

    Returns:
      RehydrateResult with substituted text and count of resolved tokens.
    """
    t0 = time.perf_counter()

    found_tokens = find_all_tokens(text)
    if not found_tokens:
      duration_ms = (time.perf_counter() - t0) * 1000.0
      return RehydrateResult(
        text=text, rehydrated_count=0, duration_ms=duration_ms
      )

    unique_hashes = list({h for _, h, _, _ in found_tokens})

    encrypted_map = await self._vault.retrieve_batch(org_id, request_id, unique_hashes)

    any_found = any(v is not None for v in encrypted_map.values())
    if not any_found:
      duration_ms = (time.perf_counter() - t0) * 1000.0
      return RehydrateResult(
        text=text, rehydrated_count=0, duration_ms=duration_ms
      )

    dek = await self._crypto.get_or_create_dek(org_id)

    decrypted_map: dict[str, str] = {}
    for hash_hex, encrypted_bytes in encrypted_map.items():
      if encrypted_bytes is None:
        continue
      try:
        decrypted_map[hash_hex] = self._crypto.decrypt(dek, encrypted_bytes, associated_data=org_id.encode())
      except Exception:
        _logger.warning(
          "Failed to decrypt token %s for org %s", hash_hex, org_id
        )

    rehydrated_text, count = _replace_tokens(text, found_tokens, decrypted_map)

    duration_ms = (time.perf_counter() - t0) * 1000.0
    return RehydrateResult(
      text=rehydrated_text,
      rehydrated_count=count,
      duration_ms=duration_ms,
    )


def _replace_tokens(
  text: str,
  found_tokens: list[tuple[str, str, int, int]],
  decrypted_map: dict[str, str],
) -> tuple[str, int]:
  """
  Substitute tokens with decrypted plaintext, right-to-left.

  Args:
    text: Original text with tokens.
    found_tokens: List of (pii_type, hash_hex, start, end) from find_all_tokens().
    decrypted_map: Map from hash_hex → decrypted plaintext (only resolved entries).

  Returns:
    (rehydrated_text, count_of_substitutions)
  """
  result = list(text)
  count = 0

  for pii_type, hash_hex, start, end in sorted(
    found_tokens, key=lambda t: t[2], reverse=True
  ):
    plaintext = decrypted_map.get(hash_hex)
    if plaintext is not None:
      result[start:end] = list(plaintext)
      count += 1

  return "".join(result), count
