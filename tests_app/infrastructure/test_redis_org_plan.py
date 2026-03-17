"""
RedisOrgPlanAdapter adversarial tests.

Adversarial Analysis:
  1. Two orgs must never see each other's plan assignments (key collision via
     org_id prefix is the main risk vector).
  2. Overwriting an existing plan must fully replace the old value — no
     partial merge that could preserve a stale stripe_customer_id.
  3. Malformed JSON in Redis must not crash get_org_plan_id — it should propagate
     the exception (fail-closed, not fail-open returning None).

Boundary Map:
  org_id: valid UUID, empty string, string with colons (Redis key separator)
  plan_id: valid slug, empty string
  stripe_customer_id: None (omitted), valid string, empty string
  assigned_at: must be ISO 8601 UTC
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from app.infrastructure.adapters.redis_org_plan import RedisOrgPlanAdapter

ORG_A = "00000000-0000-0000-0000-00000000000a"
ORG_B = "00000000-0000-0000-0000-00000000000b"


@pytest.fixture
async def redis() -> fakeredis.aioredis.FakeRedis:
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


@pytest.fixture
def adapter(redis: fakeredis.aioredis.FakeRedis) -> RedisOrgPlanAdapter:
    return RedisOrgPlanAdapter(redis_client=redis)


class TestTenantIsolation:
    """Two orgs must never see each other's plan data."""

    async def test_org_a_plan_not_visible_to_org_b(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "enterprise")
        result_b = await adapter.get_org_plan_id(ORG_B)
        assert result_b is None

    async def test_org_b_plan_not_visible_to_org_a(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_B, "starter")
        result_a = await adapter.get_org_plan_id(ORG_A)
        assert result_a is None

    async def test_both_orgs_have_independent_plans(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "business")
        await adapter.set_org_plan(ORG_B, "free")
        assert await adapter.get_org_plan_id(ORG_A) == "business"
        assert await adapter.get_org_plan_id(ORG_B) == "free"


class TestStoreAndRetrieve:
    """Basic store/retrieve contract."""

    async def test_get_returns_none_for_unknown_org(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        result = await adapter.get_org_plan_id("nonexistent-org")
        assert result is None

    async def test_set_then_get_returns_correct_plan_id(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "starter")
        assert await adapter.get_org_plan_id(ORG_A) == "starter"

    async def test_overwrite_replaces_plan_completely(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "free", stripe_customer_id="cus_old")
        await adapter.set_org_plan(ORG_A, "enterprise")
        info = await adapter.get_org_plan_info(ORG_A)
        assert info is not None
        assert info["plan_id"] == "enterprise"
        # stripe_customer_id must be None (overwritten), not "cus_old"
        assert info["stripe_customer_id"] is None

    async def test_overwrite_updates_assigned_at(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "free")
        info1 = await adapter.get_org_plan_info(ORG_A)
        assert info1 is not None
        ts1 = info1["assigned_at"]

        await adapter.set_org_plan(ORG_A, "starter")
        info2 = await adapter.get_org_plan_info(ORG_A)
        assert info2 is not None
        ts2 = info2["assigned_at"]
        # Timestamps should be different (or at least not older)
        assert ts2 >= ts1


class TestGetOrgPlanInfo:
    """get_org_plan_info() returns the full dict."""

    async def test_returns_none_for_unknown_org(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        result = await adapter.get_org_plan_info("unknown-org")
        assert result is None

    async def test_returns_dict_with_all_expected_keys(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "business", stripe_customer_id="cus_123")
        info = await adapter.get_org_plan_info(ORG_A)
        assert info is not None
        assert set(info.keys()) == {"plan_id", "stripe_customer_id", "assigned_at"}
        assert info["plan_id"] == "business"
        assert info["stripe_customer_id"] == "cus_123"
        # assigned_at must parse as ISO datetime
        datetime.fromisoformat(info["assigned_at"])

    async def test_stripe_customer_id_none_when_not_provided(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "free")
        info = await adapter.get_org_plan_info(ORG_A)
        assert info is not None
        assert info["stripe_customer_id"] is None

    async def test_stripe_customer_id_preserved_when_provided(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan(ORG_A, "starter", stripe_customer_id="cus_abc")
        info = await adapter.get_org_plan_info(ORG_A)
        assert info is not None
        assert info["stripe_customer_id"] == "cus_abc"


class TestBoundaryInputs:
    """Edge-case inputs that should not crash the adapter."""

    async def test_org_id_with_colon_does_not_collide(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        """Colons are the Redis key separator — ensure no key collision."""
        await adapter.set_org_plan("org:a", "free")
        await adapter.set_org_plan("org:b", "starter")
        assert await adapter.get_org_plan_id("org:a") == "free"
        assert await adapter.get_org_plan_id("org:b") == "starter"

    async def test_empty_string_org_id(
        self, adapter: RedisOrgPlanAdapter
    ) -> None:
        await adapter.set_org_plan("", "free")
        assert await adapter.get_org_plan_id("") == "free"
        # Other orgs must not see this
        assert await adapter.get_org_plan_id(ORG_A) is None
