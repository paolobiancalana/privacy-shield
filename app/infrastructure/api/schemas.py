"""
Pydantic request/response models for the Privacy Shield API.

All models use strict typing. No 'Any' fields — the API surface is fully typed.
organization_id and request_id are validated as UUID strings at the model level.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, field_validator


def _validate_uuid(v: str, field_name: str) -> str:
  try:
    uuid.UUID(v)
  except ValueError:
    raise ValueError(f"{field_name} must be a valid UUID")
  return v


class TokenizeRequest(BaseModel):
  """Request body for POST /api/v1/tokenize."""

  texts: list[str] = Field(..., min_length=1, max_length=100, description="One or more texts to tokenize (max 100).")
  organization_id: str = Field(..., description="UUID of the processing organization.")
  request_id: str = Field(..., description="UUID identifying this request (for flush).")
  existing_tokens: dict[str, str] = Field(
    default_factory=dict,
    max_length=1_000,
    description="Carry-over map: pii_value → token from previous turns (max 1000 entries).",
  )

  @field_validator("organization_id")
  @classmethod
  def validate_org_id(cls, v: str) -> str:
    return _validate_uuid(v, "organization_id")

  @field_validator("request_id")
  @classmethod
  def validate_request_id(cls, v: str) -> str:
    return _validate_uuid(v, "request_id")

  @field_validator("existing_tokens")
  @classmethod
  def validate_existing_tokens_sizes(cls, v: dict[str, str]) -> dict[str, str]:
    for key, val in v.items():
      if len(key) > 512 or len(val) > 128:
        raise ValueError("existing_tokens entries must be <= 512 chars key, 128 chars value")
    return v

  @field_validator("texts")
  @classmethod
  def validate_texts(cls, v: list[str]) -> list[str]:
    if not v:
      raise ValueError("texts must contain at least one element")
    for i, t in enumerate(v):
      if not isinstance(t, str):
        raise ValueError(f"texts[{i}] must be a string")
    return v

  @field_validator("texts")
  @classmethod
  def validate_text_lengths(cls, v: list[str]) -> list[str]:
    for i, text in enumerate(v):
      if len(text) > 10_000:
        raise ValueError(f"Text at index {i} exceeds 10000 character limit")
    return v


class TokenInfo(BaseModel):
  """Metadata for one tokenized PII span."""

  original: str = Field(..., description="Original PII value (DO NOT LOG THIS).")
  token: str = Field(..., description="Opaque token string e.g. '[#pe:a3f2]'.")
  type: str = Field(..., description="PII type code e.g. 'pe', 'cf'.")
  start: int = Field(..., description="Start offset in the original text.")
  end: int = Field(..., description="End offset (exclusive) in the original text.")
  source: str = Field(..., description="Detection source: 'regex' or 'slm'.")


class TokenizeResponse(BaseModel):
  """Response body for POST /api/v1/tokenize."""

  tokenized_texts: list[str]
  tokens: list[TokenInfo]
  detection_ms: float
  tokenization_ms: float


class RehydrateRequest(BaseModel):
  """Request body for POST /api/v1/rehydrate."""

  text: str = Field(..., description="Text containing Privacy Shield tokens.")
  organization_id: str = Field(..., description="UUID of the processing organization.")
  request_id: str = Field(
    ...,
    description="UUID of the originating tokenization request. "
    "Must match the request_id used during tokenize — enforces vault scoping.",
  )

  @field_validator("organization_id")
  @classmethod
  def validate_org_id(cls, v: str) -> str:
    return _validate_uuid(v, "organization_id")

  @field_validator("request_id")
  @classmethod
  def validate_request_id(cls, v: str) -> str:
    return _validate_uuid(v, "request_id")


class RehydrateResponse(BaseModel):
  """Response body for POST /api/v1/rehydrate."""

  text: str
  rehydrated_count: int


class FlushRequest(BaseModel):
  """Request body for POST /api/v1/flush."""

  organization_id: str
  request_id: str

  @field_validator("organization_id")
  @classmethod
  def validate_org_id(cls, v: str) -> str:
    return _validate_uuid(v, "organization_id")

  @field_validator("request_id")
  @classmethod
  def validate_request_id(cls, v: str) -> str:
    return _validate_uuid(v, "request_id")


class FlushResponse(BaseModel):
  """Response body for POST /api/v1/flush."""

  flushed_count: int


class RotateDekRequest(BaseModel):
  """Request body for POST /api/v1/rotate-dek."""

  organization_id: str = Field(
    ...,
    description="UUID of the organization whose DEK should be rotated.",
  )

  @field_validator("organization_id")
  @classmethod
  def validate_org_id(cls, v: str) -> str:
    return _validate_uuid(v, "organization_id")


class RotateDekResponse(BaseModel):
  """Response body for POST /api/v1/rotate-dek."""

  rotated: bool = Field(..., description="True if the rotation completed successfully.")
  re_encrypted_count: int = Field(
    ...,
    description="Number of vault entries re-encrypted under the new DEK.",
  )


class ComponentStatus(BaseModel):
  """Status of a single health component."""

  status: str = Field(..., description="'up', 'down', or 'not_configured'.")
  latency_ms: float | None = Field(None, description="Round-trip latency in ms (if applicable).")
  kek_valid: bool | None = Field(None, description="True if the KEK decrypt test passed (crypto only).")


class HealthComponents(BaseModel):
  """Per-component breakdown for the health response."""

  redis: ComponentStatus
  crypto: ComponentStatus
  slm: ComponentStatus


class HealthResponse(BaseModel):
  """
  Response body for GET /health (enhanced Fase 4 format).

  HTTP status mapping:
    200 → 'healthy'
    503 → 'degraded' or 'unhealthy'
  """

  status: str = Field(..., description="'healthy', 'degraded', or 'unhealthy'.")
  components: HealthComponents
  version: str


class ErrorResponse(BaseModel):
  """Standardized error envelope — never exposes internal stack traces."""

  error: str
  code: str
  detail: str | None = None


class CreateKeyRequest(BaseModel):
  """
  Request body for POST /api/v1/keys.

  The plan and rate_limit_per_minute fields are accepted for backward compatibility
  but are silently ignored when OrgPlanPort is wired in the container — the org's
  assigned plan drives both values automatically.
  """

  model_config = {"extra": "ignore"}

  organization_id: str = Field(
    ...,
    description="UUID of the organization this key belongs to.",
  )
  environment: str = Field(
    "live",
    pattern="^(live|test)$",
    description="Key environment: 'live' or 'test'.",
  )

  @field_validator("organization_id")
  @classmethod
  def validate_org_id(cls, v: str) -> str:
    return _validate_uuid(v, "organization_id")


class CreateKeyResponse(BaseModel):
  """Response body for POST /api/v1/keys. The key is shown only once."""

  key: str = Field(
    ...,
    description="The raw API key. Store it securely — it cannot be retrieved again.",
  )
  key_id: str = Field(..., description="Stable identifier for the key (for revocation).")
  organization_id: str


class ChangePlanRequest(BaseModel):
  """Request body for POST /api/v1/org/{org_id}/plan."""

  plan_id: str = Field(..., description="Target plan ID (must exist in the plan catalog).")
  stripe_customer_id: str | None = Field(
    None,
    max_length=64,
    pattern=r"^cus_[A-Za-z0-9]{14,24}$",
    description="Stripe customer ID (format: cus_xxx).",
  )


class PlanResponse(BaseModel):
  """Serialized representation of a Plan for API consumers."""

  id: str
  name: str
  rate_limit_per_minute: int
  monthly_token_limit: int
  max_keys: int
  price_cents: int


class OrgPlanResponse(BaseModel):
  """Current plan, usage, and key-count summary for an organization."""

  plan: PlanResponse
  usage: dict
  active_keys: int
  max_keys: int
