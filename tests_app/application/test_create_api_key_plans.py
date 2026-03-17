"""
CreateApiKeyUseCase plan enforcement tests.

Adversarial Analysis:
  1. When OrgPlanPort is injected, the caller-supplied 'plan' and 'rate_limit'
     params MUST be overridden by the plan's values. An attacker sending
     plan="enterprise" in the body must NOT bypass plan limits.
  2. The max_keys check counts only ACTIVE keys. Revoked keys must not count
     toward the limit, or an org could never create new keys after revoking.
  3. When OrgPlanPort is None (backward compat), the use case must use the
     caller-supplied plan/rate_limit and skip key counting entirely.

Boundary Map:
  active_keys vs max_keys: at max_keys-1 (allowed), at max_keys (blocked)
  org plan: None (not set, defaults to "free"), "free" (2 keys), "enterprise" (100 keys)
  OrgPlanPort: None (backward compat), injected (plan enforcement active)
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.application.create_api_key import CreateApiKeyUseCase
from app.domain.entities import ApiKeyMetadata, MaxKeysExceededError
from app.domain.plans import PLANS


@pytest.fixture
def mock_api_key_port() -> AsyncMock:
    port = AsyncMock()
    port.store_key = AsyncMock(return_value=None)
    port.list_keys = AsyncMock(return_value=[])
    port.store_key_if_under_limit = AsyncMock(return_value=True)
    port.count_active_keys = AsyncMock(return_value=0)
    return port


@pytest.fixture
def mock_org_plan_port() -> AsyncMock:
    port = AsyncMock()
    port.get_org_plan_id = AsyncMock(return_value=None)  # defaults to "free"
    return port


def _make_active_key_metadata(org_id: str = "org-1") -> ApiKeyMetadata:
    """Create a minimal active ApiKeyMetadata for list_keys mocking."""
    return ApiKeyMetadata(
        key_id="kid_000000000000",
        org_id=org_id,
        key_hash="a" * 64,
        plan="free",
        rate_limit_per_minute=10,
        active=True,
        created_at="2026-01-01T00:00:00Z",
        environment="live",
    )


def _make_revoked_key_metadata(org_id: str = "org-1") -> ApiKeyMetadata:
    """Create a minimal revoked ApiKeyMetadata."""
    return ApiKeyMetadata(
        key_id="kid_000000000001",
        org_id=org_id,
        key_hash="b" * 64,
        plan="free",
        rate_limit_per_minute=10,
        active=False,
        created_at="2026-01-01T00:00:00Z",
        environment="live",
    )


class TestPlanEnforcement:
    """When OrgPlanPort is provided, plan drives rate_limit and plan_id."""

    async def test_plan_overrides_caller_supplied_rate_limit(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "starter"
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(
            org_id="org-1",
            rate_limit=999,  # attacker tries high rate limit
            plan="enterprise",  # attacker tries enterprise plan label
        )
        # Must use starter plan's values, not caller's
        assert result.metadata.rate_limit_per_minute == PLANS["starter"].rate_limit_per_minute
        assert result.metadata.plan == "starter"

    async def test_defaults_to_free_when_org_has_no_plan(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = None
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(org_id="org-1")
        assert result.metadata.plan == "free"
        assert result.metadata.rate_limit_per_minute == PLANS["free"].rate_limit_per_minute

    async def test_defaults_to_free_when_plan_id_invalid(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        """If Redis returns a plan_id that no longer exists in PLANS catalog,
        use case falls back to 'free'."""
        mock_org_plan_port.get_org_plan_id.return_value = "deleted_plan"
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(org_id="org-1")
        assert result.metadata.plan == "free"

    async def test_enterprise_plan_allows_100_keys(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "enterprise"
        # store_key_if_under_limit returns True (under limit)
        mock_api_key_port.store_key_if_under_limit.return_value = True
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(org_id="org-1")
        assert result.metadata.plan == "enterprise"


class TestMaxKeysEnforcement:
    """MaxKeysExceededError must be raised at exactly max_keys active keys."""

    async def test_free_plan_blocks_at_2_active_keys(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.store_key_if_under_limit.return_value = False
        mock_api_key_port.count_active_keys.return_value = 2
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MaxKeysExceededError) as exc_info:
            await uc.execute(org_id="org-1")
        assert exc_info.value.current_keys == 2
        assert exc_info.value.max_keys == 2
        assert exc_info.value.plan_id == "free"

    async def test_free_plan_allows_at_1_active_key(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.store_key_if_under_limit.return_value = True
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(org_id="org-1")
        assert result.metadata.plan == "free"

    async def test_revoked_keys_do_not_count_toward_limit(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        """store_key_if_under_limit only counts active keys, so revoked keys
        don't affect the limit."""
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.store_key_if_under_limit.return_value = True
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(org_id="org-1")
        assert result.metadata.plan == "free"

    async def test_starter_plan_blocks_at_5_active_keys(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "starter"
        mock_api_key_port.store_key_if_under_limit.return_value = False
        mock_api_key_port.count_active_keys.return_value = 5
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MaxKeysExceededError) as exc_info:
            await uc.execute(org_id="org-1")
        assert exc_info.value.max_keys == 5
        assert exc_info.value.plan_id == "starter"

    async def test_enterprise_blocks_at_100_active_keys(
        self, mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "enterprise"
        mock_api_key_port.store_key_if_under_limit.return_value = False
        mock_api_key_port.count_active_keys.return_value = 100
        uc = CreateApiKeyUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MaxKeysExceededError):
            await uc.execute(org_id="org-1")


class TestBackwardCompatibility:
    """Without OrgPlanPort, the use case must work as before."""

    async def test_no_org_plan_port_uses_caller_supplied_plan(
        self, mock_api_key_port: AsyncMock
    ) -> None:
        uc = CreateApiKeyUseCase(api_key_port=mock_api_key_port, org_plan_port=None)
        result = await uc.execute(org_id="org-1", plan="premium", rate_limit=500)
        assert result.metadata.plan == "premium"
        assert result.metadata.rate_limit_per_minute == 500

    async def test_no_org_plan_port_skips_max_keys_check(
        self, mock_api_key_port: AsyncMock
    ) -> None:
        """Without OrgPlanPort, store_key_if_under_limit is never called and max_keys is not enforced."""
        uc = CreateApiKeyUseCase(api_key_port=mock_api_key_port, org_plan_port=None)
        await uc.execute(org_id="org-1")
        mock_api_key_port.store_key_if_under_limit.assert_not_called()
        mock_api_key_port.store_key.assert_called_once()
