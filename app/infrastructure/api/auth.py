"""
FastAPI authentication dependencies for the Privacy Shield API.

Two auth levels:
  require_api_key   — validates X-Api-Key header, checks rate limit, stores resolved
                      org context in request.state. Used on all operational endpoints
                      (tokenize, rehydrate, flush).
  require_admin_key — validates X-Admin-Key header against the ADMIN_API_KEY config
                      secret. Used on key management and DEK rotation endpoints.
                      Enforces a Redis sliding-window rate limit of 10 req/min per
                      client IP to prevent brute-force attacks.

require_api_key injects:
  request.state.api_key_meta  — the full ApiKeyMetadata for downstream use
  request.state.api_key_hash  — the SHA-256 hash (for usage recording in routes)

Both dependencies resolve the container from request.app.state.container to remain
stateless (no module-level singletons that would break test isolation).
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import Header, HTTPException, Request

from app.infrastructure.telemetry import get_logger

_logger = get_logger("auth")

_ADMIN_RATE_LIMIT = 10
_ADMIN_RATE_TTL_SECONDS = 120

_LUA_ADMIN_RATE_LIMIT = """
local key = KEYS[1]
local limit = tonumber(ARGV[1])
local ttl = tonumber(ARGV[2])
local count = redis.call('INCR', key)
if count == 1 then
    redis.call('EXPIRE', key, ttl)
end
return count
"""


def _extract_client_ip(request: Request) -> str:
  """Extract client IP, preferring X-Forwarded-For rightmost entry."""
  xff = request.headers.get("x-forwarded-for")
  if xff:
    ips = [ip.strip() for ip in xff.split(",")]
    if ips:
      return ips[-1]
  return request.client.host if request.client else "unknown"


async def require_api_key(
  request: Request,
  x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
) -> dict:
  """
  FastAPI dependency: validate X-Api-Key, enforce rate limit.

  Resolution steps:
    1. Reject immediately if header is missing (401).
    2. SHA-256 hash the raw key.
    3. Look up metadata via ApiKeyPort.validate_key() — returns None if
       not found or revoked (401).
    4. Increment the per-minute rate limit counter (429 if exceeded).
    5. Store metadata + hash in request.state for downstream routes.
    6. Return a dict with resolved org_id, plan, key_id, key_hash.

  Args:
    request: FastAPI request object.
    x_api_key: X-Api-Key header value.

  Returns:
    Dictionary with org_id, plan, key_id, key_hash.

  Raises:
    HTTPException: 401 if key is missing or invalid, 429 if rate limit exceeded.
  """
  if x_api_key is None:
    raise HTTPException(status_code=401, detail="Missing X-Api-Key header")

  # Reject keys with null bytes or control characters (prevents oracle attacks)
  if "\x00" in x_api_key or any(ord(c) < 32 for c in x_api_key):
    raise HTTPException(status_code=401, detail="Invalid API key")

  container = request.app.state.container
  api_key_port = container.api_key_port

  key_hash = hashlib.sha256(x_api_key.encode("utf-8")).hexdigest()
  metadata = await api_key_port.validate_key(key_hash)

  if metadata is None:
    _logger.warning(
      "API key validation failed — invalid or revoked key",
      extra={"_ps_operation": "auth", "key_hash_prefix": key_hash[:8]},
    )
    container.metrics.increment("ps_auth_failures_total", {"reason": "invalid_key"})
    raise HTTPException(status_code=401, detail="Invalid or revoked API key")

  allowed, count = await api_key_port.check_rate_limit(
    key_hash, metadata.rate_limit_per_minute
  )
  if not allowed:
    _logger.warning(
      "Rate limit exceeded",
      extra={
        "_ps_operation": "auth",
        "key_id": metadata.key_id,
        "org_id": metadata.org_id,
        "count": count,
        "limit": metadata.rate_limit_per_minute,
      },
    )
    container.metrics.increment("ps_auth_failures_total", {"reason": "rate_limited"})
    raise HTTPException(
      status_code=429,
      detail="Rate limit exceeded",
      headers={
        "Retry-After": "60",
        "X-RateLimit-Limit": str(metadata.rate_limit_per_minute),
      },
    )

  request.state.api_key_meta = metadata
  request.state.api_key_hash = key_hash

  return {
    "org_id": metadata.org_id,
    "plan": metadata.plan,
    "key_id": metadata.key_id,
    "key_hash": key_hash,
  }


async def require_admin_key(
  request: Request,
  x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
  """
  FastAPI dependency: enforce admin API key for privileged endpoints.

  Enforces a Redis sliding-window rate limit of 10 req/min per client IP
  BEFORE the key comparison to prevent timing-based brute force. The Redis
  key is set with a 2-minute TTL so partial windows expire cleanly.

  If ADMIN_API_KEY is empty in config, the endpoint is disabled (403).
  If the header is missing or does not match, returns 401.

  Args:
    request: FastAPI request object.
    x_admin_key: X-Admin-Key header value.

  Raises:
    HTTPException: 403 if endpoint is disabled, 429 if rate limit exceeded,
                   401 if key is missing or invalid.
  """
  container = request.app.state.container

  client_ip = _extract_client_ip(request)
  rate_key = f"ps:admin_rate:{client_ip}:{int(time.time()) // 60}"
  try:
    count = int(await container.redis_client.eval(
      _LUA_ADMIN_RATE_LIMIT, 1, rate_key,
      str(_ADMIN_RATE_LIMIT), str(_ADMIN_RATE_TTL_SECONDS),
    ))
  except Exception:
    count = await container.redis_client.incr(rate_key)
    if count == 1:
      await container.redis_client.expire(rate_key, _ADMIN_RATE_TTL_SECONDS)
  if count > _ADMIN_RATE_LIMIT:
    _logger.warning(
      "Admin rate limit exceeded",
      extra={"_ps_operation": "admin_auth", "client_ip": client_ip, "count": count},
    )
    container.metrics.increment("ps_auth_failures_total", {"reason": "admin_rate_limited"})
    raise HTTPException(status_code=429, detail="Admin rate limit exceeded")

  config = container.config
  expected_key: str = getattr(config, "admin_api_key", "")
  if not expected_key:
    raise HTTPException(status_code=403, detail="Admin endpoint disabled")
  if not hmac.compare_digest(x_admin_key or "", expected_key):
    _logger.warning(
      "Admin key validation failed — invalid or missing X-Admin-Key",
      extra={"_ps_operation": "admin_auth", "client_ip": client_ip},
    )
    container.metrics.increment("ps_auth_failures_total", {"reason": "admin_invalid"})
    raise HTTPException(status_code=401, detail="Invalid or missing X-Admin-Key")
