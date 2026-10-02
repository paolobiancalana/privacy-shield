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
import hashlib
import uuid

import redis.asyncio as aioredis

from app.domain.ports.vault_port import VaultPort, RotationSnapshot
from redis.exceptions import WatchError

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
    expected_dek: bytes | None = None,
  ) -> bool:
    """Guard against a writer encrypting with a DEK retired by rotation."""
    if ttl_seconds <= 0:
      raise ValueError("Token TTL must be positive")
    async with self._redis.pipeline(transaction=True) as pipe:
      try:
        await pipe.watch(self._dek_key(org_id))
        if expected_dek is not None and await pipe.get(self._dek_key(org_id)) != expected_dek:
          return False
        pipe.multi()
        pipe.set(self._token_key(org_id, request_id, token_hash), encrypted_value, ex=ttl_seconds)
        pipe.set(f"ps:revision:{org_id}", uuid.uuid4().hex.encode())
        # Register in the same transaction: flush/rotation cannot miss a
        # token because its writer died between SET and SADD.
        pipe.sadd(self._request_key(org_id, request_id), token_hash)
        pipe.expire(self._request_key(org_id, request_id), ttl_seconds)
        await pipe.execute()
        return True
      except WatchError:
        return False

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
    """Atomic create-or-read with WATCH/MULTI; never overwrite a winner.

    Bounded contention fails closed. Network/Redis errors propagate; there
    is no unguarded fallback after losing the watched state.
    """
    key = self._dek_key(org_id)
    for _ in range(5):
      async with self._redis.pipeline(transaction=True) as pipe:
        try:
          await pipe.watch(key)
          existing = await pipe.get(key)
          if existing is not None:
            return existing
          pipe.multi()
          pipe.set(key, encrypted_dek)
          await pipe.execute()
          return encrypted_dek
        except WatchError:
          continue
    raise RuntimeError("DEK creation contention")

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

  async def retrieve_batch_with_dek(self, org_id: str, request_id: str, token_hashes: list[str]) -> tuple[bytes | None, dict[str, bytes | None]]:
    values = await self._redis.mget(self._dek_key(org_id), *[
      self._token_key(org_id, request_id, h) for h in token_hashes
    ])
    return values[0], dict(zip(token_hashes, values[1:]))

  def _rotation_key(self, org_id: str, operation_id: str) -> str:
    digest = hashlib.sha256(operation_id.encode()).hexdigest()
    return f"ps:rotation:{org_id}:{digest}"

  async def rotation_result(self, org_id: str, operation_id: str) -> int | None:
    raw = await self._redis.get(self._rotation_key(org_id, operation_id))
    return int(raw) if raw is not None else None

  async def snapshot_rotation(self, org_id: str) -> RotationSnapshot:
    dek, revision = await self._redis.mget(self._dek_key(org_id), f"ps:revision:{org_id}")
    tokens = {}
    prefix = f"ps:{org_id}:"
    async for key in self._redis.scan_iter(match=prefix + "*", count=100):
      decoded = key.decode() if isinstance(key, bytes) else key
      request_id, token_hash = decoded[len(prefix):].rsplit(":", 1)
      value = await self._redis.get(key)
      if value is not None:
        tokens[(request_id, token_hash)] = value
    return RotationSnapshot(dek, revision, tokens)

  async def commit_rotation(self, org_id: str, snapshot: RotationSnapshot, encrypted_dek: bytes, tokens: dict[tuple[str, str], bytes], operation_id: str) -> int | None:
    dek_key = self._dek_key(org_id)
    revision_key = f"ps:revision:{org_id}"
    result_key = self._rotation_key(org_id, operation_id)
    keys = [self._token_key(org_id, r, h) for r, h in snapshot.tokens]
    async with self._redis.pipeline(transaction=True) as pipe:
      try:
        await pipe.watch(dek_key, revision_key, result_key, *keys)
        result = await pipe.get(result_key)
        if result is not None:
          return int(result)
        dek, revision = await pipe.mget(dek_key, revision_key)
        if dek != snapshot.encrypted_dek or revision != snapshot.revision:
          return None
        live = []
        for pair, key in zip(snapshot.tokens, keys):
          value = await pipe.get(key)
          if value is None:
            continue  # expired/flushed: never resurrect
          if value != snapshot.tokens[pair]:
            return None
          if await pipe.pttl(key) < 0:
            raise RuntimeError("Vault token has no expiry")
          live.append((key, tokens[pair]))
        pipe.multi()
        for key, value in live:
          pipe.set(key, value, xx=True, keepttl=True)
        pipe.set(dek_key, encrypted_dek)
        pipe.set(revision_key, uuid.uuid4().hex.encode())
        pipe.set(result_key, len(live))
        await pipe.execute()
        return len(live)
      except WatchError:
        return None
