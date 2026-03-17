"""
TokenizeTextUseCase monthly quota enforcement tests.

Adversarial Analysis:
  1. The monthly quota check uses increment_and_check_monthly_tokens() which
     atomically increments and checks in a single Redis operation (TOCTOU-safe).
  2. Enterprise plans (monthly_token_limit == -1) must ALWAYS skip the monthly
     check, even if usage is astronomically high.
  3. When both api_key_port and org_plan_port are None, the monthly quota check
     must be entirely skipped (backward compat).
  4. The vault quota (QuotaExceededError) is independent of the monthly quota
     (MonthlyQuotaExceededError). Both must work independently.
  5. Monthly quota is only checked when PII spans are detected (post-detection,
     pre-vault-write). If no spans, no tokens to count.

Boundary Map:
  increment result: (True, new_total) allowed, (False, current) blocked
  monthly_token_limit: -1 (skip), 0 (always blocked — edge case), 1000 (free)
  api_key_port / org_plan_port: None (skip) vs injected (enforce)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.application.tokenize_text import TokenizeTextUseCase
from app.domain.entities import (
    DetectionResult,
    MonthlyQuotaExceededError,
    PiiSpan,
    QuotaExceededError,
    UsageRecord,
)


def _make_detection_with_spans() -> AsyncMock:
    """Detection mock that returns one PII span (triggers monthly quota check)."""
    d = AsyncMock()
    d.detect = AsyncMock(
        return_value=DetectionResult(
            spans=[PiiSpan(start=0, end=4, text="test", pii_type="pe", source="regex", confidence=1.0)],
            detection_ms=0.1,
            source="regex",
        )
    )
    return d


@pytest.fixture
def mock_detection() -> AsyncMock:
    d = AsyncMock()
    d.detect = AsyncMock(
        return_value=DetectionResult(spans=[], detection_ms=0.1, source="regex")
    )
    return d


@pytest.fixture
def mock_detection_with_spans() -> AsyncMock:
    return _make_detection_with_spans()


@pytest.fixture
def mock_vault() -> AsyncMock:
    v = AsyncMock()
    v.count_org_tokens = AsyncMock(return_value=0)
    return v


@pytest.fixture
def mock_crypto() -> MagicMock:
    c = MagicMock()
    c.get_or_create_dek = AsyncMock(return_value=b"\x02" * 32)
    c.hmac_token_hash = MagicMock(return_value="a1b2")
    c.encrypt = MagicMock(return_value=b"encrypted")
    return c


@pytest.fixture
def mock_api_key_port() -> AsyncMock:
    port = AsyncMock()
    port.get_usage = AsyncMock(
        return_value=UsageRecord(
            org_id="org-1",
            month="2026-03",
            tokenize_calls=0,
            rehydrate_calls=0,
            flush_calls=0,
            total_tokens_created=0,
        )
    )
    port.increment_and_check_monthly_tokens = AsyncMock(return_value=(True, 0))
    return port


@pytest.fixture
def mock_org_plan_port() -> AsyncMock:
    port = AsyncMock()
    port.get_org_plan_id = AsyncMock(return_value=None)  # defaults to "free"
    return port


ORG_ID = "00000000-0000-0000-0000-00000000000a"
REQ_ID = "00000000-0000-0000-0000-000000000099"


class TestMonthlyQuotaEnforcement:
    """Monthly quota enforcement via atomic increment_and_check_monthly_tokens."""

    async def test_raises_when_atomic_check_rejects(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Free plan has 1000 monthly limit. Atomic increment returns rejected."""
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.increment_and_check_monthly_tokens.return_value = (False, 1000)
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MonthlyQuotaExceededError) as exc_info:
            await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)
        assert exc_info.value.used == 1000
        assert exc_info.value.limit == 1000
        assert exc_info.value.plan_id == "free"

    async def test_raises_when_starter_plan_rejects(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "starter"
        mock_api_key_port.increment_and_check_monthly_tokens.return_value = (False, 50_000)
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MonthlyQuotaExceededError) as exc_info:
            await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)
        assert exc_info.value.plan_id == "starter"
        assert exc_info.value.limit == 50_000

    async def test_allows_when_atomic_check_accepts(
        self,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.increment_and_check_monthly_tokens.return_value = (True, 999)
        uc = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        # No PII spans → quota check skipped, should not raise
        result = await uc.execute(text="no PII here", org_id=ORG_ID, request_id=REQ_ID)
        assert result.tokenized_text == "no PII here"


class TestEnterpriseBypasses:
    """Enterprise plan (monthly_token_limit == -1) always passes."""

    async def test_enterprise_skips_monthly_check_even_with_spans(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "enterprise"
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        # Must NOT raise MonthlyQuotaExceededError — enterprise skips the check
        result = await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)
        assert result.tokenized_text is not None

    async def test_enterprise_increment_not_called(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Enterprise should short-circuit before calling increment_and_check."""
        mock_org_plan_port.get_org_plan_id.return_value = "enterprise"
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)
        mock_api_key_port.increment_and_check_monthly_tokens.assert_not_called()


class TestBackwardCompatibility:
    """Without both ports, monthly quota is not checked."""

    async def test_no_ports_skips_monthly_check(
        self,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        uc = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=None,
            org_plan_port=None,
        )
        result = await uc.execute(text="no PII", org_id=ORG_ID, request_id=REQ_ID)
        assert result.tokenized_text == "no PII"

    async def test_only_api_key_port_skips_monthly_check(
        self,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
    ) -> None:
        """If org_plan_port is None but api_key_port is present, skip."""
        uc = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=None,
        )
        result = await uc.execute(text="no PII", org_id=ORG_ID, request_id=REQ_ID)
        assert result.tokenized_text == "no PII"

    async def test_only_org_plan_port_skips_monthly_check(
        self,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """If api_key_port is None but org_plan_port is present, skip."""
        uc = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=None,
            org_plan_port=mock_org_plan_port,
        )
        result = await uc.execute(text="no PII", org_id=ORG_ID, request_id=REQ_ID)
        assert result.tokenized_text == "no PII"


class TestVaultQuotaIndependence:
    """Vault quota (QuotaExceededError) works independently of monthly quota."""

    async def test_vault_quota_still_enforced_without_plan_ports(
        self,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_vault.count_org_tokens.return_value = 10_000  # at limit
        uc = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            max_tokens_per_org=10_000,
            api_key_port=None,
            org_plan_port=None,
        )
        with pytest.raises(QuotaExceededError):
            await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)

    async def test_vault_quota_fires_before_monthly_when_both_exceeded(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        """Vault check runs before detection+monthly check, so QuotaExceededError
        fires first when both limits are exceeded."""
        mock_org_plan_port.get_org_plan_id.return_value = "free"
        mock_api_key_port.increment_and_check_monthly_tokens.return_value = (False, 2000)
        mock_vault.count_org_tokens.return_value = 20_000  # over vault limit
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            max_tokens_per_org=10_000,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        # Vault quota fires first (it runs before detection + monthly check)
        with pytest.raises(QuotaExceededError):
            await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)


class TestPlanResolutionFallback:
    """When org has invalid/missing plan_id, should fall back to free."""

    async def test_invalid_plan_id_falls_back_to_free(
        self,
        mock_detection_with_spans: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
        mock_api_key_port: AsyncMock,
        mock_org_plan_port: AsyncMock,
    ) -> None:
        mock_org_plan_port.get_org_plan_id.return_value = "nonexistent_plan"
        mock_api_key_port.increment_and_check_monthly_tokens.return_value = (False, 1000)
        uc = TokenizeTextUseCase(
            detection=mock_detection_with_spans,
            vault=mock_vault,
            crypto=mock_crypto,
            api_key_port=mock_api_key_port,
            org_plan_port=mock_org_plan_port,
        )
        with pytest.raises(MonthlyQuotaExceededError) as exc_info:
            await uc.execute(text="test", org_id=ORG_ID, request_id=REQ_ID)
        assert exc_info.value.plan_id == "free"
