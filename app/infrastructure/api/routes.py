"""
FastAPI route definitions for the Privacy Shield API.

Routes are thin: they validate input via Pydantic, delegate to use cases,
and map results to response models. No business logic lives here.

Endpoints:
  POST /api/v1/tokenize            — tokenize one or more texts (requires X-Api-Key)
  POST /api/v1/rehydrate           — rehydrate a single tokenized text (requires X-Api-Key)
  POST /api/v1/flush               — flush all vault entries for a request (requires X-Api-Key)
  POST /api/v1/rotate-dek          — rotate the per-org DEK (requires X-Admin-Key)
  POST /api/v1/keys                — create a new API key (requires X-Admin-Key)
  DELETE /api/v1/keys/{key_hash}   — revoke a key (requires X-Admin-Key)
  GET  /api/v1/keys                — list keys, optionally filtered by org_id (requires X-Admin-Key)
  GET  /api/v1/usage/{org_id}      — get monthly usage stats (requires X-Admin-Key)
  GET  /health                     — structured liveness check (Redis + crypto + SLM)
  GET  /metrics                    — in-memory metrics snapshot (JSON)
"""
from __future__ import annotations

import asyncio
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.application.flush_request import FlushRequestUseCase
from app.application.rehydrate_text import RehydrateTextUseCase
from app.application.rotate_dek import RotateDekUseCase
from app.application.tokenize_text import TokenizeTextUseCase
from app.domain.entities import (
  MaxKeysExceededError,
  MonthlyQuotaExceededError,
  PlanNotFoundError,
  QuotaExceededError,
)
from app.domain.plans import get_plan, list_plans
from app.infrastructure.api.auth import require_admin_key, require_api_key
from app.infrastructure.api.schemas import (
  ChangePlanRequest,
  ComponentStatus,
  CreateKeyRequest,
  CreateKeyResponse,
  FlushRequest,
  FlushResponse,
  HealthComponents,
  HealthResponse,
  OrgPlanResponse,
  PlanResponse,
  RehydrateRequest,
  RehydrateResponse,
  RotateDekRequest,
  RotateDekResponse,
  TokenInfo,
  TokenizeRequest,
  TokenizeResponse,
)
from app.infrastructure.telemetry import get_logger, log_error, log_operation

_logger = get_logger("routes")

_UUID_REGEX = re.compile(
  r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
  re.IGNORECASE,
)


def _validate_path_uuid(value: str, param_name: str) -> str:
  """Raise HTTP 422 if *value* is not a well-formed UUID string."""
  if not _UUID_REGEX.match(value):
    raise HTTPException(status_code=422, detail=f"{param_name} must be a valid UUID")
  return value


router = APIRouter()


def _get_container(request: Request):
  """FastAPI dependency: retrieve the DI container from app state."""
  return request.app.state.container


