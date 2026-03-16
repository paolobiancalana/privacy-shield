"""
TokenizeTextUseCase tests — orchestration logic with mocked ports.

Adversarial Analysis:
  1. Collision handling: two PII values with same HMAC[:4] must produce distinct tokens.
  2. Same PII appearing twice in one text must reuse the same token (deduplication).
  3. _MAX_COLLISION_ATTEMPTS exhaustion (>50) must raise RuntimeError, not loop forever.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, call

import pytest

from app.application.tokenize_text import TokenizeTextUseCase, _MAX_COLLISION_ATTEMPTS
from app.domain.entities import DetectionResult, PiiSpan, TokenizeResult


ORG_ID = "00000000-0000-0000-0000-000000000001"
REQUEST_ID = "00000000-0000-0000-0000-000000000099"


def _make_span(
    start: int, end: int, text: str, pii_type: str = "pe", source: str = "regex"
) -> PiiSpan:
    return PiiSpan(
        start=start, end=end, text=text, pii_type=pii_type, source=source, confidence=1.0
    )


@pytest.fixture
def use_case(mock_detection: AsyncMock, mock_vault: AsyncMock, mock_crypto: MagicMock) -> TokenizeTextUseCase:
    return TokenizeTextUseCase(
        detection=mock_detection,
        vault=mock_vault,
        crypto=mock_crypto,
        token_ttl_seconds=60,
    )


class TestTokenizeSinglePii:
    """Single PII detected: token created, vault stored, request registered."""

    async def test_single_pii_tokenized(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[_make_span(0, 5, "Mario")],
            detection_ms=1.0,
            source="regex",
        )
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        result = await use_case.execute("Mario ha chiamato", ORG_ID, REQUEST_ID)

        assert isinstance(result, TokenizeResult)
        assert len(result.tokens) == 1
        assert result.tokens[0].token == "[#pe:a1b2]"
        assert result.tokens[0].original == "Mario"
        assert "[#pe:a1b2]" in result.tokenized_text
        assert "Mario" not in result.tokenized_text
        assert result.span_count == 1

        # Vault store was called
        mock_vault.store.assert_called_once()
        mock_vault.register_request_token.assert_called_once()

    async def test_detection_ms_propagated(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[], detection_ms=42.5, source="regex"
        )
        result = await use_case.execute("no pii", ORG_ID, REQUEST_ID)
        assert result.detection_ms == 42.5

    async def test_tokenization_ms_populated(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[], detection_ms=0.0, source="regex"
        )
        result = await use_case.execute("no pii", ORG_ID, REQUEST_ID)
        assert result.tokenization_ms >= 0.0


class TestTokenizeMultiplePii:
    """Multiple distinct PII values: each gets its own token."""

    async def test_multiple_pii_all_tokenized(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[
                _make_span(0, 5, "Mario", "pe"),
                _make_span(20, 36, "RSSMRA85M01H501Z", "cf"),
            ],
            detection_ms=2.0,
            source="regex",
        )
        # Return different hashes for different values
        mock_crypto.hmac_token_hash.side_effect = ["a1b2", "c3d4"]

        result = await use_case.execute(
            "Mario con codice RSSMRA85M01H501Z", ORG_ID, REQUEST_ID
        )

        assert len(result.tokens) == 2
        assert result.tokens[0].pii_type == "pe"
        assert result.tokens[1].pii_type == "cf"
        assert result.span_count == 2


class TestTokenizeDeduplication:
    """Same PII appearing twice: same token reused (no duplicate vault store)."""

    async def test_same_pii_twice_same_token(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[
                _make_span(0, 5, "Mario", "pe"),
                _make_span(10, 15, "Mario", "pe"),
            ],
            detection_ms=1.0,
            source="regex",
        )
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        result = await use_case.execute("Mario xxx Mario", ORG_ID, REQUEST_ID)

        assert len(result.tokens) == 2
        # Both should be the same token
        assert result.tokens[0].token == result.tokens[1].token
        # Vault store called only ONCE (deduplicated)
        assert mock_vault.store.call_count == 1


class TestTokenizeCollision:
    """HMAC collision: two different PII with same base hash get different suffixes."""

    async def test_collision_produces_suffixed_hash(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[
                _make_span(0, 5, "Mario", "pe"),
                _make_span(10, 15, "Paolo", "pe"),
            ],
            detection_ms=1.0,
            source="regex",
        )
        # Both produce same base hash
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        result = await use_case.execute("Mario xxx Paolo", ORG_ID, REQUEST_ID)

        assert len(result.tokens) == 2
        # First gets base hash, second gets collision suffix
        assert result.tokens[0].token_hash == "a1b2"
        assert result.tokens[1].token_hash == "a1b2_2"
        assert result.tokens[0].token != result.tokens[1].token


class TestTokenizeExistingTokens:
    """existing_tokens carry-over from prior texts."""

    async def test_existing_tokens_prevent_collision(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        # existing_tokens already claims "a1b2" for "Mario"
        existing = {"Mario": "[#pe:a1b2]"}

        mock_detection.detect.return_value = DetectionResult(
            spans=[_make_span(0, 5, "Paolo", "pe")],
            detection_ms=1.0,
            source="regex",
        )
        # Same base hash as Mario
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        result = await use_case.execute("Paolo xxx", ORG_ID, REQUEST_ID, existing_tokens=existing)

        # Paolo should get a1b2_2 since a1b2 is taken by Mario
        assert len(result.tokens) == 1
        assert result.tokens[0].token_hash == "a1b2_2"

    async def test_existing_tokens_same_value_reuses_hash(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        existing = {"Mario": "[#pe:a1b2]"}
        mock_detection.detect.return_value = DetectionResult(
            spans=[_make_span(0, 5, "Mario", "pe")],
            detection_ms=1.0,
            source="regex",
        )
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        result = await use_case.execute("Mario xxx", ORG_ID, REQUEST_ID, existing_tokens=existing)
        # Same value -> same hash reused (idempotent)
        assert result.tokens[0].token_hash == "a1b2"


class TestTokenizeEmptyAndNoPii:
    """Empty text and no PII found."""

    async def test_empty_text_no_tokens(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[], detection_ms=0.1, source="regex"
        )
        result = await use_case.execute("", ORG_ID, REQUEST_ID)
        assert result.tokenized_text == ""
        assert result.tokens == []
        assert result.span_count == 0

    async def test_no_pii_text_unchanged(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[], detection_ms=0.5, source="regex"
        )
        result = await use_case.execute("Ciao a tutti!", ORG_ID, REQUEST_ID)
        assert result.tokenized_text == "Ciao a tutti!"
        assert result.tokens == []


class TestTokenizeErrorPropagation:
    """Detection or vault failures propagate gracefully."""

    async def test_detection_failure_propagates(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
    ) -> None:
        mock_detection.detect.side_effect = RuntimeError("detector crashed")
        with pytest.raises(RuntimeError, match="detector crashed"):
            await use_case.execute("test", ORG_ID, REQUEST_ID)

    async def test_vault_store_failure_propagates(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_vault: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        mock_detection.detect.return_value = DetectionResult(
            spans=[_make_span(0, 5, "Mario")],
            detection_ms=1.0,
            source="regex",
        )
        mock_crypto.hmac_token_hash.return_value = "a1b2"
        mock_vault.store.side_effect = ConnectionError("Redis down")

        with pytest.raises(ConnectionError, match="Redis down"):
            await use_case.execute("Mario", ORG_ID, REQUEST_ID)

    async def test_crypto_get_or_create_dek_failure_propagates(
        self,
        use_case: TokenizeTextUseCase,
        mock_crypto: MagicMock,
    ) -> None:
        mock_crypto.get_or_create_dek.side_effect = RuntimeError("KEK invalid")
        with pytest.raises(RuntimeError, match="KEK invalid"):
            await use_case.execute("test", ORG_ID, REQUEST_ID)


class TestTokenizeCollisionExhaustion:
    """HMAC collision counter exhaustion after _MAX_COLLISION_ATTEMPTS."""

    async def test_collision_exhaustion_raises_runtime_error(
        self,
        use_case: TokenizeTextUseCase,
        mock_detection: AsyncMock,
        mock_crypto: MagicMock,
    ) -> None:
        """Seed existing_tokens with 50 different values all sharing the same base hash."""
        existing = {}
        for i in range(1, _MAX_COLLISION_ATTEMPTS + 1):
            suffix = f"a1b2_{i}" if i > 1 else "a1b2"
            existing[f"value_{i}"] = f"[#pe:{suffix}]"

        mock_detection.detect.return_value = DetectionResult(
            spans=[_make_span(0, 5, "brand_new_value", "pe")],
            detection_ms=1.0,
            source="regex",
        )
        mock_crypto.hmac_token_hash.return_value = "a1b2"

        with pytest.raises(RuntimeError, match="Exceeded.*collision attempts"):
            await use_case.execute("brand_new_value", ORG_ID, REQUEST_ID, existing_tokens=existing)
