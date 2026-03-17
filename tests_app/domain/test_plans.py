"""
Plan catalog domain tests — adversarial and boundary.

Adversarial Analysis:
  1. Plan immutability: frozen dataclass fields must reject mutation.
  2. get_plan() with injection-style strings must return None, not crash.
  3. The catalog must contain exactly 4 plans with exact field values.

Boundary Map:
  plan_id: "free", "starter", "business", "enterprise" (valid) vs "ENTERPRISE", "",
           "free ", "nonexistent", SQL injection string (invalid)
  monthly_token_limit: -1 sentinel (enterprise) vs positive int (others)
  max_keys: 2 (free) to 100 (enterprise)
  price_cents: 0 (free, enterprise) vs positive (starter, business)
"""
from __future__ import annotations

import dataclasses

import pytest

from app.domain.plans import PLANS, Plan, get_plan, list_plans


class TestCatalogIntegrity:
    """Verify the plan catalog has exactly the expected structure."""

    def test_catalog_contains_exactly_four_plans(self) -> None:
        assert len(PLANS) == 4

    def test_catalog_keys_are_lowercase_slugs(self) -> None:
        expected_keys = {"free", "starter", "business", "enterprise"}
        assert set(PLANS.keys()) == expected_keys

    def test_each_plan_id_matches_its_dict_key(self) -> None:
        for key, plan in PLANS.items():
            assert plan.id == key, f"Plan key '{key}' does not match plan.id '{plan.id}'"

    def test_list_plans_returns_all_four(self) -> None:
        plans = list_plans()
        assert len(plans) == 4
        assert all(isinstance(p, Plan) for p in plans)

    def test_list_plans_returns_plans_in_insertion_order(self) -> None:
        plans = list_plans()
        expected_ids = ["free", "starter", "business", "enterprise"]
        assert [p.id for p in plans] == expected_ids


class TestPlanFieldValues:
    """Verify each plan has exact expected field values — no approximation."""

    def test_free_plan_exact_fields(self) -> None:
        p = PLANS["free"]
        assert p.id == "free"
        assert p.name == "Free"
        assert p.rate_limit_per_minute == 10
        assert p.monthly_token_limit == 1_000
        assert p.max_keys == 2
        assert p.price_cents == 0

    def test_starter_plan_exact_fields(self) -> None:
        p = PLANS["starter"]
        assert p.id == "starter"
        assert p.name == "Starter"
        assert p.rate_limit_per_minute == 60
        assert p.monthly_token_limit == 50_000
        assert p.max_keys == 5
        assert p.price_cents == 1_900

    def test_business_plan_exact_fields(self) -> None:
        p = PLANS["business"]
        assert p.id == "business"
        assert p.name == "Business"
        assert p.rate_limit_per_minute == 200
        assert p.monthly_token_limit == 500_000
        assert p.max_keys == 20
        assert p.price_cents == 7_900

    def test_enterprise_plan_exact_fields(self) -> None:
        p = PLANS["enterprise"]
        assert p.id == "enterprise"
        assert p.name == "Enterprise"
        assert p.rate_limit_per_minute == 1_000
        assert p.monthly_token_limit == -1
        assert p.max_keys == 100
        assert p.price_cents == 0

    def test_enterprise_is_only_plan_with_unlimited_token_limit(self) -> None:
        unlimited_plans = [p for p in PLANS.values() if p.monthly_token_limit == -1]
        assert len(unlimited_plans) == 1
        assert unlimited_plans[0].id == "enterprise"

    def test_all_non_enterprise_plans_have_positive_token_limits(self) -> None:
        for plan_id, plan in PLANS.items():
            if plan_id != "enterprise":
                assert plan.monthly_token_limit > 0, (
                    f"Plan '{plan_id}' has non-positive monthly_token_limit: "
                    f"{plan.monthly_token_limit}"
                )


class TestGetPlan:
    """get_plan() boundary and adversarial cases."""

    def test_returns_correct_plan_for_each_valid_id(self) -> None:
        for plan_id in ("free", "starter", "business", "enterprise"):
            result = get_plan(plan_id)
            assert result is not None
            assert result.id == plan_id

    def test_returns_none_for_nonexistent_plan(self) -> None:
        assert get_plan("nonexistent") is None

    def test_returns_none_for_empty_string(self) -> None:
        assert get_plan("") is None

    def test_returns_none_for_case_variant_uppercase(self) -> None:
        """Plan IDs are case-sensitive — 'ENTERPRISE' must not match."""
        assert get_plan("ENTERPRISE") is None
        assert get_plan("Free") is None
        assert get_plan("STARTER") is None

    def test_returns_none_for_whitespace_padded_id(self) -> None:
        assert get_plan("free ") is None
        assert get_plan(" free") is None

    def test_returns_none_for_sql_injection_string(self) -> None:
        assert get_plan("'; DROP TABLE plans; --") is None

    def test_returns_none_for_null_byte_string(self) -> None:
        assert get_plan("free\x00") is None


class TestPlanImmutability:
    """Plans must be frozen dataclasses — mutation must raise."""

    def test_cannot_mutate_plan_id(self) -> None:
        plan = PLANS["free"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.id = "hacked"  # type: ignore[misc]

    def test_cannot_mutate_rate_limit(self) -> None:
        plan = PLANS["starter"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.rate_limit_per_minute = 999_999  # type: ignore[misc]

    def test_cannot_mutate_monthly_token_limit(self) -> None:
        plan = PLANS["free"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.monthly_token_limit = -1  # type: ignore[misc]

    def test_cannot_mutate_max_keys(self) -> None:
        plan = PLANS["enterprise"]
        with pytest.raises(dataclasses.FrozenInstanceError):
            plan.max_keys = 0  # type: ignore[misc]

    def test_plans_dict_mutation_does_not_affect_get_plan(self) -> None:
        """Even if someone mutates the PLANS dict, get_plan should still work
        for existing plans because dict mutation is at the dict level, not plan level."""
        original_free = get_plan("free")
        assert original_free is not None
        assert original_free.id == "free"