@router.post(
  "/api/v1/tokenize",
  response_model=TokenizeResponse,
  summary="Tokenize PII in one or more texts",
)
async def tokenize(
  body: TokenizeRequest,
  container=Depends(_get_container),
  auth: dict = Depends(require_api_key),
) -> TokenizeResponse:
  """
  Replace Italian PII with opaque Privacy Shield tokens.

  Processes each text in 'texts' sequentially, accumulating tokens
  across all texts so the same PII always maps to the same token
  within one request.

  Requires a valid X-Api-Key header. The resolved org_id from the key
  is used for usage recording; the body's organization_id is used for
  vault scoping (must match the key's org for correct token isolation).
  """
  use_case: TokenizeTextUseCase = container.tokenize_use_case
  t0 = time.perf_counter()

  org_id = auth["org_id"]
  if body.organization_id != org_id:
    _logger.warning(
      "org_id mismatch: body=%s vs key=%s — using key org_id",
      body.organization_id,
      org_id,
    )

  all_tokenized: list[str] = []
  all_token_infos: list[TokenInfo] = []
  total_detection_ms = 0.0
  existing = dict(body.existing_tokens)

  metrics = container.metrics

  for text in body.texts:
    try:
      result = await asyncio.wait_for(
        use_case.execute(
          text=text,
          org_id=org_id,
          request_id=body.request_id,
          existing_tokens=existing,
        ),
        timeout=5.0,
      )
    except asyncio.TimeoutError:
      raise HTTPException(status_code=408, detail="Text processing timeout")
    except MonthlyQuotaExceededError as exc:
      metrics.record_monthly_quota_exceeded(exc.plan_id)
      _logger.warning(
        "Monthly token quota exceeded",
        extra={"_ps_operation": "tokenize", "org_id": org_id},
      )
      raise HTTPException(
        status_code=429,
        detail="Monthly token quota exceeded for your plan",
        headers={
          "Retry-After": "86400",
        },
      ) from exc
    except QuotaExceededError as exc:
      _logger.warning(
        "Org token quota exceeded",
        extra={"_ps_operation": "tokenize", "org_id": org_id},
      )
      raise HTTPException(
        status_code=503,
        detail="Organization token quota exceeded",
      ) from exc
    except Exception as exc:
      log_error(
        _logger,
        operation="tokenize",
        org_id=org_id,
        error_code="TOKENIZE_FAILED",
        message="tokenize use case raised an exception",
        exc=exc,
      )
      metrics.record_failure("redis_error")
      raise HTTPException(status_code=500, detail="Tokenization failed") from exc

    all_tokenized.append(result.tokenized_text)
    total_detection_ms += result.detection_ms

    for entry in result.tokens:
      existing[entry.original] = entry.token

    for entry in result.tokens:
      all_token_infos.append(
        TokenInfo(
          original=entry.original,
          token=entry.token,
          type=entry.pii_type,
          start=entry.start,
          end=entry.end,
          source=entry.source,
        )
      )

    source = result.tokens[0].source if result.tokens else "regex"
    token_types = [e.pii_type for e in result.tokens]
    metrics.record_tokenization(source=source, token_types=token_types)

  total_ms = (time.perf_counter() - t0) * 1000.0
  metrics.record_latency("tokenize", total_ms)
  log_operation(
    _logger,
    operation="tokenize",
    org_id=org_id,
    duration_ms=total_ms,
    token_count=len(all_token_infos),
    text_count=len(body.texts),
    detection_ms=total_detection_ms,
  )

  await container.api_key_port.record_usage(auth["org_id"], "tokenize")

  return TokenizeResponse(
    tokenized_texts=all_tokenized,
    tokens=all_token_infos,
    detection_ms=total_detection_ms,
    tokenization_ms=total_ms,
  )


@router.post(
  "/api/v1/rehydrate",
  response_model=RehydrateResponse,
  summary="Rehydrate tokens back to original PII",
)
async def rehydrate(
  body: RehydrateRequest,
  container=Depends(_get_container),
  auth: dict = Depends(require_api_key),
) -> RehydrateResponse:
  """
  Replace Privacy Shield tokens with their original plaintext values.

  Tokens that cannot be resolved (expired vault entries) are left as-is.
  Requires a valid X-Api-Key header.
  """
  use_case: RehydrateTextUseCase = container.rehydrate_use_case
  metrics = container.metrics
  org_id = auth["org_id"]
  if body.organization_id != org_id:
    _logger.warning(
      "org_id mismatch: body=%s vs key=%s — using key org_id",
      body.organization_id,
      org_id,
    )
  try:
    result = await use_case.execute(
      text=body.text,
      org_id=org_id,
      request_id=body.request_id,
    )
  except Exception as exc:
    log_error(
      _logger,
      operation="rehydrate",
      org_id=org_id,
      error_code="REHYDRATE_FAILED",
      message="rehydrate use case raised an exception",
      exc=exc,
    )
    metrics.record_failure("redis_error")
    raise HTTPException(status_code=500, detail="Rehydration failed") from exc

  metrics.record_latency("rehydrate", result.duration_ms)
  log_operation(
    _logger,
    operation="rehydrate",
    org_id=org_id,
    duration_ms=result.duration_ms,
    rehydrated_count=result.rehydrated_count,
  )

  await container.api_key_port.record_usage(auth["org_id"], "rehydrate")

  return RehydrateResponse(
    text=result.text,
    rehydrated_count=result.rehydrated_count,
  )


