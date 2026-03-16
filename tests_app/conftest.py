"""
Shared fixtures for the Privacy Shield test suite.

All async fixtures use pytest-asyncio's auto mode (configured in pyproject.toml).
"""
from __future__ import annotations

import base64
import os
from unittest.mock import AsyncMock, MagicMock

import fakeredis.aioredis
import pytest

from app.domain.ports.crypto_port import CryptoPort
from app.domain.ports.detection_port import DetectionPort
from app.domain.ports.vault_port import VaultPort
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
from app.infrastructure.config import Settings


# ------------------------------------------------------------------
# Crypto primitives
# ------------------------------------------------------------------


@pytest.fixture
def fake_kek() -> bytes:
    """Return a deterministic 32-byte KEK for testing."""
    return b"\x01" * 32


@pytest.fixture
def fake_kek_base64(fake_kek: bytes) -> str:
    """Return the fake KEK as base64 for Settings construction."""
    return base64.b64encode(fake_kek).decode("ascii")


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------


@pytest.fixture
def fake_settings(fake_kek_base64: str) -> Settings:
    """Return a Settings object with test-friendly defaults (no env vars needed)."""
    return Settings(
        PRIVACY_SHIELD_KEK_BASE64=fake_kek_base64,
        REDIS_URL="redis://localhost:6379",
        TOKEN_TTL_SECONDS=60,
        HOST="127.0.0.1",
        PORT=9999,
        LOG_LEVEL="DEBUG",
        APP_VERSION="0.0.0-test",
    )


# ------------------------------------------------------------------
# Mocked Ports
# ------------------------------------------------------------------


@pytest.fixture
def mock_vault() -> AsyncMock:
    """Return an AsyncMock implementing VaultPort's interface."""
    vault = AsyncMock(spec=VaultPort)
    vault.store = AsyncMock(return_value=None)
    vault.retrieve = AsyncMock(return_value=None)
    vault.retrieve_batch = AsyncMock(return_value={})
    vault.register_request_token = AsyncMock(return_value=None)
    vault.flush_request = AsyncMock(return_value=0)
    vault.store_dek = AsyncMock(return_value=None)
    vault.retrieve_dek = AsyncMock(return_value=None)
    # T4.3: new VaultPort methods — set_dek_if_absent returns the ARGV[1] bytes
    # (the candidate DEK passed to it) to simulate "first writer wins" behaviour.
    vault.set_dek_if_absent = AsyncMock(side_effect=lambda org_id, enc_dek: enc_dek)
    vault.scan_active_token_hashes = AsyncMock(return_value=[])
    vault.get_token_ttl = AsyncMock(return_value=30)
    vault.count_org_tokens = AsyncMock(return_value=0)
    return vault


@pytest.fixture
def mock_crypto() -> MagicMock:
    """Return a MagicMock implementing CryptoPort's interface.

    Sync methods use MagicMock; get_or_create_dek is async.
    """
    crypto = MagicMock(spec=CryptoPort)
    # Sync methods
    crypto.encrypt = MagicMock(return_value=b"encrypted_data")
    crypto.decrypt = MagicMock(return_value="decrypted_value")
    crypto.hmac_token_hash = MagicMock(return_value="a1b2")
    crypto.encrypt_dek = MagicMock(return_value=b"wrapped_dek")
    crypto.decrypt_dek = MagicMock(return_value=b"\x02" * 32)
    # Async methods
    crypto.get_or_create_dek = AsyncMock(return_value=b"\x02" * 32)
    return crypto


@pytest.fixture
def mock_detection() -> AsyncMock:
    """Return an AsyncMock implementing DetectionPort's interface."""
    from app.domain.entities import DetectionResult

    detection = AsyncMock(spec=DetectionPort)
    detection.detect = AsyncMock(
        return_value=DetectionResult(spans=[], detection_ms=0.5, source="regex")
    )
    return detection


# ------------------------------------------------------------------
# fakeredis
# ------------------------------------------------------------------


@pytest.fixture
async def fake_redis() -> fakeredis.aioredis.FakeRedis:
    """Return a fresh fakeredis async client (isolated per test)."""
    client = fakeredis.aioredis.FakeRedis(decode_responses=False)
    yield client
    await client.aclose()


# ------------------------------------------------------------------
# Wired Container (with fakeredis)
# ------------------------------------------------------------------


@pytest.fixture
async def wired_vault(fake_redis: fakeredis.aioredis.FakeRedis) -> RedisVaultAdapter:
    """Return a RedisVaultAdapter wired to fakeredis."""
    return RedisVaultAdapter(redis_client=fake_redis)


@pytest.fixture
def wired_crypto(fake_kek: bytes, wired_vault: RedisVaultAdapter) -> AesCryptoAdapter:
    """Return an AesCryptoAdapter wired to the test vault."""
    return AesCryptoAdapter(kek=fake_kek, vault=wired_vault)


@pytest.fixture
def wired_detection() -> RegexDetectionAdapter:
    """Return the real RegexDetectionAdapter."""
    return RegexDetectionAdapter()
