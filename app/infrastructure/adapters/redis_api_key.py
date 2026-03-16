"""
RedisApiKeyAdapter — Redis-backed implementation of ApiKeyPort.

Key schema:
  ps:apikey:{key_hash}              → JSON metadata (no TTL)
  ps:apikeys                        → SET of all key_hashes (global index)
  ps:rate:{key_hash}:{minute_ts}    → INT counter (TTL 120s, sliding window)
  ps:usage:{org_id}:{yyyy-mm}:{op}  → INT counter (no TTL, billing permanent)
  ps:usage:{org_id}:{yyyy-mm}:tokens_created → INT counter (no TTL)

All key prefixes are namespaced under "ps:" to avoid collisions with the vault.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.domain.entities import ApiKeyMetadata, UsageRecord
from app.domain.ports.api_key_port import ApiKeyPort


class RedisApiKeyAdapter(ApiKeyPort):
  """
  Redis implementation of API key storage, rate limiting, and usage tracking.

  The Redis client is injected at construction time; this adapter does not
  own the connection pool lifecycle (Container does).
  """

  _APIKEY_PREFIX = "ps:apikey"
  _APIKEYS_INDEX = "ps:apikeys"
  _RATE_PREFIX = "ps:rate"
  _USAGE_PREFIX = "ps:usage"
  _RATE_KEY_TTL_SECONDS = 120

  def __init__(self, redis_client: aioredis.Redis) -> None:
    self._redis = redis_client

  def _metadata_key(self, key_hash: str) -> str:
    return f"{self._APIKEY_PREFIX}:{key_hash}"

  def _rate_key(self, key_hash: str) -> str:
    minute_ts = int(time.time()) // 60
    return f"{self._RATE_PREFIX}:{key_hash}:{minute_ts}"

  def _usage_key(self, org_id: str, month: str, operation: str) -> str:
    return f"{self._USAGE_PREFIX}:{org_id}:{month}:{operation}"

  def _metadata_to_dict(self, metadata: ApiKeyMetadata) -> dict:
    return {
      "key_id": metadata.key_id,
      "org_id": metadata.org_id,
      "key_hash": metadata.key_hash,
      "plan": metadata.plan,
      "rate_limit_per_minute": metadata.rate_limit_per_minute,
      "active": metadata.active,
      "created_at": metadata.created_at,
      "environment": metadata.environment,
    }

  def _decode_bytes(self, value: bytes | str) -> str:
    return value if isinstance(value, str) else value.decode("utf-8")

  def _int_or_zero(self, value: bytes | str | int | None) -> int:
    if value is None:
      return 0
    if isinstance(value, int):
      return value
    return int(self._decode_bytes(value))

  async def store_key(self, metadata: ApiKeyMetadata) -> None:
    """Persist metadata JSON and add the hash to the global index SET."""
    data = json.dumps(self._metadata_to_dict(metadata)).encode("utf-8")
    pipe = self._redis.pipeline(transaction=False)
    pipe.set(self._metadata_key(metadata.key_hash), data)
    pipe.sadd(self._APIKEYS_INDEX, metadata.key_hash)
    await pipe.execute()

  async def validate_key(self, key_hash: str) -> ApiKeyMetadata | None:
    """Return metadata for an active key, or None if missing/revoked."""
    raw = await self._redis.get(self._metadata_key(key_hash))
    if raw is None:
      return None
    data = json.loads(self._decode_bytes(raw))
    if not data.get("active", False):
      return None
    return ApiKeyMetadata(**data)

  async def revoke_key(self, key_hash: str) -> bool:
    """Set active=False in the stored metadata. Returns False if not found."""
    raw = await self._redis.get(self._metadata_key(key_hash))
    if raw is None:
      return False
    data = json.loads(self._decode_bytes(raw))
    data["active"] = False
    updated = json.dumps(data).encode("utf-8")
    await self._redis.set(self._metadata_key(key_hash), updated)
    return True

  async def list_keys(self, org_id: str | None = None) -> list[ApiKeyMetadata]:
    """Return all key metadata, optionally filtered by org_id."""
    all_hashes: set[bytes] = await self._redis.smembers(self._APIKEYS_INDEX)
    results: list[ApiKeyMetadata] = []
    for raw_hash in all_hashes:
      h_str = self._decode_bytes(raw_hash)
      raw = await self._redis.get(self._metadata_key(h_str))
      if raw is None:
        continue
      data = json.loads(self._decode_bytes(raw))
      if org_id is not None and data.get("org_id") != org_id:
        continue
      results.append(ApiKeyMetadata(**data))
    return results

  async def check_rate_limit(self, key_hash: str, limit: int) -> tuple[bool, int]:
    """
    Increment sliding-window counter for the current minute.

    Sets a 120-second TTL on first increment so the key always expires
    even if the process restarts mid-minute.
    """
    rate_key = self._rate_key(key_hash)
    count: int = await self._redis.incr(rate_key)
    if count == 1:
      await self._redis.expire(rate_key, self._RATE_KEY_TTL_SECONDS)
    allowed = count <= limit
    return (allowed, count)

  async def record_usage(
    self, org_id: str, operation: str, token_count: int = 0
  ) -> None:
    """Increment per-org monthly operation counter (and optional token counter)."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    pipe = self._redis.pipeline(transaction=False)
    pipe.incr(self._usage_key(org_id, month, operation))
    if token_count > 0:
      pipe.incrby(self._usage_key(org_id, month, "tokens_created"), token_count)
    await pipe.execute()

  async def get_usage(self, org_id: str, month: str) -> UsageRecord:
    """Fetch aggregated monthly usage counters for an org in a pipeline."""
    pipe = self._redis.pipeline(transaction=False)
    for op in ("tokenize", "rehydrate", "flush"):
      pipe.get(self._usage_key(org_id, month, op))
    pipe.get(self._usage_key(org_id, month, "tokens_created"))
    results = await pipe.execute()

    return UsageRecord(
      org_id=org_id,
      month=month,
      tokenize_calls=self._int_or_zero(results[0]),
      rehydrate_calls=self._int_or_zero(results[1]),
      flush_calls=self._int_or_zero(results[2]),
      total_tokens_created=self._int_or_zero(results[3]),
    )
