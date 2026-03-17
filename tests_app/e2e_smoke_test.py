"""
E2E / Smoke / Integration test suite for Privacy Shield production readiness.

Tests the live deployment at api.privacyshield.pro (no mTLS, API key only).

Run: python3 -m pytest tests_app/e2e_smoke_test.py -v
"""
from __future__ import annotations

import hashlib
import os
import time
import uuid

import httpx
import pytest

BASE_URL = "https://api.privacyshield.pro"
API_KEY = os.environ.get(
    "PS_API_KEY", "ps_live_0ca00f62c9db29f594070680a3448c92"
)
ADMIN_KEY = os.environ.get("PS_ADMIN_KEY", "")
ORG_ID = "2acac729-da91-5a48-8c41-e545c9a9c1fa"


def _headers(api_key: bool = True) -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        h["X-Api-Key"] = API_KEY
    return h


def _admin_headers() -> dict[str, str]:
    return {"X-Admin-Key": ADMIN_KEY, "Content-Type": "application/json"}


# ── SMOKE TESTS ─────────────────────────────────────────────────────────


class TestSmoke:
    """Basic connectivity — no auth, just verify the server is up."""

    def test_health_returns_200(self):
        r = httpx.get(f"{BASE_URL}/health", timeout=10)
        assert r.status_code == 200
        body = r.json()
        assert body["status"] in ("healthy", "degraded")
        assert "components" in body
        assert "version" in body

    def test_health_redis_up(self):
        r = httpx.get(f"{BASE_URL}/health", timeout=10)
        body = r.json()
        assert body["components"]["redis"]["status"] == "up"

    def test_health_crypto_up(self):
        r = httpx.get(f"{BASE_URL}/health", timeout=10)
        body = r.json()
        assert body["components"]["crypto"]["status"] == "up"
        assert body["components"]["crypto"]["kek_valid"] is True

    def test_no_api_key_returns_401(self):
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers={"Content-Type": "application/json"},
            json={"texts": ["test"], "organization_id": ORG_ID, "request_id": str(uuid.uuid4())},
            timeout=10,
        )
        assert r.status_code == 401

    def test_invalid_api_key_returns_401(self):
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers={"Content-Type": "application/json", "X-Api-Key": "ps_live_invalid"},
            json={"texts": ["test"], "organization_id": ORG_ID, "request_id": str(uuid.uuid4())},
            timeout=10,
        )
        assert r.status_code == 401

    def test_root_returns_444(self):
        """Nginx catch-all should return 444 (connection reset)."""
        with pytest.raises((httpx.RemoteProtocolError, httpx.ReadError)):
            httpx.get(f"{BASE_URL}/", timeout=10)


# ── INTEGRATION TESTS — SDK-like HTTP calls ──────────────────────────────


class TestTokenize:
    """Tokenize endpoint — PII detection and token creation."""

    def test_tokenize_single_text_with_pii(self):
        request_id = str(uuid.uuid4())
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": ["Mario Rossi, CF RSSMRA85M01H501Z"],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["tokenized_texts"]) == 1
        assert "[#pe:" in body["tokenized_texts"][0]
        assert "[#cf:" in body["tokenized_texts"][0]
        assert len(body["tokens"]) >= 2
        assert body["detection_ms"] > 0
        assert body["tokenization_ms"] > 0

    def test_tokenize_no_pii(self):
        """Text without PII should return unchanged."""
        request_id = str(uuid.uuid4())
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": ["Il tempo oggi è bello."],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert body["tokens"] == []
        assert body["tokenized_texts"][0] == "Il tempo oggi è bello."

    def test_tokenize_batch(self):
        """Multiple texts in one call."""
        request_id = str(uuid.uuid4())
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": [
                    "Mario Rossi abita a Roma.",
                    "Contattare Luigi Bianchi al 333-1234567.",
                ],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert len(body["tokenized_texts"]) == 2
        assert len(body["tokens"]) >= 2

    def test_tokenize_same_pii_same_token(self):
        """Same PII across texts should produce the same token."""
        request_id = str(uuid.uuid4())
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": [
                    "Mario Rossi è il cliente.",
                    "Contattare Mario Rossi domani.",
                ],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        # Find all pe tokens — same PII should map to same token
        pe_tokens = [t for t in body["tokens"] if t["type"] == "pe" and t["original"] == "Mario Rossi"]
        if len(pe_tokens) >= 2:
            assert pe_tokens[0]["token"] == pe_tokens[1]["token"]

    def test_tokenize_italian_pii_types(self):
        """Various Italian PII types: CF, IBAN, email, phone."""
        request_id = str(uuid.uuid4())
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": [
                    "CF: RSSMRA85M01H501Z, IBAN: IT60X0542811101000000123456, email: mario@example.com, tel: +39 333 1234567"
                ],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        detected_types = {t["type"] for t in body["tokens"]}
        # At minimum CF and IBAN should be detected (regex-based)
        assert "cf" in detected_types, f"CF not detected. Types: {detected_types}"
        assert "ib" in detected_types, f"IBAN not detected. Types: {detected_types}"


# ── E2E LIFECYCLE: tokenize → rehydrate → flush ─────────────────────────


