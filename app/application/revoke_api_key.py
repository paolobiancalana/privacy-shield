"""
RevokeApiKeyUseCase — deactivate an API key by its SHA-256 hash.

Revoking a key sets active=False in the metadata. The key entry is kept in
Redis so that audit trails remain intact. Subsequent calls to validate_key
will return None for revoked keys.
"""
from __future__ import annotations

from app.domain.ports.api_key_port import ApiKeyPort


class RevokeApiKeyUseCase:
  """Deactivate an API key identified by its SHA-256 hash."""

  def __init__(self, api_key_port: ApiKeyPort) -> None:
    self._port = api_key_port

  async def execute(self, key_hash: str) -> bool:
    """
    Mark the key as inactive.

    Args:
      key_hash: SHA-256 hash of the API key to revoke.

    Returns:
      True if the key existed and was revoked.
      False if the key was not found (idempotent-safe).
    """
    return await self._port.revoke_key(key_hash)
