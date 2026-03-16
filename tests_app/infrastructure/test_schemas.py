"""
Pydantic schema validation tests.

Adversarial Analysis:
  1. Invalid UUID must be rejected without echoing the value (PII leak vector).
  2. Empty texts list must be rejected.
  3. Valid requests must pass without error.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.infrastructure.api.schemas import (
    ErrorResponse,
    FlushRequest,
    FlushResponse,
    HealthResponse,
    RehydrateRequest,
    RehydrateResponse,
    TokenInfo,
    TokenizeRequest,
    TokenizeResponse,
)


VALID_UUID = "00000000-0000-0000-0000-000000000001"


class TestTokenizeRequest:
    """TokenizeRequest validation."""

    def test_valid_request(self) -> None:
        req = TokenizeRequest(
            texts=["Ciao Mario"],
            organization_id=VALID_UUID,
            request_id=VALID_UUID,
        )
        assert len(req.texts) == 1

    def test_empty_texts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TokenizeRequest(
                texts=[],
                organization_id=VALID_UUID,
                request_id=VALID_UUID,
            )

    def test_invalid_org_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            TokenizeRequest(
                texts=["test"],
                organization_id="not-a-uuid",
                request_id=VALID_UUID,
            )
        # Verify the invalid value is NOT echoed in the error
        error_str = str(exc_info.value)
        assert "not-a-uuid" not in error_str or "must be a valid UUID" in error_str

    def test_invalid_request_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TokenizeRequest(
                texts=["test"],
                organization_id=VALID_UUID,
                request_id="bad",
            )

    def test_existing_tokens_default_empty(self) -> None:
        req = TokenizeRequest(
            texts=["test"],
            organization_id=VALID_UUID,
            request_id=VALID_UUID,
        )
        assert req.existing_tokens == {}

    def test_existing_tokens_provided(self) -> None:
        req = TokenizeRequest(
            texts=["test"],
            organization_id=VALID_UUID,
            request_id=VALID_UUID,
            existing_tokens={"Mario": "[#pe:a3f2]"},
        )
        assert req.existing_tokens == {"Mario": "[#pe:a3f2]"}


class TestRehydrateRequest:
    """RehydrateRequest validation."""

    def test_valid_request(self) -> None:
        req = RehydrateRequest(
            text="Ciao [#pe:a3f2]",
            organization_id=VALID_UUID,
            request_id=VALID_UUID,
        )
        assert req.text == "Ciao [#pe:a3f2]"

    def test_invalid_org_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            RehydrateRequest(
                text="test",
                organization_id="invalid",
                request_id=VALID_UUID,
            )


class TestFlushRequest:
    """FlushRequest validation."""

    def test_valid_request(self) -> None:
        req = FlushRequest(
            organization_id=VALID_UUID,
            request_id=VALID_UUID,
        )
        assert req.organization_id == VALID_UUID

    def test_invalid_org_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlushRequest(
                organization_id="not-uuid",
                request_id=VALID_UUID,
            )

    def test_invalid_request_uuid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            FlushRequest(
                organization_id=VALID_UUID,
                request_id="not-uuid",
            )


class TestResponseSchemas:
    """Response schemas can be constructed with expected fields."""

    def test_tokenize_response(self) -> None:
        resp = TokenizeResponse(
            tokenized_texts=["[#pe:a3f2] ha chiamato"],
            tokens=[
                TokenInfo(
                    original="Mario",
                    token="[#pe:a3f2]",
                    type="pe",
                    start=0,
                    end=5,
                    source="regex",
                )
            ],
            detection_ms=1.0,
            tokenization_ms=2.0,
        )
        assert len(resp.tokens) == 1

    def test_rehydrate_response(self) -> None:
        resp = RehydrateResponse(text="Mario ha chiamato", rehydrated_count=1)
        assert resp.rehydrated_count == 1

    def test_flush_response(self) -> None:
        resp = FlushResponse(flushed_count=3)
        assert resp.flushed_count == 3

    def test_health_response(self) -> None:
        # T4.5: HealthResponse now uses structured per-component format.
        from app.infrastructure.api.schemas import ComponentStatus, HealthComponents
        components = HealthComponents(
            redis=ComponentStatus(status="up", latency_ms=1.2),
            crypto=ComponentStatus(status="up", kek_valid=True),
            slm=ComponentStatus(status="not_configured"),
        )
        resp = HealthResponse(status="healthy", components=components, version="1.0.0")
        assert resp.status == "healthy"
        assert resp.components.redis.status == "up"
        assert resp.components.crypto.kek_valid is True
        assert resp.components.slm.status == "not_configured"

    def test_error_response(self) -> None:
        resp = ErrorResponse(error="bad", code="ERR", detail=None)
        assert resp.detail is None

    def test_error_response_with_detail(self) -> None:
        resp = ErrorResponse(error="bad", code="ERR", detail="more info")
        assert resp.detail == "more info"
