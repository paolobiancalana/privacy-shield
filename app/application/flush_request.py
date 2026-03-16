# privacy-shield/app/application/flush_request.py
"""
FlushRequestUseCase — delete all vault tokens associated with a request.

This use case implements the explicit TTL shortcut: callers invoke it
when a processing pipeline is complete so that PII does not linger in Redis
for the full 60-second TTL. GDPR Article 5(1)(e) — storage limitation.

The operation is idempotent: flushing an already-flushed request_id returns 0.
"""
from __future__ import annotations

from app.domain.entities import FlushResult
from app.domain.ports.vault_port import VaultPort


class FlushRequestUseCase:
    """Delete all token vault entries associated with (org_id, request_id)."""

    def __init__(self, vault: VaultPort) -> None:
        self._vault = vault

    async def execute(self, org_id: str, request_id: str) -> FlushResult:
        """
        Flush all tokens registered under 'request_id' for 'org_id'.

        Args:
            org_id:     Organization UUID.
            request_id: UUID identifying the processing request whose tokens
                        should be deleted.

        Returns:
            FlushResult with the number of token keys that were unlinked.
            Returns 0 if the request was already flushed or never created.
        """
        count = await self._vault.flush_request(org_id, request_id)
        return FlushResult(flushed_count=count)
