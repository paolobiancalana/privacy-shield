"""
CreateApiKeyUseCase adversarial tests.

Adversarial Analysis:
  1. The raw key MUST use cryptographically random bytes. Two consecutive calls
     must produce different keys (collision probability ~2^-128 is negligible).
  2. The key hash MUST be SHA-256 of the raw key. If the hash is derived from
     something else (e.g., just the random part), an attacker could forge auth.
  3. The prefix for "live" must be "ps_live_" and "test" must be "ps_test_".
     Any other environment value is passed through to the entity which validates it.

Boundary Map:
  environment: "live" -> prefix "ps_live_", "test" -> prefix "ps_test_"
  rate_limit: default 100, minimum 1
  raw_key length: 8 (prefix) + 32 (hex) = 40 chars
  key_id: "kid_" + first 12 hex chars = 16 chars total
"""
from __future__ import annotations

import hashlib

import pytest
from unittest.mock import AsyncMock

from app.application.create_api_key import CreateApiKeyResult, CreateApiKeyUseCase


@pytest.fixture
def mock_port() -> AsyncMock:
    port = AsyncMock()
    port.store_key = AsyncMock(return_value=None)
    return port


@pytest.fixture
def use_case(mock_port: AsyncMock) -> CreateApiKeyUseCase:
    return CreateApiKeyUseCase(api_key_port=mock_port)


class TestKeyFormat:
    """Key format and structure validation."""

    async def test_live_key_has_correct_prefix(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        assert result.raw_key.startswith("ps_live_")

    async def test_test_key_has_correct_prefix(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="test")
        assert result.raw_key.startswith("ps_test_")

    async def test_key_is_exactly_40_chars(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        assert len(result.raw_key) == 40  # 8 prefix + 32 hex

    async def test_key_suffix_is_hex(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        hex_part = result.raw_key[8:]  # strip prefix
        # Must parse as hex without error
        int(hex_part, 16)
        assert len(hex_part) == 32


class TestKeyHash:
    """Key hash integrity."""

    async def test_hash_is_sha256_of_raw_key(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        expected_hash = hashlib.sha256(result.raw_key.encode("utf-8")).hexdigest()
        assert result.metadata.key_hash == expected_hash

    async def test_hash_is_64_char_hex(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        assert len(result.metadata.key_hash) == 64
        int(result.metadata.key_hash, 16)  # must be valid hex


class TestKeyId:
    """key_id format validation."""

    async def test_key_id_starts_with_kid_prefix(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", environment="live")
        assert result.metadata.key_id.startswith("kid_")

    async def test_key_id_length_is_16(self, use_case: CreateApiKeyUseCase) -> None:
        """kid_ (4) + 12 hex chars = 16."""
        result = await use_case.execute(org_id="org-1", environment="live")
        assert len(result.metadata.key_id) == 16


class TestMetadataFields:
    """Metadata propagation to stored object."""

    async def test_org_id_propagated(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-test-42")
        assert result.metadata.org_id == "org-test-42"

    async def test_plan_propagated(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", plan="enterprise")
        assert result.metadata.plan == "enterprise"

    async def test_rate_limit_propagated(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1", rate_limit=500)
        assert result.metadata.rate_limit_per_minute == 500

    async def test_active_is_true_on_creation(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1")
        assert result.metadata.active is True

    async def test_created_at_is_iso_format(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1")
        # Must parse as ISO without error
        from datetime import datetime

        datetime.fromisoformat(result.metadata.created_at)


class TestPortInteraction:
    """Verify correct calls to the ApiKeyPort."""

    async def test_store_key_called_once(
        self, use_case: CreateApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        await use_case.execute(org_id="org-1")
        mock_port.store_key.assert_called_once()

    async def test_store_key_receives_correct_metadata(
        self, use_case: CreateApiKeyUseCase, mock_port: AsyncMock
    ) -> None:
        result = await use_case.execute(org_id="org-1", plan="premium", rate_limit=200)
        stored_meta = mock_port.store_key.call_args[0][0]
        assert stored_meta.org_id == "org-1"
        assert stored_meta.plan == "premium"
        assert stored_meta.rate_limit_per_minute == 200
        assert stored_meta.key_hash == result.metadata.key_hash

    async def test_store_key_failure_propagates(self, mock_port: AsyncMock) -> None:
        """If the port raises, the use case must NOT swallow the exception."""
        mock_port.store_key.side_effect = RuntimeError("Redis down")
        uc = CreateApiKeyUseCase(api_key_port=mock_port)
        with pytest.raises(RuntimeError, match="Redis down"):
            await uc.execute(org_id="org-1")


class TestUniqueness:
    """Two key creations must produce different keys."""

    async def test_two_calls_produce_different_raw_keys(
        self, use_case: CreateApiKeyUseCase
    ) -> None:
        r1 = await use_case.execute(org_id="org-1")
        r2 = await use_case.execute(org_id="org-1")
        assert r1.raw_key != r2.raw_key

    async def test_two_calls_produce_different_hashes(
        self, use_case: CreateApiKeyUseCase
    ) -> None:
        r1 = await use_case.execute(org_id="org-1")
        r2 = await use_case.execute(org_id="org-1")
        assert r1.metadata.key_hash != r2.metadata.key_hash


class TestResultType:
    """Verify CreateApiKeyResult structure."""

    async def test_result_is_frozen_dataclass(self, use_case: CreateApiKeyUseCase) -> None:
        result = await use_case.execute(org_id="org-1")
        assert isinstance(result, CreateApiKeyResult)
        import dataclasses

        with pytest.raises(dataclasses.FrozenInstanceError):
            result.raw_key = "tampered"  # type: ignore[misc]
