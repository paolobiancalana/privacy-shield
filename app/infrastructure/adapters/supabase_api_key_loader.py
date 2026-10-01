"""
SupabaseApiKeyLoader — loads API key metadata from Supabase Postgres.

Used in two scenarios:
1. Startup warm-up: populates Redis with all active keys from Supabase so that
   a Redis restart does not immediately break all authentication.
2. Cache-aside fallback: when validate_key() misses in Redis (key was created
   after the last warm-up), this loader fetches the key from Supabase and
   writes it back into Redis so subsequent requests hit the cache.

Schema expected in Supabase (ps_api_keys + ps_organizations JOIN ps_plans):
  ps_api_keys.key_hash        TEXT  — SHA-256 of rawkey, unique index
  ps_api_keys.org_id          UUID  — FK → ps_organizations.id
  ps_api_keys.environment     TEXT  — 'live' | 'test'
  ps_api_keys.active          BOOL  — False means revoked
  ps_api_keys.revoked_at      TIMESTAMPTZ nullable
  ps_api_keys.expires_at      TIMESTAMPTZ nullable
  ps_organizations.plan_id    TEXT  — FK → ps_plans.id
  ps_plans.rate_limit_per_minute INT

The loader is stateless and thread-safe: it holds only the Supabase URL and
service-role key; all network calls are synchronous (supabase-py sync client).
Async wrapping is done in the container via run_in_executor.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

from app.domain.entities import ApiKeyMetadata

_logger = logging.getLogger("privacy_shield.supabase_loader")


class SupabaseApiKeyLoader:
    """
    Fetches active API key metadata from Supabase.

    All methods return ApiKeyMetadata objects compatible with the Redis adapter.
    The loader never writes to Supabase — it is read-only.
    """

    def __init__(self, supabase_url: str, supabase_service_key: str) -> None:
        self._client: Client = create_client(supabase_url, supabase_service_key)

    def _is_expired(self, expires_at: str | None) -> bool:
        """Return True if the key has a non-null expires_at in the past."""
        if not expires_at:
            return False
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return exp < datetime.now(timezone.utc)
        except (ValueError, AttributeError):
            return False

    def _row_to_metadata(self, row: dict) -> Optional[ApiKeyMetadata]:
        """Convert a Supabase row (with plan join) to ApiKeyMetadata."""
        try:
            # Respect active flag and expiry
            if not row.get("active", False):
                return None
            if self._is_expired(row.get("expires_at")):
                return None

            plan_data = row.get("ps_organizations", {}) or {}
            plan_obj = plan_data.get("ps_plans", {}) or {}
            rate_limit = plan_obj.get("rate_limit_per_minute", 100)
            plan_id = plan_data.get("plan_id", "free")

            return ApiKeyMetadata(
                key_id=str(row["id"]),
                org_id=str(row["org_id"]),
                key_hash=row["key_hash"],
                plan=plan_id,
                rate_limit_per_minute=max(1, int(rate_limit)),
                active=True,
                created_at=str(row.get("created_at", "")),
                environment=row.get("environment", "live"),
            )
        except Exception as exc:
            _logger.warning("Failed to parse API key row: %s", exc, extra={"row_id": row.get("id")})
            return None

    def load_all_active(self) -> list[ApiKeyMetadata]:
        """
        Fetch all active, non-expired API keys from Supabase.
        Used at startup for Redis warm-up.
        """
        try:
            response = (
                self._client.table("ps_api_keys")
                .select(
                    "id, key_hash, org_id, environment, active, created_at, expires_at, "
                    "ps_organizations!inner(plan_id, ps_plans!inner(rate_limit_per_minute))"
                )
                .eq("active", True)
                .is_("revoked_at", None)
                .execute()
            )
            rows = response.data or []
            results = []
            for row in rows:
                metadata = self._row_to_metadata(row)
                if metadata is not None:
                    results.append(metadata)
            _logger.info(
                "Loaded %d active API keys from Supabase",
                len(results),
                extra={"_ps_operation": "warmup"},
            )
            return results
        except Exception as exc:
            _logger.error(
                "Failed to load API keys from Supabase during warm-up: %s",
                exc,
                extra={"_ps_operation": "warmup"},
            )
            return []

    def load_by_hash(self, key_hash: str) -> Optional[ApiKeyMetadata]:
        """
        Fetch a single key by its SHA-256 hash from Supabase.
        Used as cache-aside fallback when the key misses in Redis.
        """
        try:
            response = (
                self._client.table("ps_api_keys")
                .select(
                    "id, key_hash, org_id, environment, active, created_at, expires_at, "
                    "ps_organizations!inner(plan_id, ps_plans!inner(rate_limit_per_minute))"
                )
                .eq("key_hash", key_hash)
                .eq("active", True)
                .is_("revoked_at", None)
                .maybe_single()
                .execute()
            )
            row = response.data
            if not row:
                return None
            return self._row_to_metadata(row)
        except Exception as exc:
            _logger.warning(
                "Supabase fallback lookup failed for key_hash=%s: %s",
                key_hash[:8],
                exc,
                extra={"_ps_operation": "cache_aside"},
            )
            return None
