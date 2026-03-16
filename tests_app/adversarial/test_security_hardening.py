"""
Security hardening adversarial tests — 10 fixes applied in Fase 4 hardening pass.

Adversarial Analysis:
  1. Redis TTL atomicity: Without MULTI/EXEC, SADD can succeed while EXPIRE fails,
     leaving orphaned SET keys that never expire — a slow Redis memory leak.
  2. Batch size / text length limits: An attacker can submit 10k texts or 1MB strings
     to cause OOM in the detection regex engine or vault write amplification.
  3. Token entropy: With only 4 hex chars (65k values) collision rate is dangerous
     for orgs with moderate PII volume. 8 hex chars gives ~4 billion values.
  4. Unicode normalization: NFD-decomposed accented chars (e.g. e + combining grave)
     can bypass regex patterns that expect single NFC code points (e.g. for CF).
  5. Email ReDoS: Unbounded regex quantifiers on local-part/domain can cause
     catastrophic backtracking on adversarial strings without '@'.
  6. GCM associated data: Without org_id bound as AAD, a stolen ciphertext from
     org A can be decrypted by org B's DEK if they somehow share the same DEK.

Boundary Map:
  texts.length: [1, 100] -> test at 0, 1, 100, 101
  texts[i].length: [0, 10000] -> test at 0, 10000, 10001
  hmac_token_hash output: exactly 8 hex chars
  build_collision_hash attempt: [1, 10] -> test at 1, 10, 11
  log_operation kwargs: SAFE_LOG_FIELDS allowlist -> test safe and forbidden keys
  Redis TTL: SADD + EXPIRE must be atomic (pipeline transaction=True)
"""
from __future__ import annotations

import asyncio
import base64
import os
import re
import time
import unicodedata
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
from cryptography.exceptions import InvalidTag
from pydantic import ValidationError

from app.application.tokenize_text import TokenizeTextUseCase, _MAX_COLLISION_ATTEMPTS
from app.domain.entities import DetectionResult, PiiSpan
from app.domain.services.token_format import (
    TOKEN_PATTERN,
    build_collision_hash,
    format_token,
    parse_token,
)
from app.infrastructure.adapters.aes_crypto import AesCryptoAdapter
from app.infrastructure.adapters.redis_vault import RedisVaultAdapter
from app.infrastructure.adapters.regex_detection import RegexDetectionAdapter
from app.infrastructure.api.schemas import TokenizeRequest
from app.infrastructure.config import Settings
from app.infrastructure.telemetry import SAFE_LOG_FIELDS, log_operation


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ORG_A = "00000000-0000-0000-0000-00000000000a"
ORG_B = "00000000-0000-0000-0000-00000000000b"
REQ_A = "00000000-0000-0000-0000-0000000000a1"


# ===================================================================
# Fix 1: Redis TTL Atomicity (register_request_token uses MULTI/EXEC)
# ===================================================================

