"""
ApiKeyPort — abstract contract for API key authentication, rate limiting,
and per-org monthly usage tracking.

Implementor: RedisApiKeyAdapter.
Domain layer only — zero infrastructure imports.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.entities import ApiKeyMetadata, UsageRecord


class ApiKeyPort(ABC):
  """API key management, validation, rate limiting, and usage tracking."""

  @abstractmethod
  async def store_key(self, metadata: ApiKeyMetadata) -> None:
    """
    Persist a hashed API key with its metadata.

    Key pattern: ps:apikey:{key_hash}
    Also adds key_hash to the global index: ps:apikeys (Redis SET).
    """
    ...

  @abstractmethod
  async def validate_key(self, key_hash: str) -> ApiKeyMetadata | None:
    """
    Look up a key by its SHA-256 hash.

    Returns metadata if the key exists AND is active.
    Returns None if not found or if the key has been revoked (active=False).
    """
    ...

  @abstractmethod
  async def revoke_key(self, key_hash: str) -> bool:
    """
    Mark a key as inactive (active=False) without deleting it.

    Returns True if the key existed and was revoked.
    Returns False if the key was not found.
    """
    ...

  @abstractmethod
  async def list_keys(self, org_id: str | None = None) -> list[ApiKeyMetadata]:
    """
    Return all stored key metadata entries, optionally filtered by org_id.

    Includes both active and revoked keys. Never returns raw key material.
    """
    ...

  @abstractmethod
  async def check_rate_limit(self, key_hash: str, limit: int) -> tuple[bool, int]:
    """
    Increment the per-minute sliding-window counter for the given key.

    Uses key pattern: ps:rate:{key_hash}:{minute_timestamp}
    The counter expires after 120 seconds (two full minutes of buffer).

    Returns:
      tuple: (allowed, current_count) where allowed is True if
        current_count <= limit after increment.
    """
    ...

  @abstractmethod
  async def record_usage(
    self, org_id: str, operation: str, token_count: int = 0
  ) -> None:
    """
    Increment per-org monthly usage counters.

    Key pattern: ps:usage:{org_id}:{yyyy-mm}:{operation}
    If token_count > 0, also increments: ps:usage:{org_id}:{yyyy-mm}:tokens_created

    No TTL — usage counters persist indefinitely for billing purposes.
    """
    ...

  @abstractmethod
  async def get_usage(self, org_id: str, month: str) -> UsageRecord:
    """
    Retrieve aggregated usage stats for an org in a given month.

    Args:
      org_id: Organization identifier.
      month: Month in 'YYYY-MM' format (e.g. '2026-03').

    Returns:
      UsageRecord with zero counts for operations that have not been called.
    """
    ...

  @abstractmethod
  async def count_active_keys(self, org_id: str) -> int:
    """Count active (non-revoked) keys for an org. Atomic read."""
    ...

  @abstractmethod
  async def store_key_if_under_limit(self, metadata: ApiKeyMetadata, max_keys: int) -> bool:
    """Atomically check active key count and store if under limit.
    Returns True if stored, False if limit reached."""
    ...

  @abstractmethod
  async def increment_and_check_monthly_tokens(
    self, org_id: str, token_count: int, limit: int
  ) -> tuple[bool, int]:
    """Atomically increment monthly token counter and check against limit.
    Returns (allowed, new_total). If not allowed, the increment is rolled back."""
    ...