@router.post(
  "/api/v1/flush",
  response_model=FlushResponse,
  summary="Flush vault entries for a completed request",
)
async def flush(
  body: FlushRequest,
  container=Depends(_get_container),
  auth: dict = Depends(require_api_key),
) -> FlushResponse:
  """
  Delete all vault tokens registered under (organization_id, request_id).

  Idempotent — calling it multiple times returns 0 after the first call.
  Requires a valid X-Api-Key header.
  """
  use_case: FlushRequestUseCase = container.flush_use_case
  metrics = container.metrics
  org_id = auth["org_id"]
  if body.organization_id != org_id:
    _logger.warning(
      "org_id mismatch: body=%s vs key=%s — using key org_id",
      body.organization_id,
      org_id,
    )
  t0_flush = time.perf_counter()
  try:
    result = await use_case.execute(
      org_id=org_id,
      request_id=body.request_id,
    )
  except Exception as exc:
    log_error(
      _logger,
      operation="flush",
      org_id=org_id,
      error_code="FLUSH_FAILED",
      message="flush use case raised an exception",
      exc=exc,
    )
    metrics.record_failure("redis_error")
    metrics.record_flush("fallback_ttl")
    raise HTTPException(status_code=500, detail="Flush failed") from exc

  flush_ms = (time.perf_counter() - t0_flush) * 1000.0
  metrics.record_latency("flush", flush_ms)
  metrics.record_flush("success")
  log_operation(
    _logger,
    operation="flush",
    org_id=org_id,
    duration_ms=flush_ms,
    flushed_count=result.flushed_count,
  )

  await container.api_key_port.record_usage(auth["org_id"], "flush")

  return FlushResponse(flushed_count=result.flushed_count)


@router.post(
  "/api/v1/rotate-dek",
  response_model=RotateDekResponse,
  summary="Rotate the per-org DEK and re-encrypt all active vault entries",
  dependencies=[Depends(require_admin_key)],
)
async def rotate_dek(
  body: RotateDekRequest,
  container=Depends(_get_container),
) -> RotateDekResponse:
  """
  Rotate the Data Encryption Key for an organisation.

  Generates a new DEK, re-encrypts all active vault entries under it,
  and stores the new encrypted DEK in Redis. The operation is safe to
  retry — partial rotations re-encrypt the remaining entries on the
  next call.

  Returns the number of vault entries that were re-encrypted.

  Requires the X-Admin-Key header to match ADMIN_API_KEY in config.
  """
  use_case: RotateDekUseCase = container.rotate_dek_use_case
  metrics = container.metrics
  t0 = time.perf_counter()

  try:
    result = await use_case.execute(org_id=body.organization_id)
  except ValueError as exc:
    log_error(
      _logger,
      operation="rotate_dek",
      org_id=body.organization_id,
      error_code="DEK_NOT_FOUND",
      message="rotation requested for org with no existing DEK",
      exc=exc,
    )
    raise HTTPException(
      status_code=404,
      detail="DEK not found for the specified organization",
    ) from exc
  except Exception as exc:
    log_error(
      _logger,
      operation="rotate_dek",
      org_id=body.organization_id,
      error_code="ROTATION_FAILED",
      message="DEK rotation raised an exception",
      exc=exc,
    )
    metrics.record_failure("redis_error")
    raise HTTPException(status_code=500, detail="DEK rotation failed") from exc

  rotation_ms = (time.perf_counter() - t0) * 1000.0
  metrics.record_dek_rotation()
  log_operation(
    _logger,
    operation="rotate_dek",
    org_id=body.organization_id,
    duration_ms=rotation_ms,
    re_encrypted_count=result.re_encrypted_count,
  )
  return RotateDekResponse(
    rotated=result.rotated,
    re_encrypted_count=result.re_encrypted_count,
  )


