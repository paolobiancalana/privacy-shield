"""
SupabaseApiKeyLoader — loads API key metadata from Supabase Postgres.

Supabase is the authorization authority on every request. Redis warm-up is
metadata caching only; revocation and expiry never rely on a positive cache.
New runtime keys and backend revocations are written to the same authority.

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

    Read methods return ApiKeyMetadata objects compatible with the Redis adapter.
    Authorization reads and durable creation/revocation share the same authority.
    """

    def __init__(self, supabase_url: str, supabase_service_key: str) -> None:
        self._client: Client = create_client(supabase_url, supabase_service_key)

    def _is_expired(self, expires_at: str | None) -> bool:
        """Return True if the key has a non-null expires_at in the past."""
        if expires_at is None:
            return False
        try:
            exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            return exp <= datetime.now(timezone.utc)
        except (ValueError, AttributeError, TypeError):
            return True

    def _row_to_metadata(self, row: dict) -> Optional[ApiKeyMetadata]:
        """Convert a Supabase row (with plan join) to ApiKeyMetadata."""
        try:
            # Respect active flag and expiry
            if row.get("active") is not True or row.get("revoked_at") is not None:
                return None
            if self._is_expired(row.get("expires_at")):
                return None

            plan_data = row.get("ps_organizations")
            if not plan_data:
                return None
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
            _logger.warning("Failed to parse API key row: %s", type(exc).__name__, extra={"row_id": row.get("id")})
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
                    "id, key_hash, org_id, environment, active, revoked_at, created_at, expires_at, "
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
                type(exc).__name__,
                extra={"_ps_operation": "warmup"},
            )
            return []

    def load_by_hash(self, key_hash: str) -> Optional[ApiKeyMetadata]:
        """
        Fetch a single key by its SHA-256 hash from Supabase.
        Used on every authentication attempt, including warm Redis hits.
        """
        try:
            response = (
                self._client.table("ps_api_keys")
                .select(
                    "id, key_hash, org_id, environment, active, revoked_at, created_at, expires_at, "
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
                type(exc).__name__,
                extra={"_ps_operation": "cache_aside"},
            )
            return None

    def revoke_by_hash(self, key_hash: str) -> bool:
        """Durable, idempotent control-plane revocation; errors propagate."""
        response = (self._client.table("ps_api_keys")
                    .update({"active": False, "revoked_at": datetime.now(timezone.utc).isoformat()})
                    .eq("key_hash", key_hash).execute())
        return bool(response.data)

    def register_key(self, metadata: ApiKeyMetadata) -> None:
        """Insert a new runtime key. NEVER upsert: replay cannot undo revocation.

        Supabase generates its own UUID; runtime key_id remains the legacy
        display identifier. Organization must already exist in the authority.
        """
        response = (self._client.table("ps_api_keys").insert({
            "org_id": metadata.org_id, "key_hash": metadata.key_hash,
            "key_prefix": f"ps_{metadata.environment}_…",
            "label": "Runtime API key", "environment": metadata.environment,
            "active": metadata.active, "created_at": metadata.created_at,
        }).execute())
        if not response.data:
            raise RuntimeError("API key authority insert failed")

    def check_available(self) -> bool:
        """Read-only readiness probe; a missing key is not a connectivity test."""
        try:
            self._client.table("ps_api_keys").select("id").limit(1).execute()
            return True
        except Exception:
            return False
