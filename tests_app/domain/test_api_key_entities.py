"""
Domain entity tests for ApiKeyMetadata and UsageRecord.

Adversarial Analysis:
  1. ApiKeyMetadata.__post_init__ accepts only "live"/"test" for environment.
     An attacker passing "staging", "", or None should trigger ValueError.
  2. rate_limit_per_minute must be >= 1. Values of 0, -1, and boundary 1 are tested.
  3. Frozen dataclasses must reject mutation. An attacker who obtains a metadata
     reference must not be able to modify org_id or active status.

Boundary Map:
  environment: "live", "test" (valid) -> "staging", "", " live", "LIVE" (invalid)
  rate_limit_per_minute: 1 (min valid) -> 0 (invalid), -1 (invalid), 2**31 (large valid)
"""
from __future__ import annotations

import dataclasses

import pytest

from app.domain.entities import ApiKeyMetadata, UsageRecord


def _make_meta(**overrides) -> ApiKeyMetadata:
    """Factory with sane defaults. Override any field via kwargs."""
    defaults = {
        "key_id": "kid_test_abc123",
        "org_id": "550e8400-e29b-41d4-a716-446655440000",
        "key_hash": "a" * 64,
        "plan": "standard",
        "rate_limit_per_minute": 100,
        "active": True,
        "created_at": "2026-03-15T12:00:00Z",
        "environment": "live",
    }
    defaults.update(overrides)
    return ApiKeyMetadata(**defaults)


class TestApiKeyMetadataConstruction:
    """Valid construction cases."""

    def test_valid_live_key(self) -> None:
        meta = _make_meta(environment="live")
        assert meta.org_id == "550e8400-e29b-41d4-a716-446655440000"
        assert meta.active is True
        assert meta.environment == "live"
        assert meta.rate_limit_per_minute == 100
        assert meta.plan == "standard"

    def test_valid_test_key(self) -> None:
        meta = _make_meta(environment="test")
        assert meta.environment == "test"

    def test_minimum_valid_rate_limit(self) -> None:
        meta = _make_meta(rate_limit_per_minute=1)
        assert meta.rate_limit_per_minute == 1

    def test_large_rate_limit(self) -> None:
        meta = _make_meta(rate_limit_per_minute=2**31)
        assert meta.rate_limit_per_minute == 2**31

    def test_inactive_key(self) -> None:
        meta = _make_meta(active=False)
        assert meta.active is False


class TestApiKeyMetadataEnvironmentValidation:
    """Environment field must be exactly 'live' or 'test'."""

    @pytest.mark.parametrize(
        "bad_env",
        [
            "staging",
            "production",
            "",
            " live",
            "live ",
            "LIVE",
            "TEST",
            "Live",
            "test\n",
            "live\x00",
        ],
    )
    def test_invalid_environment_raises_valueerror(self, bad_env: str) -> None:
        with pytest.raises(ValueError, match="environment"):
            _make_meta(environment=bad_env)


class TestApiKeyMetadataRateLimitValidation:
    """rate_limit_per_minute must be >= 1."""

    @pytest.mark.parametrize("bad_limit", [0, -1, -100])
    def test_zero_and_negative_rate_limit_raises(self, bad_limit: int) -> None:
        with pytest.raises(ValueError, match="rate_limit_per_minute"):
            _make_meta(rate_limit_per_minute=bad_limit)


class TestApiKeyMetadataImmutability:
    """Frozen dataclass must reject field mutation."""

    def test_cannot_mutate_active(self) -> None:
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.active = False  # type: ignore[misc]

    def test_cannot_mutate_org_id(self) -> None:
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.org_id = "attacker-org"  # type: ignore[misc]

    def test_cannot_mutate_rate_limit(self) -> None:
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.rate_limit_per_minute = 999999  # type: ignore[misc]

    def test_cannot_mutate_environment(self) -> None:
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.environment = "test"  # type: ignore[misc]

    def test_cannot_mutate_key_hash(self) -> None:
        meta = _make_meta()
        with pytest.raises(dataclasses.FrozenInstanceError):
            meta.key_hash = "attacker_hash"  # type: ignore[misc]


class TestUsageRecordConstruction:
    """UsageRecord valid construction and immutability."""

    def test_valid_construction(self) -> None:
        record = UsageRecord(
            org_id="org-1",
            month="2026-03",
            tokenize_calls=10,
            rehydrate_calls=5,
            flush_calls=2,
            total_tokens_created=150,
        )
        assert record.org_id == "org-1"
        assert record.month == "2026-03"
        assert record.tokenize_calls == 10
        assert record.rehydrate_calls == 5
        assert record.flush_calls == 2
        assert record.total_tokens_created == 150

    def test_zero_usage(self) -> None:
        record = UsageRecord(
            org_id="org-1",
            month="2026-03",
            tokenize_calls=0,
            rehydrate_calls=0,
            flush_calls=0,
            total_tokens_created=0,
        )
        assert record.tokenize_calls == 0
        assert record.total_tokens_created == 0

    def test_frozen_immutability(self) -> None:
        record = UsageRecord(
            org_id="org-1",
            month="2026-03",
            tokenize_calls=10,
            rehydrate_calls=5,
            flush_calls=2,
            total_tokens_created=150,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            record.tokenize_calls = 999  # type: ignore[misc]

        with pytest.raises(dataclasses.FrozenInstanceError):
            record.org_id = "attacker-org"  # type: ignore[misc]