@router.post(
  "/api/v1/keys",
  response_model=CreateKeyResponse,
  summary="Create a new API key for an organization",
  dependencies=[Depends(require_admin_key)],
)
async def create_key(
  body: CreateKeyRequest,
  container=Depends(_get_container),
) -> CreateKeyResponse:
  """
  Generate a new API key for the specified organization.

  The raw key is returned once in the response and is not stored anywhere.
  If the key is lost, it must be revoked and a new one created.

  When the org has reached the maximum keys allowed by their plan, returns 409.

  Requires X-Admin-Key header.
  """
  try:
    result = await container.create_api_key_use_case.execute(
      org_id=body.organization_id,
      environment=body.environment,
    )
  except MaxKeysExceededError as exc:
    container.metrics.record_max_keys_exceeded(exc.plan_id)
    _logger.warning(
      "Max keys exceeded for org",
      extra={"_ps_operation": "create_key", "org_id": body.organization_id},
    )
    raise HTTPException(
      status_code=409,
      detail=(
        f"Organization has reached the maximum number of API keys "
        f"({exc.max_keys}) for plan '{exc.plan_id}'. "
        "Revoke an existing key or upgrade your plan."
      ),
    ) from exc
  log_operation(
    _logger,
    operation="create_key",
    org_id=body.organization_id,
    duration_ms=0,
    key_id=result.metadata.key_id,
    environment=result.metadata.environment,
  )
  return CreateKeyResponse(
    key=result.raw_key,
    key_id=result.metadata.key_id,
    organization_id=result.metadata.org_id,
  )


@router.delete(
  "/api/v1/keys/{key_hash}",
  summary="Revoke an API key by its SHA-256 hash",
  dependencies=[Depends(require_admin_key)],
)
async def revoke_key(
  key_hash: str,
  container=Depends(_get_container),
) -> dict:
  """
  Deactivate an API key. The key is not deleted — its metadata remains in Redis
  for audit purposes — but it will no longer be accepted by require_api_key.

  Requires X-Admin-Key header.
  """
  revoked = await container.revoke_api_key_use_case.execute(key_hash=key_hash)
  if not revoked:
    raise HTTPException(status_code=404, detail="Key not found")
  log_operation(_logger, operation="revoke_key", org_id="", duration_ms=0, key_hash=key_hash)
  return {"revoked": True}


@router.get(
  "/api/v1/keys",
  summary="List API keys, optionally filtered by organization",
  dependencies=[Depends(require_admin_key)],
)
async def list_keys(
  org_id: str | None = None,
  container=Depends(_get_container),
) -> list[dict]:
  """
  Return metadata for all stored keys. Includes revoked keys.
  Optionally filter by org_id query parameter.

  Requires X-Admin-Key header.
  """
  if org_id is not None:
    _validate_path_uuid(org_id, "org_id")
  keys = await container.api_key_port.list_keys(org_id=org_id)
  return [
    {
      "key_id": k.key_id,
      "org_id": k.org_id,
      "plan": k.plan,
      "rate_limit_per_minute": k.rate_limit_per_minute,
      "active": k.active,
      "environment": k.environment,
      "created_at": k.created_at,
    }
    for k in keys
  ]


@router.get(
  "/api/v1/usage/{org_id}",
  summary="Get monthly usage stats for an organization",
  dependencies=[Depends(require_admin_key)],
)
async def get_usage(
  org_id: str,
  month: str | None = None,
  container=Depends(_get_container),
) -> dict:
  """
  Return aggregated per-org usage counters for a given month, enriched with
  plan information (limit, remaining tokens, percent used).

  month query parameter format: YYYY-MM (e.g. '2026-03').
  Defaults to the current calendar month (UTC).

  Requires X-Admin-Key header.
  """
  _validate_path_uuid(org_id, "org_id")
  resolved_month = month or datetime.now(timezone.utc).strftime("%Y-%m")
  usage = await container.api_key_port.get_usage(org_id, resolved_month)

  resolved_plan_id = await container.org_plan_port.get_org_plan_id(org_id)
  plan_id = resolved_plan_id or "free"

  plan = get_plan(plan_id) or get_plan("free")

  monthly_limit = plan.monthly_token_limit if plan else -1
  used = usage.total_tokens_created

  if monthly_limit == -1:
    remaining = None
    percent_used = 0.0
  else:
    remaining = max(0, monthly_limit - used)
    percent_used = round((used / monthly_limit) * 100, 2) if monthly_limit > 0 else 0.0

  return {
    "org_id": usage.org_id,
    "month": usage.month,
    "tokenize_calls": usage.tokenize_calls,
    "rehydrate_calls": usage.rehydrate_calls,
    "flush_calls": usage.flush_calls,
    "total_tokens_created": used,
    "plan_id": plan_id,
    "plan_name": plan.name if plan else "Free",
    "monthly_token_limit": monthly_limit,
    "remaining_tokens": remaining,
    "percent_used": percent_used,
  }


