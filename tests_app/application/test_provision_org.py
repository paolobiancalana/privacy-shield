"""
ProvisionOrgUseCase adversarial tests.

Adversarial Analysis:
  1. Idempotency race condition: two concurrent execute() calls for the same
     (org_id, environment) can both pass the active_env_keys check before either
     writes, resulting in duplicate keys. The check-then-act pattern is not atomic.
  2. Plan NOT updated on idempotent path: when the org already has an active key
     for the environment, set_org_plan is never called -- a caller intending to
     change the plan alongside re-provision gets silently ignored.
  3. Cross-tenant: list_keys(org_id) must filter by org_id. If the port ignores
     the filter, provisioning org B could see org A's keys and return created=False
     with org A's key_id -- a tenant leak.

Boundary Map:
  org_id: any string (API layer validates UUID; use case accepts anything)
  plan_id: "free" | "starter" | "business" | "enterprise"; default "free"
  environment: "live" | "test"; default "live"
  ProvisionResult.key: non-empty on created=True, "" on created=False
  ProvisionResult frozen: immutable dataclass
"""
from __future__ import annotations

import dataclasses

import pytest
from unittest.mock import AsyncMock, call

from app.application.provision_org import ProvisionOrgUseCase, ProvisionResult
from app.domain.entities import ApiKeyMetadata, MaxKeysExceededError
from app.domain.plans import PLANS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_key_metadata(
    key_id: str = "kid_aabbccddee00",
    org_id: str = "org-A",
    active: bool = True,
    environment: str = "live",
    plan: str = "free",
) -> ApiKeyMetadata:
    return ApiKeyMetadata(
        key_id=key_id,
        org_id=org_id,
        key_hash="a" * 64,
        plan=plan,
        rate_limit_per_minute=10,
        active=active,
        created_at="2026-01-01T00:00:00+00:00",
        environment=environment,
    )


@pytest.fixture
def mock_api_key_port() -> AsyncMock:
    port = AsyncMock()
    port.list_keys = AsyncMock(return_value=[])
    port.store_key = AsyncMock(return_value=None)
    port.store_key_if_under_limit = AsyncMock(return_value=True)
    port.count_active_keys = AsyncMock(return_value=0)
    return port


@pytest.fixture
def mock_org_plan_port() -> AsyncMock:
    port = AsyncMock()
    port.get_org_plan_id = AsyncMock(return_value="free")
    async def _set(org_id: str, plan_id: str) -> None:
        port.get_org_plan_id.return_value = plan_id
    port.set_org_plan = AsyncMock(side_effect=_set)
    return port


@pytest.fixture
def use_case(mock_api_key_port: AsyncMock, mock_org_plan_port: AsyncMock) -> ProvisionOrgUseCase:
    return ProvisionOrgUseCase(
        api_key_port=mock_api_key_port,
        org_plan_port=mock_org_plan_port,
    )


# ---------------------------------------------------------------------------
# Tenant Isolation
# ---------------------------------------------------------------------------


