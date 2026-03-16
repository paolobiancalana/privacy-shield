"""
Settings — Pydantic BaseSettings for the Privacy Shield microservice.

All configuration is loaded from environment variables. No hardcoded values
except safe defaults (host, port, TTL, log level). The KEK is mandatory —
startup fails immediately if absent.
"""
from __future__ import annotations

import base64

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
  """
  Runtime configuration loaded from environment variables.

  Mandatory:
    PRIVACY_SHIELD_KEK_BASE64 — base64-encoded 32-byte master key.

  Optional (with sensible defaults):
    REDIS_URL           — Redis connection URL.
    TOKEN_TTL_SECONDS   — Vault entry lifetime in seconds.
    HOST                — Uvicorn bind host.
    PORT                — Uvicorn bind port.
    LOG_LEVEL           — Python logging level string.
    ADMIN_API_KEY       — Admin API key for privileged endpoints.
    DEFAULT_RATE_LIMIT  — Default rate limit for new API keys.
    APP_VERSION         — Service version string.
  """

  kek_base64: str = Field(..., alias="PRIVACY_SHIELD_KEK_BASE64")
  # Redis auth supported via URL: redis://:password@host:port
  redis_url: str = Field("redis://localhost:6379", alias="REDIS_URL")
  token_ttl_seconds: int = Field(60, alias="TOKEN_TTL_SECONDS")
  host: str = Field("0.0.0.0", alias="HOST")
  port: int = Field(8000, alias="PORT")
  log_level: str = Field("INFO", alias="LOG_LEVEL")
  version: str = Field("1.0.0", alias="APP_VERSION")
  admin_api_key: str = Field("", alias="ADMIN_API_KEY")
  default_rate_limit: int = Field(100, alias="DEFAULT_RATE_LIMIT")
  max_tokens_per_org: int = Field(10_000, alias="MAX_TOKENS_PER_ORG")
  pii_model_dir: str = Field("/opt/pii/model", alias="PII_MODEL_DIR")

  model_config = {"populate_by_name": True}

  @field_validator("kek_base64")
  @classmethod
  def validate_kek(cls, v: str) -> str:
    """Ensure the KEK decodes to exactly 32 bytes."""
    try:
      raw = base64.b64decode(v)
    except Exception as exc:
      raise ValueError("PRIVACY_SHIELD_KEK_BASE64 is not valid base64") from exc
    if len(raw) != 32:
      raise ValueError(
        f"PRIVACY_SHIELD_KEK_BASE64 must decode to 32 bytes, got {len(raw)}"
      )
    return v

  @field_validator("token_ttl_seconds")
  @classmethod
  def validate_ttl(cls, v: int) -> int:
    if v < 10:
      raise ValueError("TOKEN_TTL_SECONDS must be >= 10")
    return v

  @field_validator("log_level")
  @classmethod
  def validate_log_level(cls, v: str) -> str:
    valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    upper = v.upper()
    if upper not in valid:
      raise ValueError(f"LOG_LEVEL must be one of {valid}, got {v!r}")
    return upper

  def kek_bytes(self) -> bytes:
    """Decode and return the raw KEK bytes."""
    return base64.b64decode(self.kek_base64)
