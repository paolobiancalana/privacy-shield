"""
RevokeApiKeyUseCase adversarial tests.

Adversarial Analysis:
  1. Revoking a nonexistent key must return False (not raise).
  2. Revoking an already-revoked key is idempotent via the port -- the use case
     must faithfully return whatever the port returns.
  3. If the port raises an exception, it must propagate (not be swallowed).

Boundary Map:
  key_hash: valid hash, empty string, very long string
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from app.application.revoke_api_key import RevokeApiKeyUseCase


@pytest.fixture
def mock_port() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def use_case(mock_port: AsyncMock) -> RevokeApiKeyUseCase:
    return RevokeApiKeyUseCase(api_key_port=mock_port)


class TestRevokeExisting:
    async def test_revoke_existing_key_returns_true(
        self, use_case: RevokeApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        mock_port.revoke_key.return_value = True
        result = await use_case.execute(key_hash="abc123")
        assert result is True
        mock_port.revoke_key.assert_called_once_with("abc123")

    async def test_revoke_passes_exact_hash_to_port(
        self, use_case: RevokeApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        mock_port.revoke_key.return_value = True
        await use_case.execute(key_hash="exact_hash_value_here")
        mock_port.revoke_key.assert_called_once_with("exact_hash_value_here")


class TestRevokeNonexistent:
    async def test_revoke_nonexistent_returns_false(
        self, use_case: RevokeApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        mock_port.revoke_key.return_value = False
        result = await use_case.execute(key_hash="no_such_hash")
        assert result is False


class TestErrorPropagation:
    async def test_port_exception_propagates(self, mock_port: AsyncMock) -> None:
        """If the port raises, the use case must NOT swallow the exception."""
        mock_port.revoke_key.side_effect = ConnectionError("Redis timeout")
        uc = RevokeApiKeyUseCase(api_key_port=mock_port)
        with pytest.raises(ConnectionError, match="Redis timeout"):
            await uc.execute(key_hash="abc")

    async def test_port_returns_non_bool_type(self, mock_port: AsyncMock) -> None:
        """If the port returns something truthy but non-bool, use case propagates as-is."""
        mock_port.revoke_key.return_value = 1
        uc = RevokeApiKeyUseCase(api_key_port=mock_port)
        result = await uc.execute(key_hash="abc")
        # The use case is a thin wrapper -- it returns whatever the port returns
        assert result == 1


class TestEdgeCases:
    async def test_empty_hash_string(
        self, use_case: RevokeApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        """Empty string hash is passed through to port (port decides behavior)."""
        mock_port.revoke_key.return_value = False
        result = await use_case.execute(key_hash="")
        assert result is False
        mock_port.revoke_key.assert_called_once_with("")
