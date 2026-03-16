"""
VaultPort — abstract contract for ephemeral PII token storage.

Implementor: RedisVaultAdapter.
The vault stores AES-256-GCM encrypted PII values keyed by
(org_id, request_id, token_hash). Including request_id in the vault key
prevents cross-request token rehydration: a key holder from the same org
cannot rehydrate tokens from another request's vault entries.

All entries are TTL-bound (default 60 s) except the DEK key (no TTL — managed by CryptoPort).
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class VaultPort(ABC):
  """Encrypted token vault with per-request lifecycle management."""

  @abstractmethod
  async def store(
    self,
    org_id: str,
    request_id: str,
    token_hash: str,
    encrypted_value: bytes,
    ttl_seconds: int,
  ) -> None:
    """
    Persist one encrypted PII value with a TTL.

    Key pattern: ps:{org_id}:{request_id}:{token_hash}
    The request_id scopes the vault entry so only the originating
    request can rehydrate it, preventing cross-request PII access.
    """
    ...

  @abstractmethod
  async def retrieve(self, org_id: str, request_id: str, token_hash: str) -> bytes | None:
    """
    Retrieve one encrypted value. Returns None if key is absent or expired.

    Key pattern: ps:{org_id}:{request_id}:{token_hash}
    """
    ...

  @abstractmethod
  async def retrieve_batch(
    self, org_id: str, request_id: str, token_hashes: list[str]
  ) -> dict[str, bytes | None]:
    """
    Retrieve multiple encrypted values in a single round-trip (MGET).

    Returns a mapping from token_hash → encrypted_bytes | None.
    Missing / expired keys map to None.
    """
    ...

  @abstractmethod
  async def register_request_token(
    self,
    org_id: str,
    request_id: str,
    token_hash: str,
    ttl_seconds: int,
  ) -> None:
    """
    Associate token_hash with a request so it can be flushed atomically.

    Key pattern: ps:req:{org_id}:{request_id}  (Redis SET)
    The SET key TTL is reset to ttl_seconds on every SADD call.
    """
    ...

  @abstractmethod
  async def flush_request(self, org_id: str, request_id: str) -> int:
    """
    Delete all tokens belonging to a request and the request tracking key.

    Steps:
      1. SMEMBERS ps:req:{org_id}:{request_id}
      2. UNLINK each ps:{org_id}:{request_id}:{hash}
      3. DEL ps:req:{org_id}:{request_id}

    Returns the number of token keys unlinked.
    """
    ...

  @abstractmethod
  async def store_dek(self, org_id: str, encrypted_dek: bytes) -> None:
    """
    Persist the encrypted DEK with NO TTL.

    Key pattern: ps:dek:{org_id}
    The DEK lifecycle is longer than individual token TTLs.
    """
    ...

  @abstractmethod
  async def retrieve_dek(self, org_id: str) -> bytes | None:
    """
    Retrieve the encrypted DEK for 'org_id'.

    Returns None if absent.
    Key pattern: ps:dek:{org_id}
    """
    ...

  @abstractmethod
  async def set_dek_if_absent(self, org_id: str, encrypted_dek: bytes) -> bytes:
    """
    Atomically store 'encrypted_dek' only if no DEK exists for 'org_id'.

    Implemented with a Redis Lua SET-NX script to eliminate the race condition
    present in a multi-instance deployment where two concurrent first requests
    for the same org could each generate and overwrite each other's DEK.

    Returns the encrypted DEK that is now stored (either the existing one
    if already present, or 'encrypted_dek' if it was the first writer).
    The caller should decrypt the returned bytes to obtain the raw DEK.

    Key pattern: ps:dek:{org_id} (no TTL)
    """
    ...

  @abstractmethod
  async def scan_active_token_hashes(self, org_id: str) -> list[tuple[str, str]]:
    """
    Return all active (request_id, token_hash) pairs belonging to 'org_id'.

    Implemented by scanning all ps:req:{org_id}:* keys and collecting
    their SET members (SMEMBERS). Returns deduplicated (request_id, token_hash)
    tuples so RotateDekUseCase can pass both to retrieve/store.
    Used exclusively by RotateDekUseCase.

    Note: SCAN is non-blocking and cursor-based in Redis; this method
    should use SCAN with a MATCH pattern rather than KEYS to avoid
    blocking the server on large keyspaces.
    """
    ...

  @abstractmethod
  async def get_token_ttl(self, org_id: str, request_id: str, token_hash: str) -> int:
    """
    Return the remaining TTL (in seconds) for a vault entry.

    Returns -1 if the key has no TTL (permanent) or -2 if it does not exist.
    Used by RotateDekUseCase to preserve expiry semantics during re-encryption.

    Key pattern: ps:{org_id}:{request_id}:{token_hash}
    """
    ...

  @abstractmethod
  async def count_org_tokens(self, org_id: str) -> int:
    """
    Return the total number of active vault tokens for 'org_id'.

    Implemented by scanning all ps:req:{org_id}:* request tracking sets
    and summing their SCARD values. Used to enforce per-org token quotas
    before new tokens are stored (Breach #5 fix).

    Note: SCAN is non-blocking; this method uses SCAN with MATCH to avoid
    blocking on large keyspaces.
    """
    ...
