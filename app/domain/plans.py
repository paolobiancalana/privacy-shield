# app/domain/plans.py
"""
Plan catalog for the Privacy Shield plan/tier system.

Plans are immutable value objects defined at module load time. They carry
the enforcement parameters that drive rate limiting (per-minute), monthly
token quota, max concurrent API keys, and price (for billing stubs).

The sentinel value -1 for monthly_token_limit means unlimited (enterprise).
Callers must check `plan.monthly_token_limit != -1` before enforcing.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Plan:
    """
    Immutable plan definition.

    Attributes:
        id: Unique plan identifier (lowercase slug).
        name: Human-readable display name.
        rate_limit_per_minute: Max API calls per minute for any key on this plan.
        monthly_token_limit: Max tokens created per org per month. -1 = unlimited.
        max_keys: Maximum active API keys allowed per org.
        price_cents: Monthly price in EUR cents (0 = free or custom billing).
    """

    id: str
    name: str
    rate_limit_per_minute: int
    monthly_token_limit: int
    max_keys: int
    price_cents: int


PLANS: dict[str, Plan] = {
    "free": Plan(
        id="free",
        name="Free",
        rate_limit_per_minute=10,
        monthly_token_limit=1_000,
        max_keys=2,
        price_cents=0,
    ),
    "starter": Plan(
        id="starter",
        name="Starter",
        rate_limit_per_minute=60,
        monthly_token_limit=50_000,
        max_keys=5,
        price_cents=1_900,
    ),
    "business": Plan(
        id="business",
        name="Business",
        rate_limit_per_minute=200,
        monthly_token_limit=500_000,
        max_keys=20,
        price_cents=7_900,
    ),
    "enterprise": Plan(
        id="enterprise",
        name="Enterprise",
        rate_limit_per_minute=1_000,
        monthly_token_limit=-1,
        max_keys=100,
        price_cents=0,
    ),
}


def get_plan(plan_id: str) -> Plan | None:
    """Return the Plan for plan_id, or None if not found."""
    return PLANS.get(plan_id)


def list_plans() -> list[Plan]:
    """Return all plans in insertion order."""
    return list(PLANS.values())