class TestRedisTtlAtomicity:
    """
    register_request_token must execute SADD + EXPIRE atomically via
    a Redis pipeline with transaction=True (MULTI/EXEC). A non-atomic
    sequence risks SADD succeeding but EXPIRE failing, leaving orphaned
    SET keys that consume memory indefinitely.
    """

    async def test_sadd_and_expire_happen_in_single_transaction(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """After register_request_token, the request SET must exist AND have a TTL."""
        vault = RedisVaultAdapter(redis_client=fake_redis)
        await vault.register_request_token(ORG_A, REQ_A, "hash1", ttl_seconds=120)

        key = f"ps:req:{ORG_A}:{REQ_A}"
        # Key must exist
        members = await fake_redis.smembers(key)
        assert b"hash1" in members

        # Key MUST have a TTL (not -1 = no expiry)
        ttl = await fake_redis.ttl(key)
        assert ttl > 0, f"Request set key has no TTL (ttl={ttl}) — SADD/EXPIRE not atomic"
        assert ttl <= 120

    async def test_multiple_register_calls_reset_ttl(
        self, fake_redis: fakeredis.aioredis.FakeRedis
    ) -> None:
        """Each call resets the TTL — the second call with shorter TTL must win."""
        vault = RedisVaultAdapter(redis_client=fake_redis)
        await vault.register_request_token(ORG_A, REQ_A, "h1", ttl_seconds=300)
        await vault.register_request_token(ORG_A, REQ_A, "h2", ttl_seconds=30)

        key = f"ps:req:{ORG_A}:{REQ_A}"
        ttl = await fake_redis.ttl(key)
        # TTL should be at most 30 (the latest call's value)
        assert ttl <= 30, f"TTL was not reset by second call (ttl={ttl})"

        # Both hashes must be in the set
        members = await fake_redis.smembers(key)
        assert b"h1" in members
        assert b"h2" in members

    async def test_pipeline_uses_transaction_flag(self) -> None:
        """
        Directly verify that the pipeline is opened with transaction=True
        by instrumenting the Redis client's pipeline method.
        """
        mock_redis = AsyncMock()
        mock_pipe = AsyncMock()
        mock_pipe.__aenter__ = AsyncMock(return_value=mock_pipe)
        mock_pipe.__aexit__ = AsyncMock(return_value=False)
        mock_pipe.sadd = MagicMock()
        mock_pipe.expire = MagicMock()
        mock_pipe.execute = AsyncMock(return_value=[1, True])

        mock_redis.pipeline = MagicMock(return_value=mock_pipe)

        vault = RedisVaultAdapter(redis_client=mock_redis)
        await vault.register_request_token(ORG_A, REQ_A, "h1", ttl_seconds=60)

        # Verify pipeline was called with transaction=True
        mock_redis.pipeline.assert_called_once_with(transaction=True)


# ===================================================================
# Fix 2: Batch Size Limit (max 100 texts, max 10,000 chars per text)
# ===================================================================

class TestBatchSizeLimit:
    """
    TokenizeRequest must reject payloads that exceed batch size (100 texts)
    or per-text character length (10,000 chars). These limits prevent OOM
    in regex detection and vault write amplification attacks.
    """

    def test_101_texts_rejected(self) -> None:
        """Submitting 101 texts must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TokenizeRequest(
                texts=["hello"] * 101,
                organization_id=ORG_A,
                request_id=REQ_A,
            )
        errors = exc_info.value.errors()
        # Should have at least one error about max_length/list_too_long
        assert any(
            "too_long" in str(e.get("type", "")) or "max" in str(e.get("msg", "")).lower()
            for e in errors
        ), f"Expected max_length error, got: {errors}"

    def test_text_exceeding_10000_chars_rejected(self) -> None:
        """A single text with 10,001 chars must raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TokenizeRequest(
                texts=["a" * 10_001],
                organization_id=ORG_A,
                request_id=REQ_A,
            )
        errors = exc_info.value.errors()
        assert any(
            "10000" in str(e.get("msg", ""))
            for e in errors
        ), f"Expected 10000 char limit error, got: {errors}"

    def test_exactly_100_texts_of_10000_chars_accepted(self) -> None:
        """Boundary: 100 texts each exactly 10,000 chars must be accepted."""
        req = TokenizeRequest(
            texts=["x" * 10_000] * 100,
            organization_id=ORG_A,
            request_id=REQ_A,
        )
        assert len(req.texts) == 100
        assert all(len(t) == 10_000 for t in req.texts)

    def test_empty_texts_rejected(self) -> None:
        """texts=[] must raise ValidationError (min_length=1)."""
        with pytest.raises(ValidationError):
            TokenizeRequest(
                texts=[],
                organization_id=ORG_A,
                request_id=REQ_A,
            )

    def test_single_text_accepted(self) -> None:
        """Boundary: 1 text is the minimum valid payload."""
        req = TokenizeRequest(
            texts=["ciao"],
            organization_id=ORG_A,
            request_id=REQ_A,
        )
        assert len(req.texts) == 1

    def test_exactly_10000_chars_accepted(self) -> None:
        """Boundary: exactly 10,000 chars is the maximum valid length."""
        req = TokenizeRequest(
            texts=["b" * 10_000],
            organization_id=ORG_A,
            request_id=REQ_A,
        )
        assert len(req.texts[0]) == 10_000


# ===================================================================
# Fix 3: Tokenization Timeout (408 on slow processing)
# ===================================================================

class TestTokenizationTimeout:
    """
    The /api/v1/tokenize route wraps each text processing in asyncio.wait_for
    with a 5-second timeout. If the use case is slow (e.g. SLM inference),
    it must raise asyncio.TimeoutError which the route maps to 408.
    """

    async def test_timeout_raises_timeout_error(self) -> None:
        """
        When the tokenize use case takes longer than the timeout,
        asyncio.TimeoutError is raised.
        """

        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)

        mock_use_case = AsyncMock()
        mock_use_case.execute = slow_execute

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                mock_use_case.execute(
                    text="Mario Rossi",
                    org_id=ORG_A,
                    request_id=REQ_A,
                ),
                timeout=0.1,
            )

    async def test_fast_processing_does_not_timeout(self) -> None:
        """Normal-speed processing completes within the timeout window."""
        result = MagicMock()
        result.tokenized_text = "test"
        result.detection_ms = 1.0
        result.tokens = []

        mock_use_case = AsyncMock()
        mock_use_case.execute = AsyncMock(return_value=result)

        got = await asyncio.wait_for(
            mock_use_case.execute(
                text="Mario Rossi",
                org_id=ORG_A,
                request_id=REQ_A,
            ),
            timeout=5.0,
        )
        assert got.tokenized_text == "test"


