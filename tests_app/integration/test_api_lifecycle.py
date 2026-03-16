"""
API lifecycle integration tests -- full E2E through FastAPI with fakeredis.

Adversarial Analysis:
  1. Invalid UUID must produce 422, NOT echo the invalid value.
  2. Empty texts list must produce 422.
  3. Batch tokenize with shared PII must produce same token across texts.
"""
from __future__ import annotations

import base64
import hashlib
import os

# Set env var BEFORE any app import to avoid module-level Settings() failure
_KEK_RAW = b"\x01" * 32
_KEK_B64 = base64.b64encode(_KEK_RAW).decode("ascii")
os.environ.setdefault("PRIVACY_SHIELD_KEK_BASE64", _KEK_B64)

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.container import Container
from app.infrastructure.config import Settings
from app.main import create_app


VALID_ORG_ID = "00000000-0000-0000-0000-000000000001"
VALID_REQ_ID = "00000000-0000-0000-0000-000000000099"
ADMIN_SECRET = "test-admin-key-lifecycle"


@pytest.fixture
def test_settings() -> Settings:
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=_KEK_B64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="WARNING",
        APP_VERSION="0.0.0-test",
        ADMIN_API_KEY=ADMIN_SECRET,
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncClient:
    """Create a test client with fakeredis injected into the container."""
    app = create_app(settings=test_settings)

    fake_redis = fakeredis.aioredis.FakeRedis(decode_responses=False)

    container = Container(config=test_settings)
    container._redis = fake_redis
    _ = container.crypto_port
    app.state.container = container

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # Create an API key for the test org and store on the client
        resp = await ac.post(
            "/api/v1/keys",
            headers={"X-Admin-Key": ADMIN_SECRET},
            json={"organization_id": VALID_ORG_ID},
        )
        assert resp.status_code == 200
        ac.headers["X-Api-Key"] = resp.json()["key"]
        yield ac

    await fake_redis.aclose()


class TestTokenizeEndpoint:
    """POST /api/v1/tokenize."""

    async def test_tokenize_italian_text_with_cf(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["Il codice fiscale di Mario e' RSSMRA85M01H501Z"],
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tokenized_texts"]) == 1
        assert "[#cf:" in data["tokenized_texts"][0]
        assert "RSSMRA85M01H501Z" not in data["tokenized_texts"][0]
        assert len(data["tokens"]) >= 1
        assert data["detection_ms"] >= 0
        assert data["tokenization_ms"] >= 0

    async def test_batch_tokenize_shared_pii(self, client: AsyncClient) -> None:
        """3 texts with same email: same token across texts."""
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": [
                    "Email: mario@test.com",
                    "Scrivi a mario@test.com",
                    "Conferma mario@test.com",
                ],
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tokenized_texts"]) == 3

        tokens = data["tokens"]
        email_tokens = [t for t in tokens if t["type"] == "em"]
        assert len(email_tokens) >= 1
        first_email_token = email_tokens[0]["token"]
        for text in data["tokenized_texts"]:
            assert first_email_token in text


class TestTokenizeValidation:
    """Validation error cases."""

    async def test_empty_texts_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": [],
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 422

    async def test_invalid_org_uuid_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["test"],
                "organization_id": "not-a-uuid",
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 422
        data = resp.json()
        # Must NOT echo the invalid value back
        assert "not-a-uuid" not in str(data)

    async def test_missing_org_id_returns_422(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["test"],
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 422


class TestRehydrateEndpoint:
    """POST /api/v1/rehydrate."""

    async def test_tokenize_then_rehydrate_roundtrip(self, client: AsyncClient) -> None:
        tok_resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["Chiama mario@test.com per info"],
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert tok_resp.status_code == 200
        tokenized_text = tok_resp.json()["tokenized_texts"][0]

        reh_resp = await client.post(
            "/api/v1/rehydrate",
            json={
                "text": tokenized_text,
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert reh_resp.status_code == 200
        data = reh_resp.json()
        assert "mario@test.com" in data["text"]
        assert data["rehydrated_count"] >= 1

    async def test_rehydrate_no_tokens(self, client: AsyncClient) -> None:
        resp = await client.post(
            "/api/v1/rehydrate",
            json={
                "text": "Testo senza token",
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "Testo senza token"
        assert data["rehydrated_count"] == 0


class TestFlushEndpoint:
    """POST /api/v1/flush."""

    async def test_tokenize_flush_rehydrate_lifecycle(self, client: AsyncClient) -> None:
        tok_resp = await client.post(
            "/api/v1/tokenize",
            json={
                "texts": ["Email: mario@test.com"],
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert tok_resp.status_code == 200
        tokenized_text = tok_resp.json()["tokenized_texts"][0]

        flush_resp = await client.post(
            "/api/v1/flush",
            json={
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert flush_resp.status_code == 200
        assert flush_resp.json()["flushed_count"] >= 1

        reh_resp = await client.post(
            "/api/v1/rehydrate",
            json={
                "text": tokenized_text,
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert reh_resp.status_code == 200
        data = reh_resp.json()
        assert data["rehydrated_count"] == 0
        assert "[#em:" in data["text"]

    async def test_flush_idempotent(self, client: AsyncClient) -> None:
        flush_resp1 = await client.post(
            "/api/v1/flush",
            json={
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        flush_resp2 = await client.post(
            "/api/v1/flush",
            json={
                "organization_id": VALID_ORG_ID,
                "request_id": VALID_REQ_ID,
            },
        )
        assert flush_resp1.status_code == 200
        assert flush_resp2.status_code == 200
        assert flush_resp2.json()["flushed_count"] == 0
