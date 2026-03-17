"""
CreateApiKeyUseCase — generate a new API key, hash it, and persist metadata.

The raw key is returned exactly once (in CreateApiKeyResult.raw_key) and is
NEVER stored anywhere in the system. Only the SHA-256 hash of the raw key
is written to Redis. If the caller loses the raw key, it cannot be recovered.

Key format:
  Live keys:  ps_live_<32 hex chars>   (e.g. ps_live_4a3f9b1c...)
  Test keys:  ps_test_<32 hex chars>   (e.g. ps_test_7d2e0a4b...)

When OrgPlanPort is provided (injected by Container), the use case resolves
the org's current plan and enforces plan.max_keys before key creation. The
plan's rate_limit_per_minute overrides the caller-supplied rate_limit param.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone

from app.domain.entities import ApiKeyMetadata, MaxKeysExceededError
from app.domain.plans import PLANS, get_plan
from app.domain.ports.api_key_port import ApiKeyPort
from app.domain.ports.org_plan_port import OrgPlanPort

_DEFAULT_PLAN_ID = "free"


@dataclass(frozen=True)
class CreateApiKeyResult:
  """
  The return value of a successful CreateApiKeyUseCase execution.

  Attributes:
    raw_key: Plaintext API key shown once to the caller. Never log this.
    metadata: Persisted metadata (contains the SHA-256 hash, never the raw key).
  """

  raw_key: str
  metadata: ApiKeyMetadata


class CreateApiKeyUseCase:
  """Generate, hash, and store a new API key for an organization."""

  def __init__(
    self,
    api_key_port: ApiKeyPort,
    org_plan_port: OrgPlanPort | None = None,
  ) -> None:
    self._port = api_key_port
    self._org_plan_port = org_plan_port

  async def execute(
    self,
    org_id: str,
    plan: str = "standard",
    rate_limit: int = 100,
    environment: str = "live",
  ) -> CreateApiKeyResult:
    """
    Create and persist a new API key.

    When OrgPlanPort is available:
      - Resolves the org's plan (default 'free' if no explicit assignment).
      - Overrides plan and rate_limit params with plan-defined values.
      - Counts active keys for the org; raises MaxKeysExceededError if at limit.

    Steps:
      1. (Optional) Resolve plan from OrgPlanPort, enforce max_keys.
      2. Generate 16 cryptographically random bytes (32 hex chars).
      3. Prepend the environment prefix to form the raw key.
      4. SHA-256 hash the raw key for Redis storage.
      5. Persist ApiKeyMetadata via the port.
      6. Return the raw key + metadata (raw key shown once, never stored).

    Args:
      org_id: Organization identifier.
      plan: Subscription plan name (overridden by org plan when OrgPlanPort present).
      rate_limit: Maximum API calls per minute (overridden by org plan when present).
      environment: "live" or "test".

    Returns:
      CreateApiKeyResult with the raw key and persisted metadata.

    Raises:
      MaxKeysExceededError: If the org has reached the plan's max_keys limit.
    """
    effective_plan = plan
    effective_rate_limit = rate_limit

    if self._org_plan_port is not None:
      plan_id = await self._org_plan_port.get_org_plan_id(org_id) or _DEFAULT_PLAN_ID
      resolved = get_plan(plan_id) or PLANS[_DEFAULT_PLAN_ID]

      effective_plan = resolved.id
      effective_rate_limit = resolved.rate_limit_per_minute
      resolved_max_keys = resolved.max_keys

    prefix = "ps_live_" if environment == "live" else "ps_test_"
    random_hex = os.urandom(16).hex()
    raw_key = f"{prefix}{random_hex}"

    key_hash = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    key_id = f"kid_{random_hex[:12]}"

    metadata = ApiKeyMetadata(
      key_id=key_id,
      org_id=org_id,
      key_hash=key_hash,
      plan=effective_plan,
      rate_limit_per_minute=effective_rate_limit,
      active=True,
      created_at=datetime.now(timezone.utc).isoformat(),
      environment=environment,
    )

    if self._org_plan_port is not None:
      stored = await self._port.store_key_if_under_limit(metadata, resolved_max_keys)
      if not stored:
        active_count = await self._port.count_active_keys(org_id)
        raise MaxKeysExceededError(org_id, active_count, resolved_max_keys, effective_plan)
    else:
      await self._port.store_key(metadata)

    return CreateApiKeyResult(raw_key=raw_key, metadata=metadata)