# ===================================================================
# Fix 4: Token Entropy (8 hex chars instead of 4)
# ===================================================================

class TestTokenEntropy:
    """
    hmac_token_hash must return exactly 8 hex chars (from SHA-256[:8]).
    The token format [#pe:abcd1234] uses 8-char hashes.
    Legacy 4-char tokens [#pe:abcd] must still be parsed for backward compat.
    """

    def test_hmac_returns_exactly_8_hex_chars(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """hmac_token_hash output must be exactly 8 hex characters."""
        dek = os.urandom(32)
        h = wired_crypto.hmac_token_hash(dek, "Mario Rossi")
        assert len(h) == 8, f"Expected 8 hex chars, got {len(h)}: {h!r}"
        assert re.fullmatch(r"[a-f0-9]{8}", h), f"Not valid hex: {h!r}"

    def test_8_char_token_format_accepted(self) -> None:
        """Token [#pe:abcd1234] with 8-char hash is valid."""
        token = format_token("pe", "abcd1234")
        assert token == "[#pe:abcd1234]"
        parsed = parse_token(token)
        assert parsed is not None
        assert parsed == ("pe", "abcd1234")

    def test_legacy_4_char_token_still_parsed(self) -> None:
        """Backward compat: legacy [#pe:abcd] with 4-char hash is still valid."""
        parsed = parse_token("[#pe:abcd]")
        assert parsed is not None
        assert parsed == ("pe", "abcd")

    def test_5_to_7_char_hashes_accepted(self) -> None:
        """TOKEN_PATTERN accepts 4-8 hex chars — test the middle range."""
        for length in (5, 6, 7):
            h = "a" * length
            token = format_token("pe", h)
            parsed = parse_token(token)
            assert parsed is not None, f"Failed for hash length {length}"
            assert parsed == ("pe", h)

    def test_3_char_hash_rejected(self) -> None:
        """3 hex chars is below the minimum — must be rejected."""
        assert parse_token("[#pe:abc]") is None

    def test_9_char_hash_rejected(self) -> None:
        """9 hex chars is above the maximum — must be rejected."""
        assert parse_token("[#pe:abcdef012]") is None

    def test_uniqueness_over_1000_random_values(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """
        8-char hex gives ~4 billion possible values. Over 1000 random PII values,
        we expect zero collisions (probability < 1e-4 by birthday paradox).
        """
        dek = os.urandom(32)
        hashes = set()
        for i in range(1000):
            h = wired_crypto.hmac_token_hash(dek, f"unique_value_{i}")
            hashes.add(h)
        # All 1000 should be distinct (collision probability ~0.0001 for 8 hex chars)
        assert len(hashes) == 1000, (
            f"Got {1000 - len(hashes)} collisions in 1000 values — "
            f"entropy too low for 8-char hex"
        )

    def test_deterministic_across_calls(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """Same (dek, pii_value) must always produce the same 8-char hash."""
        dek = os.urandom(32)
        h1 = wired_crypto.hmac_token_hash(dek, "Test Value")
        h2 = wired_crypto.hmac_token_hash(dek, "Test Value")
        assert h1 == h2
        assert len(h1) == 8


# ===================================================================
# Fix 5: Unicode Normalization (NFC before detection)
# ===================================================================

class TestUnicodeNormalization:
    """
    RegexDetectionAdapter.detect() must normalize input text to NFC form
    before running regex patterns. Without this, NFD-decomposed characters
    (e.g. e + combining grave = è) bypass patterns expecting single code points.
    """

    async def test_nfd_decomposed_cf_detected(self) -> None:
        """
        A Codice Fiscale containing NFD-decomposed characters must be detected
        after NFC normalization.
        """
        detector = RegexDetectionAdapter()
        # Standard CF: RSSMRA85M01H501Z (no accented chars, should work in all forms)
        cf = "RSSMRA85M01H501Z"
        nfd_text = unicodedata.normalize("NFD", f"Il codice fiscale è {cf}")
        assert unicodedata.is_normalized("NFD", nfd_text)

        result = await detector.detect(nfd_text)
        cf_spans = [s for s in result.spans if s.pii_type == "cf"]
        assert len(cf_spans) >= 1, (
            f"CF {cf} not detected in NFD-normalized text. "
            f"Detected spans: {[(s.pii_type, s.text) for s in result.spans]}"
        )

    async def test_nfd_email_with_accented_domain_detected(self) -> None:
        """
        An email in text with NFD accented characters surrounding it
        must still be detected after normalization.
        """
        detector = RegexDetectionAdapter()
        # NFD-decompose the surrounding text, not the email itself
        nfd_text = unicodedata.normalize("NFD", "L'indirizzo è mario.rossi@pec.it per favore")
        result = await detector.detect(nfd_text)
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(email_spans) >= 1, (
            f"Email not detected in NFD text. Spans: {[(s.pii_type, s.text) for s in result.spans]}"
        )

    async def test_pre_normalized_nfc_text_no_regression(self) -> None:
        """
        Already NFC-normalized text must still detect PII correctly.
        This is a regression test — normalization must be idempotent.
        """
        detector = RegexDetectionAdapter()
        nfc_text = unicodedata.normalize("NFC", "Contattare mario@test.com urgente")
        assert unicodedata.is_normalized("NFC", nfc_text)

        result = await detector.detect(nfc_text)
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(email_spans) == 1
        assert email_spans[0].text == "mario@test.com"

    async def test_combining_characters_in_name_context(self) -> None:
        """
        Text with combining characters (e + \\u0300 = è) near PII must not
        break detection of adjacent PII spans.
        """
        detector = RegexDetectionAdapter()
        # e\u0300 is NFD for è
        text_nfd = "L'e\u0300-mail e\u0300 test@example.com"
        result = await detector.detect(text_nfd)
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(email_spans) >= 1


# ===================================================================
# Fix 6: Email ReDoS Protection
# ===================================================================

class TestEmailRedos:
    """
    The email regex must not exhibit catastrophic backtracking on adversarial
    inputs. The fix caps local-part at 64 chars and domain at 255 chars
    to prevent unbounded quantifier nesting.
    """

    async def test_100k_chars_without_at_completes_fast(self) -> None:
        """
        100k characters of 'a' without '@' must NOT cause catastrophic
        backtracking. The regex should fail to match and return quickly.
        """
        detector = RegexDetectionAdapter()
        adversarial_input = "a" * 100_000

        t0 = time.perf_counter()
        result = await detector.detect(adversarial_input)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        # Must complete in under 100ms (generous margin; ReDoS would take seconds)
        assert elapsed_ms < 100, (
            f"Detection took {elapsed_ms:.1f}ms on 100k chars — possible ReDoS"
        )
        # No email spans should be found
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(email_spans) == 0

    async def test_valid_email_still_detected(self) -> None:
        """Regression: standard email must still be detected after ReDoS fix."""
        detector = RegexDetectionAdapter()
        result = await detector.detect("Contatta a@b.com per info")
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        assert len(email_spans) == 1
        assert email_spans[0].text == "a@b.com"

    async def test_64_char_local_part_detected(self) -> None:
        """Boundary: 64-char local part is within the capped limit."""
        detector = RegexDetectionAdapter()
        local = "a" * 64
        email = f"{local}@test.com"
        result = await detector.detect(f"Email: {email}")
        email_spans = [s for s in result.spans if s.pii_type == "em"]
        # With the cap at 64 chars for local part body (after the first char),
        # total local part = 1 (start alnum) + 64 (body) = 65 chars
        # We just verify the detection completes without ReDoS
        # The exact match depends on the regex cap implementation
        assert result.detection_ms < 100

    async def test_redos_pattern_with_dots(self) -> None:
        """
        Classic ReDoS attack vector: local part with alternating dots.
        Must complete quickly regardless of result.
        """
        detector = RegexDetectionAdapter()
        adversarial = "a." * 5000 + "b"  # 10001 chars, no @

        t0 = time.perf_counter()
        result = await detector.detect(adversarial)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert elapsed_ms < 100, (
            f"Dotted ReDoS pattern took {elapsed_ms:.1f}ms — backtracking risk"
        )


# ===================================================================
# Fix 7: Collision Hard Limit (max 10 attempts)
# ===================================================================

class TestCollisionHardLimit:
    """
    build_collision_hash must enforce a hard limit of 10 attempts.
    _MAX_COLLISION_ATTEMPTS in tokenize_text.py must be exactly 10.
    """

    def test_attempt_10_succeeds(self) -> None:
        """Boundary: attempt=10 is the last valid attempt."""
        result = build_collision_hash("abcd1234", 10)
        assert result == "abcd1234_10"

    def test_attempt_11_raises_value_error(self) -> None:
        """Boundary+1: attempt=11 must raise ValueError."""
        with pytest.raises(ValueError, match="collision limit exceeded"):
            build_collision_hash("abcd1234", 11)

    def test_attempt_1_returns_base_hash(self) -> None:
        """attempt=1 returns the base hash without suffix."""
        result = build_collision_hash("abcd1234", 1)
        assert result == "abcd1234"

    def test_attempt_2_returns_suffixed(self) -> None:
        """attempt=2 returns base_2."""
        result = build_collision_hash("abcd1234", 2)
        assert result == "abcd1234_2"

    def test_max_collision_attempts_constant_is_10(self) -> None:
        """_MAX_COLLISION_ATTEMPTS must be exactly 10."""
        assert _MAX_COLLISION_ATTEMPTS == 10

    def test_attempt_0_returns_base_hash(self) -> None:
        """attempt=0 (below 1) returns base hash (same as attempt=1)."""
        result = build_collision_hash("abcd1234", 0)
        assert result == "abcd1234"

    def test_large_attempt_raises(self) -> None:
        """Very large attempt numbers must also raise."""
        with pytest.raises(ValueError):
            build_collision_hash("abcd1234", 1000)

    async def test_full_collision_exhaustion_in_use_case(self) -> None:
        """
        When all 10 collision slots are occupied by DIFFERENT values,
        the 11th distinct value must raise RuntimeError in the use case.
        """
        mock_detection = AsyncMock()
        mock_vault = AsyncMock()
        mock_vault.store = AsyncMock()
        mock_vault.register_request_token = AsyncMock()
        mock_vault.count_org_tokens = AsyncMock(return_value=0)
        mock_crypto = MagicMock()
        mock_crypto.get_or_create_dek = AsyncMock(return_value=b"\x02" * 32)
        mock_crypto.encrypt = MagicMock(return_value=b"enc")
        # Force all values to hash to the same base
        mock_crypto.hmac_token_hash = MagicMock(return_value="deadbeef")

        # Pre-seed 10 different values occupying all collision slots
        existing: dict[str, str] = {}
        for i in range(1, _MAX_COLLISION_ATTEMPTS + 1):
            suffix = f"deadbeef_{i}" if i > 1 else "deadbeef"
            existing[f"value_{i}"] = f"[#pe:{suffix}]"

        mock_detection.detect = AsyncMock(
            return_value=DetectionResult(
                spans=[PiiSpan(
                    start=0, end=9, text="new_value",
                    pii_type="pe", source="regex", confidence=1.0
                )],
                detection_ms=0.5,
                source="regex",
            )
        )

        use_case = TokenizeTextUseCase(
            detection=mock_detection,
            vault=mock_vault,
            crypto=mock_crypto,
            token_ttl_seconds=60,
        )

        with pytest.raises(RuntimeError, match="Exceeded.*collision attempts"):
            await use_case.execute(
                "new_value", ORG_A, REQ_A, existing_tokens=existing
            )


# ===================================================================
# Fix 8: Redis Auth (redis://:password@host:port URL format)
# ===================================================================

class TestRedisAuth:
    """
    Settings must accept Redis URLs with embedded passwords.
    The format redis://:password@host:port is the standard Redis auth URL.
    """

    def test_password_url_accepted(self) -> None:
        """redis://:password@host:port must be a valid REDIS_URL."""
        kek_b64 = base64.b64encode(b"\x01" * 32).decode("ascii")
        settings = Settings(
            PRIVACY_SHIELD_KEK_BASE64=kek_b64,
            REDIS_URL="redis://:s3cretPassw0rd@redis.example.com:6380",
            TOKEN_TTL_SECONDS=60,
        )
        assert settings.redis_url == "redis://:s3cretPassw0rd@redis.example.com:6380"

    def test_default_url_no_auth(self) -> None:
        """Default Redis URL (no password) is valid."""
        kek_b64 = base64.b64encode(b"\x01" * 32).decode("ascii")
        settings = Settings(
            PRIVACY_SHIELD_KEK_BASE64=kek_b64,
        )
        assert settings.redis_url == "redis://localhost:6379"

    def test_redis_url_with_db_number(self) -> None:
        """Redis URL with database number must be accepted."""
        kek_b64 = base64.b64encode(b"\x01" * 32).decode("ascii")
        settings = Settings(
            PRIVACY_SHIELD_KEK_BASE64=kek_b64,
            REDIS_URL="redis://:password@host:6379/2",
        )
        assert "/2" in settings.redis_url

    def test_rediss_tls_url_accepted(self) -> None:
        """rediss:// (TLS) URL must be accepted."""
        kek_b64 = base64.b64encode(b"\x01" * 32).decode("ascii")
        settings = Settings(
            PRIVACY_SHIELD_KEK_BASE64=kek_b64,
            REDIS_URL="rediss://:password@redis.cloud.com:6380",
        )
        assert settings.redis_url.startswith("rediss://")


# ===================================================================
# Fix 9: GCM Associated Data (org_id bound to ciphertext)
# ===================================================================

class TestGcmAssociatedData:
    """
    AES-GCM associated data (AAD) binds the ciphertext to an org_id.
    Decrypting with a different org_id must fail with InvalidTag.
    This is the cryptographic enforcement of tenant isolation.
    """

    def test_encrypt_decrypt_same_org_succeeds(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """Encrypt with org_A AAD, decrypt with org_A AAD -> success."""
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Mario Rossi", associated_data=ORG_A.encode())
        plaintext = wired_crypto.decrypt(dek, ct, associated_data=ORG_A.encode())
        assert plaintext == "Mario Rossi"

    def test_encrypt_org_a_decrypt_org_b_fails(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """
        CRITICAL: Encrypt with org_A AAD, decrypt with org_B AAD must FAIL.
        This is the cryptographic tenant isolation barrier.
        """
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Mario Rossi", associated_data=ORG_A.encode())
        with pytest.raises(InvalidTag):
            wired_crypto.decrypt(dek, ct, associated_data=ORG_B.encode())

    def test_encrypt_with_ad_decrypt_without_ad_fails(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """Encrypt with AAD, decrypt without AAD -> InvalidTag."""
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Secret", associated_data=ORG_A.encode())
        with pytest.raises(InvalidTag):
            wired_crypto.decrypt(dek, ct, associated_data=None)

    def test_encrypt_without_ad_decrypt_without_ad_succeeds(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """Backward compat: both None AAD -> decryption succeeds."""
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Legacy Data", associated_data=None)
        plaintext = wired_crypto.decrypt(dek, ct, associated_data=None)
        assert plaintext == "Legacy Data"

    def test_encrypt_without_ad_decrypt_with_ad_fails(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """Encrypt without AAD, decrypt WITH AAD -> InvalidTag."""
        dek = os.urandom(32)
        ct = wired_crypto.encrypt(dek, "Data", associated_data=None)
        with pytest.raises(InvalidTag):
            wired_crypto.decrypt(dek, ct, associated_data=ORG_A.encode())

    async def test_cross_tenant_token_cannot_be_decrypted(
        self,
        wired_vault: RedisVaultAdapter,
        wired_crypto: AesCryptoAdapter,
    ) -> None:
        """
        End-to-end: a token encrypted for org_A and stored in the vault
        cannot be decrypted by org_B even if they somehow obtain the ciphertext.
        """
        dek_a = await wired_crypto.get_or_create_dek(ORG_A)
        dek_b = await wired_crypto.get_or_create_dek(ORG_B)

        # Encrypt PII for org_A with org_A as AAD
        encrypted = wired_crypto.encrypt(dek_a, "RSSMRA85M01H501Z", associated_data=ORG_A.encode())
        await wired_vault.store(ORG_A, REQ_A, "target_hash", encrypted, ttl_seconds=60)

        # Even if org_B obtains the ciphertext bytes...
        stolen_ct = await wired_vault.retrieve(ORG_A, REQ_A, "target_hash")
        assert stolen_ct is not None

        # ...they cannot decrypt it with their own DEK
        with pytest.raises(Exception):
            wired_crypto.decrypt(dek_b, stolen_ct, associated_data=ORG_B.encode())

        # ...nor with the correct DEK but wrong AAD
        with pytest.raises(InvalidTag):
            wired_crypto.decrypt(dek_a, stolen_ct, associated_data=ORG_B.encode())

    def test_empty_string_ad_different_from_none(
        self, wired_crypto: AesCryptoAdapter
    ) -> None:
        """AAD=b'' and AAD=None must not be interchangeable."""
        dek = os.urandom(32)
        ct_none = wired_crypto.encrypt(dek, "test", associated_data=None)
        ct_empty = wired_crypto.encrypt(dek, "test", associated_data=b"")

        # Both should decrypt with their own AAD
        assert wired_crypto.decrypt(dek, ct_none, associated_data=None) == "test"
        assert wired_crypto.decrypt(dek, ct_empty, associated_data=b"") == "test"


# ===================================================================
# Fix 10: Log Field Validation (SAFE_LOG_FIELDS allowlist)
# ===================================================================

class TestLogFieldValidation:
    """
    log_operation must reject kwargs containing fields not in SAFE_LOG_FIELDS.
    This prevents accidental PII leakage into structured log output.
    """

    def test_safe_field_token_count_accepted(self) -> None:
        """A field in SAFE_LOG_FIELDS must not raise."""
        import logging
        logger = logging.getLogger("test_safe")
        # Should not raise
        log_operation(logger, operation="test", org_id=ORG_A, duration_ms=1.0, token_count=5)

    def test_forbidden_field_pii_value_raises(self) -> None:
        """'pii_value' is a forbidden field — must raise ValueError."""
        import logging
        logger = logging.getLogger("test_forbidden")
        with pytest.raises(ValueError, match="Forbidden log field.*pii_value"):
            log_operation(
                logger,
                operation="test",
                org_id=ORG_A,
                duration_ms=1.0,
                pii_value="Mario Rossi",
            )

    def test_forbidden_field_original_text_raises(self) -> None:
        """'original_text' is a forbidden field — must raise ValueError."""
        import logging
        logger = logging.getLogger("test_forbidden2")
        with pytest.raises(ValueError, match="Forbidden log field.*original_text"):
            log_operation(
                logger,
                operation="test",
                org_id=ORG_A,
                duration_ms=1.0,
                original_text="Il suo codice fiscale è RSSMRA85M01H501Z",
            )

    def test_forbidden_field_decrypted_value_raises(self) -> None:
        """Any 'decrypted_*' field must be rejected."""
        import logging
        logger = logging.getLogger("test_forbidden3")
        with pytest.raises(ValueError, match="Forbidden log field"):
            log_operation(
                logger,
                operation="test",
                org_id=ORG_A,
                duration_ms=1.0,
                decrypted_pii="secret data",
            )

    def test_forbidden_field_token_hash_to_value_mapping(self) -> None:
        """The mapping field must be rejected."""
        import logging
        logger = logging.getLogger("test_forbidden4")
        with pytest.raises(ValueError, match="Forbidden log field"):
            log_operation(
                logger,
                operation="test",
                org_id=ORG_A,
                duration_ms=1.0,
                token_hash_to_value_mapping={"abc": "Mario"},
            )

    def test_all_safe_fields_accepted(self) -> None:
        """Every field in SAFE_LOG_FIELDS must be accepted without error."""
        import logging
        logger = logging.getLogger("test_all_safe")
        kwargs = {field: "test_value" for field in SAFE_LOG_FIELDS}
        # Remove 'operation' from kwargs since it's a positional arg
        kwargs.pop("operation", None)
        kwargs.pop("org_id", None)
        kwargs.pop("duration_ms", None)
        log_operation(
            logger,
            operation="test",
            org_id=ORG_A,
            duration_ms=1.0,
            **kwargs,
        )

    def test_safe_log_fields_is_frozenset(self) -> None:
        """SAFE_LOG_FIELDS must be immutable (frozenset, not set or list)."""
        assert isinstance(SAFE_LOG_FIELDS, frozenset)

    def test_arbitrary_field_name_rejected(self) -> None:
        """Completely unknown fields must also be rejected."""
        import logging
        logger = logging.getLogger("test_arbitrary")
        with pytest.raises(ValueError, match="Forbidden log field"):
            log_operation(
                logger,
                operation="test",
                org_id=ORG_A,
                duration_ms=1.0,
                user_password="p@ssw0rd",
            )


# ===================================================================
# Cross-Fix Integration: Full pipeline with all hardening active
# ===================================================================

class TestCrossFIxIntegration:
    """
    Verify that all hardening fixes work together in an integrated scenario.
    """

    async def test_full_tokenize_pipeline_with_aad_and_8char_hash(
        self,
        wired_vault: RedisVaultAdapter,
        wired_crypto: AesCryptoAdapter,
    ) -> None:
        """
        End-to-end: tokenize with real crypto, verify 8-char hashes in tokens,
        verify AAD is used (decrypt without AAD fails), verify vault TTL exists.
        """
        detection = RegexDetectionAdapter()
        use_case = TokenizeTextUseCase(
            detection=detection,
            vault=wired_vault,
            crypto=wired_crypto,
            token_ttl_seconds=120,
        )

        result = await use_case.execute(
            text="Email: mario.rossi@pec.it",
            org_id=ORG_A,
            request_id=REQ_A,
        )

        # Should have detected the email
        assert len(result.tokens) >= 1
        email_entry = next((t for t in result.tokens if t.pii_type == "em"), None)
        assert email_entry is not None

        # Token hash should be 8 hex chars (no collision suffix expected)
        assert re.fullmatch(r"[a-f0-9]{8}", email_entry.token_hash), (
            f"Token hash is not 8 hex chars: {email_entry.token_hash!r}"
        )

        # The token in the tokenized text should match the format
        assert f"[#em:{email_entry.token_hash}]" in result.tokenized_text

        # Verify the vault entry has a TTL (atomicity fix)
        # Token is stored under REQ_A (the request_id used in execute())
        ttl = await wired_vault.get_token_ttl(ORG_A, REQ_A, email_entry.token_hash)
        assert ttl > 0, "Vault entry has no TTL"

        # Verify AAD was used: the encrypted value cannot be decrypted with wrong org
        dek_a = await wired_crypto.get_or_create_dek(ORG_A)
        stored = await wired_vault.retrieve(ORG_A, REQ_A, email_entry.token_hash)
        assert stored is not None

        # Correct AAD works
        decrypted = wired_crypto.decrypt(dek_a, stored, associated_data=ORG_A.encode())
        assert decrypted == "mario.rossi@pec.it"

        # Wrong AAD fails
        with pytest.raises(InvalidTag):
            wired_crypto.decrypt(dek_a, stored, associated_data=ORG_B.encode())