# ── Plan catalog endpoints (public, no auth) ─────────────────────────────────


@router.get(
  "/api/v1/plans",
  response_model=list[PlanResponse],
  summary="List all available plans",
)
async def list_available_plans() -> list[PlanResponse]:
  """Return all plans in the catalog. No authentication required."""
  return [
    PlanResponse(
      id=p.id,
      name=p.name,
      rate_limit_per_minute=p.rate_limit_per_minute,
      monthly_token_limit=p.monthly_token_limit,
      max_keys=p.max_keys,
      price_cents=p.price_cents,
    )
    for p in list_plans()
  ]


@router.get(
  "/api/v1/plans/{plan_id}",
  response_model=PlanResponse,
  summary="Get a single plan by ID",
)
async def get_single_plan(plan_id: str) -> PlanResponse:
  """
  Return the plan with the given plan_id.

  Returns 404 if the plan does not exist.
  No authentication required.
  """
  plan = get_plan(plan_id)
  if plan is None:
    raise HTTPException(status_code=404, detail=f"Plan '{plan_id}' not found")
  return PlanResponse(
    id=plan.id,
    name=plan.name,
    rate_limit_per_minute=plan.rate_limit_per_minute,
    monthly_token_limit=plan.monthly_token_limit,
    max_keys=plan.max_keys,
    price_cents=plan.price_cents,
  )


# ── Org plan management endpoints (admin auth) ────────────────────────────────


@router.get(
  "/api/v1/org/{org_id}/plan",
  response_model=OrgPlanResponse,
  summary="Get the current plan, usage, and key counts for an org",
  dependencies=[Depends(require_admin_key)],
)
async def get_org_plan(
  org_id: str,
  container=Depends(_get_container),
) -> OrgPlanResponse:
  """
  Return the org's current plan, its monthly token usage, and active key count.

  Requires X-Admin-Key header.
  """
  _validate_path_uuid(org_id, "org_id")
  resolved_plan_id = await container.org_plan_port.get_org_plan_id(org_id)
  plan_id = resolved_plan_id or "free"

  plan = get_plan(plan_id) or get_plan("free")

  current_month = datetime.now(timezone.utc).strftime("%Y-%m")
  usage = await container.api_key_port.get_usage(org_id, current_month)

  all_keys = await container.api_key_port.list_keys(org_id)
  active_keys = sum(1 for k in all_keys if k.active)

  return OrgPlanResponse(
    plan=PlanResponse(
      id=plan.id,
      name=plan.name,
      rate_limit_per_minute=plan.rate_limit_per_minute,
      monthly_token_limit=plan.monthly_token_limit,
      max_keys=plan.max_keys,
      price_cents=plan.price_cents,
    ),
    usage={
      "month": usage.month,
      "tokenize_calls": usage.tokenize_calls,
      "rehydrate_calls": usage.rehydrate_calls,
      "flush_calls": usage.flush_calls,
      "total_tokens_created": usage.total_tokens_created,
    },
    active_keys=active_keys,
    max_keys=plan.max_keys,
  )


