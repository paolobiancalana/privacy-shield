# app/application/provision_org.py
"""
ProvisionOrgUseCase — atomically assign a plan and create an API key for an
organization in a single operation.

Idempotency contract:
  If the org already has at least one *active* key for the requested
  environment, the use case returns the existing key_id and plan without
  creating a new key or overwriting the plan.  The raw key is NOT returned
  in that case (created=False, key="") because it was never stored.

  Callers that need the raw key after losing it must revoke the old key and
  call provision again (created=True on the next call).

Key creation follows the same rules as CreateApiKeyUseCase:
  - Plan max_keys is enforced (MaxKeysExceededError propagated to caller).
  - The org's plan is read back from OrgPlanPort after set_org_plan() so
    the returned ProvisionResult.plan always reflects the stored value.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.domain.ports.api_key_port import ApiKeyPort
from app.domain.ports.org_plan_port import OrgPlanPort
from app.application.create_api_key import CreateApiKeyUseCase


@dataclass(frozen=True)
class ProvisionResult:
  """
  The return value of a successful ProvisionOrgUseCase execution.

  Attributes:
    plan: The plan_id assigned to the org.
    key: Raw API key shown exactly once on first provision.
         Empty string ("") on subsequent calls (created=False).
    key_id: Stable identifier for the key (safe to store, use for revocation).
    created: True if a new key was created; False if the org was already
             provisioned for this environment.
    org_id: Organization identifier.
    environment: "live" or "test".
  """

  plan: str
  key: str
  key_id: str
  created: bool
  org_id: str
  environment: str


class ProvisionOrgUseCase:
  """
  Atomic org provisioning: assign plan + create API key in one operation.

  Idempotent: calling this twice for the same (org_id, environment) pair
  returns the existing key_id with created=False and an empty raw key.
  """

  def __init__(
    self,
    api_key_port: ApiKeyPort,
    org_plan_port: OrgPlanPort,
  ) -> None:
    self._api_key_port = api_key_port
    self._org_plan_port = org_plan_port
    self._create_key_use_case = CreateApiKeyUseCase(
      api_key_port=api_key_port,
      org_plan_port=org_plan_port,
    )

  async def execute(
    self,
    org_id: str,
    plan_id: str = "free",
    environment: str = "live",
  ) -> ProvisionResult:
    """
    Provision an organization: assign plan + create API key.

    Steps:
      1. List existing keys for the org; if an active key already exists for
         this environment, return it immediately (idempotent, created=False).
      2. Set the org plan via OrgPlanPort.set_org_plan().
      3. Create a new API key via CreateApiKeyUseCase (inherits plan-based
         max_keys enforcement and rate_limit resolution).
      4. Return ProvisionResult with the raw key (created=True).

    Args:
      org_id: Organization identifier (UUID string).
      plan_id: Target plan ID. Defaults to "free".
      environment: Key environment: "live" or "test". Defaults to "live".

    Returns:
      ProvisionResult — see dataclass docstring for field semantics.

    Raises:
      MaxKeysExceededError: If key creation would exceed the plan's max_keys.
        (Only raised on first provision; idempotent path never reaches key
        creation.)
    """
    existing_keys = await self._api_key_port.list_keys(org_id)
    active_env_keys = [
      k for k in existing_keys if k.active and k.environment == environment
    ]

    if active_env_keys:
      first_key = active_env_keys[0]
      resolved_plan_id = await self._org_plan_port.get_org_plan_id(org_id)
      return ProvisionResult(
        plan=resolved_plan_id or "free",
        key="",
        key_id=first_key.key_id,
        created=False,
        org_id=org_id,
        environment=environment,
      )

    await self._org_plan_port.set_org_plan(org_id=org_id, plan_id=plan_id)

    result = await self._create_key_use_case.execute(
      org_id=org_id,
      environment=environment,
    )

    return ProvisionResult(
      plan=result.metadata.plan,
      key=result.raw_key,
      key_id=result.metadata.key_id,
      created=True,
      org_id=org_id,
      environment=environment,
    )
