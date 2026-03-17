# app/infrastructure/adapters/redis_org_plan.py
"""
RedisOrgPlanAdapter — Redis-backed implementation of OrgPlanPort.

Key schema:
  ps:org_plan:{org_id}  → JSON {"plan_id": "starter",
                                 "stripe_customer_id": null,
                                 "assigned_at": "2026-03-17T...Z"}
                          No TTL — org plan assignments are permanent
                          until explicitly changed.

All key prefixes are namespaced under "ps:" to avoid collisions with the vault.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import redis.asyncio as aioredis

from app.domain.ports.org_plan_port import OrgPlanPort


class RedisOrgPlanAdapter(OrgPlanPort):
    """
    Redis implementation of org→plan storage.

    The Redis client is injected at construction time; this adapter does not
    own the connection pool lifecycle (Container does).
    """

    _ORG_PLAN_PREFIX = "ps:org_plan"

    def __init__(self, redis_client: aioredis.Redis) -> None:
        self._redis = redis_client

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _org_plan_key(self, org_id: str) -> str:
        return f"{self._ORG_PLAN_PREFIX}:{org_id}"

    def _decode_bytes(self, value: bytes | str) -> str:
        return value if isinstance(value, str) else value.decode("utf-8")

    # ------------------------------------------------------------------
    # OrgPlanPort implementation
    # ------------------------------------------------------------------

    async def get_org_plan_id(self, org_id: str) -> str | None:
        """Return the plan_id for the org, or None (caller defaults to 'free')."""
        raw = await self._redis.get(self._org_plan_key(org_id))
        if raw is None:
            return None
        data = json.loads(self._decode_bytes(raw))
        return data.get("plan_id")

    async def set_org_plan(
        self,
        org_id: str,
        plan_id: str,
        stripe_customer_id: str | None = None,
    ) -> None:
        """Persist org→plan mapping. Overwrites any existing assignment."""
        payload = {
            "plan_id": plan_id,
            "stripe_customer_id": stripe_customer_id,
            "assigned_at": datetime.now(timezone.utc).isoformat(),
        }
        encoded = json.dumps(payload).encode("utf-8")
        await self._redis.set(self._org_plan_key(org_id), encoded)

    async def get_org_plan_info(self, org_id: str) -> dict | None:
        """Return the full stored plan info dict, or None if not set."""
        raw = await self._redis.get(self._org_plan_key(org_id))
        if raw is None:
            return None
        return json.loads(self._decode_bytes(raw))
