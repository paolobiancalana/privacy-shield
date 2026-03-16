"""
FlushRequestUseCase tests — idempotent flush delegation.

Adversarial Analysis:
  1. Double flush must return 0 on second call (idempotent).
  2. Flush for non-existent request must return 0 (not error).
  3. Flush must delegate to vault with correct org_id + request_id.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.application.flush_request import FlushRequestUseCase
from app.domain.entities import FlushResult


ORG_ID = "00000000-0000-0000-0000-000000000001"
REQUEST_ID = "00000000-0000-0000-0000-000000000099"


@pytest.fixture
def use_case(mock_vault: AsyncMock) -> FlushRequestUseCase:
    return FlushRequestUseCase(vault=mock_vault)


class TestFlushDelegation:
    """Flush delegates to vault with correct parameters."""

    async def test_delegates_to_vault_flush_request(
        self,
        use_case: FlushRequestUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        mock_vault.flush_request.return_value = 3

        result = await use_case.execute(ORG_ID, REQUEST_ID)

        assert isinstance(result, FlushResult)
        assert result.flushed_count == 3
        mock_vault.flush_request.assert_called_once_with(ORG_ID, REQUEST_ID)


class TestFlushIdempotent:
    """Double flush returns 0 on second call."""

    async def test_double_flush_returns_zero(
        self,
        use_case: FlushRequestUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        mock_vault.flush_request.side_effect = [5, 0]

        result1 = await use_case.execute(ORG_ID, REQUEST_ID)
        result2 = await use_case.execute(ORG_ID, REQUEST_ID)

        assert result1.flushed_count == 5
        assert result2.flushed_count == 0


class TestFlushNonExistentRequest:
    """Flush for request that was never created."""

    async def test_non_existent_request_returns_zero(
        self,
        use_case: FlushRequestUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        mock_vault.flush_request.return_value = 0
        result = await use_case.execute(ORG_ID, "nonexistent-id")
        assert result.flushed_count == 0


class TestFlushVaultError:
    """Vault error propagates."""

    async def test_vault_error_propagates(
        self,
        use_case: FlushRequestUseCase,
        mock_vault: AsyncMock,
    ) -> None:
        mock_vault.flush_request.side_effect = ConnectionError("Redis down")
        with pytest.raises(ConnectionError, match="Redis down"):
            await use_case.execute(ORG_ID, REQUEST_ID)
