"""
RedisVaultAdapter — implements VaultPort using redis.asyncio.

Key schema:
  ps:{org_id}:{request_id}:{token_hash}   → encrypted PII bytes          TTL = token_ttl_seconds
  ps:req:{org_id}:{request_id}            → Redis SET of token hashes    TTL = token_ttl_seconds
  ps:dek:{org_id}                         → encrypted DEK bytes           NO TTL

Including request_id in the token key ensures that rehydration is scoped to the
originating request. A key holder in the same org cannot reconstruct tokens from
a different request, which eliminates the cross-request token injection vector.

All keys are namespaced under the "ps:" prefix to avoid collisions with
other Redis consumers. UNLINK is used instead of DEL for non-blocking removal.
"""
from __future__ import annotations

import logging

import redis.asyncio as aioredis

from app.domain.ports.vault_port import VaultPort

_logger = logging.getLogger(__name__)


class RedisVaultAdapter(VaultPort):
  """
  Async Redis adapter for the Privacy Shield vault.

  A single shared connection pool is injected at construction time;
  the adapter does not own the pool lifecycle (Container does).
  """

  _TOKEN_PREFIX = "ps"
  _REQUEST_PREFIX = "ps:req"
  _DEK_PREFIX = "ps:dek"

  def __init__(self, redis_client: aioredis.Redis) -> None:
    self._redis = redis_client

  def _token_key(self, org_id: str, request_id: str, token_hash: str) -> str:
    """Build a request-scoped vault key: ps:{org_id}:{request_id}:{token_hash}."""
    return f"{self._TOKEN_PREFIX}:{org_id}:{request_id}:{token_hash}"

  def _request_key(self, org_id: str, request_id: str) -> str:
    """Build a request tracking key: ps:req:{org_id}:{request_id}."""
    return f"{self._REQUEST_PREFIX}:{org_id}:{request_id}"

  def _dek_key(self, org_id: str) -> str:
    """Build a DEK storage key: ps:dek:{org_id}."""
    return f"{self._DEK_PREFIX}:{org_id}"

  async def store(
    self,
    org_id: str,
    request_id: str,
    token_hash: str,
    encrypted_value: bytes,
    ttl_seconds: int,
  ) -> None:
    """SET ps:{org_id}:{request_id}:{token_hash} with TTL."""
    await self._redis.set(
      self._token_key(org_id, request_id, token_hash),
      encrypted_value,
      ex=ttl_seconds,
    )

  async def retrieve(self, org_id: str, request_id: str, token_hash: str) -> bytes | None:
    """GET ps:{org_id}:{request_id}:{token_hash}. Returns None on miss or expiry."""
    value: bytes | None = await self._redis.get(
      self._token_key(org_id, request_id, token_hash)
    )
    return value

  async def retrieve_batch(
    self, org_id: str, request_id: str, token_hashes: list[str]
  ) -> dict[str, bytes | None]:
    """
    MGET multiple token keys in a single Redis round-trip.

    Returns {token_hash: encrypted_bytes | None} for every requested hash.
    """
    if not token_hashes:
      return {}

    keys = [self._token_key(org_id, request_id, h) for h in token_hashes]
    values: list[bytes | None] = await self._redis.mget(*keys)
    return dict(zip(token_hashes, values))

  async def register_request_token(
    self,
    org_id: str,
    request_id: str,
    token_hash: str,
    ttl_seconds: int,
  ) -> None:
    """
    Add token_hash to the request SET and reset the SET's TTL.

    Uses a transactional pipeline (MULTI/EXEC) to execute SADD + EXPIRE atomically.
    """
    request_key = self._request_key(org_id, request_id)
    async with self._redis.pipeline(transaction=True) as pipe:
      pipe.sadd(request_key, token_hash)
      pipe.expire(request_key, ttl_seconds)
      await pipe.execute()

  async def flush_request(self, org_id: str, request_id: str) -> int:
    """
    Delete all tokens registered under (org_id, request_id).

    Steps:
      1. SMEMBERS → get all token hashes in the request set.
      2. UNLINK each ps:{org_id}:{request_id}:{hash} (non-blocking background deletion).
      3. DEL the request tracking key itself.

    Returns the number of token keys unlinked (may be less than set size
    if some tokens already expired before flush).
    """
    request_key = self._request_key(org_id, request_id)

    members: set[bytes] = await self._redis.smembers(request_key)
    if not members:
      return 0

    token_keys = [
      self._token_key(
        org_id,
        request_id,
        m.decode("utf-8") if isinstance(m, bytes) else m,
      )
      for m in members
    ]
    unlinked: int = await self._redis.unlink(*token_keys)

    await self._redis.delete(request_key)

    return unlinked

  async def store_dek(self, org_id: str, encrypted_dek: bytes) -> None:
    """
    Persist the encrypted DEK with NO TTL.

    Key pattern: ps:dek:{org_id}
    """
    await self._redis.set(self._dek_key(org_id), encrypted_dek)

  async def retrieve_dek(self, org_id: str) -> bytes | None:
    """Retrieve the encrypted DEK for 'org_id'. Returns None if absent."""
    value: bytes | None = await self._redis.get(self._dek_key(org_id))
    return value

  async def set_dek_if_absent(self, org_id: str, encrypted_dek: bytes) -> bytes:
    """
    Atomically store 'encrypted_dek' only if no DEK exists for 'org_id'.

    Primary path: uses a Redis Lua script for atomic GET-or-SET semantics.
    The Lua script returns the existing value if present, otherwise stores
    the new value and returns it. This eliminates the TOCTOU race in
    multi-instance deployments.

    Fallback path (e.g. test environments with fakeredis without lupa):
    If Redis EVAL is not supported, falls back to a non-atomic SET NX +
    GET sequence. This is the same behaviour as Fase 1 (last-writer-wins
    on first DEK creation for the same org). Acceptable for test environments
    and single-instance deployments.

    Lua contract: KEYS[1] = dek_key, ARGV[1] = encrypted_dek_bytes
      Returns: bytes of the stored DEK (either existing or new).
    """
    lua_script = """
    local existing = redis.call('GET', KEYS[1])
    if existing then
        return existing
    else
        redis.call('SET', KEYS[1], ARGV[1])
        return ARGV[1]
    end
    """
    key = self._dek_key(org_id)
    try:
      result: bytes = await self._redis.eval(lua_script, 1, key, encrypted_dek)
      return result
    except Exception:
      _logger.warning(
        "set_dek_if_absent: Redis EVAL unavailable for org key %r — "
        "falling back to non-atomic SET-NX (acceptable for single-instance / test envs)",
        key,
      )
      was_set: bool = await self._redis.setnx(key, encrypted_dek)
      if was_set:
        return encrypted_dek
      existing: bytes | None = await self._redis.get(key)
      if existing is not None:
        return existing
      await self._redis.set(key, encrypted_dek)
      return encrypted_dek

  async def scan_active_token_hashes(self, org_id: str) -> list[tuple[str, str]]:
    """
    Discover all active (request_id, token_hash) pairs for 'org_id' via non-blocking SCAN.

    Scans all ps:req:{org_id}:* keys and collects their SET members.
    Returns a deduplicated list of (request_id, token_hash) tuples so that
    RotateDekUseCase can pass both to retrieve/store with the new key schema.
    The same token_hash may appear under multiple request_ids — each is a
    distinct vault entry under the scoped key schema.
    """
    pattern = f"{self._REQUEST_PREFIX}:{org_id}:*"
    prefix_len = len(f"{self._REQUEST_PREFIX}:{org_id}:")
    seen: set[tuple[str, str]] = set()
    cursor = 0

    while True:
      cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
      for key in keys:
        raw_key = key.decode("utf-8") if isinstance(key, bytes) else key
        request_id = raw_key[prefix_len:]
        members: set[bytes] = await self._redis.smembers(key)
        for member in members:
          decoded = member.decode("utf-8") if isinstance(member, bytes) else member
          seen.add((request_id, decoded))
      if cursor == 0:
        break

    return list(seen)

  async def get_token_ttl(self, org_id: str, request_id: str, token_hash: str) -> int:
    """
    Return remaining TTL (seconds) for a vault entry.

    Redis TTL return values:
      -1 = key exists but has no expiry (should not happen for token keys)
      -2 = key does not exist
      N  = seconds remaining
    """
    ttl: int = await self._redis.ttl(self._token_key(org_id, request_id, token_hash))
    return ttl

  async def count_org_tokens(self, org_id: str) -> int:
    """
    Return total active token count for 'org_id' by summing SCARD of all
    ps:req:{org_id}:* tracking sets.

    Uses non-blocking SCAN to avoid blocking Redis on large keyspaces.
    Each request tracking set's cardinality corresponds to the number of
    vault tokens registered for that request.
    """
    pattern = f"{self._REQUEST_PREFIX}:{org_id}:*"
    total = 0
    cursor = 0

    while True:
      cursor, keys = await self._redis.scan(cursor=cursor, match=pattern, count=100)
      for key in keys:
        count: int = await self._redis.scard(key)
        total += count
      if cursor == 0:
        break

    return total