class TestTenantIsolation:
    """Cross-tenant provisioning must never leak data between orgs."""

    async def test_provision_org_a_then_org_b_returns_different_keys(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Provisioning two different orgs must produce independent keys and key_ids."""
        mock_api_key_port.list_keys.return_value = []
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result_a = await uc.execute(org_id="org-A", plan_id="free")
        result_b = await uc.execute(org_id="org-B", plan_id="free")

        assert result_a.org_id == "org-A"
        assert result_b.org_id == "org-B"
        assert result_a.key != result_b.key
        assert result_a.key_id != result_b.key_id
        assert result_a.created is True
        assert result_b.created is True

    async def test_list_keys_called_with_correct_org_id(
        self,
        use_case: ProvisionOrgUseCase,
        mock_api_key_port: AsyncMock,
    ) -> None:
        """list_keys must be called with the org_id argument to scope the query."""
        await use_case.execute(org_id="org-X")
        mock_api_key_port.list_keys.assert_called_once_with("org-X")

    async def test_idempotent_path_does_not_return_other_orgs_key(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """When org-A has a key, provisioning org-B (which has no keys) must create a new one."""
        org_a_key = _make_key_metadata(key_id="kid_orgA_key001", org_id="org-A")

        async def scoped_list_keys(org_id):
            if org_id == "org-A":
                return [org_a_key]
            return []

        mock_api_key_port.list_keys.side_effect = scoped_list_keys
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result_a = await uc.execute(org_id="org-A")
        result_b = await uc.execute(org_id="org-B")

        assert result_a.created is False
        assert result_a.key_id == "kid_orgA_key001"
        assert result_a.key == ""

        assert result_b.created is True
        assert result_b.key_id != "kid_orgA_key001"
        assert result_b.key != ""


# ---------------------------------------------------------------------------
# Error Branches
# ---------------------------------------------------------------------------


class TestErrorBranches:
    """Every Result.success === false branch must have a test."""

    async def test_max_keys_exceeded_propagates(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """MaxKeysExceededError from CreateApiKeyUseCase must propagate to the caller."""
        mock_api_key_port.list_keys.return_value = []
        mock_api_key_port.store_key_if_under_limit.return_value = False
        mock_api_key_port.count_active_keys.return_value = 2

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        with pytest.raises(MaxKeysExceededError) as exc_info:
            await uc.execute(org_id="org-1", plan_id="free")

        assert exc_info.value.org_id == "org-1"
        assert exc_info.value.max_keys == PLANS["free"].max_keys

    async def test_api_key_port_list_keys_failure_propagates(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """If list_keys raises (e.g. Redis down), the exception must not be swallowed."""
        mock_api_key_port.list_keys.side_effect = RuntimeError("Redis connection lost")

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        with pytest.raises(RuntimeError, match="Redis connection lost"):
            await uc.execute(org_id="org-1")

    async def test_set_org_plan_failure_propagates(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """If set_org_plan raises, the exception must propagate (plan not set = no key created)."""
        mock_api_key_port.list_keys.return_value = []
        mock_org_plan_port.set_org_plan.side_effect = RuntimeError("Redis SET failed")

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        with pytest.raises(RuntimeError, match="Redis SET failed"):
            await uc.execute(org_id="org-1")

    async def test_get_org_plan_id_returns_none_on_idempotent_path_defaults_to_free(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """When get_org_plan_id returns None (no plan set), idempotent path should default to 'free'."""
        existing_key = _make_key_metadata()
        mock_api_key_port.list_keys.return_value = [existing_key]
        mock_org_plan_port.get_org_plan_id.return_value = None

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A")
        assert result.plan == "free"
        assert result.created is False


# ---------------------------------------------------------------------------
# Boundary Conditions
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """Edge cases at parameter boundaries."""

    async def test_default_plan_is_free(
        self,
        use_case: ProvisionOrgUseCase,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Calling execute() without plan_id must default to 'free'."""
        await use_case.execute(org_id="org-1")
        mock_org_plan_port.set_org_plan.assert_called_once_with(
            org_id="org-1", plan_id="free"
        )

    async def test_default_environment_is_live(
        self,
        use_case: ProvisionOrgUseCase,
    ) -> None:
        """Calling execute() without environment must default to 'live'."""
        result = await use_case.execute(org_id="org-1")
        assert result.environment == "live"

    async def test_provision_result_is_frozen(
        self,
        use_case: ProvisionOrgUseCase,
    ) -> None:
        """ProvisionResult must be a frozen dataclass -- mutation must raise."""
        result = await use_case.execute(org_id="org-1")
        assert isinstance(result, ProvisionResult)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.plan = "tampered"  # type: ignore[misc]

    async def test_environment_test_creates_test_prefixed_key(
        self,
        use_case: ProvisionOrgUseCase,
    ) -> None:
        """environment='test' must produce a ps_test_ prefixed key."""
        result = await use_case.execute(org_id="org-1", environment="test")
        assert result.key.startswith("ps_test_")
        assert result.environment == "test"

    async def test_environment_live_creates_live_prefixed_key(
        self,
        use_case: ProvisionOrgUseCase,
    ) -> None:
        """environment='live' must produce a ps_live_ prefixed key."""
        result = await use_case.execute(org_id="org-1", environment="live")
        assert result.key.startswith("ps_live_")

    async def test_inactive_key_does_not_trigger_idempotent_path(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Only ACTIVE keys should block re-provision. An inactive (revoked) key must not."""
        revoked_key = _make_key_metadata(active=False)
        mock_api_key_port.list_keys.return_value = [revoked_key]
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A")
        assert result.created is True
        assert result.key != ""

    async def test_key_for_different_environment_does_not_trigger_idempotent_path(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Org has a 'live' key. Provisioning 'test' must create a new key."""
        live_key = _make_key_metadata(environment="live")
        mock_api_key_port.list_keys.return_value = [live_key]
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A", environment="test")
        assert result.created is True
        assert result.key != ""
        assert result.environment == "test"


# ---------------------------------------------------------------------------
# Idempotent Path
# ---------------------------------------------------------------------------


class TestIdempotentPath:
    """When the org already has an active key for the environment."""

    async def test_idempotent_returns_created_false(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        existing = _make_key_metadata(key_id="kid_existing001")
        mock_api_key_port.list_keys.return_value = [existing]

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A")
        assert result.created is False
        assert result.key == ""
        assert result.key_id == "kid_existing001"

    async def test_idempotent_path_does_not_call_set_org_plan(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """On the idempotent path, set_org_plan must NOT be called."""
        existing = _make_key_metadata()
        mock_api_key_port.list_keys.return_value = [existing]

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        await uc.execute(org_id="org-A", plan_id="starter")
        mock_org_plan_port.set_org_plan.assert_not_called()

    async def test_idempotent_path_returns_stored_plan_not_requested_plan(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Idempotent path reads plan from DB, does not echo the requested plan_id."""
        existing = _make_key_metadata()
        mock_api_key_port.list_keys.return_value = [existing]
        mock_org_plan_port.get_org_plan_id.return_value = "business"

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A", plan_id="starter")
        assert result.plan == "business"

    async def test_idempotent_selects_first_active_env_key(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """When multiple active keys exist for the environment, return the first one."""
        key1 = _make_key_metadata(key_id="kid_first_000001")
        key2 = _make_key_metadata(key_id="kid_second_00002")
        mock_api_key_port.list_keys.return_value = [key1, key2]

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-A")
        assert result.key_id == "kid_first_000001"


# ---------------------------------------------------------------------------
# Happy Path (last, per protocol)
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Standard functional success paths."""

    async def test_new_org_provision_creates_key_and_sets_plan(
        self,
        use_case: ProvisionOrgUseCase,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        result = await use_case.execute(org_id="org-new", plan_id="starter")

        assert result.created is True
        assert result.key.startswith("ps_live_")
        assert len(result.key) == 40
        assert result.key_id.startswith("kid_")
        assert result.org_id == "org-new"
        assert result.environment == "live"
        assert result.plan == "starter"

        mock_org_plan_port.set_org_plan.assert_called_once_with(
            org_id="org-new", plan_id="starter"
        )

    async def test_set_org_plan_called_before_key_creation(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Plan assignment must happen BEFORE key creation to enforce plan limits."""
        call_order: list[str] = []

        async def track_set_plan(**kwargs):
            call_order.append("set_org_plan")

        async def track_store_key(metadata, max_keys):
            call_order.append("store_key_if_under_limit")
            return True

        mock_org_plan_port.set_org_plan.side_effect = track_set_plan
        mock_api_key_port.store_key_if_under_limit.side_effect = track_store_key

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        await uc.execute(org_id="org-1", plan_id="starter")

        assert call_order == ["set_org_plan", "store_key_if_under_limit"]

    async def test_result_plan_reflects_resolved_plan_from_org_plan_port(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """The plan in the result must come from the CreateApiKeyUseCase metadata,
        which reads it from get_org_plan_id after set_org_plan."""
        mock_org_plan_port.get_org_plan_id.return_value = "starter"
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        result = await uc.execute(org_id="org-1", plan_id="starter")
        assert result.plan == "starter"


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    """Race condition tests."""

    async def test_concurrent_provisions_same_org_env_both_create_keys(
        self,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """
        FLAG-PROVISION-001: Two concurrent provisions for the same (org, env) pair
        will both see list_keys return [] and both create keys. This is a known
        check-then-act race condition. The test documents the behavior.

        Production fix: use store_key_if_under_limit atomic check or a distributed lock.
        """
        mock_api_key_port.list_keys.return_value = []
        mock_api_key_port.store_key_if_under_limit.return_value = True

        uc = ProvisionOrgUseCase(
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )

        import asyncio
        results = await asyncio.gather(
            uc.execute(org_id="org-race", plan_id="free"),
            uc.execute(org_id="org-race", plan_id="free"),
        )

        # Both will return created=True because list_keys returns [] for both
        assert results[0].created is True
        assert results[1].created is True
        # They produce different keys (different random bytes)
        assert results[0].key != results[1].key