@router.post(
  "/api/v1/org/{org_id}/plan",
  response_model=OrgPlanResponse,
  summary="Assign a plan to an organization",
  dependencies=[Depends(require_admin_key)],
)
async def set_org_plan(
  org_id: str,
  body: ChangePlanRequest,
  container=Depends(_get_container),
) -> OrgPlanResponse:
  """
  Assign plan_id to the organization.

  Validates that the plan exists and that the org's current active key count
  does not exceed the new plan's max_keys. Returns 409 if keys must be revoked
  before downgrading, 404 if the plan_id is unknown.

  Requires X-Admin-Key header.
  """
  _validate_path_uuid(org_id, "org_id")
  target_plan = get_plan(body.plan_id)
  if target_plan is None:
    raise HTTPException(status_code=404, detail=f"Plan '{body.plan_id}' not found")

  all_keys = await container.api_key_port.list_keys(org_id)
  active_keys = sum(1 for k in all_keys if k.active)
  if active_keys > target_plan.max_keys:
    raise HTTPException(
      status_code=409,
      detail=(
        f"Cannot downgrade to plan '{body.plan_id}': org has {active_keys} active "
        f"keys but the plan allows {target_plan.max_keys}. "
        "Revoke excess keys before changing plan."
      ),
    )

  old_plan_id = await container.org_plan_port.get_org_plan_id(org_id) or "free"
  await container.org_plan_port.set_org_plan(
    org_id=org_id,
    plan_id=body.plan_id,
    stripe_customer_id=body.stripe_customer_id,
  )
  container.metrics.record_plan_change(from_plan=old_plan_id, to_plan=body.plan_id)
  log_operation(
    _logger,
    operation="set_org_plan",
    org_id=org_id,
    duration_ms=0,
    plan=body.plan_id,
  )

  current_month = datetime.now(timezone.utc).strftime("%Y-%m")
  usage = await container.api_key_port.get_usage(org_id, current_month)

  return OrgPlanResponse(
    plan=PlanResponse(
      id=target_plan.id,
      name=target_plan.name,
      rate_limit_per_minute=target_plan.rate_limit_per_minute,
      monthly_token_limit=target_plan.monthly_token_limit,
      max_keys=target_plan.max_keys,
      price_cents=target_plan.price_cents,
    ),
    usage={
      "month": usage.month,
      "tokenize_calls": usage.tokenize_calls,
      "rehydrate_calls": usage.rehydrate_calls,
      "flush_calls": usage.flush_calls,
      "total_tokens_created": usage.total_tokens_created,
    },
    active_keys=active_keys,
    max_keys=target_plan.max_keys,
  )


@router.get(
  "/health",
  summary="Structured liveness check with per-component status",
)
async def health(container=Depends(_get_container)) -> JSONResponse:
  """
  Return structured service health.

  Checks:
    - redis: PING round-trip with latency measurement
    - crypto: dummy encrypt→decrypt self-test to validate KEK
    - slm: not configured in Fase 1/3 — placeholder returns 'not_configured'

  HTTP status:
    200 → status='healthy' (all components up)
    503 → status='degraded' (one or more components down)
  """
  metrics = container.metrics

  redis_status = "up"
  redis_latency_ms: float | None = None
  try:
    t_redis = time.perf_counter()
    await container.redis_client.ping()
    redis_latency_ms = round((time.perf_counter() - t_redis) * 1000.0, 2)
  except Exception:
    redis_status = "down"

  crypto_status = "up"
  kek_valid = False
  try:
    kek_valid = container.crypto_port.validate_kek()
    if not kek_valid:
      crypto_status = "down"
  except Exception:
    crypto_status = "down"
    kek_valid = False

  slm_component = ComponentStatus(status="not_configured")

  all_up = redis_status == "up" and crypto_status == "up"
  overall_status = "healthy" if all_up else "degraded"

  components = HealthComponents(
    redis=ComponentStatus(status=redis_status, latency_ms=redis_latency_ms),
    crypto=ComponentStatus(status=crypto_status, kek_valid=kek_valid),
    slm=slm_component,
  )
  response_body = HealthResponse(
    status=overall_status,
    components=components,
    version=container.config.version,
  )

  metrics.record_health_check(overall_status)
  http_status = 200 if overall_status == "healthy" else 503
  return JSONResponse(status_code=http_status, content=response_body.model_dump())


@router.get(
  "/metrics",
  summary="In-memory metrics snapshot (admin-only)",
  dependencies=[Depends(require_admin_key)],
)
async def metrics_snapshot(container=Depends(_get_container)) -> JSONResponse:
  """
  Return an in-memory snapshot of all Privacy Shield counters and histograms.

  The snapshot is reset when the process restarts. No PII is ever included.
  Intended for use by internal monitoring dashboards and health scripts.
  """
  return JSONResponse(content=container.metrics.snapshot())


@router.get(
  "/metrics/prometheus",
  summary="Prometheus text exposition of all metrics (admin-only)",
  dependencies=[Depends(require_admin_key)],
)
async def metrics_prometheus(container=Depends(_get_container)) -> Response:
  """
  Return all Privacy Shield metrics in Prometheus text exposition format 0.0.4.

  Suitable for scraping by a Prometheus server or compatible collector.
  No PII, org_id, key_id, or IP addresses are ever included.
  Requires X-Admin-Key header.
  """
  return Response(
    content=container.metrics.to_prometheus(),
    media_type="text/plain; version=0.0.4; charset=utf-8",
  )
