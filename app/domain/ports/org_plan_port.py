# app/domain/ports/org_plan_port.py
"""
OrgPlanPort — abstract contract for org→plan mapping persistence.

Implementor: RedisOrgPlanAdapter.
Domain layer only — zero infrastructure imports.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class OrgPlanPort(ABC):
    """Persist and retrieve per-organization plan assignments."""

    @abstractmethod
    async def get_org_plan_id(self, org_id: str) -> str | None:
        """
        Return the plan_id assigned to the org, or None (defaults to 'free').

        Args:
            org_id: Organization identifier.

        Returns:
            plan_id string (e.g. 'starter') or None if no explicit assignment.
        """
        ...

    @abstractmethod
    async def set_org_plan(
        self,
        org_id: str,
        plan_id: str,
        stripe_customer_id: str | None = None,
    ) -> None:
        """
        Persist an org→plan mapping with an optional Stripe customer reference.

        No TTL is applied — the mapping is permanent until explicitly updated.

        Args:
            org_id: Organization identifier.
            plan_id: Target plan_id (must exist in PLANS catalog).
            stripe_customer_id: Optional Stripe customer ID for billing linkage.
        """
        ...

    @abstractmethod
    async def get_org_plan_info(self, org_id: str) -> dict | None:
        """
        Return the full stored plan info dict for the org, or None if not set.

        The returned dict contains: plan_id, stripe_customer_id, assigned_at.

        Args:
            org_id: Organization identifier.

        Returns:
            Dict with plan metadata or None if no explicit assignment exists.
        """
        ...
