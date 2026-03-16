"""
CreateApiKeyUseCase — generate a new API key, hash it, and persist metadata.

The raw key is returned exactly once (in CreateApiKeyResult.raw_key) and is
NEVER stored anywhere in the system. Only the SHA-256 hash of the raw key
is written to Redis. If the caller loses the raw key, it cannot be recovered.

Key format:
  Live keys:  ps_live_<32 hex chars>   (e.g. ps_live_4a3f9b1c...)
  Test keys:  ps_test_<32 hex chars>   (e.g. ps_test_7d2e0a4b...)
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.entities import ApiKeyMetadata
from app.domain.ports.api_key_port import ApiKeyPort


@dataclass(frozen=True)
class CreateApiKeyResult:
  """
  The return value of a successful CreateApiKeyUseCase execution.

  Attributes:
    raw_key: Plaintext API key shown once to the caller. Never log this.
    metadata: Persisted metadata (contains the SHA-256 hash, never the raw key).
  """

  raw_key: str
  metadata: ApiKeyMetadata


class CreateApiKeyUseCase:
  """Generate, hash, and store a new API key for an organization."""

  def __init__(self, api_key_port: ApiKeyPort) -> None:
    self._port = api_key_port

  async def execute(
    self,
    org_id: str,
    plan: str = "standard",
    rate_limit: int = 100,
    environment: str = "live",
  ) -> CreateApiKeyResult:
    """
    Create and persist a new API key.

    Steps:
      1. Generate 16 cryptographically random bytes (32 hex chars).
      2. Prepend the environment prefix to form the raw key.
      3. SHA-256 hash the raw key for Redis storage.
      4. Persist ApiKeyMetadata via the port.
      5. Return the raw key + metadata (raw key shown once, never stored).

    Args:
      org_id: Organization identifier.
      plan: Subscription plan name.
      rate_limit: Maximum API calls per minute.
      environment: "live" or "test".

    Returns:
      CreateApiKeyResult with the raw key and persisted metadata.
    """
    prefix = "ps_live_" if environment == "live" else "ps_test_"
    random_hex = os.urandom(16).hex()
    raw_key = f"{prefix}{random_hex}"

    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_id = f"kid_{random_hex[:12]}"

    metadata = ApiKeyMetadata(
      key_id=key_id,
      org_id=org_id,
      key_hash=key_hash,
      plan=plan,
      rate_limit_per_minute=rate_limit,
      active=True,
      created_at=datetime.now(timezone.utc).isoformat(),
      environment=environment,
    )

    await self._port.store_key(metadata)
    return CreateApiKeyResult(raw_key=raw_key, metadata=metadata)