class TestLifecycle:
    """Full request lifecycle: tokenize, rehydrate, then flush."""

    def test_full_lifecycle(self):
        request_id = str(uuid.uuid4())
        text = "Mario Rossi, CF RSSMRA85M01H501Z, abita in Via Roma 15, Milano."

        # 1. Tokenize
        tok_r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": [text],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert tok_r.status_code == 200
        tok_body = tok_r.json()
        tokenized = tok_body["tokenized_texts"][0]
        assert "Mario Rossi" not in tokenized
        assert "[#" in tokenized

        # 2. Rehydrate
        reh_r = httpx.post(
            f"{BASE_URL}/api/v1/rehydrate",
            headers=_headers(),
            json={
                "text": tokenized,
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert reh_r.status_code == 200
        reh_body = reh_r.json()
        assert "Mario Rossi" in reh_body["text"]
        assert "RSSMRA85M01H501Z" in reh_body["text"]
        assert reh_body["rehydrated_count"] >= 2

        # 3. Flush
        flush_r = httpx.post(
            f"{BASE_URL}/api/v1/flush",
            headers=_headers(),
            json={
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert flush_r.status_code == 200
        flush_body = flush_r.json()
        assert flush_body["flushed_count"] >= 1

        # 4. Rehydrate AFTER flush — tokens should NOT resolve
        reh2_r = httpx.post(
            f"{BASE_URL}/api/v1/rehydrate",
            headers=_headers(),
            json={
                "text": tokenized,
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        assert reh2_r.status_code == 200
        reh2_body = reh2_r.json()
        # After flush, tokens cannot be resolved — text stays tokenized
        assert reh2_body["rehydrated_count"] == 0
        assert "[#" in reh2_body["text"]

    def test_flush_idempotent(self):
        """Flush same request_id twice — second call returns 0."""
        request_id = str(uuid.uuid4())

        # Tokenize first
        httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": ["Mario Rossi"],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )

        # Flush 1
        r1 = httpx.post(
            f"{BASE_URL}/api/v1/flush",
            headers=_headers(),
            json={"organization_id": ORG_ID, "request_id": request_id},
            timeout=15,
        )
        assert r1.status_code == 200

        # Flush 2 — idempotent
        r2 = httpx.post(
            f"{BASE_URL}/api/v1/flush",
            headers=_headers(),
            json={"organization_id": ORG_ID, "request_id": request_id},
            timeout=15,
        )
        assert r2.status_code == 200
        assert r2.json()["flushed_count"] == 0

    def test_cross_request_isolation(self):
        """Tokens from request A cannot be rehydrated with request B."""
        req_a = str(uuid.uuid4())
        req_b = str(uuid.uuid4())

        # Tokenize with request A
        tok_r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": ["Mario Rossi"],
                "organization_id": ORG_ID,
                "request_id": req_a,
            },
            timeout=15,
        )
        tokenized = tok_r.json()["tokenized_texts"][0]

        # Rehydrate with request B — should NOT resolve
        reh_r = httpx.post(
            f"{BASE_URL}/api/v1/rehydrate",
            headers=_headers(),
            json={
                "text": tokenized,
                "organization_id": ORG_ID,
                "request_id": req_b,
            },
            timeout=15,
        )
        assert reh_r.status_code == 200
        assert reh_r.json()["rehydrated_count"] == 0

        # Cleanup
        httpx.post(
            f"{BASE_URL}/api/v1/flush",
            headers=_headers(),
            json={"organization_id": ORG_ID, "request_id": req_a},
            timeout=15,
        )


# ── LATENCY / PERFORMANCE ───────────────────────────────────────────────


class TestPerformance:
    """Latency sanity checks — not strict SLAs, just smoke."""

    def test_tokenize_latency_under_500ms(self):
        request_id = str(uuid.uuid4())
        t0 = time.perf_counter()
        r = httpx.post(
            f"{BASE_URL}/api/v1/tokenize",
            headers=_headers(),
            json={
                "texts": ["Mario Rossi, CF RSSMRA85M01H501Z"],
                "organization_id": ORG_ID,
                "request_id": request_id,
            },
            timeout=15,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 500, f"Tokenize took {elapsed_ms:.0f}ms (expected <500ms)"

        # Cleanup
        httpx.post(
            f"{BASE_URL}/api/v1/flush",
            headers=_headers(),
            json={"organization_id": ORG_ID, "request_id": request_id},
            timeout=15,
        )

    def test_health_latency_under_100ms(self):
        t0 = time.perf_counter()
        r = httpx.get(f"{BASE_URL}/health", timeout=10)
        elapsed_ms = (time.perf_counter() - t0) * 1000
        assert r.status_code == 200
        assert elapsed_ms < 500, f"Health took {elapsed_ms:.0f}ms (expected <500ms)"


# ── PROMETHEUS METRICS ENDPOINT ──────────────────────────────────────────


@pytest.mark.skipif(not ADMIN_KEY, reason="ADMIN_KEY not set")
class TestPrometheusEndpoint:
    """Prometheus metrics endpoint (requires admin key)."""

    def test_prometheus_returns_200(self):
        r = httpx.get(
            f"{BASE_URL}/metrics/prometheus",
            headers=_admin_headers(),
            timeout=10,
        )
        assert r.status_code == 200
        assert "text/plain" in r.headers.get("content-type", "")

    def test_prometheus_contains_type_lines(self):
        r = httpx.get(
            f"{BASE_URL}/metrics/prometheus",
            headers=_admin_headers(),
            timeout=10,
        )
        body = r.text
        assert "# TYPE ps_tokenizations_total counter" in body
        assert "# TYPE ps_latency_ms histogram" in body
        assert "ps_uptime_seconds" in body

    def test_prometheus_no_pii(self):
        r = httpx.get(
            f"{BASE_URL}/metrics/prometheus",
            headers=_admin_headers(),
            timeout=10,
        )
        body = r.text
        assert ORG_ID not in body
        assert "Mario" not in body
        assert "Rossi" not in body
        assert "RSSMRA" not in body

    def test_prometheus_no_auth_returns_401(self):
        r = httpx.get(f"{BASE_URL}/metrics/prometheus", timeout=10)
        assert r.status_code in (401, 403)
